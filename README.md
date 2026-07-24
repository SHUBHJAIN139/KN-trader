# 📊 KN Smart TP SL Trader (v4.0)

> Automated stock signal system that ports a TradingView Pine Script indicator to Python, fetches top volume stocks from Chartink screener, filters signals using EMA Crossovers + ATR TP/SL + Volume confirmation, and logs results to **Google Sheets** and **Telegram**.

[![GitHub Actions Status](https://github.com/SHUBHJAIN139/KN-trader/actions/workflows/daily.yml/badge.svg)](https://github.com/SHUBHJAIN139/KN-trader/actions/workflows/daily.yml)

📱 **[▶️ Click Here to Run Strategy from Any PC or Phone (GitHub Actions Dispatch)](https://github.com/SHUBHJAIN139/KN-trader/actions/workflows/daily.yml)**

---

⚠️ **DISCLAIMER**: This software is for educational purposes only. It does NOT constitute financial advice. Trading Indian equities involves substantial risk of financial loss. Always conduct your own research before trading.

---

## 🏗️ Architecture

```
Chartink Screener ──→ screener.py ──→ Stock List
                                         │
                    ┌────────────────────┘
                    ▼
              NSE Direct API (1d)  ──→  data.py  ──→  OHLCV DataFrames
              Twelve Data API (4h) ──↗       │
                                             ▼
                                      indicator.py ──→ EMA Crossover Signals
                                             │           + ATR TP/SL Levels
                                             ▼
                                       pipeline.py
                                        ┌────┴────┐
                                        ▼         ▼
                                  sheets.py   telegram.py
                                  (Google      (Telegram
                                   Sheets)      Bot)
```

## ✨ Features

- **Pine Script Fidelity** — Exact port of the KN Smart TP SL indicator (EMA 5/13 crossover + ATR-based TP1/TP2/TP3/SL)
- **Dynamic Stock Universe** — Fetches stocks daily from your [Chartink screener](https://chartink.com/screener/trading-view-11042052)
- **Dual Timeframe** — Daily (1d via NSE API) and 4-hour (4h via Twelve Data, resampled from 1h)
- **Google Sheets Output** — Signals written to dated worksheet tabs for easy review
- **Telegram Alerts** — Rich formatted push notifications with entry/SL/TP levels
- **GitHub Actions** — Automated daily runs at 9:00 AM IST (Mon-Fri)
- **Zero TA-Lib** — Manual EMA/ATR using pandas (no C dependencies)

## 📁 Project Structure

```
E:\kn-trader\
├── README.md                          ← You are here
├── requirements.txt                   ← Python dependencies
├── .gitignore                         ← Git exclusions
├── .env.example                       ← Environment template
├── .github/workflows/daily.yml        ← GitHub Actions cron job
├── credentials/.gitkeep               ← Google service account keys
└── src/
    ├── __init__.py                    ← Package marker
    ├── __main__.py                    ← python -m src entry point
    ├── config.py                      ← Env var loader (Pydantic)
    ├── models.py                      ← Pydantic I/O models
    ├── indicator.py                   ← Pine Script → Python port
    ├── data.py                        ← NSE (1d) + Twelve Data (4h)
    ├── screener.py                    ← Chartink scraper
    ├── sheets.py                      ← Google Sheets writer
    ├── telegram.py                    ← Telegram bot notifier
    └── pipeline.py                    ← Main orchestrator + CLI
```

---

## 🚀 Quick Start

### 1. Prerequisites

- **Python 3.12+** (tested with Python 3.12.0)
- **pip** (comes with Python)

### 2. Install Dependencies

```bash
cd E:\kn-trader
E:\python311\python.exe -m pip install -r requirements.txt
```

### 3. Configure Environment

```bash
copy .env.example .env
# Edit .env with your credentials (see setup guides below)
```

### 4. Run (Dry Mode)

```bash
# Daily signals — prints to console, no external services needed
E:\python311\python.exe -m src.pipeline --timeframe 1d --dry-run

# 4-hour signals (requires TWELVE_DATA_API_KEY in .env)
E:\python311\python.exe -m src.pipeline --timeframe 4h --dry-run
```

### 5. Run (Full Mode)

```bash
# With Google Sheets + Telegram output
E:\python311\python.exe -m src.pipeline --timeframe 1d
```

---

## 🔧 Setup Guides

### Telegram Bot Setup

1. Open Telegram, search for **@BotFather**
2. Send `/newbot` and follow the prompts to create your bot
3. Copy the **bot token** → paste into `.env` as `TELEGRAM_BOT_TOKEN`
4. Send any message to your new bot
5. Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
6. Find `"chat":{"id": YOUR_CHAT_ID}` in the JSON response
7. Copy the **chat ID** → paste into `.env` as `TELEGRAM_CHAT_ID`

### Google Sheets Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select existing)
3. Enable **Google Sheets API** and **Google Drive API**
4. Go to **Credentials** → **Create Credentials** → **Service Account**
5. Download the JSON key file → save as `credentials/service-account.json`
6. Copy the service account email (looks like `xxx@xxx.iam.gserviceaccount.com`)
7. Create a Google Sheet named "KN Trader Signals"
8. Share the sheet with the service account email (Editor access)
9. Set `GOOGLE_CREDENTIALS_PATH=credentials/service-account.json` in `.env`

### Twelve Data API Setup (for 4h timeframe)

1. Sign up at [twelvedata.com](https://twelvedata.com/)
2. Get your free API key from the dashboard
3. Set `TWELVE_DATA_API_KEY=your-key-here` in `.env`
4. Free tier: 800 API calls/day, 8 calls/minute

### Chartink Scan Clause (if auto-extraction fails)

The screener URL auto-extracts the scan clause. If it fails:

1. Open your screener URL in Chrome
2. Press F12 → Network tab
3. Click "Run Scan" on the Chartink page
4. Find the `process` POST request
5. Copy the `scan_clause` from the request payload
6. Set `CHARTINK_SCAN_CLAUSE=<your clause>` in `.env`

---

## ⚙️ GitHub Actions Setup

The workflow runs automatically Mon-Fri at 9:00 AM IST.

### Add Repository Secrets

Go to your GitHub repo → Settings → Secrets and variables → Actions:

| Secret | Value |
|--------|-------|
| `TELEGRAM_BOT_TOKEN` | Your Telegram bot token |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |
| `GOOGLE_CREDENTIALS_JSON` | Entire JSON content of service account key |
| `TWELVE_DATA_API_KEY` | Your Twelve Data API key |

### Manual Trigger

You can also trigger the workflow manually from the **Actions** tab → **Run workflow**.

---

## 📐 Pine Script Mapping

| Pine Script | Python (indicator.py) |
|---|---|
| `ta.ema(close, 5)` | `series.ewm(span=5, adjust=False).mean()` |
| `ta.atr(14)` | True Range → `ewm(alpha=1/14, adjust=False).mean()` |
| `ta.crossover(fast, slow)` | `(fast > slow) & (fast.shift(1) <= slow.shift(1))` |
| `ta.crossunder(fast, slow)` | `(fast < slow) & (fast.shift(1) >= slow.shift(1))` |
| `close - atrVal * slAtrMult` | Identical formula (BUY SL) |
| `close + risk * rr1` | Identical formula (BUY TP1) |

### Default Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| EMA Fast | 5 | Fast EMA period |
| EMA Slow | 13 | Slow EMA period |
| ATR Period | 14 | ATR lookback |
| SL Multiplier | 1.5× ATR | Stop-loss distance |
| TP1 R:R | 1.0 | Take-profit 1 risk-reward |
| TP2 R:R | 2.0 | Take-profit 2 risk-reward |
| TP3 R:R | 3.0 | Take-profit 3 risk-reward |

---

## 📱 Sample Telegram Message

```
🟢 BUY Signal: RELIANCE
⏱ Timeframe: 1d
📅 Date: 2026-07-01

📊 Entry: ₹2,450.50
🛑 SL: ₹2,412.30 (1.56%)
🎯 TP1: ₹2,488.70 (+1.56%)
🎯 TP2: ₹2,526.90 (+3.12%)
🎯 TP3: ₹2,565.10 (+4.68%)

📐 ATR: 25.47 | Risk: ₹38.20
```

---

## 🛡️ Legal Disclaimer

This software is provided "AS IS" without warranty of any kind. The signals generated are based on technical analysis (EMA crossover) and should NOT be treated as financial advice. The developers are not responsible for any financial losses incurred from using this software. Past performance does not guarantee future results. Always consult a qualified financial advisor.

---

## 📝 License

This project is for educational purposes. Built by a BTech AI/ML student as a learning project.
