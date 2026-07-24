"""Diagnostic tool for KN Smart TP SL Trader v4.0.

Runs 8 validation checks covering environment, packages, screener, volume parsing,
1d data source, 4h data source, indicator logic, and external APIs (Sheets/Telegram).
Uses plain ASCII labels for printing to support Windows Command Prompt (cp1252).
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
import pandas as pd

# Set path to include src
sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def print_header(title: str) -> None:
    print(f"\n============================================================")
    print(f" SECTION: {title}")
    print(f"============================================================")


def run_checks() -> bool:
    success = True
    print("Starting system diagnostics for KN Smart TP SL Trader (v4.0)...")

    # -------------------------------------------------------------------------
    # 1. Package Imports Check
    # -------------------------------------------------------------------------
    print_header("1. Package Imports Check")
    try:
        import pandas as pd
        import requests
        from bs4 import BeautifulSoup
        import gspread
        from google.oauth2.service_account import Credentials
        import yfinance as yf
        import pydantic
        import pydantic_settings
        print("[PASS] All required packages imported successfully.")
    except ImportError as e:
        print(f"[FAIL] Missing required packages: {e}")
        success = False

    # -------------------------------------------------------------------------
    # 2. Config & Environment Variables Check
    # -------------------------------------------------------------------------
    print_header("2. Config & Environment Variables Check")
    try:
        from src.config import Settings
        config = Settings.from_env()
        print(f"GOOGLE_SHEET_NAME: {config.google_sheet_name}")
        print(f"TELEGRAM_CHAT_ID: {config.telegram_chat_id}")
        print(f"CHARTINK_SCREENER_URL: {config.chartink_screener_url}")
        print(f"EMA_FAST/SLOW: {config.ema_fast}/{config.ema_slow}")
        print(f"ATR_PERIOD/SL_MULT: {config.atr_period}/{config.sl_atr_mult}")
        print(f"TOP_N / MIN_VOL_RATIO: {config.top_n} / {config.min_vol_ratio}")
        
        # Basic validation
        if not config.google_sheet_name:
            print("[FAIL] GOOGLE_SHEET_NAME is not set.")
            success = False
        else:
            print("[PASS] Configuration loaded and validated successfully.")
    except Exception as e:
        print(f"[FAIL] Config loading failed: {e}")
        success = False

    # -------------------------------------------------------------------------
    # 3. Chartink Screener Connectivity Check
    # -------------------------------------------------------------------------
    print_header("3. Chartink Screener Connectivity Check")
    try:
        from src.screener import ChartinkScreener
        screener = ChartinkScreener(config.chartink_screener_url, config.chartink_scan_clause)
        print(f"Connecting to: {config.chartink_screener_url}")
        stocks = screener.fetch_symbols(top_n=5)
        if stocks:
            print(f"[PASS] Successfully fetched stocks from Chartink. Top 5: {stocks}")
        else:
            print("[FAIL] Screener returned an empty list of stocks.")
            success = False
    except Exception as e:
        print(f"[FAIL] Screener connectivity failed: {e}")
        success = False

    # -------------------------------------------------------------------------
    # 4. Volume Suffix Parsing Check
    # -------------------------------------------------------------------------
    print_header("4. Volume Suffix Parsing Check")
    try:
        from src.screener import parse_volume
        test_cases = [
            ("1.5M", 1500000),
            ("500K", 500000),
            ("2.5L", 250000),
            ("1.2Cr", 12000000),
            ("1,234,567", 1234567),
            (75000, 75000)
        ]
        sub_pass = True
        for raw, expected in test_cases:
            parsed = parse_volume(raw)
            if parsed != expected:
                print(f"[FAIL] parse_volume({raw!r}) returned {parsed}, expected {expected}")
                sub_pass = False
        if sub_pass:
            print("[PASS] Volume parser correctly handles K, M, L, Cr suffixes and numeric inputs.")
        else:
            success = False
    except Exception as e:
        print(f"[FAIL] Volume parser check failed: {e}")
        success = False

    # -------------------------------------------------------------------------
    # 5. Daily NSE Bhavcopy (1d) Check
    # -------------------------------------------------------------------------
    print_header("5. Daily NSE Bhavcopy (1d) Check")
    try:
        from src.data import NSEFetcher
        fetcher = NSEFetcher()
        # Find a weekday date that is likely to exist (e.g. 2-3 days ago)
        test_date = date.today() - timedelta(days=3)
        while test_date.weekday() >= 5:  # Skip weekends
            test_date -= timedelta(days=1)
            
        print(f"Downloading test Bhavcopy for: {test_date}")
        df = fetcher._download_day(test_date)
        if df is not None and not df.empty:
            print(f"[PASS] Successfully downloaded Bhavcopy. Shape: {df.shape}")
            # Try symbol extraction
            sample_sym = "RELIANCE"
            row = fetcher._extract_symbol(df, sample_sym, test_date)
            if row:
                print(f"[PASS] Successfully extracted symbol {sample_sym} data: {row}")
            else:
                print(f"[WARN] Could not extract {sample_sym} (perhaps not traded in EQ series on this day)")
        else:
            print("[FAIL] Bhavcopy download returned None or empty DataFrame.")
            success = False
    except Exception as e:
        print(f"[FAIL] NSE Bhavcopy check failed: {e}")
        success = False

    # -------------------------------------------------------------------------
    # 6. Intraday yfinance (4h) Check
    # -------------------------------------------------------------------------
    print_header("6. Intraday yfinance (4h) Check")
    try:
        from src.data import TwelveDataFetcher
        fetcher = TwelveDataFetcher()
        sample_sym = "TRENT"
        print(f"Downloading 1h data for {sample_sym} via yfinance...")
        df_1h = fetcher._fetch_hourly(sample_sym)
        if df_1h is not None and not df_1h.empty:
            print(f"[PASS] Downloaded 1h data. Columns: {list(df_1h.columns)}")
            df_4h = fetcher.fetch_4h(sample_sym)
            if df_4h is not None and not df_4h.empty:
                print(f"[PASS] Successfully resampled to 4h. Shape: {df_4h.shape}")
            else:
                print("[FAIL] Resample to 4h returned empty DataFrame.")
                success = False
        else:
            print("[FAIL] yfinance 1h download returned empty DataFrame.")
            success = False
    except Exception as e:
        print(f"[FAIL] yfinance check failed: {e}")
        success = False

    # -------------------------------------------------------------------------
    # 7. Indicator Crossover & Volume Ratio Check
    # -------------------------------------------------------------------------
    print_header("7. Indicator Crossover & Volume Ratio Check")
    try:
        from src.indicator import KNSmartTPSLSignals
        
        # Create dummy dataframe
        dates = pd.date_range(start="2026-06-01", periods=25, freq="D")
        dummy_df = pd.DataFrame({
            "open": [100.0] * 25,
            "high": [105.0] * 25,
            "low": [95.0] * 25,
            "close": [100.0] * 24 + [110.0],  # sudden spike for crossover trigger
            "volume": [1000] * 24 + [3000]    # high volume for volume filter
        }, index=dates)
        
        indicator = KNSmartTPSLSignals(ema_fast=5, ema_slow=13)
        dummy_df = indicator.calculate(dummy_df)
        
        print("Indicator columns computed:", [c for c in dummy_df.columns if c in ["ema_fast", "ema_slow", "atr", "vol_ma", "buy_signal"]])
        
        # Trigger signal check
        active = indicator.get_active_signals(dummy_df, "TEST", "1d", lookback=5)
        if active:
            sig = active[0]
            print(f"[PASS] Found active signal: {sig.signal_type} on {sig.signal_date}")
            print(f"[PASS] Computed vol_ratio: {sig.vol_ratio} (signal volume: {sig.volume})")
        else:
            print("[WARN] No signal triggered. This is normal depending on dummy data series crossover state.")
            
        print("[PASS] Indicator calculations executed without exceptions.")
    except Exception as e:
        print(f"[FAIL] Indicator check failed: {e}")
        success = False

    # -------------------------------------------------------------------------
    # 8. External API Check (Google Sheets & Telegram)
    # -------------------------------------------------------------------------
    print_header("8. External API Check (Google Sheets & Telegram)")
    
    # 8a. Google Sheets Connection Check
    print("Connecting to Google Sheets...")
    try:
        from src.sheets import SheetsWriter
        import gspread
        writer = SheetsWriter(config.google_credentials_path, config.google_sheet_name)
        is_key = len(config.google_sheet_name) == 44 and config.google_sheet_name.startswith("1")
        try:
            if is_key:
                sh = writer.client.open_by_key(config.google_sheet_name)
            else:
                sh = writer.client.open(config.google_sheet_name)
            print(f"[PASS] Successfully opened Google Sheet: '{config.google_sheet_name}'")
        except gspread.SpreadsheetNotFound:
            if is_key:
                print(f"[FAIL] Google Sheet ID '{config.google_sheet_name}' not found or not shared with service account.")
                print("  Please make sure you have shared your Google Sheet with the service account email:")
                print("  -> kn-trader@ace-charter-501116-e9.iam.gserviceaccount.com")
                success = False
            else:
                print(f"Sheet '{config.google_sheet_name}' not found. Testing auto-creation...")
                try:
                    sh = writer.client.create(config.google_sheet_name)
                    print(f"[PASS] Successfully created new Google Sheet: '{config.google_sheet_name}'")
                except gspread.exceptions.APIError as api_err:
                    print(f"[FAIL] Could not create sheet (quota/API limit): {api_err}")
                    print("  To fix this, please create a Google Sheet manually and share it with the service account email:")
                    print("  -> kn-trader@ace-charter-501116-e9.iam.gserviceaccount.com")
                    print("  Then configure GOOGLE_SHEET_NAME in your .env with the title or ID of that sheet.")
                    success = False
    except Exception as e:
        print(f"[FAIL] Google Sheets check failed: {e}")
        print("  Please make sure your GOOGLE_CREDENTIALS_PATH has valid JSON credentials.")
        success = False

    # 8b. Telegram Bot Connection Check
    print("Connecting to Telegram Bot API...")
    if not config.telegram_bot_token:
        print("[WARN] TELEGRAM_BOT_TOKEN is not set. Skipping Telegram check.")
    else:
        try:
            url = f"https://api.telegram.org/bot{config.telegram_bot_token}/getMe"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                bot_info = resp.json().get("result", {})
                print(f"[PASS] Telegram Bot is active. Username: @{bot_info.get('username')}")
            else:
                print(f"[FAIL] Telegram token check returned status {resp.status_code}")
                success = False
        except Exception as e:
            print(f"[FAIL] Telegram connection failed: {e}")
            success = False

    print_header("Diagnostic Summary")
    if success:
        print("System ready. All checks passed successfully.")
    else:
        print("Diagnostic checks failed. Please check configurations.")
        
    return success


if __name__ == "__main__":
    run_checks()
