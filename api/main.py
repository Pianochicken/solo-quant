from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from api.core.fetcher import DataFetcher

app = FastAPI(title="SoloQuant API")

# Enable CORS for Next.js (usually runs on port 3000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

fetcher = DataFetcher()

@app.get("/")
def read_root():
    return {"status": "SoloQuant API is running 🚀"}

@app.get("/market/{symbol}")
def get_market_data(symbol: str, timeframe: str = '1d', limit: int = 100):
    """
    Get generic market data (Price + Funding).
    Note: symbol should be URL encoded if needed, but for simple BTC/USDT standard slash might need handling.
    We'll treat 'BTC-USDT' or 'BTC/USDT' carefully.
    """
    # Fix symbol format if passed as BTC-USDT for URL safety, convert to BTC/USDT for CCXT
    formatted_symbol = symbol.replace('-', '/')
    
    try:
        data = fetcher.fetch_market_data(formatted_symbol, timeframe, limit)
        oi = fetcher.fetch_open_interest(formatted_symbol, limit, '1h') 
        
        return {
            "symbol": formatted_symbol,
            "data": data,
            "open_interest": oi
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Quant / Grid Trading Endpoints ---
from pydantic import BaseModel
from api.quant.grid_bot import GridBot
from api.core.execution import ExecutionHandler

# Initialize Execution Handler (Dry Run = True)
executor = ExecutionHandler(fetcher.exchange, dry_run=True)

class GridParams(BaseModel):
    symbol: str
    lower_price: float
    upper_price: float
    grid_count: int
    investment: float

@app.post("/quant/grid/preview")
def preview_grid(params: GridParams):
    """
    Calculates grid lines and simulated initial orders.
    """
    try:
        bot = GridBot(
            params.symbol, 
            params.lower_price, 
            params.upper_price, 
            params.grid_count, 
            params.investment
        )
        
        # Calculate theoretical orders at current price
        # Need current price first
        ticker = fetcher.exchange.fetch_ticker(params.symbol)
        current_price = ticker['last']
        
        orders = bot.get_orders_for_price(current_price)
        
        return {
            "grid_lines": bot.grids,
            "current_price": current_price,
            "simulated_orders": orders
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/quant/grid/start")
def start_grid(params: GridParams):
    """
    Starts a Grid Bot (Dry Run Only for now).
    """
    # For now, just simulate placements
    try:
        # Re-instantiate bot (in memory storage comes later)
        bot = GridBot(
            params.symbol, 
            params.lower_price, 
            params.upper_price, 
            params.grid_count, 
            params.investment
        )
        
        ticker = fetcher.exchange.fetch_ticker(params.symbol)
        current_price = ticker['last']
        orders = bot.get_orders_for_price(current_price)
        
        executed_orders = []
        for order in orders:
            res = executor.place_order(
                symbol=order['symbol'],
                side=order['side'],
                order_type=order['type'],
                amount=order['amount'],
                price=order['price']
            )
            executed_orders.append(res)
            
        return {
            "status": "started",
            "mode": "dry_run" if executor.dry_run else "live",
            "orders_placed": executed_orders
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Backtesting API ---
from api.quant.backtester import Backtester
import time

class BacktestParams(BaseModel):
    symbol: str
    lower_price: float
    upper_price: float
    grid_count: int
    investment: float
    duration_days: int = 7 # Default backtest 7 days

@app.post("/quant/backtest")
def run_backtest(params: BacktestParams):
    try:
        # 1. Fetch History
        end_time = int(time.time() * 1000)
        start_time = end_time - (params.duration_days * 24 * 60 * 60 * 1000)
        
        history = fetcher.fetch_history(params.symbol, start_time, end_time, '1h')
        
        if not history:
             raise HTTPException(status_code=404, detail="No historical data found")

        # 2. Init Bot
        bot = GridBot(
            params.symbol, 
            params.lower_price, 
            params.upper_price, 
            params.grid_count, 
            params.investment
        )
        
        # 3. Run Backtest
        tester = Backtester(bot, history)
        result = tester.run()
        
        # 4. Metrics
        initial = params.investment
        final = result['final_balance']
        pnl = final - initial
        pnl_percent = (pnl / initial) * 100
        
        return {
            "metrics": {
                "initial_balance": initial,
                "final_balance": final,
                "pnl": pnl,
                "pnl_percent": pnl_percent,
                "total_trades": len(result['trades'])
            },
            "equity_curve": result['equity'],
            "trades": result['trades'][-50:] # Limit to last 50 for UI
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
