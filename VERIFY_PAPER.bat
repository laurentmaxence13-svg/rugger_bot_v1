@echo off
setlocal
if exist ".venv\Scripts\python.exe" (
  set "PYTHON=.venv\Scripts\python.exe"
) else (
  set "PYTHON=python"
)
echo Verification syntaxe...
%PYTHON% -m compileall -q bot tests
if errorlevel 1 goto :failed
echo Verification tests...
%PYTHON% -m unittest discover -s tests -v
if errorlevel 1 goto :failed
echo.
echo OK : code compile et tests PAPER passes.
pause
exit /b 0
:failed
echo.
echo ECHEC : corrige l'installation avant de lancer le moteur.
pause
exit /b 1
