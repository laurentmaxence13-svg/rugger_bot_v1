$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.\.venv\Scripts\python.exe')) {
    Write-Host 'Environnement .venv absent : lance depuis ton dossier rugger_bot_v1 existant.'
    exit 1
}
$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $py -m pip install -r '.\requirements.txt' certifi
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$env:SSL_CERT_FILE = (& $py -c 'import certifi; print(certifi.where())').Trim()
$env:REQUESTS_CA_BUNDLE = $env:SSL_CERT_FILE
& $py -m unittest tests.test_launchlab_onchain tests.test_launchlab_parser tests.test_paper_pipeline tests.test_research_rpc tests.test_mint_audit tests.test_paper_session tests.test_calibration_v2 tests.test_paper_end_to_end -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py -m bot.analyser.paper_engine --shadow-final --session-seconds 7200 --session-report ".\data\paper_session_report.json"
