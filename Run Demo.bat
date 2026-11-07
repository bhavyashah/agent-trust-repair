@echo off
rem One-click launcher for the reimbursement demo.
rem Starts a fresh demo: restores the Receipts folder, forgets saved preferences,
rem opens the chat panel in your browser and the agent's own browser window beside it.
rem Close this window (or press Ctrl+C) to stop the demo.
title Reimbursement demo
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Python environment .venv is missing. Ask Claude to set it up again.
  pause & exit /b 1
)
if not exist ".env" (
  echo The .env file with GEMINI_API_KEY is missing.
  pause & exit /b 1
)

netstat -ano | findstr /r /c:":8790 .*LISTENING" >nul
if not errorlevel 1 (
  echo The demo is already running in another window. Opening the chat panel.
  start "" http://localhost:8790/
  timeout /t 3 >nul
  exit /b 0
)

echo Starting a fresh demo. The chat panel will open in your browser.
echo Close this window to stop the demo.
echo.
".venv\Scripts\python.exe" agent\panel.py --reset %*
echo.
echo The demo has stopped.
pause
