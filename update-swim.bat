@echo off
:: ------------------------------------------------
:: LSSC Swim App - Test -> Deploy Script
:: ------------------------------------------------
:: 1. Runs the app locally so you can test
:: 2. After you stop it, asks if you want to deploy
:: ------------------------------------------------

cd "%USERPROFILE%\OneDrive\Desktop\swim-app"

echo.
echo ===============================
echo   LSSC Swim App - Test & Deploy
echo ===============================
echo.

:: ---------- LOCAL TEST ----------
:: check python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python not found. Install Python first.
    pause
    exit /b
)

:: check uvicorn
python -m uvicorn --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Uvicorn not found. Installing...
    python -m pip install uvicorn fastapi python-multipart
)

echo.
echo 🚀 Starting local server at http://127.0.0.1:8000
start http://127.0.0.1:8000
echo (Press CTRL + C to stop the server when you are done testing.)
echo.

python -m uvicorn main:app --reload

:: when user stops server, ask to deploy
echo.
echo ---------------------------------------
echo Local server stopped.
echo Do you want to DEPLOY these changes now?
echo ---------------------------------------
set /p dep="Deploy to GitHub/Render? (Y/N): "
if /I not "%dep%"=="Y" (
    echo ✅ Done. Changes stay local.
    pause
    exit /b
)

:: ---------- DEPLOY ----------
echo.
echo 🔄 Staging changes...
git add .

set /p msg="Enter a short commit message (or press Enter for default): "
if "%msg%"=="" set msg=Update swim app

echo.
echo 💬 Committing...
git commit -m "%msg% - %date%"

echo.
echo 🚀 Pushing to GitHub...
git push origin main

if %errorlevel% neq 0 (
    echo ❌ Push failed. Check GitHub or your connection.
    pause
    exit /b
)

echo.
echo 🌐 Opening Render dashboard...
start https://render.com/dashboard

echo.
echo ✅ All done — Render will build your new version.
pause
