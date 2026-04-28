---
name: skill-quant-trading
description: Guidelines and architectural philosophy for building the Solo-Quant trading platform. Focuses on multi-indicator confluence, dual-engine strategy, and strict quantitative engineering principles.
---

# Quantitative Trading Skill — Solo-Quant Core Philosophy

This document serves as the **Constitution** for AI Agents and developers working on the Solo-Quant platform. It defines the timeless trading philosophies, engineering principles, and data integrity rules. 

> **Rule of Thumb**: This file dictates *HOW* we think and code. For details on *WHAT* the current active codebase contains (e.g., specific indicators used right now, immediate next tasks), always refer to `AI_HANDOFF.md`.

---

## 1. Trading Strategy Philosophy

### 1.1 Multi-Indicator Confluence (共振法則)
Single indicators inevitably produce false signals. Our system *only* executes trades when multiple, mathematically independent indicators (e.g., Sentiment, Momentum, Structure, Volume) align simultaneously.
*   **Actionable Rule**: Never trigger a trade based on a single condition. Always use a scoring or weighted logic system to evaluate confluence across different market dimensions.

### 1.2 Dual-Engine Architecture (雙引擎架構)
Markets operate in two distinct regimes: **Ranging (盤整)** and **Trending (趨勢)**. A single logic engine will fail in one of these regimes.
*   **Mean Reversion Engine**: Designed for ranging markets or deep pullbacks. Buys oversold dips, sells overbought rips.
*   **Trend Breakout Engine**: Designed for strong, unilateral trends where pullbacks do not occur. Buys breakouts of structural highs combined with momentum surges.
*   **Regime-Awareness**: The system must actively detect the current regime (e.g., via ADX, Moving Average stacking) and dynamically route signal evaluation to the appropriate engine.

### 1.3 Dynamic Asset Profiles (自適應閾值)
Different asset classes (Majors vs. Altcoins vs. Memes) possess fundamentally different volatilities and baselines. 
*   **Actionable Rule**: Thresholds must be dynamic. The backend architecture must support loading distinct parameter profiles based on the asset being analyzed.

---

## 2. Quantitative Engineering Standards

### 2.1 Data Integrity & Look-Ahead Bias Prevention (零未來函數)
The most fatal error in quantitative trading is leaking future data into historical calculations.
*   **Strict Rule**: Absolutely prohibit `shift(-1)` or any operation that looks forward in time. All indicator calculations and regime detections must be strictly `causal` (using only data at $t$ or $t-n$).
*   **Implementation**: Always use pandas `.rolling()` windows or strict historical slicing. 

### 2.2 Indicator Warm-Up Parity (暖機對齊原則)
Path-dependent indicators (like EMA, RSI, CVD) yield different values depending on when the calculation started.
*   **Strict Rule**: The backtest engine and the live dashboard *must* compute indicators over the exact same historical window (e.g., always fetching a fixed 1000 candles). Never crop the dataset *before* calculating indicators.

### 2.3 Dirty Data Handling
Crypto APIs frequently return anomalies (flash crashes, missing ticks, `NaN` values).
*   **Actionable Rule**: Explicitly handle missing data (e.g., `ffill()`) and clamp extreme mathematical outliers (especially before feeding data into standard deviation models like Z-Scores) to prevent cascading failures.

---

## 3. System Architecture & Coding Standards

### 3.1 Two Distinct Operating Modes
The platform supports two fundamentally different tactical approaches:
1.  **Grid Strategy (網格)**: For capturing spread in ranging, oscillating markets.
2.  **Signal-Driven Strategy (信號)**: For directional swing trading managed by explicit Stop Loss (SL), Take Profit (TP), and Trailing Stops.

### 3.2 Backend: Performance & Typing
- **FastAPI / Python**: 
  - Use `async`/`await` for all I/O bound operations (e.g., exchange API requests).
  - Use **Pydantic** to strictly validate all API inputs/outputs.
- **Vectorization**: 
  - Avoid `for` loops and `.iterrows()` for indicator mathematics. Rely entirely on vectorized operations (Pandas/NumPy/Polars) for massive performance gains. *Note: For loops are acceptable in the backtesting simulator loop where chronological state management (e.g., trailing stops) is required.*

### 3.3 Frontend: Next.js & Lightweight Charts
- **Timezone Awareness**: Financial charting libraries often default to UTC. Ensure all incoming timestamps are properly parsed and aligned to the user's Local Time before rendering to prevent UI/Backend log mismatches.
- **Component Isolation**: Chart components must be pure. Complex state (like data fetching) belongs in parent hooks or pages, passing clean data arrays into the charting elements.

---

## 4. Backtesting & Risk Validation

No algorithm goes to production without rigorous validation.

### 4.1 Required Metrics
- **Win Rate & Total Trades**: Statistical significance is mandatory.
- **Expected Value (EV)**: Must mathematically factor in realistic assumptions.
- **Max Drawdown**: The ultimate test of strategy survival.
- **Sharpe/Sortino Ratio**: Risk-adjusted performance.

### 4.2 Cost Realism
*   **Strict Rule**: A backtest that ignores exchange fees (e.g., Taker fees) and slippage is a fantasy. All profitability metrics must be net of estimated real-world execution costs.

---

## 5. Standard Operating Procedure (SOP) for Adding New Indicators
When adding a new indicator to the system, follow this strict lifecycle:
1. **Mathematical Validation**: Implement the raw math in the backend `core/` module. Validate against edge cases (zero division, NaNs).
2. **Confluence Integration**: Wire the output into the `calculate_confluence_signals` engine. Determine if it belongs to the Reversion or Breakout track.
3. **API Serialization**: Expose the necessary arrays via the FastAPI response model.
4. **UI Representation**: Build the visualization layer in the frontend chart components, ensuring color consistency (e.g., Green = Bullish/Up, Red = Bearish/Down).
