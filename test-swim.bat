@echo off
:: -------------------------------------------
:: LSSC Swim App - Local Test Script
:: -------------------------------------------
:: Runs the FastAPI backend locally with reload enabled
:: and opens the site in your browser for preview.
:: -------------------------------------------

cd "%USERPROFILE%\OneDrive\Desktop\swim-app"

echo.
echo ===============================
echo   LSSC Swim App - Local Test
echo ===============================
echo.

:: Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python not found. Please install Python 3.12 or later.
    pause
    exit /b
)

:: Check for uvicorn
python -m uvicorn --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Uvicorn is not installed. Installing now...
    python -m pip install uvicorn fastapi python-multipart
)

echo.
echo 🚀 Starting FastAPI app with auto-reload...
start http://127.0.0.1:8000
echo.
echo (Press CTRL + C in this window to stop the server.)
echo.

python -m uvicorn main:app --reload

pause
