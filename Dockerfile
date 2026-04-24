# Imagem base Python slim estavel
FROM python:3.11-slim AS runtime

# Evita .pyc, log em tempo real, desabilita hash randomizer para builds reproduziveis
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Label de versao (atualizado pelo CI)
ARG GIT_SHA=unknown
ARG BUILD_DATE=unknown
LABEL org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.source="https://github.com/fluxodigital/ia" \
      build_version="${BUILD_DATE}"

WORKDIR /app

# [INF-14] Dependencias de sistema minimas. curl e necessario para healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Instala dependencias Python antes do codigo para aproveitar cache de layer
COPY requirements.txt .
RUN pip install -r requirements.txt

# Cache bust: hash do git SHA garante que este passo NAO usa cache quando o codigo muda
ARG GIT_SHA=unknown
RUN echo "cache_bust_${GIT_SHA}" > /tmp/cachebust

# Copia codigo da aplicacao
COPY . .

# [INF-14] Usuario nao-root para reduzir blast radius de escape de container
RUN groupadd -r appgrp --gid 1000 \
 && useradd -r -g appgrp --uid 1000 -m -d /home/appuser appuser \
 && chown -R appuser:appgrp /app
USER appuser

EXPOSE 8000

# [INF-07] Healthcheck interno do container (pode ser sobrescrito no compose)
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -fsS "http://localhost:${PORT:-8000}/health" || exit 1

# [ARQ-01] Migrations NAO rodam mais no CMD.
# Use um init container / job pre-deploy para rodar:
#   docker compose run --rm api python -m alembic upgrade head
# ou execute o script scripts/migrate.sh com Redis lock.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${UVICORN_WORKERS:-4}"]
