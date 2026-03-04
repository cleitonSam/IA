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

# --- UTILITÁRIOS DE COMPRESSÃO E FUZZY MATCHING ---
def comprimir_texto(texto: str) -> str:
    if not texto: return ""
    dados = zlib.compress(texto.encode('utf-8'))
    return base64.b64encode(dados).decode('utf-8')

def descomprimir_texto(texto_comprimido: str) -> str:
    if not texto_comprimido: return ""
    try:
        dados = base64.b64decode(texto_comprimido)
        return zlib.decompress(dados).decode('utf-8')
    except:
        return texto_comprimido 

def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

# --- RENOVAÇÃO DE LOCK (WATCHDOG) ---
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

# --- SISTEMA DE FOLLOW-UP DINÂMICO (TEMPLATES) ---
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

        if templates:
            logger.info(f"📅 {len(templates)} followups agendados para conv {conversation_id} (Unidade: {slug})")
    except Exception as e:
        logger.error(f"Erro ao agendar followups: {e}")

async def worker_followup():
    logger.info("🤖 Worker de Follow-up Enterprise iniciado.")
    while True:
        await asyncio.sleep(30) 
        if not db_pool: continue
        
        try:
            agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
            pendentes = await db_pool.fetch("SELECT * FROM followups WHERE status = 'pendente' AND agendado_para <= $1 ORDER BY agendado_para LIMIT 20", agora)
            
            for f in pendentes:
                is_manual = await redis_client.get(f"atend_manual:{f['conversation_id']}")
                is_paused = await redis_client.get(f"pause_ia:{f['conversation_id']}")
                
                if is_manual == "1" or is_paused == "1":
                    await db_pool.execute("UPDATE followups SET status = 'cancelado' WHERE id = $1", f['id'])
                    continue

                respondeu = await db_pool.fetchval("""
                    SELECT 1 FROM mensagens_local WHERE conversation_id = $1 AND role = 'user' AND created_at > NOW() - interval '5 minutes'
                """, f["conversation_id"])

                if respondeu:
                    await db_pool.execute("UPDATE followups SET status = 'cancelado' WHERE id = $1", f["id"])
                    logger.info(f"🚫 Followup cancelado para conv {f['conversation_id']} (Cliente já respondeu).")
                    continue

                template = await db_pool.fetchrow("SELECT mensagem FROM followup_templates WHERE id = $1", f["template_id"])
                if not template:
                    await db_pool.execute("UPDATE followups SET status = 'erro', erro_log = 'Template não encontrado' WHERE id = $1", f['id'])
                    continue

                msg_followup = template["mensagem"]
                url_m = f"{CHATWOOT_URL}/api/v1/accounts/{f['account_id']}/conversations/{f['conversation_id']}/messages"
                res = await http_client.post(url_m, json={
                    "content": msg_followup, "message_type": "outgoing",
                    "content_attributes": {"origin": "ai", "ai_agent": "Assistente Virtual", "ignore_webhook": True}
                }, headers={"api_access_token": CHATWOOT_TOKEN})
                
                if res.status_code < 300:
                    await db_pool.execute("UPDATE followups SET status = 'enviado', enviado_em = NOW() WHERE id = $1", f['id'])
                else:
                    await db_pool.execute("UPDATE followups SET status = 'erro', erro_log = $2 WHERE id = $1", f['id'], res.text)

        except Exception as e:
            logger.error(f"Erro no worker de follow-up: {e}")

# --- BACKGROUND JOBS (TIMEOUTS) ---
async def monitorar_escolha_unidade(account_id: int, conversation_id: int):
    await asyncio.sleep(120) 
    if not await redis_client.exists(f"esperando_unidade:{conversation_id}"): return
    if await redis_client.exists(f"unidade_escolhida:{conversation_id}"): return

    url_m = f"{CHATWOOT_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
    await http_client.post(url_m, json={
        "content": "Só confirmando 🙂 qual unidade você deseja?",
        "message_type": "outgoing",
        "content_attributes": {"origin": "ai", "ai_agent": "Assistente Virtual", "ignore_webhook": True}
    }, headers={"api_access_token": CHATWOOT_TOKEN})

    await asyncio.sleep(480) 
    if not await redis_client.exists(f"esperando_unidade:{conversation_id}"): return
    if await redis_client.exists(f"unidade_escolhida:{conversation_id}"): return

    await redis_client.delete(f"esperando_unidade:{conversation_id}")
    url_c = f"{CHATWOOT_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}"
    await http_client.put(url_c, json={"status": "resolved"}, headers={"api_access_token": CHATWOOT_TOKEN})
    logger.info(f"⏳ Conversa {conversation_id} fechada por inatividade.")

# --- FUNÇÕES DE BUSCA DINÂMICA (SAAS) ---
async def listar_unidades_ativas():
    if not db_pool: return []
    try:
        rows = await db_pool.fetch("SELECT slug, nome, palavras_chave FROM unidades_config WHERE ativa = TRUE ORDER BY nome")
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Erro ao listar unidades ativas: {e}")
        return []

async def carregar_unidade(slug: str):
    if not db_pool: return {}
    cache_key = f"cfg:unidade:{slug}"
    cache = await redis_client.get(cache_key)
    if cache:
        logger.info(f"⚡ [CACHE REDIS] Unidade '{slug}' carregada da memória.")
        return json.loads(cache)
    try:
        row = await db_pool.fetchrow("SELECT * FROM unidades_config WHERE slug = $1 AND ativa = TRUE", slug)
        if row:
            dados = dict(row)
            await redis_client.setex(cache_key, 300, json.dumps(dados, default=str)) 
            logger.info(f"🐘 [POSTGRES] Unidade '{slug}' carregada direto do banco.")
            return dados
        logger.warning(f"⚠️ [ALERTA] Unidade '{slug}' NÃO ENCONTRADA no banco ou ativa=FALSE!")
        return {}
    except Exception as e:
        logger.error(f"Erro BD ao carregar unidade '{slug}': {e}")
        return {}

async def carregar_faq_unidade(slug: str):
    if not db_pool: return ""
    cache_key = f"cfg:faq:{slug}"
    cache = await redis_client.get(cache_key)
    if cache: return cache
    try:
        rows = await db_pool.fetch("SELECT pergunta, resposta FROM faq_unidades WHERE slug_unidade = $1 AND ativo = TRUE ORDER BY prioridade DESC", slug)
        faq_formatado = "".join([f"\nPergunta: {r['pergunta']}\nResposta: {r['resposta']}\n" for r in rows]).strip()
        if faq_formatado: await redis_client.setex(cache_key, 300, faq_formatado)
        return faq_formatado
    except Exception: return ""

async def carregar_personalidade(slug: str):
    if not db_pool: return {}
    cache_key = f"cfg:pers:{slug}"
    cache = await redis_client.get(cache_key)
    if cache: return json.loads(cache)
    try:
        row = await db_pool.fetchrow("SELECT * FROM personalidade_ia WHERE slug_unidade = $1 LIMIT 1", slug)
        if row:
            dados = dict(row)
            await redis_client.setex(cache_key, 300, json.dumps(dados, default=str))
            return dados
        return {}
    except Exception: return {}

async def carregar_configuracao_global():
    if not db_pool: return {}
    cache_key = "cfg:global"
    cache = await redis_client.get(cache_key)
    if cache: return json.loads(cache)
    try:
        row = await db_pool.fetchrow("SELECT * FROM configuracoes_gerais ORDER BY id ASC LIMIT 1")
        if row:
            dados = dict(row)
            await redis_client.setex(cache_key, 3600, json.dumps(dados, default=str)) 
            return dados
        return {}
    except Exception: return {}

# --- IA: CLASSIFICADOR DE UNIDADE (Zero-Shot) ---
async def ia_detectar_unidade(mensagem_cliente: str, unidades: list) -> str:
    lista_nomes = "\n".join([f"- {u['nome']} (slug: {u['slug']})" for u in unidades])
    prompt = f"""Você é um classificador de intenção. Sua missão é descobrir se o cliente citou o nome de uma das unidades abaixo.
    UNIDADES:
    {lista_nomes}
    MENSAGEM DO CLIENTE: "{mensagem_cliente}"
    Se ele citou, retorne APENAS o 'slug' exato da unidade. Se não, retorne: NULL
    """
    try:
        response = await cliente_ia.chat.completions.create(
            model="google/gemini-2.5-flash-lite", 
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0, max_tokens=10
        )
        resultado = response.choices[0].message.content.strip()
        if resultado != "NULL": return resultado
    except Exception: pass
    return None

# --- AUXILIARES BANCO DE DADOS ---
def log_db_error(retry_state):
    logger.error(f"Erro BD após {retry_state.attempt_number} tentativas: {retry_state.outcome.exception()}")
    return None

@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_iniciar_conversa(conversation_id: int, unidade: str):
    if not db_pool: return
    await db_pool.execute("INSERT INTO conversas_ia (conversation_id, unidade) VALUES ($1, $2) ON CONFLICT (conversation_id) DO NOTHING", conversation_id, unidade)

@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_salvar_mensagem_local(conversation_id: int, role: str, content: str):
    if not db_pool: return
    await db_pool.execute("INSERT INTO mensagens_local (conversation_id, role, content) VALUES ($1, $2, $3)", conversation_id, role, content)

async def bd_obter_historico_local(conversation_id: int, limit: int = 30):
    if not db_pool: return None
    try:
        rows = await db_pool.fetch("SELECT role, content FROM mensagens_local WHERE conversation_id = $1 ORDER BY created_at DESC LIMIT $2", conversation_id, limit)
        msgs = reversed(rows)
        return "\n".join([f"{'Cliente' if r['role'] == 'user' else 'Atendente'}: {r['content']}" for r in msgs])
    except Exception: return None

@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_atualizar_msg_cliente(conversation_id: int):
    if not db_pool: return
    await db_pool.execute("UPDATE conversas_ia SET mensagens_cliente = mensagens_cliente + 1, updated_at = NOW() WHERE conversation_id = $1", conversation_id)

@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_atualizar_msg_ia(conversation_id: int):
    if not db_pool: return
    await db_pool.execute("UPDATE conversas_ia SET mensagens_ia = mensagens_ia + 1, updated_at = NOW() WHERE conversation_id = $1", conversation_id)

@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_registrar_primeira_resposta(conversation_id: int):
    if not db_pool: return
    existe = await db_pool.fetchval("SELECT primeira_resposta_em FROM conversas_ia WHERE conversation_id = $1", conversation_id)
    if not existe:
        await db_pool.execute("UPDATE conversas_ia SET primeira_resposta_em = NOW(), updated_at = NOW() WHERE conversation_id = $1", conversation_id)

@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_registrar_evento_funil(conversation_id: int, tipo_evento: str, descricao: str, score_incremento: int = 5):
    if not db_pool: return
    if tipo_evento == "interesse_detectado":
        existe = await db_pool.fetchval("SELECT 1 FROM eventos_conversa WHERE conversation_id = $1 AND tipo_evento = $2", conversation_id, tipo_evento)
        if existe: return
    await db_pool.execute("INSERT INTO eventos_conversa (conversation_id, tipo_evento, descricao) VALUES ($1, $2, $3)", conversation_id, tipo_evento, descricao)
    await db_pool.execute("UPDATE conversas_ia SET score = score + $2, updated_at = NOW() WHERE conversation_id = $1", conversation_id, score_incremento)
    if tipo_evento == "interesse_detectado":
        await db_pool.execute("UPDATE conversas_ia SET interesse_detectado = TRUE WHERE conversation_id = $1", conversation_id)

@retry(wait=wait_exponential(multiplier=1, min=2, max=5), stop=stop_after_attempt(3), retry_error_callback=log_db_error)
async def bd_finalizar_conversa(conversation_id: int):
    if not db_pool: return
    await db_pool.execute("UPDATE conversas_ia SET encerrada_em = NOW(), updated_at = NOW() WHERE conversation_id = $1", conversation_id)
    await db_pool.execute("UPDATE followups SET status = 'cancelado' WHERE conversation_id = $1 AND status = 'pendente'", conversation_id)

# --- PROCESSAMENTO IA E ÁUDIO ---
async def transcrever_audio(url: str):
    if not cliente_whisper: return "[Áudio recebido, mas Whisper não configurado]"
    async with whisper_semaphore: 
        try:
            resp = await http_client.get(url, follow_redirects=True)
            audio_file = io.BytesIO(resp.content)
            extensao = url.split('?')[0].split('.')[-1]
            if extensao.lower() not in ['flac', 'm4a', 'mp3', 'mp4', 'mpeg', 'mpga', 'oga', 'ogg', 'wav', 'webm']:
                extensao = 'ogg'
            audio_file.name = f"audio.{extensao}" 
            transcription = await cliente_whisper.audio.transcriptions.create(model="whisper-1", file=audio_file)
            return transcription.text
        except Exception as e:
            logger.error(f"Erro Whisper: {e}")
            return "[Erro ao transcrever áudio]"

def limpar_nome(nome):
    if not nome: return "Cliente"
    return re.sub(r"[^a-zA-ZÀ-ÿ\s]", "", str(nome)).strip()

async def processar_ia_e_responder(account_id: int, conversation_id: int, contact_id: int, slug: str, nome_cliente: str, lock_val: str):
    chave_lock = f"lock:{conversation_id}"
    watchdog = asyncio.create_task(renovar_lock(chave_lock, lock_val))
    
    try:
        await asyncio.sleep(2) 
        
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
        
        transcricoes = await asyncio.gather(*tasks_audio)
        pergunta_final = " ".join(textos + list(transcricoes)).strip()
        if not pergunta_final and not imagens_urls: return

        msg_log_local = pergunta_final if pergunta_final else "[Enviou uma imagem]"
        await bd_salvar_mensagem_local(conversation_id, "user", msg_log_local)

        unidade = await carregar_unidade(slug) or {}
        
        # --- LOGS CLAROS DE RASTREIO ---
        logger.info(f"🔎 Pergunta analisada no Buffet: '{pergunta_final}'")
        logger.info(f"📦 Dados carregados da unidade:\n{json.dumps(unidade, indent=2, ensure_ascii=False, default=str)}")
        
        estado_raw = await redis_client.get(f"estado:{conversation_id}")
        estado_atual = descomprimir_texto(estado_raw) or "neutro"
        
        texto_lower_fast = pergunta_final.lower()
        fast_reply = None
        
        # --- 🚨 MAPEAMENTO BLINDADO DE CAMPOS DO BANCO ---
        end_banco = unidade.get('endereco') or unidade.get('location')
        hor_banco = unidade.get('horario_funcionamento') or unidade.get('horarios')
        
        logger.info(f"📍 Endereço mapeado para Fast-Path: {end_banco}")
        logger.info(f"🕒 Horário mapeado para Fast-Path: {hor_banco}")
        
        # --- 🚨 TRAVA DE SEGURANÇA: Unidade Vazia ---
        if not unidade:
            logger.error(f"❌ Unidade '{slug}' não carregou corretamente. Abortando IA para evitar alucinações.")
            fast_reply = "Desculpe, estou com dificuldade para acessar os dados da unidade no momento. Um instante por favor."
            
        # --- ⚡ FAST-PATH (Bypass LLM via Regex Avançado) ---
        elif len(texto_lower_fast) < 80: # Só aplica fast-path se a pergunta for direta e curta
            if re.search(r"\b(endere[cç]o|onde fica|localiza[cç][aã]o|fica onde|qual o local)\b", texto_lower_fast):
                if end_banco and str(end_banco).strip().lower() not in ['não informado', 'nao informado', 'none', '']:
                    fast_reply = f"📍 Nossa unidade fica em:\n{end_banco}\n\nPosso te ajudar com mais alguma dúvida?"
            
            elif re.search(r"\b(hor[aá]rio|funcionamento|abre|fecha|que horas)\b", texto_lower_fast):
                if hor_banco and str(hor_banco).strip().lower() not in ['não informado', 'nao informado', 'none', '']:
                    fast_reply = f"🕒 Nosso horário de funcionamento é:\n{hor_banco}\n\nSe quiser, posso te ajudar com planos e valores também!"

        if fast_reply:
            logger.info("⚡ Fast-Path Ativado! Respondendo de forma determinística (sem IA).")
            resposta_texto = fast_reply
            novo_estado = estado_atual
        else:
            # --- 🤖 FLUXO NORMAL DA IA (PROMPT MASTER) ---
            faq = await carregar_faq_unidade(slug) or ""
            pers = await carregar_personalidade(slug) or {}
            historico = await bd_obter_historico_local(conversation_id) or "Sem histórico."
            
            nome_empresa = unidade.get('nome_empresa') or 'Nossa Empresa'
            nome_unidade = unidade.get('nome') or 'Unidade Matriz'
            link_principal = unidade.get('link_matricula') or 'nosso site oficial'
            
            dados_unidade = f"""
            DADOS COMPLETOS DA UNIDADE
            Nome da unidade: {unidade.get('nome') or 'não informado'}
            Empresa: {unidade.get('nome_empresa') or 'não informado'}

            Endereço: {end_banco or 'não informado'}
            Cidade/Estado: {unidade.get('cidade') or 'não informado'} / {unidade.get('estado') or 'não informado'}
            CEP: {unidade.get('cep') or 'não informado'}

            Telefone: {unidade.get('telefone') or 'não informado'}
            WhatsApp: {unidade.get('whatsapp') or 'não informado'}
            Email: {unidade.get('email') or 'não informado'}

            Horários (Geral): {hor_banco or 'não informado'}
            Horário sábado: {unidade.get('horario_sabado') or 'não informado'}
            Horário domingo/feriado: {unidade.get('horario_domingo') or 'não informado'}

            Link de matrícula: {unidade.get('link_matricula') or 'não informado'}
            Link do site: {unidade.get('site') or 'não informado'}
            Instagram: {unidade.get('instagram') or 'não informado'}

            Modalidades disponíveis: {unidade.get('modalidades') or 'não informado'}
            Planos disponíveis: {unidade.get('planos') or 'não informado'}
            Valor médio dos planos: {unidade.get('valor_planos') or 'não informado'}

            Possui estacionamento: {unidade.get('estacionamento') or 'não informado'}
            Possui vestiário: {unidade.get('vestiario') or 'não informado'}
            Possui chuveiro: {unidade.get('chuveiro') or 'não informado'}
            Possui armários: {unidade.get('armarios') or 'não informado'}

            Possui avaliação física: {unidade.get('avaliacao_fisica') or 'não informado'}
            Possui personal trainer: {unidade.get('personal_trainer') or 'não informado'}
            Possui aula experimental: {unidade.get('aula_experimental') or 'não informado'}

            Formas de pagamento aceitas: {unidade.get('formas_pagamento') or 'não informado'}
            Aceita Gympass: {unidade.get('gympass') or 'não informado'}
            Aceita TotalPass: {unidade.get('totalpass') or 'não informado'}

            Descrição da unidade: {unidade.get('descricao') or 'não informado'}
            Contexto adicional: {unidade.get('contexto_adicional') or 'não informado'}
            """
            
            nome_ia = pers.get('nome_ia') or 'Assistente Virtual'
            tom_voz = pers.get('tom_voz') or 'Profissional, claro e prestativo'
            instrucoes_padrao = f"Atenda o cliente de forma educada e tire dúvidas sobre os serviços da {nome_empresa}."
            instrucoes_base = pers.get('instrucoes_base') or instrucoes_padrao
            
            regras_padrao = (
                "1. Seja breve e objetivo.\n"
                "2. Se a informação existir nos DADOS DA UNIDADE, responda diretamente sem sugerir acessar o site ou ligar.\n"
                "3. Forneça respostas diretas baseadas no FAQ e nos Dados da Unidade.\n"
                "4. Formate SEMPRE sua resposta com parágrafos curtos, tópicos/listas (se aplicável) e quebras de linha para facilitar a leitura."
            )
            regras_atendimento = pers.get('regras_atendimento') or regras_padrao

            prompt_sistema = f"""Você é {nome_ia}, assistente virtual da empresa {nome_empresa} (Unidade: {nome_unidade}).
            Personalidade e Tom de Voz: {tom_voz}
            
            INSTRUÇÕES GERAIS:
            {instrucoes_base}
            
            REGRAS DE ATENDIMENTO (Siga estritamente):
            {regras_atendimento}
            * Se o cliente demonstrar intenção clara de compra ou conversão (matrícula/agendamento), direcione para o link principal: {link_principal}.
            
            {dados_unidade}

            FAQ DA UNIDADE ({nome_unidade}):
            {faq if faq else 'Nenhum FAQ cadastrado.'}
            
            DADOS DO ATENDIMENTO ATUAL:
            Nome do Cliente: {nome_cliente}
            Estado/Sentimento Anterior: {estado_atual}
            
            ---
            MUITO IMPORTANTE (CONTRATO DE SISTEMA):
            Você deve SEMPRE responder estritamente no formato JSON válido, sem markdown em volta.
            Formato exigido:
            {{
                "resposta": "a sua mensagem final formatada para o cliente",
                "estado": "qual o estado atual do cliente numa única palavra (ex: neutro, interessado, irritado, conversao)"
            }}
            """

            conteudo_usuario = []
            if pergunta_final:
                conteudo_usuario.append({"type": "text", "text": f"Histórico:\n{historico}\n\nCliente diz: {pergunta_final}"})
            else:
                conteudo_usuario.append({"type": "text", "text": f"Histórico:\n{historico}\n\nO cliente enviou uma imagem. Analise a imagem e responda adequadamente ajudando-o no contexto do atendimento."})
                
            for img_url in imagens_urls:
                try:
                    resp = await http_client.get(img_url, headers={"api_access_token": CHATWOOT_TOKEN}, follow_redirects=True)
                    if resp.status_code == 200:
                        img_b64 = base64.b64encode(resp.content).decode("utf-8")
                        mime_type = "image/png" if ".png" in img_url.lower() else "image/webp" if ".webp" in img_url.lower() else "image/jpeg"
                        conteudo_usuario.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{img_b64}"}})
                except Exception as e:
                    logger.error(f"Erro ao baixar imagem para base64: {e}")

            modelo_escolhido = "google/gemini-2.5-flash" if imagens_urls else "google/gemini-2.5-flash-lite"

            start_time = time.time()
            
            async with llm_semaphore:
                try:
                    response = await cliente_ia.chat.completions.create(
                        model=modelo_escolhido, 
                        messages=[{"role": "system", "content": prompt_sistema}, {"role": "user", "content": conteudo_usuario}],
                        temperature=0.7, timeout=30, response_format={"type": "json_object"}
                    )
                    resposta_bruta = response.choices[0].message.content
                except Exception as e:
                    logger.warning(f"Fallback para Gemini Flash devido a erro: {e}")
                    response = await cliente_ia.chat.completions.create(
                        model="google/gemini-2.5-flash",
                        messages=[{"role": "system", "content": prompt_sistema}, {"role": "user", "content": conteudo_usuario}],
                        temperature=0.7, response_format={"type": "json_object"}
                    )
                    resposta_bruta = response.choices[0].message.content
            
            logger.info(f"⏱️ LLM Latency ({modelo_escolhido}): {time.time() - start_time:.2f}s | Conv: {conversation_id}")

            try:
                dados_ia = json.loads(resposta_bruta)
                resposta_texto = dados_ia.get("resposta", "Desculpe, não consegui processar a informação.")
                novo_estado = dados_ia.get("estado", estado_atual).strip().lower()
            except json.JSONDecodeError:
                resposta_texto = resposta_bruta
                novo_estado = estado_atual

        # --- APLICAÇÃO DE DADOS (COMUM AO IA E AO FAST-PATH) ---
        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.setex(f"estado:{conversation_id}", 86400, comprimir_texto(novo_estado))
            pipe.lpush(f"hist_estado:{conversation_id}", f"{datetime.now(ZoneInfo('America/Sao_Paulo')).isoformat()}|{novo_estado}")
            pipe.ltrim(f"hist_estado:{conversation_id}", 0, 10)
            pipe.expire(f"hist_estado:{conversation_id}", 86400)
            await pipe.execute()

        if "interessado" in novo_estado or "conversao" in novo_estado or "matricula" in novo_estado:
            await bd_registrar_evento_funil(conversation_id, "interesse_detectado", f"Detetou estado: {novo_estado}")

        await bd_salvar_mensagem_local(conversation_id, "assistant", resposta_texto)

        is_manual_atendimento = (await redis_client.get(f"atend_manual:{conversation_id}")) == "1"
        pedacos = [p.strip() for p in resposta_texto.split("\n") if p.strip()]
        
        for i, p in enumerate(pedacos):
            if is_manual_atendimento or await redis_client.exists(f"pause_ia:{conversation_id}"): break
            await asyncio.sleep(min(len(p) * 0.04, 4) + random.uniform(0.5, 1.5))
            
            url_m = f"{CHATWOOT_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
            await http_client.post(url_m, json={"content": p, "message_type": "outgoing", "content_attributes": {"origin": "ai", "ai_agent": nome_ia, "ignore_webhook": True}}, headers={"api_access_token": CHATWOOT_TOKEN})
            await bd_atualizar_msg_ia(conversation_id)
            if i == 0: await bd_registrar_primeira_resposta(conversation_id)
        
        if not is_manual_atendimento:
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
    if not hmac.compare_digest(signature or "", expected):
        raise HTTPException(status_code=401, detail="Assinatura inválida")

@app.post("/webhook")
async def chatwoot_webhook(request: Request, background_tasks: BackgroundTasks, x_chatwoot_signature: str = Header(None)):
    await validar_assinatura(request, x_chatwoot_signature)
    payload = await request.json()
    
    event = payload.get("event")
    id_conv = payload.get("conversation", {}).get("id") or payload.get("id")
    account_id = payload.get("account", {}).get("id")

    rate_key = f"rate:{id_conv}"
    contador = await redis_client.incr(rate_key)
    if contador == 1: await redis_client.expire(rate_key, 10)
    if contador > 10: return {"status": "rate_limit"}

    conv_obj = payload.get("conversation", {}) if "conversation" in payload else payload
    if conv_obj:
        is_manual = "1" if (conv_obj.get("assignee_id") is not None or conv_obj.get("status") not in ["pending", "open", None]) else "0"
        await redis_client.setex(f"atend_manual:{id_conv}", 86400, is_manual)

    if event == "conversation_updated":
        if conv_obj.get("status") == "resolved":
            await bd_finalizar_conversa(id_conv)
            await redis_client.delete(f"pause_ia:{id_conv}", f"estado:{id_conv}", f"unidade_escolhida:{id_conv}", f"esperando_unidade:{id_conv}")
            return {"status": "conversa_encerrada"}
        return {"status": "conversa_atualizada"}

    if event != "message_created": return {"status": "ignorado"}

    message_type = payload.get("message_type")
    sender_type = payload.get("sender", {}).get("type", "").lower()
    content_attrs = payload.get("content_attributes") or {}
    is_ai_message = content_attrs.get("origin") == "ai"
    conteudo_texto = payload.get("content", "")

    labels = payload.get("conversation", {}).get("labels", [])
    slug = next((str(l).lower().strip() for l in labels if l), None) or await redis_client.get(f"unidade_escolhida:{id_conv}")

    # ========================================================
    # 🧠 ROTEAMENTO DINÂMICO DE UNIDADE (Rápido -> IA -> Menu)
    # ========================================================
    if not slug and message_type == "incoming":
        unidades_ativas = await listar_unidades_ativas()
        
        if not unidades_ativas:
            logger.error("❌ Nenhuma unidade ativa no sistema.")
            return {"status": "sem_unidades_ativas"}
            
        elif len(unidades_ativas) == 1:
            slug = unidades_ativas[0]["slug"]
            await redis_client.setex(f"unidade_escolhida:{id_conv}", 86400, slug)
            # Fluxo desce para processar a pergunta normalmente
            
        else:
            texto_cliente = conteudo_texto.lower().strip()
            unidade_selecionada = None
            
            # --- 1. DETECÇÃO SUPER RÁPIDA (String Match) ---
            for u in unidades_ativas:
                if u["nome"].lower() in texto_cliente:
                    unidade_selecionada = u
                    logger.info(f"⚡ Detecção rápida! Cliente citou a unidade: {u['nome']}")
                    break
            
            # --- 2. DETECÇÃO INTELIGENTE POR IA ---
            if not unidade_selecionada:
                slug_detectado_ia = await ia_detectar_unidade(texto_cliente, unidades_ativas)
                if slug_detectado_ia:
                    for u in unidades_ativas:
                        if u["slug"] == slug_detectado_ia:
                            unidade_selecionada = u
                            logger.info(f"🤖 IA classificou o cliente automaticamente para a unidade: {slug_detectado_ia}")
                            break
            
            esperando_unidade = await redis_client.get(f"esperando_unidade:{id_conv}")
            
            if esperando_unidade or unidade_selecionada:
                # --- 3. Tenta identificar por Número ---
                if not unidade_selecionada and texto_cliente.isdigit():
                    idx = int(texto_cliente) - 1
                    if 0 <= idx < len(unidades_ativas):
                        unidade_selecionada = unidades_ativas[idx]
                
                # --- 4. Tenta identificar por Fuzzy Matching ---
                if not unidade_selecionada:
                    melhor_score = 0
                    for u in unidades_ativas:
                        score_nome = similar(texto_cliente, u["nome"].lower())
                        score_pk = 0
                        if u.get("palavras_chave"):
                            pks = [p.strip().lower() for p in u["palavras_chave"].split(",")]
                            score_pk = max([similar(texto_cliente, pk) for pk in pks] + [0])
                        score_atual = max(score_nome, score_pk)
                        if score_atual > melhor_score:
                            melhor_score = score_atual
                            unidade_selecionada = u
                    if melhor_score < 0.6: 
                        unidade_selecionada = None
                        
                # ✅ SUCESSO: Achou a unidade
                if unidade_selecionada:
                    slug = unidade_selecionada["slug"]
                    await redis_client.setex(f"unidade_escolhida:{id_conv}", 86400, slug)
                    await redis_client.delete(f"esperando_unidade:{id_conv}")
                    await bd_iniciar_conversa(id_conv, slug)
                    await bd_registrar_evento_funil(id_conv, "unidade_escolhida", f"Cliente escolheu a unidade {unidade_selecionada['nome']}", score_incremento=3)
                    
                    logger.info(f"✅ Unidade definida ({slug}). Reprocessando pergunta original do cliente...")
                    # ⚠️ SEM RETURN! O fluxo continua e a pergunta vai pro Buffet para a IA/Fast-Path ler.
                
                # ❌ FALHA: Mostra a lista pedindo correção
                else:
                    cfg = await carregar_configuracao_global()
                    texto_erro = cfg.get("mensagem_erro_unidade") or "Ops! Não consegui identificar essa unidade. 😕 Por favor, digite o número ou o nome correto:"
                    nomes_unidades = "\n".join([f"{i+1}. {u['nome']}" for i, u in enumerate(unidades_ativas)])
                    mensagem = f"{texto_erro}\n\n{nomes_unidades}"
                    
                    url_m = f"{CHATWOOT_URL}/api/v1/accounts/{account_id}/conversations/{id_conv}/messages"
                    await http_client.post(url_m, json={
                        "content": mensagem, "message_type": "outgoing",
                        "content_attributes": {"origin": "ai", "ai_agent": "Assistente Virtual", "ignore_webhook": True}
                    }, headers={"api_access_token": CHATWOOT_TOKEN})
                    return {"status": "aguardando_unidade_valida"}
                    
            else:
                # 💬 PRIMEIRA VEZ: Mostra Menu
                cfg = await carregar_configuracao_global()
                boas_vindas = cfg.get("mensagem_boas_vindas") or "Olá! 😊 Seja bem-vindo."
                menu_unidades = cfg.get("mensagem_menu_unidades") or "Temos as seguintes unidades disponíveis. Qual delas você gostaria de falar?"
                
                nomes_unidades = "\n".join([f"{i+1}. {u['nome']}" for i, u in enumerate(unidades_ativas)])
                mensagem = f"{boas_vindas}\n\n{menu_unidades}\n\n{nomes_unidades}\n\n👇 Digite o **número** ou o **nome** da unidade:"
                
                url_m = f"{CHATWOOT_URL}/api/v1/accounts/{account_id}/conversations/{id_conv}/messages"
                await http_client.post(url_m, json={
                    "content": mensagem, "message_type": "outgoing",
                    "content_attributes": {"origin": "ai", "ai_agent": "Assistente Virtual", "ignore_webhook": True}
                }, headers={"api_access_token": CHATWOOT_TOKEN})
                
                await redis_client.setex(f"esperando_unidade:{id_conv}", 86400, "1")
                background_tasks.add_task(monitorar_escolha_unidade, account_id, id_conv)
                return {"status": "aguardando_escolha_unidade"}

    if not slug: return {"status": "erro_sem_unidade"}

    if message_type == "outgoing" and sender_type == "user":
        if is_ai_message: return {"status": "ignorado_mensagem_ia"}
        await redis_client.setex(f"pause_ia:{id_conv}", 43200, "1")
        if db_pool:
            await db_pool.execute("UPDATE followups SET status = 'cancelado' WHERE conversation_id = $1 AND status = 'pendente'", id_conv)
        return {"status": "ia_pausada"}

    if message_type != "incoming": return {"status": "ignorado_nao_incoming"}

    await bd_iniciar_conversa(id_conv, slug)
    await bd_atualizar_msg_cliente(id_conv)

    if await redis_client.exists(f"pause_ia:{id_conv}"): return {"status": "ignorado_ia_pausada"}

    anexos = payload.get("attachments") or payload.get("message", {}).get("attachments", [])
    arquivos_encontrados = []
    for a in anexos:
        file_type = str(a.get("file_type", "")).lower()
        tipo = "image" if file_type.startswith("image") or "image" in file_type else "audio" if file_type.startswith("audio") or "audio" in file_type else "documento"
        arquivos_encontrados.append({"url": a.get("data_url"), "type": tipo})

    chave_buffet = f"buffet:{id_conv}"
    await redis_client.rpush(chave_buffet, json.dumps({"text": conteudo_texto, "files": arquivos_encontrados}))
    await redis_client.expire(chave_buffet, 60)

    lock_val = str(uuid.uuid4())
    if await redis_client.set(f"lock:{id_conv}", lock_val, nx=True, ex=60):
        background_tasks.add_task(processar_ia_e_responder, account_id, id_conv, payload.get("sender", {}).get("id"), slug, limpar_nome(payload.get("sender", {}).get("name")), lock_val)
        return {"status": "processando"}
    
    return {"status": "acumulando_no_buffet"}

@app.get("/desbloquear/{conversation_id}")
async def desbloquear_ia(conversation_id: int):
    if await redis_client.delete(f"pause_ia:{conversation_id}"):
        return {"status": "sucesso", "mensagem": f"✅ IA reativada para a conversa {conversation_id}!"}
    return {"status": "aviso", "mensagem": f"A conversa {conversation_id} não estava pausada."}

@app.get("/")
async def health(): 
    return {"status": "🤖 Motor Multi-Tenant SaaS Escalável e Otimizado! 🚀"}
