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

### 2.2 Signal Notification System (Telegram)
An event-driven notification pipeline embedded within the FastAPI container. No external message brokers (Kafka/RabbitMQ).

- **Modules**: `api/core/notifier.py` (Telegram Bot API via `httpx`) + `api/core/signal_scanner.py` (scan logic + dedup).
- **Schedule**: `APScheduler` with `CronTrigger(minute="0,15,30,45")` — scans at fixed clock times, 5-second delay between symbols to avoid OKX rate limiting.
- **Dedup**: In-memory `_last_notified` dict tracks the latest notified signal timestamp per `(symbol, timeframe)`. Combined with a **1-hour recency window** to prevent notification floods on container restart.
- **Message Format**: `🟢⬆ 2026/05/05 17:00 [BTC/USDT] Reversion BUY @ $94,500 | 3/7 CVD↑+FR-+BB↑`
- **Config API**: `GET/POST /notifications/config` (toggle on/off, select symbols), `POST /notifications/test`, `POST /notifications/scan-now`.
- **Env Vars**: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env` (injected via `docker-compose.yml`). **Never commit tokens to Git.**

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
5. **Signal Scanner Warmup Parity**:
   - *Gotcha*: The signal scanner (`signal_scanner.py`) must call `get_market_data(limit=1000)` — the exact same pipeline as the Dashboard — to ensure indicator warmup is identical.
   - *Rule*: Never shortcut the scanner with fewer candles or a different code path.

---

## 4. Current Development Focus (The "Next")
### Goal: Frontend Notification Config Panel & Backtest Parameter Tuning

**Context**: The backend notification system (Telegram) is fully operational (Phase 1 & 2 complete). The next priorities are:

### 4.1 Frontend Notification Config Panel (Phase 3)
Build a UI panel so the user can manage notification settings without calling raw API endpoints.
1. **Frontend UI**: Add a Notification Settings section (e.g., in a Settings page or a dropdown/modal in the header) where the user can:
   - Toggle notifications on/off globally.
   - Select which symbols to monitor (default: all enabled).
   - View current scan schedule.
   - Send a test notification.
2. **Integration**: Connect to existing `GET/POST /notifications/config` and `POST /notifications/test` endpoints.

### 4.2 Backtest Parameter Tuning & Risk Management Refinement
The default backtesting parameters (SL, TP, Trail %, Trail Activation %) are too tight for Breakout strategies, causing trades to be prematurely stopped out by normal market noise.
1. **Parameter Optimization / Preset Profiles**: Determine optimal risk management presets for "Mean-Reversion" vs "Breakout" trades.
2. **Backtest Panel Enhancements**: Introduce risk management presets in the UI (e.g., "Conservative" vs "Trend Following") which load distinct SL/TP/Trail ratios.

### 4.3 (Optional / Future): Frontend WebSocket Push
1. **WebSocket Endpoint**: `ws://localhost:8000/ws/signals` for real-time push to the frontend UI (toast notifications or signal feed panel).
2. Not required for Phase 3 — Telegram bot is the primary notification channel.

---

## 5. AI Agent Prompt (Copy-Paste to start next session)
*Copy the prompt below to hand off this exact context to the next AI session:*

> 「請扮演一位資深的全端工程師。請先閱讀 `AI_HANDOFF.md` 以了解專案架構與避坑規則。
> 
> 我們目前的進度在第 4 節。後端的 Telegram 信號通知系統已經完成並上線運作（Phase 1 & 2），接下來需要完成兩個任務：
> 
> **任務一：前端通知設定面板 (Phase 3)**
> 1. 在前端新增一個 Notification Settings 的 UI 區域（可以是 Settings 頁面或 Header 內的下拉選單）。
> 2. 串接現有的 `GET/POST /notifications/config` 和 `POST /notifications/test` API。
> 3. 讓使用者可以開關通知、選擇要監控的幣種、發送測試通知。
> 
> **任務二：回測風控參數調校**
> 1. 檢查 `SignalBacktester` 的預設風控參數，針對 Breakout 策略放寬 SL 和 Trail %。
> 2. 在前端回測面板加入『快速載入風控預設』選項（例如『保守回歸』與『順勢突破』）。
> 3. 確認 Position Lifecycle 順序正確 (SL -> TP -> Trailing Stop)。」

