$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host ""
Write-Host "DeterminFlow Startup Script"
Write-Host "============================"
Write-Host ""

# Find Python 3.11+
$python = $null
$candidates = @(
    (Join-Path $Root ".venv\Scripts\python.exe"),
    "py",
    "python"
)

foreach ($candidate in $candidates) {
    try {
        if ($candidate -ne "py" -and $candidate -ne "python") {
            if (-not (Test-Path $candidate)) { continue }
        }
        if ($candidate -eq "py") {
            $version = (& py -3.11 --version 2>&1 | Select-String -Pattern "(\d+\.\d+)" -AllMatches).Matches[0].Value
        } else {
            $version = (& $candidate --version 2>&1 | Select-String -Pattern "(\d+\.\d+)" -AllMatches).Matches[0].Value
        }
        if ([version]$version -ge [version]"3.11") {
            $python = $candidate
            break
        }
    } catch {}
}

if (-not $python) {
    Write-Host "ERROR: Python 3.11+ not found" -ForegroundColor Red
    exit 1
}

Write-Host "Using Python: $python" -ForegroundColor Green

# Setup venv
$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    if ($python -eq "py") {
        & py -3.11 -m venv (Join-Path $Root ".venv")
    } else {
        & $python -m venv (Join-Path $Root ".venv")
    }
}

# Install dependencies
Write-Host "Checking dependencies..." -ForegroundColor Cyan
$req = Join-Path $Root "requirements.txt"
if (Test-Path $req) {
    Write-Host "Installing dependencies..." -ForegroundColor Cyan
    & $venvPython -m pip install --quiet --upgrade pip
    & $venvPython -m pip install --quiet -r $req
    Write-Host "Dependencies installed" -ForegroundColor Green
}

# Initialize config
if (-not (Test-Path (Join-Path $Root ".env"))) {
    Copy-Item (Join-Path $Root ".env.example") (Join-Path $Root ".env") -ErrorAction SilentlyContinue
}

$modelCfg = Join-Path $Root "config\models_config.json"
if (-not (Test-Path $modelCfg)) {
    Copy-Item (Join-Path $Root "config\models_config.example.json") $modelCfg -ErrorAction SilentlyContinue
}

# Start service
Write-Host "Starting service..." -ForegroundColor Cyan
$proc = Start-Process -FilePath $venvPython -ArgumentList @("run.py") -WorkingDirectory $Root -PassThru

# Wait for service
$ready = $false
for ($i = 0; $i -lt 180; $i++) {
    Start-Sleep -Seconds 1
    if ($proc.HasExited) {
        Write-Host "ERROR: Service failed to start (exit code $($proc.ExitCode))" -ForegroundColor Red
        exit 1
    }
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8020/docs" -UseBasicParsing -TimeoutSec 2
        $ready = $true
        break
    } catch {}
}

if ($ready) {
    Write-Host "Service ready!" -ForegroundColor Green
    Start-Process "http://127.0.0.1:8020/docs"
} else {
    Write-Host "ERROR: Service did not start in time" -ForegroundColor Red
    exit 1
}
