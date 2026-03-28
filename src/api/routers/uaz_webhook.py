import uuid
import json
import asyncio
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
    background_tasks: BackgroundTasks,
    x_webhook_token: str = Header(None),
    authorization: str = Header(None)
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

    # --- Autenticação: valida token do webhook ---
    _expected_token = integracao.get("webhook_token") or integracao.get("webhook_secret")
    if _expected_token:
        _received_token = x_webhook_token or (authorization.replace("Bearer ", "") if authorization else None)
        if not _received_token or _received_token != _expected_token:
            logger.warning(f"🔒 Webhook UazAPI rejeitado para empresa {empresa_id}: token inválido")
            raise HTTPException(status_code=401, detail="Token de webhook inválido")

    try:
        body = await request.json()
        event = body.get("event")

        # --- Read Receipts Tracking ---
        if event == "messages.update":
            _updates = body.get("data", {}).get("messages", [])
            for _upd in _updates:
                _upd_status = _upd.get("status")
                _upd_key = _upd.get("key", {})
                _upd_phone = (_upd_key.get("remoteJid") or "").split("@")[0]
                if _upd_status in (3, 4, "READ", "PLAYED") and _upd_phone:
                    # Status 3=DELIVERED, 4=READ/PLAYED
                    _conv = await buscar_conversa_por_fone(_upd_phone, empresa_id)
                    if _conv:
                        from src.services.db_queries import bd_registrar_evento_funil
                        _tipo = "mensagem_lida" if _upd_status in (4, "READ", "PLAYED") else "mensagem_entregue"
                        await bd_registrar_evento_funil(
                            _conv.get("conversation_id"), empresa_id,
                            _tipo, f"phone={_upd_phone}", score_incremento=0
                        )
            return {"status": "receipts_tracked", "count": len(_updates)}

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

        # Imagem e Vídeo (multimodal — IA "vê" a imagem)
        image_msg = msg_payload.get("imageMessage")
        video_msg = msg_payload.get("videoMessage")
        has_image = bool(image_msg)
        has_video = bool(video_msg)

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

        has_media = has_audio or has_image or has_video
        if not content and not has_media:
            return {"status": "ignored", "reason": "empty_content"}

        # Placeholder para mídia sem texto — será complementado pelo pipeline
        if not content and has_audio:
            content = "[Áudio recebido]"
        elif not content and has_image:
            content = "[Imagem recebida]"
        elif not content and has_video:
            content = "[Vídeo recebido]"

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

        # --- Detecção de URLs de Mídia (Áudio, Imagem, Vídeo) ---
        # Busca mediaUrl no payload UazAPI (vários locais possíveis).
        # O stream_worker cuida de popular o buffet usando o conversation_id correto.
        media_url = (
            data.get("mediaUrl") or
            body.get("mediaUrl") or
            message.get("mediaUrl") or
            ""
        )

        audio_url = ""
        image_url = ""

        if has_audio:
            audio_url = media_url
            if audio_url:
                logger.info(f"🎙️ UazAPI: Áudio com mediaUrl para {phone} | {audio_url[:80]}...")
            else:
                logger.info(f"🎙️ UazAPI: Áudio detectado para {phone} (sem mediaUrl no payload, worker resolverá via Chatwoot)")

        if has_image or has_video:
            image_url = media_url
            if image_url:
                logger.info(f"🖼️ UazAPI: {'Imagem' if has_image else 'Vídeo'} com mediaUrl para {phone} | {image_url[:80]}...")
            else:
                logger.info(f"🖼️ UazAPI: {'Imagem' if has_image else 'Vídeo'} detectado para {phone} (sem mediaUrl, worker resolverá via Chatwoot)")

        # --- Dedup cross-webhook: evita processar a mesma mensagem 2x ---
        _uaz_msg_id = key.get("id", "")
        if _uaz_msg_id:
            _dedup_key = f"dedup:msg:{empresa_id}:{phone}:{_uaz_msg_id}"
            if not await redis_client.set(_dedup_key, "1", nx=True, ex=120):
                logger.info(f"🔁 Mensagem duplicada ignorada (dedup): {phone} msg_id={_uaz_msg_id}")
                return {"status": "ignored", "reason": "duplicate"}

        job_data = {
            "source": "uazapi",
            "empresa_id": str(empresa_id),
            "phone": phone,
            "content": content,
            "nome_cliente": data.get("pushName") or "Cliente WhatsApp",
            "msg_id": _uaz_msg_id,
            "instance": body.get("instance"),
            "has_audio": "1" if has_audio else "",
            "audio_url": audio_url,
            "has_image": "1" if (has_image or has_video) else "",
            "image_url": image_url,
        }

        # Publicar no Redis Streams
        await redis_client.xadd("ia:webhook:stream", job_data)

        logger.info(f"📥 UazAPI Webhook: Mensagem de {phone} enfileirada.")
        return {"status": "queued", "phone": phone}

    except Exception as e:
        logger.error(f"❌ Erro ao processar webhook UazAPI: {e}")
        return {"status": "error", "message": str(e)}
