# Solo-Quant Project Context & AI Handoff

This document is the **Context Buffer** for AI Agents. It defines how the system works *right now*, the critical rules to avoid regressions, and the immediate next goal.
*Note: For historical updates, please refer to `CHANGELOG.md`.*
*Note: For general domain knowledge, trading philosophy, and coding standards, ALWAYS review `@[.github/skills/skill-quant-trading/SKILL.md]`.*

---

## 1. Project Overview & Tech Stack
**Solo-Quant** is a cryptocurrency algorithmic trading platform focused on Multi-indicator Confluence Analysis and Signal-Driven Backtesting.
- **Backend**: Python 3.11, FastAPI, Pandas, NumPy, CCXT. (Run via `docker compose up api`)
- **Frontend**: Next.js 16 (App Router), TypeScript, Tailwind CSS, Lightweight Charts. (Run via `docker compose up web`)
- **Architecture**: Dual-mode (Grid-based Legacy vs. Signal-Driven Modern).

---

## 2. Current Architecture (The "Now")

### 2.1 The Signal-Driven Engine (v2)
The core of the system relies on generating `Bullish` and `Bearish` markers from `IndicatorEngine`, which are then parsed by the `SignalBacktester` to execute trades.

- **Data Flow**: `get_market_data(limit=1000)` fetches OHLCV from DB -> `IndicatorEngine` calculates arrays -> UI renders `AdvancedChart` / Backend runs `SignalBacktester`.
- **Dual-Engine Logic**: Evaluation combines a **Reversion Engine** (RSI, BB, EMA, Funding) for ranging regimes, and a **Breakout Engine** (Donchian Channels, MACD, CVD) for catching strong trend continuations.
- **Position Lifecycle**: `api/quant/position.py` manages Stop Loss -> Take Profit -> Trailing Stop (evaluated in this exact order per bar).
- **Regime-Adaptive Thresholds**: The system detects the current market regime (`trending up`, `trending down`, `ranging`). In a trend, it automatically relaxes the thresholds of Mean-Reversion indicators (like RSI and EMA) to buy shallow dips.
- **Visuals**: The UI features an `AdvancedChart` with 7 layers: Main Price, RSI, CVD, Open Interest, Funding Rate, Market Pulse, and a **Regime Chart** (Emerald for Uptrend, Red for Downtrend, Amber for Ranging). Breakout signals are distinctly visualized (e.g., Rocket 🚀 icon, Blue/Orange colors) separate from reversion signals.

---

## 3. Crucial Principles & Gotchas (READ BEFORE CODING)
To prevent regressions, **ALL future AI Agents MUST adhere to these rules**:

1. **Indicator Path-Dependence Parity**:
   - *Gotcha*: Backtest and Dashboard used to show different signals because the backtest only fetched the `duration_days` worth of candles, altering the warmup of EMA/CVD.
   - *Rule*: **ALWAYS** fetch `limit=1000` candles for indicator calculation, even if the backtest only runs on the last 30 days. Crop the data *after* calculation.
2. **Strict Time Alignment (No Look-Ahead Bias)**:
   - *Gotcha*: Calculating regime on the entire array leaks future data into the past.
   - *Rule*: Any new indicator or regime detection MUST use `.rolling(window)` or strictly iterate using only index `<= current_bar`.
3. **Local Time vs UTC**:
   - *Gotcha*: Lightweight charts defaults to UTC, causing a 1-hour mismatch with the backend trade logs.
   - *Rule*: All UI times must be explicitly parsed as Local Time before injecting into charts or tables.
4. **Regime Chart Constraints**:
   - *Gotcha*: The `AdvancedChart.tsx` Regime Chart is a *constant height* histogram (value is always 1). It relies purely on the `color` attribute to convey state. Do not attempt to map Y-values for regime states.

---

## 4. Current Development Focus (The "Next")
### Goal: Event-Driven Signal Notification System (Telegram)

**Context**: The Dual-Engine (Reversion + Breakout) is complete and the frontend displays both signal types. The next priority is to build a **real-time notification pipeline** so the user receives Telegram alerts the moment a new signal appears, without needing to stare at the dashboard.

**Architecture Decision**: No Kafka/RabbitMQ. The system is a single-user trading desk with signal frequency of a few per hour at most. The entire notification system will be **embedded within the existing FastAPI container** using `APScheduler` + direct Telegram Bot API calls.

### 4.1 Implementation Phases

#### Phase 1: Telegram Bot Notification (Core)
1. **Create Telegram Bot**: Register a bot via @BotFather, obtain `BOT_TOKEN`.
2. **Obtain Chat ID**: Send a message to the bot, then fetch `CHAT_ID` via `https://api.telegram.org/bot<TOKEN>/getUpdates`.
3. **New Module — `api/core/notifier.py`**: Encapsulate `send_telegram_message(text)` using `httpx` (async HTTP POST to Telegram Bot API).
4. **Environment Variables**: Store `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`, inject via Docker Compose `environment`. **Never commit tokens to Git.**

#### Phase 2: Scheduled Signal Scanner
1. **Integrate APScheduler**: Initialize the scheduler inside FastAPI's `lifespan` event (on startup). Register a periodic job that runs every **15 minutes**.
2. **New Module — `api/core/signal_scanner.py`**: Contains `scan_and_notify()`:
   - Iterates over all monitored symbols (configurable list, default: all enabled symbols).
   - Calls the existing `get_market_data()` → `IndicatorEngine.calculate_confluence_signals()` pipeline (respecting the 1000-candle warmup rule).
   - Compares signal timestamps against `last_notified_time` (stored in-memory or DB) to **deduplicate** — only new signals are dispatched.
   - Formats the notification message and calls `send_telegram_message()`.
3. **Message Format**:
   ```
   Buy (Reversion):  🟢⬆ [BTC/USDT] Reversion BUY @ $94,500 | 3/7 CVD↑+FR-(OI↑)+BB↑
   Buy (Breakout):   🟢⬆ [BTC/USDT] Breakout BUY @ $95,200 | 🚀 MACD↑+CVD↑
   Sell (Reversion):  🔴⬇ [BTC/USDT] Reversion SELL @ $96,100 | 4/7 Z+FR++RSI72+EMA↓
   Sell (Breakout):   🔴⬇ [BTC/USDT] Breakdown SELL @ $93,800 | 🚀 MACD↓+CVD↓
   ```

#### Phase 3: Frontend Notification Config Panel
1. **New API Endpoints**:
   - `GET /notifications/config` — Returns current notification settings (enabled symbols, on/off state).
   - `POST /notifications/config` — Updates notification settings.
2. **Frontend UI**: Add a Notification Settings section (e.g., in a Settings page or a dropdown in the header) where the user can:
   - Toggle notifications on/off globally.
   - Select which symbols to monitor (default: all enabled).
   - (Future) Adjust scan frequency.

#### Phase 4 (Optional / Future): Frontend WebSocket Push
1. **WebSocket Endpoint**: `ws://localhost:8000/ws/signals` for real-time push to the frontend UI (e.g., toast notifications or a signal feed panel).
2. This is **not required for Phase 1-3** — the Telegram bot is the primary notification channel.

### 4.2 Gotchas for This Feature
- **Deduplication is critical**: Without tracking `last_notified_time`, every 15-minute scan would re-send all historical signals. Use a simple in-memory dict keyed by `(symbol, timeframe)` → `last_signal_timestamp`.
- **Telegram Rate Limits**: ~30 msgs/sec per chat. Not a concern for our volume, but wrap calls in `try/except` for resilience.
- **Respect Indicator Warmup Parity**: The scanner MUST call `get_market_data(limit=1000)`, identical to the Dashboard. Never shortcut with fewer candles.

---

## 5. AI Agent Prompt (Copy-Paste to start next session)
*Copy the prompt below to hand off this exact context to the next AI session:*

> 「請扮演一位資深的 Python 後端工程師。請先閱讀 `AI_HANDOFF.md` 以了解專案架構與避坑規則。
> 
> 我們目前的進度在第 4 節『Event-Driven Signal Notification System』。目標是建立一套 Telegram 通知系統，當新的交易信號出現時，自動推送到我的 Telegram。
> 
> 請執行以下任務：
> 1. 建立 `api/core/notifier.py`，封裝 Telegram Bot API 的訊息發送（使用 `httpx` 異步 POST）。Token 和 Chat ID 從環境變數讀取。
> 2. 建立 `api/core/signal_scanner.py`，實作 `scan_and_notify()` 函式。它必須重用現有的 `get_market_data(limit=1000)` + `IndicatorEngine` 管線來計算信號，並且只通知新出現的信號（透過記錄 `last_notified_time` 來去重）。
> 3. 在 FastAPI 的 `lifespan` 事件中整合 `APScheduler`，每 15 分鐘自動執行一次掃描。
> 4. 通知訊息格式範例：`🟢⬆ [BTC/USDT] Breakout BUY @ $95,200 | 🚀 MACD↑+CVD↑`。
> 5. 更新 `docker-compose.yml` 加入 `TELEGRAM_BOT_TOKEN` 和 `TELEGRAM_CHAT_ID` 環境變數。
> 6. 請務必遵循第 3 節的避坑規則，特別是 Indicator Warmup Parity（必須使用 1000 根 K 線暖機）。」
