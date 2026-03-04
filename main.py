import os
import io
import asyncio
import random
import re
import hmac
import hashlib
import logging
import httpx
import json
import base64
import uuid
import time
import zlib
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Request, BackgroundTasks, Header, HTTPException
from dotenv import load_dotenv
from openai import AsyncOpenAI
import redis.asyncio as redis
import asyncpg
from tenacity import retry, wait_exponential, stop_after_attempt

# --- CONFIGURAÇÃO DE LOG ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("motor-saas-ia")

load_dotenv()

# 🧯 Segurança: Validar variáveis críticas
CHATWOOT_URL = os.getenv("CHATWOOT_URL")
CHATWOOT_TOKEN = os.getenv("CHATWOOT_TOKEN")
if not CHATWOOT_URL or not CHATWOOT_TOKEN:
    raise RuntimeError("🚨 Configuração crítica ausente: CHATWOOT_URL ou CHATWOOT_TOKEN não definidos no .env")

app = FastAPI()

# --- CONFIGURAÇÕES E VARIÁVEIS DE AMBIENTE ---
CHATWOOT_WEBHOOK_SECRET = os.getenv("CHATWOOT_WEBHOOK_SECRET")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY") 
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")         
REDIS_URL = os.getenv("REDIS_URL")
DATABASE_URL = os.getenv("DATABASE_URL")

# Clientes de IA
cliente_ia = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
cliente_whisper = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Clientes Globais de Conexão
http_client: httpx.AsyncClient = None
redis_client: redis.Redis = None
db_pool: asyncpg.Pool = None

# --- CONTROLE DE CONCORRÊNCIA ---
whisper_semaphore = asyncio.Semaphore(5)
llm_semaphore = asyncio.Semaphore(15)

LUA_RELEASE_LOCK = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

@app.on_event("startup")
async def startup_event():
    global http_client, redis_client, db_pool
    http_client = httpx.AsyncClient(timeout=30.0, limits=httpx.Limits(max_keepalive_connections=20, max_connections=50))
    
    try:
        redis_client = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
        await redis_client.ping()
        logger.info("🚀 Conexão com Redis estabelecida com sucesso!")
    except Exception as e:
        logger.error(f"❌ Erro ao conectar no Redis: {e}")
        raise e

    if DATABASE_URL:
        try:
            db_pool = await asyncpg.create_pool(DATABASE_URL)
            logger.info("🐘 Conexão com PostgreSQL estabelecida com sucesso!")
        except Exception as e:
            logger.error(f"❌ Erro ao conectar no PostgreSQL: {e}")
    else:
        logger.warning("⚠️ DATABASE_URL não definida. As métricas não serão salvas.")
    
    asyncio.create_task(worker_followup())

@app.on_event("shutdown")
async def shutdown_event():
    await http_client.aclose()
    await redis_client.aclose()
    if db_pool: await db_pool.close()
    logger.info("🛑 Servidor desligado.")

# --- UTILITÁRIOS ---
def comprimir_texto(texto: str) -> str:
    if not texto: return ""
    return base64.b64encode(zlib.compress(texto.encode('utf-8'))).decode('utf-8')

def descomprimir_texto(texto_comprimido: str) -> str:
    if not texto_comprimido: return ""
    try:
        return zlib.decompress(base64.b64decode(texto_comprimido)).decode('utf-8')
    except:
        return texto_comprimido 

def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def limpar_nome(nome):
    if not nome: return "Cliente"
    return re.sub(r"[^a-zA-ZÀ-ÿ\s]", "", str(nome)).strip()

async def renovar_lock(chave: str, valor: str, intervalo: int = 20):
    try:
        while True:
            await asyncio.sleep(intervalo)
            res = await redis_client.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], 60) else return 0 end",
                1, chave, valor
            )
            if not res: break
    except asyncio.CancelledError:
        pass

# --- FUNÇÃO CENTRALIZADA DE ENVIO PARA O CHATWOOT ---
async def enviar_mensagem_chatwoot(account_id: int, conversation_id: int, content: str, nome_ia: str = "Assistente Virtual"):
    url_m = f"{CHATWOOT_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
    payload = {
        "content": content, 
        "message_type": "outgoing",
        "content_attributes": {"origin": "ai", "ai_agent": nome_ia, "ignore_webhook": True}
    }
    headers = {"api_access_token": CHATWOOT_TOKEN}
    try:
        resp = await http_client.post(url_m, json=payload, headers=headers)
        resp.raise_for_status()
        return resp
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem para Chatwoot: {e}")
        return None

# --- BACKGROUND JOBS & FOLLOW-UP ---
async def agendar_followups(conversation_id: int, account_id: int, slug: str):
    if not db_pool: return
    try:
        await db_pool.execute("DELETE FROM followups WHERE conversation_id = $1 AND status = 'pendente'", conversation_id)
        templates = await db_pool.fetch("SELECT * FROM followup_templates WHERE slug_unidade = $1 AND ativo = TRUE ORDER BY ordem", slug)
        agora = datetime.now(ZoneInfo("America/Sao_Paulo"))

        for t in templates:
            agendar = agora + timedelta(minutes=t["delay_minutos"])
            await db_pool.execute("""
                INSERT INTO followups (conversation_id, account_id, slug_unidade, template_id, ordem, agendado_para, status)
                VALUES ($1,$2,$3,$4,$5,$6,'pendente')
            """, conversation_id, account_id, slug, t["id"], t["ordem"], agendar)
    except Exception as e:
        logger.error(f"Erro ao agendar followups: {e}")

async def worker_followup():
    while True:
        await asyncio.sleep(30) 
        if not db_pool: continue
        try:
            agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
            pendentes = await db_pool.fetch("SELECT * FROM followups WHERE status = 'pendente' AND agendado_para <= $1 LIMIT 20", agora)
            
            for f in pendentes:
                if await redis_client.get(f"atend_manual:{f['conversation_id']}") == "1" or await redis_client.get(f"pause_ia:{f['conversation_id']}") == "1":
                    await db_pool.execute("UPDATE followups SET status = 'cancelado' WHERE id = $1", f['id'])
                    continue

                respondeu = await db_pool.fetchval("SELECT 1 FROM mensagens_local WHERE conversation_id = $1 AND role = 'user' AND created_at > NOW() - interval '5 minutes'", f["conversation_id"])
                if respondeu:
                    await db_pool.execute("UPDATE followups SET status = 'cancelado' WHERE id = $1", f["id"])
                    continue

                template = await db_pool.fetchrow("SELECT mensagem FROM followup_templates WHERE id = $1", f["template_id"])
                if template:
                    await enviar_mensagem_chatwoot(f['account_id'], f['conversation_id'], template["mensagem"])
                    await db_pool.execute("UPDATE followups SET status = 'enviado', enviado_em = NOW() WHERE id = $1", f['id'])
                else:
                    await db_pool.execute("UPDATE followups SET status = 'erro', erro_log = 'Template não encontrado' WHERE id = $1", f['id'])
        except Exception as e:
            logger.error(f"Erro no worker de follow-up: {e}")

async def monitorar_escolha_unidade(account_id: int, conversation_id: int):
    await asyncio.sleep(120) 
    if not await redis_client.exists(f"esperando_unidade:{conversation_id}"): return
    if await redis_client.exists(f"unidade_escolhida:{conversation_id}"): return

    await enviar_mensagem_chatwoot(account_id, conversation_id, "Só confirmando 🙂 qual unidade você deseja falar?")

    await asyncio.sleep(480) 
    if not await redis_client.exists(f"esperando_unidade:{conversation_id}"): return
    if await redis_client.exists(f"unidade_escolhida:{conversation_id}"): return

    await redis_client.delete(f"esperando_unidade:{conversation_id}")
    url_c = f"{CHATWOOT_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}"
    await http_client.put(url_c, json={"status": "resolved"}, headers={"api_access_token": CHATWOOT_TOKEN})

# --- FUNÇÕES DE BUSCA DINÂMICA (SAAS) ---
async def listar_unidades_ativas():
    if not db_pool: return []
    try:
        rows = await db_pool.fetch("SELECT slug, nome, palavras_chave FROM unidades_config WHERE ativa = TRUE ORDER BY nome")
        return [dict(r) for r in rows]
    except Exception as e:
        return []

async def carregar_unidade(slug: str):
    if not db_pool: return {}
    cache = await redis_client.get(f"cfg:unidade:{slug}")
    if cache: return json.loads(cache)
    row = await db_pool.fetchrow("SELECT * FROM unidades_config WHERE slug = $1 AND ativa = TRUE", slug)
    if row:
        dados = dict(row)
        await redis_client.setex(f"cfg:unidade:{slug}", 300, json.dumps(dados, default=str)) 
        return dados
    return {}

async def carregar_faq_unidade(slug: str):
    if not db_pool: return ""
    cache = await redis_client.get(f"cfg:faq:{slug}")
    if cache: return cache
    rows = await db_pool.fetch("SELECT pergunta, resposta FROM faq_unidades WHERE slug_unidade = $1 AND ativo = TRUE ORDER BY prioridade DESC", slug)
    faq_formatado = "".join([f"\nPergunta: {r['pergunta']}\nResposta: {r['resposta']}\n" for r in rows]).strip()
    if faq_formatado: await redis_client.setex(f"cfg:faq:{slug}", 300, faq_formatado)
    return faq_formatado

async def carregar_personalidade(slug: str):
    if not db_pool: return {}
    cache = await redis_client.get(f"cfg:pers:{slug}")
    if cache: return json.loads(cache)
    row = await db_pool.fetchrow("SELECT * FROM personalidade_ia WHERE slug_unidade = $1 LIMIT 1", slug)
    if row:
        dados = dict(row)
        await redis_client.setex(f"cfg:pers:{slug}", 300, json.dumps(dados, default=str))
        return dados
    return {}

# --- AUXILIARES BANCO DE DADOS ---
def log_db_error(retry_state):
    logger.error(f"Erro BD: {retry_state.outcome.exception()}")
    return None

@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_iniciar_conversa(conversation_id: int, unidade: str):
    if db_pool: await db_pool.execute("INSERT INTO conversas_ia (conversation_id, unidade) VALUES ($1, $2) ON CONFLICT (conversation_id) DO NOTHING", conversation_id, unidade)

@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_salvar_mensagem_local(conversation_id: int, role: str, content: str):
    if db_pool: await db_pool.execute("INSERT INTO mensagens_local (conversation_id, role, content) VALUES ($1, $2, $3)", conversation_id, role, content)

async def bd_obter_historico_local(conversation_id: int, limit: int = 30):
    if not db_pool: return None
    rows = await db_pool.fetch("SELECT role, content FROM mensagens_local WHERE conversation_id = $1 ORDER BY created_at DESC LIMIT $2", conversation_id, limit)
    msgs = reversed(rows)
    return "\n".join([f"{'Cliente' if r['role'] == 'user' else 'Atendente'}: {r['content']}" for r in msgs])

@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_atualizar_metricas(conversation_id: int, role: str):
    if not db_pool: return
    coluna = "mensagens_cliente" if role == "user" else "mensagens_ia"
    await db_pool.execute(f"UPDATE conversas_ia SET {coluna} = {coluna} + 1, updated_at = NOW() WHERE conversation_id = $1", conversation_id)

@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_registrar_evento_funil(conversation_id: int, tipo_evento: str, descricao: str, score: int = 5):
    if not db_pool: return
    if tipo_evento == "interesse_detectado" and await db_pool.fetchval("SELECT 1 FROM eventos_conversa WHERE conversation_id = $1 AND tipo_evento = $2", conversation_id, tipo_evento): return
    await db_pool.execute("INSERT INTO eventos_conversa (conversation_id, tipo_evento, descricao) VALUES ($1, $2, $3)", conversation_id, tipo_evento, descricao)
    await db_pool.execute("UPDATE conversas_ia SET score = score + $2, updated_at = NOW() WHERE conversation_id = $1", conversation_id, score)

# --- PROCESSAMENTO IA E ÁUDIO ---
async def transcrever_audio(url: str):
    if not cliente_whisper: return "[Áudio]"
    async with whisper_semaphore: 
        try:
            resp = await http_client.get(url, follow_redirects=True)
            audio_file = io.BytesIO(resp.content)
            audio_file.name = "audio.ogg" 
            transcription = await cliente_whisper.audio.transcriptions.create(model="whisper-1", file=audio_file)
            return transcription.text
        except: return "[Erro ao transcrever áudio]"

async def processar_ia_e_responder(account_id: int, conversation_id: int, contact_id: int, slug: str, nome_cliente: str, lock_val: str):
    chave_lock = f"lock:{conversation_id}"
    watchdog = asyncio.create_task(renovar_lock(chave_lock, lock_val))
    
    try:
        await asyncio.sleep(2) # Buffer de digitação
        
        chave_buffet = f"buffet:{conversation_id}"
        mensagens_acumuladas = await redis_client.lrange(chave_buffet, 0, -1)
        await redis_client.delete(chave_buffet)
        if not mensagens_acumuladas: return

        textos, tasks_audio, imagens_urls = [], [], []
        for m_json in mensagens_acumuladas:
            m = json.loads(m_json)
            if m.get("text"): textos.append(m["text"])
            for f in m.get("files", []):
                if f["type"] == "audio": tasks_audio.append(transcrever_audio(f["url"]))
                elif f["type"] == "image": imagens_urls.append(f["url"])
        
        pergunta_final = " ".join(textos + list(await asyncio.gather(*tasks_audio))).strip()
        if not pergunta_final and not imagens_urls: return

        await bd_salvar_mensagem_local(conversation_id, "user", pergunta_final or "[Enviou uma imagem]")

        # Carrega Unidade e Personalidade
        unidade = await carregar_unidade(slug) or {}
        pers = await carregar_personalidade(slug) or {}
        nome_ia = pers.get('nome_ia') or 'Assistente Virtual'
        estado_atual = descomprimir_texto(await redis_client.get(f"estado:{conversation_id}")) or "neutro"
        
        texto_lower_fast = pergunta_final.lower()
        fast_reply = None
        
        # ⚡ FAST-PATH OTIMIZADO (Sem bloqueio de tamanho)
        if unidade and not imagens_urls:
            end_banco = unidade.get('endereco') or unidade.get('location') or unidade.get('localizacao')
            hor_banco = unidade.get('horario_funcionamento') or unidade.get('horarios')
            pre_banco = unidade.get('valor_planos') or unidade.get('planos')
            link_mat = unidade.get('link_matricula') or unidade.get('site')
            
            if re.search(r"(endere[cç]o|onde fica|localiza[cç][aã]o|fica onde|qual o local|como chego)", texto_lower_fast):
                if end_banco and str(end_banco).strip().lower() not in ['não informado', 'none', '']:
                    fast_reply = f"📍 *Nossa unidade fica em:*\n{end_banco}\n\nPosso te ajudar com mais alguma dúvida?"
            
            elif re.search(r"(hor[aá]rio|funcionamento|abre|fecha|que horas|t[aá] aberto)", texto_lower_fast):
                if hor_banco and str(hor_banco).strip().lower() not in ['não informado', 'none', '']:
                    fast_reply = f"🕒 *Nosso horário de funcionamento é:*\n{hor_banco}\n\nSe quiser, posso te ajudar com nossos planos também! 💪"

            elif re.search(r"(pre[cç]o|valor|quanto custa|mensalidade|planos|promo[cç][aã]o)", texto_lower_fast):
                if pre_banco and str(pre_banco).strip().lower() not in ['não informado', 'none', '']:
                    fast_reply = f"💰 *Sobre nossos planos:*\n{pre_banco}\n\nVocê pode ver todos os detalhes e garantir sua vaga aqui: {link_mat}"

        # Decisão: IA ou Fast-Path
        if fast_reply:
            logger.info(f"⚡ FAST-PATH Ativado para a conversa {conversation_id}")
            resposta_texto = fast_reply
            novo_estado = estado_atual
        else:
            # Fluxo IA Gemini
            faq = await carregar_faq_unidade(slug) or ""
            historico = await bd_obter_historico_local(conversation_id) or "Sem histórico."
            
            dados_unidade_txt = "\n".join([f"{k}: {v}" for k, v in unidade.items() if v and str(v).lower() not in ['não informado', 'none', '']])
            
            prompt_sistema = f"""Você é {nome_ia}, assistente virtual da unidade {unidade.get('nome', 'Matriz')}.
            Personalidade: {pers.get('tom_voz', 'Profissional e educado')}
            Instruções: {pers.get('instrucoes_base', 'Tire dúvidas sobre os serviços.')}
            Regras: {pers.get('regras_atendimento', 'Seja breve. Não invente dados.')}
            
            DADOS DA UNIDADE:
            {dados_unidade_txt}

            FAQ:
            {faq}
            
            Cliente: {nome_cliente} | Estado Atual: {estado_atual}
            
            Responda em formato JSON: {{"resposta": "mensagem formatada", "estado": "sentimento em 1 palavra"}}"""

            conteudo_usuario = [{"type": "text", "text": f"Histórico:\n{historico}\n\nCliente: {pergunta_final}"}]
            for img_url in imagens_urls:
                try:
                    resp = await http_client.get(img_url, headers={"api_access_token": CHATWOOT_TOKEN}, follow_redirects=True)
                    img_b64 = base64.b64encode(resp.content).decode("utf-8")
                    conteudo_usuario.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}})
                except: pass

            modelo = "google/gemini-2.5-flash" if imagens_urls else "google/gemini-2.5-flash-lite"
            
            async with llm_semaphore:
                response = await cliente_ia.chat.completions.create(
                    model=modelo, messages=[{"role": "system", "content": prompt_sistema}, {"role": "user", "content": conteudo_usuario}],
                    temperature=0.7, response_format={"type": "json_object"}
                )
                
            try:
                dados_ia = json.loads(response.choices[0].message.content)
                resposta_texto = dados_ia.get("resposta", "Desculpe, não consegui processar a informação.")
                novo_estado = dados_ia.get("estado", estado_atual).strip().lower()
            except:
                resposta_texto = response.choices[0].message.content
                novo_estado = estado_atual

        # Atualiza Redis
        await redis_client.setex(f"estado:{conversation_id}", 86400, comprimir_texto(novo_estado))
        if "interessado" in novo_estado or "matricula" in novo_estado:
            await bd_registrar_evento_funil(conversation_id, "interesse_detectado", f"Estado: {novo_estado}")

        await bd_salvar_mensagem_local(conversation_id, "assistant", resposta_texto)

        # Envio em pedaços simulando humano
        is_manual = (await redis_client.get(f"atend_manual:{conversation_id}")) == "1"
        pedacos = [p.strip() for p in resposta_texto.split("\n") if p.strip()]
        
        for p in pedacos:
            if is_manual or await redis_client.exists(f"pause_ia:{conversation_id}"): break
            await asyncio.sleep(min(len(p) * 0.04, 3) + random.uniform(0.5, 1.0))
            await enviar_mensagem_chatwoot(account_id, conversation_id, p, nome_ia)
            await bd_atualizar_metricas(conversation_id, "assistant")
        
        if not is_manual:
            await agendar_followups(conversation_id, account_id, slug)

    except Exception as e:
        logger.error(f"🔥 Erro Crítico: {e}", exc_info=True)
    finally:
        watchdog.cancel()
        try: await redis_client.eval(LUA_RELEASE_LOCK, 1, chave_lock, lock_val)
        except: pass

# --- WEBHOOK ENDPOINT ---
async def validar_assinatura(request: Request, signature: str):
    if not CHATWOOT_WEBHOOK_SECRET: return
    body = await request.body()
    expected = hmac.new(CHATWOOT_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature or "", expected): raise HTTPException(status_code=401, detail="Assinatura inválida")

@app.post("/webhook")
async def chatwoot_webhook(request: Request, background_tasks: BackgroundTasks, x_chatwoot_signature: str = Header(None)):
    await validar_assinatura(request, x_chatwoot_signature)
    payload = await request.json()
    
    event = payload.get("event")
    id_conv = payload.get("conversation", {}).get("id") or payload.get("id")
    account_id = payload.get("account", {}).get("id")

    if await redis_client.incr(f"rate:{id_conv}") > 10: return {"status": "rate_limit"}
    await redis_client.expire(f"rate:{id_conv}", 10)

    conv_obj = payload.get("conversation", {}) if "conversation" in payload else payload
    if conv_obj:
        is_manual = "1" if (conv_obj.get("assignee_id") is not None or conv_obj.get("status") not in ["pending", "open", None]) else "0"
        await redis_client.setex(f"atend_manual:{id_conv}", 86400, is_manual)

    if event == "conversation_updated":
        if conv_obj.get("status") == "resolved":
            if db_pool: await db_pool.execute("UPDATE conversas_ia SET encerrada_em = NOW() WHERE conversation_id = $1", id_conv)
            await redis_client.delete(f"pause_ia:{id_conv}", f"estado:{id_conv}", f"unidade_escolhida:{id_conv}", f"esperando_unidade:{id_conv}")
        return {"status": "conversa_atualizada"}

    if event != "message_created": return {"status": "ignorado"}

    message_type = payload.get("message_type")
    sender_type = payload.get("sender", {}).get("type", "").lower()
    is_ai_message = (payload.get("content_attributes") or {}).get("origin") == "ai"
    conteudo_texto = payload.get("content", "").strip()

    slug = await redis_client.get(f"unidade_escolhida:{id_conv}")

    # ========================================================
    # 🧠 ROTEAMENTO: O MENU INTELIGENTE DE UNIDADES
    # ========================================================
    if not slug and message_type == "incoming":
        unidades_ativas = await listar_unidades_ativas()
        
        if not unidades_ativas:
            return {"status": "sem_unidades_ativas"}
            
        # Caso 1: Só existe 1 unidade no sistema. Pula o menu.
        elif len(unidades_ativas) == 1:
            slug = unidades_ativas[0]["slug"]
            await redis_client.setex(f"unidade_escolhida:{id_conv}", 86400, slug)
            
        # Caso 2: Existem várias unidades.
        else:
            unidade_selecionada = None
            
            # Verifica se o cliente mandou o NÚMERO do menu
            if conteudo_texto.isdigit():
                idx = int(conteudo_texto) - 1
                if 0 <= idx < len(unidades_ativas):
                    unidade_selecionada = unidades_ativas[idx]
            
            # Verifica se o cliente mandou o NOME da unidade
            if not unidade_selecionada:
                for u in unidades_ativas:
                    if u["nome"].lower() in conteudo_texto.lower() or similar(conteudo_texto, u["nome"]) > 0.8:
                        unidade_selecionada = u
                        break

            # Se encontrou a unidade escolhida, salva no Redis e continua
            if unidade_selecionada:
                slug = unidade_selecionada["slug"]
                await redis_client.setex(f"unidade_escolhida:{id_conv}", 86400, slug)
                await redis_client.delete(f"esperando_unidade:{id_conv}")
                await bd_iniciar_conversa(id_conv, slug)
                logger.info(f"✅ Unidade escolhida: {slug}")
                
                # Se ele só mandou o número, avisa e pede a dúvida dele
                if conteudo_texto.isdigit():
                    await enviar_mensagem_chatwoot(account_id, id_conv, f"Ótimo! Você escolheu a unidade *{unidade_selecionada['nome']}*.\nComo posso te ajudar hoje?")
                    return {"status": "unidade_confirmada_aguardando_duvida"}
            
            # Se NÃO encontrou, envia o MENU NUMERADO e trava.
            else:
                menu = "Olá! 😊 Para te atender melhor, de qual unidade você deseja falar?\n\n"
                for i, u in enumerate(unidades_ativas):
                    menu += f"*{i+1}.* {u['nome']}\n"
                menu += "\n👇 *Digite o NÚMERO ou o NOME da unidade:*"
                
                await enviar_mensagem_chatwoot(account_id, id_conv, menu)
                await redis_client.setex(f"esperando_unidade:{id_conv}", 86400, "1")
                background_tasks.add_task(monitorar_escolha_unidade, account_id, id_conv)
                return {"status": "menu_enviado_aguardando_escolha"}

    if not slug: return {"status": "erro_sem_unidade"}

    # Controle de Pausa Humana
    if message_type == "outgoing" and sender_type == "user":
        if not is_ai_message: 
            await redis_client.setex(f"pause_ia:{id_conv}", 43200, "1")
        return {"status": "ignorado"}

    if message_type != "incoming" or await redis_client.exists(f"pause_ia:{id_conv}"): 
        return {"status": "ignorado"}

    await bd_iniciar_conversa(id_conv, slug)
    await bd_atualizar_metricas(id_conv, "user")

    anexos = payload.get("attachments") or payload.get("message", {}).get("attachments", [])
    arquivos = [{"url": a.get("data_url"), "type": "image" if "image" in str(a.get("file_type", "")).lower() else "audio"} for a in anexos]

    chave_buffet = f"buffet:{id_conv}"
    await redis_client.rpush(chave_buffet, json.dumps({"text": conteudo_texto, "files": arquivos}))
    await redis_client.expire(chave_buffet, 60)

    lock_val = str(uuid.uuid4())
    if await redis_client.set(f"lock:{id_conv}", lock_val, nx=True, ex=60):
        background_tasks.add_task(processar_ia_e_responder, account_id, id_conv, payload.get("sender", {}).get("id"), slug, limpar_nome(payload.get("sender", {}).get("name")), lock_val)
    
    return {"status": "processando"}

@app.get("/desbloquear/{conversation_id}")
async def desbloquear_ia(conversation_id: int):
    if await redis_client.delete(f"pause_ia:{conversation_id}"):
        return {"status": "sucesso", "mensagem": "✅ IA reativada!"}
    return {"status": "aviso"}

@app.get("/")
async def health(): 
    return {"status": "🤖 Motor Multi-Tenant SaaS Top de Linha! 🚀"}
