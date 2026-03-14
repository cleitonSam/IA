import uuid
from fastapi import APIRouter, Request, Header, HTTPException, BackgroundTasks
from src.core.config import logger, REDIS_URL, EMPRESA_ID_PADRAO
from src.core.redis_client import redis_client
from src.services.db_queries import buscar_empresa_por_account_id, buscar_conversa_por_fone

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
        
        # Ignora mensagens enviadas pelo próprio bot
        if key.get("fromMe"):
            return {"status": "ignored", "reason": "from_me"}
            
        remote_jid = key.get("remoteJid", "")
        if not remote_jid or "@s.whatsapp.net" not in remote_jid:
            return {"status": "ignored", "reason": "not_personal_chat"}
            
        # Extrair telefone (ID do chat no WhatsApp)
        phone = remote_jid.split("@")[0]
        
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
