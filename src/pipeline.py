"""Main pipeline orchestrator for KN Smart TP SL Trader v4.

This script coordinates fetching stocks from Chartink, retrieving OHLCV data
via Bhavcopy (1d) or yfinance (4h), calculating EMA/ATR crossover signals,
filtering by volume criteria, writing to Google Sheets, and alerting Telegram.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timezone

from src.config import Settings
from src.data import DataFetcher
from src.indicator import KNSmartTPSLSignals
from src.models import PipelineResult, TradeSignal
from src.screener import ChartinkScreener
from src.sheets import SheetsWriter
from src.telegram import TelegramNotifier

# Configure default logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("pipeline")


def run_pipeline(
    config: Settings,
    timeframe: str = "1d",
    top_n: int = 50,
    min_vol_ratio: float = 1.5,
    limit: int | None = None,
    dry_run: bool = False,
) -> PipelineResult:
    """Run the end-to-end signal generation pipeline."""
    run_date = date.today()
    logger.info("============================================================")
    logger.info("KN Smart TP SL Trader (v4.0) — Starting pipeline")
    logger.info(
        "Timeframe: %s | Top N: %d | Min Vol Ratio: %.2f | Limit: %s | Dry Run: %s",
        timeframe, top_n, min_vol_ratio, limit, dry_run
    )
    logger.info("============================================================")

    # Step 1: Fetch stock list from Chartink
    logger.info("Step 1: Fetching top volume stocks from Chartink screener...")
    screener = ChartinkScreener(config.chartink_screener_url, config.chartink_scan_clause)
    symbol_volumes = screener.fetch_symbols(top_n=top_n)

    if not symbol_volumes:
        logger.error("No stocks returned from screener. Exiting.")
        return PipelineResult(
            timestamp=datetime.now(timezone.utc),
            timeframe=timeframe,
            stocks_scanned=0,
            signals_found=0,
            top_n=top_n,
            volume_filter_rejected=0,
            signals=[],
        )

    # If limit is specified, restrict the list of stocks to fetch
    if limit is not None:
        symbol_volumes = symbol_volumes[:limit]
        logger.info("CLI --limit applied: Scanning only first %d stocks", len(symbol_volumes))

    symbols = [item[0] for item in symbol_volumes]
    logger.info(
        "Got %d stocks for analysis: %s",
        len(symbols),
        ", ".join(symbols[:10]) + ("..." if len(symbols) > 10 else ""),
    )

    # Step 2: Download OHLCV data
    logger.info("Step 2: Downloading %s OHLCV data...", timeframe)
    fetcher = DataFetcher(config.twelve_data_api_key)
    data_map = fetcher.fetch_batch(symbols, timeframe=timeframe)

    # Step 3: Compute signals & filter by volume ratio
    logger.info("Step 3: Calculating indicators and applying volume filter...")
    indicator = KNSmartTPSLSignals(
        ema_fast=config.ema_fast,
        ema_slow=config.ema_slow,
        atr_period=config.atr_period,
        sl_atr_mult=config.sl_atr_mult,
        rr1=config.rr1,
        rr2=config.rr2,
        rr3=config.rr3,
    )

    signals: list[TradeSignal] = []
    volume_filter_rejected = 0

    for sym in symbols:
        if sym not in data_map:
            logger.warning("No data retrieved for %s. Skipping.", sym)
            continue

        df = data_map[sym]
        df = indicator.calculate(df)

        # Get active signals (crossover in last 5 bars)
        active_sigs = indicator.get_active_signals(df, sym, timeframe, lookback=5)
        if active_sigs:
            sig = active_sigs[0]
            # Verify volume filter: signal_volume >= min_vol_ratio * 20-bar avg volume
            if sig.vol_ratio < min_vol_ratio:
                volume_filter_rejected += 1
                logger.info(
                    "Signal for %s (%s) rejected by volume filter: vol_ratio=%.2f < %.2f",
                    sym, sig.signal_type, sig.vol_ratio, min_vol_ratio
                )
                continue

            signals.append(sig)

    logger.info(
        "Analysis complete: Found %d signals after volume filtering (%d rejected)",
        len(signals), volume_filter_rejected
    )

    # Build PipelineResult
    result = PipelineResult(
        timestamp=datetime.now(timezone.utc),
        timeframe=timeframe,
        stocks_scanned=len(symbols),
        signals_found=len(signals),
        top_n=top_n,
        volume_filter_rejected=volume_filter_rejected,
        signals=signals,
    )

    if dry_run:
        logger.info("DRY RUN -- Skipping Sheets and Telegram notifications")
        logger.info("Active Signals:")
        if signals:
            for s in signals:
                logger.info(
                    "  >> %s: %s (%s) | Entry: %.2f | SL: %.2f | TP1: %.2f | Vol Ratio: %.2f (Date: %s)",
                    s.signal_type, s.symbol, s.timeframe, s.entry, s.sl, s.tp1, s.vol_ratio, s.signal_date
                )
        else:
            logger.info("  No signals matched filter criteria today.")
        return result

    # Step 4: Write to Google Sheets
    if signals:
        logger.info("Step 4: Writing signals to Google Sheets...")
        try:
            writer = SheetsWriter(
                credentials_path=config.google_credentials_path,
                sheet_name=config.google_sheet_name or None,
                spreadsheet_id=config.google_sheet_id or None,
            )
            writer.write_signals(signals, run_date, timeframe)
        except Exception:
            logger.exception("Failed to write to Google Sheets")
    else:
        logger.info("Step 4: Skipping Sheets (No signals today)")

    # Step 5: Notify Telegram
    logger.info("Step 5: Pushing alerts to Telegram...")
    try:
        notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)
        # Send individual signal alerts
        for s in signals:
            notifier.send_signal(s)
        # Send run summary
        notifier.send_summary(result)
    except Exception:
        logger.exception("Failed to send Telegram notifications")

    logger.info("Pipeline run complete.")
    return result


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="KN Smart TP SL Trader v4.0 CLI")
    parser.add_argument(
        "--timeframe",
        choices=["1d", "4h"],
        default="1d",
        help="Timeframe to scan (1d or 4h)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        help="Overriding top N volume stocks to fetch from Chartink",
    )
    parser.add_argument(
        "--min-vol-ratio",
        type=float,
        help="Overriding minimum volume ratio on the signal bar",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of stocks to scan (useful for quick testing)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip Sheets and Telegram notifications",
    )

    args = parser.parse_args()

    # Load configuration
    try:
        config = Settings.from_env()
    except Exception as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)

    # Set parameters with fallback to config
    top_n = args.top_n if args.top_n is not None else config.top_n
    min_vol_ratio = args.min_vol_ratio if args.min_vol_ratio is not None else config.min_vol_ratio

    run_pipeline(
        config=config,
        timeframe=args.timeframe,
        top_n=top_n,
        min_vol_ratio=min_vol_ratio,
        limit=args.limit,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
