# ═══════════════════════════════════════════════════════
#  Motor SaaS IA — Comandos por Ambiente
#  Uso: make <comando>  (ex: make dev-up, make staging-logs)
# ═══════════════════════════════════════════════════════

.PHONY: help \
        dev-up dev-down dev-build dev-logs dev-ps dev-restart \
        staging-up staging-down staging-build staging-logs staging-ps staging-restart \
        prod-up prod-down prod-build prod-logs prod-ps prod-restart \
        migrate-dev migrate-staging migrate-prod \
        setup-dev setup-staging setup-prod

# ── Ajuda ──────────────────────────────────────────────
help:
	@echo ""
	@echo "  Motor SaaS IA — Comandos Disponíveis"
	@echo "  ═══════════════════════════════════════"
	@echo ""
	@echo "  DEV (porta 8081):"
	@echo "    make dev-up          Sobe todos os serviços dev"
	@echo "    make dev-down        Para todos os serviços dev"
	@echo "    make dev-build       Rebuild sem cache"
	@echo "    make dev-logs        Logs em tempo real"
	@echo "    make dev-restart     Reinicia sem rebuild"
	@echo "    make dev-ps          Status dos containers dev"
	@echo "    make migrate-dev     Roda alembic upgrade head (dev)"
	@echo ""
	@echo "  STAGING (porta 8082):"
	@echo "    make staging-up      Sobe todos os serviços staging"
	@echo "    make staging-down    Para todos os serviços staging"
	@echo "    make staging-build   Rebuild sem cache"
	@echo "    make staging-logs    Logs em tempo real"
	@echo "    make staging-restart Reinicia sem rebuild"
	@echo "    make staging-ps      Status dos containers staging"
	@echo "    make migrate-staging Roda alembic upgrade head (staging)"
	@echo ""
	@echo "  PROD (porta 80):"
	@echo "    make prod-up         Sobe todos os serviços prod"
	@echo "    make prod-down       Para todos os serviços prod"
	@echo "    make prod-build      Rebuild sem cache"
	@echo "    make prod-logs       Logs em tempo real"
	@echo "    make prod-ps         Status dos containers prod"
	@echo "    make migrate-prod    Roda alembic upgrade head (prod)"
	@echo ""
	@echo "  SETUP (primeira vez):"
	@echo "    make setup-dev       Copia .env.dev.example → .env.dev"
	@echo "    make setup-staging   Copia .env.staging.example → .env.staging"
	@echo "    make setup-prod      Copia .env.production.example → .env.production"
	@echo ""

# ── DEV ────────────────────────────────────────────────
dev-up:
	docker compose -f docker-compose.dev.yml up -d

dev-down:
	docker compose -f docker-compose.dev.yml down

dev-build:
	docker compose -f docker-compose.dev.yml up --build --force-recreate -d

dev-logs:
	docker compose -f docker-compose.dev.yml logs -f --tail=100

dev-ps:
	docker compose -f docker-compose.dev.yml ps

dev-restart:
	docker compose -f docker-compose.dev.yml restart

migrate-dev:
	docker exec ia-dev-api alembic upgrade head

# ── STAGING ────────────────────────────────────────────
staging-up:
	docker compose -f docker-compose.staging.yml up -d

staging-down:
	docker compose -f docker-compose.staging.yml down

staging-build:
	docker compose -f docker-compose.staging.yml up --build --force-recreate -d

staging-logs:
	docker compose -f docker-compose.staging.yml logs -f --tail=100

staging-ps:
	docker compose -f docker-compose.staging.yml ps

staging-restart:
	docker compose -f docker-compose.staging.yml restart

migrate-staging:
	docker exec ia-staging-api alembic upgrade head

# ── PROD ───────────────────────────────────────────────
prod-up:
	docker compose -f docker-compose.prod.yml up -d

prod-down:
	docker compose -f docker-compose.prod.yml down

prod-build:
	docker compose -f docker-compose.prod.yml up --build --force-recreate -d

prod-logs:
	docker compose -f docker-compose.prod.yml logs -f --tail=100

prod-ps:
	docker compose -f docker-compose.prod.yml ps

prod-restart:
	docker compose -f docker-compose.prod.yml restart

migrate-prod:
	docker exec ia-prod-api alembic upgrade head

# ── SETUP (primeira vez) ───────────────────────────────
setup-dev:
	@if [ ! -f .env.dev ]; then \
		cp .env.dev.example .env.dev; \
		echo "✅  .env.dev criado — edite com suas credenciais"; \
	else \
		echo "⚠️   .env.dev já existe, não sobrescrito"; \
	fi

setup-staging:
	@if [ ! -f .env.staging ]; then \
		cp .env.staging.example .env.staging; \
		echo "✅  .env.staging criado — edite com suas credenciais"; \
	else \
		echo "⚠️   .env.staging já existe, não sobrescrito"; \
	fi

setup-prod:
	@if [ ! -f .env.production ]; then \
		cp .env.production.example .env.production; \
		echo "✅  .env.production criado — edite com suas credenciais"; \
	else \
		echo "⚠️   .env.production já existe, não sobrescrito"; \
	fi
