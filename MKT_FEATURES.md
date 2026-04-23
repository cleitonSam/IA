# Melhorias de Produto — Iteração MKT (abril 2026)

Features construídas a partir da análise de mercado (`Analise_Mercado_Fluxo_IA.docx`), **sem duplicar** o que já existia. Tudo tem um ID (`MKT-XX`) que aparece como comentário no código para rastreabilidade.

## [AI-UPGRADE] Stack de modelos (abril 2026)

A `src/services/model_router.py` usa o stack **Gemini 2.5** do Google (via OpenRouter):

| Tier | Modelo (default) | Usado em |
|---|---|---|
| PADRÃO | `google/gemini-2.5-flash` | Conversação geral, resposta ao cliente |
| POTENTE | `google/gemini-2.5-pro` | Objeções complexas, cancelamento, negociação, madrugada econômica |
| LITE | `google/gemini-2.5-flash-lite` | Saudação, horário, endereço (barato e rápido) |
| VISION | `google/gemini-2.5-pro` | Análise de fotos (MKT-08) |
| CLASSIFIER | `google/gemini-2.5-flash-lite` | Tarefas internas (sentimento, intent triage) — custo baixo |

Todos configuráveis via env (`MODELO_PADRAO`, `MODELO_POTENTE`, etc). Tem também `MODELO_PADRAO_OVERRIDE` pra forçar um modelo globalmente em caso de emergência.

Módulos novos atualizados para usar `google/gemini-2.5-flash` / `gemini-2.5-pro`:
- `client_memory.py` — extração de fatos + consolidação (flash)
- `agentic_rag.py` — planning + evaluator + synthesis (flash)
- `vision_analysis.py` — foto do aluno, ficha, descrição de imagem (pro)

## [INTEGRAÇÃO FINAL] Tudo plugado (abril 2026)

Os arquivos `main.py` e `src/services/stream_worker.py` foram atualizados pra plugar automaticamente os novos módulos:

### `main.py`
- Init do Sentry (INF-10) logo antes de `FastAPI()`
- 6 routers novos registrados: `kb`, `instagram_webhook`, `voice_webhook`, `leads_dashboard`, `alertas_router`, `roi_router`

### `stream_worker.py` (pipeline principal)
Hooks pre-IA (paralelo, não bloqueia resposta):
1. Cancela follow-ups `sem_resposta` quando cliente volta a conversar
2. Analisa sentimento e dispara alerta se detectar risco
3. Extrai fatos da mensagem para memória do cliente (MKT-03)

Hooks pos-IA (assíncrono):
4. Rescore do lead com ML (MKT-01)
5. Se virou tier A, grava `lead_qualificado` pra atribuição de ROI (MKT-07)

Tudo com fallback — se os hooks falharem, o pipeline principal continua.

## O que já existia (não refiz)

| Já tinha | Onde | Observação |
|---|---|---|
| `knowledge_base` + `rag_service.py` | `src/services/rag_service.py` | RAG linear completo com embeddings JSONB, chunk, cache Redis |
| `memoria_cliente` | migration `l5m6n7o8p9q0` | Tabela pronta, só faltou pipeline de extração |
| `score_lead` / `score_interesse` | migrations `5d740eb04415` + `y8z9a0b1c2d3` | Campos prontos, faltou classifier |
| `sentimento_ia` + `csat` + `cancelamento_detectado` | migration `b2c3d4e5f6g7` | Detecção pós-conversa existia, faltou real-time |
| A/B testing | `src/services/ab_testing.py` | Completo, nada a fazer |
| Follow-up single-touch | `workers.py` + `templates_followup` | Faltou sequência N-touch |
| Playground | confirmado pelo usuário | Skip |

## Pulado (escopo futuro)

- **Integração ERP** (Tecnofit, Pacto, W12, NextFit) — usuário pediu pra deixar pra depois.
- **Mobile app nativo** — escopo grande, vai pra sprint dedicado.
- **Multi-agent orchestration** — Q1 2027 conforme roadmap.

## O que foi construído nessa rodada

### [MKT-01] Lead scoring com ML heurístico evolutivo
**Arquivo:** `src/services/lead_scoring.py`

Função pública: `score_conversa(conv_id, empresa_id)` → `LeadScore(score=0-100, tier=A/B/C/D, explicacao=[...])`.

Usa 2 camadas:
1. **Heurística** (funciona sem dados) — pesos por sinal: `pediu_visita` +25, `perguntou_preco` +18, `sentiment_positivo` +12, `cancelamento` -40 etc.
2. **ML real** (quando houver outcome) — logistic regression salvo em `data/lead_model_empresa_<id>.json`; combina 60% ML + 40% heurística.

Pesos customizáveis por empresa: `data/lead_scoring_empresa_<id>.json`.

Tiers: A (80+, quente), B (60-79, morno), C (30-59, frio), D (0-29, descartar).

### [MKT-02] Sentimento em tempo real + alerta de escalação
**Arquivo:** `src/services/sentiment_realtime.py`

Função: `analisar_mensagem(conv_id, empresa_id, texto, sentimento_ia)` analisa cada mensagem e dispara alerta se detectar:
- Cancelamento explícito ("quero cancelar", "vou sair da academia")
- Urgência ("absurdo", "procon", "reclame aqui")
- Timeout crítico ("ninguém responde", "faz horas")
- Sentimento negativo persistente

Grava em **nova tabela `alertas_escalacao`** (migration `mkt01_features`) e opcionalmente dispara webhook externo (`ALERT_WEBHOOK_URL` para Slack/Discord/n8n).

Rate-limit de 5 min por (conversa, tipo) — evita spam.

### [MKT-03] Memória de cliente Mem0-style
**Arquivo:** `src/services/client_memory.py`

Sobre a tabela `memoria_cliente` existente:
- `extract_and_store_facts(empresa, fone, mensagens)` → chama GPT-4o-mini pra extrair fatos estruturados (tipo: preferência, objeção, horário, objetivo, restrição, histórico). Deduplica por similaridade exata; reforça relevância quando o mesmo fato é observado de novo.
- `recall_for_prompt(empresa, fone)` → monta bloco `[MEMORIA DO CLIENTE]` pra injetar no prompt.
- `apply_decay(empresa, 30 dias, 0.9)` → reduz relevância de fatos antigos; remove quando < 0.2.
- `consolidate_if_needed(empresa, fone, max_per_tipo=5)` → se um cliente tem muitos fatos do mesmo tipo, LLM consolida em 1.

### [MKT-04] KB auto-ingestão (crawl site + upload PDF)
**Arquivos:** `src/services/kb_ingestion.py`, `src/api/routers/kb.py`

Endpoints expostos:
- `POST /api/kb/crawl` — crawl BFS de um site (max 30 páginas, depth 2), extrai texto, indexa.
- `POST /api/kb/upload-pdf` — upload multipart, extrai via `pypdf`, indexa (max 20MB).
- `POST /api/kb/ingest-text` — texto direto.
- `GET /api/kb` — lista itens.
- `DELETE /api/kb/{id}` — soft delete.

Rate-limit aplicado em crawl (5/hora) e upload (20/hora) via `rate_limit` do audit anterior. Dependência nova: `beautifulsoup4` e `pypdf` (adicionar no `requirements.txt` se for usar).

### [MKT-05] Instagram DM webhook
**Arquivo:** `src/api/routers/instagram_webhook.py`

Endpoints:
- `GET /webhook/instagram/{empresa_id}` — verificação do Meta (hub.challenge)
- `POST /webhook/instagram/{empresa_id}` — recebe DMs, valida HMAC `X-Hub-Signature-256`, dedup, enfileira no mesmo `ia:webhook:stream` que o UazAPI usa. `phone` fica `ig:<user_id>` pra diferenciar.

Função `send_instagram_message(empresa_id, recipient, text)` pra o worker responder via Graph API.

Integração no banco: assume que existe uma integração `integracoes.tipo='instagram'` com `app_secret`, `page_access_token`, `page_id`. Se não tiver, falha fail-closed.

### [MKT-06] Voice agent (Vapi / Retell)
**Arquivos:** `src/services/voice_agent.py`, `src/api/routers/voice_webhook.py`

Suporta Vapi e Retell via env `VOICE_PROVIDER=vapi|retell|disabled`.

Função: `schedule_outbound_call(empresa, fone, script_prompt, motivo, metadata)` agenda chamada; grava em **nova tabela `voice_calls`**; retorna o ID local.

Webhook: `POST /webhook/voice/{empresa_id}` recebe callback com duração, transcript, custo e resultado. Atualiza `voice_calls.status`.

Casos de uso óbvios: recuperação de aluno inativo, confirmação de avaliação, outbound pra lead que só deu telefone.

### [MKT-07] ROI attribution + dashboard
**Arquivos:** `src/services/roi_attribution.py`, `src/api/routers/leads_dashboard.py`

Modelo append-only em **nova tabela `roi_events`**:
- `record_lead_qualificado(empresa, conv, fone, score)` → tipo `lead_qualificado`.
- `record_matricula(empresa, fone, plano, valor_mensal, lookback_dias=30)` → tipo `matricula`; se existir `lead_qualificado` do mesmo `contato_fone` nos últimos 30d, atribui ao bot.
- `compute_roi(empresa, periodo, custo_mensal_bot_brl)` → `{leads, matriculas_bot, receita_bot_brl, roi_ratio, taxa_conversao_pct}`.

Endpoint: `GET /api/roi?periodo_dias=30&custo_mensal_bot_brl=500`.

Viabiliza pricing **outcome-based** pilot (cobrar % sobre incremento).

### [MKT-08] Multimodal vision (foto do aluno)
**Arquivo:** `src/services/vision_analysis.py`

3 funções:
- `analisar_foto_avaliacao(empresa, url_or_b64)` → sugere objetivo de treino, nível, exercícios iniciais, disclaimer médico obrigatório.
- `extrair_dados_ficha(empresa, url_or_b64)` → OCR de ficha preenchida → JSON com nome, peso, altura, objetivo.
- `descrever_imagem_generica(empresa, url, pergunta)` → fallback pra aluno que manda foto de equipamento/alimento.

Usa `openai/gpt-4o-mini` via OpenRouter (trocar pra `anthropic/claude-3.5-sonnet` se quiser qualidade superior). Alertas LGPD nas docstrings — nunca armazenar foto original sem consentimento.

### [MKT-09] Agentic RAG (planning iterativo)
**Arquivo:** `src/services/agentic_rag.py`

Complementa o `rag_service.py` linear. `answer_with_agentic_rag(empresa, pergunta, max_iter=2)`:
1. **PLAN** — LLM decompõe pergunta em 1-3 sub-queries.
2. **RETRIEVE** — busca cada sub-query.
3. **EVALUATE** — LLM decide se é suficiente; se não, refina e busca mais.
4. **ANSWER** — LLM sintetiza resposta citando fontes numeradas.

Custa ~3x mais LLM que RAG linear. Usar quando pergunta for complexa (detecta `len > 80 chars` ou mais de 2 pontos de interrogação, por exemplo).

### [MKT-10] N-touch follow-up com timing inteligente
**Arquivo:** `src/services/followup_engine.py`

**Novas tabelas:** `followup_sequences` + `followup_sequence_steps`. Colunas extras em `followups`: `sequence_id`, `sequence_step`, `metadata_json`.

Fluxo:
- Admin cria sequência: N templates encadeados com `delay_hours` entre cada.
- `iniciar_sequencia_para_conversa(seq, conv, empresa, fone)` enfileira todos os steps, respeitando horário comercial BRT (8h-21h). Se cair fora, empurra pra próxima janela.
- `check_and_cancel_on_customer_activity(conv, empresa)` — o worker chama quando o cliente responde: cancela steps com condição `sem_resposta` pendentes (não incomoda cliente que voltou a conversar).
- `metricas_sequencia(empresa, seq)` — taxa de entrega por step.

## Estrutura de arquivos nova

```
src/services/
├── lead_scoring.py          [MKT-01]
├── sentiment_realtime.py    [MKT-02]
├── client_memory.py         [MKT-03]
├── kb_ingestion.py          [MKT-04]
├── voice_agent.py           [MKT-06]
├── roi_attribution.py       [MKT-07]
├── vision_analysis.py       [MKT-08]
├── agentic_rag.py           [MKT-09]
└── followup_engine.py       [MKT-10]

src/api/routers/
├── kb.py                    [MKT-04]
├── instagram_webhook.py     [MKT-05]
├── voice_webhook.py         [MKT-06]
└── leads_dashboard.py       [MKT-01/02/07]

src/tests/
├── test_lead_scoring.py
├── test_sentiment_realtime.py
├── test_followup_engine.py
└── test_roi_attribution.py

alembic/versions/
└── mkt01_features_novas.py    (cria 5 tabelas + 3 colunas)
```

## Como plugar no sistema (próximos passos que eu NÃO fiz pra não quebrar o fluxo atual)

**1. Registrar os novos routers em `main.py`:**

```python
from src.api.routers.kb import router as kb_router
from src.api.routers.instagram_webhook import router as ig_router
from src.api.routers.voice_webhook import router as voice_router
from src.api.routers.leads_dashboard import router as leads_router, alertas_router, roi_router

app.include_router(kb_router)
app.include_router(ig_router)
app.include_router(voice_router)
app.include_router(leads_router)
app.include_router(alertas_router)
app.include_router(roi_router)
```

**2. Plugar análise em tempo real no `stream_worker.py` / `bot_core.py`:**

Logo após receber a mensagem do cliente e identificar o `empresa_id` + `conversation_id`:

```python
from src.services.sentiment_realtime import analisar_mensagem
from src.services.lead_scoring import score_conversa
from src.services.client_memory import extract_and_store_facts
from src.services.followup_engine import check_and_cancel_on_customer_activity

# cliente respondeu -> cancela follow-ups com condicao 'sem_resposta'
await check_and_cancel_on_customer_activity(conversation_id, empresa_id)

# analisa msg pro alerta de escalacao
await analisar_mensagem(conversation_id, empresa_id, texto_cliente, sentimento_ia)

# rescore do lead (async, nao bloqueia resposta)
asyncio.create_task(score_conversa(conversation_id, empresa_id))

# acumula mensagens recentes; a cada 3+ msgs do cliente, extrai fatos
# (o bot_core.py tem buffet no Redis — dá pra pegar de lá)
await extract_and_store_facts(empresa_id, contato_fone, ultimas_msgs)
```

**3. Injetar memória no prompt LLM (onde monta o prompt hoje):**

```python
from src.services.client_memory import recall_for_prompt

memoria_bloco = await recall_for_prompt(empresa_id, contato_fone)
if memoria_bloco:
    prompt_blocos.append(memoria_bloco)
```

**4. Rodar a migration:**

```bash
docker compose run --rm api sh scripts/migrate.sh
# ou localmente
alembic upgrade head
```

**5. Dependências opcionais** (já estão em `requirements.txt` ou pode ser adicionadas):

```
beautifulsoup4>=4.12,<5    # para MKT-04 crawl site (opcional — tem fallback regex)
pypdf>=4.0,<6              # para MKT-04 upload-pdf (obrigatório)
```

**6. Envs novas (adicionar em `.env.production.example`):**

```
# MKT-02 sentimento
ALERT_WEBHOOK_URL=                           # Slack/Discord/n8n — opcional

# MKT-05 Instagram
INSTAGRAM_VERIFY_TOKEN=
INSTAGRAM_APP_SECRET=
INSTAGRAM_PAGE_ACCESS_TOKEN=

# MKT-06 Voice
VOICE_PROVIDER=disabled                      # vapi|retell|disabled
VAPI_API_KEY=
VAPI_ASSISTANT_ID=
VAPI_PHONE_NUMBER_ID=
VOICE_WEBHOOK_SECRET=                        # pra validar callback
```

## O que ficou fora (propositalmente)

- **Mobile app nativo (iOS/Android)** — escopo de 4-6 semanas de dev dedicado; fica pra sprint próprio.
- **Multi-agent orchestration** — Q1 2027 conforme roadmap de mercado.
- **Integração com ERPs de academia** — usuário pediu pra deixar pra depois.
- **Sub-agente de self-improvement** — vai exigir 500+ outcomes históricos pra ter sinal; faz sentido só depois de 3-6 meses de uso.

## Resumo de impacto

| Área | Antes | Depois | Gap fechado |
|---|---|---|---|
| Lead scoring | campo persistido, sem lógica | classifier + tier + endpoint + modelo ML evolutivo | ✅ |
| Sentimento | detecção pós-conversa | tempo real + alerta + webhook externo | ✅ |
| Memória cliente | tabela vazia | extração LLM + recall + decay + consolidação | ✅ |
| KB | indexação manual | crawl site + upload PDF + endpoint | ✅ |
| Instagram | — | webhook completo + pipeline existente reusado | ✅ |
| Voice | só TTS via Gemini | Vapi + Retell + tabela + webhook de callback | ✅ |
| ROI | — | atribuição lookback + dashboard + endpoint | ✅ |
| Multimodal | recebia, não analisava | 3 fluxos vision com GPT-4o | ✅ |
| RAG | linear 1-shot | agentic iterativo com planning | ✅ |
| Follow-up | 1 touch só | N-touch + business hours + cancelamento automático | ✅ |
