"""Google Sheets writer utilizing atomic updates and credential JSON/filepath support."""

from __future__ import annotations

from datetime import date, datetime
import json
import logging
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from src.models import TradeSignal

logger = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_HEADERS = [
    "Symbol", "Signal", "Timeframe", "Date",
    "Entry", "SL", "TP1", "TP2", "TP3",
    "ATR", "Risk INR", "RR1 %", "RR2 %", "RR3 %",
    "Volume", "Vol Ratio"
]


class SheetsWriter:
    """Writes trade signals to Google Sheets with auto-overwrite and atomic update support."""

    def __init__(
        self,
        credentials_path: str,
        sheet_name: str | None = None,
        spreadsheet_id: str | None = None,
    ) -> None:
        """Initialize connection to Google Sheets."""
        self._sheet_name = sheet_name
        self._spreadsheet_id = spreadsheet_id
        self._client = self._authenticate(credentials_path)
        # Compatibility fields for unmodified write_signals
        self.sheet_name = sheet_name or spreadsheet_id
        self.client = self._client

    @property
    def spreadsheet(self):
        """Lazy-loaded spreadsheet property for external/validation calls."""
        return self._get_or_create_spreadsheet()

    def _authenticate(self, credentials_path: str) -> gspread.Client:
        """Authenticate using credentials path/string and return gspread Client."""
        self.creds = self._load_credentials(credentials_path)
        self.client = gspread.authorize(self.creds)
        return self.client

    def _load_credentials(self, credentials_path: str) -> Credentials:
        """Loads service account credentials from a JSON string or file path."""
        try:
            # Try parsing directly as JSON string (GitHub Actions environment secret)
            creds_dict = json.loads(credentials_path)
            logger.info("Loading Google credentials from JSON string")
            return Credentials.from_service_account_info(creds_dict, scopes=_SCOPES)
        except json.JSONDecodeError:
            # If not JSON, treat it as a path to a credentials file
            logger.info("Loading Google credentials from file: %s", credentials_path)
            return Credentials.from_service_account_file(credentials_path, scopes=_SCOPES)

    def _get_or_create_spreadsheet(self):
        if self._spreadsheet_id:
            # Use ID directly (most reliable)
            try:
                return self._client.open_by_key(self._spreadsheet_id)
            except gspread.SpreadsheetNotFound as e:
                raise RuntimeError(
                    f"Spreadsheet ID {self._spreadsheet_id} not found. "
                    "Make sure you shared the Sheet with the service account email: "
                    "kn-trader@ace-charter-501116-e9.iam.gserviceaccount.com"
                ) from e
        if self._sheet_name:
            try:
                return self._client.open(self._sheet_name)
            except gspread.SpreadsheetNotFound:
                return self._client.create(self._sheet_name)
        raise ValueError("Need sheet_name OR spreadsheet_id")

    def write_signals(
        self,
        signals: list[TradeSignal],
        run_date: date,
        timeframe: str,
    ) -> None:
        """Write signals to a new worksheet tab named by run date and timeframe.

        Example tab name: '2026-07-03 4h'. Overwrites if it already exists.
        """
        try:
            # Open spreadsheet by ID or Name
            # Google Sheet IDs are long alphanumeric strings (typically 30-50 chars)
            import re
            is_key = bool(re.fullmatch(r'[A-Za-z0-9_-]{25,}', self.sheet_name))
            
            try:
                if is_key:
                    logger.info("Opening spreadsheet by ID: %s", self.sheet_name)
                    sh = self.client.open_by_key(self.sheet_name)
                else:
                    logger.info("Opening spreadsheet by name: %s", self.sheet_name)
                    sh = self.client.open(self.sheet_name)
            except gspread.SpreadsheetNotFound:
                logger.error(
                    "Spreadsheet %r not found. Make sure you shared "
                    "it with the service account email shown in your "
                    "credentials JSON (client_email field).",
                    self.sheet_name
                )
                raise

            # Define tab name format: 'YYYY-MM-DD timeframe'
            tab_name = f"{run_date.strftime('%Y-%m-%d')} {timeframe}"

            # Open existing tab or create a new one
            try:
                ws = sh.worksheet(tab_name)
                logger.info("Worksheet %r already exists. Clearing for overwrite...", tab_name)
                ws.clear()
            except gspread.WorksheetNotFound:
                logger.info("Creating new worksheet tab: %r", tab_name)
                ws = sh.add_worksheet(title=tab_name, rows=1000, cols=20)

            # Build rows data
            rows: list[list[Any]] = [_HEADERS]
            for s in signals:
                rows.append([
                    s.symbol,
                    s.signal_type,
                    s.timeframe,
                    str(s.signal_date),
                    s.entry,
                    s.sl,
                    s.tp1,
                    s.tp2,
                    s.tp3,
                    s.atr,
                    s.risk_rupees,
                    s.rr1_pct,
                    s.rr2_pct,
                    s.rr3_pct,
                    s.volume,
                    s.vol_ratio,
                ])

            # Write atomically using worksheet.update
            num_rows = len(rows)
            num_cols = len(_HEADERS)
            col_letter = chr(64 + num_cols)  # 'P' for 16 columns
            range_name = f"A1:{col_letter}{num_rows}"

            ws.update(
                range_name=range_name,
                values=rows,
                value_input_option="USER_ENTERED"
            )
            logger.info("Successfully wrote %d signals to worksheet %r", len(signals), tab_name)

        except Exception:
            logger.exception("Failed to write signals to Google Sheets")
            raise
