"""Pydantic models for all I/O boundaries in the trading pipeline.

Why Pydantic?
- Validates data at runtime (catches bad API responses before they corrupt signals)
- Self-documenting schemas (a new contributor can read models.py to understand the data flow)
- Serialization to dict/JSON for Sheets and Telegram output
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, ConfigDict


class TradeSignal(BaseModel):
    """A single trade signal with ATR-based TP/SL levels.

    Maps 1:1 to the Pine Script's output when buySignal or sellSignal fires.
    All price fields are in INR (Indian Rupees).
    """

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(..., description="NSE symbol, e.g. 'RELIANCE'")
    signal_type: Literal["BUY", "SELL"] = Field(
        ..., description="Direction of the EMA crossover signal"
    )
    timeframe: str = Field(
        ..., description="Timeframe used: '1d' or '4h'"
    )
    signal_date: date = Field(
        ..., description="Date the crossover occurred"
    )
    entry: float = Field(..., description="Entry price (close at signal bar)")
    sl: float = Field(..., description="Stop-loss = entry ∓ ATR × sl_mult")
    tp1: float = Field(..., description="Take-profit 1 = entry ± risk × RR1")
    tp2: float = Field(..., description="Take-profit 2 = entry ± risk × RR2")
    tp3: float = Field(..., description="Take-profit 3 = entry ± risk × RR3")
    atr: float = Field(..., description="ATR value at signal bar")
    risk_rupees: float = Field(
        ..., description="Absolute risk per share = ATR × sl_mult"
    )
    rr1_pct: float = Field(
        ..., description="TP1 distance as % of entry"
    )
    rr2_pct: float = Field(
        ..., description="TP2 distance as % of entry"
    )
    rr3_pct: float = Field(
        ..., description="TP3 distance as % of entry"
    )
    volume: int = Field(..., description="Volume on signal bar")
    vol_ratio: float = Field(..., description="Ratio of signal volume to 20-bar avg volume")
    notes: str = Field(default="", description="Extra notes or metrics for this signal")


class PipelineResult(BaseModel):
    """Summary of a single pipeline run.

    Used to build the Telegram summary message and the Google Sheets
    header row for each run.
    """

    model_config = ConfigDict(frozen=True)

    timestamp: datetime = Field(
        ..., description="UTC timestamp when the pipeline finished"
    )
    timeframe: str = Field(
        ..., description="Timeframe used: '1d' or '4h'"
    )
    stocks_scanned: int = Field(
        ..., ge=0, description="Number of stocks fetched from screener"
    )
    signals_found: int = Field(
        ..., ge=0, description="Number of signals detected"
    )
    top_n: int = Field(
        default=50, ge=0, description="Maximum number of top volume stocks scanned"
    )
    volume_filter_rejected: int = Field(
        default=0, ge=0, description="Number of signals rejected by volume filter"
    )
    signals: list[TradeSignal] = Field(
        default_factory=list,
        description="All signals found in this run",
    )


class ScreenerStock(BaseModel):
    """A single stock returned from the Chartink screener.

    We only need the NSE code for downstream processing, but we capture
    extra fields for logging/debugging.
    """

    model_config = ConfigDict(frozen=True)

    nsecode: str = Field(..., description="NSE symbol, e.g. 'RELIANCE'")
    name: str = Field(default="", description="Full company name")
    close: float = Field(default=0.0, description="Last close price from screener")
    per_chg: float = Field(default=0.0, description="Percentage change")
    volume: int = Field(default=0, description="Volume from screener")
