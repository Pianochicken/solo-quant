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

from api.core.indicators import IndicatorEngine

@app.get("/market/{symbol}")
def get_market_data(symbol: str, timeframe: str = '1d', limit: int = 100):
    """
    Get generic market data (Price + Funding + Sentiment).
    """
    # Fix symbol format
    formatted_symbol = symbol.replace('-', '/')
    
    try:
        # 1. Fetch Basic Data
        data = fetcher.fetch_market_data(formatted_symbol, timeframe, limit)
        
        # Helper: Map CCXT timeframe to OKX Rubik/OI period
        # OKX Rubik API supports: '5m', '1H', '1D'
        # OKX OI History supports: '5m', '1H', '1D'  
        tf_map = {
            '1m': '5m',   # Round up to nearest supported
            '3m': '5m',
            '5m': '5m',
            '15m': '5m',  # OKX doesn't have 15m, use 5m + merge_asof aligns
            '30m': '1H',
            '1h': '1H',
            '2h': '1H',
            '4h': '1H',
            '6h': '1H',
            '12h': '1H',
            '1d': '1D',
            '1w': '1D',
        }
        indicator_period = tf_map.get(timeframe, '1H')
        
        # 3. Fetch CoinKarma Data (Micro-structure)
        # Order Book for Liquidity Walls
        orderbook = fetcher.fetch_order_book_depth(formatted_symbol, limit=400)
        
        # Long/Short Ratio for Z-Score
        ls_ratio_history = fetcher.fetch_long_short_ratio(formatted_symbol, period=indicator_period, limit=200)
        
        # Taker Volume for CVD (uses indicator_period)
        taker_volume = fetcher.fetch_taker_volume(formatted_symbol, period=indicator_period, limit=1000)
        
        # Open Interest (uses indicator_period to match Price chart timeframe)
        open_interest_raw = fetcher.fetch_open_interest(formatted_symbol, timeframe=indicator_period, limit=500)
        
        # Always fetch DAILY OI for long-term percentile (100 days ≈ 3 months, 1 page only)
        daily_oi_for_percentile = fetcher.fetch_open_interest(formatted_symbol, timeframe='1D', limit=100)
        
        # --- Data Alignment: Sync OI & Funding to Price Timestamps ---
        import pandas as pd
        
        # 1. Prepare Price DataFrame
        if data['price']:
            df_price = pd.DataFrame(data['price'])
            df_price['time'] = df_price['time'].astype(int)
            df_price.sort_values('time', inplace=True)
            
            # 2. Align Open Interest
            if open_interest_raw:
                df_oi = pd.DataFrame(open_interest_raw)
                df_oi['time'] = df_oi['time'].astype(int)
                df_oi.sort_values('time', inplace=True)
                
                merged_oi = pd.merge_asof(
                    df_price[['time']], 
                    df_oi[['time', 'value']], 
                    on='time', 
                    direction='backward'
                )
                merged_oi['value'] = merged_oi['value'].ffill().fillna(0)
                open_interest = merged_oi[['time', 'value']].to_dict('records')
            else:
                open_interest = []

        # 3. Align Funding Rate
            if data['funding']:
                df_funding = pd.DataFrame(data['funding'])
                df_funding['time'] = df_funding['time'].astype(int)
                df_funding.sort_values('time', inplace=True)
                
                merged_funding = pd.merge_asof(
                    df_price[['time']], 
                    df_funding[['time', 'value']], 
                    on='time', 
                    direction='backward'
                )
                merged_funding['value'] = merged_funding['value'].ffill().fillna(0)
                funding_aligned = merged_funding[['time', 'value']].to_dict('records')
            else:
                funding_aligned = []

            # 4. Compute & Align CVD
            # Filter taker volume to price chart's time range FIRST,
            # then compute cumulative sum. This keeps CVD values relative to the visible chart.
            if taker_volume:
                price_start_time = df_price['time'].min()
                price_end_time = df_price['time'].max()
                
                # Only accumulate CVD from data within the price chart's range
                filtered_taker = [t for t in taker_volume if price_start_time <= t['time'] <= price_end_time]
                
                cvd_raw = IndicatorEngine.calculate_cvd_history(filtered_taker)
                if cvd_raw:
                    df_cvd = pd.DataFrame(cvd_raw)
                    df_cvd['time'] = df_cvd['time'].astype(int)
                    df_cvd.sort_values('time', inplace=True)
                    
                    merged_cvd = pd.merge_asof(
                        df_price[['time']],
                        df_cvd[['time', 'value']],
                        on='time',
                        direction='backward'
                    )
                    merged_cvd['value'] = merged_cvd['value'].ffill().fillna(0)
                    cvd_aligned = merged_cvd[['time', 'value']].to_dict('records')
                else:
                    cvd_aligned = []
            else:
                cvd_aligned = []

        else:
            open_interest = open_interest_raw
            funding_aligned = data['funding']
            cvd_aligned = [] # Fallback

        # 3. Calculate Indicators
        # Get current price from last close
        current_price = data['price'][-1]['close'] if data['price'] else 0
        
        # removed: liquidity_walls = IndicatorEngine.calculate_liquidity_density(orderbook, current_price)
        lsur_z_score = IndicatorEngine.calculate_lsur_z_score(ls_ratio_history)
        
        # 4. LSUR Z-Score History → Align to price timestamps
        lsur_z_history = IndicatorEngine.calculate_lsur_z_score_history(ls_ratio_history)
        
        lsur_z_aligned = []
        
        if lsur_z_history and data['price']:
            df_z = pd.DataFrame(lsur_z_history)
            df_z['time'] = df_z['time'].astype(int)
            df_z.sort_values('time', inplace=True)
            
            merged_z = pd.merge_asof(
                df_price[['time']],
                df_z[['time', 'value', 'signal']],
                on='time',
                direction='backward'
            )
            
            for _, row in merged_z.iterrows():
                t = int(row['time'])
                z_val = float(row['value']) if pd.notna(row['value']) else None
                if z_val is not None:
                    lsur_z_aligned.append({"time": t, "value": z_val})
        
        # 5. OI Percentile (from daily data — always has months of history)
        oi_percentile = IndicatorEngine.calculate_oi_percentile(daily_oi_for_percentile)
        
        # 6. Multi-Indicator Confluence Signals
        # Combine LSUR Z-Score + CVD momentum + OI percentile + Funding Rate
        confluence_markers = IndicatorEngine.calculate_confluence_signals(
            price_data=data['price'],
            lsur_z_aligned=lsur_z_aligned,
            cvd_aligned=cvd_aligned,
            oi_percentile=oi_percentile,
            funding_aligned=funding_aligned
        )
        
        return {
            "symbol": formatted_symbol,
            "data": {
                "price": data['price'],
                "funding": funding_aligned
            },
            "indicators": {
                "lsur_z_score": lsur_z_score,
                "lsur_history": ls_ratio_history,
                "lsur_z_history": lsur_z_aligned,
                "lsur_markers": confluence_markers,    # Confluence signals (replaces old Z-only markers)
                "cvd_history": cvd_aligned,
                "open_interest": open_interest,
                "oi_percentile": oi_percentile
            }
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# --- Quant / Grid Trading Endpoints ---
from pydantic import BaseModel
from api.quant.grid_bot import GridBot
from api.core.execution import ExecutionHandler

# Initialize Execution Handler (Dry Run = True)
executor = ExecutionHandler(fetcher.exchange, dry_run=True)

@app.get("/quant/smart-params/{symbol}")
def get_smart_grid_params(symbol: str):
    """
    Returns AI-suggested Grid Parameters based on Liquidity Walls & Sentiment.
    """
    formatted_symbol = symbol.replace('-', '/')
    try:
        # 1. Fetch needed data
        price_data = fetcher.fetch_market_data(formatted_symbol, limit=1)
        current_price = price_data['price'][-1]['close']
        
        orderbook = fetcher.fetch_order_book_depth(formatted_symbol, limit=400)
        ls_ratio_history = fetcher.fetch_long_short_ratio(formatted_symbol, limit=100)
        
        # 2. Analyze Indicators
        walls = IndicatorEngine.calculate_liquidity_density(orderbook, current_price)
        z_score = IndicatorEngine.calculate_lsur_z_score(ls_ratio_history)
        
        # 3. Determine Smart Range
        # Lower = First major Support Wall (Bid)
        # Upper = First major Resistance Wall (Ask)
        # Fallback: +/- 5% if no walls found close by
        
        lower_price = walls['bid_walls'][0]['price'] if walls['bid_walls'] else current_price * 0.95
        upper_price = walls['ask_walls'][0]['price'] if walls['ask_walls'] else current_price * 1.05
        
        # Ensure range is valid
        if lower_price >= current_price: lower_price = current_price * 0.98
        if upper_price <= current_price: upper_price = current_price * 1.02
        
        return {
            "symbol": formatted_symbol,
            "current_price": current_price,
            "lower_price": lower_price,
            "upper_price": upper_price,
            "grid_count": 20, # Default recommended
            "sentiment_score": z_score,
            "signal": "wait" if abs(z_score) > 2 else "neutral" # Simple signal hint
        }
    except Exception as e:
        print(f"Smart Params Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
        # Need current price and sentiment
        formatted_symbol = params.symbol.replace('-', '/')
        ticker = fetcher.exchange.fetch_ticker(formatted_symbol)
        current_price = ticker['last']
        
        # Fetch Sentiment for Smart Guard
        ls_ratio_history = fetcher.fetch_long_short_ratio(formatted_symbol, limit=100)
        z_score = IndicatorEngine.calculate_lsur_z_score(ls_ratio_history)
        
        orders = bot.get_orders_for_price(current_price, sentiment_score=z_score)
        
        return {
            "grid_lines": bot.grids,
            "current_price": current_price,
            "simulated_orders": orders,
            "sentiment_score": z_score
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
        
        formatted_symbol = params.symbol.replace('-', '/')
        ticker = fetcher.exchange.fetch_ticker(formatted_symbol)
        current_price = ticker['last']
        
        # Fetch Sentiment for Smart Guard
        ls_ratio_history = fetcher.fetch_long_short_ratio(formatted_symbol, limit=100)
        z_score = IndicatorEngine.calculate_lsur_z_score(ls_ratio_history)
        
        orders = bot.get_orders_for_price(current_price, sentiment_score=z_score)
        
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
            "orders_placed": executed_orders,
            "sentiment_guard": "active" if abs(z_score) > 2 else "monitoring"
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
        formatted_symbol = params.symbol.replace('-', '/')
        
        # 1. Fetch Price History
        end_time = int(time.time() * 1000)
        start_time = end_time - (params.duration_days * 24 * 60 * 60 * 1000)
        
        history = fetcher.fetch_history(formatted_symbol, start_time, end_time, '1h')
        
        if not history:
             raise HTTPException(status_code=404, detail="No historical data found")

        # 2. Fetch Sentiment History (LSUR)
        # We need LSUR for the same period. 
        # OKX LSUR endpoint usually returns recent data. 
        # For BACKTESTING, we ideally need historical LSUR.
        # Implied limitation: We might only get recent 1440 points (OKX limit).
        # If duration > available LSUR history, we pad with Neutral (0).
        
        # Try fetching 1H LSUR. 7 days * 24 = 168 points. Easy.
        # `fetch_long_short_ratio` implementation uses `limit`. 
        # We need to ensure we get enough points.
        hours_needed = params.duration_days * 24
        lsur_raw = fetcher.fetch_long_short_ratio(formatted_symbol, period='1H', limit=hours_needed + 50) 
        
        # Calculate Z-Scores for this history
        # We need a rolling window for Z-Score. `calculate_lsur_z_score` does this.
        # But `calculate_lsur_z_score` returns a SINGLE current Z-Score.
        # We need a SERIES of Z-Scores corresponding to each timestamp.
        
        # We need to expose a helper or recalculate here.
        # Let's simple-calc here for MVP:
        # Z = (Value - Mean(Last 20)) / Std(Last 20)
        
        import pandas as pd
        import numpy as np
        
        lsur_df = pd.DataFrame(lsur_raw)
        if not lsur_df.empty:
            lsur_df['value'] = lsur_df['value'].astype(float)
            # Sort by time ascending
            lsur_df = lsur_df.sort_values('time')
            
            # Calculate rolling Z-Score
            window = 20
            lsur_df['mean'] = lsur_df['value'].rolling(window=window).mean()
            lsur_df['std'] = lsur_df['value'].rolling(window=window).std()
            lsur_df['z_score'] = (lsur_df['value'] - lsur_df['mean']) / lsur_df['std']
            
            # Convert back to list of dicts: [{'time': t, 'value': z}, ...]
            sentiment_data = lsur_df[['time', 'z_score']].dropna().rename(columns={'z_score': 'value'}).to_dict('records')
        else:
            sentiment_data = []

        # 3. Init Bot
        bot = GridBot(
            params.symbol, 
            params.lower_price, 
            params.upper_price, 
            params.grid_count, 
            params.investment
        )
        
        # 4. Run Backtest
        tester = Backtester(bot, history, sentiment_data=sentiment_data)
        result = tester.run()
        
        # 5. Metrics
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
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
