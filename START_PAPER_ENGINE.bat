@echo off
setlocal
if exist ".venv\Scripts\python.exe" (
  set "PYTHON=.venv\Scripts\python.exe"
) else (
  set "PYTHON=python"
)
%PYTHON% -m bot.analyser.paper_engine --poll 15 --max-age 7200 --min-liquidity 1000 --report data\paper_engine_report.json
echo.
echo Paper engine arrete. Appuie sur une touche pour fermer.
pause >nul
