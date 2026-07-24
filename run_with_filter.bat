@echo off
REM ============================================================
REM KN Smart TP SL Trader - RUN WITH VOLUME FILTER
REM ============================================================
REM Uses --min-vol-ratio 1.5 (strict - only signals with 50%+ volume)
REM Top 50 stocks by volume from Chartink, 4h timeframe
REM ============================================================

REM Force E: drive (works no matter which drive you start from)
cd /d "E:\kn-trader"

REM Activate venv (must run in every fresh CMD)
echo [1/3] Activating virtual environment...
call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo ERROR: Could not activate venv. Check that E:\kn-trader\.venv exists.
    pause
    exit /b 1
)

REM Run the pipeline
echo [2/3] Running KN Trader (4h, top 50, vol ratio >= 1.5)...
echo.
E:\python311\python.exe -m src.pipeline --timeframe 4h --top-n 50 --min-vol-ratio 1.5

echo.
echo [3/3] Done. Check Google Sheet and Telegram group.
pause
