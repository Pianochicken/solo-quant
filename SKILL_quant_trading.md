---
name: Quantitative Trading Development
description: Guidelines for building a crypto trading platform focused on finding profitable buy/sell signals through multi-indicator confluence analysis.
---

# Quantitative Trading Skill — SoloQuant

## Core Objective: Finding Profitable Buy/Sell Points

Every indicator, architecture choice, and UI decision serves ONE purpose: **enter and exit trades at the right time to profit.** Always make development decisions with this goal in mind.

---

## 1. Signal System: Multi-Indicator Confluence

### Core Principle
Single indicators produce false signals. Only trade when **multiple independent indicators agree on the same direction.** Our system requires **≥ 3 out of 4 indicators to agree** before emitting a signal.

### The Four Indicators

| Indicator | What It Measures | Bullish Condition | Bearish Condition |
|-----------|-----------------|-------------------|-------------------|
| **LSUR Z-Score** | Position crowding | Z ≤ -1.5 (crowded shorts → squeeze up) | Z ≥ 1.5 (crowded longs → liquidation) |
| **CVD Momentum** | Active buy/sell pressure | 3-bar delta > 0 (buying increasing) | 3-bar delta < 0 (selling increasing) |
| **OI Percentile** | Market leverage level | ≥ 75% (high leverage = fuel for short squeeze) | ≥ 75% (high leverage = fuel for liquidation) |
| **Funding Rate** | Market sentiment bias | < -0.005% (panic capitulation) | > 0.015% (excessive greed) |

### Signal Logic Flow

```
Each candle →
  Collect 4 indicator values →
    Apply Dynamic Asset Profile (Adjust thresholds based on asset type: BTC vs ALTs) →
    Check each against threshold →
      Calculate confluence score (0~4) →
        Score ≥ 3 → Emit buy/sell marker
        Score < 3 → No marker
```

### Dynamic Asset Profiles (Asset-Specific Tuning)
Different asset classes exhibit different baseline metrics. For example, Altcoins (HYPE/CC) naturally have higher baseline funding rates and higher volatility compared to Majors (BTC/ETH).
*   **Rule**: Thresholds must dynamically scale based on the asset. Do not use BTC funding rate thresholds for Memecoins, as it will result in constant false "overheated" signals.

### Improving Signal Accuracy (Priority Order)
1. **Tune thresholds**: Tighten/loosen individual trigger conditions (e.g., Z from 1.5 → 2.0)
2. **Add new indicators**: Introduce independent data sources (e.g., liquidation data, on-chain metrics), update threshold
3. **Improve data quality**: Ensure sufficient history, update frequency, no missing values
4. **Backtest**: Every change must be validated — compare win rate and EV before/after

> **Rule**: Never lower thresholds just because "there aren't enough signals." Fewer good trades > many bad trades.

---

## 2. Indicator Development Standards

### Adding a New Indicator
1. **Define purpose**: What market dimension does it measure? Is it already covered?
2. **Confirm data source**: Is the API stable? Enough history? Rate limits?
3. **Implement calculation**: Add static method in `IndicatorEngine` (`indicators.py`)
4. **Integrate into confluence**: Add scoring condition in `calculate_confluence_signals()`
5. **Frontend chart**: Add corresponding sub-chart in `AdvancedChart.tsx`
6. **Add InfoTooltip**: Chinese explanation next to the label for user understanding

### Key Indicator Concepts
- **OI cannot distinguish long vs short**: Every contract has a buyer AND seller. Use LSUR/CVD/FR for direction.
- **OI percentile uses daily data**: Regardless of chart timeframe, percentile always uses daily OI (sufficient history).
- **CVD shows real money flow**: More direct than OI for detecting one-sided pressure.
- **Z-Score is mean-reversion**: Greater deviation → higher probability of reversion.

---

## 3. Chart Visualization: Make Signals Obvious

### Price Chart (Main)
- Candlesticks + confluence markers (⚡ arrows)
- Green up arrow = bullish confluence | Red down arrow = bearish confluence
- Marker text shows which indicators triggered (e.g., `⚡3/4 Z+CVD↑+FR-`)

### Sub-Panes
Each indicator has its own small chart for visual context:
- **CVD**: Cumulative line (yellow), rising = buyers dominate
- **OI**: Histogram (green/red), green = OI increase, red = decrease
- **Funding Rate**: Histogram (green/red), positive = longs pay, negative = shorts pay

### Right Panel (Sentiment Sentinel)
- LSUR Z-Score current value + status text
- EMA Trend state (Uptrend / Downtrend / Neutral)
- RSI (14) current value + status
- OI Percentile (rolling 90-day rank)

### Design Rules
- All indicator labels have ⓘ InfoTooltip (Chinese explanation)
- Color consistency: green = bullish/increase, red = bearish/decrease
- Format large numbers with `toLocaleString()`

---

## 4. System Architecture

### Three-Layer Separation
```
Data Layer (api/core/fetcher.py)
  ↓ Normalized data
Strategy Layer (api/core/indicators.py)
  ↓ Signals + indicator results
API Layer (api/main.py)
  ↓ JSON Response
Frontend (web/components/AdvancedChart.tsx)
```

### API Rate Limiting
- OKX has rate limits (~20 req/2s)
- Add `time.sleep(0.5)` between paginated requests
- Cap max pages (CVD: 5, OI: 3)

### Data Alignment
All indicator data must be time-aligned with price candles before confluence:
```python
pd.merge_asof(price_df, indicator_df, on='time', direction='backward')
```

---

## 5. Signal System ↔ Grid Trading Relationship

> **Signal system = Strategic judgment** (Should we trade? What direction?)
> **Grid trading = Tactical execution** (Once decided, how to capture spread?)

### Why They Must Be Linked

Grid trading profits from **range-bound oscillation**. During strong trends:

| Market State | Grid Behavior | Risk |
|-------------|--------------|------|
| Range-bound | Normal buy low / sell high | ✅ Steady profit |
| Strong downtrend | Keeps buying (catching knives) | ❌ Accumulates losses |
| Strong uptrend | Keeps selling (misses rally) | ⚠️ Opportunity cost |

**Confluence signals should act as the grid's gatekeeper** — telling it when to pause and when to run.

### Signal → Grid Operating Rules

```
Bearish confluence (⚡ bearish, score ≥ 3)
  → Pause grid or reduce capital → Wait for market to cool

Bullish confluence (⚡ bullish, score ≥ 3)
  → OK to start/restart grid → Range-bound uptrend is ideal

No signal (neutral)
  → Grid runs normally

OI percentile extreme (> 90%)
  → High volatility risk → Consider reducing capital or pausing
```

### Three Integration Strategies (Simple → Advanced)

**1. Switch Mode (recommended starting point)**
- Bearish signal → Stop grid
- No signal / bullish → Run grid
- Simplest and safest

**2. Adaptive Mode**
- Bearish → Shift range down + halve capital
- Bullish → Shift range up + increase allocation
- Requires more backtesting

**3. Directional Grid (advanced)**
- Bearish → Keep only sell orders (trend-following short)
- Bullish → Keep only buy orders (trend-following long)
- Transitions from pure grid to trend-following

> **Important: All rules above are initial hypotheses. Must be refined based on actual P&L data.**
> Do not over-rely on any fixed strategy without backtesting and live verification.

### Safety Mechanisms
- `dry_run=True` to simulate, not execute
- Panic Close button for emergencies
- Exception handling + auto-retry

---

## 6. Backtesting & Verification

No backtest = gambling. Every strategy change must be validated:

### Key Metrics
- **Win Rate**: % of signals with correct direction
- **Expected Value (EV)**: Average P&L per trade
- **Max Drawdown**: Worst-case loss from peak
- **Sharpe Ratio**: Risk-adjusted return

### Workflow
1. Modify indicators/thresholds
2. Run backtest (`scripts/tests/` or Backtester page)
3. Compare win rate and EV before vs after
4. Only deploy to live when data supports it

---

## 7. Software Development & Engineering Principles

### 7.1 Framework & Architecture Guidelines
- **FastAPI (Backend)**: 
  - **Async First**: Use `async`/`await` for all I/O operations (exchange API requests).
  - **Data Validation**: Strictly type all API inputs and outputs using **Pydantic** models.
  - **Separation of Concerns**: Keep route handlers (`main.py`) thin. Delegate pure business logic and math to `core/` and `quant/` modules.
- **Next.js & React (Frontend)**:
  - **Component Isolation**: Chart components (`AdvancedChart.tsx`) should be pure and accept data as props. Keep state management inside top-level pages or custom `lib/` hooks.
  - **Type Safety**: Maintain strict TypeScript interfaces matching the Python Pydantic models (e.g., `SignalConfig`, `BacktestParams`).
- **Data Processing Edge**:
  - **Vectorization over Iteration**: *Never* use `for` loops or `.iterrows()` for indicator calculations. Always use vectorized Pandas/Numpy operations (and architect towards Polars) to ensure backtests finish in milliseconds, not minutes.

### 7.2 Testing & Validation Methodology
- **Unit Testing (Pytest)**:
  - Mathematical integrity is critical. All functions in `indicators.py` must be tested against isolated, mock data arrays where the expected output is strictly known.
- **Quant Backtesting Integrity**:
  - **Prevent Overfitting**: Do not blindly tune thresholds just to make the historical chart look good. Always validate parameter changes on "out-of-sample" (unseen) timeframes.
  - **Cost Realism**: Backtest EV (Expected Value) *must* factor in exchange trading fees (e.g., 0.05% taker) and realistic slippage. A strategy profitable without fees is often a losing strategy in production.
- **System Resilience**:
  - Third-party exchange APIs *will* timeout or rate-limit. All external calls in `fetcher.py` must have robust `try/except` fallbacks and retry mechanisms.

### 7.3 Version Control Workflow
- **Conventional Commits**: Strictly use standard prefix tags (`feat:`, `fix:`, `refactor:`, `test:`, `quant:`).
- **Atomic Commits**: Separate UI layout changes from core quantitative logic modifications to maintain a clean git history and easy rollbacks (like our recent `KeyError` fix).
