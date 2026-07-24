"""Chartink screener scraper — fetches the daily stock universe sorted by volume.

Why Chartink?
- The user maintains a custom screener that filters stocks by specific
  technical criteria. The stock list changes daily.
- We scrape this instead of hardcoding tickers, so the pipeline
  automatically adapts to the user's evolving watchlist.

How it works:
1. GET the screener page (with retries) → extract CSRF token and scan clause
2. POST to /screener/process with the token + clause
3. Parse JSON → extract stock symbols and parse volumes, sorting by volume desc
"""

from __future__ import annotations

import html
import json
import logging
import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.models import ScreenerStock

logger = logging.getLogger(__name__)

_PROCESS_URL = "https://chartink.com/screener/process"
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}


def parse_volume(val: str | int | float) -> int:
    """Parse ChartInk volume field handling K/M/L/Cr suffixes and commas."""
    if not val:
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    
    val_str = str(val).strip().replace(",", "")
    if not val_str:
        return 0
    
    suffix_multipliers = {
        "cr": 10_000_000,
        "m": 1_000_000,
        "l": 100_000,
        "k": 1_000,
    }
    
    for suffix, mult in suffix_multipliers.items():
        if val_str.lower().endswith(suffix):
            try:
                num_part = val_str[:-len(suffix)].strip()
                return int(float(num_part) * mult)
            except ValueError:
                pass
                
    try:
        return int(float(val_str))
    except ValueError:
        return 0


class ChartinkScreener:
    """Fetches the daily stock list from a Chartink screener URL.

    Usage:
        screener = ChartinkScreener(url="https://chartink.com/screener/my-screen")
        symbols_with_volume = screener.fetch_symbols(top_n=50)
        # [('RELIANCE', 1200000), ('TCS', 980000), ...]
    """

    def __init__(
        self,
        screener_url: str,
        scan_clause_override: str = "",
    ) -> None:
        """Initialize with a Chartink screener URL.

        Args:
            screener_url: Full URL to the saved screener page.
            scan_clause_override: If provided, skip extraction and use
                this clause directly. Useful as fallback if page
                structure changes.
        """
        self.screener_url = screener_url
        self.scan_clause_override = scan_clause_override
        self._session = requests.Session()
        self._session.headers.update(_DEFAULT_HEADERS)

    def fetch_symbols(self, top_n: int = 50) -> list[tuple[str, int]]:
        """Fetch today's stock symbols and volumes from the screener.

        Returns:
            List of tuples: [(symbol, volume)] sorted by volume descending.
            Empty list on failure (logged, never raises).
        """
        try:
            stocks = self._fetch_stocks()
            
            # Map stocks to tuple: (symbol, volume), stripping '$' prefix if present
            results: list[tuple[str, int]] = []
            for s in stocks:
                if not s.nsecode:
                    continue
                sym = s.nsecode.strip()
                if sym.startswith("$"):
                    sym = sym[1:]
                results.append((sym, s.volume))
                
            # Sort by volume descending
            results.sort(key=lambda x: x[1], reverse=True)
            
            # Slice to top_n
            sliced = results[:top_n]
            logger.info("Chartink returned %d stocks, sliced to top %d", len(results), len(sliced))
            return sliced
        except Exception:
            logger.exception("Failed to fetch stocks from Chartink")
            return []

    def _fetch_page_with_retry(self, max_retries: int = 3) -> Optional[str]:
        """GET the screener page with retries and exponential backoff."""
        for attempt in range(max_retries):
            try:
                resp = self._session.get(self.screener_url, timeout=15)
                resp.raise_for_status()
                return resp.text
            except Exception as e:
                wait = 2 ** attempt
                logger.warning(
                    "Attempt %d/%d failed to GET Chartink page: %s. Retrying in %ds...",
                    attempt + 1, max_retries, e, wait
                )
                time.sleep(wait)
        return None

    def _fetch_stocks(self) -> list[ScreenerStock]:
        """Internal: fetch and parse screener results."""
        # Step 1: GET the screener page once
        logger.info("Fetching Chartink screener page...")
        html_content = self._fetch_page_with_retry()
        if not html_content:
            raise ValueError("Failed to retrieve Chartink page after all retries")

        # Step 2: Extract CSRF token from the page
        csrf_token = self._extract_csrf_token(html_content)
        if not csrf_token:
            raise ValueError("Could not extract CSRF token from Chartink page")

        # Step 3: Get the scan clause
        scan_clause = self.scan_clause_override or self._parse_scan_clause(html_content)
        if not scan_clause:
            raise ValueError(
                "Could not extract scan_clause from Chartink page. "
                "Set CHARTINK_SCAN_CLAUSE in .env as fallback."
            )

        # Step 4: POST to the process endpoint
        self._session.headers["X-CSRF-TOKEN"] = csrf_token
        self._session.headers["Referer"] = self.screener_url

        response = self._session.post(
            _PROCESS_URL,
            data={"scan_clause": scan_clause},
            timeout=30,
        )
        response.raise_for_status()

        # Step 5: Parse JSON response
        data = response.json()
        raw_stocks = data.get("data", [])
        logger.debug("Raw Chartink response: %d records", len(raw_stocks))

        return [
            ScreenerStock(
                nsecode=row.get("nsecode", ""),
                name=row.get("name", ""),
                close=float(row.get("close", 0)),
                per_chg=float(row.get("per_chg", 0)),
                volume=parse_volume(row.get("volume", 0)),
            )
            for row in raw_stocks
        ]

    def _extract_csrf_token(self, html_content: str) -> Optional[str]:
        """Extract the CSRF meta tag from the page HTML."""
        try:
            soup = BeautifulSoup(html_content, "html.parser")
            meta = soup.find("meta", attrs={"name": "csrf-token"})
            if meta and meta.get("content"):
                return meta["content"]
            logger.warning("CSRF meta tag not found in Chartink page")
            return None
        except Exception:
            logger.exception("Failed to parse CSRF token from page HTML")
            return None

    def _parse_scan_clause(self, html_content: str) -> Optional[str]:
        """Extract the scan_clause from the screener page HTML.

        We try multiple extraction methods on the retrieved page.
        """
        try:
            # Method 0 (primary): Extract 'atlas_query' from JSON data
            # Chartink embeds the scan clause as 'atlas_query' inside a
            # JSON blob stored in a Vue component attribute like
            # :scan-data-json="{ ... &quot;atlas_query&quot;: &quot;...&quot; ... }"
            atlas_match = re.search(
                r'"atlas_query"\s*:\s*"([^"]+)"',
                html.unescape(html_content),
            )
            if atlas_match:
                clause = atlas_match.group(1)
                # Decode any remaining HTML entities (e.g. &#039; → ')
                clause = html.unescape(clause)
                logger.info("Extracted scan_clause from atlas_query")
                return clause

            # Method 1: Look for scan_clause in JavaScript
            patterns = [
                r'scan_clause\s*[=:]\s*["\']((?:[^"\'\\]|\\.)*)["\']\s*',
                r'"scan_clause"\s*:\s*"((?:[^"\\]|\\.)*)"',
                r"scan_clause\s*=\s*encodeURIComponent\(['\"]([^'\"]+)['\"]\)",
            ]
            for pattern in patterns:
                match = re.search(pattern, html_content)
                if match:
                    clause = match.group(1)
                    logger.info("Extracted scan_clause via regex")
                    return clause

            # Method 2: Look in textarea elements
            soup = BeautifulSoup(html_content, "html.parser")
            for textarea in soup.find_all("textarea"):
                text = textarea.get_text(strip=True)
                if text and text.startswith("(") and "latest" in text.lower():
                    logger.info("Extracted scan_clause from textarea")
                    return text

            # Method 3: Look in hidden input fields
            for inp in soup.find_all("input", {"type": "hidden"}):
                if inp.get("id", "").lower().find("scan") >= 0:
                    val = inp.get("value", "")
                    if val:
                        logger.info("Extracted scan_clause from hidden input")
                        return val

            logger.warning("Could not auto-extract scan_clause.")
            return None

        except Exception:
            logger.exception("Error extracting scan_clause")
            return None
