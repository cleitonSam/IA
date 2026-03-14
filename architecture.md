# Arquitetura do Motor SaaS IA (Atualizada)

Este documento descreve a arquitetura atualizada do projeto após o processo de refatoração, que transformou a aplicação de um monolito (um único arquivo [main.py](file:///Users/macbook/Projetos/IA/IA/main.py)) para uma arquitetura modular, escalável e de fácil manutenção estruturada no diretório `src/`.

## 1. Visão Geral do Sistema

O "Motor SaaS IA" é uma aplicação assíncrona baseada em **FastAPI** que atua como um webhook inteligente para o **Chatwoot**. Ele intercepta mensagens, tenta resolvê-las utilizando lógica determinística (Fast-Path) e, se necessário, delega a resposta para provedores de LLM (como OpenRouter e OpenAI).

### 1.1 Funcionalidades Core
- **Webhook Handler**: Recebe e despacha os eventos vindos do Chatwoot no Endpoint `/webhook`.
- **Inteligência de Sessão e Funil**: Monitoramento da intenção do usuário, mantendo contexto e cache de conversas.
- **Rate Limiting Global e Local**: Proteção em múltiplas camadas usando Redis (por IP, Endpoint e Conversa).
- **Circuit Breaker**: Proteção contra falhas no LLM, evitando travamentos, timeout em cascata e gastos desnecessários.
- **Fast-Path / Roteador de Intenções**: Análise rápida via Regex para responder dúvidas de horários, localizações e FAQs sem onerar chamadas pesadas ao LLM.
- **Persistência Dinâmica**: Estado de conversas no Redis (`redis.asyncio`) e dados analíticos/operacionais via `asyncpg` no PostgreSQL.

## 2. Arquitetura Modularizada (Diretório `src/`)

Para curar a dor do "Deus-Objeto" presente anteriormente no [main.py](file:///Users/macbook/Projetos/IA/IA/main.py), o projeto adota o padrão de **Separação de Contextos (Clean Architecture Pattern)** agrupando as lógicas da seguinte maneira:

```text
IA/
├── requirements.txt
├── .env
├── main.py                   # Ponto de Entrada (Launcher) do FastAPI. Declara Middlewares globais e Lifecycle (On Startup/Shutdown), amarrando as rotas da API.
└── src/                      # Código Mestre da Aplicação
    │
    ├── core/                 # Infraestrutura, Segurança e Configurações Centrais.
    │   ├── config.py         # Leitura de variáveis de ambiente do .env e Loggers globais.
    │   ├── database.py       # Gerenciamento do Pool de conexões assíncronas (AsyncPG) e fechamento do DB.
    │   ├── redis_client.py   # Gerenciamento do client Redis e fallbacks locais na ausência de instâncias.
    │   └── security.py       # Padrão CircuitBreaker e restrições limitadoras do backend (RateLimits de LLM).
    │
    ├── api/                  # Camada de Apresentação (Interface Externa / Rotas HTTP).
    │   └── routers/
    │       ├── webhook.py    # Rotas essenciais como o POST do Chatwoot webhook e deboucing via BackgroundTasks.
    │       └── system.py     # Endpoints utilitários (Health checks, Metrics Prometheus, Diagnósticos de DB).
    │
    ├── services/             # Camada de Domínio / Regras de Negócio e Orquestração Pura.
    │   ├── llm_service.py    # Factory Global do AsyncOpenAI (OpenRouter/OpenAI API) com detecção analítica de erros da infra de LLM.
    │   └── bot_core.py       # "Coração" do webhook. Deleção direta responsável por disparar tarefas assíncronas de gravação, formatação do prompt mágico e comunicação direta com a API original do Chatwoot (HTTPX).
    │
    └── utils/                # Camada Util / Agregados Universais sem acoplamento a serviços de estado (Nem DB, nem Redis).
        ├── text_helpers.py   # Limpeza regex de markdown, extração de intenção por textos e normalização avançada de nomes.
        ├── time_helpers.py   # Padronização timezone "America/Sao_Paulo", formatação de horas abertas/fechadas.
        └── intent_helpers.py # Avaliação heurística e determinística em strings base para pular chamadas a IA.
```

### 2.1 Vantagens Obtidas
- **Resiliência e Identificação Rápida de Bug:** Como o [main.py](file:///Users/macbook/Projetos/IA/IA/main.py) foi reduzido de ~4.500 linhas para apenas cerca de 37 linhas, um erro que ocorre na conversação do bot e um erro no banco de dados residem em arquivos totalmente distintos (`bot_core.py` e [database.py](file:///Users/macbook/Projetos/IA/IA/src/core/database.py)).
- **Desbloqueamento da Equipe:** Com a separação baseada no domínio do App, múltiplos desenvolvedores têm menos chance de sofrer conflitos severos de *Merge* num sistema VCS.
- **Preparação para Testes:** As lógicas extraídas para a pasta `src/utils` foram desanexadas do protocolo REST (FastAPI) de modo que injetar testes unitários usando `pytest` torna-se trivial na validação do roteador Regex local.
- **Injeção de API Simples:** Para cada nova feature externa (como uma dashboard ou sincronizador futuro), cria-se simplesmente um novo router dentro de `src/api/routers/`.

## 3. Fluxo Base de Execução
1. O uvicorn chama o objeto `app` no **`main.py`**.
2. O Lifecycle chama `init_db_pool()` do `database.py` e levanta o Redis (`redis_client.py`).
3. Uma notificação do chatwoot atinge o endpoint ativo `/webhook` (dentro de `src/api/routers/webhook.py`).
4. Funções em **`utils/intent_helpers.py`** validam rapidamente a necessidade de resposta imediata via DB local em fallback ou caching. 
5. Caso necessite inteligência pesada de vendas/marketing, o **`services/bot_core.py`** consolida o *Prompt Mágico* através de variáveis unificadas e delega a missão transacional ao OpenRouter via provedor **`services/llm_service.py`**.
