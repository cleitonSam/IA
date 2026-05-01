# SETUP_GITHUB_SECRETS.ps1
# Configura os 4 secrets do GitHub Actions para o deploy automatico funcionar
# Execute: PowerShell -ExecutionPolicy Bypass -File SETUP_GITHUB_SECRETS.ps1
#
# Preencha as 4 variaveis abaixo antes de executar:

$SSH_HOST = ""        # IP ou hostname do servidor (ex: 123.45.67.89)
$SSH_USER = ""        # Usuario SSH (ex: root ou ubuntu)
$SSH_KEY  = ""        # Conteudo completo da chave privada SSH (incluindo -----BEGIN...-----)
$PROD_PATH = ""       # Caminho do projeto no servidor (ex: /opt/ia ou /home/ubuntu/IA)

# ===================== NAO EDITAR ABAIXO =====================

$TOKEN = "SEU_GITHUB_TOKEN_AQUI"
$REPO  = "cleitonSam/IA"

if (-not $SSH_HOST -or -not $SSH_USER -or -not $SSH_KEY -or -not $PROD_PATH) {
    Write-Host "ERRO: Preencha SSH_HOST, SSH_USER, SSH_KEY e PROD_PATH antes de executar!" -ForegroundColor Red
    exit 1
}

Write-Host "Configurando secrets do GitHub Actions..." -ForegroundColor Cyan

# Busca public key do repositorio para criptografar os secrets
$keyResp = Invoke-RestMethod -Uri "https://api.github.com/repos/$REPO/actions/secrets/public-key" `
    -Headers @{ Authorization = "token $TOKEN"; "User-Agent" = "PS-Setup" }

$keyId  = $keyResp.key_id
$pubKey = $keyResp.key

Write-Host "Public key obtida: $($pubKey.Substring(0,20))..." -ForegroundColor Gray

# Funcao: criptografa valor usando libsodium (via Python + PyNaCl)
function Encrypt-Secret($pubKeyB64, $value) {
    $script = @"
import base64, sys
from nacl import encoding, public

pk_bytes = base64.b64decode('$pubKeyB64')
pk = public.PublicKey(pk_bytes)
box = public.SealedBox(pk)
enc = box.encrypt(sys.argv[1].encode('utf-8'))
print(base64.b64encode(enc).decode())
"@
    return (python3 -c $script $value)
}

$secrets = @{
    "SSH_HOST"  = $SSH_HOST
    "SSH_USER"  = $SSH_USER
    "SSH_KEY"   = $SSH_KEY
    "PROD_PATH" = $PROD_PATH
}

foreach ($name in $secrets.Keys) {
    Write-Host "  Enviando $name..." -ForegroundColor Yellow
    $enc = Encrypt-Secret $pubKey $secrets[$name]
    $body = @{ encrypted_value = $enc; key_id = $keyId } | ConvertTo-Json
    $resp = Invoke-RestMethod -Method Put `
        -Uri "https://api.github.com/repos/$REPO/actions/secrets/$name" `
        -Headers @{ Authorization = "token $TOKEN"; "User-Agent" = "PS-Setup" } `
        -Body $body -ContentType "application/json"
    Write-Host "    OK" -ForegroundColor Green
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host " Secrets configurados! Proximo push no main" -ForegroundColor Green
Write-Host " vai disparar o deploy automatico." -ForegroundColor Green
Write-Host " https://github.com/$REPO/actions" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
