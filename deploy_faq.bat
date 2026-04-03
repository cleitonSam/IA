@echo off
echo === Removendo index.lock ===
del /f ".git\index.lock" 2>nul
echo === Adicionando main.py ===
git add main.py
echo === Diff ===
git diff --cached --stat
echo === Commitando ===
git commit -m "fix: FAQ Neural sempre consultado - inclui global e empresas sem unidade"
echo === Push ===
git push origin main
echo === PRONTO! ===
pause
