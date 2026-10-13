$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "DeterminFlow Universal Launcher" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# [1/6] Environment Check
Write-Host "[1/6] Environment Check..." -ForegroundColor Yellow
$checkScript = Join-Path $Root "scripts\check_environment.py"
if (Test-Path $checkScript) {
    try {
        $pythonCmds = @("python", "python3", "py -3.11", "py")
        $pythonFound = $false
        foreach ($cmd in $pythonCmds) {
            try {
                $cmdParts = $cmd -split ' '
                if ($cmdParts.Length -eq 1) {
                    & $cmdParts[0] $checkScript
                } else {
                    & $cmdParts[0] $cmdParts[1] $checkScript
                }
                $pythonFound = $true
                break
            } catch {
                continue
            }
        }
        if (-not $pythonFound) {
            Write-Host "WARNING: Cannot run environment check (Python not found), continuing..." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "WARNING: Environment check failed, continuing..." -ForegroundColor Yellow
    }
} else {
    Write-Host "WARNING: Environment check script not found, skipping..." -ForegroundColor Yellow
}
Write-Host ""

# [2/6] Find Python 3.11+
Write-Host "[2/6] Finding Python 3.11+..." -ForegroundColor Yellow
$python = $null
$candidates = @(
    (Join-Path $Root ".venv\Scripts\python.exe"),
    "py -3.11",
    "py -3",
    "py",
    "python",
    "python3"
)

foreach ($candidate in $candidates) {
    try {
        $cmdParts = $candidate -split ' '
        $testCmd = if ($cmdParts.Length -eq 1) { $cmdParts[0] } else { $cmdParts[0] }

        if ($testCmd -like "*python.exe" -and -not (Test-Path $testCmd)) {
            continue
        }

        $versionOutput = if ($cmdParts.Length -eq 1) {
            & $cmdParts[0] --version 2>&1
        } else {
            & $cmdParts[0] $cmdParts[1] --version 2>&1
        }

        $versionString = $versionOutput | Out-String
        if ($versionString -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 11) {
                $python = $candidate
                Write-Host "Found Python $major.$minor" -ForegroundColor Green
                break
            }
        }
    } catch {
        continue
    }
}

if (-not $python) {
    Write-Host "ERROR: Python 3.11+ not found" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please install Python 3.11 or higher:" -ForegroundColor Yellow
    Write-Host "  https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "After installation, add Python to PATH or use py launcher" -ForegroundColor Yellow
    pause
    exit 1
}
Write-Host ""

# [3/6] Setup Virtual Environment
Write-Host "[3/6] Setting up virtual environment..." -ForegroundColor Yellow
$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    try {
        $cmdParts = $python -split ' '
        if ($cmdParts.Length -eq 1) {
            & $cmdParts[0] -m venv (Join-Path $Root ".venv")
        } else {
            & $cmdParts[0] $cmdParts[1] -m venv (Join-Path $Root ".venv")
        }
        Write-Host "Virtual environment created successfully" -ForegroundColor Green
    } catch {
        Write-Host "ERROR: Failed to create virtual environment: $_" -ForegroundColor Red
        pause
        exit 1
    }
} else {
    Write-Host "Virtual environment already exists" -ForegroundColor Green
}
Write-Host ""

# [4/6] Install Python Dependencies
Write-Host "[4/6] Installing Python dependencies..." -ForegroundColor Yellow
$req = Join-Path $Root "requirements.txt"
if (Test-Path $req) {
    try {
        Write-Host "Upgrading pip..." -ForegroundColor Cyan
        & $venvPython -m pip install --quiet --upgrade pip setuptools wheel 2>&1 | Out-Null

        Write-Host "Installing packages (first run may take a few minutes)..." -ForegroundColor Cyan
        & $venvPython -m pip install --quiet -r $req

        if ($LASTEXITCODE -eq 0) {
            Write-Host "Python dependencies installed successfully" -ForegroundColor Green
        } else {
            Write-Host "WARNING: Some dependencies failed to install, but continuing..." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "WARNING: Error during dependency installation: $_" -ForegroundColor Yellow
        Write-Host "   Service may not start properly" -ForegroundColor Yellow
    }
} else {
    Write-Host "WARNING: requirements.txt not found, skipping dependency installation" -ForegroundColor Yellow
}
Write-Host ""

# [5/6] Initialize Configuration
Write-Host "[5/6] Initializing configuration..." -ForegroundColor Yellow
$envFile = Join-Path $Root ".env"
$envExample = Join-Path $Root ".env.example"
if (-not (Test-Path $envFile)) {
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile -ErrorAction SilentlyContinue
        Write-Host "Created .env from .env.example" -ForegroundColor Green
    } else {
        Write-Host "WARNING: .env.example not found, skipping" -ForegroundColor Yellow
    }
} else {
    Write-Host ".env already exists" -ForegroundColor Green
}

$modelCfg = Join-Path $Root "config\models_config.json"
$modelCfgExample = Join-Path $Root "config\models_config.example.json"
if (-not (Test-Path $modelCfg)) {
    if (Test-Path $modelCfgExample) {
        $configDir = Join-Path $Root "config"
        if (-not (Test-Path $configDir)) {
            New-Item -ItemType Directory -Path $configDir -Force | Out-Null
        }
        Copy-Item $modelCfgExample $modelCfg -ErrorAction SilentlyContinue
        Write-Host "Created model config from example" -ForegroundColor Green
    } else {
        Write-Host "WARNING: models_config.example.json not found, skipping" -ForegroundColor Yellow
    }
} else {
    Write-Host "Model config already exists" -ForegroundColor Green
}
Write-Host ""

# [6/6] Start Service
Write-Host "[6/6] Starting service..." -ForegroundColor Yellow
Write-Host ""

# Show Humanware Engine banner
$humanwareBannerScript = Join-Path $Root "scripts\humanware_banner.ps1"
if (Test-Path $humanwareBannerScript) {
    try {
        . $humanwareBannerScript
        Show-HumanwareBanner -RootPath $Root
    } catch {
        # Silent continue if banner script fails
    }
}

$logDir = Join-Path $Root "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logDir "startup_$timestamp.log"

Write-Host "Starting DeterminFlow..." -ForegroundColor Cyan
Write-Host "Log file: $logFile" -ForegroundColor Gray
Write-Host ""

$proc = Start-Process -FilePath $venvPython -ArgumentList @("run.py") -WorkingDirectory $Root -NoNewWindow -PassThru

Write-Host "Waiting for service to start..." -ForegroundColor Cyan
$ready = $false
$maxWait = 180
for ($i = 0; $i -lt $maxWait; $i++) {
    Start-Sleep -Seconds 1

    if ($proc.HasExited) {
        Write-Host ""
        Write-Host "ERROR: Service failed to start (exit code: $($proc.ExitCode))" -ForegroundColor Red
        Write-Host ""
        Write-Host "Troubleshooting:" -ForegroundColor Yellow
        Write-Host "  1. Check the error messages above" -ForegroundColor Yellow
        Write-Host "  2. Run manually: .\.venv\Scripts\python.exe run.py" -ForegroundColor Yellow
        Write-Host "  3. Check if port 8020 is in use" -ForegroundColor Yellow
        Write-Host "  4. See documentation: STARTUP_TROUBLESHOOTING.md" -ForegroundColor Yellow
        Write-Host ""
        pause
        exit 1
    }

    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:8020/docs" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch {
        # Continue waiting
    }

    if ($i -gt 0 -and $i % 10 -eq 0) {
        Write-Host "  Waiting... ($i/$maxWait seconds)" -ForegroundColor Gray
    }
}

Write-Host ""
if ($ready) {
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "DeterminFlow Started Successfully!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Web Interface:  http://localhost:8020/" -ForegroundColor Cyan
    Write-Host "API Docs:       http://localhost:8020/docs" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Press Ctrl+C to stop the service" -ForegroundColor Yellow
    Write-Host ""

    # Open browser with cache-busting parameter
    $timestamp = [DateTimeOffset]::Now.ToUnixTimeSeconds()
    $url = "http://127.0.0.1:8020/?_t=$timestamp"

    try {
        Start-Process $url
        Write-Host "Browser opened with cache refresh" -ForegroundColor Green
    } catch {
        Write-Host "Please open the URL above in your browser" -ForegroundColor Yellow
    }

    try {
        $proc.WaitForExit()
    } catch {
        Write-Host "Service stopped" -ForegroundColor Yellow
    }
} else {
    Write-Host "ERROR: Service startup timeout (waited more than $maxWait seconds)" -ForegroundColor Red
    Write-Host ""
    Write-Host "Possible causes:" -ForegroundColor Yellow
    Write-Host "  1. Frontend build taking too long (Node.js dependency installation)" -ForegroundColor Yellow
    Write-Host "  2. Server responding slowly" -ForegroundColor Yellow
    Write-Host "  3. Port is in use" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Suggestion:" -ForegroundColor Yellow
    Write-Host "  Check if the process is still running, service may have started" -ForegroundColor Yellow
    Write-Host "  Try accessing: http://localhost:8020/" -ForegroundColor Yellow
    Write-Host ""

    $response = Read-Host "Terminate process? (y/N)"
    if ($response -eq "y" -or $response -eq "Y") {
        Stop-Process -Id $proc.Id -Force
        Write-Host "Process terminated" -ForegroundColor Yellow
    } else {
        Write-Host "Process continues running" -ForegroundColor Green
    }

    exit 1
}
