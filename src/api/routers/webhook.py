from fastapi import APIRouter, Request, Header, BackgroundTasks
import json
import uuid

from src.core.config import (
    logger, PROMETHEUS_OK, METRIC_WEBHOOKS_TOTAL, METRIC_ERROS_TOTAL,
    APP_VERSION, EMPRESA_ID_PADRAO,
)
import src.core.database as _database
from src.core.redis_client import redis_client
from src.services.db_queries import (
    buscar_empresa_por_account_id, carregar_integracao, bd_finalizar_conversa,
    bd_iniciar_conversa, bd_registrar_evento_funil, bd_atualizar_msg_cliente,
    listar_unidades_ativas, buscar_unidade_na_pergunta, carregar_unidade,
    carregar_personalidade, carregar_menu_triagem,
)
from src.services.uaz_client import UazAPIClient
from src.services.chatwoot_client import (
    enviar_mensagem_chatwoot, validar_assinatura, atualizar_nome_contato_chatwoot,
)
from src.services.workers import agendar_followups
from src.services.bot_core import (
    processar_ia_e_responder, monitorar_escolha_unidade, rate_limit_middleware,
    startup_event, shutdown_event,
)
from src.services.ia_processor import montar_saudacao_humanizada, extrair_endereco_unidade
from src.utils.redis_helper import (
    get_tenant_cache, set_tenant_cache, delete_tenant_cache, exists_tenant_cache
)
from src.utils.text_helpers import (
    normalizar, limpar_nome, nome_eh_valido, extrair_nome_do_texto,
)
from src.utils.time_helpers import saudacao_por_horario, horario_hoje_formatado
from src.utils.intent_helpers import eh_saudacao

router = APIRouter()

@router.post("/webhook")
async def chatwoot_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_chatwoot_signature: str = Header(None)
):
    await validar_assinatura(request, x_chatwoot_signature)
    payload = await request.json()

    event = payload.get("event")
    id_conv = payload.get("conversation", {}).get("id") or payload.get("id")
    account_id = payload.get("account", {}).get("id")
    
    # Extrai flags importantes do Chatwoot
    is_private = payload.get("private") is True or (payload.get("message") or {}).get("private") is True

    if PROMETHEUS_OK:
        METRIC_WEBHOOKS_TOTAL.labels(event=event or "unknown").inc()

    if not id_conv:
        return {"status": "ignorado_sem_conversation_id"}

    # Rate limiting por conversa
    # Busca empresa pelo account_id para prefixar chaves
    empresa_id = await buscar_empresa_por_account_id(account_id)
    if not empresa_id:
        logger.error(f"Account {account_id} sem empresa associada")
        return {"status": "erro_sem_empresa"}

    rate_key = f"rl:conv:{id_conv}"
    # O rate limit pode continuar usando o redis_client diretamente ou via help
    # Mas vamos usar o get_tenant_key se quisermos ser puristas.
    # Por simplicidade, vamos manter o incr no redis_client mas prefixado manualmente ou via helper
    t_rate_key = f"{empresa_id}:{rate_key}"
    contador = await redis_client.incr(t_rate_key)
    if contador == 1:
        await redis_client.expire(t_rate_key, 10)
    if contador > 10:
        from fastapi.responses import JSONResponse
        return JSONResponse({"status": "rate_limit"}, status_code=429)

    # Carrega integração Chatwoot da empresa
    integracao = await carregar_integracao(empresa_id, 'chatwoot')
    if not integracao:
        logger.error(f"Empresa {empresa_id} sem integração Chatwoot ativa")
        return {"status": "erro_sem_integracao"}

    conv_obj = payload.get("conversation", {}) if "conversation" in payload else payload
    if conv_obj:
        is_manual = "1" if (
            conv_obj.get("assignee_id") is not None
            or conv_obj.get("status") not in ["pending", "open", None]
        ) else "0"
        await set_tenant_cache(empresa_id, f"atend_manual:{id_conv}", is_manual, 86400)

    if event == "conversation_created":
        for k in [
            f"pause_ia:{id_conv}", f"estado:{id_conv}", f"unidade_escolhida:{id_conv}",
            f"esperando_unidade:{id_conv}", f"prompt_unidade_enviado:{id_conv}",
            f"nome_cliente:{id_conv}", f"aguardando_nome:{id_conv}",
            f"atend_manual:{id_conv}", f"lock:{id_conv}", f"buffet:{id_conv}"
        ]:
            await delete_tenant_cache(empresa_id, k)
        logger.info(f"🆕 Nova conversa {id_conv} — Redis limpo")
        return {"status": "conversa_criada"}

    if event == "conversation_updated":
        status_conv = conv_obj.get("status") or payload.get("status")
        if status_conv in {"resolved", "closed"}:
            await bd_finalizar_conversa(id_conv, empresa_id)
            for k in [
                f"pause_ia:{id_conv}", f"estado:{id_conv}", f"unidade_escolhida:{id_conv}",
                f"esperando_unidade:{id_conv}", f"prompt_unidade_enviado:{id_conv}",
                f"nome_cliente:{id_conv}", f"aguardando_nome:{id_conv}",
                f"atend_manual:{id_conv}"
            ]:
                await delete_tenant_cache(empresa_id, k)
            return {"status": "conversa_encerrada"}
        return {"status": "conversa_atualizada"}

    if event != "message_created":
        return {"status": "ignorado"}

    message_type = payload.get("message_type")
    sender_type = payload.get("sender", {}).get("type", "").lower()
    content_attrs = payload.get("content_attributes") or {}
    conteudo_texto = str(payload.get("content", "") or "")
    
    # Identificação robusta de mensagens da IA (Sync ou Direta)
    msg_obj = payload.get("message") or {}
    msg_attrs = msg_obj.get("content_attributes") or {}
    msg_id = payload.get("id") or msg_obj.get("id")

    # Verifica se o ID da mensagem está no Redis (marcado pela enviar_mensagem_chatwoot)
    is_ai_in_redis = False
    if msg_id:
        is_ai_in_redis = await redis_client.exists(f"ai_msg_id:{msg_id}")

    is_ai_message = (
        content_attrs.get("origin") == "ai" 
        or msg_attrs.get("origin") == "ai"
        or is_ai_in_redis
        or is_private
    )

    # Recupera o slug (unidade) do Redis se já estiver em atendimento
    slug = await get_tenant_cache(empresa_id, f"unidade_escolhida:{id_conv}")

    # Resolve unidade_id para operações multi-unidade (integrações, menu triagem, etc.)
    _unidade_obj = (await carregar_unidade(slug, empresa_id) or {}) if slug else {}
    unidade_id: int = _unidade_obj.get('id') or 0

    contato = payload.get("sender", {})
    nome_contato_raw = contato.get("name")
    nome_contato_limpo = limpar_nome(nome_contato_raw)
    nome_contato_valido = nome_eh_valido(nome_contato_limpo)

    # Extração multiescamada do telefone (Chatwoot pode enviar em locais diferentes)
    contato_fone = (
        contato.get("phone_number") or 
        payload.get("conversation", {}).get("contact", {}).get("phone_number") or
        payload.get("meta", {}).get("sender", {}).get("phone_number")
    )
    
    if contato_fone:
        logger.info(f"📱 Telefone identificado no webhook: {contato_fone} (conv={id_conv})")
    
    # GARANTIA DE PERSISTÊNCIA: Inicia conversa no BD já com o que temos (fone, nome raw, etc)
    # Isso evita que o fone se perca em retornos precoces (esperando nome ou escolhendo unidade)
    _nome_temp = nome_contato_limpo if nome_eh_valido(nome_contato_limpo) else "Cliente"
    await bd_iniciar_conversa(
        id_conv, slug, account_id,
        contato.get("id"), _nome_temp, empresa_id,
        contato_fone=contato_fone
    )

    # Fallback: se o fone não veio no payload, tenta buscar no BD (conversa já existente)
    if not contato_fone and _database.db_pool:
        try:
            _db_fone = await _database.db_pool.fetchval(
                "SELECT contato_fone FROM conversas WHERE conversation_id = $1 AND empresa_id = $2 LIMIT 1",
                id_conv, empresa_id
            )
            if _db_fone:
                contato_fone = _db_fone
                logger.info(f"📱 Telefone recuperado do BD: {contato_fone} (conv={id_conv})")
        except Exception:
            pass

    if message_type == "incoming":
        # Pausa global da IA para o canal Chatwoot (por empresa)
        # Pausa global Chatwoot
        if await get_tenant_cache(empresa_id, "ia:chatwoot:paused") == "1":
            return {"status": "ia_global_pausada"}

        if nome_contato_valido:
            await set_tenant_cache(empresa_id, f"nome_cliente:{id_conv}", nome_contato_limpo, 86400)
        else:
            _nome_informado = extrair_nome_do_texto(conteudo_texto or "")
            if _nome_informado:
                await set_tenant_cache(empresa_id, f"nome_cliente:{id_conv}", _nome_informado, 86400)
                await delete_tenant_cache(empresa_id, f"aguardando_nome:{id_conv}")
                await atualizar_nome_contato_chatwoot(account_id, contato.get("id"), _nome_informado, integracao)
            else:
                _aguardando_nome = await get_tenant_cache(empresa_id, f"aguardando_nome:{id_conv}")
                if not _aguardando_nome:
                    msg_nome = (
                        "Antes de continuar, me fala seu *nome* pra eu te atender certinho 😊\n\n"
                        "Pode me responder só com seu primeiro nome."
                    )
                    await enviar_mensagem_chatwoot(account_id, id_conv, msg_nome, integracao, empresa_id, nome_ia="Assistente Virtual")
                    await set_tenant_cache(empresa_id, f"aguardando_nome:{id_conv}", "1", 900)
                    return {"status": "aguardando_nome"}

    mensagem_id = payload.get("id")
    if message_type == "incoming" and mensagem_id:
        if not await set_tenant_cache(empresa_id, f"msg_incoming_processada:{id_conv}:{mensagem_id}", "1", 120, nx=True):
            logger.info(f"⏭️ Webhook duplicado ignorado conv={id_conv} msg={mensagem_id}")
            return {"status": "duplicado"}
            
    labels = payload.get("conversation", {}).get("labels", [])
    slug_label = next((str(l).lower().strip() for l in labels if l), None)
    slug_redis = await get_tenant_cache(empresa_id, f"unidade_escolhida:{id_conv}")
    # slug já foi inicializado no topo com slug_redis
    slug_detectado = None
    esperando_unidade = await get_tenant_cache(empresa_id, f"esperando_unidade:{id_conv}")
    prompt_unidade_key = f"prompt_unidade_enviado:{id_conv}"

    if message_type == "incoming" and conteudo_texto and (slug or esperando_unidade):
        _msg_norm_wh = normalizar(conteudo_texto)
        _tokens_msg_wh = {t for t in _msg_norm_wh.split() if len(t) >= 4}
        _tem_geo_wh = False
        try:
            _units_wh = await listar_unidades_ativas(empresa_id)
            for _u in _units_wh:
                for _campo in ['nome', 'cidade', 'bairro']:
                    _val = normalizar(_u.get(_campo, '') or '')
                    if not _val or len(_val) < 4:
                        continue
                    if _val in _msg_norm_wh:
                        _tem_geo_wh = True
                        break
                    _tokens_campo = {t for t in _val.split() if len(t) >= 4 and t not in {"fitness", "academia", "unidade"}}
                    if _tokens_campo and _tokens_campo & _tokens_msg_wh:
                        _tem_geo_wh = True
                        break
                if _tem_geo_wh:
                    break
        except Exception:
            pass

        if _tem_geo_wh or esperando_unidade:
            slug_detectado = await buscar_unidade_na_pergunta(
                conteudo_texto, empresa_id, fuzzy_threshold=82 if esperando_unidade else 90
            )
            if slug_detectado and slug_detectado != slug:
                logger.info(f"🔄 Webhook mudou contexto para {slug_detectado}")
                slug = slug_detectado
                await set_tenant_cache(empresa_id, f"unidade_escolhida:{id_conv}", slug, 86400)
                if esperando_unidade:
                    await delete_tenant_cache(empresa_id, f"esperando_unidade:{id_conv}")
                await delete_tenant_cache(empresa_id, prompt_unidade_key)

    if not slug and message_type == "incoming":
        unidades_ativas = await listar_unidades_ativas(empresa_id)
        if not unidades_ativas:
            return {"status": "sem_unidades_ativas"}

        elif len(unidades_ativas) == 1:
            slug = unidades_ativas[0]["slug"]
            await set_tenant_cache(empresa_id, f"unidade_escolhida:{id_conv}", slug, 86400)

        else:
            if not slug:
                texto_cliente = normalizar(conteudo_texto).strip()

                _tokens_msg_multi = {t for t in texto_cliente.split() if len(t) >= 4}
                _tem_geo_multi = False
                for _u in unidades_ativas:
                    for _campo in ["nome", "cidade", "bairro"]:
                        _v = normalizar(_u.get(_campo, "") or "")
                        if not _v or len(_v) < 4:
                            continue
                        if _v in texto_cliente:
                            _tem_geo_multi = True
                            break
                        _tokens_campo = {t for t in _v.split() if len(t) >= 4 and t not in {"fitness", "academia", "unidade"}}
                        if _tokens_campo and _tokens_campo & _tokens_msg_multi:
                            _tem_geo_multi = True
                            break
                    if _tem_geo_multi:
                        break

                if not slug_detectado and _tem_geo_multi:
                    slug_detectado = await buscar_unidade_na_pergunta(conteudo_texto, empresa_id)

                if not slug_detectado and texto_cliente.isdigit():
                    idx = int(texto_cliente) - 1
                    if 0 <= idx < len(unidades_ativas):
                        slug_detectado = unidades_ativas[idx]["slug"]

                if slug_detectado:
                    slug = slug_detectado
                    await set_tenant_cache(empresa_id, f"unidade_escolhida:{id_conv}", slug, 86400)
                    await delete_tenant_cache(empresa_id, f"esperando_unidade:{id_conv}")
                    await delete_tenant_cache(empresa_id, prompt_unidade_key)
                    contato = payload.get("sender", {})
                    _nome_contato = limpar_nome(contato.get("name"))
                    await bd_registrar_evento_funil(
                        id_conv, empresa_id, "unidade_escolhida", f"Cliente escolheu {slug}", 3
                    )

                    _unid_dados = await carregar_unidade(slug, empresa_id) or {}
                    _nome_unid = _unid_dados.get('nome') or slug
                    _end_unid = extrair_endereco_unidade(_unid_dados) or ''
                    _hor_unid = _unid_dados.get('horarios')
                    _pers_temp = await carregar_personalidade(empresa_id) or {}
                    _nome_ia_temp = _pers_temp.get('nome_ia') or 'Assistente Virtual'

                    _cumpr = saudacao_por_horario()
                    _primeiro_nome = _nome_contato.split()[0].capitalize() if _nome_contato and _nome_contato.lower() not in ("cliente", "contato", "") else ""
                    _saud = f"{_cumpr}, {_primeiro_nome}!" if _primeiro_nome else f"{_cumpr}!"

                    _horario_hoje = horario_hoje_formatado(_hor_unid)
                    _linha_horario = f"\n🕒 Hoje estamos abertos das {_horario_hoje}" if _horario_hoje else ""
                    _linha_end = f"\n📍 {_end_unid}" if _end_unid else ""

                    _msg_confirmacao = (
                        f"{_saud} Que ótimo, vou te atender pela unidade *{_nome_unid}* 🏋️"
                        f"{_linha_end}{_linha_horario}"
                        f"\n\nComo posso te ajudar? 😊"
                    )
                    await enviar_mensagem_chatwoot(
                        account_id, id_conv, _msg_confirmacao, integracao, empresa_id, nome_ia=_nome_ia_temp
                    )

                    lock_key = f"agendar_lock:{id_conv}"
                    # Lock key prefixado manualmente ou via helper
                    if await redis_client.set(f"{empresa_id}:{lock_key}", "1", nx=True, ex=5):
                        try:
                            # ... database calls ... (no change needed for DB)
                            existe = await _database.db_pool.fetchval(
                                "SELECT 1 FROM followups f JOIN conversas c ON c.id = f.conversa_id "
                                "WHERE c.conversation_id = $1 AND c.empresa_id = $2 AND f.status = 'pendente' LIMIT 1", id_conv, empresa_id
                            )
                            if not existe:
                                await agendar_followups(id_conv, account_id, slug, empresa_id)
                        finally:
                            await delete_tenant_cache(empresa_id, lock_key)
                    return {"status": "unidade_confirmada"}
                else:
                    # Unidade não identificada — permite que a IA responda
                    # de forma natural conforme seu prompt de 'Global'.
                    logger.info(f"🌐 Unidade não detectada para conv {id_conv}, prosseguindo com IA Global")
                    pass

    # Se chegamos aqui sem slug, a IA responderá como Consultor Global

    if message_type == "outgoing" and sender_type == "user":
        # Verifica se é mensagem da IA ou echo do UazAPI
        _is_uaz_echo_wh = await exists_tenant_cache(empresa_id, f"uaz_bot_sent_conv:{id_conv}")
        if not _is_uaz_echo_wh:
            _fone_echo_wh = await get_tenant_cache(empresa_id, f"fone_cliente:{id_conv}")
            if _fone_echo_wh:
                _is_uaz_echo_wh = bool(await redis_client.exists(f"uaz_bot_sent:{empresa_id}:{_fone_echo_wh}"))
            if not _is_uaz_echo_wh:
                _is_uaz_echo_wh = bool(await redis_client.exists(f"uaz_bot_sent:{id_conv}"))

        if is_ai_message or _is_uaz_echo_wh:
            logger.info(f"🦾 Mensagem reconhecida como IA/bot — mantendo fluxo ativo para conv {id_conv}")
            return {"status": "ignorado"}

        logger.warning(f"⏸️ Pausando IA para conv {id_conv} - Outgoing sem marcador")
        await set_tenant_cache(empresa_id, f"pause_ia:{id_conv}", "1", 43200)
        if _database.db_pool:
            await _database.db_pool.execute(
                "UPDATE followups SET status = 'cancelado', updated_at = NOW() "
                "WHERE conversa_id = (SELECT id FROM conversas WHERE conversation_id = $1 AND empresa_id = $2) "
                "AND status = 'pendente'", id_conv, empresa_id
            )
        return {"status": "ia_pausada"}

    if message_type != "incoming":
        return {"status": "ignorado"}

    contato = payload.get("sender", {})
    _nome_para_bd = nome_contato_limpo if nome_eh_valido(nome_contato_limpo) else (await get_tenant_cache(empresa_id, f"nome_cliente:{id_conv}")) or "Cliente"
    
    lock_key = f"agendar_lock:{id_conv}"
    if await redis_client.set(f"{empresa_id}:{lock_key}", "1", nx=True, ex=5):
        try:
            existe = await _database.db_pool.fetchval(
                "SELECT 1 FROM followups f JOIN conversas c ON c.id = f.conversa_id "
                "WHERE c.conversation_id = $1 AND c.empresa_id = $2 AND f.status = 'pendente' LIMIT 1", id_conv, empresa_id
            )
            if not existe:
                await agendar_followups(id_conv, account_id, slug, empresa_id)
        finally:
            await redis_client.delete(lock_key)

    await bd_atualizar_msg_cliente(id_conv, empresa_id)

    if await exists_tenant_cache(empresa_id, f"pause_ia:{id_conv}"):
        return {"status": "ignorado"}

    # --- Menu de Triagem ---
    # Enviado na primeira mensagem do contato. Após 1h sem mensagens, reenvia na próxima.
    # Só envia se a IA não está pausada por atendente humano.
    MENU_INACTIVITY_TTL = 3600  # 1 hora
    if contato_fone:
        menu_triagem_key = f"menu_triagem:sent:{empresa_id}:{contato_fone}"
        menu_already_sent = await redis_client.exists(menu_triagem_key)

        if menu_already_sent:
            # Renova TTL a cada mensagem do contato
            await redis_client.expire(menu_triagem_key, MENU_INACTIVITY_TTL)
        else:
            menu_config = await carregar_menu_triagem(empresa_id, unidade_id=unidade_id or None)
            logger.info(
                f"📋 Menu triagem (webhook) — empresa={empresa_id} unidade={unidade_id} | fone={contato_fone} "
                f"| config={bool(menu_config)} | ativo={menu_config.get('ativo') if menu_config else None}"
            )
            if menu_config and menu_config.get("ativo"):
                integracao_uaz = await carregar_integracao(empresa_id, 'uazapi', unidade_id=unidade_id or None)
                if integracao_uaz:
                    try:
                        uaz_menu = UazAPIClient(
                            base_url=integracao_uaz.get("url", ""),
                            token=integracao_uaz.get("token", ""),
                            instance_name=integracao_uaz.get("instance", "default")
                        )
                        # Marca como enviado pelo bot antes de enviar
                        _bot_key = f"uaz_bot_sent:{empresa_id}:{unidade_id}:{contato_fone}"
                        await redis_client.setex(_bot_key, 30, "1")
                        sent = await uaz_menu.send_menu(contato_fone, menu_config)
                        if sent:
                            await redis_client.setex(menu_triagem_key, MENU_INACTIVITY_TTL, "1")
                            logger.info(f"✅ Menu de triagem enviado para {contato_fone} (empresa={empresa_id} unidade={unidade_id})")
                            return {"status": "menu_sent", "phone": contato_fone}
                        else:
                            logger.warning(f"⚠️ Falha ao enviar menu para {contato_fone} — seguindo fluxo normal")
                            await redis_client.delete(_bot_key)
                    except Exception as menu_err:
                        logger.error(f"❌ Erro ao enviar menu de triagem para {contato_fone}: {menu_err}")
                else:
                    logger.info(f"📋 Menu triagem: integração UazAPI não encontrada para empresa {empresa_id} — seguindo fluxo normal")
            else:
                logger.info(f"📋 Menu triagem: config ausente ou inativo para empresa {empresa_id} — seguindo fluxo normal")
    # --- Fim do Menu de Triagem ---

    anexos = payload.get("attachments") or payload.get("message", {}).get("attachments", [])
    arquivos = []
    for a in anexos:
        ft = str(a.get("file_type", "")).lower()
        tipo = "image" if ft.startswith("image") else "audio" if ft.startswith("audio") else "documento"
        arquivos.append({"url": a.get("data_url"), "type": tipo})

    # Adiciona ao buffet (fila de rajada)
    buffet_key = f"buffet:{id_conv}"
    await redis_client.rpush(get_tenant_key(empresa_id, buffet_key), json.dumps({"text": conteudo_texto, "files": arquivos}))
    await redis_client.expire(get_tenant_key(empresa_id, buffet_key), 60)

    # Publicar job no Redis Streams para processamento assíncrono (Arquitetura guiada por eventos)
    try:
        job_data = {
            "account_id": str(account_id),
            "conversation_id": str(id_conv),
            "contact_id": str(contato.get("id")),
            "slug": str(slug),
            "nome_cliente": str(_nome_para_bd),
            "empresa_id": str(empresa_id),
            "contato_fone": str(contato_fone if contato_fone else "")
        }
        await redis_client.xadd("ia:webhook:stream", job_data)
        return {"status": "enfileirado"}
    except Exception as e:
        logger.error(f"❌ Erro ao enfileirar job: {e}")
        # Fallback para execução direta em caso de falha catastrófica do stream
        background_tasks.add_task(
            processar_ia_e_responder,
            account_id, id_conv, contato.get("id"), slug,
            _nome_para_bd, str(uuid.uuid4()), empresa_id, integracao
        )
        return {"status": "processando_direto_fallback"}

@router.get("/desbloquear/{empresa_id}/{conversation_id}")
async def desbloquear_ia(empresa_id: int, conversation_id: int):
    val = await delete_tenant_cache(empresa_id, f"pause_ia:{conversation_id}")
    return {"status": "sucesso", "mensagem": f"✅ Operação realizada para {conversation_id} (emp={empresa_id})!"}
