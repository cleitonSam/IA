# Cache invalidation + auditoria de configuração (abril 2026)

## Problema resolvido

Antes dessa iteração, quando você editava FAQ / personalidade / KB no dashboard, a IA continuava usando o conteúdo antigo por até **5 minutos** (TTL dos caches). Isso criava a sensação de que "o bot não está pegando o que eu atualizei".

Agora: **toda vez que você salva algo no admin, o cache é limpo imediatamente**. A próxima mensagem do cliente já usa o conteúdo novo.

## O que foi feito

### [CACHE-01] Invalidação automática

Criado `src/services/cache_invalidation.py` com funções centralizadas por tipo:

| Função | Limpa |
|---|---|
| `invalidate_personalidade(empresa_id)` | personalidade + menu + fluxo + global |
| `invalidate_faq(empresa_id, slug=None)` | FAQ (formatado + raw) + RAG cache |
| `invalidate_kb(empresa_id)` | knowledge base / RAG |
| `invalidate_menu_triagem(empresa_id)` | menu de triagem |
| `invalidate_fluxo_triagem(empresa_id)` | fluxo visual |
| `invalidate_integracao(empresa_id, tipo=None)` | chatwoot / uazapi / evo |
| `invalidate_unidades(empresa_id)` | lista + individuais + FAQ (dependem de unidade) |
| `invalidate_planos(empresa_id)` | planos ativos |
| `invalidate_global(empresa_id)` | config global |
| `flush_empresa(empresa_id)` | TUDO da empresa (botão "limpar memória") |
| `flush_all()` | NUCLEAR: todas as empresas (só admin_master) |

### Endpoints que agora invalidam cache automaticamente

Plugados em `src/api/routers/management.py`:

| Endpoint | Invalida |
|---|---|
| `POST /management/personalities` | personalidade |
| `PUT /management/personalities/{id}` | personalidade |
| `DELETE /management/personalities/{id}` | personalidade |
| `POST /management/fluxo-triagem` | fluxo + personalidade |
| `POST /management/faq` | FAQ |
| `PUT /management/faq/{id}` | FAQ |
| `DELETE /management/faq/{id}` | FAQ |
| `POST /management/knowledge-base` | KB + FAQ |
| `DELETE /management/knowledge-base/{id}` | KB + FAQ |
| `PUT /management/integrations/{tipo}` | integração (todas variantes) |
| `PUT /management/integrations/evo/unit/{id}` | integração EVO |
| `POST /management/planos` | planos |
| `PUT /management/planos/{id}` | planos |
| `DELETE /management/planos/{id}` | planos |
| `POST /management/planos/sync` | planos |

### [CACHE-02] Endpoints admin novos (`src/api/routers/cache_admin.py`)

Botões pro dashboard que te permitem limpar cache manualmente:

| Endpoint | Uso |
|---|---|
| `POST /api/cache/flush` | Limpa TUDO da empresa — "forçar recarregamento" |
| `POST /api/cache/flush/faq` | Só FAQ |
| `POST /api/cache/flush/kb` | Só knowledge base |
| `POST /api/cache/flush/personalidade` | Só personalidade/menu/fluxo |
| `POST /api/cache/flush/integracao?tipo=chatwoot` | Só integração |
| `POST /api/cache/flush/planos` | Só planos |
| `GET /api/cache/config-status` | **Auditoria: quais campos estão vazios** |
| `POST /api/cache/flush/all` | Admin_master: TODAS as empresas |

### `GET /api/cache/config-status` — o endpoint mais útil

Retorna:
```json
{
  "empresa_id": 1,
  "tem_personalidade_ativa": true,
  "completude_pct": 66.7,
  "campos_ok": ["nome_ia", "personalidade", "tom_voz", ...],
  "campos_vazios": [
    {"campo": "objetivos_venda", "descricao": "Objetivos comerciais (ex: qualificar lead)"},
    {"campo": "scripts_objecoes", "descricao": "Scripts para objeções (preço alto, falta de tempo)"}
  ],
  "contadores": {
    "faqs_ativas": 15,
    "kb_items": 3,
    "planos_ativos": 5,
    "unidades_ativas": 2
  },
  "alertas": [
    "ATENCAO: menos de 50% dos campos..."
  ]
}
```

**Use isso no dashboard pra mostrar "Completude do bot: 67%" e listar o que falta preencher.**

## Campos hardcoded encontrados que podem mascarar vazios

Durante a auditoria encontrei 10+ pontos no código onde a IA usa **default hardcoded** quando o admin não preencheu o campo. Listados abaixo — **se esses campos estiverem vazios no dashboard, o bot NÃO vai ser personalizado**:

| Arquivo | Linha | Default usado | Campo que deveria preencher |
|---|---|---|---|
| `flow_executor.py` | 702 | `"Assistente"` | `personalidade_ia.nome_ia` |
| `bot_core.py` | 692 | `"Assistente"` | `personalidade_ia.nome_ia` |
| `bot_core.py` | 1077 | `"Assistente"` | `personalidade_ia.nome_ia` |
| `bot_core.py` | 1113 | `"Assistente Virtual"` | `personalidade_ia.nome_ia` |
| `bot_core.py` | 1404 | `"Profissional, claro e prestativo"` | `personalidade_ia.tom_voz` |
| `bot_core.py` | 1406 | `"Olá! Sou {nome_ia}, como posso ajudar?"` | `personalidade_ia.saudacao_personalizada` |
| `bot_core.py` | 2583 | `"Assistente Virtual"` | `personalidade_ia.nome_ia` |
| `bot_core.py` | 2632 | `"Assistente"` | `personalidade_ia.nome_ia` |
| `bot_core.py` | 2677 | `"Cliente"` | nome do cliente (quando não coletado) |

**Como resolver:** use o endpoint `GET /api/cache/config-status` pra ver quais campos estão vazios na sua personalidade ativa. Preencha todos, e o bot vai parar de cair nesses defaults.

## Como usar no frontend (dashboard)

### 1. Indicador de completude no topo do dashboard
```js
const status = await fetch("/api/cache/config-status").then(r => r.json())
// Mostra: "Completude do bot: 67% — 3 campos faltando"
// Lista campos_vazios pra admin preencher
```

### 2. Botão "Limpar memória do bot"
```js
await fetch("/api/cache/flush", { method: "POST" })
// Toast: "Cache limpo! Próxima mensagem vai usar conteúdo atualizado."
```

### 3. Página de FAQ — ao salvar, já invalida automaticamente
Nenhuma mudança no frontend necessária — o backend já limpa cache em cada save.

## O que NÃO foi mexido (propositadamente)

- **`memoria_cliente` (tabela)** — são fatos do cliente (preferências, objeções passadas). Não deve ser limpa quando FAQ/info muda.
- **`conversas` e `mensagens_locais`** — histórico operacional, não é cache.
- **Testes** — cache_invalidation é simples o suficiente pra não precisar de teste isolado; a lógica é testada indiretamente pelos endpoints.

## Arquivos novos/modificados

**Novos:**
- `src/services/cache_invalidation.py`
- `src/api/routers/cache_admin.py`
- `CACHE_AND_CONFIG.md` (este arquivo)

**Modificados:**
- `src/api/routers/management.py` (import + 10+ endpoints agora invalidam)
- `main.py` (registra cache_admin router)
