@echo off
setlocal
if exist ".venv\Scripts\python.exe" (
  set "PYTHON=.venv\Scripts\python.exe"
) else (
  set "PYTHON=python"
)
echo PAPER DIAGNOSTIC : ENTRY/EXIT fictifs uniquement
%PYTHON% -m bot.analyser.paper_engine --poll 15 --max-age 7200 --min-liquidity 1000 --shadow-baseline --report data\shadow_paper_report.json
echo.
echo Shadow paper arrete. Appuie sur une touche pour fermer.
pause >nul
