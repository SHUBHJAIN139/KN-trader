"""Configuration loader for KN Smart TP SL Trader utilizing pydantic-settings."""

from __future__ import annotations

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Configuration settings loaded from environment or .env file."""

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = Field(default="", validation_alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", validation_alias="TELEGRAM_CHAT_ID")
    google_credentials_path: str = Field(
        default="credentials/service-account.json",
        validation_alias="GOOGLE_CREDENTIALS_PATH",
    )
    google_sheet_name: str = Field(
        default="KN Trader Signals",
        validation_alias="GOOGLE_SHEET_NAME",
    )
    google_sheet_id: str = Field(
        default="",
        validation_alias="GOOGLE_SHEET_ID",
    )
    twelve_data_api_key: str = Field(
        default="",
        validation_alias="TWELVE_DATA_API_KEY",
    )
    chartink_screener_url: str = Field(
        default="https://chartink.com/screener/trading-view-11042052",
        validation_alias="CHARTINK_SCREENER_URL",
    )
    chartink_scan_clause: str = Field(
        default="",
        validation_alias="CHARTINK_SCAN_CLAUSE",
    )

    ema_fast: int = Field(default=5, validation_alias="EMA_FAST")
    ema_slow: int = Field(default=13, validation_alias="EMA_SLOW")
    atr_period: int = Field(default=14, validation_alias="ATR_PERIOD")
    sl_atr_mult: float = Field(default=1.5, validation_alias="SL_ATR_MULT")
    rr1: float = Field(default=1.0, validation_alias="RR1")
    rr2: float = Field(default=2.0, validation_alias="RR2")
    rr3: float = Field(default=3.0, validation_alias="RR3")
    top_n: int = Field(default=50, validation_alias="TOP_N")
    min_vol_ratio: float = Field(default=1.5, validation_alias="MIN_VOL_RATIO")

    @classmethod
    def from_env(cls) -> Settings:
        """Create a Settings instance.

        BaseSettings does this automatically by reading environment/dotenv variables.
        """
        return cls()
