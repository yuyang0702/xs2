@echo off
cd /d "%~dp0web"
echo Building frontend...
call npm run build
if %errorlevel% equ 0 (
    echo.
    echo Frontend build completed successfully!
    echo.
) else (
    echo.
    echo Frontend build failed!
    echo.
)
pause
