$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$Url = "http://127.0.0.1:8020/docs"

function Write-Info([string]$Message) {
    Write-Host "[DeterminFlow] $Message" -ForegroundColor Cyan
}

function Test-Service([string]$Address) {
    try {
        $response = Invoke-WebRequest -Uri $Address -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    } catch {
        return $false
    }
}

if (Test-Service $Url) {
    Write-Info "The service is already running; opening the browser."
    Start-Process $Url
    exit 0
}

function Get-PythonCommand {
    $candidates = @(
        @{ File = (Join-Path $Root ".venv\Scripts\python.exe"); Kind = "path" },
        @{ File = "py"; Kind = "launcher" },
        @{ File = "python"; Kind = "path" }
    )

    foreach ($candidate in $candidates) {
        try {
            if ($candidate.Kind -eq "path" -and $candidate.File -ne "python" -and -not (Test-Path $candidate.File)) {
                continue
            }
            if ($candidate.File -eq "py") {
                $versionText = (& py -3.11 -c "import sys; print(str(sys.version_info.major) + '.' + str(sys.version_info.minor))" 2>$null | Select-Object -Last 1)
            } else {
                $versionText = (& $candidate.File -c "import sys; print(str(sys.version_info.major) + '.' + str(sys.version_info.minor))" 2>$null | Select-Object -Last 1)
            }
            if ($versionText -match '^([0-9]+)\.([0-9]+)$') {
                $version = [version]("{0}.{1}" -f $Matches[1], $Matches[2])
                if ($version -ge [version]"3.11") {
                    return $candidate
                }
            }
        } catch {
            continue
        }
    }
    return $null
}

$python = Get-PythonCommand
if ($null -eq $python) {
    Write-Host "Python 3.11 or newer was not found." -ForegroundColor Red
    Write-Host "Install Python 3.11+ and run this launcher again."
    Write-Host "For a ready-to-run build, open: https://github.com/alikon-art/DeterminFlow/releases/latest"
    Read-Host "Press Enter to exit"
    exit 1
}

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Info "Creating the Python virtual environment."
    if ($python.File -eq "py") {
        & py -3.11 -m venv (Join-Path $Root ".venv")
    } else {
        & $python.File -m venv (Join-Path $Root ".venv")
    }
}

if (-not (Test-Path $venvPython)) {
    throw "Virtual environment creation failed: $venvPython"
}

$dependencyMarker = Join-Path $Root ".venv\.determinflow-dependencies-ready"
$requirements = Join-Path $Root "requirements.lock"
if (-not (Test-Path $dependencyMarker) -or (Get-Item $requirements).LastWriteTimeUtc -gt (Get-Item $dependencyMarker).LastWriteTimeUtc) {
    Write-Info "Installing Python dependencies; the first run can take a few minutes."
    & $venvPython -m pip install -r $requirements
    Set-Content -Path $dependencyMarker -Value (Get-Date).ToUniversalTime().ToString("o") -Encoding UTF8
}

if (-not (Test-Path (Join-Path $Root ".env"))) {
    Copy-Item (Join-Path $Root ".env.example") (Join-Path $Root ".env")
}

$modelConfig = Join-Path $Root "config\models_config.json"
if (-not (Test-Path $modelConfig)) {
    Copy-Item (Join-Path $Root "config\models_config.example.json") $modelConfig
}

Write-Info "Starting the local service."
$process = Start-Process -FilePath $venvPython -ArgumentList @("run.py") -WorkingDirectory $Root -PassThru

$ready = $false
for ($i = 0; $i -lt 180; $i++) {
    Start-Sleep -Seconds 1
    if ($process.HasExited) {
        Write-Host "The backend process exited with code $($process.ExitCode)." -ForegroundColor Red
        Write-Host "Check the backend window for details."
        Read-Host "Press Enter to exit"
        exit 1
    }
    if (Test-Service $Url) {
        $ready = $true
        break
    }
}

if (-not $ready) {
    Write-Host "The service did not become ready within 180 seconds." -ForegroundColor Yellow
    exit 1
}

Write-Info "Service ready; opening $Url"
Start-Process $Url
