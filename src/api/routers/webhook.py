from fastapi import APIRouter, Request, Header, BackgroundTasks
import json
import uuid

# Importações globais extraídas do core
from src.services.bot_core import *

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

    if _PROMETHEUS_OK:
        METRIC_WEBHOOKS_TOTAL.labels(event=event or "unknown").inc()

    if not id_conv:
        return {"status": "ignorado_sem_conversation_id"}

    # Rate limiting por conversa
    rate_key = f"rl:conv:{id_conv}"
    contador = await redis_client.incr(rate_key)
    if contador == 1:
        await redis_client.expire(rate_key, 10)
    if contador > 10:
        from fastapi.responses import JSONResponse
        return JSONResponse({"status": "rate_limit"}, status_code=429)

    # Busca empresa pelo account_id
    empresa_id = await buscar_empresa_por_account_id(account_id)
    if not empresa_id:
        logger.error(f"Account {account_id} sem empresa associada")
        return {"status": "erro_sem_empresa"}

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
        await redis_client.setex(f"atend_manual:{id_conv}", 86400, is_manual)

    if event == "conversation_created":
        await redis_client.delete(
            f"pause_ia:{id_conv}", f"estado:{id_conv}",
            f"unidade_escolhida:{id_conv}", f"esperando_unidade:{id_conv}",
            f"prompt_unidade_enviado:{id_conv}", f"nome_cliente:{id_conv}", f"aguardando_nome:{id_conv}",
            f"atend_manual:{id_conv}", f"lock:{id_conv}", f"buffet:{id_conv}"
        )
        logger.info(f"🆕 Nova conversa {id_conv} — Redis limpo")
        return {"status": "conversa_criada"}

    if event == "conversation_updated":
        status_conv = conv_obj.get("status") or payload.get("status")
        if status_conv in {"resolved", "closed"}:
            await bd_finalizar_conversa(id_conv)
            await redis_client.delete(
                f"pause_ia:{id_conv}", f"estado:{id_conv}",
                f"unidade_escolhida:{id_conv}", f"esperando_unidade:{id_conv}",
                f"prompt_unidade_enviado:{id_conv}", f"nome_cliente:{id_conv}", f"aguardando_nome:{id_conv}",
                f"atend_manual:{id_conv}"
            )
            return {"status": "conversa_encerrada"}
        return {"status": "conversa_atualizada"}

    if event != "message_created":
        return {"status": "ignorado"}

    message_type = payload.get("message_type")
    sender_type = payload.get("sender", {}).get("type", "").lower()
    content_attrs = payload.get("content_attributes") or {}
    is_ai_message = content_attrs.get("origin") == "ai"
    conteudo_texto = payload.get("content", "")

    contato = payload.get("sender", {})
    nome_contato_raw = contato.get("name")
    nome_contato_limpo = limpar_nome(nome_contato_raw)
    nome_contato_valido = nome_eh_valido(nome_contato_limpo)

    if message_type == "incoming":
        if nome_contato_valido:
            await redis_client.setex(f"nome_cliente:{id_conv}", 86400, nome_contato_limpo)
        else:
            _nome_informado = extrair_nome_do_texto(conteudo_texto or "")
            if _nome_informado:
                await redis_client.setex(f"nome_cliente:{id_conv}", 86400, _nome_informado)
                await redis_client.delete(f"aguardando_nome:{id_conv}")
                await atualizar_nome_contato_chatwoot(account_id, contato.get("id"), _nome_informado, integracao)
            else:
                _aguardando_nome = await redis_client.get(f"aguardando_nome:{id_conv}")
                if not _aguardando_nome:
                    msg_nome = (
                        "Antes de continuar, me fala seu *nome* pra eu te atender certinho 😊\n\n"
                        "Pode me responder só com seu primeiro nome."
                    )
                    await enviar_mensagem_chatwoot(account_id, id_conv, msg_nome, "Assistente Virtual", integracao)
                    await redis_client.setex(f"aguardando_nome:{id_conv}", 900, "1")
                    return {"status": "aguardando_nome"}

    mensagem_id = payload.get("id")
    if message_type == "incoming" and mensagem_id:
        dedup_key = f"msg_incoming_processada:{id_conv}:{mensagem_id}"
        if not await redis_client.set(dedup_key, "1", nx=True, ex=120):
            logger.info(f"⏭️ Webhook duplicado ignorado conv={id_conv} msg={mensagem_id}")
            return {"status": "duplicado"}
            
    labels = payload.get("conversation", {}).get("labels", [])
    slug_label = next((str(l).lower().strip() for l in labels if l), None)
    slug_redis = await redis_client.get(f"unidade_escolhida:{id_conv}")
    slug = slug_redis
    slug_detectado = None
    esperando_unidade = await redis_client.get(f"esperando_unidade:{id_conv}")
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
                await redis_client.setex(f"unidade_escolhida:{id_conv}", 86400, slug)
                if esperando_unidade:
                    await redis_client.delete(f"esperando_unidade:{id_conv}")
                await redis_client.delete(prompt_unidade_key)

    if not slug and message_type == "incoming":
        unidades_ativas = await listar_unidades_ativas(empresa_id)
        if not unidades_ativas:
            return {"status": "sem_unidades_ativas"}

        elif len(unidades_ativas) == 1:
            slug = unidades_ativas[0]["slug"]
            await redis_client.setex(f"unidade_escolhida:{id_conv}", 86400, slug)

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
                    await redis_client.setex(f"unidade_escolhida:{id_conv}", 86400, slug)
                    await redis_client.delete(f"esperando_unidade:{id_conv}")
                    await redis_client.delete(prompt_unidade_key)
                    contato = payload.get("sender", {})
                    _nome_contato = limpar_nome(contato.get("name"))
                    await bd_iniciar_conversa(
                        id_conv, slug, account_id,
                        contato.get("id"), _nome_contato, empresa_id
                    )
                    await bd_registrar_evento_funil(
                        id_conv, "unidade_escolhida", f"Cliente escolheu {slug}", 3
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
                        account_id, id_conv, _msg_confirmacao, _nome_ia_temp, integracao
                    )

                    lock_key = f"agendar_lock:{id_conv}"
                    if await redis_client.set(lock_key, "1", nx=True, ex=5):
                        try:
                            existe = await db_pool.fetchval(
                                "SELECT 1 FROM followups f JOIN conversas c ON c.id = f.conversa_id "
                                "WHERE c.conversation_id = $1 AND f.status = 'pendente' LIMIT 1", id_conv
                            )
                            if not existe:
                                await agendar_followups(id_conv, account_id, slug, empresa_id)
                        finally:
                            await redis_client.delete(lock_key)
                    return {"status": "unidade_confirmada"}
                else:
                    if esperando_unidade or await redis_client.get(prompt_unidade_key) == "1":
                        throttle_key = f"esperando_unidade_throttle:{id_conv}"
                        if not await redis_client.get(throttle_key):
                            msg_retry = (
                                "Ainda não consegui localizar a unidade certinha 😅\n\n"
                                "Me manda um *bairro*, *cidade* ou o *nome da unidade* (ex.: Ricardo Jafet)."
                            )
                            await enviar_mensagem_chatwoot(account_id, id_conv, msg_retry, "Assistente Virtual", integracao)
                            await redis_client.setex(throttle_key, 30, "1")
                        return {"status": "aguardando_escolha_unidade"}

                    _qtd_unidades = len(unidades_ativas)
                    msg = (
                        "Boa pergunta! Somos sim a Red Fitness 💪\n\n"
                        f"Hoje temos *{_qtd_unidades} unidades* e quero te direcionar para a certa.\n"
                        "Me diz sua *cidade*, *bairro* ou o *nome da unidade* que você prefere."
                    )
                    await enviar_mensagem_chatwoot(account_id, id_conv, msg, "Assistente Virtual", integracao)
                    await redis_client.setex(f"esperando_unidade:{id_conv}", 86400, "1")
                    await redis_client.setex(prompt_unidade_key, 600, "1")
                    background_tasks.add_task(monitorar_escolha_unidade, account_id, id_conv, empresa_id)
                    return {"status": "aguardando_escolha_unidade"}

    if not slug:
        return {"status": "erro_sem_unidade"}

    if message_type == "outgoing" and sender_type == "user":
        if is_ai_message:
            return {"status": "ignorado"}
        await redis_client.setex(f"pause_ia:{id_conv}", 43200, "1")
        if db_pool:
            await db_pool.execute(
                "UPDATE followups SET status = 'cancelado' "
                "WHERE conversa_id = (SELECT id FROM conversas WHERE conversation_id = $1) "
                "AND status = 'pendente'", id_conv
            )
        return {"status": "ia_pausada"}

    if message_type != "incoming":
        return {"status": "ignorado"}

    contato = payload.get("sender", {})
    _nome_para_bd = nome_contato_limpo if nome_eh_valido(nome_contato_limpo) else (await redis_client.get(f"nome_cliente:{id_conv}")) or "Cliente"
    await bd_iniciar_conversa(
        id_conv, slug, account_id,
        contato.get("id"), _nome_para_bd, empresa_id
    )

    lock_key = f"agendar_lock:{id_conv}"
    if await redis_client.set(lock_key, "1", nx=True, ex=5):
        try:
            existe = await db_pool.fetchval(
                "SELECT 1 FROM followups f JOIN conversas c ON c.id = f.conversa_id "
                "WHERE c.conversation_id = $1 AND f.status = 'pendente' LIMIT 1", id_conv
            )
            if not existe:
                await agendar_followups(id_conv, account_id, slug, empresa_id)
        finally:
            await redis_client.delete(lock_key)

    await bd_atualizar_msg_cliente(id_conv)

    if await redis_client.exists(f"pause_ia:{id_conv}"):
        return {"status": "ignorado"}

    anexos = payload.get("attachments") or payload.get("message", {}).get("attachments", [])
    arquivos = []
    for a in anexos:
        ft = str(a.get("file_type", "")).lower()
        tipo = "image" if ft.startswith("image") else "audio" if ft.startswith("audio") else "documento"
        arquivos.append({"url": a.get("data_url"), "type": tipo})

    await redis_client.rpush(
        f"buffet:{id_conv}",
        json.dumps({"text": conteudo_texto, "files": arquivos})
    )
    await redis_client.expire(f"buffet:{id_conv}", 60)

    lock_val = str(uuid.uuid4())
    if await redis_client.set(f"lock:{id_conv}", lock_val, nx=True, ex=180):
        background_tasks.add_task(
            processar_ia_e_responder,
            account_id, id_conv, contato.get("id"), slug,
            _nome_para_bd, lock_val, empresa_id, integracao
        )
        return {"status": "processando"}

    return {"status": "acumulando_no_buffet"}

@router.get("/desbloquear/{conversation_id}")
async def desbloquear_ia(conversation_id: int):
    if await redis_client.delete(f"pause_ia:{conversation_id}"):
        return {"status": "sucesso", "mensagem": f"✅ IA reativada para {conversation_id}!"}
    return {"status": "aviso", "mensagem": f"A conversa {conversation_id} não estava pausada."}
