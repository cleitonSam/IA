import os
import asyncio
import random
import re
import hmac
import hashlib
import logging
import httpx
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
    # Inicia HTTP Pool
    http_client = httpx.AsyncClient(timeout=20.0, limits=httpx.Limits(max_keepalive_connections=20, max_connections=50))
    
    # Inicia Redis Pool com teste de conexão
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
        # Se tiver alguém atribuído ou não estiver 'pending'/'open', é manual
        return dados.get("assignee_id") is not None or dados.get("status") not in ["pending", "open"]
    except: return True

async def obter_historico_chatwoot(account_id, conversation_id):
    url = f"{CHATWOOT_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
    headers = {"api_access_token": CHATWOOT_TOKEN}
    try:
        res = await http_client.get(url, headers=headers)
        msgs = res.json().get("payload", [])
        msgs = sorted(msgs, key=lambda x: x["id"])[-20:]
        return "\n".join([f"{'Cliente' if m['message_type']==0 else 'Atendente'}: {m['content']}" for m in msgs if m.get("content")])
    except: return ""

# --- LÓGICA DA IA ---

async def processar_ia_e_responder(account_id, conversation_id, contact_id, slug_unidade, nome_cliente):
    chave_lock = f"lock:{conversation_id}"
    try:
        await asyncio.sleep(10) # Tempo de buffet
        
        chave_buffet = f"buffet:{conversation_id}"
        mensagens_lista = await redis_client.lrange(chave_buffet, 0, -1)
        await redis_client.delete(chave_buffet)
        
        texto_usuario = " ".join(mensagens_lista).strip()
        if not texto_usuario or await verificar_atendimento_manual(account_id, conversation_id):
            return

        u = UNIDADES.get(slug_unidade, UNIDADES["marajoara"])
        historico = await obter_historico_chatwoot(account_id, conversation_id)

        # Determina se precisa saudar ou ser direto
        precisa_saudacao = "Atendente:" not in historico[-200:] # Se não falei nada recentemente

        system_prompt = f"""
        Você é o Consultor de Vendas da {u['nome']}.
        Seu objetivo: Converter curiosos em alunos matriculados de forma natural.

        CONTEXTO:
        - Cliente: {nome_cliente}
        - Unidade: {u['nome']} ({u['endereco']})
        - Link de Matrícula: {u['link_venda']}

        REGRAS DE PERSONALIDADE (ANTI-ROBÔ):
        1. SAUDAÇÃO INTELIGENTE: {'Seja amigável na primeira mensagem.' if precisa_saudacao else 'NÃO diga "Olá" ou "Tudo bem" agora, você já está conversando com ele. Vá direto ao ponto.'}
        2. ESTILO: Use português do dia a dia (Brasil). Pode usar gírias leves de academia (bora, treinar, foco).
        3. CURTO E GROSSO: Responda em no máximo 2 parágrafos pequenos. 
        4. VARIÁVEL: Use variações como "Opa", "E aí", "Tudo certo?" apenas se for o início da conversa. 
        5. LINK: Só envie o link de matrícula ({u['link_venda']}) se o cliente demonstrar intenção de fechar ou perguntar preços/planos. Se o link já estiver no histórico, NÃO envie de novo.
        6. CAPTURA DE NOME: Se o cliente se apresentar com outro nome, use [NOME: Valor].

        HISTÓRICO:
        {historico}
        """

        response = await cliente_ia.chat.completions.create(
            model="google/gemini-2.0-flash-lite:preview-0205", # Versão correta e estável
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": texto_usuario}],
            temperature=0.8
        )
        
        resposta = response.choices[0].message.content

        # Tratamento de Nome
        if "[NOME:" in resposta:
            match = re.search(r"\[NOME:\s*(.*?)\]", resposta)
            if match:
                novo_nome = limpar_nome(match.group(1))
                url_c = f"{CHATWOOT_URL}/api/v1/accounts/{account_id}/contacts/{contact_id}"
                await http_client.put(url_c, json={"name": novo_nome}, headers={"api_access_token": CHATWOOT_TOKEN})
                resposta = re.sub(r"\[NOME:.*?\]", "", resposta).strip()

        # Envio parcelado para simular digitação
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
    conteudo = payload.get("content", "")

    # 1. Alimenta o buffet no Redis
    chave_buffet = f"buffet:{id_conv}"
    await redis_client.rpush(chave_buffet, conteudo)
    await redis_client.expire(chave_buffet, 60)

    # 2. Tenta o Lock
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
async def health(): return {"status": "Online e com Redis! 🚀"}