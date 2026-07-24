"""Stock data fetchers -- NSE Bhavcopy (daily) and yfinance (4h).

Daily (1d): NSE Bhavcopy CSV (free, no auth)
4h: yfinance 1h → resampled to 4h (free, no API key, works for NSE .NS stocks)
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, date
from typing import Optional
import io

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────
# NSE India Bhavcopy -- Daily OHLCV via CSV archives
# ────────────────────────────────────────────────────────────────

_NSE_BHAV_URL = (
    "https://nsearchives.nseindia.com/products/content/"
    "sec_bhavdata_full_{date}.csv"
)
_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
}

_NSE_LOOKBACK_DAYS = 180


class NSEFetcher:
    """Fetches daily OHLCV from NSE sec_bhavdata CSV archives."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(_NSE_HEADERS)
        self._day_cache: dict[str, Optional[pd.DataFrame]] = {}

    def fetch_daily(self, symbol: str) -> Optional[pd.DataFrame]:
        """Fetch ~6 months of daily OHLCV for a single NSE stock."""
        end = date.today()
        start = end - timedelta(days=_NSE_LOOKBACK_DAYS)

        rows: list[dict] = []
        current = start
        while current <= end:
            if current.weekday() < 5:  # Skip weekends
                day_df = self._download_day(current)
                if day_df is not None and not day_df.empty:
                    row = self._extract_symbol(day_df, symbol, current)
                    if row is not None:
                        rows.append(row)
            current += timedelta(days=1)

        if not rows:
            logger.warning("No daily data found for %s", symbol)
            return None

        return self._rows_to_df(rows)

    def fetch_daily_batch(self, symbols: list[str]) -> dict[str, pd.DataFrame]:
        """Fetch daily OHLCV for multiple stocks efficiently."""
        end = date.today()
        start = end - timedelta(days=_NSE_LOOKBACK_DAYS)

        symbol_set = set(s.upper() for s in symbols)
        rows_by_symbol: dict[str, list[dict]] = {s: [] for s in symbol_set}

        current = start
        days_ok = 0
        days_fail = 0

        while current <= end:
            if current.weekday() < 5:  # Skip weekends
                day_df = self._download_day(current)
                if day_df is not None and not day_df.empty:
                    days_ok += 1
                    for sym in symbol_set:
                        row = self._extract_symbol(day_df, sym, current)
                        if row is not None:
                            rows_by_symbol[sym].append(row)
                else:
                    days_fail += 1
                time.sleep(0.2)  # Be respectful

            current += timedelta(days=1)

        logger.info(
            "Bhavcopy batch: %d days fetched, %d skipped/failed",
            days_ok, days_fail,
        )

        results: dict[str, pd.DataFrame] = {}
        for sym, rows in rows_by_symbol.items():
            if rows:
                df = self._rows_to_df(rows)
                if df is not None and not df.empty:
                    results[sym] = df

        return results

    def _download_day(self, trading_date: date) -> Optional[pd.DataFrame]:
        """Download and parse one day's sec_bhavdata CSV."""
        date_str = trading_date.strftime("%d%m%Y")

        if date_str in self._day_cache:
            return self._day_cache[date_str]

        url = _NSE_BHAV_URL.format(date=date_str)

        try:
            resp = self._session.get(url, timeout=15)

            if resp.status_code == 404:
                self._day_cache[date_str] = pd.DataFrame()
                return pd.DataFrame()

            if resp.status_code != 200:
                logger.debug("Bhavcopy %d for %s", resp.status_code, trading_date)
                self._day_cache[date_str] = None
                return None

            df = pd.read_csv(io.StringIO(resp.text))
            df.columns = df.columns.str.strip()

            self._day_cache[date_str] = df
            return df

        except Exception:
            logger.exception("Error downloading Bhavcopy for %s", trading_date)
            self._day_cache[date_str] = None
            return None

    @staticmethod
    def _extract_symbol(
        day_df: pd.DataFrame, symbol: str, trading_date: date
    ) -> Optional[dict]:
        """Extract a single symbol's OHLCV from a day's Bhavcopy."""
        if "SYMBOL" not in day_df.columns:
            return None

        mask = day_df["SYMBOL"].str.strip().str.upper() == symbol.upper()
        if "SERIES" in day_df.columns:
            mask = mask & (day_df["SERIES"].str.strip() == "EQ")

        matches = day_df[mask]
        if matches.empty:
            return None

        row = matches.iloc[0]
        try:
            return {
                "date": trading_date,
                "open": float(row.get("OPEN_PRICE", 0)),
                "high": float(row.get("HIGH_PRICE", 0)),
                "low": float(row.get("LOW_PRICE", 0)),
                "close": float(row.get("CLOSE_PRICE", 0)),
                "volume": int(float(row.get("TTL_TRD_QNTY", 0))),
            }
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _rows_to_df(rows: list[dict]) -> Optional[pd.DataFrame]:
        """Convert collected rows to a clean OHLCV DataFrame."""
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna()
        return df if not df.empty else None


# ────────────────────────────────────────────────────────────────
# Helper for extracting ticker data from yfinance MultiIndex
# ────────────────────────────────────────────────────────────────

def extract_ticker_df(data: pd.DataFrame, symbol: str) -> Optional[pd.DataFrame]:
    """Robustly extract OHLCV data for a ticker from a flat or MultiIndex yfinance DataFrame."""
    if data.empty:
        return None

    if not isinstance(data.columns, pd.MultiIndex):
        # Flat columns
        df = data.copy()
        df.columns = [str(c).lower() for c in df.columns]
        return df

    ticker = f"{symbol}.NS"
    clean_sym = symbol.replace("$", "").replace(" ", "").strip()
    clean_ticker = f"{clean_sym}.NS"

    # Case A: Level 0 is the ticker (e.g. group_by="ticker")
    for t in [ticker, symbol, clean_ticker, clean_sym]:
        if t in data.columns.levels[0]:
            df = data[t].copy()
            df.columns = [str(c).lower() for c in df.columns]
            return df

    # Case B: Level 1 is the ticker (e.g. default yf.download call)
    for t in [ticker, symbol, clean_ticker, clean_sym]:
        if t in data.columns.levels[1]:
            df = data.xs(t, axis=1, level=1).copy()
            df.columns = [str(c).lower() for c in df.columns]
            return df

    return None


# ────────────────────────────────────────────────────────────────
# yfinance Hourly OHLCV (resampled to 4h)
# ────────────────────────────────────────────────────────────────

class TwelveDataFetcher:
    """Fetches hourly OHLCV from yfinance, resampled to 4h.

    We keep the TwelveDataFetcher class name for compatibility.
    """

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    def fetch_4h(self, symbol: str) -> Optional[pd.DataFrame]:
        """Fetch 1h data and resample to 4h candles."""
        df_1h = self._fetch_hourly(symbol)
        if df_1h is None or df_1h.empty:
            return None

        df_4h = df_1h.resample("4h").agg(
            {"open": "first", "high": "max", "low": "min",
             "close": "last", "volume": "sum"}
        ).dropna()

        logger.info(
            "Resampled %d 1h -> %d 4h candles for %s",
            len(df_1h), len(df_4h), symbol,
        )
        return df_4h

    def _fetch_hourly(self, symbol: str) -> Optional[pd.DataFrame]:
        """Fetch 1h OHLCV via yfinance."""
        import yfinance as yf
        try:
            ticker = symbol.replace("$", "").replace(" ", "").strip() + ".NS"
            data = yf.download(
                ticker,
                period="60d",
                interval="1h",
                progress=False,
            )
            return extract_ticker_df(data, symbol)
        except Exception as e:
            logger.warning("yfinance failed for %s: %s", symbol, e)
            return None


# ────────────────────────────────────────────────────────────────
# Unified Data Fetcher
# ────────────────────────────────────────────────────────────────

class DataFetcher:
    """Routes data requests to the correct source by timeframe."""

    def __init__(self, twelve_data_api_key: str = "") -> None:
        self._nse = NSEFetcher()
        self._td_api_key = twelve_data_api_key

    def fetch(
        self, symbol: str, timeframe: str = "1d"
    ) -> Optional[pd.DataFrame]:
        """Fetch OHLCV data for a single stock."""
        if timeframe == "1d":
            return self._nse.fetch_daily(symbol)
        elif timeframe == "4h":
            return TwelveDataFetcher(self._td_api_key).fetch_4h(symbol)
        else:
            raise ValueError(f"Unsupported timeframe: {timeframe!r}")

    def _fetch_batch_hourly_yfinance(self, symbols: list[str]) -> dict[str, pd.DataFrame]:
        """Fetch 1h OHLCV for all symbols in a single batch yfinance call."""
        import yfinance as yf
        tickers = [f"{s.replace('$', '').replace(' ', '').strip()}.NS" for s in symbols]
        try:
            data = yf.download(
                tickers,
                period="60d",
                interval="1h",
                group_by="ticker",
                progress=False,
                threads=True,
            )
            if data.empty:
                return {}
            results = {}
            for symbol in symbols:
                try:
                    df = extract_ticker_df(data, symbol)
                    if df is not None and not df.empty:
                        results[symbol] = df[["open", "high", "low", "close", "volume"]]
                except Exception:
                    continue
            return results
        except Exception as e:
            logger.warning("yfinance batch failed: %s", e)
            return {}

    def fetch_batch(
        self, symbols: list[str], timeframe: str = "1d"
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV for multiple stocks."""
        if timeframe == "1d":
            logger.info("Fetching daily data for %d stocks via Bhavcopy...", len(symbols))
            results = self._nse.fetch_daily_batch(symbols)
            logger.info("Bhavcopy complete: %d/%d stocks have data", len(results), len(symbols))
            return results

        # 4h: batch yfinance download
        total = len(symbols)
        logger.info("Fetching 4h data for %d stocks via yfinance batch...", total)
        raw_1h = self._fetch_batch_hourly_yfinance(symbols)
        results = {}
        for symbol, df_1h in raw_1h.items():
            try:
                df_4h = df_1h.resample("4h").agg(
                    {"open": "first", "high": "max", "low": "min",
                     "close": "last", "volume": "sum"}
                ).dropna()
                results[symbol] = df_4h
            except Exception as e:
                logger.warning("Failed to resample %s to 4h: %s", symbol, e)
                continue

        logger.info("Batch complete: %d/%d stocks for %s", len(results), total, timeframe)
        return results