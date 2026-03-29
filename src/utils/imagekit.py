import httpx
import base64
from typing import Optional, Dict, Any
from src.core.config import IMAGEKIT_PRIVATE_KEY, logger

async def upload_to_imagekit(
    file_content: bytes, 
    file_name: str, 
    folder: str = "/unidades"
) -> Optional[str]:
    """
    Realiza o upload de um arquivo para o ImageKit via API REST.
    Retorna a URL da imagem ou None em caso de erro.
    """
    if not IMAGEKIT_PRIVATE_KEY:
        logger.error("IMAGEKIT_PRIVATE_KEY não configurada")
        return None

    # Autenticação: Basic Auth (private_key + ':') em base64
    auth_str = f"{IMAGEKIT_PRIVATE_KEY}:"
    auth_b64 = base64.b64encode(auth_str.encode()).decode()

    url = "https://upload.imagekit.io/api/v1/files/upload"
    headers = {
        "Authorization": f"Basic {auth_b64}"
    }
    
    files = {
        "file": (file_name, file_content),
        "fileName": (None, file_name),
        "useUniqueFileName": (None, "true"),
        "folder": (None, folder)
    }

    # Timeout adaptativo: vídeos precisam de mais tempo
    file_size_mb = len(file_content) / (1024 * 1024)
    upload_timeout = max(60.0, min(file_size_mb * 10, 300.0))  # 10s/MB, min 60s, max 300s

    try:
        async with httpx.AsyncClient() as client:
            logger.info(f"📤 Upload ImageKit: {file_name} ({file_size_mb:.1f}MB) timeout={upload_timeout:.0f}s")
            resp = await client.post(url, headers=headers, files=files, timeout=upload_timeout)

            if resp.status_code in (200, 201):
                data = resp.json()
                logger.info(f"✅ Upload ImageKit sucesso: {data.get('url')}")
                return data.get("url")
            else:
                logger.error(f"❌ Erro upload ImageKit ({resp.status_code}): {resp.text}")
                return None
    except httpx.TimeoutException:
        logger.error(f"❌ Timeout no upload ImageKit ({file_size_mb:.1f}MB, {upload_timeout:.0f}s)")
        return None
    except Exception as e:
        logger.error(f"❌ Exceção no upload ImageKit: {e}")
        return None
