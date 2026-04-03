@echo off
echo === Corrigindo deploy ===
del /f ".git\index.lock" 2>nul

echo === Salvando main.py modificado ===
copy /Y main.py main_backup.py

echo === Voltando para estado original (antes dos commits ruins) ===
git reset --hard HEAD~2

echo === Restaurando main.py com as correcoes ===
copy /Y main_backup.py main.py
del main_backup.py

echo === Adicionando apenas main.py ===
git add main.py

echo === Verificando diff ===
git diff --cached --stat

echo === Commitando ===
git commit -m "fix: fluxo triagem respeita horario + IA nunca e bloqueada por schedule"

echo === Force push ===
git push --force origin main

echo === PRONTO! ===
pause
