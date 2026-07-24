"""Core indicator logic — exact port of the KN Smart TP SL Pine Script.

This module translates the TradingView Pine Script indicator into Python
using pandas.  Every formula is a 1:1 port so that backtest results match
the chart overlay exactly.
"""

from __future__ import annotations

from datetime import date
import pandas as pd

from src.models import TradeSignal


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
    ) -> list[TradeSignal]:
        """Scan the last *lookback* rows for the most recent signal."""
        tail: pd.DataFrame = df.tail(lookback)

        for idx in reversed(tail.index):
            row: pd.Series = tail.loc[idx]

            if row["buy_signal"]:
                return [self.get_trade_levels(row, "BUY", symbol, timeframe)]

            if row["sell_signal"]:
                return [self.get_trade_levels(row, "SELL", symbol, timeframe)]

        return []
