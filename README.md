# SoloQuant 🚀

**SoloQuant** is a modern, full-stack quantitative trading platform designed for crypto algorithmic trading. It features a real-time dashboard with multi-indicator confluence signals, grid trading strategy execution, and a visual backtesting engine.

## ✨ Features

### 📊 Real-time Dashboard
- **Professional K-Line Charts**: Interactive candlestick charts with overlaid indicators using `lightweight-charts`.
- **Multi-Timeframe Support**: 15m / 1h / 4h / 1D with instant switching.
- **Indicator Overlays**: EMA50/200, RSI(14), Funding Rate, CVD, Open Interest.
- **Local Data Persistence**: PostgreSQL-backed history caching for unified minute-level precision and offline resilience.

### 🎯 Multi-Indicator Confluence Signal System (v4)
7 indicators scored in parallel to generate high-confidence buy/sell signals:

| # | Indicator | Bullish Condition | Bearish Condition |
|---|-----------|-------------------|-------------------|
| 1 | LSUR Z-Score | Overcrowded shorts | Overcrowded longs |
| 2 | CVD Momentum | Buying pressure ↑ | Selling pressure ↑ |
| 3 | OI × Price | Price↑ + OI↑ (new longs) / Deleverage bottom | Price↓ + OI↑ (new shorts) / Short squeeze |
| 4 | Funding Rate | Negative extreme | Positive extreme |
| 5 | RSI (14) | Oversold | Overbought |
| 6 | EMA Zone | Price below EMA50 | Price above EMA50 |
| 7 | Bollinger %B | Below lower band | Above upper band |

- **Timeframe-Adaptive Thresholds**: Each timeframe has its own tuned parameter profile.
- **Signal Threshold**: 3/7 confluence required to trigger.
- **Cooldown**: Prevents signal clustering (8 bars on 15m, 2 bars on 1D).

### 🤖 Quantitative Strategies
- **Grid Trading Bot**: Automated grid strategy with AI-suggested parameters.
- **Dry Run Mode**: Simulate trading logic without risking real assets.
- **Backtesting Engine**: Fast historical simulations with equity curves and PnL analysis.

### 📡 Sentiment Panel
- **LSUR Z-Score**: Crowded positioning indicator.
- **EMA Trend**: 50/200 EMA trend filter (Uptrend / Downtrend / Neutral).
- **RSI (14)**: Overbought/Oversold momentum gauge.
- **OI Percentile**: Current leverage level relative to 90-day history.

## 🛠️ Tech Stack

### Backend (Python / FastAPI / PostgreSQL)
- **FastAPI**: High-performance async web framework.
- **PostgreSQL & SQLAlchemy**: Relational data persistence storing historical OHLCV and secondary metrics.
- **CCXT**: Universal crypto exchange API connector (OKX & Binance).
- **Pandas & NumPy**: Quantitative analysis and indicator calculations.
- **Concurrent Futures**: Parallel API data fetching for low latency.

### Frontend (TypeScript / Next.js)
- **Next.js 14+**: App Router-based modern React framework.
- **Tailwind CSS**: Utility-first styling for a premium dark-mode UI.
- **Lightweight Charts**: Financial charting library by TradingView.
- **Lucide React**: Beautiful & consistent iconography.

## 🚀 Getting Started

### Prerequisites
- Python 3.9+
- Node.js 18+
- Docker & Docker Compose (Required for PostgreSQL Database)

### Installation

1.  **Clone the repository**
    ```bash
    git clone https://github.com/Pianochicken/solo-quant.git
    cd solo-quant
    ```

2.  **Setup Backend**
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    ```

3.  **Setup Frontend**
    ```bash
    cd web
    npm install
    ```

### Running the Application (Local Development)

```bash
./run_fullstack.sh
```

- **Frontend**: http://localhost:3000
- **Backend API Docs**: http://localhost:8000/docs

### 🐳 Running with Docker (Production / Cloud Deployment)

The project is fully containerized for easy deployment to AWS/GCP or local testing.

1. **Build and start the containers**
   ```bash
   docker-compose up -d --build
   ```
2. **Access the services**
   - Frontend: `http://localhost:3000`
   - Backend API: `http://localhost:8000`
3. **Stop the containers**
   ```bash
   docker-compose down
   ```

## 📂 Project Structure

```
solo-quant/
├── api/                 # FastAPI Backend
│   ├── core/            # Core logic (Fetcher, Indicators, Execution)
│   ├── db/              # Data persistence (Models, Database config, CRUD)
│   ├── quant/           # Quant strategies & Backtester
│   └── main.py          # API Gateway & Data Orchestration
├── web/                 # Next.js Frontend
│   ├── app/             # App Router pages
│   ├── components/      # React UI components (Chart, SentimentPanel)
│   └── lib/             # API clients & type definitions
├── run_fullstack.sh     # Startup script
└── requirements.txt     # Python dependencies
```

## 📜 License

MIT License.
