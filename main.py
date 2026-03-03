import os
import asyncio
import random
import re
import hmac
import hashlib
import logging
import httpx
import json # <-- Adicionado para tratar o pacote de texto + mídia
import redis.asyncio as redis
from fastapi import FastAPI, Request, BackgroundTasks, Header, HTTPException
from dotenv import load_dotenv
from openai import AsyncOpenAI

# --- CONFIGURAÇÃO DE LOG ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("panobianco-ia")

load_dotenv()
app = FastAPI()

# --- CONFIGURAÇÕES ---
CHATWOOT_URL = os.getenv("CHATWOOT_URL")
CHATWOOT_TOKEN = os.getenv("CHATWOOT_TOKEN")
CHATWOOT_WEBHOOK_SECRET = os.getenv("CHATWOOT_WEBHOOK_SECRET")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
REDIS_URL = os.getenv("REDIS_URL")

cliente_ia = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# CLIENTES GLOBAIS
http_client: httpx.AsyncClient = None
redis_client: redis.Redis = None

@app.on_event("startup")
async def startup_event():
    global http_client, redis_client
    http_client = httpx.AsyncClient(timeout=20.0, limits=httpx.Limits(max_keepalive_connections=20, max_connections=50))
    
    try:
        redis_client = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
        await redis_client.ping()
        logger.info("🚀 Conexão com Redis estabelecida com sucesso!")
    except Exception as e:
        logger.error(f"❌ Erro ao conectar no Redis: {e}")
        raise e

@app.on_event("shutdown")
async def shutdown_event():
    await http_client.aclose()
    await redis_client.aclose()
    logger.info("🛑 Servidor desligado.")

# --- BANCO DE DADOS DE UNIDADES ---
UNIDADES = {
    "marajoara": {
        "nome": "Panobianco Marajoara",
        "endereco": "Rua Paulo Sérgio, 61 - Parque Marajoara - Santo André",
        "horarios": "*Segunda a Sexta:* 05h às 23h\n*Sábado:* 08h às 17h\n*DOM:* 09h às 14h",
        "link_venda": "https://evo-totem.w12app.com.br/panobiancos/282/site/oportunidade"
    }
}

# --- AUXILIARES ---
async def validar_assinatura(request: Request, x_chatwoot_signature: str):
    if not CHATWOOT_WEBHOOK_SECRET: return
    body = await request.body()
    signature = hmac.new(CHATWOOT_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, x_chatwoot_signature or ""):
        raise HTTPException(status_code=401, detail="Assinatura inválida")

def limpar_nome(nome: str):
    if not nome: return "Futuro Atleta"
    nome_limpo = re.sub(r'[~+0-9]', '', nome).strip()
    return nome_limpo if len(nome_limpo) > 1 else "Futuro Atleta"

async def verificar_atendimento_manual(account_id, conversation_id):
    url = f"{CHATWOOT_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}"
    headers = {"api_access_token": CHATWOOT_TOKEN}
    try:
        res = await http_client.get(url, headers=headers)
        dados = res.json()
        return dados.get("assignee_id") is not None or dados.get("status") not in ["pending", "open"]
    except: return True

async def obter_historico_chatwoot(account_id, conversation_id):
    url = f"{CHATWOOT_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
    headers = {"api_access_token": CHATWOOT_TOKEN}
    try:
        res = await http_client.get(url, headers=headers)
        msgs = res.json().get("payload", [])
        msgs = sorted(msgs, key=lambda x: x["id"])[-20:]
        return "\n".join([f"{'Cliente' if m['message_type']==0 else 'Atendente'}: {m.get('content') or '[Enviou Mídia]'}" for m in msgs])
    except: return ""

# --- LÓGICA DA IA (AGORA MULTIMODAL) ---

async def processar_ia_e_responder(account_id, conversation_id, contact_id, slug_unidade, nome_cliente):
    chave_lock = f"lock:{conversation_id}"
    try:
        await asyncio.sleep(12) # Tempo de buffet ligeiramente maior para mídias
        
        chave_buffet = f"buffet:{conversation_id}"
        mensagens_lista = await redis_client.lrange(chave_buffet, 0, -1)
        await redis_client.delete(chave_buffet)
        
        if not mensagens_lista or await verificar_atendimento_manual(account_id, conversation_id):
            return

        # 1. Separar o que é texto, imagem e áudio do Buffet
        textos = []
        imagens = []
        audios = []
        
        for item in mensagens_lista:
            try:
                dado = json.loads(item)
                if dado.get("text"): textos.append(dado["text"])
                for f in dado.get("files", []):
                    if f["type"] == "image": imagens.append(f["url"])
                    elif f["type"] == "audio": audios.append(f["url"])
            except json.JSONDecodeError:
                # Segurança caso tenha ficado texto puro antigo no Redis
                textos.append(item)

        texto_usuario = " ".join(textos).strip()
        
        # 2. Montar o array Multimodal para a IA
        conteudo_usuario_ia = []
        
        # Adiciona os textos e os links de áudio (se houver)
        if texto_usuario or audios:
            texto_final = texto_usuario
            if audios:
                links_audio = ", ".join(audios)
                texto_final += f"\n\n[O cliente enviou um áudio neste link: {links_audio}. Se possível, acesse o link para ouvir e responder.]"
            
            conteudo_usuario_ia.append({"type": "text", "text": texto_final if texto_final else "[O cliente enviou apenas mídia]"})
        
        # Adiciona as imagens
        for img_url in imagens:
            if img_url:
                conteudo_usuario_ia.append({"type": "image_url", "image_url": {"url": img_url}})

        u = UNIDADES.get(slug_unidade, UNIDADES["marajoara"])
        historico = await obter_historico_chatwoot(account_id, conversation_id)
        precisa_saudacao = "Atendente:" not in historico[-200:]

        system_prompt = f"""
        Você é o Consultor de Vendas da {u['nome']}.
        Seu objetivo: Converter curiosos em alunos matriculados de forma natural.

        Você agora tem capacidade de VER imagens. Analise as fotos enviadas pelos clientes (ex: fotos de equipamentos, comprovantes, etc) e interaja de acordo.
        
        CONTEXTO:
        - Cliente: {nome_cliente}
        - Unidade: {u['nome']} ({u['endereco']})
        - Link de Matrícula: {u['link_venda']}

        REGRAS DE PERSONALIDADE:
        1. SAUDAÇÃO: {'Seja amigável na primeira mensagem.' if precisa_saudacao else 'Vá direto ao ponto.'}
        2. ESTILO: Português do dia a dia (Brasil), gírias leves de academia. Máx 2 parágrafos.
        3. LINK: Só envie se o cliente perguntar de preços. Se já enviou, NÃO envie de novo.
        4. NOME: Se o cliente der um novo nome, use [NOME: Valor].

        HISTÓRICO:
        {historico}
        """

        response = await cliente_ia.chat.completions.create(
            model="google/gemini-2.0-flash-lite:preview-0205",
            messages=[
                {"role": "system", "content": system_prompt}, 
                {"role": "user", "content": conteudo_usuario_ia} # <-- Passando a lista multimodal
            ],
            temperature=0.8
        )
        
        resposta = response.choices[0].message.content

        # Tratamento de Nome e Envio (Mantidos)
        if "[NOME:" in resposta:
            match = re.search(r"\[NOME:\s*(.*?)\]", resposta)
            if match:
                novo_nome = limpar_nome(match.group(1))
                url_c = f"{CHATWOOT_URL}/api/v1/accounts/{account_id}/contacts/{contact_id}"
                await http_client.put(url_c, json={"name": novo_nome}, headers={"api_access_token": CHATWOOT_TOKEN})
                resposta = re.sub(r"\[NOME:.*?\]", "", resposta).strip()

        pedacos = [p.strip() for p in resposta.split("\n") if p.strip()]
        for p in pedacos:
            if await verificar_atendimento_manual(account_id, conversation_id): break
            await asyncio.sleep(len(p) * 0.05 + random.uniform(1, 2))
            url_m = f"{CHATWOOT_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
            await http_client.post(url_m, json={"content": p, "message_type": "outgoing"}, headers={"api_access_token": CHATWOOT_TOKEN})

    except Exception as e:
        logger.error(f"🔥 Erro: {e}", exc_info=True)
    finally:
        await redis_client.delete(chave_lock)

# --- ENDPOINT WEBHOOK ---

@app.post("/webhook")
async def chatwoot_webhook(request: Request, background_tasks: BackgroundTasks, x_chatwoot_signature: str = Header(None)):
    await validar_assinatura(request, x_chatwoot_signature)
    payload = await request.json()
    
    if payload.get("event") != "message_created" or payload.get("message_type") != "incoming":
        return {"status": "ignorado"}

    id_conv = payload.get("conversation", {}).get("id")
    conteudo_texto = payload.get("content", "")
    
    # 1. Extrair os Anexos (Imagens e Áudios)
    anexos = payload.get("attachments", [])
    arquivos_encontrados = []
    for a in anexos:
        # Pega a URL e identifica se é 'image' ou 'audio'
        tipo = "image" if "image" in str(a.get("file_type", "")) else "audio" if "audio" in str(a.get("file_type", "")) else "documento"
        arquivos_encontrados.append({
            "url": a.get("data_url"),
            "type": tipo
        })

    # 2. Alimenta o buffet no Redis com Texto + Arquivos em formato JSON
    chave_buffet = f"buffet:{id_conv}"
    dados_mensagem = json.dumps({"text": conteudo_texto, "files": arquivos_encontrados})
    await redis_client.rpush(chave_buffet, dados_mensagem)
    await redis_client.expire(chave_buffet, 60)

    # 3. Tenta o Lock
    if await redis_client.set(f"lock:{id_conv}", "1", nx=True, ex=60):
        labels = payload.get("conversation", {}).get("labels", [])
        slug = labels[0].lower() if labels and labels[0].lower() in UNIDADES else "marajoara"
        
        background_tasks.add_task(
            processar_ia_e_responder,
            payload["account"]["id"], id_conv, payload.get("sender", {}).get("id"),
            slug, limpar_nome(payload.get("sender", {}).get("name"))
        )
        return {"status": "processando"}
    
    return {"status": "acumulando_no_buffet"}

@app.get("/")
async def health(): return {"status": "Multimodal Online com Redis! 📸🎙️"}