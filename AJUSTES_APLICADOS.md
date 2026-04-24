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
