@echo off
echo === Deploy: fix horario aberto/fechado em tempo real ===
echo.
echo Removendo index.lock...
del /f ".git\index.lock" 2>nul

echo Adicionando arquivos...
git add main.py
git add deploy_horario.bat

echo.
echo === Verificando diff ===
git diff --cached --stat

echo.
echo === Commitando ===
git commit -m "fix: IA verifica status aberto/fechado em tempo real antes de responder horario"

echo.
echo === Push para GitHub ===
git push origin main

echo.
echo === PRONTO! Agora faz o build no Easypanel ===
pause
