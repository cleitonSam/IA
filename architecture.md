# Arquitetura do Motor SaaS IA (Versão Enterprise 🚀)

Este documento descreve a arquitetura profissional e escalável do projeto, evoluída para suportar alta carga e múltiplos processos através de uma estrutura orientada a eventos.

## 1. Visão Geral do Sistema

O "Motor SaaS IA" é uma plataforma assíncrona baseada em **FastAPI** projetada para escala. Ele utiliza uma arquitetura desacoplada onde a recepção de dados (API) e o processamento inteligente (IA) ocorrem de forma independente, garantindo resiliência e baixa latência.

### 1.1 Diferenciais da Nova Estrutura
- **Arquitetura Event-Driven**: Uso de **Redis Streams** para separar o recebimento de webhooks do processamento pesado.
- **Isolamento de Processos**: Possibilidade de rodar containers específicos para API e outros para Workers através da variável `APP_MODE`.
- **Persistência Segura**: Migrações de banco de dados gerenciadas via **Alembic**.
- **Observabilidade**: Métricas nativas para Prometheus e dashboards no Grafana.

## 2. Estrutura de Diretórios

O projeto segue um padrão modular rigoroso:

```text
IA/
├── alembic/              # Gerenciamento de migrações do PostgreSQL.
├── src/                  # Código fonte principal
│   ├── api/              # Camada de Interface (Routers FastAPI)
│   │   └── routers/
│   │       ├── webhook.py # Receptor ultrarrápido (apenas enfileira jobs).
│   │       └── system.py  # Diagnósticos, Métricas e Health.
│   ├── core/             # Core Infra (Bancos, Redis, Configs).
│   ├── services/         # Lógica de Negócio e Orquestração
│   │   ├── bot_core.py    # O "Cérebro" do processamento de IA.
│   │   ├── stream_worker.py # Consumidor de filas de alta performance.
│   │   └── workers.py     # Background tasks (Follow-ups, Métricas).
│   └── utils/            # Helpers puros (Texto, Tempo, Intenções).
├── Dockerfile            # Configuração de containerização.
├── docker-compose.yml    # Orquestração de serviços API/Worker.
└── main.py               # Ponto de entrada unificado.
```

## 3. Fluxo de Dados de Alta Performance

A grande inovação desta arquitetura é o fluxo assíncrono:

1.  **Ingestão**: O Chatwoot envia um webhook para `/webhook`.
2.  **Enfileiramento**: A API valida a assinatura e joga o payload bruto no **Redis Stream** (`ia:webhook:stream`).
3.  **Resposta Instantânea**: A API retorna `200 OK` (enfileirado) em milissegundos, liberando o Chatwoot.
4.  **Consumo**: O `stream_worker.py` (rodando em um processo isolado) detecta a mensagem no Stream através de um **Consumer Group**.
5.  **Processamento**: O Worker chama o `bot_core.py` que consulta o Postgres, monta o contexto e aciona o LLM via OpenRouter.
6.  **Entrega**: O resultado é enviado de volta para a conversa no Chatwoot via HTTPX.

## 4. Modos de Operação (`APP_MODE`)

A aplicação pode ser escalada horizontalmente alterando apenas uma variável de ambiente:

- **`APP_MODE=api`**: O container atua apenas como servidor web, recebendo mensagens.
- **`APP_MODE=worker`**: O container foca exclusivamente em esvaziar a fila de mensagens e realizar tarefas de background (follow-up).
- **`APP_MODE=both`**: Modo híbrido (padrão para desenvolvimento/pequenas escalas).

---
> [!IMPORTANT]  
> Esta arquitetura permite que, em caso de picos de tráfego, você aumente apenas o número de instâncias de `worker` no Easypanel, mantendo a API leve e responsiva.
