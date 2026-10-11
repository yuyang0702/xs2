@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ========================================
echo DeterminFlow - Automatic Dependency Installer
echo ========================================
echo.
echo Starting DeterminFlow with automatic dependency detection and installation...
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_determinflow.ps1"
if errorlevel 1 (
  echo.
  echo DeterminFlow startup failed. See the message above.
  pause
)
endlocal
