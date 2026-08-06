@echo off
REM ============================================================
REM KN Smart TP SL Trader - RUN WITHOUT VOLUME FILTER
REM ============================================================
REM Uses --min-vol-ratio 1.0 (no filter - shows ALL crossovers)
REM Top 50 stocks by volume from Chartink, 4h timeframe
REM Use this to see how many raw signals exist before filtering
REM ============================================================

REM Force E: drive
cd /d "E:\kn-trader"

REM Activate venv
echo [1/3] Activating virtual environment...
call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo ERROR: Could not activate venv. Check that E:\kn-trader\.venv exists.
    pause
    exit /b 1
)

REM Run the pipeline (volume filter disabled)
echo [2/3] Running KN Trader (4h & 1w weekly, top 50, WITHOUT volume filter - ALL signals)...
echo.
E:\python311\python.exe -m src.pipeline --timeframe 4h 1w --top-n 50 --no-vol-filter

echo.
echo [3/3] Done. Check Google Sheet and Telegram group.
echo Compare with run_with_filter.bat to see what filter rejects.
pause
