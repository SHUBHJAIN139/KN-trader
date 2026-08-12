"""Telegram Bot Command Listener for KN Smart TP SL Trader.

Listens for chat commands from Telegram (/scan, /run, /nofilter, /help)
and executes the signal pipeline directly, replying with live signals in Telegram chat.
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Any

import requests

from src.config import Settings
from src.pipeline import run_pipeline, parse_timeframes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("telegram_bot")


class TelegramBotListener:
    """Long-polling Telegram Bot command handler."""

    def __init__(self, settings: Settings) -> None:
        self.config = settings
        self.token = settings.telegram_bot_token.strip()
        self.allowed_chat_id = settings.telegram_chat_id.strip()
        self.api_url = f"https://api.telegram.org/bot{self.token}"
        self.offset = 0

    def send_message(self, chat_id: str, text: str, reply_to_message_id: int | None = None) -> bool:
        """Send message to Telegram chat."""
        url = f"{self.api_url}/sendMessage"
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id

        try:
            resp = requests.post(url, json=payload, timeout=15)
            if not resp.ok:
                # Fallback to plain text if Markdown fails
                payload.pop("parse_mode", None)
                payload["text"] = text.replace("*", "").replace("`", "").replace("_", "")
                requests.post(url, json=payload, timeout=15)
            return True
        except Exception as e:
            logger.error("Failed to send bot response: %s", e)
            return False

    def handle_command(self, chat_id: str, text: str, msg_id: int) -> None:
        """Process incoming chat command."""
        cmd_raw = text.strip().lower()
        parts = cmd_raw.split()
        cmd = parts[0] if parts else ""

        # Handle bot username suffix if command is sent in a group e.g. /scan@kn_trader_v2_bot
        if "@" in cmd:
            cmd = cmd.split("@")[0]

        if cmd in ("/start", "/help"):
            help_msg = (
                "🤖 *KN Trader Bot Commands*\n\n"
                "🔹 `/scan` or `/run` — Scan 4h & 1w timeframes (with volume filter)\n"
                "🔹 `/scan 4h` — Scan 4h timeframe only\n"
                "🔹 `/scan 1w` — Scan 1w weekly timeframe only\n"
                "🔹 `/scan 1d` — Scan 1d daily timeframe only\n"
                "🔹 `/nofilter` — Scan 4h & 1w WITHOUT volume filter\n"
                "🔹 `/all` — Scan 1d, 4h & 1w timeframes\n"
            )
            self.send_message(chat_id, help_msg, msg_id)
            return

        # Determine timeframe & filter mode based on command
        if cmd == "/nofilter":
            tfs = ["4h", "1w"]
            min_vol = 0.0
        elif cmd in ("/scan", "/run", "/all") or cmd.startswith("/scan"):
            if len(parts) > 1:
                tfs = parse_timeframes(parts[1:])
            elif cmd == "/all":
                tfs = ["1d", "4h", "1w"]
            else:
                tfs = ["4h", "1w"]
            min_vol = self.config.min_vol_ratio
        else:
            return

        tf_str = ", ".join(tfs)
        mode_str = f"Volume Filter >= {min_vol}x" if min_vol > 0 else "NO Volume Filter"
        start_msg = (
            f"⏳ *Starting Market Scan...*\n"
            f"⏱ Timeframes: `{tf_str}`\n"
            f"🔊 Mode: `{mode_str}`\n\n"
            f"_Please wait, scanning top volume stocks..._"
        )
        self.send_message(chat_id, start_msg, msg_id)

        try:
            for tf in tfs:
                run_pipeline(
                    config=self.config,
                    timeframe=tf,
                    top_n=self.config.top_n,
                    min_vol_ratio=min_vol,
                    dry_run=False,
                )
            self.send_message(chat_id, f"✅ *Scan Complete!* ({tf_str})", msg_id)
        except Exception as e:
            logger.exception("Error executing pipeline from bot command")
            self.send_message(chat_id, f"❌ *Error during scan:* `{e}`", msg_id)

    def start_polling(self) -> None:
        """Start long-polling for commands."""
        logger.info("KN Trader Bot Listener started. Waiting for chat commands...")
        print("Bot listener is running. Send /help or /scan in Telegram!")

        while True:
            try:
                url = f"{self.api_url}/getUpdates"
                params = {"offset": self.offset, "timeout": 20}
                resp = requests.get(url, params=params, timeout=25)

                if not resp.ok:
                    time.sleep(5)
                    continue

                data = resp.json()
                results = data.get("result", [])

                for item in results:
                    self.offset = item["update_id"] + 1
                    message = item.get("message") or item.get("channel_post")
                    if not message:
                        continue

                    text = message.get("text", "")
                    chat_id = str(message.get("chat", {}).get("id", ""))
                    msg_id = message.get("message_id")

                    if text.startswith("/"):
                        logger.info("Received command '%s' from chat %s", text, chat_id)
                        self.handle_command(chat_id, text, msg_id)

            except Exception as e:
                logger.error("Polling error: %s", e)
                time.sleep(5)


def main() -> None:
    config = Settings.from_env()
    if not config.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN is not configured in .env")
        sys.exit(1)

    listener = TelegramBotListener(config)
    listener.start_polling()


if __name__ == "__main__":
    main()
