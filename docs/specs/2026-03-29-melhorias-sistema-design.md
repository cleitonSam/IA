# Motor SaaS IA — Design de Melhorias do Sistema
> Spec criado em 29/03/2026 | Status: AGUARDANDO APROVAÇÃO

---

## Contexto

Sistema em produção: FastAPI + Next.js + Redis Streams + PostgreSQL + OpenRouter.
Análise completa realizada em 29/03/2026 identificou 5 módulos de melhoria prioritários.
O objetivo é manter tudo funcionando em produção durante as melhorias (zero downtime).

---

## MÓDULO A — Correções Urgentes (Hotfixes)

### A1 — CORS Dinâmico

**Problema atual:** `main.py` define origens CORS de forma estática:
```python
_cors_origins = [FRONTEND_URL, "http://localhost:3000"]
```
Se o domínio do frontend mudar (ex: deploy em domínio personalizado por cliente),
as requisições são bloqueadas. Não há suporte a múltiplos domínios.

**Solução:**
- Adicionar env var `CORS_ORIGINS` com suporte a lista separada por vírgula
- Fallback para `FRONTEND_URL` se não definida
- Validação: rejeitar origens vazias ou malformadas

```python
# src/middleware/cors.py (novo arquivo)
def build_cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "")
    extras = [o.strip() for o in raw.split(",") if o.strip()]
    base = [FRONTEND_URL, "http://localhost:3000"]
    return list({*base, *extras})
```

**Impacto:** Correção imediata do bloqueio de requisições em produção.

---

### A2 — Integração EVO: Isolamento de Credenciais por Unidade

**Problema atual:** `evo_client.py` busca credenciais com `carregar_integracao(empresa_id, 'evo', unidade_id)`.
Se `unidade_id` for `None`, usa credencial global — pode apontar para unidade errada.

**Problemas identificados:**
1. Email é obrigatório na EVO v1 mas o sistema gera um fake (`{phone}@lead.com`) —
   funciona mas pode causar deduplicação errada no CRM.
2. Sem retry em falhas de rede (timeout único sem retry)
3. Sem validação se a URL da API EVO está acessível antes de tentar criar prospect

**Solução:**
- Adicionar `@retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(3))` em `criar_prospect_evo`
- Adicionar validação prévia: `GET /api/v2/health` na EVO antes de chamar endpoints
- Logar o fake email gerado para auditoria
- Retornar erro estruturado ao invés de `False` (para que `bot_core.py` saiba o motivo)

---

### A3 — Email de Convite: Branding Dinâmico + Robustez

**Problema atual:**
- Email hardcoded com branding antigo — não reflete o nome real da empresa
- Sem template de boas-vindas após registro completado
- Sem retry em falha SMTP (a falha é silenciosa — retorna `False` mas não bloqueia o fluxo)
- Link de convite não tem fallback se `FRONTEND_URL` não está configurado

**Solução:**

```python
# Novo: email_service.py
async def enviar_convite(email_destino: str, nome_empresa: str, token: str,
                          nome_plataforma: str = "Motor IA"):
    """
    - nome_plataforma: vem de env var PLATFORM_NAME (padrão: "Motor IA")
    - Retry até 3x com backoff
    - Template responsivo com logo opcional (LOGO_URL env var)
    - Segunda função: enviar_boas_vindas(email, nome_usuario, nome_empresa)
    """
```

Novos env vars:
- `PLATFORM_NAME` — nome da plataforma no email (ex: "Fluxo")
- `PLATFORM_LOGO_URL` — URL do logo para o email
- `SUPPORT_EMAIL` — email de suporte exibido no rodapé

---

## MÓDULO B — Inteligência de Custo de Tokens

### Contexto de Preço

Plano atual: R$ 39,90/mês por cliente, com custos de API:
- Horário comercial (06h–23:59): ~R$ 0,0272 por 100 requisições
- Madrugada (00:00–05:59): ~R$ 0,0176 por 100 requisições

O `model_router.py` já faz roteamento inteligente (~40% de economia).
O que falta: **controle de orçamento, visibilidade de custo e roteamento temporal**.

---

### B1 — Roteamento Temporal por Horário

**Problema:** O `model_router.py` não considera o horário para escolher modelos.
À noite, o custo por requisição é menor — podemos ser mais generosos com modelos.
De dia, devemos priorizar modelos lite para economizar.

**Solução — adicionar ao `model_router.py`:**

```python
def _is_horario_economico() -> bool:
    """00:00–05:59 BRT — custo de API mais baixo."""
    hora = datetime.now(ZoneInfo("America/Sao_Paulo")).hour
    return hora < 6

def escolher_modelo(...) -> str:
    # Nova Regra 0: Horário econômico → upgrade automático para modelo potente
    # sem custo adicional relevante
    if _is_horario_economico() and intencao not in INTENCOES_LITE:
        return MODELO_POTENTE
    # ... resto da lógica atual ...
```

**Impacto:** Melhora qualidade das respostas à noite sem custo extra.

---

### B2 — Budget Tracker por Empresa

**Problema:** Não há rastreamento de custo por empresa. Não é possível saber
quanto cada cliente consome ou alertar antes de estourar o limite.

**Solução — nova tabela:**
```sql
-- Migração: add_token_usage_tracking
CREATE TABLE token_usage (
    id          BIGSERIAL PRIMARY KEY,
    empresa_id  INTEGER NOT NULL REFERENCES empresas(id),
    data        DATE NOT NULL DEFAULT CURRENT_DATE,
    modelo      TEXT NOT NULL,
    tokens_in   INTEGER NOT NULL DEFAULT 0,
    tokens_out  INTEGER NOT NULL DEFAULT 0,
    custo_usd   NUMERIC(10,6) NOT NULL DEFAULT 0,
    req_count   INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_token_usage_empresa_data_modelo
    ON token_usage(empresa_id, data, modelo);
CREATE INDEX idx_token_usage_empresa_data
    ON token_usage(empresa_id, data DESC);
```

**Novo campo na personalidade:**
```sql
-- Migração: add_comprimento_resposta
ALTER TABLE personalidades
ADD COLUMN comprimento_resposta TEXT DEFAULT 'normal'
    CHECK (comprimento_resposta IN ('concisa','normal','detalhada'));
```

**Lógica no `bot_core.py`:**
- Após cada chamada ao LLM, salvar `usage.prompt_tokens + usage.completion_tokens`
- Calcular custo com tabela de preços por modelo (constante no código)
- Redis counter para rate limit diário: `ia:budget:empresa:{id}:date:{YYYYMMDD}`

**Novo endpoint:**
```
GET /management/usage/summary?days=30
→ { daily: [...], total_tokens, total_cost_usd, avg_per_conversation }
```

---

### B3 — Controle de Verbosidade nas Respostas

**Problema:** As mensagens da IA às vezes são muito longas.
O campo `max_tokens` existe mas não instrui o LLM a ser conciso no system prompt.

**Solução — injeção no `_build_playground_prompt()`:**

```python
# Novo bloco adicionado ao final do system prompt:
VERBOSIDADE_MAP = {
    "concisa":   "[TAMANHO DE RESPOSTA]\nResponda em no máximo 2–3 frases. "
                 "Seja direto e objetivo. NUNCA use listas ou parágrafos longos.",
    "normal":    "[TAMANHO DE RESPOSTA]\nRespostas entre 3–5 frases. "
                 "Balance completude e concisão.",
    "detalhada": "[TAMANHO DE RESPOSTA]\nPode detalhar quando necessário. "
                 "Use listas quando ajudar a clareza.",
}
verbosidade = p.get("comprimento_resposta", "normal")
blocos.append(VERBOSIDADE_MAP[verbosidade])
```

**UI — novo controle na seção Engine:**
```
[ Concisa ]  [ Normal ● ]  [ Detalhada ]
  2-3 frases   3-5 frases   Sem limite
```

---

## MÓDULO C — Editor de Personalidade (5 Gaps)

### C1 — Remover Duplicação no settings/page.tsx

**Problema:** `settings/page.tsx` ainda tem aba "Personalidade IA" com campos básicos
duplicados. O usuário vê dois lugares para editar a mesma configuração.

**Solução:**
- Substituir a aba "Personalidade IA" em settings por um card de redirecionamento:
```tsx
// Substituir o formulário por:
<div className="text-center py-12">
  <Brain className="w-12 h-12 mx-auto mb-4 text-cyan-400" />
  <h3>Configurações de Personalidade</h3>
  <p>Gerencie a personalidade da IA na página dedicada</p>
  <Link href="/dashboard/personality">Ir para Personalidade IA →</Link>
</div>
```

---

### C2 — Endpoint de Preview do Prompt

**Problema:** `_build_playground_prompt()` existe no backend mas o cliente não
consegue ver o prompt exato que será enviado ao LLM.

**Novo endpoint:**
```
POST /management/personalities/{personality_id}/preview-prompt
Body: {} (opcional: override de campos para preview rápido)
Response: {
  "system_prompt": "...",
  "char_count": 2847,
  "estimated_tokens": 712,
  "sections": ["REGRAS GERAIS", "IDENTIDADE", "PERSONALIDADE", ...]
}
```

**UI — botão "Ver Prompt Completo" na personality page:**
- Abre drawer lateral com o prompt renderizado
- Mostra contador: "~712 tokens no system prompt"
- Destaca seções em cores diferentes
- Botão "Copiar" para clipboard

---

### C3 — Templates de Personalidade

**Problema:** Ao criar personalidade nova, todos os campos ficam vazios.
O cliente não sabe como preencher.

**Novo endpoint:**
```
GET /management/personality-templates
Response: [
  { id: "academia_vendas", nome: "Academia — Vendas Ativas", desc: "...", fields: {...} },
  { id: "academia_receptivo", nome: "Academia — Atendente Receptivo", fields: {...} },
  { id: "academia_premium", nome: "Academia Premium", fields: {...} },
  { id: "generico_vendas", nome: "Genérico — Consultora de Vendas", fields: {...} },
]
```

Templates são hardcoded no backend (sem tabela — evita complexidade desnecessária).

**UI:**
- Ao clicar em "+ Nova Personalidade", mostrar modal com templates
- Botão "Começar do zero" disponível
- Cada template mostra preview de como a IA irá se comportar

---

### C4 — Refatoração de personality/page.tsx (1865 linhas)

**Problema:** Arquivo monolítico difícil de manter.

**Nova estrutura:**
```
frontend/src/app/dashboard/personality/
├── page.tsx                        (orquestração — ~200 linhas)
├── components/
│   ├── PersonalityList.tsx         (lista lateral — ~150 linhas)
│   ├── PersonalityForm/
│   │   ├── index.tsx               (formulário principal — ~200 linhas)
│   │   ├── SectionIdentidade.tsx   (~100 linhas)
│   │   ├── SectionEngine.tsx       (~120 linhas)
│   │   ├── SectionVendas.tsx       (~150 linhas)
│   │   ├── SectionBranding.tsx     (~100 linhas)
│   │   ├── SectionContexto.tsx     (~100 linhas)
│   │   ├── SectionSeguranca.tsx    (~80 linhas)
│   │   ├── SectionHorarios.tsx     (~150 linhas)
│   │   └── SectionVozIA.tsx        (~150 linhas)
│   ├── PlaygroundPanel.tsx         (~300 linhas)
│   ├── PromptPreviewDrawer.tsx     (~150 linhas)
│   └── TemplatesModal.tsx          (~100 linhas)
├── hooks/
│   ├── usePersonalities.ts         (fetch + CRUD)
│   └── usePlayground.ts            (sessões + streaming)
└── types.ts                        (interfaces TypeScript)
```

---

## MÓDULO D — Performance e Estabilidade do Banco

### D1 — Índices Críticos Faltantes

Migração única: `add_critical_indexes`

```sql
-- Lookup de conversa por phone (hot path do bot_core)
CREATE INDEX CONCURRENTLY idx_conversas_empresa_phone
    ON conversas(empresa_id, phone);

-- Dashboard de conversas (ordenação por data)
CREATE INDEX CONCURRENTLY idx_conversas_empresa_created
    ON conversas(empresa_id, created_at DESC);

-- Histórico de mensagens por conversa
CREATE INDEX CONCURRENTLY idx_mensagens_conversa_created
    ON mensagens_locais(conversa_id, created_at DESC);

-- Followups pendentes (worker query)
CREATE INDEX CONCURRENTLY idx_followups_pending
    ON followups(status, scheduled_at)
    WHERE status = 'pending';

-- Métricas por data (dashboard queries)
CREATE INDEX CONCURRENTLY idx_metricas_empresa_data
    ON metricas_diarias(empresa_id, data DESC);
```

**Impacto esperado:** 40-70% redução no tempo de resposta do bot em conversas ativas.

---

### D2 — Connection Pool Aumentado

**Arquivo:** `src/core/database.py`

```python
# ANTES
db_pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10, ...)

# DEPOIS
db_pool = await asyncpg.create_pool(
    dsn,
    min_size=5,           # 5 conexões sempre abertas
    max_size=30,          # até 30 sob pico
    max_inactive_connection_lifetime=300,  # fecha idle após 5min
    command_timeout=15,   # timeout por query
    statement_cache_size=100,  # cache de prepared statements
)
```

---

### D3 — Query Timeouts Universais

**Problema:** `await pool.fetch(query)` sem timeout pode travar workers indefinidamente.

**Solução — wrapper global em `db_queries.py`:**
```python
QUERY_TIMEOUT = float(os.getenv("DB_QUERY_TIMEOUT", "10"))

async def _fetch(pool, query: str, *args, timeout: float = QUERY_TIMEOUT):
    """Wrapper com timeout e logging de queries lentas."""
    start = time.monotonic()
    async with pool.acquire() as conn:
        result = await asyncio.wait_for(conn.fetch(query, *args), timeout=timeout)
    elapsed = time.monotonic() - start
    if elapsed > 2.0:
        logger.warning(f"⚠️ Query lenta ({elapsed:.2f}s): {query[:100]}")
    return result
```

---

## MÓDULO E — API: Paginação e Padronização

### E1 — Paginação nas Listagens

Endpoints que retornam listas sem paginação (risco em escala):

| Endpoint | Impacto |
|---|---|
| GET `/conversations` | Pode ter 100k+ linhas |
| GET `/logs` | Cresce sem limite |
| GET `/followup/history` | Acumula ao longo do tempo |
| GET `/knowledge-base` | Pode ter muitos documentos |

**Padrão adotado (offset + cursor para conversas):**
```
GET /conversations?page=1&per_page=50&status=open&unidade_id=5
Response: {
  "data": [...],
  "meta": { "total": 1420, "page": 1, "per_page": 50, "total_pages": 29 }
}
```

---

### E2 — Padronização de Respostas de Erro

**Problema:** Erros retornam em formatos diferentes por todo o sistema.

**Padrão único adotado:**
```python
# src/api/response.py (já existe!) — padronizar uso
{
  "error": {
    "code": "validation_error",        # snake_case, sem espaço
    "message": "Mensagem legível",     # para o usuário
    "details": [...]                   # opcional, campo-a-campo
  }
}
```

**Novo middleware centralizado:**
```python
# src/middleware/error_handler.py
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "Erro interno"}}
    )
```

---

### E3 — Rate Limiting nas Rotas de Management

**Problema:** Apenas `/webhook` tem rate limiting. Rotas de CRUD ficam expostas.

**Solução com `slowapi`:**
```python
# src/middleware/rate_limit.py
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

# Aplicado nos routers:
@router.post("/personalities")
@limiter.limit("20/minute")
async def create_personality(...): ...

@router.post("/personalities/playground/stream")
@limiter.limit("60/minute")  # playground pode ser mais generoso
async def playground_stream(...): ...
```

---

## MÓDULO F — Refatoração Estrutural (Manutenibilidade)

### F1 — Extrair Módulos de main.py

**Objetivo:** Reduzir `main.py` de ~5.400 linhas para ~100 linhas.

**Nova estrutura:**
```
src/
├── middleware/
│   ├── cors.py           (CORS dinâmico — A1)
│   ├── rate_limit.py     (rate limiting — E3)
│   └── error_handler.py  (E2)
├── core/
│   ├── startup.py        (lifespan + db_pool + redis init)
│   └── config.py         (já existe)
└── main.py               (~100 linhas: app definition + router includes)
```

---

### F2 — Tratamento de Exceções (183 bare excepts)

**Abordagem pragmática:** Não substituir todos de uma vez. Priorizar os caminhos críticos:

**Prioridade 1 (bot_core.py — caminho principal do LLM):**
```python
# Substituir por tratamento específico:
except asyncio.TimeoutError:     # LLM demorou
except httpx.HTTPStatusError:    # LLM retornou erro HTTP
except (json.JSONDecodeError, KeyError):  # resposta malformada
except Exception as e:           # fallback com log obrigatório
    logger.error(f"Unexpected: {e}", exc_info=True)
```

**Prioridade 2:** `flow_executor.py` — 30 tipos de node, cada um com exception masking.

---

## Prioridade de Implementação

### 🔴 Semana 1 — Corrigir problemas em produção
| Item | Arquivo | Tempo |
|------|---------|-------|
| A1: CORS dinâmico | `main.py` + env var | 1h |
| A3: Email de convite | `email_service.py` | 2h |
| D1: Índices no banco | nova migration | 2h |
| D2: Connection pool | `database.py` | 30min |
| B3: Verbosidade respostas | `management.py` + migration | 3h |

### 🟡 Semana 2 — Experiência do cliente
| Item | Arquivo | Tempo |
|------|---------|-------|
| C1: Remover duplicação settings | `settings/page.tsx` | 30min |
| C2: Preview do prompt | `management.py` + UI | 4h |
| C3: Templates personalidade | `management.py` + UI | 3h |
| B1: Roteamento temporal | `model_router.py` | 1h |
| E1: Paginação nas listagens | `dashboard.py` + UI | 4h |

### 🟢 Semana 3 — Robustez e escalabilidade
| Item | Arquivo | Tempo |
|------|---------|-------|
| B2: Budget tracker | nova migration + bot_core | 6h |
| A2: Evo retry/validação | `evo_client.py` | 2h |
| D3: Query timeouts | `db_queries.py` | 2h |
| E2: Padronização erros | `src/middleware/` | 3h |
| E3: Rate limiting management | `slowapi` | 2h |

### 🔵 Semana 4 — Manutenibilidade
| Item | Arquivo | Tempo |
|------|---------|-------|
| C4: Refatorar personality page | `dashboard/personality/` | 8h |
| F1: Extrair módulos main.py | `src/middleware/` + `src/core/` | 8h |
| F2: Exception handling | `bot_core.py` + `flow_executor.py` | 6h |

---

## Resumo de Arquivos Novos/Modificados

### Novos arquivos
- `src/middleware/cors.py`
- `src/middleware/rate_limit.py`
- `src/middleware/error_handler.py`
- `src/core/startup.py`
- `alembic/versions/..._add_critical_indexes.py`
- `alembic/versions/..._add_token_usage_tracking.py`
- `alembic/versions/..._add_comprimento_resposta.py`
- `frontend/src/app/dashboard/personality/components/*.tsx`
- `frontend/src/app/dashboard/personality/hooks/*.ts`
- `frontend/src/app/dashboard/personality/types.ts`
- `docs/specs/2026-03-29-melhorias-sistema-design.md`

### Arquivos modificados
- `main.py` (extração de módulos)
- `src/api/routers/management.py` (preview-prompt, templates, verbosidade, paginação)
- `src/api/routers/dashboard.py` (paginação)
- `src/services/evo_client.py` (retry, validação)
- `src/services/email_service.py` (branding dinâmico, retry)
- `src/services/model_router.py` (roteamento temporal)
- `src/services/bot_core.py` (budget tracking, exception handling)
- `src/core/database.py` (pool config)
- `src/utils/db_queries.py` (query timeout wrapper)
- `frontend/src/app/dashboard/personality/page.tsx` → dividido em componentes
- `frontend/src/app/dashboard/settings/page.tsx` (remover aba personalidade)

---

## Invariantes (Não Mudar)

- Estrutura das tabelas existentes (apenas ADD COLUMN e novos índices)
- API do webhook (`/webhook`) — Chatwoot depende dela
- Endpoints do playground (`/personalities/playground/*`) — já funcionando
- Estrutura do `_build_playground_prompt()` — apenas adicionar bloco de verbosidade
- Fluxo de autenticação JWT
- Lógica do `model_router.py` — apenas adicionar roteamento temporal ao início

---

*Spec criado após análise completa do código-fonte em 29/03/2026.*
*Próximo passo: aprovação do usuário → plano de implementação detalhado por módulo.*
