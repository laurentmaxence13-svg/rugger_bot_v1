@echo off
setlocal EnableExtensions
title RUGGER BOT - TERMINAL PAPER
pushd "%~dp0"
if errorlevel 1 (
  echo ERREUR : dossier de projet non accessible.
  pause
  exit /b 1
)

if not exist "bot\dashboard\app.py" (
  echo ERREUR : application introuvable.
  echo Extraire entierement le ZIP dans un dossier Windows, ne pas lancer depuis l'archive.
  pause
  exit /b 1
)
if not exist "LANCER_TERMINAL_PAPER.ps1" (
  echo ERREUR : lanceur de diagnostic absent.
  echo Telecharger la derniere version complete depuis GitHub, branche main.
  pause
  exit /b 1
)

where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo ERREUR : PowerShell indisponible. Installer Windows PowerShell 5.1 ou plus.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0LANCER_TERMINAL_PAPER.ps1"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo.
  echo ECHEC DU LANCEMENT : lire le message d'erreur ci-dessus.
  echo Envoie une capture de cette fenetre et, si present, du fichier terminal_paper_serveur_stderr.log.
  echo Le navigateur seul ne permet pas d'identifier la cause.
  pause
)
popd
endlocal & exit /b %RESULT%
