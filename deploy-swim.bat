@echo off
:: -------------------------------------------
:: LSSC Swim App Auto Deploy Script
:: -------------------------------------------
:: This script stages, commits, and pushes updates to GitHub,
:: then opens the Render dashboard for live deployment.
:: -------------------------------------------

cd "%USERPROFILE%\OneDrive\Desktop\swim-app"

echo.
echo ===============================
echo   LSSC Swim App - Deploy Tool
echo ===============================
echo.

:: Show git status first
git status
echo.
echo -------------------------------------------
echo The files above will be deployed to Render.
echo -------------------------------------------
echo.

:: Ask for confirmation
set /p confirm="Proceed with deployment? (Y/N): "
if /I not "%confirm%"=="Y" (
    echo ❌ Deployment cancelled.
    pause
    exit /b
)

echo.
echo 🔄 Staging changes...
git add .

:: Ask for commit message
set /p msg="Enter a short commit message (or press Enter for default): "
if "%msg%"=="" set msg=Update swim app

echo.
echo 💬 Committing changes...
git commit -m "%msg% - %date%"

echo.
echo 🚀 Pushing to GitHub...
git push origin main

if %errorlevel% neq 0 (
    echo ❌ Git push failed. Please check your internet connection or GitHub login.
    pause
    exit /b
)

echo.
echo 🌐 Opening Render Dashboard...
start https://render.com/dashboard

echo.
echo ✅ Deployment complete! Render is rebuilding your live site.
pause
