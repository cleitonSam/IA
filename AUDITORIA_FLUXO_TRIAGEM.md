# Auditoria Fluxo de Triagem — Estado Atual, Benchmark de Mercado e Backlog Priorizado

Data: Abril 2026  
Escopo: Editor visual `fluxo-triagem` (React Flow), engine `flow_executor.py`, integração UazAPI, comparação com 14 plataformas de mercado.

---

## Sumário Executivo

O sistema de fluxo de triagem está num estágio maduro em termos de cobertura de nós (31 tipos, acima da média de mercado que fica em 15-25). A engine de execução tem recursos avançados como multi-tenancy correto, dedup idempotente e split semântico de mensagens. A stack front (React Flow + Next.js 14) está no mesmo nível visual de Voiceflow e Landbot.

**Os gaps mais relevantes estão em três eixos:**

1. **Bugs / dívidas técnicas críticas** no código atual (6 itens de alto risco, ver §3)
2. **Features do mercado ausentes** que são hoje padrão em plataformas competidoras — HTTP Request genérico, integração com planilhas/CRM, OTP, WhatsApp Flows da Meta
3. **Capacidades da UazAPI subutilizadas** — pelo menos 5 endpoints já disponíveis no provedor nunca viraram nó no editor (reactions, edit/delete, labels, location/contact já no client mas sem exposição)

Este documento lista 40+ melhorias acionáveis, priorizadas em três ondas (quick wins < 2 semanas, roadmap médio prazo, longo prazo).

---

## 1. Estado Atual — Auditoria Técnica

### 1.1 Tipos de nós implementados

**Total: 31 nós.** Cobertura abaixo agrupada por categoria:

| Categoria | Nós |
|---|---|
| **Controle** | `start`, `end`, `loop` (limitado a 3), `goToMenu` |
| **Envio** | `sendText`, `sendMenu`, `sendImage`, `sendAudio`, `sendMedia` |
| **Roteamento** | `switch` (match exato/numérico/palavra), `condition` (regex), `sourceFilter` (privado/grupo) |
| **Espera / Input** | `delay` (1-15s), `waitInput` |
| **Variáveis** | `setVariable`, `getVariable`, `generateProtocol` |
| **IA / LLM** | `aiRespond`, `aiClassify`, `aiSentiment`, `aiQualify`, `aiExtract`, `aiMenu`, `menuFixoIA`, `aiMenuDinamicoIA` |
| **Dados** | `search` (FAQ semântica), `redis` (set/get/del), `businessHours` (custom/global) |
| **Integração** | `humanTransfer`, `transferTeam`, `webhook`, `code` (Python `exec`) |

### 1.2 Capacidades UazAPI usadas

Métodos do `UazAPIClient` chamados hoje pelo `flow_executor`:

| Método | Endpoint | Usado por |
|---|---|---|
| `send_text` | POST `/send/text` | sendText, waitInput, aiRespond, aiSentiment, humanTransfer, transferTeam, aiQualify |
| `send_text_smart` | (wrapper custom com split ≤700 chars) | aiRespond, menuFixoIA, aiMenuDinamicoIA |
| `send_menu` | POST `/send/menu` | sendMenu, aiMenu, menuFixoIA, aiMenuDinamicoIA |
| `send_media` | POST `/send/media` | sendImage, sendAudio, sendMedia |
| `send_ppt` | wrapper de `send_media` | sendAudio |

Todas as chamadas incluem `track_source="chatbot"`, `readchat=true`, `readmessages=true`, retry 3x com backoff exponencial (1/2/4s) e timeout 15s. Retry só dispara em erros de rede e HTTP 429 — **HTTP 4xx/5xx (exceto 429) não têm retry**, o que pode causar falhas silenciosas.

### 1.3 Arquitetura do estado e multi-tenancy

O estado do fluxo por conversa é persistido em Redis com chaves `fluxo_state:{empresa_id}:{unidade_id}:{phone}` e `fluxo_vars:{empresa_id}:{unidade_id}:{phone}` (TTL 1800s / 30 min). Bom:

- Multi-tenant correto (empresa + unidade no prefixo)
- Contexto automático: `phone`, `hora`, `data`, `_unidade_id`, mais dot-notation em templates (`{{user.name}}`)
- Dedup de webhook por `message_id` (TTL 120s, estratégia SET nx)
- Bot-echo prevention com 3 variantes de chave (legacy, conv_id, multi-tenant)

### 1.4 Frontend (editor visual)

- Framework: **React Flow** (@xyflow/react) + Next.js 14 + TypeScript + Tailwind
- Arquivo principal: `frontend/src/app/dashboard/fluxo-triagem/page.tsx` (1200+ linhas)
- 31 componentes de nó (um por tipo) em `nodes/`
- Features presentes: drag & drop, deletar nó/edge, múltiplos handles (switch, aiSentiment, condition, search), import/export JSON, templates e tutorial modais, validação básica (start existe e conectado)
- Features ausentes: undo/redo, preview/debug, versionamento, grouping, command palette, inspeção de variáveis em runtime, validação de nós órfãos

---

## 2. Gaps de UazAPI — Capacidades não aproveitadas

### 2.1 Métodos implementados no client mas sem nó visual

| Método | Arquivo | Por que importa |
|---|---|---|
| `send_location` | `uaz_client.py:785-807` | Compartilhar endereço de filial, ponto de coleta |
| `send_contact` | `uaz_client.py:467-501` | Compartilhar vCard de atendente/gerente |
| `send_carousel` | `uaz_client.py:724-779` | Catálogo de produtos em triagem de venda |
| `send_poll` | `uaz_client.py:694-722` | Enquete de satisfação, pesquisas rápidas |
| `set_presence` | `uaz_client.py:278-295` | "digitando..." antes de envios longos (UX) |

**Ação rápida:** criar 5 nós novos (`sendLocation`, `sendContact`, `sendCarousel`, `sendPoll`, `setPresence`) — estimativa de 1 sprint porque o client já tem os métodos.

### 2.2 Endpoints UazAPI nunca utilizados (alto valor)

| Endpoint | O que faz | Caso de uso em triagem |
|---|---|---|
| POST `/send/reaction` | Reage com emoji a uma mensagem específica | Confirmação visual (👍 entendi, ❤️ resolvido) — reduz volume de mensagens |
| POST `/message/edit` | Edita mensagem já enviada | Corrigir typo ou atualizar horário/preço sem cancelar + reenviar |
| POST `/message/delete` | Revoga mensagem enviada | Remover mensagem sensível enviada por engano |
| POST `/send/text` (com `replyid`) | Resposta com quote | Contextualizar respostas em conversas longas — já existe parâmetro, mas sem nó expondo |
| POST `/label/add`, `/label/remove` | Tags/labels no contato | Categorizar cliente (VIP, problema, resolvido) — filtragem no painel |
| POST `/group/create`, `/group/invite`, `/group/remove` | Gerenciar grupos | Criar sala temporária de atendimento, escalar a grupo de especialistas |
| POST `/send/pix-button` | Botão com QR Code PIX | Vendas via WhatsApp — fechar pagamento sem sair da conversa |

### 2.3 Webhooks UazAPI ignorados

Atualmente o listener de webhook processa `message_created`. Eventos adicionais que a UazAPI emite e estamos ignorando:

- `reaction` — cliente reagiu com emoji a mensagem (permitiria fluxos reativos)
- `message.edit` — cliente editou mensagem (auditoria de correções)
- `message.revoke` — cliente deletou mensagem (auditoria de deleções)
- `group_participant` — entrou/saiu do grupo
- `message_status` — status de entrega/leitura (rastrear SLA de entrega)

---

## 3. Dívidas técnicas e bugs críticos

Inventário de riscos encontrados durante auditoria do código:

| ID | Local | Problema | Severidade |
|---|---|---|---|
| D1 | `flow_executor.py:832` | `uaz_client.transfer_to_team()` chamado via `hasattr` check mas **método nunca foi implementado** — `humanTransfer` apenas envia texto, não transfere de fato | 🔴 Alto |
| D2 | `flow_executor.py:975` (nó `code`) | `exec()` de código Python sem sandbox — acessa `__import__` livremente. **Security issue** se entrada vem de usuário confiável parcial | 🔴 Alto |
| D3 | `main.py:4115-4230` vs `uaz_webhook.py:197-234` | Lógica de fluxo duplicada em dois pontos de entrada (webhook + bot core monolith) | 🔴 Alto |
| D4 | `main.py:4203` | `executar_fluxo()` chamado sem `unidade_id` — sempre passa 0, quebra multi-tenancy por unidade | 🔴 Alto |
| D5 | `uaz_client.py:144-150` | HTTP 4xx (exceto 429) sem retry. Pode perder mensagens em falhas transientes que passam como 400 | 🟡 Médio |
| D6 | `humanTransfer` | Chave `pause_ia_phone` seta sem TTL definido — pode pausar IA indefinidamente | 🟡 Médio |
| D7 | `flow_executor.py:28` | `MAX_LOOP_COUNT=3` hardcoded — não customizável por fluxo | 🟡 Médio |
| D8 | `main.py:4136` | Anti-burst 30 msgs/h hardcoded | 🟡 Médio |
| D9 | `flow_executor.py:498` | Profundidade máxima 20 hardcoded | 🟡 Médio |
| D10 | `uaz_webhook.py:318` | Dedup só por `message_id` — se o mesmo payload vier com ids diferentes (reconnect), processa duplicado | 🟡 Médio |

**Bugs já corrigidos nesta sessão** (commit pendente):
- `NameError: empresa_id` em `coletar_mensagens_buffer` e `aguardar_escolha_unidade_ou_reencaminhar` (main.py)
- `/health` endpoint ausente — container ficava amarelo no Easypanel
- Cache de integração UazAPI não invalidava key global (só por unidade) — token antigo persistia
- Query de integração sem `ORDER BY id DESC` (retornava linha mais antiga com `LIMIT 1` em empate)
- `PersonalityCreate/Update` sem campo `mensagem_fora_horario` (AttributeError ao salvar)
- Fluxo de triagem travado no horário da IA — agora usa o próprio nó `businessHours`

---

## 4. Benchmark de Mercado (14 plataformas)

### 4.1 Tabela comparativa mestre

| Plataforma | Modelo | Preço base | # nós | Editor | IA nativa | Analytics | Multi-canal | Nota |
|---|---|---|---|---|---|---|---|---|
| **ManyChat** | SaaS | US$15-29/mês | ~15 | Excelente | GPT-4 | Completo | Sim | 8.5 |
| **Typebot** | OSS / Cloud | €0 self-host / €39 cloud | 34+ | Excelente | GPT-3.5+ | Bom | Sim | 8.0 |
| **Botpress** | OSS / SaaS | €0 OSS | N/A | Excelente | LLM (CALM) | Muito bom | Sim | 8.5 |
| **n8n** | OSS / SaaS | €0 OSS | 400+ | Excelente | AI Nodes v3 | Bom | Sim | 8.0 |
| **Voiceflow** | SaaS | US$60-150/ed/mês | ~15 | Excelente | GPT-4 multi-LLM | Muito bom | Sim | 8.5 |
| **Landbot** | SaaS | €40-400/mês | ~25 | Excelente | GPT-4 + Copilot | Muito bom | Sim | 8.0 |
| **Chatfuel** | SaaS | US$24-400/mês | ~20 | Muito bom | GPT-4 | Excelente | Sim | 8.0 |
| **Take Blip** | SaaS | Enterprise | ~30 | Excelente | GPT-4 | Excelente | Sim | 8.5 |
| **Zenvia** | SaaS | Variável | ~25 | Muito bom | Gen IA | Excelente | Sim | 7.5 |
| **Wati** | SaaS | €39+/mês | ~20 | Muito bom | GPT-4 | Muito bom | WhatsApp | 7.5 |
| **Rasa** | OSS / Pro | €0 OSS | Flows CALM | Dev | CALM LLM | Bom | API | 7.0 |
| **Tiledesk** | OSS | €0 | N/A | Muito bom | LLM + MCP | Bom | Sim | 7.5 |
| **Chatwoot** | OSS / SaaS | €0 | N/A (Captain) | Bom | Limitada | Excelente | Sim | 7.5 |
| **BotConversa** | SaaS | Variável (BR) | ~20 | Muito bom | Gen IA | Bom | WhatsApp | 7.0 |
| **Nosso sistema (hoje)** | Self-hosted | — | **31** | Muito bom (React Flow) | GPT/OpenRouter | Básico | WhatsApp + Chatwoot | **~7.5** |

### 4.2 Features que destoam em cada player (potenciais inspirações)

- **Voiceflow** — Command Palette (Cmd+K), autocomplete de variáveis em expressions, Git integration pré-alpha, multi-LLM routing por bloco
- **Landbot** — Hybrid AI (regras + LLM), AI Copilot inline que sugere blocos, operações matemáticas nativas (lead scoring em tempo real), parsing de texto não-estruturado
- **Typebot** — Fair-source, deploy fácil em Railway (~US$5-15/mês), blocks exportáveis em JSON versionáveis
- **n8n** — Expression editor estilo IDE com autocomplete JS, preview do output de cada nó em real-time, 400+ integrações
- **Rasa CALM** — Flows nomeados ("transfer_to_human", "collect_email") com LLM interpretando usuário e flows controlando lógica — arquitetura anti-hallucination
- **Botpress** — Autonomous Nodes (LLM decide ação), integração nativa com Slack/WA/Telegram/Web, actions customizáveis em JS/TS
- **ManyChat** — Live Chat integrado ao mesmo widget do fluxo, shared inbox, broadcast agendado
- **Take Blip** — BSP Badge oficial Meta, suporte a Apple Messages for Business, Google RCS, Teams — multi-canal nativo
- **Tiledesk** — Model Context Protocol (MCP) para tools externas, RAG nativo, human-in-the-loop workflows

### 4.3 Tipos de nó que o mercado tem e nós não temos

| Nó (nome de mercado) | O que faz | Plataformas | Valor (triagem) | Prioridade |
|---|---|---|---|---|
| **HTTP Request** | Chamar qualquer API REST (auth, query, body), transformar response em vars | n8n, Typebot, Rasa, Voiceflow | 🔴 Alto | Crítica |
| **WhatsApp Flows (Meta)** | Mini-apps dentro do chat (form builder oficial Meta 2024+) | Meta, Wati, ManyChat | 🔴 Muito alto | Crítica |
| **OTP / Authentication** | Gerar PIN, enviar via template Meta aprovada, validar resposta | Meta, Voiceflow | 🔴 Alto | Crítica |
| **Google Sheets** | Ler/escrever em abas (FAQ dinâmica, lookup) | Typebot, Voiceflow, n8n | 🟠 Alto | Alta |
| **CRM Sync** | Upsert contato em Salesforce/Pipedrive/HubSpot | n8n, Botpress, Landbot | 🟠 Alto | Alta |
| **Payment Gateway** | Stripe/MercadoPago checkout via chat | Typebot, Chatfuel | 🟠 Alto | Alta |
| **NPS/CSAT Survey** | Rating pós-triagem (1-5) + free text | Voiceflow, ManyChat | 🟠 Médio-alto | Alta |
| **Ticket Creation** | Criar ticket em helpdesk (Jira, Zendesk) | n8n, Botpress | 🟠 Alto | Alta |
| **Template Approval (Meta)** | Criar e submeter templates pra aprovação, tracking | Wati, Blip, ManyChat | 🟠 Alto | Alta |
| **Catalog / Products (WA)** | Listar produtos do catálogo WA | Meta, Wati | 🟠 Alto | Alta |
| **Subscription / Opt-in** | Gerenciar consentimento (LGPD/GDPR) com audit log | ManyChat, Wati | 🟠 Alto | Alta |
| **Calendar Booking** | Integrar Calendly, Google Cal, Outlook | Landbot, Typebot | 🟡 Médio | Média |
| **File Picker** | Upload de documentos/imagens pelo cliente | Typebot, Landbot | 🟡 Médio | Média |
| **A/B Test Split** | Dividir usuários em 2+ variantes | Voiceflow, ManyChat | 🟡 Médio | Média |
| **Form Validation** | Validar email/CPF/telefone em tempo real | Landbot, Typebot | 🟡 Médio | Média |
| **Idle Re-engagement** | Retomar conversa após inatividade | Voiceflow, Chatfuel | 🟡 Médio | Média |
| **Escalation SLA** | Timeout antes de handoff humano | Zendesk, Chatwoot | 🟡 Médio | Média |
| **Time-based Trigger** | Executar em horário específico (broadcast) | n8n, Botpress | 🟡 Médio | Média |
| **Delay Humanizado** | Delay aleatório + typing indicator | Landbot | ⚪ Baixo | Baixa |

### 4.4 UX do editor — padrões a adotar

Os editores líderes (Voiceflow, Landbot, n8n, Typebot) convergem em alguns padrões que o nosso ainda não tem:

1. **Command Palette (Cmd+K / Ctrl+K)** — buscar nó por nome, variável, tipo; navegar entre subflows; atalhos (undo/redo/copy/paste). VS Code, Figma, Discord tudo tem. Ganho: +30% velocidade.
2. **Undo / Redo com histórico** — React Flow oferece os hooks; falta implementar estado de histórico e shortcut Ctrl+Z.
3. **Inspetor de variáveis em runtime (debug)** — ver valores de vars enquanto simula o fluxo. Voiceflow, Botpress Studio, Typebot têm.
4. **Preview / simulador inline** — rodar o fluxo dentro do editor com input fictício, step-by-step. Typebot e Botpress têm.
5. **Breadcrumb + Mini Map** — orientação em fluxos grandes (>50 nós).
6. **Grouping / Collapse** — agrupar nós relacionados, collapse pra reduzir visual clutter. n8n tem.
7. **Sticky notes no canvas** — documentação inline do fluxo. Figma e n8n têm.
8. **Autocomplete de variáveis em expressions** — `{{` abre menu de vars disponíveis. Voiceflow e n8n têm.
9. **Versionamento com diff visual** — exportar como YAML/JSON, commit com mensagem, diff entre versões. Voiceflow pré-alpha, Botpress Studio tem.
10. **Validação ao salvar** — detectar nós órfãos, handles sem conexão, loops sem exit, variáveis usadas mas nunca setadas.

---

## 5. WhatsApp Cloud API (Meta) — Feature gap estrutural

UazAPI é uma API não-oficial. Features que existem no oficial Meta Cloud API e simplesmente não chegam ao UazAPI:

| Feature | UazAPI | Meta Cloud | Impacto |
|---|---|---|---|
| **WhatsApp Flows** (mini-apps dentro do chat) | ❌ | ✅ | Conversão até 3x maior em captura de leads |
| **Template approval flow** com aprovação automatizada | ❌ | ✅ 1-3 dias | Compliance + broadcasting fora da janela de 24h |
| **OTP Template** com aprovação instantânea | ❌ | ✅ | Reset do relógio de 24h + KYC legal |
| **Catalog & Products** | ❌ | ✅ | E-commerce nativo |
| **Messaging limits tiered** (1K → 10K → 100K/dia) | 🤷 Desconhecido | ✅ | Escalabilidade previsível |
| **Official support + SLA** | ❌ | ✅ 24/7 | Enterprise-ready |
| **Compliance LGPD/GDPR** | Parcial | ✅ audit log oficial | Necessário pra enterprise |

**Estratégia recomendada:** manter UazAPI como default (flexibilidade, custo), oferecer um tier "Plus" com Meta Cloud API como opt-in pra clientes que exigem compliance.

---

## 6. Backlog Priorizado

### Onda 1 — Quick Wins (≤2 semanas, impacto imediato)

Tudo aqui é correção ou exposição de recursos que já existem no código:

| ID | Item | Esforço | Benefício |
|---|---|---|---|
| QW-1 | Corrigir D1: implementar `transfer_to_team()` no `UazAPIClient` ou remover o hasattr check | 2-4h | `humanTransfer` funciona como prometido |
| QW-2 | Corrigir D4: passar `unidade_id` em `executar_fluxo()` no main.py:4203 | 1h | Multi-tenancy por unidade restabelecida |
| QW-3 | Consolidar D3: remover execução duplicada do fluxo (escolher um ponto único: webhook OU main.py) | 4-8h | Elimina race conditions e inconsistência |
| QW-4 | Corrigir D6: setar TTL explícito em `pause_ia_phone` (ex: 43200s = 12h) | 30min | Evita pausa indefinida da IA |
| QW-5 | Expor `send_location`, `send_contact`, `send_poll` e `set_presence` como nós visuais | 1 sprint | 4 features já no client, só faltam componentes |
| QW-6 | Adicionar undo/redo no editor (hook `useReactFlow`) | 1-2d | Feature esperada de qualquer editor moderno |
| QW-7 | Validação de fluxo ao salvar (nós órfãos, handles sem conexão) | 1-2d | Previne erros em produção |
| QW-8 | Rate limit / loop limit vindo da config no DB (ao invés de hardcoded) | 1-2d | Operadores ajustam sem deploy |
| QW-9 | Retry HTTP 4xx (5xx também) com lista de status retentáveis (ex: 408, 500, 502, 503, 504) | 1d | Menos mensagens perdidas |

### Onda 2 — Features do mercado (2-12 semanas)

Priorizadas pelo trio impacto / diferencial / esforço:

| ID | Item | Referência | Esforço | Prioridade |
|---|---|---|---|---|
| M-1 | Nó **HTTP Request** genérico (GET/POST/PUT/DELETE, headers, body template) | n8n, Typebot | 2-3d | 🔴 Crítica |
| M-2 | Nó **WhatsApp Flows** (Meta oficial) — requer primeiro integrar Meta Cloud API | Meta, Wati | 2-3 sprints | 🔴 Crítica (tier Plus) |
| M-3 | Nó **OTP** (gerar PIN 6 dígitos, enviar template aprovado, validar com waitInput) | Meta, Voiceflow | 3-5d | 🔴 Crítica |
| M-4 | Nó **Google Sheets** (ler + escrever, OAuth2) | Typebot, Voiceflow | 1 sprint | 🟠 Alta |
| M-5 | Nó **CRM Sync** (Salesforce, Pipedrive, HubSpot, RD Station) | n8n, Botpress | 1-2 sprints | 🟠 Alta |
| M-6 | Nó **Payment** (Stripe + MercadoPago para BR) | Typebot, Chatfuel | 1 sprint | 🟠 Alta |
| M-7 | Nó **NPS/CSAT** (rating 1-5 + free text, salva em DB) | Voiceflow, ManyChat | 3-5d | 🟠 Alta |
| M-8 | Nó **Ticket Creation** (Jira, Zendesk, Freshdesk, Chatwoot interno) | n8n, Botpress | 1 sprint | 🟠 Alta |
| M-9 | Nó **Reaction** (usa POST `/send/reaction` da UazAPI) | — | 1-2d | 🟠 Média-alta |
| M-10 | Nós **Edit / Delete Message** | — | 1-2d | 🟡 Média |
| M-11 | Nó **Label/Tag contact** (POST `/label/add` e `/label/remove`) | ManyChat | 2-3d | 🟡 Média |
| M-12 | Nó **Calendar Booking** (Google Cal + Outlook + Calendly) | Landbot, Typebot | 1-2 sprints | 🟡 Média |
| M-13 | Nó **File Upload** (receber documento do cliente, validar, armazenar) | Typebot, Landbot | 1 sprint | 🟡 Média |
| M-14 | Nó **A/B Test Split** (split por percentual + tracking do branch escolhido) | Voiceflow, ManyChat | 3-5d | 🟡 Média |
| M-15 | Nó **Form Validation** (CPF, CNPJ, email, telefone BR) | Landbot | 2-3d | 🟡 Média |
| M-16 | Nó **Idle Re-engagement** (se inativo X minutos, dispara follow-up) | Voiceflow | 3-5d | 🟡 Média |
| M-17 | Nó **Escalation SLA** (se bot não resolveu em X min, transfere humano) | Chatwoot | 2-3d | 🟡 Média |
| M-18 | Nó **Subscription / Opt-in** com audit log (LGPD) | ManyChat, Wati | 1 sprint | 🟡 Média |

### Onda 3 — UX do editor (1-3 meses)

| ID | Item | Esforço | Benefício |
|---|---|---|---|
| E-1 | **Command Palette** (Cmd+K) — buscar nós, vars, subfluxos | 1 sprint | +30% velocidade |
| E-2 | **Debug mode** com step-by-step e inspetor de variáveis | 2-3 sprints | Reduz bugs em produção drasticamente |
| E-3 | **Preview / simulador** inline no editor (input fictício) | 1-2 sprints | Desenhistas validam sem deploy |
| E-4 | **Versionamento** com export YAML/JSON, commit message, diff visual | 2-3 sprints | Enterprise feature, desbloqueia Git |
| E-5 | **Grouping / Collapse** de nós | 3-5d | Legibilidade em fluxos grandes |
| E-6 | **Sticky notes** no canvas | 1-2d | Documentação inline |
| E-7 | **Autocomplete de variáveis** (`{{` abre menu com vars disponíveis) | 3-5d | Reduz erros de digitação |
| E-8 | **Breadcrumb + mini map** para fluxos grandes | 3-5d | Orientação em >50 nós |
| E-9 | **Templates pré-prontos** por vertical (imobiliária, academia, clínica, jurídico, e-commerce) | 2-3 sprints | Onboarding mais rápido |
| E-10 | **Analytics inline** (taxa de conclusão por nó, drop-off, tempo médio) | 2-3 sprints | Otimização data-driven |

### Onda 4 — Arquitetura / plataforma (3-6 meses)

- Migração opcional pra **Meta Cloud API** oficial (tier Plus), com Flows, Templates e OTP nativos
- **Sandbox de segurança** no nó `code` (RestrictedPython ou workers isolados)
- **Audit log completo** de todas as interações (LGPD-ready)
- **Multi-language UI** (pt-BR, en, es) para expandir além do BR
- **Observabilidade**: métricas de fluxo por nó (Prometheus + Grafana), alertas de drop-off

---

## 7. Ordem recomendada de execução

Considerando que o sistema já está em produção com clientes reais, a ordem abaixo maximiza valor entregue com menor risco:

**Sprint 1-2 (imediato):** Onda 1 completa (QW-1 a QW-9). Consertar bugs primeiro, depois expor recursos já prontos. É o único trabalho com ROI positivo garantido.

**Sprint 3-6 (curto prazo):** M-1 (HTTP Request), M-3 (OTP via UazAPI se for o caso, ou só esqueleto), M-9/10/11 (reaction, edit/delete, labels — tudo UazAPI já suporta), e Onda 3 começando com E-1 (Command Palette), E-5 (Grouping) e E-7 (Autocomplete).

**Sprint 7-12 (médio prazo):** M-4 (Sheets), M-5 (CRM), M-6 (Payment), M-7 (NPS), E-2 (Debug mode) e E-9 (Templates por vertical).

**Sprint 13+ (longo prazo):** Decisão estratégica sobre Meta Cloud API oficial — se decidir ir, M-2 (WhatsApp Flows) e Onda 4 completa. Se não, focar em diferenciais no lado UazAPI (compliance automatizada, multi-tenancy avançado, templates verticais).

---

## 8. Fontes

Documentação oficial consultada:

- UazAPI: https://docs.uazapi.com/
- ManyChat: https://manychat.com/pricing, https://help.manychat.com
- Typebot: https://typebot.io, https://docs.typebot.io
- Botpress: https://botpress.com/docs
- n8n: https://n8n.io
- Voiceflow: https://www.voiceflow.com
- Landbot: https://landbot.io
- Take Blip: https://www.blip.ai
- Zenvia: https://zenvia.com
- Wati: https://www.wati.io
- Meta WhatsApp Business: https://developers.facebook.com/docs/whatsapp
- Rasa: https://rasa.com/docs
- Tiledesk: https://tiledesk.com
- Chatwoot: https://www.chatwoot.com
- BotConversa: https://botconversa.com.br

Código-fonte do projeto analisado:
- `src/services/flow_executor.py`
- `src/services/uaz_client.py`
- `src/services/db_queries.py`
- `src/api/routers/uaz_webhook.py`
- `main.py` (linhas 4060-4230)
- `frontend/src/app/dashboard/fluxo-triagem/page.tsx`
- `frontend/src/app/dashboard/fluxo-triagem/nodes/*.tsx`
