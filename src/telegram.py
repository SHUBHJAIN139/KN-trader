"""Telegram bot notifier with rate limit retrying, message spacing, and volume logging."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

import requests

from src.models import TradeSignal, PipelineResult

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Pushes trade signals and run summaries to a Telegram channel/group."""

    def __init__(self, bot_token: str, chat_id: str) -> None:
        """Initialize Telegram notifier.

        Args:
            bot_token: HTTP API bot token from BotFather.
            chat_id: Unique chat ID or channel username (e.g. '@mychannel').
        """
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._api_url = f"https://api.telegram.org/bot{bot_token}"
        self._last_send_time = 0.0

    def _wait(self) -> None:
        """Helper to enforce at least 1.5 seconds delay between requests."""
        now = time.time()
        elapsed = now - self._last_send_time
        needed = 1.5
        if elapsed < needed:
            sleep_time = needed - elapsed
            logger.debug("Sleeping %.2f seconds to maintain Telegram rate limits", sleep_time)
            time.sleep(sleep_time)

    def _send_message(self, text: str) -> bool:
        """Send message via Telegram Bot API with 429 rate limit retries."""
        url = f"{self._api_url}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        self._wait()

        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                resp = requests.post(url, json=payload, timeout=15)

                # Auto-retry on 429
                if resp.status_code == 429:
                    retry_after = 5.0  # default fallback
                    headers = resp.headers
                    for h_name, h_val in headers.items():
                        if h_name.lower() == "retry-after":
                            try:
                                retry_after = float(h_val)
                            except ValueError:
                                pass
                            break
                    logger.warning(
                        "Telegram rate limit (429) hit. Waiting %.1f seconds (attempt %d/%d)...",
                        retry_after, attempt + 1, max_retries
                    )
                    time.sleep(retry_after)
                    continue

                resp.raise_for_status()
                result = resp.json()

                if result.get("ok"):
                    logger.info("Telegram message sent successfully")
                    self._last_send_time = time.time()
                    return True
                else:
                    logger.warning(
                        "Telegram API returned ok=false: %s",
                        result.get("description", "unknown error"),
                    )
                    return False

            except requests.exceptions.RequestException as req_err:
                if attempt < max_retries:
                    wait_time = 2 ** attempt * 2
                    logger.warning(
                        "Telegram request failed (connection/timeout): %s. Retrying in %ds (attempt %d/%d)...",
                        req_err, wait_time, attempt + 1, max_retries
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(
                        "Telegram request failed after all retries. Last error: %s",
                        req_err,
                        exc_info=True
                    )
                    return False
            except Exception:
                logger.exception("Unexpected error sending Telegram message")
                return False
        return False

    def send_signal(self, signal: TradeSignal | dict[str, Any]) -> bool:
        """Send a single trade signal alert. Accepts Pydantic object or dict."""
        if isinstance(signal, dict):
            s = TradeSignal(**signal)
        else:
            s = signal

        emoji = "🟢" if s.signal_type == "BUY" else "🔴"
        direction = s.signal_type
        sl_pct = abs(s.sl - s.entry) / s.entry * 100

        message = (
            f"{emoji} *{direction} Signal: {s.symbol}*\n"
            f"⏱ Timeframe: `{s.timeframe}`\n"
            f"📅 Date: `{s.signal_date}`\n"
            f"\n"
            f"📊 Entry: `₹{s.entry:,.2f}`\n"
            f"🛑 SL: `₹{s.sl:,.2f}` ({sl_pct:.2f}%)\n"
            f"🎯 TP1: `₹{s.tp1:,.2f}` (+{s.rr1_pct:.2f}%)\n"
            f"🎯 TP2: `₹{s.tp2:,.2f}` (+{s.rr2_pct:.2f}%)\n"
            f"🎯 TP3: `₹{s.tp3:,.2f}` (+{s.rr3_pct:.2f}%)\n"
            f"\n"
            f"📐 ATR: `{s.atr:.2f}` | Risk: `₹{s.risk_rupees:.2f}`\n"
            f"🔊 Volume: `{s.volume:,}` (x{s.vol_ratio:.2f} avg)\n"
        )

        return self._send_message(message)

    def send_summary(self, result: PipelineResult) -> bool:
        """Send summary report of the pipeline run."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        buy_count = sum(1 for s in result.signals if s.signal_type == "BUY")
        sell_count = sum(1 for s in result.signals if s.signal_type == "SELL")

        message = (
            f"📋 *KN Smart TP SL Trader — Run Summary*\n"
            f"⏱ Timeframe: `{result.timeframe}`\n"
            f"🕐 Run: `{now}`\n"
            f"\n"
            f"📊 Stocks Scanned: `{result.stocks_scanned}` (Top {result.top_n} by volume)\n"
            f"🔍 Signals Found: `{result.signals_found}`\n"
            f"🟢 Buy Signals: `{buy_count}`\n"
            f"🔴 Sell Signals: `{sell_count}`\n"
            f"❌ Volume Filter Rejected: `{result.volume_filter_rejected}`\n"
        )

        if result.signals:
            message += "\n*Signals:*\n"
            for s in result.signals:
                emoji = "🟢" if s.signal_type == "BUY" else "🔴"
                message += (
                    f"{emoji} `{s.symbol}` — "
                    f"Entry: ₹{s.entry:,.2f} | "
                    f"SL: ₹{s.sl:,.2f} | "
                    f"Vol: {s.volume:,} (x{s.vol_ratio:.1f} avg)\n"
                )
        else:
            message += "\n_No signals matched filters today._\n"

        return self._send_message(message)
