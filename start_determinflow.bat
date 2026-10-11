@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ========================================
echo DeterminFlow - Universal Launcher
echo ========================================
echo.

REM Try to use the new launcher, fallback to legacy if not exists
if exist "%~dp0start_determinflow_v2.ps1" (
    echo Using enhanced launcher v2.0...
    echo.
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_determinflow_v2.ps1"
) else (
    echo Using legacy launcher...
    echo.
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_determinflow.ps1"
)

if errorlevel 1 (
  echo.
  echo DeterminFlow startup failed. See the message above.
  echo.
  echo Troubleshooting:
  echo   1. Check the error messages above
  echo   2. Run manually: .venv\Scripts\python.exe run.py
  echo   3. See documentation: STARTUP_TROUBLESHOOTING.md
  echo.
  pause
)
endlocal
