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
### Goal: Backtest Parameter Tuning & Risk Management Refinement

**Context**: The Dual-Engine (Reversion + Breakout) is now complete, and the frontend dynamically displays both signal types accurately. However, the default backtesting parameters (Stop Loss, Take Profit, Trail %, Trail Activation %) are too tight for Breakout strategies (which typically require larger ATR / breathing room), causing trades to be prematurely stopped out by normal market noise (whipsaws).

**Execution Focus**:
1. **Parameter Optimization / Preset Profiles**: Determine optimal risk management presets for "Mean-Reversion" vs "Breakout" trades. 
2. **Backtest Panel Enhancements**: Perhaps introduce risk management presets directly in the UI (e.g., "Conservative" vs "Trend Following") which load distinct SL/TP/Trail ratios.
3. **Analytics Tuning**: Increase `Trail %` and `Trail Activation` in default tests to validate that Breakout signals effectively capture major trend continuations without early stop-outs.

---

## 5. AI Agent Prompt (Copy-Paste to start next session)
*Copy the prompt below to hand off this exact context to the next AI session:*

> 「請扮演一位資深的量化交易演算法工程師。請先閱讀 `AI_HANDOFF.md` 以了解專案架構。
> 
> 我們目前的進度在第 4 節『Backtest Parameter Tuning & Risk Management Refinement』。我們的雙引擎 (Dual-Engine) 信號機制已順利上線，但在執行回測時，預設的 trailing stop loss 過於緊繃，導致 Breakout 的訊號經常在小幅洗盤時被提早洗出場。
> 
> 請執行以下任務：
> 1. 請檢查並調整 `SignalBacktester` 或前端 UI 預設帶入的風控參數（例如：放寬 Breakout 的 SL 和 Trail %）。
> 2. （如果適用）在前端面板加入『快速載入風控預設 (Presets)』的選項，例如分成『保守回歸』與『擁抱順勢』。
> 3. 確認每一次調整後，都保持回測引擎的 `Position Lifecycle` 順序正確 (SL -> TP -> Trailing Stop)，並在圖表上驗證策略的存活率與盈虧比。」
