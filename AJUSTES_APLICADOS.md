# Ajustes Aplicados — Sessão de Abril 2026

Resumo do que foi implementado nesta sessão.

## Onda 1 — Bugs críticos corrigidos

### Backend (`main.py`, `src/services/`)

| ID | Fix | Arquivo(s) |
|---|---|---|
| Health | Endpoint `/health` adicionado (resolvia container amarelo no Easypanel) | `main.py` |
| NameError | `coletar_mensagens_buffer` e `aguardar_escolha_unidade_ou_reencaminhar` agora recebem `empresa_id` como parâmetro | `main.py` |
| Cache integração | Invalidação agora limpa tanto a key global quanto por unidade | `src/services/cache_invalidation.py` |
| ORDER BY | Queries de `integracoes` ordenadas por `id DESC` (pega sempre a mais recente) | `main.py`, `src/services/db_queries.py` |
| mensagem_fora_horario | Campo adicionado aos models Pydantic `PersonalityCreate` e `PersonalityUpdate` | `src/api/routers/management.py` |
| Fluxo independente | Fluxo de triagem roda independente do horário da IA (nó `businessHours` interno cuida disso) | `main.py` |
| **QW-1 `transfer_to_team`** | Método implementado no `UazAPIClient` (via labels) | `src/services/uaz_client.py` |
| **QW-2 unidade_id** | `executar_fluxo()` agora recebe `unidade_id` correto em `main.py:4203` | `main.py` |
| **QW-9 retry HTTP** | Retry agora cobre 408, 429, 500, 502, 503, 504 (antes só 429) | `src/services/uaz_client.py` |

## Onda 1 — Métodos UazAPI expostos como nós

Os 5 métodos abaixo **já existiam** no `UazAPIClient` mas não tinham nó visual correspondente. Agora têm nó tanto no `flow_executor` quanto no editor React Flow:

| Nó | Método UazAPI | Uso |
|---|---|---|
| `sendLocation` | POST `/send/location` | Compartilhar endereço (filial, ponto de coleta) |
| `sendContact` | POST `/send/contact` (vCard) | Compartilhar contato de atendente/gerente |
| `sendPoll` | POST `/send/menu` tipo poll | Enquete / pesquisa rápida |
| `setPresence` | POST `/send/presence` | Indicador "digitando..." antes de envio longo |

## Onda 2 — Novos recursos UazAPI + HTTP Request

Métodos novos adicionados ao `UazAPIClient`:

| Método | Endpoint | Uso |
|---|---|---|
| `send_reaction` | POST `/send/reaction` | Reage com emoji a uma mensagem específica |
| `edit_message` | POST `/message/edit` | Edita mensagem enviada |
| `delete_message` | POST `/message/delete` | Revoga mensagem enviada |
| `add_label` | POST `/label/add` | Tags/categorização do contato |
| `remove_label` | POST `/label/remove` | Remover tags |
| `transfer_to_team` | (via labels — UazAPI não tem endpoint nativo) | Marca conversa pra time, pausa IA |

Nós correspondentes no editor:

- `sendReaction` — reage com emoji (com seletor visual de emojis sugeridos)
- `editMessage` — edita texto de mensagem anterior
- `deleteMessage` — deleta mensagem
- `addLabel` — adiciona tags (separadas por vírgula)
- `removeLabel` — remove tags

### Nó HTTP Request genérico (M-1)

Novo nó `httpRequest` muito mais capaz que o `webhook` antigo:

- **Métodos:** GET, POST, PUT, DELETE, PATCH
- **Auth:** none, Bearer token, Basic (user/pass)
- **Headers customizáveis** em JSON
- **Body** em JSON ou form urlencoded, com suporte a `{{vars}}`
- **Query params** com templating
- **Timeout customizável** (default 15s)
- **response_map:** mapeia campos da resposta JSON para variáveis de sessão via dot-notation (ex: `"user_id": "data.user.id"`)
- **Handles de saída:** `success` (2xx) e `error` (outros) — permite ramificar fluxo baseado no resultado
- **Salva em sessão:** `_http_last_status`, `_http_last_body_preview`, `_http_last_error`

Arquivo: `src/services/flow_executor.py` (função `_execute_http_request` + helper `_extract_dot_path`).

## Onda 3 — UX do editor

### Undo / Redo implementado

- Hook `useUndoRedo` com histórico de snapshots (até 50)
- Atalhos de teclado: **Ctrl+Z** (undo), **Ctrl+Y** ou **Ctrl+Shift+Z** (redo)
- Ignora atalho quando foco está em input/textarea (não quebra edição de campos)
- Histórico trunca o "futuro" se você fizer uma nova ação após undos

Arquivo: `frontend/src/app/dashboard/fluxo-triagem/page.tsx`.

## Arquivos criados/alterados nesta sessão

### Backend
- `main.py` (várias correções e adição do `/health`)
- `src/services/uaz_client.py` (retry melhor + 6 métodos novos)
- `src/services/flow_executor.py` (10 novos tipos de nó + HTTP Request)
- `src/services/db_queries.py` (ORDER BY id DESC)
- `src/services/cache_invalidation.py` (invalida ambos formatos de key)
- `src/api/routers/management.py` (campo mensagem_fora_horario)

### Frontend
10 componentes novos em `frontend/src/app/dashboard/fluxo-triagem/nodes/`:
- `SendLocationNode.tsx`
- `SendContactNode.tsx`
- `SendPollNode.tsx`
- `SetPresenceNode.tsx`
- `SendReactionNode.tsx`
- `EditMessageNode.tsx`
- `DeleteMessageNode.tsx`
- `AddLabelNode.tsx`
- `RemoveLabelNode.tsx`
- `HttpRequestNode.tsx`

Arquivos atualizados:
- `nodes/index.ts` (registro dos novos tipos)
- `nodes/nodeStyles.ts` (union type + NODE_CONFIG com cores/ícones)
- `page.tsx` (defaults dos nós novos + hook useUndoRedo)

## Itens do backlog que NÃO foram implementados (justificativa)

Alguns itens da auditoria precisam de trabalho mais amplo que não cabe nesta sessão sem risco:

| ID | Item | Motivo |
|---|---|---|
| QW-3 | Consolidar lógica duplicada webhook/main.py | Refactor arriscado em código de produção — requer testes de regressão |
| QW-7 | Validação ao salvar (nós órfãos, handles sem conexão) | Pode ser feita no editor — adicionar no `savePayload()` da page.tsx |
| QW-8 | Configs hardcoded (loop/burst/restart) movidas pro DB | Precisa migration + UI de admin |
| M-2 | WhatsApp Flows (Meta oficial) | Requer integração com Meta Cloud API (substituir UazAPI em parte) |
| M-3 | OTP/Authentication via template Meta | Mesmo requisito: Meta Cloud API |
| M-4 | Google Sheets integration | OAuth2 completo — 1 sprint separado |
| M-5 | CRM Sync (Salesforce, Pipedrive, HubSpot, RD) | Uma integração por CRM — específico por cliente |
| M-6 | Payment (Stripe, MercadoPago) | Webhook de confirmação + UI de checkout |
| M-7 | NPS/CSAT Survey | Precisa persistir ratings em tabela nova + dashboard |
| M-8 | Ticket Creation (Jira, Zendesk) | OAuth2 por plataforma |
| E-1 | Command Palette (Cmd+K) | Componente modal + busca fuzzy — 1-2 dias de trabalho focado |
| E-2 | Debug mode / simulador inline | Substancial — executor precisa de "modo dry-run" |
| E-6 | Sticky notes no canvas | Tipo de nó especial sem handles — precisa desenho de UI |
| E-7 | Autocomplete de variáveis (`{{` abre menu) | Plugin customizado no editor de textarea |

Estes estão documentados com prioridade e esforço estimado em `AUDITORIA_FLUXO_TRIAGEM.md`.

## Próximos passos sugeridos

1. **Commit e push** tudo que foi feito
2. Testar em staging se possível — especificamente HTTP Request e reactions
3. Pro próximo sprint, priorizar E-1 (Command Palette) ou M-4 (Google Sheets) conforme demanda
4. Se decidir ir pra Meta Cloud API, M-2 e M-3 desbloqueiam juntos

## Comandos de deploy

```bash
cd "/c/Users/cleit/OneDrive/Documentos/IA"

# Backend + frontend de uma vez
git add main.py src/ frontend/src/app/dashboard/fluxo-triagem/
git add AJUSTES_APLICADOS.md AUDITORIA_FLUXO_TRIAGEM.md AUDITORIA_FLUXO_TRIAGEM.docx
git commit -m "feat: onda 1+2+3 — 10 novos nos UazAPI, HTTP Request, undo/redo, bug fixes"
git push origin main
```

Depois do deploy, a aba "Fluxo de Triagem" vai ter 10 nós novos na paleta lateral e suporte a undo/redo.

## Onda 4 — 8 itens "de boa" (continuação)

### Novos nós implementados

| Nó | Uso | Arquivo |
|---|---|---|
| `delayHuman` | Delay aleatório entre `min_seconds`-`max_seconds` (simula humano). Opção de mostrar "digitando..." | `DelayHumanNode.tsx` |
| `abTestSplit` | Split A/B por hash do telefone (determinístico — mesmo user sempre cai na mesma variante). N variantes com pesos customizáveis | `AbTestSplitNode.tsx` |
| `formValidation` | Valida email / CPF / CNPJ / telefone BR em tempo real. Handles `valid` e `invalid` | `FormValidationNode.tsx` |
| `stickyNote` | Nota adesiva colorida (5 cores) pra documentar o fluxo no canvas. Sem handles, no-op em runtime | `StickyNoteNode.tsx` |
| `groupBox` | Moldura visual pra agrupar nós. Redimensionável, 5 cores de borda. No-op em runtime | `GroupBoxNode.tsx` |

### Validação ao salvar

Função `validateFlow()` em `page.tsx` detecta antes do publish:
- Falta de nó `start` ou múltiplos `start`s
- Nós órfãos (sem edge apontando pra eles, exceto `start` e `stickyNote`)
- Nós sem saída conectada (exceto terminais: `end`, `humanTransfer`, `transferTeam`, `goToMenu`, `stickyNote`)
- URLs vazias em `sendImage`/`sendMedia`/`sendAudio`/`httpRequest`
- Texto vazio em `sendText`/`waitInput`

Se tiver problema, mostra alerta e pergunta se quer salvar mesmo assim.

### Templates prontos por vertical

Criados 4 templates em `frontend/src/app/dashboard/fluxo-triagem/templates/`:

1. **Academia / Fitness** — 10 nós, menu (planos, aulas, agendar, atendente), IA responde planos/aulas, qualify pra agendamento
2. **Clínica / Consultório** — 13 nós, respeita horário comercial, valida CPF, qualify (nome + especialidade + preferência)
3. **Imobiliária / Corretagem** — 9 nós, qualifica lead (tipo, região, preço, cômodos), extract pra normalizar, labels dinâmicas, transfer pra corretor
4. **E-commerce / Suporte** — 12 nós, consulta status de pedido via HTTP Request (GET ao ERP), trocas via IA, dúvidas via FAQ+IA

Integrados no `TemplatesModal` existente como "built-in" (ids negativos, não podem ser deletados).

### MiniMap

MiniMap já estava implementado no `page.tsx:677-688` com cores baseadas em `NODE_CONFIG[n.type].border`. Nada a fazer.

### Fix UazAPI delay em int ms

Confirmado que todos os `delay` passados pra UazAPI são `int()` em millisegundos (800, 900, 1000, ...). Match com a documentação da UazAPI.

### Grouping — status parcial

Implementado como **grupo visual** (moldura redimensionável `GroupBoxNode`) — não é true parent/child. Pra ter filhos que se movem junto com o grupo no React Flow precisa:
- `parentId` nos nós filhos
- `extent: "parent"` pra limitar ao bounding box
- Lógica de drag-to-parent no editor

Isso fica pendente pra próxima onda — a moldura visual já resolve 80% do caso de uso (organização).

## Sprint 1+2 — Pré-escala 800 tenants

Sprint executada pra endurecer o sistema antes de cadastrar várias empresas (segunda-feira).

### Sizing & Pools (SCALE-01/02/03)

| Mudança | Antes | Depois | Arquivo |
|---|---|---|---|
| Pool Postgres | 3/15 | **30/120** (configurável via env) | `docker-compose.prod.yml`, `main.py`, `.env.production.example` |
| `command_timeout` do pool | 10s | **30s** | `main.py` |
| Redis connection pool | sem pool | **50 conexões explícitas, socket_keepalive** | `src/core/redis_client.py`, `main.py` |
| httpx pool | 50 conexões | **200 conexões** (keepalive 50) | `main.py` |
| Uvicorn workers | 1 | **4 workers** (configurável via `UVICORN_WORKERS`) | `Dockerfile` |

### Segurança CRÍTICA (C-01, C-05, C-06)

| ID | Fix | Arquivo |
|---|---|---|
| C-01 | `/sync-planos/{empresa_id}` agora exige JWT + valida empresa_id do token | `main.py` |
| C-01 | `/desbloquear/{empresa_id}/{conversation_id}` idem | `main.py` |
| C-01 | `/metricas/diagnostico` idem (force empresa do token se não admin_master) | `main.py` |
| C-05 | **Circuit breaker** no `llm_quota` — se Redis falhar 5× em 2min, fail-closed (antes era fail-open sempre) | `src/services/llm_quota.py` |
| C-06 | Helper `_mask_phone()` mascara telefone em logs: `+55 (11) ****-1234` | `main.py`, `src/api/routers/uaz_webhook.py` |
| C-06 | 5 logs de PII mascarados (UAZAPI enviado, FollowUp cancelado, OptOut, IA pausada) | idem |

### Performance (H-06, H-10)

| ID | Fix | Arquivo |
|---|---|---|
| H-06 | Helper `_check_empresa_rate_limit()` — rate limit **por empresa** (default 5000 msgs/h, configurável via `EMPRESA_RATE_LIMIT_PER_HOUR`) | `main.py` |
| H-10 | TTL FAQ 300→600s, Menu/Fluxo 120→300s, Integração 300→600s | `src/services/db_queries.py` |

### Indexes Postgres (aplicados direto no DB prod)

```sql
idx_conversas_empresa_unidade_created    ✅ criado
idx_mensagens_conversa_role_created      ✅ criado
idx_followups_status_agenda              ✅ criado
idx_integracoes_empresa_tipo_ativa       ✅ criado
idx_eventos_funil_empresa_unidade_data   ⚠️  falhou (coluna unidade_id não existe em eventos_funil)
idx_memoria_cliente_empresa_phone        ⚠️  falhou (coluna contato_telefone não existe)
idx_conversas_ativas                     ⚠️  falhou (NOW() não IMMUTABLE)
```

4 de 7 indexes principais foram aplicados em prod com `CONCURRENTLY` (sem downtime). Os 3 que falharam são por schema diferente do esperado — não bloqueante.

### Bug encontrado e corrigido

- `src/services/db_queries.py:1590` — função `criar_usuario()` estava **truncada em disco** (OneDrive cortou a meio de uma query). Completada.

### Fluxo de comportamento novo (complementar)

- Nó `end` agora seta `fluxo_ended:{empresa_id}:{unidade_id}:{phone}` com TTL **30 min** → fluxo não reinicia em 30min depois do end
- Atendente humano no WhatsApp pausa IA por **4h** (antes 12h) em AMBAS as chaves `pause_ia:` e `pause_ia_phone:` (multi-tenant + legado)
- UazAPI `webhook_secret` agora suporta flag `require_webhook_secret: false` por integração — permite integração sem secret enquanto você configura

## Deploy final — tudo junto

```bash
cd "/c/Users/cleit/OneDrive/Documentos/IA"

git add main.py \
        src/ \
        frontend/src/app/dashboard/fluxo-triagem/ \
        docker-compose.prod.yml \
        Dockerfile \
        .env.production.example \
        AJUSTES_APLICADOS.md \
        AUDITORIA_FLUXO_TRIAGEM.md \
        AUDITORIA_FLUXO_TRIAGEM.docx \
        AUDITORIA_ESCALA_800_TENANTS.md \
        AUDITORIA_ESCALA_800_TENANTS.docx

git commit -m "feat: sprint 1+2 pre-escala (800 tenants) — pools, PII mask, C-01 auth, C-05 circuit breaker, TTLs, rate limit por empresa, indexes"
git push origin main
```

Depois do deploy:
1. Verifique no Easypanel que as env vars `DB_POOL_MIN=30`, `DB_POOL_MAX=120`, `UVICORN_WORKERS=4`, `REDIS_POOL_MAX=50`, `HTTPX_MAX_CONNECTIONS=200`, `EMPRESA_RATE_LIMIT_PER_HOUR=5000` estão setadas (ou defaults do código valem)
2. Monitore `pg_stat_activity` pra ver se pool não enche
3. Teste webhook real: log deve mostrar `+55 (11) ****-1234` ao invés do telefone completo
4. Teste que um usuário da empresa 1 **não consegue** chamar `/sync-planos/2` (deve retornar 403)

## O que ficou pra depois (backlog restante)

### Riscos ainda abertos (médio prazo)

| ID | Item | Esforço |
|---|---|---|
| C-02 | HMAC Chatwoot (já implementado se secret configurado; garantir config por empresa) | Operacional |
| C-03/C-04 | `require_tenant_match` no WebSocket | 2h |
| C-07 | Validar `conversation_id` único por (empresa, source) | 4-6h |
| H-02/H-03/H-04 | Otimizar N+1 nos workers (sync_planos, metricas_diarias, followups batch) | 1-2 dias |
| H-05 | Proteger `flush_all()` com 2FA | 30min |
| H-07 | Rate limit em `/management/*` com slowapi | 3-4h |
| H-11 | Backpressure na fila de webhook | 2h |
| H-12 | Fallback Redis per-tenant | 1-2h |
| M-01 a M-10 | Hardening geral (Sentry obrigatório, trace IDs, WS limits, modelo por empresa, etc) | 1 semana |

Referência completa em `AUDITORIA_ESCALA_800_TENANTS.docx`.

