# Debug startup script
$ErrorActionPreference = "Stop"

Write-Host "=== DeterminFlow Debug Startup ===" -ForegroundColor Cyan

# Check Python
Write-Host "`n[1/5] Checking Python..." -ForegroundColor Yellow
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "ERROR: Python not found!" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "Python found: $($python.Source)" -ForegroundColor Green

# Check venv
Write-Host "`n[2/5] Checking virtual environment..." -ForegroundColor Yellow
if (-not (Test-Path "C:\xs2\DeterminFlow\venv\Scripts\python.exe")) {
    Write-Host "ERROR: venv not found!" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "venv OK" -ForegroundColor Green

# Check port 8848
Write-Host "`n[3/5] Checking port 8848..." -ForegroundColor Yellow
$port = Get-NetTCPConnection -LocalPort 8848 -ErrorAction SilentlyContinue
if ($port) {
    Write-Host "WARNING: Port 8848 already in use by PID $($port.OwningProcess)" -ForegroundColor Red
    $kill = Read-Host "Kill existing process? (y/n)"
    if ($kill -eq 'y') {
        Stop-Process -Id $port.OwningProcess -Force
        Start-Sleep 2
        Write-Host "Process killed" -ForegroundColor Green
    }
} else {
    Write-Host "Port 8848 available" -ForegroundColor Green
}

# Check main.py
Write-Host "`n[4/5] Checking main.py..." -ForegroundColor Yellow
if (-not (Test-Path "C:\xs2\DeterminFlow\src\main.py")) {
    Write-Host "ERROR: src/main.py not found!" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "main.py OK" -ForegroundColor Green

# Start service
Write-Host "`n[5/5] Starting service..." -ForegroundColor Yellow
Set-Location "C:\xs2\DeterminFlow"

Write-Host "Running: venv\Scripts\python.exe src\main.py" -ForegroundColor Cyan
Start-Process -FilePath "C:\xs2\DeterminFlow\venv\Scripts\python.exe" -ArgumentList "src\main.py" -WorkingDirectory "C:\xs2\DeterminFlow" -NoNewWindow

# Wait and check
Start-Sleep 5
$testPort = Test-NetConnection -ComputerName localhost -Port 8848 -InformationLevel Quiet -WarningAction SilentlyContinue
if ($testPort) {
    Write-Host "`n=== SUCCESS ===" -ForegroundColor Green
    Write-Host "Service started on http://localhost:8848" -ForegroundColor Green
    Write-Host "Opening browser..." -ForegroundColor Cyan
    Start-Process "http://localhost:8848"
} else {
    Write-Host "`n=== FAILED ===" -ForegroundColor Red
    Write-Host "Service did not start. Check the console for errors." -ForegroundColor Red
}

Read-Host "`nPress Enter to exit"
