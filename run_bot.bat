@echo off
REM ============================================================
REM KN Smart TP SL Trader - TELEGRAM BOT INTERACTIVE COMMAND LISTENER
REM ============================================================
REM Listens for commands directly in your Telegram Chat:
REM   /scan, /scan 4h, /scan 1w, /nofilter, /help
REM ============================================================

cd /d "E:\kn-trader"

echo [1/2] Activating virtual environment...
call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo ERROR: Could not activate venv. Check that E:\kn-trader\.venv exists.
    pause
    exit /b 1
)

echo [2/2] Starting Telegram Bot listener...
echo Send /help or /scan to your Telegram Bot anytime!
echo.
E:\python311\python.exe -m src.bot
pause
