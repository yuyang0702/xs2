@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ========================================
echo Building Frontend
echo ========================================
echo.

cd web

echo Running: npm run build
echo.

call npm run build

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo Build completed successfully!
    echo ========================================
    echo.
    echo Please restart the service:
    echo   start_determinflow.bat
    echo.
) else (
    echo.
    echo ========================================
    echo Build FAILED!
    echo ========================================
    echo.
    echo Please try manually:
    echo   1. Open PowerShell or CMD
    echo   2. cd C:\xs2\DeterminFlow\web
    echo   3. npm run build
    echo.
)

pause
