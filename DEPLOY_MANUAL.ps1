# DEPLOY_MANUAL.ps1
# Sincroniza o repo local com o GitHub e mostra comandos para o servidor
# Execute: PowerShell -ExecutionPolicy Bypass -File DEPLOY_MANUAL.ps1

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host " DEPLOY MANUAL - IA Bot" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# === PASSO 1: Atualiza o repositorio local ===
Write-Host ""
Write-Host "[1/2] Atualizando repo local com GitHub..." -ForegroundColor Yellow

$branch = git rev-parse --abbrev-ref HEAD 2>$null
Write-Host "      Branch atual: $branch" -ForegroundColor Gray

git fetch origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERRO: git fetch falhou." -ForegroundColor Red
    exit 1
}

git reset --hard origin/main
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERRO: git reset falhou." -ForegroundColor Red
    exit 1
}

$sha = git rev-parse --short HEAD
Write-Host "      OK — local agora em: $sha" -ForegroundColor Green

# === PASSO 2: Comandos para o servidor de producao ===
Write-Host ""
Write-Host "[2/2] Execute estes comandos NO SERVIDOR de producao:" -ForegroundColor Yellow
Write-Host ""
Write-Host "  # Acesse o servidor via SSH e rode:" -ForegroundColor Gray
Write-Host "  cd /caminho/do/projeto          # ex: cd /opt/ia" -ForegroundColor White
Write-Host "  git fetch origin main" -ForegroundColor White
Write-Host "  git reset --hard origin/main" -ForegroundColor White
Write-Host "  docker compose -f docker-compose.prod.yml build --no-cache api worker" -ForegroundColor White
Write-Host "  docker compose -f docker-compose.prod.yml up -d --force-recreate api worker" -ForegroundColor White
Write-Host "  docker compose -f docker-compose.prod.yml ps" -ForegroundColor White
Write-Host ""
Write-Host "  # Ou pelo Easypanel: clique em 'Redeploy' no servico 'api'" -ForegroundColor Gray
Write-Host ""
Write-Host "  # Apos reiniciar, desbloquear conversas pausadas:" -ForegroundColor Gray
Write-Host "  # Acesse: https://SEU_DOMINIO/webhook/desbloquear-todas/1" -ForegroundColor White
Write-Host "  # (substitua 1 pelo seu empresa_id)" -ForegroundColor Gray
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host " Commits no GitHub (main):" -ForegroundColor Green
Write-Host "   1c1414653ff9 - webhook.py auditoria Meta Cloud API" -ForegroundColor Green
Write-Host "   1fee58060daf - management.py cenarios fix" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
