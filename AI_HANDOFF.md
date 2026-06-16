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
- **Message Format**: `sendPhoto` with a TradingView-style 168-hour candlestick chart (showing EMA and precise signal markers) + Caption: `🟢⬆ 2026/05/05 17:00 [BTC/USDT] Reversion BUY @ $94,500 | 3/7 CVD↑+FR-+BB↑`
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
6. **API Contract Validation (Frontend ↔ Backend)**:
   - *Gotcha*: The frontend `NotificationConfig` interface used `symbols` while the backend returned `monitored_symbols`, causing a runtime crash (`Cannot read properties of undefined`).
   - *Rule*: Before deploying any new frontend ↔ backend integration, **always verify the API response shape** by checking the backend endpoint code or calling `curl` against it. TypeScript interfaces MUST mirror the exact field names returned by FastAPI. When in doubt, run `docker exec solo-quant-api python3 -c "from api.core.signal_scanner import get_notification_config; print(get_notification_config())"` (or equivalent) to confirm.

---

## 4. Current Development Focus (The "Next")
### Goal: Signal Quality — Major Trend Inflection Point Detection

**Context**: Phase 3 is complete. Phase 4 Layer 1+2 is **complete** — structural inflection point indicators have been implemented, deployed, and validated.

### 4.1 Completed (Phase 3) ✅
- `NotificationSettingsModal.tsx` — toggle notifications, select symbols, send test.
- Backtest presets: "保守回歸" (SL 2%, TP 4%, Trail 1.5%) and "順勢突破" (SL 4%, TP 10%, Trail 3%).
- Position Lifecycle confirmed correct: SL → TP → Trailing Stop.
- **Telegram Notification Chart**: Notifications now include a TradingView-style 168-hour candlestick chart (with EMA lines and matching visual markers for Reversion/Breakout) to provide immediate context without opening the dashboard.

### 4.2 Phase 4: Structural Indicators ✅
The primary goal is **finding price lows and highs within major trends** — not maximizing signal quantity.

#### 4.2.1 Completed (Layer 1 + Layer 2) ✅
Two new structural indicators added to `IndicatorEngine.calculate_confluence_signals()` (v5 → v6):

1. **Layer 1 — Capitulation Detector (`CAP↑`/`CAP↓`)**:
   - Detects OI crash from recent peak (≥10% drop) + CVD accumulation in one direction + price stabilization.
   - Bullish: OI crashed + CVD negative (selling) + price stopped falling → liquidation exhaustion = bottom.
   - Bearish: OI crashed + CVD positive (buying) + price stopped rising → blow-off top = top.
   - Weight: 1.5 points, `Structure` group.

2. **Layer 2 — CVD Divergence (`DIV↑`/`DIV↓`)**:
   - Bullish: Price makes Lower Low but CVD makes Higher Low → selling pressure exhaustion.
   - Bearish: Price makes Higher High but CVD makes Lower High → buying pressure exhaustion.
   - Weight: 1.5 points, `Structure` group.

- Signal text updated `/7` → `/10`. 
- **Frontend**: Dashboard modals (`IndicatorsInfoModal.tsx`, `SignalSettingsModal.tsx`) and chart tooltips updated to reflect the v6 scoring logic and the new `Structure` dimension.
- **Validated**: 4 DIV signals detected (avg score 3.9 vs non-structural avg 3.4). Frontend dashboard renders correctly.

#### 4.2.2 Phase 5: Signal Quality — Completed ✅

- **Layer 3 — Multi-Timeframe Confirmation (`[4h✓]` tag)**: 1h Reversion signals are now filtered by 4h regime direction.
  - **Loose mode**: Only blocks when 4h is `trending + direction=down` (blocks BUY) or `trending + direction=up` (blocks SELL). Neutral 4h regimes pass through.
  - Breakout signals are **exempt** from MTF filter (already aligned to trend).
  - Toggle: `enable_mtf_filter` param (default `False`). UI toggle in `SignalSettingsModal.tsx` with `[Layer 3]` badge.
  - When active, signal text shows `[4h✓]` tag: `⚡(2G) 3.5/10 [R][4h✓] RSI30+CVD↑`.
  - 4h data fetched concurrently in the existing `ThreadPoolExecutor`, adds ~0 extra latency.
  - `IndicatorEngine.calculate_confluence_signals()` upgraded to **v7**.

#### 4.2.3 Future Layers (Phase 6 — Next)
- **Layer 4 — Orderbook Liquidity Imbalance**: Inspired by CoinKarma LIQ. Requires orderbook snapshot collection mechanism (periodic DB writes).
- **Do NOT lower thresholds for quantity**: Signal quality > signal quantity. Only adjust with backtest evidence.

### 4.3 (Optional / Future): Frontend WebSocket Push
1. **WebSocket Endpoint**: `ws://localhost:8000/ws/signals` for real-time push.
2. Not a priority — Telegram bot is the primary notification channel.

---

## 5. AI Agent Prompt (Copy-Paste to start next session)
*Copy the prompt below to hand off this exact context to the next AI session:*

「請扮演一位資深的全端工程師及加密貨幣分析師。請先閱讀 `SKILL.md` 與 `AI_HANDOFF.md` 以了解專案架構、核心理念與避坑規則。

我們目前的進度在第 4 節。Phase 5 Layer 3（多時間框架共振）已完成，`enable_mtf_filter` 參數已整合至後端 v7 IndicatorEngine 與前端 UI。

**任務：信號品質持續優化 (Phase 6)**
1. 持續觀察 MTF 過濾器（Layer 3）在實際行情中的表現，收集實戰數據，對比 MTF on/off 的回測勝率差異。
2. 若 MTF 效果顯著，可考慮讓 Signal Scanner 也可選擇性開啟 MTF 過濾（目前 Scanner 不過濾）。
3. 若有需要，可實作 Layer 4（Orderbook LIQ）：需要先建立訂單簿快照收集機制（定期寫入 DB）。
4. 遵守 `SKILL.md` Section 4, Section 5 與 Section 6 的 SOP。
5. 任何指標或門檻調整必須用 Signal Backtester 驗證。」


