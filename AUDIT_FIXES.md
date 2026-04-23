# Auditoria — Correções aplicadas (2026-04-23)

Correções feitas a partir do relatório `Auditoria_Fluxo_IA.docx`. Cada item tem um **ID** (SEC/ARQ/QLD/INF) que aparece como comentário no código.

## Como validar

```bash
# Lint
ruff check .
ruff format --check .

# Testes
pytest -v

# Typecheck frontend
cd frontend && npx tsc --noEmit

# Pre-commit (uma vez, instalado globalmente)
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

## Sprint 0 — Críticos

### SEC-01 — Credenciais expostas no git
- `.gitignore` reforçado (agora bloqueia `.env.*`, venv, `=*` e outros artefatos).
- `src/core/config.py` valida que `JWT_SECRET_KEY` tem ≥ 32 chars e não é placeholder.
- **Ação manual pendente:** você já rotacionou as credenciais. Agora rode:
  ```bash
  git rm --cached .env
  git rm -r --cached lib/
  git rm --cached "=1.0.0"
  git commit -m "chore(security): remove secrets and venv from tracking"
  git push
  # Para limpar histórico (opcional, reescreve commits):
  pip install git-filter-repo
  git filter-repo --path .env --invert-paths
  git filter-repo --path lib --invert-paths
  ```

### SEC-02 — Isolamento multi-tenant
- Criada dependência central `src/core/tenant.py` com `require_tenant`, `require_tenant_match`, `require_tenant_owns`, `require_admin_master`.
- Padrão de uso documentado na docstring do módulo.
- **Próximo passo:** aplicar `require_tenant` nos endpoints de `management.py` que hoje pegam `empresa_id` do query/body sem validar. Ver `src/core/tenant.py` para exemplos.

### SEC-03 — Webhook fail-closed
- `main.py` (webhook Chatwoot): rejeita com 400 se `webhook_secret` ausente.
- `src/api/routers/uaz_webhook.py`: rejeita + usa `hmac.compare_digest` (constant-time).
- Migration `audit01_audit_log_and_webhook_secret.py` preenche `webhook_secret` em integrações antigas.

### SEC-04 — Token WebSocket em query string
- **Pendente:** está em `src/api/routers/ws.py`. Recomendação (ainda não aplicada porque precisa coordenar com frontend): autenticar via primeira mensagem do WebSocket logo após o handshake, em vez de query param.

### SEC-05 a SEC-07 — Rate-limit, convite, Pydantic
- Criado `src/middleware/rate_limit.py` com fallback in-memory via `cachetools` (sem silenciamento).
- Aplicado em `/auth/login`, `/auth/invite`, `/auth/register`, `/auth/invite/{token}`.
- `RegisterRequest` e `ConviteRequest` agora usam `EmailStr` + `Field(min_length, max_length)`.
- `/auth/register` virou atômico (transação `BEGIN` + `SELECT … FOR UPDATE` no convite) — fecha race de double-use.

### SEC-11 — EMPRESA_ID_PADRAO
- Marcado como DEPRECATED em `config.py`. Mantido temporariamente para não quebrar imports. Remoção completa requer passar por `main.py:2901`, `bot_core.py` e `stream_worker.py`.

### SEC-13 — Audit log
- Criada tabela `audit_log` (append-only via regras PostgreSQL) na migration `audit01_audit_log_and_webhook_secret.py`.
- Helper `src/core/audit_log.py` com função `audit(...)` para uso nos routers.
- **Próximo passo:** chamar `audit(...)` em todos os endpoints de `management.py` que mutam dados.

## Sprint 1 — Arquitetura e Infra

### ARQ-01 — Migrations fora do CMD
- `Dockerfile`: CMD agora só sobe o uvicorn. Não roda `alembic upgrade` mais.
- `scripts/migrate.sh`: script com **Redis distributed lock** (SET NX EX). Roda em job pré-deploy.
- `deploy-prod.yml`, `deploy-staging.yml`, `deploy-dev.yml` chamam `docker compose run --rm api sh scripts/migrate.sh` antes de `up -d`.

### ARQ-02 — Pool Postgres
- `main.py`: pool agora `min=15, max=60` (via env `DB_POOL_MIN`/`DB_POOL_MAX`).
- `docker-compose.prod.yml` seta as envs.
- `src/core/database.py` já estava com config melhor — agora é consistente.

### ARQ-04 — Rate-limit LLM por tenant
- Criado `src/services/llm_quota.py` com caps diário (tokens), mensal (USD) e por minuto (RPM).
- **Próximo passo:** chamar `check_and_reserve_llm_call(empresa_id, ...)` antes de cada `chamar_ia` em `bot_core.py`, e `record_llm_usage(...)` depois. Ponto central provável: `src/services/llm_service.py`.

### ARQ-05 — Idempotência + deadletter
- `src/services/stream_worker.py`:
  - Idempotency key determinística por `(source, empresa_id, phone/conv, msg_id)`.
  - Chave `stream:processed:*` com TTL 24h.
  - Se erro e `delivery_count >= MAX_DELIVERY_COUNT (5)`: move pra stream `ia:webhook:deadletter`.

### ARQ-06 — XAUTOCLAIM + MAXLEN
- `stream_worker`: chama `XAUTOCLAIM` a cada 60s (`min-idle-time=120s`).
- `XTRIM` a cada 100 msgs para manter `MAXLEN=10000`.

### INF-01 — TLS + security headers
- `nginx/prod.conf` reescrito: HTTPS, HSTS, X-Frame, CSP, rate-limit por endpoint, log JSON.
- `docker-compose.prod.yml` mapeia `:443` e monta `./nginx/certs` (você precisa gerar os certs via certbot).

### INF-02 — Backup Postgres
- `scripts/pg_backup.sh`: pg_dump diário para S3/B2 com retenção (30 dias default).
- `scripts/pg_restore.sh`: restore para ambiente de DR.
- **Ação manual:** criar bucket, configurar credenciais AWS CLI no servidor, adicionar cron:
  ```
  0 3 * * * /opt/ia/scripts/pg_backup.sh >> /var/log/ia_backup.log 2>&1
  ```

### INF-03 — Rollback automático
- `.github/workflows/deploy-prod.yml`:
  - Builda com tag do git SHA.
  - Captura imagem anterior antes de subir.
  - Aguarda healthcheck (120s) antes de declarar sucesso.
  - Se falhar: reverte para a imagem anterior.
  - Mantém 3 imagens antigas (não faz mais `prune -f` cego).

### INF-04 — deploy.yml legado
- `.github/workflows/deploy.yml` virou stub deprecated (manual dispatch only).
- Os deploys reais estão em `deploy-dev.yml`, `deploy-staging.yml`, `deploy-prod.yml`.

### INF-06 — Resource limits
- `docker-compose.prod.yml`: `mem_limit` e `cpus` em todos os services.

### INF-07 — Healthcheck workers
- Worker grava `worker:heartbeat` no Redis a cada 30s.
- Healthcheck do container Redis-lendo o heartbeat.

### INF-10 — Sentry
- `src/core/sentry_init.py`: inicialização com scrubber de PII (telefones, emails).
- Depende de `SENTRY_DSN` na env. Se vazio, Sentry fica desabilitado.
- **Próximo passo:** chamar `init_sentry()` no topo de `main.py`, antes de criar o `FastAPI()`.

## Sprint 2 — Qualidade

### QLD-01 / QLD-08 — Venv e `=1.0.0` no git
- `.gitignore` atualizado. **Remoção do tracking precisa ser feita por você** (comandos acima em SEC-01).

### QLD-02 — `except Exception: pass`
- `src/api/routers/auth.py` login: removido o `pass` silencioso.
- Hook de pre-commit em `.pre-commit-config.yaml` bloqueia novos casos.
- **Trabalho contínuo:** rodar `grep -rn "except Exception" src/ main.py` e substituir aos poucos.

### QLD-03 — Testes
- `src/tests/` criado com `conftest.py`, `test_tenant.py`, `test_llm_quota.py`, `test_text_helpers.py`.
- `pyproject.toml` config pytest + coverage.
- `.github/workflows/ci.yml` roda pytest com Postgres + Redis services.

### QLD-04 — Pin de dependências
- `requirements.txt` com upper bounds (`>=X,<Y`).

### QLD-09 — Linters
- `pyproject.toml` com config do `ruff` (inclui bandit/security rules).
- `.pre-commit-config.yaml` com gitleaks e ruff.

### QLD-10 — Structured logging
- Nginx: access log em JSON.
- Backend: próximo passo é substituir `logger.info(f"✅ ...")` por `logger.info("event_name", extra={...})`. Base ja está (loguru suporta isso nativamente).

## Próximos passos (manuais ou dependências externas)

1. **Git cleanup** — rodar os `git rm --cached` em SEC-01.
2. **Certbot/TLS** — gerar cert para `ia.fluxodigitaltech.com.br` e colocar em `nginx/certs/`.
3. **Backup S3** — criar bucket, colocar `BACKUP_S3_BUCKET` + credenciais no servidor, agendar cron.
4. **Sentry DSN** — criar projeto em sentry.io, colocar `SENTRY_DSN` no `.env.production`.
5. **Rodar migration `audit01`** — `scripts/migrate.sh` ou `alembic upgrade head`.
6. **Aplicar `require_tenant` em management.py** — refactor progressivo em cada endpoint.
7. **Chamar `init_sentry()` em main.py** — linha única no topo.
8. **Chamar `llm_quota.check_and_reserve_llm_call` em bot_core.py** — antes de cada LLM call.
9. **`pip install pre-commit && pre-commit install`** — local, para cada dev.

## Arquivos novos

```
src/core/tenant.py
src/core/audit_log.py
src/core/sentry_init.py
src/middleware/__init__.py
src/middleware/rate_limit.py
src/services/llm_quota.py
src/tests/__init__.py
src/tests/conftest.py
src/tests/test_tenant.py
src/tests/test_llm_quota.py
src/tests/test_text_helpers.py
alembic/versions/audit01_audit_log_and_webhook_secret.py
scripts/migrate.sh
scripts/pg_backup.sh
scripts/pg_restore.sh
nginx/prod.conf (reescrito)
pyproject.toml
.pre-commit-config.yaml
.github/workflows/ci.yml
AUDIT_FIXES.md (este arquivo)
```

## Arquivos modificados

```
Dockerfile
docker-compose.prod.yml
.gitignore
requirements.txt
.github/workflows/deploy.yml (deprecated)
.github/workflows/deploy-prod.yml
.github/workflows/deploy-staging.yml
.github/workflows/deploy-dev.yml
main.py (webhook Chatwoot + pool)
src/core/config.py (JWT_SECRET validation, Sentry envs)
src/api/routers/auth.py (rate-limit + register atomico + pydantic Field)
src/api/routers/uaz_webhook.py (hmac.compare_digest + fail-closed)
src/services/stream_worker.py (idempotencia + deadletter + XAUTOCLAIM + trim + heartbeat)
```
