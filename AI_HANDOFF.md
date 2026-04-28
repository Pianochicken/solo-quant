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
- **Position Lifecycle**: `api/quant/position.py` manages Stop Loss -> Take Profit -> Trailing Stop (evaluated in this exact order per bar).
- **Regime-Adaptive Thresholds**: The system detects the current market regime (`trending up`, `trending down`, `ranging`). In a trend, it automatically relaxes the thresholds of Mean-Reversion indicators (like RSI and EMA) to buy shallow dips.
- **Visuals**: The UI features an `AdvancedChart` with 7 layers: Main Price, RSI, CVD, Open Interest, Funding Rate, Market Pulse, and a **Regime Chart** (Emerald for Uptrend, Red for Downtrend, Amber for Ranging).

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
### Goal: Trend-Following Breakout Engine

**Context**: The current 7 indicators (RSI, BB, EMA distance, etc.) are deeply rooted in **Mean Reversion**. Even with adaptive thresholds, they fail to generate buy signals during extreme, non-pullback bull runs (e.g., 66k -> 78k) because they constantly read "overbought".

**Execution Focus**:
1. **New Trend Indicators**: Implement **Donchian Channels** (20-period highest high) and **MACD** in `api/core/indicators.py`.
2. **Dual-Engine Logic**: Refactor `calculate_confluence_signals`.
   - Engine A: The existing Reversion logic.
   - Engine B (New): If `regime == 'trending'` and `direction == 'up'`, and price breaks the Donchian upper band with rising MACD + CVD, immediately yield a Buy signal (bypassing RSI overbought checks).
   - Mark the signal dict with `strategy_type: 'reversion' | 'breakout'`.
3. **Frontend Visualization**: Update `AdvancedChart.tsx` to render the Breakout signals with a different icon/shape (e.g., a Rocket 🚀 or a distinct color) to distinguish them from Reversion arrows.

---

## 5. AI Agent Prompt (Copy-Paste to start next session)
*Copy the prompt below to hand off this exact context to the next AI session:*

> 「請扮演一位資深的量化交易演算法工程師。請先閱讀 `AI_HANDOFF.md` 以了解專案架構與避坑規則。
> 
> 我們目前的進度在第 4 節『Trend-Following Breakout Engine』。目前系統在強勢多頭中缺乏進場點，因為現有指標完全偏向均值回歸。
> 請執行以下任務：
> 1. 在 `api/core/indicators.py` 中實作唐奇安通道 (Donchian Channel) 與 MACD 指標。
> 2. 在信號判定迴圈中加入獨立的『順勢突破 (Breakout)』引擎：在 Uptrend Regime 中，只要價格突破 20T 高點且 MACD 動能向上，即產生類型為 `breakout` 的 Buy 訊號。
> 3. 請確保這些指標計算沒有未來函數 (Look-ahead bias)，並能通過現有的 pytest 單元測試。
> 4. 在前端圖表 (`AdvancedChart.tsx`) 中，將這些新的『突破信號』與原本的『抄底信號』用不同樣式區分開來（例如使用不同形狀或顏色）。」
