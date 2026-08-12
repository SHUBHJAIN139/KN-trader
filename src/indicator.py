"""Core indicator logic — exact port of the KN Smart TP SL Pine Script.

This module translates the TradingView Pine Script indicator into Python
using pandas.  Every formula is a 1:1 port so that backtest results match
the chart overlay exactly.
"""

from __future__ import annotations

from datetime import date
import logging
import pandas as pd

from src.models import TradeSignal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Standalone helper functions
# ---------------------------------------------------------------------------

def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average — mirrors Pine Script's ``ta.ema``."""
    return series.ewm(span=period, adjust=False).mean()


def atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int,
) -> pd.Series:
    """Average True Range — mirrors Pine Script's ``ta.atr``."""
    prev_close: pd.Series = close.shift(1)

    tr1: pd.Series = high - low
    tr2: pd.Series = (high - prev_close).abs()
    tr3: pd.Series = (low - prev_close).abs()
    true_range: pd.Series = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    return true_range.ewm(alpha=1 / period, adjust=False).mean()


# ---------------------------------------------------------------------------
# Main indicator class
# ---------------------------------------------------------------------------

class KNSmartTPSLSignals:
    """Pine Script → Python port of the *KN Smart TP SL* indicator."""

    def __init__(
        self,
        ema_fast: int = 5,
        ema_slow: int = 13,
        atr_period: int = 14,
        sl_atr_mult: float = 1.5,
        rr1: float = 1.0,
        rr2: float = 2.0,
        rr3: float = 3.0,
    ) -> None:
        self.ema_fast: int = ema_fast
        self.ema_slow: int = ema_slow
        self.atr_period: int = atr_period
        self.sl_atr_mult: float = sl_atr_mult
        self.rr1: float = rr1
        self.rr2: float = rr2
        self.rr3: float = rr3

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add indicator columns to *df* **in-place** and return it."""
        # --- EMAs --------------------------------------------------------
        df["ema_fast"] = ema(df["close"], self.ema_fast)
        df["ema_slow"] = ema(df["close"], self.ema_slow)

        # --- ATR ---------------------------------------------------------
        df["atr"] = atr(df["high"], df["low"], df["close"], self.atr_period)

        # --- Volume MA (20-bar rolling average) --------------------------
        if "volume" in df.columns:
            df["vol_ma"] = df["volume"].rolling(window=20, min_periods=1).mean()
        else:
            df["vol_ma"] = 0.0

        # --- Crossover / Crossunder signals ------------------------------
        fast: pd.Series = df["ema_fast"]
        slow: pd.Series = df["ema_slow"]
        fast_prev: pd.Series = fast.shift(1)
        slow_prev: pd.Series = slow.shift(1)

        df["buy_signal"] = (fast > slow) & (fast_prev <= slow_prev)
        df["sell_signal"] = (fast < slow) & (fast_prev >= slow_prev)

        return df

    def get_trade_levels(
        self,
        row: pd.Series,
        signal_type: str,
        symbol: str,
        timeframe: str,
    ) -> TradeSignal:
        """Build a ``TradeSignal`` from a single DataFrame row."""
        entry_price: float = float(row["close"])
        atr_val: float = float(row["atr"])
        risk: float = atr_val * self.sl_atr_mult

        if signal_type == "BUY":
            sl_price: float = entry_price - risk
            tp1_price: float = entry_price + risk * self.rr1
            tp2_price: float = entry_price + risk * self.rr2
            tp3_price: float = entry_price + risk * self.rr3
        elif signal_type == "SELL":
            sl_price = entry_price + risk
            tp1_price = entry_price - risk * self.rr1
            tp2_price = entry_price - risk * self.rr2
            tp3_price = entry_price - risk * self.rr3
        else:
            raise ValueError(
                f"signal_type must be 'BUY' or 'SELL', got {signal_type!r}"
            )

        risk_rupees: float = abs(entry_price - sl_price)

        rr1_pct: float = abs(tp1_price - entry_price) / entry_price * 100
        rr2_pct: float = abs(tp2_price - entry_price) / entry_price * 100
        rr3_pct: float = abs(tp3_price - entry_price) / entry_price * 100

        signal_date: date = (
            row.name.date() if hasattr(row.name, "date") else row.name
        )

        # Parse volume details
        volume_val = int(row.get("volume", 0))
        vol_ma = float(row.get("vol_ma", 0.0))
        vol_ratio = float(volume_val / vol_ma) if vol_ma > 0 else 1.0

        return TradeSignal(
            symbol=symbol,
            signal_type=signal_type,
            timeframe=timeframe,
            signal_date=signal_date,
            entry=round(entry_price, 2),
            sl=round(sl_price, 2),
            tp1=round(tp1_price, 2),
            tp2=round(tp2_price, 2),
            tp3=round(tp3_price, 2),
            atr=round(atr_val, 2),
            risk_rupees=round(risk_rupees, 2),
            rr1_pct=round(rr1_pct, 2),
            rr2_pct=round(rr2_pct, 2),
            rr3_pct=round(rr3_pct, 2),
            volume=volume_val,
            vol_ratio=round(vol_ratio, 2),
            notes="",
        )

    def get_active_signals(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        lookback: int = 5,
        max_signal_age_days: int | None = None,
    ) -> list[TradeSignal]:
        """Scan recent rows for active signals that are fresh and have NOT hit TP or SL yet.

        Filtering rules:
        1. Crossover occurred within the last `lookback` bars.
        2. Signal date must be fresh (max 3 days for 1d/4h, max 8 days for 1w).
        3. Subsequent price action from crossover bar to latest bar must NOT have touched SL or TP1.
        """
        if df.empty or len(df) < 2:
            return []

        # Determine age limit based on timeframe if not explicitly passed
        if max_signal_age_days is None:
            clean_tf = timeframe.lower().strip()
            if clean_tf in ("1w", "weekly", "wk"):
                max_signal_age_days = 8  # Current week or previous week
            elif clean_tf == "4h":
                max_signal_age_days = 3  # Last 3 days
            else:
                max_signal_age_days = 3  # Last 3 days for 1d

        today = date.today()
        tail: pd.DataFrame = df.tail(lookback)
        full_len = len(df)

        for idx in reversed(tail.index):
            row: pd.Series = tail.loc[idx]
            is_buy = bool(row["buy_signal"])
            is_sell = bool(row["sell_signal"])

            if not (is_buy or is_sell):
                continue

            signal_type = "BUY" if is_buy else "SELL"
            sig = self.get_trade_levels(row, signal_type, symbol, timeframe)

            # Rule 1: Check date freshness
            age_days = (today - sig.signal_date).days
            if age_days > max_signal_age_days:
                logger.debug(
                    "Signal for %s (%s) on %s rejected: too old (%d days > %d max)",
                    symbol, signal_type, sig.signal_date, age_days, max_signal_age_days
                )
                continue

            # Rule 2: Check subsequent price action (from signal bar + 1 to latest bar)
            try:
                sig_pos = df.index.get_loc(idx)
                if isinstance(sig_pos, slice):
                    sig_pos = sig_pos.start
            except Exception:
                sig_pos = None

            if sig_pos is not None and sig_pos < full_len - 1:
                subsequent_df = df.iloc[sig_pos + 1:]
                hit_target_or_sl = False

                if signal_type == "BUY":
                    # For BUY: SL hit if low <= sl, TP hit if high >= tp1
                    sl_hit = (subsequent_df["low"] <= sig.sl).any()
                    tp_hit = (subsequent_df["high"] >= sig.tp1).any()
                    if sl_hit or tp_hit:
                        hit_target_or_sl = True
                else:
                    # For SELL: SL hit if high >= sl, TP hit if low <= tp1
                    sl_hit = (subsequent_df["high"] >= sig.sl).any()
                    tp_hit = (subsequent_df["low"] <= sig.tp1).any()
                    if sl_hit or tp_hit:
                        hit_target_or_sl = True

                if hit_target_or_sl:
                    logger.info(
                        "Signal for %s (%s) on %s rejected: TP or SL already hit in subsequent bars",
                        symbol, signal_type, sig.signal_date
                    )
                    continue

            return [sig]

        return []
