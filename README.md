# SoloQuant 🚀

**SoloQuant** is a modern, full-stack quantitative analysis, real-time signal monitoring, and empirical backtesting terminal (Crypto Macro & Signal Terminal) tailored for cryptocurrency derivatives trading. The system integrates **underlying derivative order-flow data from Binance and OKX perpetual contracts**, the **v8 multi-layer confluence and structural inflection engine**, the **five-asset macro quadrant radar**, the **zero look-ahead bias backtesting laboratory**, and **automated Telegram tactical chart notifications**.

## ✨ Key Features

### 🧭 Multi-Asset Macro & Quadrant Strip
Real-time cross-asset monitoring for five core assets (`BTC/USDT`, `ETH/USDT`, `SOL/USDT`, `HYPE/USDT`, `CC/USDT`), automatically pre-warmed in the background every 30 seconds:
* **Relative Strength vs BTC (RS vs BTC)**: Calculates the 4H RSI(14) difference against Bitcoin to identify leading alpha assets.
* **24h Coin-Denominated OI Change (%)**: Normalizes USD open interest by price to evaluate real coin-denominated contract changes, completely eliminating passive open interest inflation caused by price moves.
* **Quadrant Classification**:
  * 🔥 **Strong Add**: Momentum stronger than BTC and coin-denominated OI significantly increasing (> +3%), indicating real capital chasing long positions.
  * ⚡ **Strong Reduce**: Price rising but open interest declining (< -3%), indicating short covering or take-profit profit-taking.
  * 🩸 **Weak Add**: Trend weaker than BTC while open interest spikes, indicating aggressive short additions or retail knife-catching.
  * 🧊 **Weak Reduce**: Momentum weaker than BTC and open interest unwinds, indicating standard long liquidation and deleveraging.

### 📊 7-Layer Synchronized Chart Terminal
A high-performance charting interface powered by TradingView's `lightweight-charts` with $O(1)$ hash map lookup for zero-latency crosshair synchronization across all panels:
1. **Main Price Chart (Price & Structure)**: Includes `EMA50` / `EMA200` overlays, toggleable **Donchian Channels**, and **Volume Profile POC (Point of Control horizontal support/resistance lines)**, overlaid with signal markers and hover tooltip reasons.
2. **Market Pulse (0-100)**: A weighted synthetic sentiment index summarizing 7 core indicators (< 20 extreme oversold/bullish, > 80 extreme overbought/bearish).
3. **RSI (14)**: Momentum oscillator with dynamic overbought/oversold thresholds adapted to asset volatility and timeframe.
4. **Cumulative Volume Delta (CVD)**: Real-time net buying/selling pressure based on taker volume.
5. **Aggregated Open Interest**: Combined Binance and OKX perpetual contract data with causal forward ratio scaling to eliminate boundary jumps.
6. **Funding Rate History**: Tracks leverage crowding and squeeze potential.
7. **Market Regime Detection**: Multifactor voting mechanism (ADX 14, BB Width expansion, CVD slope consistency, EMA structure) identifying `Trending Up`, `Trending Down`, or `Ranging`.

### 🎯 Confluence Signal System v8
Combines an environment-building setup layer with a price trigger state machine and independent breakout tracks across three primary archetypes:

| Category | Indicator | Weight | Bullish Condition | Bearish Condition |
| :--- | :--- | :---: | :--- | :--- |
| **Environment (Env)** | 1. LSUR Z-Score | 1.0 | Long/short account ratio extreme short crowding (+ anti-dulling) | Extreme long crowding (+ anti-dulling) |
| **Environment (Env)** | 2. CVD Momentum | 1.0 | Taker buy momentum surges (CVD↑) | Taker sell momentum strengthens (CVD↓) |
| **Environment (Env)** | 3. OI × Price | 1.0 | Price↑ + OI↑ or sharp dump deleveraging bottom | Price↓ + OI↑ or sharp pump deleveraging top |
| **Environment (Env)** | 4. Funding Rate | 1.0 | Negative extreme (+ OI weighting & slope discount) | Positive extreme (+ OI weighting & slope discount) |
| **Structure (Inflection)** | 5. Capitulation (CAP) | 1.5~2.0 | OI flash drop + CVD dump absorption + price stabilization | OI flash drop after parabolic pump + buying exhaustion wick |
| **Structure (Inflection)** | 6. CVD Divergence (DIV) | 1.5~2.0 | Price makes lower low while CVD forms higher low | Price makes higher high while CVD forms lower high |
| **Price Trigger (PA)** | 7. RSI (14) + PA | 1.0 | Dynamic oversold zone with bullish candlestick pattern | Dynamic overbought zone with bearish candlestick pattern |
| **Price Trigger (PA)** | 8. EMA Zone / Pullback | 1.0 | Ranging severe negative disparity or uptrend pullback to EMA50 support | Ranging severe positive disparity or downtrend bounce to EMA50 resistance |
| **Price Trigger (PA)** | 9. Bollinger %B | 1.0 | Price breaks below lower band or pullback support zone | Price breaks above upper band or rally resistance zone |
| **Breakout Track** | 10. Donchian Breakout 🚀 | Independent | First-bar close above upper band + trending regime + MACD↑ + CVD↑ + OI↑ | First-bar close below lower band + trending regime + MACD↓ + CVD↓ + OI↑ |

* **4-Layer Protection Filters**:
  * **Layer 1 & 2 (Trend Protection & Ranging Noise Reduction)**: Blocks counter-trend signals in strong trends (no-short / no-long protection); tightens setup window during 1H ranging regimes.
  * **Layer 3 (4H MTF Confirmation)**: Blocks 1H / 15m counter-trend trades when 4H higher timeframe is in a strong trend.
  * **Layer 4 (BTC Macro Regime & Alpha Decoupling)**: Dynamically adjusts altcoin thresholds based on BTC macro regime; includes dedicated Alpha Decoupling Protection and dynamic ATR pullback bounds for HYPE.

### 🧪 Signal Strategy Backtester v2
* **Zero Look-Ahead Bias Guarantee**: Backtesting fully shares the live 1,000-candle indicator warmup pipeline, eliminating unclosed-bar leaks and repainting errors.
* **Auto-Adapt Risk Profile**: Automatically injects empirical MFE/MAE optimal risk parameters (`SL`, `TP`, `Trail Activation`, `Trail Stop`) upon changing symbol or timeframe (`1h` / `4h` / `1d`).
* **Realistic Execution Constraints**: Incorporates gap slippage simulation, trailing stop safe clamping, risk-based position sizing, and archetype/min-score filtering.

### 🔔 Automated Scanner & Telegram Tactical Alerts
* Background APScheduler scans hourly at `:00, :15, :30, :45` for `1h` and `4h` signals.
* Automatically generates 168-hour high-resolution candlestick charts with EMA50/200 overlays and historical markers.
* Dispatches alerts containing trigger reasons, macro quadrant status, and automatically calculated tactical execution levels (`TP1` breakeven trigger, `TP2` target, `SL` safe stop) with graceful plain-text fallback.

---

## 🛠️ Tech Stack

### Backend (Python / FastAPI / PostgreSQL)
* **FastAPI & Uvicorn**: Asynchronous high-concurrency API gateway and lifespan scheduler management.
* **PostgreSQL 15 & SQLAlchemy (QueuePool)**: Relational time-series persistence with deadlock-prevention primary key sorting and batch upserts, using short-lived sessions to prevent connection pool exhaustion.
* **CCXT (Binance & OKX Aggregator)**: Dual-exchange perpetual contract data aggregation (OHLCV, Taker Volume, Open Interest, Long/Short Ratio, Funding Rate).
* **APScheduler & Matplotlib / HTTPX**: Background pre-warming, scheduled signal scanning, and thread-safe Telegram candlestick chart generation.

### Frontend (TypeScript / Next.js / Tailwind CSS)
* **Next.js (App Router) & React**: Responsive dark-mode quantitative terminal.
* **Lightweight Charts (v5)**: Multi-chart timeline synchronized display with custom series marker plugins and dynamic price formatting.

---

## 🚀 Getting Started

### Prerequisites
* Python 3.9+
* Node.js 18+
* Docker & Docker Compose (Required for PostgreSQL)

### Running with Docker Compose (Recommended)

1. **Configure Environment Variables**
   Create a `.env` file in the root directory (default timezone offset set to `8` for UTC+8 / Taipei):
   ```env
   TELEGRAM_BOT_TOKEN=your_telegram_bot_token
   TELEGRAM_CHAT_ID=your_telegram_chat_id
   NEXT_PUBLIC_TIMEZONE_OFFSET=8
   ```

2. **Build and Start Containers**
   ```bash
   docker-compose up -d --build
   ```

3. **Access Services**
   * **Frontend Terminal**: `http://localhost:3000`
   * **Backtest Laboratory**: `http://localhost:3000/backtest`
   * **Backend API Docs**: `http://localhost:8000/docs`

4. **Stop Containers**
   ```bash
   docker-compose down
   ```

---

## 📂 Project Structure

```text
solo_quant/
├── api/                         # FastAPI Backend
│   ├── core/                    # Indicators (indicators.py), Fetcher (fetcher.py), Scanner, Notifier
│   ├── db/                      # Database pool (database.py), ORM models (models.py), and CRUD upserts
│   ├── quant/                   # Signal backtester, position state machine, and risk profiles
│   └── main.py                  # API routes, market overview cache, and lifespan scheduler
├── web/                         # Next.js Frontend
│   ├── app/                     # Dashboard (page.tsx) and Backtest Lab (backtest/page.tsx)
│   ├── components/              # 7-layer sync chart (AdvancedChart.tsx), sentiment panel, and modals
│   └── lib/                     # API client contracts, timezone shifts, and dynamic precision utils
├── docker-compose.yml           # PostgreSQL + FastAPI + Next.js orchestration
└── requirements.txt             # Python dependencies
```

## 📜 License

MIT License.