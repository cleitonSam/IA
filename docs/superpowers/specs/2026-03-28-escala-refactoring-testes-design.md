# Antigravity IA — Escala Vertical + Refactoring + Testes

**Data:** 2026-03-28
**Contexto:** 10-50 empresas, ~2K msgs/dia, servidor único (VPS/EC2)
**Objetivo:** Aguentar mais volume, reduzir bugs recorrentes, facilitar manutenção

---

## 1. Refactoring do `main.py` (5.271 linhas → ~100 linhas)

### Problema
Arquivo mais alterado do projeto (17 mudanças em 30 commits). Mistura setup do FastAPI, webhook processor (~500 linhas na função `processar_ia_e_responder`), e endpoints avulsos.

### Mudanças

1. **Mover webhook processor** para `src/api/routers/webhook.py`
   - A função `processar_ia_e_responder()` e toda lógica de processamento de mensagens Chatwoot vai para o router de webhook
   - O router já existe mas está subutilizado (481 linhas) — será expandido

2. **Mover endpoints avulsos** para seus routers naturais:
   - `GET/POST /webhook` → `src/api/routers/webhook.py`
   - `GET /desbloquear/{empresa_id}/{conversation_id}` → `src/api/routers/management.py`
   - `GET /metrics` → `src/api/routers/dashboard.py`
   - `GET /status` → `src/api/routers/dashboard.py`
   - `GET /sync-planos/{empresa_id}` → `src/api/routers/management.py`

3. **`main.py` final** contém apenas:
   - Imports dos routers
   - Middleware setup (CORS, Prometheus)
   - Startup/shutdown events (DB pool, Redis, workers)
   - `app.include_router()` calls

### Critério de sucesso
- `main.py` com ≤150 linhas
- Todos os endpoints funcionam identicamente
- Zero mudança de comportamento externo

---

## 2. Refactoring do `bot_core.py` (2.829 linhas → ~300 linhas orquestrador)

### Problema
Segundo arquivo mais alterado (13 mudanças). Pipeline de IA mistura construção de prompt, formatação de mensagens, gerenciamento de estado e orquestração.

### Nova estrutura

```
src/services/
├── bot_core.py              → Orquestrador (~300 linhas)
├── prompt_builder.py        → Montagem de system prompt + contexto (~500 linhas)
├── message_formatter.py     → Formatação de saída (~400 linhas)
└── conversation_handler.py  → Gerenciamento de estado (~400 linhas)
```

### Responsabilidades

**`bot_core.py` (orquestrador)**
- Recebe mensagem + contexto
- Chama `conversation_handler` para carregar/salvar estado
- Chama `prompt_builder` para montar o prompt
- Chama LLM (via `llm_service.py` existente)
- Chama `message_formatter` para formatar a resposta
- Retorna resposta pronta para envio

**`prompt_builder.py`**
- Montagem do system prompt com personalidade
- Injeção de contexto (histórico, FAQ, RAG)
- Injeção de variáveis da sessão
- Instruções de segurança e tom

**`message_formatter.py`**
- Conversão Markdown → formato WhatsApp
- Formatação de menus (botões, listas)
- Preparação de mídia (áudio TTS, imagens, vídeos)
- Garantia de frase completa (`_garantir_frase_completa`)

**`conversation_handler.py`**
- Load/save estado da conversa (Redis)
- Gerenciamento de `session_vars` e flags
- Cooldowns e rate limiting por conversa
- Detecção de contexto (unidade selecionada, fluxo ativo)

### Regra de dependência
- `bot_core.py` importa os 3 módulos
- Nenhum módulo importa outro diretamente
- Comunicação via dicts/dataclasses, não chamadas cruzadas

### Critério de sucesso
- Cada módulo ≤500 linhas
- Mesmos testes de integração passam
- Zero mudança de comportamento externo

---

## 3. Processamento Assíncrono de Webhooks

### Problema atual
Processamento síncrono: webhook chega → busca contexto → chama LLM → formata → envia. Com múltiplas empresas simultâneas, bloqueia o event loop.

### Arquitetura proposta

```
WhatsApp → UazAPI → Webhook Endpoint (valida, enfileira, retorna 200 em <50ms)
                         ↓
                    Redis Streams
                    ├── stream:webhook:empresa_{id_1}
                    ├── stream:webhook:empresa_{id_2}
                    └── stream:webhook:empresa_{id_N}
                         ↓
                    Worker Pool (N workers configurável)
                         ↓
                    Bot Core → LLM → UazAPI (resposta)
```

### Detalhes

1. **Webhook receiver rápido**
   - Ambos os webhooks (UazAPI em `uaz_webhook.py` e Chatwoot em `webhook.py`) passam a enfileirar ao invés de processar inline
   - Cada webhook normaliza o payload para um formato comum antes de enfileirar: `{source: "uazapi"|"chatwoot", empresa_id, conversation_id, message_id, content, metadata}`
   - Valida assinatura/formato
   - Serializa payload e adiciona ao Redis Stream da empresa
   - Retorna HTTP 200 imediatamente
   - Tempo alvo: <50ms

2. **Streams por empresa**
   - Cada empresa tem sua própria stream key: `stream:webhook:empresa_{id}`
   - Evita que uma empresa com alto volume bloqueie as outras
   - Workers fazem round-robin entre streams

3. **Worker pool**
   - N workers assíncronos (padrão: 4, configurável via env `WORKER_POOL_SIZE`)
   - Cada worker: consome mensagem → executa pipeline bot_core → envia resposta
   - Consumer group do Redis Streams garante que cada mensagem é processada uma vez
   - Acknowledge após processamento bem-sucedido

4. **Idempotência**
   - Chave de deduplicação: `{message_id}:{conversation_id}`
   - TTL: 5 minutos no Redis
   - Se webhook duplicado chegar, ignora silenciosamente

### Pool de conexões dinâmico

| APP_MODE | PG min_size | PG max_size | Justificativa |
|----------|-------------|-------------|---------------|
| `api`    | 2           | 5           | Poucas queries, só enfileira |
| `worker` | 5           | 20          | Queries pesadas de contexto |
| `both`   | 5           | 15          | Balanceado |

### Redis pipelining

Agrupar operações Redis sequenciais em pipelines:

**Antes (3 round-trips):**
```python
estado = await redis.get(f"state:{conv_id}")
sessao = await redis.get(f"session:{conv_id}")
cache = await redis.get(f"cache:{empresa_id}")
```

**Depois (1 round-trip):**
```python
async with redis.pipeline() as pipe:
    pipe.get(f"state:{conv_id}")
    pipe.get(f"session:{conv_id}")
    pipe.get(f"cache:{empresa_id}")
    estado, sessao, cache = await pipe.execute()
```

Aplicar nos pontos com 3+ operações Redis sequenciais (identificados 8 locais no código).

### Critério de sucesso
- Webhook retorna 200 em <50ms (medido via Prometheus)
- Throughput: 100+ mensagens/minuto sem degradação
- Mensagens duplicadas não geram respostas duplicadas

---

## 4. Testes — Cobertura Mínima Viável (~30 testes)

### Setup
- `pytest` + `pytest-asyncio`
- Mocks para Redis, PostgreSQL, e LLM (sem chamadas externas)
- Diretório: `tests/`
- Execução: `pytest` (local, sem CI por agora)

### Escopo

**`tests/test_flow_executor.py` (~15 testes)**
- Execução de nós básicos: SendText, SendMenu, SendImage, SendAudio
- Switch node: roteamento por seleção de menu (incluindo strip do prefixo UazAPI)
- BusinessHours: roteamento aberto/fechado
- MenuFixoIA: envio de menu + flag + resposta IA (mock)
- Substituição de variáveis: `{{phone}}`, `{{hora}}`, `{{data}}`, `{{last_choice_label}}`
- State machine: salvar estado → receber input → restaurar estado → continuar
- Condição com regex match
- Tratamento de edge cases: nó sem conexão, variável inexistente

**`tests/test_bot_core.py` (~10 testes, pós-refactoring)**
- `prompt_builder`: monta prompt com personalidade + contexto + histórico
- `prompt_builder`: injeção de FAQ relevante
- `message_formatter`: formatação Markdown → WhatsApp
- `message_formatter`: formatação de menu com botões
- `message_formatter`: `_garantir_frase_completa` não corta tags `<SEND_VIDEO>`
- `conversation_handler`: load/save estado Redis
- `conversation_handler`: cooldown impede resposta duplicada
- Orquestrador: pipeline completo com LLM mockado

**`tests/test_webhook_pipeline.py` (~5 testes)**
- Webhook recebido → payload enfileirado no Redis Stream
- Worker consome → processa → envia resposta (LLM mockado)
- Webhook duplicado → ignorado (idempotência)
- Webhook com assinatura inválida → rejeitado
- Múltiplas empresas simultâneas → processadas em round-robin

### Critério de sucesso
- Todos os 30 testes passam
- Tempo total de execução <10s (sem I/O externo)
- Áreas mais frágeis (flow_executor, webhook) cobertas

---

## 5. Frontend — Melhorias Cirúrgicas

### 5.1 Decomposição do `personality/page.tsx` (1.810 → ~200 linhas orquestrador)

**Nova estrutura:**
```
frontend/src/app/dashboard/personality/
├── page.tsx              → Orquestrador com tabs (~200 linhas)
├── PersonalityForm.tsx   → Campos de personalidade, tom, instruções
├── HorarioConfig.tsx     → Horário de atendimento + fuso
├── SecurityConfig.tsx    → Regras de segurança/dados pessoais
└── PlaygroundSection.tsx → Área de teste da IA
```

**Regra:** `page.tsx` gerencia estado global da personality e passa via props para subcomponentes. Cada subcomponente recebe `data` + `onChange` e é auto-contido.

### 5.2 `MultiOutputNode` base para nós complexos

**Problema:** Switch, AIClassify, MenuFixoIA, AIMenuDinamicoIA duplicam ~80% do código de header + lista de opções + handles posicionados.

**Solução:** Criar `frontend/src/app/dashboard/fluxo-triagem/nodes/MultiOutputNode.tsx`

```tsx
interface MultiOutputNodeProps {
  nodeType: string;
  title: string;
  color: string;
  outputs: Array<{ id: string; label: string }>;
  children: React.ReactNode; // Conteúdo específico do nó
  props: NodeProps;
}
```

Nós complexos passam a usar:
```tsx
<MultiOutputNode nodeType="switch" title="Switch" color="#8B5CF6" outputs={conditions} props={props}>
  {/* Conteúdo específico: inputs de condição, regex, etc. */}
</MultiOutputNode>
```

Elimina ~500 linhas de código duplicado entre 4 nós.

### 5.3 Hook `useApiConfig()`

**Problema:** Cada página repete:
```tsx
const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
const config = { headers: { Authorization: `Bearer ${token}` } };
```

**Solução:** `frontend/src/hooks/useApiConfig.ts`
```tsx
export function useApiConfig() {
  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
  const empresaId = typeof window !== 'undefined' ? localStorage.getItem('empresaId') : null;
  const config = { headers: { Authorization: `Bearer ${token}` } };
  return { token, empresaId, config };
}
```

### Critério de sucesso
- `personality/page.tsx` ≤250 linhas
- Nós complexos com ≤50% do código atual
- Zero mudança visual/funcional

---

## Ordem de Execução

| Fase | O que | Dependência | Risco |
|------|-------|-------------|-------|
| 1 | Refactoring `main.py` | Nenhuma | Baixo |
| 2 | Refactoring `bot_core.py` | Nenhuma (paralelo com 1) | Médio |
| 3 | Webhook assíncrono + Redis Streams | Fases 1 e 2 | Médio |
| 4 | Testes | Fases 1, 2 e 3 | Baixo |
| 5 | Frontend | Nenhuma (paralelo com 1-4) | Baixo |

Fases 1, 2 e 5 podem ser feitas em paralelo. Fase 3 depende de 1 e 2. Fase 4 é a última.

---

## Fora do Escopo

- Microserviços / Docker Compose (fase futura)
- CI/CD pipeline
- Testes de frontend
- Acessibilidade (ARIA, keyboard nav)
- Monitoramento avançado (Grafana, alertas)
- Refactoring do `db_queries.py` (Repository pattern — fase futura)
- Refactoring do `management.py` router (1.950 linhas — fase futura)
