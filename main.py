import os
import asyncio
import random
import re
import hmac
import hashlib
import logging
import httpx
from fastapi import FastAPI, Request, BackgroundTasks, Header, HTTPException
from dotenv import load_dotenv
from openai import AsyncOpenAI
from datetime import datetime

# --- CONFIGURAÇÃO DE LOG E AMBIENTE ---
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

cliente_ia = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# CLIENTE HTTP GLOBAL (Connection Pool)
http_client: httpx.AsyncClient = None

@app.on_event("startup")
async def startup_event():
    global http_client
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
    http_client = httpx.AsyncClient(timeout=15.0, limits=limits)
    logger.info("🚀 Servidor iniciado e Pool HTTP criado.")

@app.on_event("shutdown")
async def shutdown_event():
    await http_client.aclose()
    logger.info("🛑 Servidor desligado.")

# --- ESTADOS EM MEMÓRIA ---
buffet_mensagens = {}
processando = set()

UNIDADES = {
    "marajoara": {
        "nome": "Panobianco Marajoara",
        "endereco": "Rua Paulo Sérgio, 61 - Parque Marajoara - Santo André",
        "horarios": "*Segunda a Sexta:* 05h às 23h\n*Sábado:* 08h às 17h\n*DOM:* 09h às 14h",
        "link_venda": "https://evo-totem.w12app.com.br/panobiancos/282/site/oportunidade",
        "diferenciais": "Equipamentos de última geração e ambiente focado em resultados."
    }
}

# --- FUNÇÕES DE APOIO ---

async def validar_assinatura(request: Request, x_chatwoot_signature: str):
    if not CHATWOOT_WEBHOOK_SECRET: return
    body = await request.body()
    signature = hmac.new(CHATWOOT_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, x_chatwoot_signature or ""):
        logger.warning("⚠️ Assinatura inválida.")
        raise HTTPException(status_code=401, detail="Assinatura inválida")

def limpar_nome(nome: str):
    if not nome: return "Futuro Atleta"
    nome_limpo = re.sub(r'[~+0-9]', '', nome).strip()
    return nome_limpo if len(nome_limpo) > 1 else "Futuro Atleta"

async def atualizar_nome_contato(account_id, contact_id, novo_nome):
    url = f"{CHATWOOT_URL}/api/v1/accounts/{account_id}/contacts/{contact_id}"
    headers = {"api_access_token": CHATWOOT_TOKEN}
    try:
        await http_client.put(url, json={"name": novo_nome}, headers=headers)
        logger.info(f"✅ Nome do contato {contact_id} atualizado para {novo_nome}")
    except Exception:
        logger.error(f"❌ Erro ao atualizar nome {contact_id}", exc_info=True)

async def obter_historico_chatwoot(account_id, conversation_id):
    url = f"{CHATWOOT_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
    headers = {"api_access_token": CHATWOOT_TOKEN}
    try:
        response = await http_client.get(url, headers=headers)
        payload = response.json()
        mensagens = payload.get("payload", [])
        if not mensagens: return ""

        # Garante ordem cronológica e pega as últimas 20
        mensagens = sorted(mensagens, key=lambda x: x["id"])
        mensagens = mensagens[-30:]

        historico_formatado = []
        for m in mensagens:
            if not m.get("content"): continue
            tipo = m.get("message_type")
            if tipo == 0: autor = "Cliente"
            elif tipo == 1: autor = "Atendente"
            else: continue
            historico_formatado.append(f"{autor}: {m['content']}")

        historico_final = "\n".join(historico_formatado)
        logger.info(f"📜 Histórico recuperado ({len(historico_formatado)} msgs)")
        return historico_final
    except Exception:
        logger.error("❌ Erro ao obter histórico", exc_info=True)
        return ""

async def verificar_se_humano_assumiu(account_id, conversation_id):
    url = f"{CHATWOOT_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}"
    headers = {"api_access_token": CHATWOOT_TOKEN}
    try:
        res = await http_client.get(url, headers=headers)
        dados = res.json()
        return dados.get("assignee_id") is not None or dados.get("status") not in ["pending", "open"]
    except Exception:
        return True

# --- CORE DO AGENTE ---

async def processar_ia_e_responder(account_id, conversation_id, contact_id, slug_unidade, nome_cliente):
    try:
        await asyncio.sleep(10) # Buffet
        texto_acumulado = buffet_mensagens.pop(conversation_id, None)
        if not texto_acumulado or await verificar_se_humano_assumiu(account_id, conversation_id):
            return

        u = UNIDADES.get(slug_unidade, UNIDADES["marajoara"])
        historico = await obter_historico_chatwoot(account_id, conversation_id)

        # Lógica inteligente do link
        link_ja_enviado = u['link_venda'] in historico
        if link_ja_enviado:
            regra_link = "⚠️ O link de matrícula JÁ FOI enviado anteriormente. NÃO envie novamente."
        else:
            regra_link = f"Você pode enviar o link se fizer sentido para o fechamento: {u['link_venda']}"

        system_prompt = f"""
        Você é o Consultor de Vendas da {u['nome']}. Seu objetivo é ser humano e fechar matrículas. 🏋️‍♂️

        NOME DO CLIENTE: {nome_cliente}

        HISTÓRICO RECENTE:
        {historico}

        {regra_link}

        ⚠️ REGRAS DE OURO (NÃO QUEBRE):
        1. VARIE AS SAUDAÇÕES: Não use sempre 'Olá'. Use 'E aí', 'Fala', 'Tudo certo?', etc.
        2. Nunca repita informações já respondidas no histórico.
        3. NÃO use o nome do cliente em todas as frases.
        4. Seja direto e natural. Responda em no máximo 2 blocos curtos.
        5. Se o cliente disser um nome diferente de '{nome_cliente}', use [NOME: Valor] para eu atualizar o sistema.

        DADOS DA UNIDADE:
        - Endereço: {u['endereco']}
        - Horários: {u['horarios']}
        - Link de Matrícula: {u['link_venda']}
        """

        response = await cliente_ia.chat.completions.create(
            model="google/gemini-2.5-flash-lite:preview", 
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": texto_acumulado}],
            temperature=0.7 # Aumentado para maior naturalidade e variedade
        )
        
        resposta_bruta = response.choices[0].message.content

        # Captura de nome
        if "[NOME:" in resposta_bruta:
            match = re.search(r"\[NOME:\s*(.*?)\]", resposta_bruta)
            if match:
                novo_nome = limpar_nome(match.group(1))
                await atualizar_nome_contato(account_id, contact_id, novo_nome)
                resposta_bruta = re.sub(r"\[NOME:.*?\]", "", resposta_bruta).strip()

        pedacos = [p.strip() for p in resposta_bruta.split("\n") if p.strip()]
        url_envio = f"{CHATWOOT_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
        headers = {"api_access_token": CHATWOOT_TOKEN, "Content-Type": "application/json"}

        for pedaco in pedacos:
            if await verificar_se_humano_assumiu(account_id, conversation_id): break
            await asyncio.sleep(len(pedaco) * 0.04 + random.uniform(1.2, 2.2))
            await http_client.post(url_envio, json={"content": pedaco, "message_type": "outgoing"}, headers=headers)

    except Exception:
        logger.error(f"🔥 Erro na conversa {conversation_id}", exc_info=True)
    finally:
        processando.discard(conversation_id)

# --- WEBHOOK ---

@app.post("/webhook")
async def chatwoot_webhook(request: Request, background_tasks: BackgroundTasks, x_chatwoot_signature: str = Header(None)):
    await validar_assinatura(request, x_chatwoot_signature)
    payload = await request.json()
    
    if payload.get("event") != "message_created" or payload.get("message_type") != "incoming":
        return {"status": "ignorado"}

    conversa = payload.get("conversation", {})
    id_conv = conversa.get("id")

    if id_conv in processando:
        if id_conv in buffet_mensagens:
            buffet_mensagens[id_conv] += f" {payload.get('content')}"
        return {"status": "locked"}

    labels = conversa.get("labels", [])
    slug_unidade = labels[0].lower() if labels and labels[0].lower() in UNIDADES else "marajoara"

    if conversa.get("status") in ["pending", "open"] and conversa.get("assignee_id") is None:
        processando.add(id_conv)
        buffet_mensagens[id_conv] = payload.get("content")
        
        background_tasks.add_task(
            processar_ia_e_responder, 
            payload["account"]["id"], id_conv, payload.get("sender", {}).get("id"), 
            slug_unidade, limpar_nome(payload.get("sender", {}).get("name"))
        )
        return {"status": "agendado"}
    
    return {"status": "atendimento_manual"}

@app.get("/")
async def health(): return {"status": "Online 🚀"}
