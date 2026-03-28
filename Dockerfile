# Use uma imagem Python leve e estável
FROM python:3.11-slim

# Evita que o Python gere arquivos .pyc e permite logs em tempo real
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Cache bust: 20260328-1230
LABEL build_version="20260328-1230"

# Define o diretório de trabalho
WORKDIR /app

# Instala dependências do sistema necessárias para algumas libs (se houver)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copia e instala as dependências do Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o restante do código da aplicação
COPY . .

# Expõe a porta que o FastAPI usará (opcional, documentativo)
EXPOSE 8000

# Comando padrão (pode ser sobrescrito pelo Easypanel)
# Usando sh -c para permitir expansão da variável de ambiente PORT
CMD ["sh", "-c", "alembic upgrade head; uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
