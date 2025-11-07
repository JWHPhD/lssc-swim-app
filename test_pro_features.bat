@echo off
REM =====================================================
REM  LSSC Swim App - Local Test Launcher (Pro Features)
REM =====================================================

echo.
echo -----------------------------------------------------
echo   LSSC Swim App - Testing Pro Features Branch
echo -----------------------------------------------------
echo.

REM --- Step 1: Go to the project directory ---
cd /d "C:\Users\hammo\OneDrive\Desktop\swim-app"

REM --- Step 2: Check that Git is installed ---
git --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ERROR] Git is not installed or not found in PATH.
    echo Please install Git from https://git-scm.com/download/win
    pause
    exit /b
)

REM --- Step 3: Check that Python is installed ---
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ERROR] Python is not installed or not found in PATH.
    echo Please install Python from https://www.python.org/downloads/
    pause
    exit /b
)

REM --- Step 4: Check that Uvicorn is installed ---
python -m uvicorn --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ERROR] Uvicorn not found.
    echo Run: pip install fastapi uvicorn
    pause
    exit /b
)

REM --- Step 5: Switch to the pro-features branch ---
echo.
echo Switching to Git branch: pro-features ...
git checkout pro-features

REM --- Step 6: Open browser to app page ---
start http://127.0.0.1:8000

REM --- Step 7: Start FastAPI server ---
echo.
echo -----------------------------------------------------
echo   Starting FastAPI (Uvicorn) Server...
echo   Access the app at: http://127.0.0.1:8000
echo -----------------------------------------------------
echo.

python -m uvicorn main:app --reload

echo.
echo -----------------------------------------------------
echo  Server stopped or exited.
echo -----------------------------------------------------
pause
