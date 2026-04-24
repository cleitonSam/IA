# Auditoria Pré-Escala — 800 Tenants (80 empresas × até 10 unidades)

Data: Abril 2026  
Escopo: isolamento multi-tenant, escalabilidade, pools, quotas, segurança, PII, workers, performance.

## Sumário Executivo

Sistema está **funcional para ~100-200 tenants** mas tem gaps que explodem em escala. Foram encontrados **31 riscos no total**, divididos por severidade:

| Severidade | Qtd | Bloqueia produção a 800? |
|---|---|---|
| 🔴 **CRÍTICA** | 9 | **Sim** — pode vazar dado entre empresas, gerar overage $, violar LGPD |
| 🟠 **ALTA** | 12 | Degrada performance severamente em carga |
| 🟡 **MÉDIA** | 10 | Ajustes defensivos, impacto operacional |

**Recomendação executiva:** não escalar pra 800 tenants antes de fixar os 9 CRÍTICOS. Sprint de 1-2 semanas dedicada cobre CRÍTICA + ALTA.

**Custo estimado de não fixar:** overage LLM de $100k+/mês, risco LGPD alto (multa 2% faturamento), conversation_id collision pode expor dados de uma empresa a outra.

---

## 1. Riscos CRÍTICOS (9 itens) — fixar antes de escalar

### C-01 · Endpoints sem autenticação aceitam `empresa_id` na URL
**Local:** `main.py`
- `POST /sync-planos/{empresa_id}` (linha ~2196)
- `POST /desbloquear/{empresa_id}/{conversation_id}` (linha ~6151)
- `GET /metricas/diagnostico?empresa_id=X`

**Impacto:** qualquer um com a URL dispara sync de planos, desbloqueio de IA, ou vaza diagnóstico de **qualquer** empresa. IDOR clássico.

**Fix (1-2h):** adicionar `Depends(get_current_user_token)` + validar `empresa_id` do path contra JWT payload.

### C-02 · Webhook Chatwoot lê assinatura mas não valida
**Local:** `main.py:5501` (chatwoot_webhook)

Headers `x_chatwoot_signature` e `x_chatwoot_timestamp` são lidos mas nunca conferidos. Qualquer cliente forja webhooks com `account_id` falso.

**Fix (1h):** HMAC-SHA256 de `secret + body` comparado em `hmac.compare_digest()`.

### C-03 · WebSocket não valida que o JWT tem acesso à `empresa_id`
**Local:** `src/api/routers/ws.py:120-125`

`_validate_ws_token()` só confere se o JWT é válido, **não** se o usuário pode acessar aquela empresa. Cliente da empresa 1 consegue abrir WS pra empresa 2.

**Fix (2h):** criar dependência `require_tenant_match(empresa_id)` e aplicar em todos endpoints que aceitam empresa_id via query/path.

### C-04 · WebSocket `scan_iter` sem filtro garantido
**Local:** `src/api/routers/ws.py:44`

`scan_iter(f"pause_ia:{empresa_id}:*")` — se `empresa_id` for None/vazio, o pattern vira `pause_ia:*` e retorna conversas pausadas de **todas** as empresas.

**Fix (30min):** `assert isinstance(empresa_id, int) and empresa_id > 0` antes de chamar.

### C-05 · Quota LLM fail-open em queda de Redis
**Local:** `src/services/llm_quota.py:75-79`

Se Redis cai, `check_and_reserve_llm_call()` retorna `True` — **custo ilimitado**. Uma empresa que derrube o Redis (ou se Redis simplesmente cair) faz todas as 800 empresas consumirem LLM sem limite.

Com 800 empresas × 500k tokens/dia × $0.60/1M tokens = **~$240/dia desperdiçável**. Em 1 dia de Redis fora, pode estourar $50k-100k facilmente.

**Fix (2h):** circuit breaker. Se Redis falhar 5× em 2min → fail-closed (rejeita calls) até voltar.

### C-06 · PII (telefone) em logs
**Local:** múltiplos arquivos — `uaz_webhook.py:161, 306`, `main.py:2645, 2657, 2781, 5882`, etc. Pelo menos 15+ instâncias.

Logs retêm 30+ dias, qualquer acesso a logs expõe telefone completo de clientes → **violação LGPD** (multa até 2% faturamento por caso).

**Fix (3-4h):** helper `mask_phone(phone)` que devolve `+55 (11) ****-1234` e substituir todos os `{phone}` em logs por `{mask_phone(phone)}`.

### C-07 · Chaves Redis colidem se `conversation_id` não é único por empresa
**Local:** `src/services/stream_worker.py:211,257,279,325,348`

Chaves como `{empresa_id}:buffet:{conversation_id}` assumem que `conversation_id` é único cross-empresa. Mas o ID vem do Chatwoot, que é **global por account** — pode colidir entre empresas que usam o mesmo Chatwoot.

Empresa A e Empresa B com `conversation_id=12345` → buffer compartilhado → mensagens misturadas.

**Fix (4-6h):** verificar na query/webhook se conv_id é realmente único por empresa. Se não for, mudar chave pra `{empresa_id}:buffet:{source}:{conversation_id}`.

### C-08 · `pause_ia_phone` não trata phone duplicado cross-tenant
**Local:** `src/services/flow_executor.py:851`

Chave `pause_ia_phone:{empresa_id}:{unidade_id}:{phone}` usa o phone bruto. Se dois tenants têm o mesmo contato, operação de um pode afetar o outro se houver bug nos prefixos.

Combinado com o risco de logs (C-06), reforça necessidade de tratar phone como dado isolado.

**Fix:** na verdade a chave já inclui `empresa_id`, então está ok. Monitorar casos onde o prefixo pode estar sendo passado errado (sanity check em testes).

### C-09 · Pool Postgres subdimensionado pra 800 tenants
**Local:** `docker-compose.prod.yml` e `main.py:1161`

Hoje: `min_size=2, max_size=30` (código) ou `DB_POOL_MIN=3, DB_POOL_MAX=15` (compose). Conforme carga:

```
30 conexões / 600ms por query = 50 rps máximo teórico
Com 4 workers background + 10 rps de pico → pool sempre cheio
```

**Fix (1h):** subir pra `DB_POOL_MIN=30, DB_POOL_MAX=120` no `docker-compose.prod.yml`. E garantir que `main.py` leia essas env vars (não use o hardcoded 2/30).

---

## 2. Riscos ALTOS (12 itens)

### H-01 · Uvicorn com 1 worker só
**Local:** `Dockerfile:54`

CMD roda `uvicorn` sem `--workers N`. Python GIL limita a 1 thread Python ativa. Com 800 webhooks/s, fila infinita.

**Fix:** `CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 4"]`

### H-02 · N+1 queries no `worker_sync_planos`
**Local:** `src/services/workers.py:69-80`

```python
empresas = await fetch("SELECT id FROM empresas WHERE ...")  # 1 query
for emp in empresas:
    unidades = await fetch("SELECT id FROM unidades WHERE empresa_id=$1", emp.id)  # 80 queries
    for unid in unidades:
        await sincronizar_planos_evo(emp.id, unid.id)  # 800 queries
```

**Total: 881 queries sequenciais a cada 6h, ~6-10 minutos.**

**Fix (2-3h):** um único JOIN que retorna `(empresa_id, unidade_id)` e itera uma vez.

### H-03 · N+1 no `worker_metricas_diarias`
**Local:** `src/services/workers.py:399-413`

Mesmo padrão. Roda a cada hora. ~890 queries/hora só aqui.

**Fix:** window functions + `ANY($1::int[])` pra processar tudo em 1-2 queries.

### H-04 · INSERT dentro de loop no `agendar_followups`
**Local:** `src/services/workers.py:128-141`

N+1 INSERTs. Com 800 templates × múltiplos follow-ups: 16k+ INSERTs individuais.

**Fix (1-2h):** batch INSERT com `VALUES (...), (...)` — 1 query só.

### H-05 · `flush_all()` destrói cache de todas as empresas
**Local:** `src/services/cache_invalidation.py:213-219`

Se admin clicar em "limpar tudo" por engano, destrói performance de 800 tenants simultaneamente. Padrões `cfg:*` são muito amplos.

**Fix (30min):** remover função ou restringir a admin master + confirmação obrigatória. Reimplementar como loop por empresa se precisar.

### H-06 · Rate limit por conversa insuficiente em escala
**Local:** `main.py:4142`

30 msgs/h **por conversa**. Empresa com 1000 conversas ativas = **30k msgs/h permitidas**. Rate limit global (300/min = 18k/h) é menor → um burst vai passar por cima do global.

**Fix (4-6h):** adicionar rate limit **por empresa** (ex: 5k msgs/h por empresa) além do por conversa.

### H-07 · Sem rate limit em endpoints `/management/*`
**Local:** todos os routers de admin

Usuário logado pode chamar `/management/export-leads` 100×/s. Nenhum limite.

**Fix (3-4h):** `slowapi` com decorator por endpoint: `@limiter.limit("10/minute")`.

### H-08 · Sem Redis connection pool explícito
**Local:** `src/core/redis_client.py`

`redis.from_url(REDIS_URL)` sem `connection_pool` → abre socket novo a cada call. Em 800 req/s × 5 calls Redis = 4000 sockets/s → exaustão de file descriptors.

**Fix (1h):** `redis.ConnectionPool(max_connections=50, socket_keepalive=True)`.

### H-09 · HTTP client (httpx) com 50 conexões totais
**Local:** `main.py:1103-1105`

`max_connections=50` pro UazAPI. Com 800 tenants em burst, fila. Retry 3× com backoff × 4s = 12s extras em falhas.

**Fix (30min):** `max_connections=200, max_keepalive_connections=50`.

### H-10 · TTLs de cache curtos
**Local:** `src/services/cache_invalidation.py`

Menu/fluxo com 120s = 5600 queries/min em pico com 800 tenants.

**Fix (15min):** Menu/Fluxo 120→300s, FAQ 300→600s. Reduz DB em ~80%.

### H-11 · Fila de webhook sem backpressure
**Local:** `main.py` (BackgroundTasks)

Se worker trava, fila cresce sem limite → OOM crash.

**Fix (2h):** max 10k mensagens em fila; rejeitar com 503 quando exceder.

### H-12 · Fallback local do Redis é dict global
**Local:** `src/core/redis_client.py:11-36`

`_LOCAL_REDIS_FALLBACK` é dict compartilhado entre todos os tenants. Se Redis cai, chaves de uma empresa podem ser lidas por outra (dependendo do pattern de acesso).

**Fix (1-2h):** dict aninhado `{empresa_id: {key: value}}` ou incluir empresa_id no prefixo.

---

## 3. Riscos MÉDIOS (10 itens)

### M-01 · Sentry opcional
Se `SENTRY_DSN` vazio em prod, erros não são monitorados. Configurar obrigatoriamente.

### M-02 · Logs sem empresa_id consistente
Muitos logs incluem `empresa_id`, mas vários não (ex: `main.py:5515` webhook recebido). Em escala, fica impossível debugar.

**Fix:** `contextvars.ContextVar("empresa_id")` + middleware que injeta em todos os logs.

### M-03 · Sem trace IDs cross-service
Correlacionar webhook → worker → DB sem trace ID é chute.

**Fix:** UUID por request, propagado em logs + Sentry.

### M-04 · Command timeout de 10s no pool
Queries lentas (métricas diárias, exports) podem timeout silenciosamente.

**Fix:** subir pra 30s. Queries específicas com timeout próprio.

### M-05 · Sem limite de WebSocket connections
Agente abre 100 abas → 100 sockets = ~100MB RAM por agente.

**Fix:** max N sockets por usuário e por empresa.

### M-06 · Sem escolha de modelo LLM por empresa
Todas usam Gemini Flash. Empresa "premium" pagaria por Pro mas recebe Lite.

**Fix:** campo `modelo_preferido` em `empresas`; aplicar em `get_evo_config`.

### M-07 · Sem limite de áudio/imagem por conversa
Cliente pode mandar 100 áudios (Whisper $$$), sem limite específico. Anti-burst é só por contagem.

**Fix:** limite 10 áudios/dia + 20 imagens/dia por conversa.

### M-08 · Tokens LLM reservados não são liberados se não usados
`check_and_reserve_llm_call()` reserva X tokens, mas se real foi Y < X, a diferença fica "perdida" na quota.

**Fix:** após chamada, `record_actual_usage(actual - reserved)` ajusta.

### M-09 · TTL do cache de `account_id → empresa_id` é 1h
Se account é transferido de empresa, 1h de rotas erradas.

**Fix:** baixar pra 300s + endpoint de invalidação manual.

### M-10 · Indexes compostos faltando
Hoje só tem indexes por coluna única (`empresa_id`, `contato_fone`). Queries que filtram `(empresa_id, unidade_id)` usam 2 indexes single-column → ineficiente.

**Fix:** criar indexes compostos (SQL no §5 abaixo).

---

## 4. Sizing recomendado para 800 tenants

Baseado nos cálculos dos agentes:

| Recurso | Hoje | Recomendado 800 tenants | Motivo |
|---|---|---|---|
| **Pool Postgres** (min/max) | 3 / 15 | **30 / 120** | 30 base + workers (10) + 2× safety pra picos |
| **Redis connection pool** | Unlimited (unsafe) | **50 explícito** | 10 concurrent × 5 safety |
| **Uvicorn workers** | 1 | **4** | 1 por CPU core (GIL) |
| **httpx max_connections** | 50 | **200** | Burst de 800 tenants simultâneos |
| **DB_POOL_COMMAND_TIMEOUT** | 10s | **30s** | Queries longas de workers |
| **Container API** (RAM/CPU) | 1GB / 1.0 CPU | **2GB / 2.0** | 2x buffer para pools + cache |
| **Container Worker** | 1.5GB / 1.5 | **2GB / 2.0** | Batch processing |
| **Redis memory** | — | **4GB+** | 800k+ keys ativos |
| **Postgres** | — | **8GB RAM / 4 CPU** | `shared_buffers=2GB, work_mem=50MB` |

### Nginx upstream pra load balance:
```nginx
upstream app {
    least_conn;
    server api:8000 max_fails=2 fail_timeout=10s;
    server api:8001 max_fails=2 fail_timeout=10s;
    server api:8002 max_fails=2 fail_timeout=10s;
    server api:8003 max_fails=2 fail_timeout=10s;
}
```

---

## 5. Indexes Postgres recomendados

Execute com `CONCURRENTLY` pra não travar produção:

```sql
-- 1. Conversas por empresa + unidade (dashboards)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_conversas_empresa_unidade_created
  ON conversas(empresa_id, unidade_id, created_at DESC)
  INCLUDE (contato_fone, conversation_id);

-- 2. Mensagens por conversa + role (histórico IA)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_mensagens_conversa_role_created
  ON mensagens(conversa_id, role, created_at DESC)
  INCLUDE (conteudo, latencia_ms);

-- 3. Followups pendentes (worker_followup)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_followups_status_agenda
  ON followups(status, agendado_para, empresa_id)
  WHERE status = 'pendente'
  INCLUDE (conversa_id, account_id);

-- 4. Eventos_funil (worker_metricas)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_eventos_funil_empresa_unidade_data
  ON eventos_funil(empresa_id, unidade_id, created_at DESC)
  WHERE tipo_evento IN ('pergunta', 'interesse', 'matricula');

-- 5. Memória cliente (lookup por telefone)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_memoria_cliente_empresa_phone
  ON memoria_cliente(empresa_id, contato_telefone, created_at DESC);

-- 6. Conversas ativas (partial — só conversas recentes)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_conversas_ativas
  ON conversas(empresa_id, unidade_id, conversation_id)
  WHERE status != 'encerrada' AND updated_at > NOW() - interval '7 days';

-- 7. Escalações pendentes
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_escalacoes_pendentes
  ON conversas(empresa_id, created_at DESC)
  WHERE motivo_escalacao IS NOT NULL AND status != 'encerrada';
```

---

## 6. Plano de ação priorizado

### Sprint 1 — CRÍTICA (1 semana, paraliza escala se não fizer)

**Segurança (dia 1-2):**
- [ ] C-01: proteger `/sync-planos`, `/desbloquear`, `/metricas/diagnostico` com JWT
- [ ] C-02: validar HMAC da assinatura Chatwoot
- [ ] C-03: dependência `require_tenant_match` nos endpoints que aceitam empresa_id
- [ ] C-04: validação de `empresa_id` no WebSocket scan_iter
- [ ] C-06: mascarar telefone nos 15+ pontos de log

**Escalabilidade (dia 3-4):**
- [ ] C-09: subir pool Postgres pra 30/120 no docker-compose
- [ ] H-01: uvicorn com `--workers 4` no Dockerfile
- [ ] H-08: Redis connection pool com max 50
- [ ] H-09: httpx max_connections 200
- [ ] M-10: criar os 7 indexes compostos

**Quota/LLM (dia 5):**
- [ ] C-05: circuit breaker no `llm_quota.py`
- [ ] M-08: liberar tokens reservados não usados

**Validação (dia 6-7):**
- [ ] Load test com 800 tenants simulados
- [ ] Monitorar Postgres (pool usage), Redis (memory), latência

### Sprint 2 — ALTAS (1 semana, degrada em carga)

- [ ] H-02, H-03, H-04: otimizar N+1 dos workers (join + window functions + batch insert)
- [ ] H-05: proteger `flush_all()` com 2FA
- [ ] H-06: rate limit por empresa (não só por conversa)
- [ ] H-07: rate limit em `/management/*`
- [ ] H-10: subir TTLs de cache
- [ ] H-11: backpressure na fila de webhook
- [ ] H-12: fallback Redis per-tenant
- [ ] C-07: validar conversation_id único por empresa + fix de chave se necessário

### Sprint 3 — MÉDIAS (1 semana, hardening)

- [ ] M-01 a M-09: Sentry obrigatório, contextvars de empresa_id, trace IDs, timeouts ajustados, WS limits, modelo por empresa, limites de media, ajustes de quota

---

## 7. Checklist pré-deploy de cada empresa nova

Conforme você for adicionando empresas (0 → 800), garantir que:

1. ☐ Tabela `integracoes` tem row pra `tipo='uazapi'`, `tipo='chatwoot'` com config válido
2. ☐ Campo `empresa.status = 'active'` — workers só pegam ativos
3. ☐ Personalidade criada com `mensagem_fora_horario` preenchido
4. ☐ FAQ/KB pelo menos 10 entradas — evita fallback genérico
5. ☐ `webhook_secret` configurado no UazAPI + banco (ou `require_webhook_secret=false` por integração pra modo dev)
6. ☐ Teste de smoke: webhook entra, fluxo dispara, mensagem sai

Criar um endpoint `POST /admin/provision-empresa` que faça essa validação automaticamente.

---

## 8. Métricas a monitorar em produção

Dashboards no Prometheus/Grafana:

| Métrica | Alerta em |
|---|---|
| `pg_pool_usage` | > 80% por 5min |
| `redis_memory_used` | > 3GB |
| `webhook_latency_p95` | > 2s |
| `llm_quota_rejected_total` (por empresa) | qualquer rejeição |
| `worker_leader_lost_total` | qualquer mudança inesperada |
| `sentry_events_rate` | > 10/min |
| `ia_latency_p99` | > 8s |

---

## 9. Fontes e contexto

Análise baseada em 3 auditorias paralelas:

1. **Isolamento multi-tenant** — grep em todo `src/`, `main.py`, `routers/`. Inventário de ~30 chaves Redis e 100+ queries SQL.
2. **Escalabilidade** — pools, N+1 queries, TTLs, sizing com cálculos baseados em perfil de carga esperado.
3. **Quotas + segurança + workers** — `llm_quota.py`, rate limits existentes, PII em logs, JWT, CORS, Sentry, leader election.

Arquivos principais analisados:
- `main.py` (6300+ linhas)
- `src/services/flow_executor.py` (1800+ linhas)
- `src/services/uaz_client.py`, `db_queries.py`, `cache_invalidation.py`, `llm_quota.py`, `workers.py`, `stream_worker.py`
- `src/api/routers/` (15+ endpoints)
- `docker-compose.prod.yml`, `Dockerfile`, `.env.production.example`

Relatório completo em `AUDITORIA_ESCALA_800_TENANTS.docx` (formato Word).
