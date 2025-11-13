@echo off
REM ==========================================
REM Run swim app on timeline-dev branch (your way)
REM Uses: python -m uvicorn main:app --reload
REM ==========================================

REM 1) go to your project folder
cd /d "C:\Users\hammo\OneDrive\Desktop\swim-app"

REM 2) show current branch
echo.
echo ==== Current Git Branch ====
git branch

REM 3) switch to timeline-dev
echo.
echo ==== Checking out timeline-dev ====
git checkout timeline-dev

REM 4) pull latest (optional)
echo.
echo ==== Pulling latest from origin ====
git pull

REM 5) start the FastAPI server in a NEW window
REM    we CD again inside that window, then run python -m uvicorn ... --reload
start "swim-api" cmd /k "cd /d C:\Users\hammo\OneDrive\Desktop\swim-app && python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000"

REM 6) wait a few seconds so the server can start
timeout /t 3 /nobreak >nul

REM 7) open browser to the app
start http://127.0.0.1:8000/

pause
