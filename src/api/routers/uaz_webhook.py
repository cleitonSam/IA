import uuid
from fastapi import APIRouter, Request, Header, HTTPException, BackgroundTasks
from src.core.config import logger, REDIS_URL, EMPRESA_ID_PADRAO
from src.core.redis_client import redis_client
from src.services.db_queries import buscar_empresa_por_account_id, buscar_conversa_por_fone, carregar_integracao

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

        if not remote_jid or "@s.whatsapp.net" not in remote_jid:
            return {"status": "ignored", "reason": "not_personal_chat"}

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

        # Extrair conteúdo (texto ou legenda)
        content = ""
        conversation = message.get("message", {}).get("conversation")
        extended = message.get("message", {}).get("extendedTextMessage", {}).get("text")
        image_caption = message.get("message", {}).get("imageMessage", {}).get("caption")
        video_caption = message.get("message", {}).get("videoMessage", {}).get("caption")
        
        content = conversation or extended or image_caption or video_caption or ""
        
        if not content:
            # Caso seja apenas mídia sem texto, podemos tratar futuramente
            return {"status": "ignored", "reason": "empty_content"}

        # Buscar se já existe uma conversa interna para este telefone
        conversa_existente = await buscar_conversa_por_fone(phone, empresa_id)
        
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
