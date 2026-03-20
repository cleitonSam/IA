#!/bin/bash
# Script para sincronizar e enviar alterações para ambos os repositórios (Raiz e /IA)

echo "🔄 Sincronizando arquivos entre Raiz e pasta /IA..."

# Lista de arquivos críticos para sincronizar
files=("main.py" "src/services/bot_core.py" "src/utils/time_helpers.py" "src/services/db_queries.py" "src/api/routers/management.py")

for f in "${files[@]}"; do
    if [ -f "$f" ]; then
        cp "$f" "IA/$f"
        echo "✅ Copiado: $f -> IA/$f"
    fi
done

echo "📤 Enviando alterações para o repositório Raiz..."
git add .
git commit -m "chore: automatic sync and deploy"
git push origin main

echo "📤 Enviando alterações para o repositório /IA..."
cd IA
git add .
git commit -m "chore: automatic sync and deploy"
git push origin main

echo "🚀 Pronto! Se o GitHub Actions estiver configurado, o deploy começará em instantes."
