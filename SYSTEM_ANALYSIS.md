# Antigravity IA — Analise do Sistema & Sugestoes de Melhoria

> Analise realizada em 27/03/2026 sobre a arquitetura completa do projeto.

---

## Resumo Executivo

O sistema e funcional e esta em producao, mas carrega divida tecnica significativa. As areas mais criticas sao: tratamento de erros, monolitismo do `main.py`, ausencia de testes, e potenciais gargalos de performance em escala.

---

## 1. CRITICO (Impacto direto em estabilidade)

### 1.1 Error Handling — 106+ `except Exception: pass`
**Onde:** `bot_core.py`, `flow_executor.py`, `management.py`, `workers.py`
**Problema:** Erros sao silenciados, tornando debugging em producao quase impossivel.
**Solucao:** Substituir por excecoes especificas + logging com contexto:
```python
# ANTES
try:
    result = await chamar_ia(...)
except Exception:
    pass

# DEPOIS
try:
    result = await chamar_ia(...)
except asyncio.TimeoutError:
    logger.warning(f"LLM timeout empresa={empresa_id} phone={phone}")
except httpx.HTTPStatusError as e:
    logger.error(f"LLM HTTP error {e.response.status_code} empresa={empresa_id}")
```

### 1.2 main.py Monolitico — 4.973 linhas
**Problema:** Middleware, rate limiting, startup logic, webhook handlers e utilidades num unico arquivo.
**Solucao:** Dividir em modulos:
- `src/middleware/rate_limit.py`
- `src/middleware/cors.py`
- `src/core/startup.py` (lifespan, pool init)
- `src/api/routers/webhook.py` (ja parcialmente feito)

### 1.3 Zero Testes
**Problema:** Nenhum teste unitario ou de integracao. Mudancas em producao sao arriscadas.
**Solucao imediata:**
- Testes para `_build_playground_prompt()` (funcao pura, facil de testar)
- Testes para flow_executor node routing
- Testes de integracao para webhook pipeline (mock do LLM)
- Estimativa: 1-2 dias para cobertura basica dos caminhos criticos

### 1.4 Database Queries sem Timeout
**Onde:** `db_queries.py` — todas as queries usam `await pool.fetch(...)` sem timeout
**Risco:** Uma query lenta trava o worker inteiro
**Solucao:**
```python
async with pool.acquire() as conn:
    result = await asyncio.wait_for(conn.fetch(query, *args), timeout=10)
```

---

## 2. ALTO (Impacto em performance e seguranca)

### 2.1 Structured Logging
**Problema:** Logs usam emojis e formato livre — impossivel filtrar/agregar no Grafana.
```
# Atual
logger.info("✅ Mensagem enviada com sucesso para 5511999...")
# Ideal
logger.info("message_sent", extra={"phone": "5511999...", "empresa_id": 1, "latency_ms": 230})
```
**Solucao:** Adotar JSON logging com `python-json-logger` ou `structlog`.

### 2.2 Rate Limiting nas Rotas `/management/`
**Problema:** Hoje so existe rate limit no webhook. Rotas de gestao (CRUD de personalidade, FAQ, flows) nao tem limite.
**Risco:** Um script automatizado pode sobrecarregar o banco.
**Solucao:** Adicionar `slowapi` ou middleware customizado com Redis (ja disponivel).

### 2.3 Connection Pool Subdimensionado
**Onde:** `database.py` — pool min=2, max=10
**Problema:** Em picos de trafego, todas as conexoes ficam ocupadas e requests ficam em fila.
**Solucao:** Aumentar para min=5, max=30 e monitorar `pool.get_size()` / `pool.get_idle_size()`.

### 2.4 Indices SQL Faltantes
**Tabelas afetadas:** `conversas`, `mensagens_locais`, `followups`
**Indices recomendados:**
```sql
CREATE INDEX idx_conversas_empresa_phone ON conversas(empresa_id, phone);
CREATE INDEX idx_conversas_empresa_created ON conversas(empresa_id, created_at DESC);
CREATE INDEX idx_mensagens_conversa_id ON mensagens_locais(conversa_id, created_at DESC);
CREATE INDEX idx_followups_status ON followups(status, scheduled_at) WHERE status = 'pending';
```

### 2.5 Redis Fallback In-Memory Sem Limite
**Onde:** `redis_client.py` — `_LOCAL_REDIS_FALLBACK = {}`
**Problema:** Se Redis cair, o dict cresce indefinidamente em memoria.
**Solucao:** Usar `cachetools.TTLCache(maxsize=1000, ttl=300)` como fallback.

---

## 3. MEDIO (Manutenibilidade e escalabilidade)

### 3.1 Batch Queries no bot_core
**Problema:** Pipeline chama sequencialmente:
```python
await carregar_integracao(empresa_id)    # 1 query
await carregar_personalidade(empresa_id)  # 1 query
await listar_unidades_ativas(empresa_id)  # 1 query
```
**Solucao:** Usar `asyncio.gather()` para paralelizar, ou criar uma query combinada.

### 3.2 Flow Executor — Modularizacao
**Problema:** 1.286 linhas com handlers de 30+ tipos de nos no mesmo arquivo.
**Solucao:** Criar `src/services/flow_nodes/` com um arquivo por tipo de no:
```
flow_nodes/
  text_node.py
  menu_node.py
  ia_classify_node.py
  switch_node.py
  ...
```

### 3.3 API Versioning
**Problema:** Nenhum prefixo de versao (`/v1/`). Mudancas breaking afetam todos os clientes.
**Solucao:** Mover routers para `/api/v1/` e manter backwards-compat.

### 3.4 bot_core.py — 2.560 linhas
**Problema:** Pipeline de IA, detecao de tipo de cliente, follow-ups, formatacao de resposta — tudo junto.
**Solucao:** Extrair em:
- `src/services/intent_classifier.py`
- `src/services/response_formatter.py`
- `src/services/followup_scheduler.py`

---

## 4. BAIXO (Nice-to-have)

### 4.1 Feature Flags
Para rollouts graduais de novas funcionalidades (ex: novo modelo de IA, novo tipo de no).
Opcoes: `flipper` (Redis-based) ou tabela `feature_flags` no banco.

### 4.2 Audit Log
Registrar quem editou personalidades, FAQs, flows. Util para equipes com multiplos operadores.
Tabela: `audit_log(id, user_id, empresa_id, action, entity_type, entity_id, changes_json, created_at)`.

### 4.3 Soft Deletes
Atualmente `DELETE` remove permanentemente. Adicionar coluna `deleted_at` para recuperacao.

### 4.4 Health Check Aprimorado
Endpoint `/health` que verifica:
- PostgreSQL conectado
- Redis conectado
- OpenRouter acessivel
- Ultima mensagem processada < 5 min

### 4.5 Webhook Retry Queue
Quando o envio de resposta para Chatwoot/UazAPI falha, nao ha retry.
Usar Redis Streams ou tabela `outbox` para retry automatico com backoff.

---

## 5. Metricas de Codigo

| Metrica | Valor | Avaliacao |
|---------|-------|-----------|
| Maior arquivo | 4.973 linhas (main.py) | Critico — dividir |
| Maior servico | 2.560 linhas (bot_core) | Alto — modularizar |
| `except Exception` | 106+ ocorrencias | Critico — especificar |
| Cobertura de testes | 0% | Critico — criar |
| Servicos totais | ~7.500 linhas | Aceitavel |
| Componentes frontend | 52+ (flow editor) | Bom |
| Migrations Alembic | 24 arquivos | Saudavel |

---

## 6. Proximos Passos Recomendados

1. **Semana 1:** Adicionar indices SQL + aumentar pool + fix top 10 bare excepts
2. **Semana 2:** Dividir main.py + adicionar structured logging
3. **Semana 3:** Criar testes basicos (playground, flow_executor, webhook)
4. **Semana 4:** Modularizar bot_core.py + flow_executor
5. **Continuo:** Implementar feature flags + audit log conforme necessidade
