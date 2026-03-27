import uuid
import json
import asyncio
import httpx
from fastapi import APIRouter, Request, Header, HTTPException, BackgroundTasks
from src.core.config import logger, REDIS_URL, EMPRESA_ID_PADRAO
from src.core.redis_client import redis_client
from src.services.db_queries import buscar_empresa_por_account_id, buscar_conversa_por_fone, carregar_integracao, carregar_menu_triagem, carregar_fluxo_triagem
from src.services.flow_executor import executar_fluxo
from src.services.uaz_client import UazAPIClient

router = APIRouter()

@router.post("/uazapi/{empresa_id}")
async def uazapi_webhook(
    empresa_id: int,
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    Recebe webhooks da UazAPI.
    Estrutura esperada: messages.upsert
    """
    # Carrega integração UazAPI da empresa para validar se está ativa
    integracao = await carregar_integracao(empresa_id, 'uazapi')
    if not integracao:
        logger.warning(f"⚠️ Webhook UazAPI recebido para empresa {empresa_id}, mas integração não está ativa no DB.")
        return {"status": "ignored", "reason": "integration_not_active"}

    try:
        body = await request.json()
        event = body.get("event")

        # Só processamos novas mensagens recebidas
        if event != "messages.upsert":
            return {"status": "ignored", "event": event}

        data = body.get("data", {})
        message = data.get("message", {})
        key = message.get("key", {})
        remote_jid = key.get("remoteJid", "")

        if not remote_jid or ("@s.whatsapp.net" not in remote_jid and "@g.us" not in remote_jid):
            return {"status": "ignored", "reason": "not_supported_jid"}

        phone = remote_jid.split("@")[0]

        # fromMe=true pode ser o BOT (via API) ou um ATENDENTE HUMANO (via WhatsApp)
        if key.get("fromMe"):
            bot_sent_key = f"uaz_bot_sent:{empresa_id}:{phone}"
            if await redis_client.exists(bot_sent_key):
                # É o próprio bot — ignora sem pausar
                await redis_client.delete(bot_sent_key)
                return {"status": "ignored", "reason": "from_me_bot"}
            else:
                # É um atendente humano enviando manualmente — pausa a IA
                conversa_humana = await buscar_conversa_por_fone(phone, empresa_id)
                if conversa_humana:
                    conv_id_humano = conversa_humana.get("conversation_id")
                    await redis_client.setex(f"pause_ia:{empresa_id}:{conv_id_humano}", 43200, "1")
                    logger.info(f"⏸️ IA pausada por atendente humano (UazAPI) — fone: {phone} conv: {conv_id_humano}")
                return {"status": "ignored", "reason": "from_me_human"}

        # Extrair conteúdo (texto, legenda ou seleção de menu interativo)
        msg_payload = message.get("message", {})

        conversation  = msg_payload.get("conversation")
        extended      = msg_payload.get("extendedTextMessage", {}).get("text")
        image_caption = msg_payload.get("imageMessage", {}).get("caption")
        video_caption = msg_payload.get("videoMessage", {}).get("caption")

        # Áudio (PTT ou arquivo de áudio)
        audio_msg = msg_payload.get("audioMessage") or msg_payload.get("pttMessage")
        has_audio = bool(audio_msg)

        # Seleção de lista interativa (type=list)
        list_reply    = msg_payload.get("listResponseMessage", {})
        list_title    = list_reply.get("title", "") or list_reply.get("singleSelectReply", {}).get("selectedRowId", "")

        # Seleção de botão (type=button)
        btn_reply     = msg_payload.get("buttonsResponseMessage", {})
        btn_text      = btn_reply.get("selectedDisplayText", "") or btn_reply.get("selectedButtonId", "")

        # Se é uma resposta de menu, prefixamos para a IA entender o contexto
        is_menu_reply = bool(list_reply or btn_reply)
        raw_selection = list_title or btn_text

        if is_menu_reply and raw_selection:
            content = f"[Selecionou no menu]: {raw_selection}"
        else:
            content = conversation or extended or image_caption or video_caption or ""

        if not content and not has_audio:
            return {"status": "ignored", "reason": "empty_content"}

        # Placeholder para áudio sem texto — será substituído pela transcrição
        if not content and has_audio:
            content = "[Áudio recebido]"

        # Buscar se já existe uma conversa interna para este telefone
        conversa_existente = await buscar_conversa_por_fone(phone, empresa_id)

        # --- Fluxo Visual de Triagem (n8n-style) ---
        # Verificar se há fluxo ativo ANTES do menu simples legado.
        # Se o fluxo tratar a mensagem, retorna imediatamente.
        _fluxo_config = await carregar_fluxo_triagem(empresa_id)
        logger.debug(f"[FluxoTriagem] Config para empresa {empresa_id}: ativo={_fluxo_config.get('ativo') if _fluxo_config else 'None'}")
        
        if _fluxo_config and _fluxo_config.get("ativo"):
            _ia_pausada_fluxo = False
            if conversa_existente:
                _conv_id_f = conversa_existente.get("conversation_id")
                if _conv_id_f:
                    _ia_pausada_fluxo = bool(await redis_client.exists(f"pause_ia:{empresa_id}:{_conv_id_f}"))
            _phone_paused = bool(await redis_client.exists(f"pause_ia_phone:{empresa_id}:{phone}"))
            
            logger.debug(f"[FluxoTriagem] IA Pausada: {_ia_pausada_fluxo}, Phone Paused: {_phone_paused}")
            
            if not _ia_pausada_fluxo and not _phone_paused:
                _uaz_fluxo = UazAPIClient(
                    base_url=integracao.get("url") or integracao.get("api_url") or "",
                    token=integracao.get("token", ""),
                    instance_name=integracao.get("instance", "default")
                )
                try:
                    _fluxo_tratou = await executar_fluxo(empresa_id, phone, content, _fluxo_config, _uaz_fluxo)
                    if _fluxo_tratou:
                        logger.info(f"✅ [FluxoTriagem] Mensagem de {phone} tratada pelo fluxo visual (empresa {empresa_id})")
                        return {"status": "flow_handled", "phone": phone}
                except Exception as _fe:
                    logger.error(f"❌ [FluxoTriagem] Erro ao executar fluxo para {phone}: {_fe}")

        # --- Menu de Triagem (legado) ---
        # Lógica de inatividade: a chave Redis expira após 1h sem mensagens do contato.
        # A cada mensagem recebida, o TTL é renovado. Se o contato ficar 1h sem mandar
        # mensagem, a chave expira e o menu será reenviado na próxima mensagem.
        MENU_INACTIVITY_TTL = 3600  # 1 hora
        menu_triagem_key = f"menu_triagem:sent:{empresa_id}:{phone}"
        menu_already_sent = await redis_client.exists(menu_triagem_key)

        if menu_already_sent:
            # Renova o TTL a cada mensagem — só envia de novo após 1h de inatividade
            await redis_client.expire(menu_triagem_key, MENU_INACTIVITY_TTL)

        if not menu_already_sent:
            # Verifica se a IA está pausada para esta conversa
            ia_pausada = False
            if conversa_existente:
                conv_id_existente = conversa_existente.get("conversation_id")
                if conv_id_existente:
                    ia_pausada = bool(await redis_client.exists(f"pause_ia:{empresa_id}:{conv_id_existente}"))

            if ia_pausada:
                logger.info(f"⏸️ Menu de triagem: IA pausada por atendente para {phone}, menu não enviado")
            else:
                menu_config = await carregar_menu_triagem(empresa_id)
                logger.info(f"📋 Menu triagem — empresa {empresa_id} | fone {phone} | config={bool(menu_config)} | ativo={menu_config.get('ativo') if menu_config else None}")
                if menu_config and menu_config.get("ativo"):
                    try:
                        uaz_menu = UazAPIClient(
                            base_url=integracao.get("url") or integracao.get("api_url") or "",
                            token=integracao.get("token", ""),
                            instance_name=integracao.get("instance", "default")
                        )
                        # Marca como enviado pelo bot antes de enviar (para fromMe handler ignorar)
                        await redis_client.setex(f"uaz_bot_sent:{empresa_id}:{phone}", 30, "1")
                        sent = await uaz_menu.send_menu(phone, menu_config)
                        if sent:
                            # TTL de 1h: não envia o menu novamente neste período
                            await redis_client.setex(menu_triagem_key, MENU_INACTIVITY_TTL, "1")
                            logger.info(f"✅ Menu de triagem enviado para {phone} (empresa {empresa_id})")
                            return {"status": "menu_sent", "phone": phone}
                        else:
                            logger.warning(f"⚠️ Falha ao enviar menu para {phone} — UazAPI retornou erro, seguindo fluxo normal")
                            await redis_client.delete(f"uaz_bot_sent:{empresa_id}:{phone}")
                    except Exception as menu_err:
                        logger.error(f"❌ Erro ao enviar menu de triagem para {phone}: {menu_err}")
                else:
                    logger.info(f"📋 Menu triagem: config ausente ou inativo para empresa {empresa_id} — seguindo fluxo normal")

        # --- Fim do Menu de Triagem ---

        # --- Transcrição de Áudio ---
        if has_audio and conversa_existente:
            audio_url = None
            _conv_id_audio = conversa_existente.get("conversation_id")
            _account_id_audio = conversa_existente.get("account_id")

            # 1) Tenta mediaUrl direto do payload UazAPI (instantâneo)
            audio_url = data.get("mediaUrl") or ""
            if audio_url:
                logger.info(f"🎙️ UazAPI: Áudio via mediaUrl direta para {phone} | {audio_url[:80]}...")
            else:
                # 2) Fallback: busca no Chatwoot (aguarda 3s para Chatwoot processar)
                logger.info(f"🎙️ UazAPI: mediaUrl não disponível para {phone}, tentando Chatwoot em 3s...")
                integracao_chatwoot = await carregar_integracao(empresa_id, 'chatwoot')

                if integracao_chatwoot and _conv_id_audio and _account_id_audio:
                    _cw_url = integracao_chatwoot.get("url") or integracao_chatwoot.get("base_url") or ""
                    _cw_token = integracao_chatwoot.get("access_token") or integracao_chatwoot.get("token") or ""

                    await asyncio.sleep(3)  # Dá tempo do Chatwoot receber o áudio

                    try:
                        async with httpx.AsyncClient(timeout=10.0) as _cw_client:
                            _cw_resp = await _cw_client.get(
                                f"{_cw_url.rstrip('/')}/api/v1/accounts/{_account_id_audio}/conversations/{_conv_id_audio}/messages",
                                headers={"api_access_token": str(_cw_token)},
                            )
                            if _cw_resp.status_code == 200:
                                _cw_msgs = _cw_resp.json().get("payload", [])
                                for _m in _cw_msgs:
                                    for _att in (_m.get("attachments") or []):
                                        if str(_att.get("file_type", "")).startswith("audio"):
                                            audio_url = _att.get("data_url")
                                            break
                                    if audio_url:
                                        break
                            else:
                                logger.warning(f"⚠️ Chatwoot retornou status {_cw_resp.status_code} para conv {_conv_id_audio}")
                    except Exception as _cw_err:
                        logger.error(f"❌ Erro ao buscar áudio no Chatwoot para {phone}: {_cw_err}")

                if audio_url:
                    logger.info(f"🎙️ UazAPI: Áudio encontrado no Chatwoot para {phone} | {audio_url[:80]}...")

            if audio_url:
                buffet_key = f"{empresa_id}:buffet:{_conv_id_audio}"
                await redis_client.rpush(buffet_key, json.dumps({
                    "text": "",
                    "files": [{"url": audio_url, "type": "audio"}]
                }))
                await redis_client.expire(buffet_key, 60)
            else:
                logger.warning(f"⚠️ UazAPI: Áudio detectado para {phone} mas nenhuma URL encontrada (nem UazAPI nem Chatwoot)")
        # --- Fim Transcrição de Áudio ---

        # Se não existe, usamos um ID temporário ou mapeamos depois no worker
        # Para manter compatibilidade com a fila atual:
        job_data = {
            "source": "uazapi",
            "empresa_id": str(empresa_id),
            "phone": phone,
            "content": content,
            "nome_cliente": data.get("pushName") or "Cliente WhatsApp",
            "msg_id": key.get("id"),
            "instance": body.get("instance")
        }

        # Publicar no Redis Streams
        await redis_client.xadd("ia:webhook:stream", job_data)

        logger.info(f"📥 UazAPI Webhook: Mensagem de {phone} enfileirada.")
        return {"status": "queued", "phone": phone}

    except Exception as e:
        logger.error(f"❌ Erro ao processar webhook UazAPI: {e}")
        return {"status": "error", "message": str(e)}
