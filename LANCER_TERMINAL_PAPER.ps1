param(
    [switch]$SmokeTest
)

# Read-only PAPER dashboard: no wallet connection and no real orders.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root
$address = '127.0.0.1'
$port = 8501
$url = 'http://127.0.0.1:8501'
$stdout = Join-Path $root 'terminal_paper_serveur_stdout.log'
$stderr = Join-Path $root 'terminal_paper_serveur_stderr.log'
$venv = Join-Path $root '.venv-dashboard'
$pythonVenv = Join-Path $venv 'Scripts\python.exe'
$server = $null

function Health-OK {
    try {
        $reply = Invoke-WebRequest -Uri "$url/_stcore/health" -UseBasicParsing -TimeoutSec 2
        return ($reply.StatusCode -eq 200 -and $reply.Content.Trim() -eq 'ok')
    } catch {
        return $false
    }
}

function Show-Diagnostics {
    Write-Host ''
    Write-Host '[DIAGNOSTIC] Impossible de demarrer le serveur Rugger Bot.' -ForegroundColor Red
    Write-Host 'Journaux :'
    Write-Host "  $stdout"
    Write-Host "  $stderr"
    foreach ($file in @($stderr, $stdout)) {
        if (Test-Path -LiteralPath $file) {
            Write-Host "---- $(Split-Path -Leaf $file) ----"
            Get-Content -LiteralPath $file -Tail 35
        }
    }
    Write-Host 'Copie le message ERREUR ou envoie une capture de cette fenetre.'
}

function Find-Python {
    # Prefer mainstream versions with stable Streamlit wheels on Windows.
    $candidates = @(
        @{ Command = 'py'; Params = @('-3.12') },
        @{ Command = 'py'; Params = @('-3.11') },
        @{ Command = 'py'; Params = @('-3.13') },
        @{ Command = 'py'; Params = @('-3') },
        @{ Command = 'python'; Params = @() }
    )
    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Command -ErrorAction SilentlyContinue)) { continue }
        $prefix = $candidate.Params
        try {
            $version = & $candidate.Command @prefix -c 'import sys; print(sys.version_info.major, sys.version_info.minor)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $version -match '^3 (11|12|13|14)$') { return $candidate }
        } catch { }
    }
    return $null
}

Write-Host '============================================' -ForegroundColor Cyan
Write-Host ' RUGGER BOT | TERMINAL PAPER - WINDOWS'
Write-Host '============================================' -ForegroundColor Cyan
Write-Host "Dossier : $root"
Write-Host 'Aucun ordre reel ni connexion wallet.'

if (-not (Test-Path -LiteralPath (Join-Path $root 'bot\dashboard\app.py'))) {
    throw 'Projet incomplet : decompresse entierement le ZIP GitHub, puis relance le .bat depuis le dossier du bot.'
}

if (-not $SmokeTest -and (Health-OK)) {
    Write-Host "Un serveur Streamlit repond deja sur $url" -ForegroundColor Green
    Start-Process $url
    return
}

$python = Find-Python
if ($null -eq $python) {
    throw 'Python 3.11, 3.12 ou 3.13 non detecte. Installer Python depuis python.org puis relancer le .bat.'
}

if (Test-Path -LiteralPath $pythonVenv) {
    try {
        & $pythonVenv -c 'import sys; assert sys.version_info.major == 3' 2>$null
        if ($LASTEXITCODE -ne 0) { throw 'Python inactif' }
    } catch {
        throw 'Environnement .venv-dashboard endommage. Renomme ce dossier en .venv-dashboard-old et relance.'
    }
} else {
    Write-Host 'Initialisation du Python dedie au terminal...'
    $prefix = $python.Params
    & $python.Command @prefix -m venv $venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $pythonVenv)) {
        throw 'Echec de creation du Python virtuel. Verifie que Python est installe avec le module venv.'
    }
}

Write-Host 'Verification des dependances Streamlit...'
& $pythonVenv -c 'import streamlit; import pandas; print("Streamlit", streamlit.__version__)' 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Installation des dependances (premier lancement uniquement)...'
    & $pythonVenv -m pip install --disable-pip-version-check -r (Join-Path $root 'requirements-dashboard.txt')
    if ($LASTEXITCODE -ne 0) {
        throw 'Installation Streamlit impossible. Verifie la connexion Internet et copie l erreur pip visible ci-dessus.'
    }
}

Write-Host "Demarrage de Rugger Bot a $url ..."
try {
    $params = @('-m','streamlit','run','bot/dashboard/app.py',"--server.address=$address","--server.port=$port",'--server.headless=true','--browser.gatherUsageStats=false','--server.fileWatcherType=none')
    $server = Start-Process -FilePath $pythonVenv -WorkingDirectory $root -ArgumentList $params -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        if (Health-OK) { $ready = $true; break }
        $server.Refresh()
        if ($server.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) {
        Show-Diagnostics
        throw 'Le serveur local ne repond pas sur le port 8501.'
    }
    Write-Host ''
    Write-Host "[OK] TERMINAL OPERATIONNEL : $url" -ForegroundColor Green
    if (-not $SmokeTest) {
        Start-Process $url
        Write-Host 'Ton navigateur doit afficher RUGGER BOT - TERMINAL PAPER.'
        Write-Host 'Garde cette fenetre ouverte pour garder le terminal actif.'
        Write-Host 'Ferme-la pour arreter le serveur et liberer le port.'
        Wait-Process -Id $server.Id
        Write-Host 'Le serveur a ete arrete.'
    }
} finally {
    if ($null -ne $server) {
        try {
            $server.Refresh()
            if (-not $server.HasExited) {
                Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
            }
        } catch { }
    }
}
