@echo off
echo === Deploy: fix pausa IA + horario aberto/fechado ===
echo.
del /f ".git\index.lock" 2>nul
git add main.py
git diff --cached --stat
echo.
git commit -m "fix: pausa IA funciona para qualquer outgoing nao-IA + status aberto/fechado tempo real"
git push origin main
echo.
echo === PRONTO! Agora faz build no Easypanel ===
pause
