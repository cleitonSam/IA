import os
import asyncio
import random
import re
import hmac
import hashlib
import logging
import httpx
import json
import base64
import tempfile
import redis.asyncio as redis
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Request, BackgroundTasks, Header, HTTPException
from dotenv import load_dotenv
from openai import AsyncOpenAI

# --- CONFIGURAÇÃO DE LOG ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("panobianco-ia")

load_dotenv()

# 🧯 7. Segurança: Validar variáveis críticas antes de subir a aplicação
CHATWOOT_URL = os.getenv("CHATWOOT_URL")
CHATWOOT_TOKEN = os.getenv("CHATWOOT_TOKEN")
if not CHATWOOT_URL or not CHATWOOT_TOKEN:
    raise RuntimeError("🚨 Configuração crítica ausente: CHATWOOT_URL ou CHATWOOT_TOKEN não foram definidos no .env")

app = FastAPI()

# --- CONFIGURAÇÕES E VARIÁVEIS DE AMBIENTE ---
CHATWOOT_WEBHOOK_SECRET = os.getenv("CHATWOOT_WEBHOOK_SECRET")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY") 
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")         
REDIS_URL = os.getenv("REDIS_URL")

# Clientes de IA
cliente_ia = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
cliente_whisper = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Clientes Globais de Conexão
http_client: httpx.AsyncClient = None
redis_client: redis.Redis = None

@app.on_event("startup")
async def startup_event():
    global http_client, redis_client
    http_client = httpx.AsyncClient(timeout=30.0, limits=httpx.Limits(max_keepalive_connections=20, max_connections=50))
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

# --- AUXILIARES E CONTEXTO ---
def obter_contexto_tempo():
    fuso_sp = ZoneInfo("America/Sao_Paulo")
    agora = datetime.now(fuso_sp)
    hora = agora.hour

    if 5 <= hora < 12: saudacao = "Bom dia"
    elif 12 <= hora < 18: saudacao = "Boa tarde"
    else: saudacao = "Boa noite"

    dias_semana = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]
    return saudacao, dias_semana[agora.weekday()], agora.strftime("%H:%M")

async def validar_assinatura(request: Request, x_signature: str):
    if not CHATWOOT_WEBHOOK_SECRET: return
    body = await request.body()
    signature = hmac.new(CHATWOOT_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, x_signature or ""):
        raise HTTPException(status_code=401)

def limpar_nome(nome: str):
    if not nome: return "Futuro Atleta"
    nome_limpo = re.sub(r'[~+0-9]', '', nome).strip()
    return nome_limpo if len(nome_limpo) > 1 else "Futuro Atleta"

async def verificar_atendimento_manual(account_id, conversation_id):
    url = f"{CHATWOOT_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}"
    try:
        res = await http_client.get(url, headers={"api_access_token": CHATWOOT_TOKEN})
        dados = res.json()
        return dados.get("assignee_id") is not None or dados.get("status") not in ["pending", "open"]
    except: return True

async def obter_historico_chatwoot(account_id, conversation_id):
    url = f"{CHATWOOT_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
    try:
        res = await http_client.get(url, headers={"api_access_token": CHATWOOT_TOKEN})
        msgs = sorted(res.json().get("payload", []), key=lambda x: x["id"])[-40:]
        return "\n".join([f"{'Cliente' if m['message_type']==0 else 'Atendente'}: {m.get('content') or '[Enviou Mídia]'}" for m in msgs])
    except: return ""

# --- FUNÇÕES CORE MULTIMÍDIA ---
async def baixar_arquivo_chatwoot(url: str):
    try:
        res = await http_client.get(url, headers={"api_access_token": CHATWOOT_TOKEN}, follow_redirects=True)
        res.raise_for_status()
        return res.content
    except Exception as e:
        logger.error(f"❌ Erro ao baixar arquivo do Chatwoot: {e}")
        return None

async def transcrever_audio_whisper(audio_bytes: bytes):
    if not cliente_whisper:
        return "[Áudio recebido, mas a chave OPENAI_API_KEY não foi configurada.]"
    
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp_file:
            tmp_file.write(audio_bytes)
            tmp_path = tmp_file.name

        with open(tmp_path, "rb") as audio_file:
            # 🚀 1. Timeout defensivo para o Whisper
            transcription = await asyncio.wait_for(
                cliente_whisper.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language="pt"
                ),
                timeout=20.0
            )
        return transcription.text
    except asyncio.TimeoutError:
        logger.warning("⏱️ Timeout no Whisper atingido.")
        return "Recebi seu áudio, mas ele está um pouquinho longo 😅 pode dar uma resumida pra mim rapidinho?"
    except Exception as e:
        logger.error(f"❌ Erro no Whisper: {e}")
        return "[Erro interno ao transcrever o áudio do cliente.]"
    finally:
        # Garante a limpeza do arquivo mesmo se der timeout
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

# --- LÓGICA PRINCIPAL DA IA ---
async def processar_ia_e_responder(account_id, conversation_id, contact_id, slug_unidade, nome_cliente):
    chave_lock = f"lock:{conversation_id}"
    try:
        await asyncio.sleep(12) 
        
        if await redis_client.exists(f"pause_ia:{conversation_id}"):
            logger.info(f"🛑 IA cancelou resposta pós-buffet na conversa {conversation_id} (Atendente assumiu).")
            return
        
        chave_buffet = f"buffet:{conversation_id}"
        mensagens_lista = await redis_client.lrange(chave_buffet, 0, -1)
        await redis_client.delete(chave_buffet)
        
        if not mensagens_lista or await verificar_atendimento_manual(account_id, conversation_id):
            return

        # 💣 5. Proteção contra Spam Flood
        if len(mensagens_lista) > 15:
            logger.warning(f"⚠️ Flood detectado na conversa {conversation_id}. Truncando mensagens.")
            mensagens_lista = mensagens_lista[-15:]

        textos, imagens, audios = [], [], []
        for item in mensagens_lista:
            try:
                dado = json.loads(item)
                if dado.get("text"): textos.append(dado["text"])
                for f in dado.get("files", []):
                    if f["type"] == "image": imagens.append(f["url"])
                    elif f["type"] == "audio": audios.append(f["url"])
            except:
                textos.append(item)

        texto_usuario = " ".join(textos).strip()
        conteudo_usuario_ia = []
        
        # Processamento de Áudio
        textos_transcritos = []
        for audio_url in audios:
            bytes_audio = await baixar_arquivo_chatwoot(audio_url)
            if bytes_audio:
                texto_transcrito = await transcrever_audio_whisper(bytes_audio)
                textos_transcritos.append(f"[Áudio do cliente transcrito: {texto_transcrito}]")

        texto_final = texto_usuario + "\n\n" + "\n".join(textos_transcritos)
        if texto_final.strip():
            conteudo_usuario_ia.append({"type": "text", "text": texto_final.strip()})
        else:
            conteudo_usuario_ia.append({"type": "text", "text": "[O cliente enviou apenas imagem]"})

        # Processamento de Imagens
        for img_url in imagens:
            bytes_img = await baixar_arquivo_chatwoot(img_url)
            if bytes_img:
                b64_img = base64.b64encode(bytes_img).decode('utf-8')
                conteudo_usuario_ia.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}
                })

        # Contexto e Estado Emocional
        u = UNIDADES.get(slug_unidade, UNIDADES["marajoara"])
        historico = await obter_historico_chatwoot(account_id, conversation_id)
        precisa_saudacao = "Atendente:" not in historico[-200:]
        saudacao_certa, dia_atual, hora_atual = obter_contexto_tempo()
        
        # 🧬 6. Recupera o estado emocional do cliente
        estado_cliente = await redis_client.get(f"estado:{conversation_id}") or "indefinido"

        system_prompt = f"""
        Você é o Consultor de Vendas da {u['nome']}.
        Seu objetivo: Converter curiosos em alunos matriculados de forma natural.

        CONTEXTO ATUAL:
        - Hoje é {dia_atual}, {hora_atual} (Horário de Brasília/SP).
        - Estado Emocional Mapeado do Cliente: {estado_cliente}
        - Horários da academia: {u['horarios']}

        DADOS DA UNIDADE:
        - Endereço: {u['endereco']}
        - Link de Matrícula: {u['link_venda']}

        REGRAS ABSOLUTAS:
        1. NÃO SEJA REPETITIVO: NUNCA repita frases ou links que já estão no histórico.
        2. FOCO NO AGORA: Responda APENAS à última mensagem.
        3. SAUDAÇÃO: {'Use "' + saudacao_certa + '" no início.' if precisa_saudacao else 'Vá direto ao ponto.'}
        4. LINK: Só envie se o cliente quiser comprar. Se já enviou, NÃO envie de novo.
        5. ESTILO HUMANO: Direto. 2 parágrafos curtos. Português BR com gírias leves (bora, foco).
        6. IMAGENS/ÁUDIOS: Comente naturalmente sobre o que viu ou ouviu.
        7. NOME: Cliente atual = {nome_cliente}. Para corrigir, use [NOME: Valor].
        8. FECHAMENTO: SEMPRE faça uma pergunta no final se o cliente não estiver 100% decidido. (Aumenta conversão!)
        9. EMOCIONAL: Se notar mudança clara no humor do cliente (ex: interessado, irritado, indeciso), adicione no final da sua resposta a tag [ESTADO: emocao].

        HISTÓRICO:
        {historico}
        """

        # 🚀 2. Estratégia de Produção: Rotação de modelo por horário
        hora_atual_int = datetime.now(ZoneInfo("America/Sao_Paulo")).hour
        if 8 <= hora_atual_int <= 20:
            modelos_para_tentar = ["google/gemini-2.5-flash", "google/gemini-2.5-flash-lite"]
        else:
            modelos_para_tentar = ["google/gemini-2.5-flash-lite", "google/gemini-2.5-flash"]
        
        resposta = None
        erro_final = None

        for modelo_atual in modelos_para_tentar:
            try:
                logger.info(f"🧠 Tentando gerar resposta com: {modelo_atual}...")
                response = await cliente_ia.chat.completions.create(
                    model=modelo_atual,
                    messages=[
                        {"role": "system", "content": system_prompt}, 
                        {"role": "user", "content": conteudo_usuario_ia}
                    ],
                    temperature=0.7
                )
                resposta = response.choices[0].message.content
                break 
            
            except Exception as e:
                erro_final = str(e)
                logger.warning(f"⚠️ Erro no modelo {modelo_atual}: {erro_final}")
                # 🚀 2. Fallback inteligente anti-429
                if "429" in erro_final:
                    await asyncio.sleep(2)
                else:
                    await asyncio.sleep(1)

        if not resposta:
            logger.error("❌ FALHA GERAL NA IA. Nenhum modelo conseguiu responder.")
            resposta = "Desculpe, nosso sistema está um pouquinho sobrecarregado agora. 😅 Já já eu ou alguém da equipe te responde melhor, tá bom?"

        # Tratamento de Nome Oculto
        if "[NOME:" in resposta:
            match = re.search(r"\[NOME:\s*(.*?)\]", resposta)
            if match:
                url_c = f"{CHATWOOT_URL}/api/v1/accounts/{account_id}/contacts/{contact_id}"
                await http_client.put(url_c, json={"name": limpar_nome(match.group(1))}, headers={"api_access_token": CHATWOOT_TOKEN})
                resposta = re.sub(r"\[NOME:.*?\]", "", resposta).strip()

        # 🧬 6. Captura e salva o Estado Emocional Oculto
        if "[ESTADO:" in resposta:
            match_estado = re.search(r"\[ESTADO:\s*(.*?)\]", resposta)
            if match_estado:
                novo_estado = match_estado.group(1).lower().strip()
                await redis_client.setex(f"estado:{conversation_id}", 86400, novo_estado) # Salva por 24h
                resposta = re.sub(r"\[ESTADO:.*?\]", "", resposta).strip()

        # Envio fracionado
        pedacos = [p.strip() for p in resposta.split("\n") if p.strip()]
        for p in pedacos:
            if await verificar_atendimento_manual(account_id, conversation_id): break
            if await redis_client.exists(f"pause_ia:{conversation_id}"):
                logger.info(f"🛑 IA interrompeu o envio na conversa {conversation_id} (Atendente assumiu).")
                break

            # ⚡ 8. Melhoria de performance no delay de digitação
            delay = min(len(p) * 0.04, 4)
            await asyncio.sleep(delay + random.uniform(0.5, 1.5))
            
            url_m = f"{CHATWOOT_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
            payload_msg = {
                "content": p, 
                "message_type": "outgoing",
                "content_attributes": {
                    "origin": "ai",
                    "ai_agent": "Agente Red",
                    "ignore_webhook": True
                }
            }
            await http_client.post(url_m, json=payload_msg, headers={"api_access_token": CHATWOOT_TOKEN})

    except Exception as e:
        logger.error(f"🔥 Erro Crítico: {e}", exc_info=True)
    finally:
        await redis_client.delete(chave_lock)

# --- WEBHOOK ENDPOINT ---
@app.post("/webhook")
async def chatwoot_webhook(request: Request, background_tasks: BackgroundTasks, x_chatwoot_signature: str = Header(None)):
    await validar_assinatura(request, x_chatwoot_signature)
    payload = await request.json()
    
    event = payload.get("event")
    message_type = payload.get("message_type")
    id_conv = payload.get("conversation", {}).get("id")

    if event != "message_created":
        return {"status": "ignorado"}

    sender = payload.get("sender", {})
    sender_type = sender.get("type", "").lower()
    content_attrs = payload.get("content_attributes") or {}
    
    is_ai_message = content_attrs.get("ai_agent") == "Agente Red" or content_attrs.get("origin") == "ai"

    if message_type == "outgoing" and sender_type == "user":
        if is_ai_message:
            return {"status": "ignorado_mensagem_da_ia"}
        else:
            await redis_client.setex(f"pause_ia:{id_conv}", 43200, "1")
            logger.info(f"⏸️ IA pausada por 12h na conversa {id_conv} (Atendente assumiu).")
            return {"status": "ia_pausada"}

    if message_type != "incoming":
        return {"status": "ignorado_nao_incoming"}

    if await redis_client.exists(f"pause_ia:{id_conv}"):
        logger.info(f"⏳ Mensagem ignorada na conversa {id_conv}. IA pausada.")
        return {"status": "ignorado_ia_pausada"}

    conteudo_texto = payload.get("content", "")
    anexos = payload.get("attachments", [])
    arquivos_encontrados = []
    
    for a in anexos:
        tipo = "image" if "image" in str(a.get("file_type", "")) else "audio" if "audio" in str(a.get("file_type", "")) else "documento"
        arquivos_encontrados.append({"url": a.get("data_url"), "type": tipo})

    chave_buffet = f"buffet:{id_conv}"
    await redis_client.rpush(chave_buffet, json.dumps({"text": conteudo_texto, "files": arquivos_encontrados}))
    await redis_client.expire(chave_buffet, 60)

    if await redis_client.set(f"lock:{id_conv}", "1", nx=True, ex=60):
        labels = payload.get("conversation", {}).get("labels", [])
        
        # 🛑 4. Correção para múltiplas labels no array
        slug = next((l.lower() for l in labels if l.lower() in UNIDADES), "marajoara")
        
        background_tasks.add_task(
            processar_ia_e_responder,
            payload["account"]["id"], id_conv, payload.get("sender", {}).get("id"), slug, limpar_nome(payload.get("sender", {}).get("name"))
        )
        return {"status": "processando"}
    
    return {"status": "acumulando_no_buffet"}

@app.get("/")
async def health(): 
    return {"status": "🤖 Agente Panobianco Multimodal Online e Operante! 🚀"}
