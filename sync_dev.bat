@echo off
echo === Sincronizando dev com main ===
echo.
del /f ".git\index.lock" 2>nul

echo 1. Commitando alteracoes pendentes na main...
git add main.py
git commit -m "fix: pausa IA qualquer outgoing + status aberto/fechado tempo real + aviso_mudanca" 2>nul

echo.
echo 2. Push main...
git push origin main

echo.
echo 3. Atualizando dev com tudo da main...
git fetch origin
git checkout dev
git merge origin/main --no-edit
git push origin dev

echo.
echo 4. Voltando pra main...
git checkout main

echo.
echo === PRONTO! dev esta sincronizada com main ===
echo Agora faz o build no Easypanel apontando para dev
pause
