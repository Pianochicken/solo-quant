# SoloQuant 🚀

**SoloQuant** is a modern, full-stack quantitative trading platform designed for crypto algorithmic trading. It features a real-time dashboard, grid trading strategy execution, and a visual backtesting engine.

![SoloQuant Dashboard](https://via.placeholder.com/800x400?text=SoloQuant+Dashboard+Preview)

## ✨ Features

- **Real-time Market Data**: milliseconds-latency price and funding rate updates via OKX API.
- **Interactive Dashboard**:
    - **Synced Charts**: Professional K-Line charts with overlaid Funding Rate indicators using `lightweight-charts`.
    - **Order Management**: Visual tracking of open orders and trade history.
- **Quantitative Strategies**:
    - **Grid Trading Bot**: Automated high-frequency grid strategy (Arithmetic/Geometric).
    - **Dry Run Mode**: Simulate trading logic without risking real assets.
- **Backtesting System**:
    - **Vectorized Engine**: Fast historical simulations against real market data.
    - **Visual Reports**: Equity curves, PnL analysis, and trade execution visualization.
- **Hybrid Architecture**: Combines Python's data science ecosystem with Next.js's reactive UI.

## 🛠️ Tech Stack

### Backend (Python / FastAPI)
- **FastAPI**: High-performance async web framework.
- **CCXT**: Universal crypto exchange API connector (OKX supported).
- **Pandas & NumPy**: Quantitative analysis and vectorized backtesting.
- **Pydantic**: Data validation and settings management.

### Frontend (TypeScript / Next.js)
- **Next.js 14+**: App Router-based modern React framework.
- **Tailwind CSS**: Utility-first styling for a premium dark-mode UI.
- **Lightweight Charts**: Financial charting library by TradingView.
- **Lucide React**: Beautiful & consistent iconography.

## 🚀 Getting Started

### Prerequisites
- Python 3.9+
- Node.js 18+

### Installation

1.  **Clone the repository**
    ```bash
    git clone https://github.com/Pianochicken/solo-quant.git
    cd solo-quant
    ```

2.  **Setup Backend**
    ```bash
    # Create virtual environment
    python -m venv .venv
    source .venv/bin/activate  # Windows: .venv\Scripts\activate

    # Install dependencies
    pip install -r requirements.txt
    ```

3.  **Setup Frontend**
    ```bash
    cd web
    npm install
    ```

### Running the Application

We provide a convenient script to launch both services simultaneously:

```bash
# In the root directory
./run_fullstack.sh
```

- **Frontend**: http://localhost:3000
- **Backend API Docs**: http://localhost:8000/docs

## 📂 Project Structure

```
solo-quant/
├── api/                 # FastAPI Backend
│   ├── core/            # Core logic (Fetcher, Execution)
│   ├── quant/           # Quant strategies & Backtester
│   └── main.py          # API Gateway
├── web/                 # Next.js Frontend
│   ├── app/             # App Router pages
│   ├── components/      # React UI components
│   └── lib/             # API clients & utilities
├── run_fullstack.sh     # Startup script
└── requirements.txt     # Python dependencies
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📜 License

MIT License.
