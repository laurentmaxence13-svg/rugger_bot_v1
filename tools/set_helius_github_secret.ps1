# Run from VS Code PowerShell in the rugger_bot_v1 repository:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\set_helius_github_secret.ps1
#
# Reads ONLY HELIUS_API_KEY from the local .env file, and transfers ONLY this
# value to the named GitHub Actions repository secret. No secret is printed,
# included in process arguments, written to disk, or committed to GitHub.
# Requires GitHub CLI (gh) installed and authenticated with repository rights.

$ErrorActionPreference = 'Stop'
$Repository = 'laurentmaxence13-svg/rugger_bot_v1'
$Root = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $Root '.env'

if (-not (Test-Path -LiteralPath $EnvPath -PathType Leaf)) {
    throw 'Fichier .env introuvable a la racine de rugger_bot_v1.'
}

$matchingLines = @(
    Get-Content -LiteralPath $EnvPath |
        Where-Object { $_ -match '^\s*(?:export\s+)?HELIUS_API_KEY\s*=' }
)
if ($matchingLines.Count -ne 1) {
    throw 'HELIUS_API_KEY doit apparaitre exactement une fois dans .env.'
}

$key = ($matchingLines[0] -replace '^\s*(?:export\s+)?HELIUS_API_KEY\s*=\s*', '').Trim()
if (($key.Length -ge 2) -and
    (($key.StartsWith('"') -and $key.EndsWith('"')) -or
     ($key.StartsWith("'") -and $key.EndsWith("'")))) {
    $key = $key.Substring(1, $key.Length - 2)
}
if ([string]::IsNullOrWhiteSpace($key) -or
    $key -eq 'COLLE_TA_CLE_ICI' -or
    $key -match '^https?://' -or $key -match '^wss?://' -or
    $key -match '\s') {
    throw 'Valeur HELIUS_API_KEY absente, au mauvais format ou remplacée par un URL.'
}

$ghCommand = Get-Command 'gh' -ErrorAction SilentlyContinue
if ($null -eq $ghCommand) {
    throw 'GitHub CLI manquant. Installe gh, puis execute gh auth login.'
}

# Check authentication first. Do not expose the API key in any shell argument.
& $ghCommand.Source auth status 1>$null 2>$null
if ($LASTEXITCODE -ne 0) {
    throw 'GitHub CLI non connecte. Execute gh auth login.'
}

$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName = $ghCommand.Source
$startInfo.Arguments = "secret set HELIUS_API_KEY --repo $Repository"
$startInfo.UseShellExecute = $false
$startInfo.RedirectStandardInput = $true
$startInfo.RedirectStandardOutput = $true
$startInfo.RedirectStandardError = $true
$startInfo.CreateNoWindow = $true
$process = New-Object System.Diagnostics.Process
$process.StartInfo = $startInfo

try {
    if (-not $process.Start()) {
        throw 'Impossible de demarrer GitHub CLI.'
    }
    # No PowerShell pipe (which could append an unwanted newline).
    $process.StandardInput.Write($key)
    $process.StandardInput.Close()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) {
        throw 'Enregistrement refuse par GitHub. Verifie la connexion gh et les droits du depot.'
    }
    Write-Output 'OK : HELIUS_API_KEY a ete enregistree dans les secrets GitHub Actions.'
} finally {
    $key = $null
    $process.Dispose()
}
