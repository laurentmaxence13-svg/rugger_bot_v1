@echo off
setlocal
cd /d "%~dp0"
echo.
echo =========================================
echo  RUGGER BOT - TERMINAL PAPER (LECTURE SEULE)
echo =========================================
echo.
if not exist ".venv\Scripts\python.exe" (
  echo Creation du Python virtuel .venv...
  py -3 -m venv .venv
  if errorlevel 1 (
    echo ERREUR : Python 3 est requis. Installer Python et cocher Add Python to PATH.
    pause
    exit /b 1
  )
)
set "PY=.venv\Scripts\python.exe"
echo Verification des dependances du terminal...
"%PY%" -m pip install -r requirements-dashboard.txt
if errorlevel 1 (
  echo ERREUR : installation de Streamlit impossible. Verifier la connexion Internet.
  pause
  exit /b 1
)
echo.
echo Ouvrir dans le navigateur : http://localhost:8501
echo Le terminal ne peut PAS effectuer d'ordres reels.
echo CTRL+C pour arreter.
"%PY%" -m streamlit run bot/dashboard/app.py --server.address 127.0.0.1 --server.port 8501
endlocal
