@echo off
:: Engleesh launcher — Windows

cd /d "%~dp0"

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Python not found.
    echo Install from https://www.python.org/downloads/
    echo Check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

echo Installing dependencies...
venv\Scripts\pip.exe install -q -r requirements.txt

echo Starting Engleesh...
venv\Scripts\python.exe app.py

if %errorlevel% neq 0 (
    echo.
    echo Application exited with an error.
    pause
)
