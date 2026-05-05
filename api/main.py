import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel as PydanticBaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from api.core.fetcher import DataFetcher
from api.db.database import engine, Base
import api.db.models  # Import to register models with Base

logger = logging.getLogger(__name__)

# --- Configure root logger so INFO messages from scanner/notifier are visible ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Create tables if they don't exist yet
Base.metadata.create_all(bind=engine)

# --- APScheduler: Signal Notification Scheduler ---
scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: start/stop the APScheduler for periodic signal scanning."""
    from api.core.signal_scanner import scan_and_notify

    scheduler.add_job(
        scan_and_notify,
        trigger=CronTrigger(minute="0,15,30,45"),
        id="signal_scanner",
        name="Periodic Signal Scanner",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("APScheduler started — signal scanner runs at :00, :15, :30, :45 every hour.")
    yield
    scheduler.shutdown()
    logger.info("APScheduler shut down.")


app = FastAPI(title="SoloQuant API", lifespan=lifespan)

# Enable CORS for Next.js (usually runs on port 3000 locally, can add production URLs below)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://solo-quant.vercel.app",  # Example Vercel app
        "*"  # Accept from everywhere or restrict it to strict domains later
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global DataFetcher instance to maintain the in-memory cache
_fetcher_instance = None

def get_fetcher() -> DataFetcher:
    global _fetcher_instance
    if _fetcher_instance is None:
        _fetcher_instance = DataFetcher()
    return _fetcher_instance

@app.get("/")
def read_root():
    return {"status": "SoloQuant API is running 🚀"}

@app.post("/clear-cache")
def clear_cache():
    """
    Clears the in-memory cache of the DataFetcher to force fresh data fetches.
    """
    global _fetcher_instance
    if _fetcher_instance and hasattr(_fetcher_instance, 'cache'):
        _fetcher_instance.cache.clear()
        return {"status": "success", "message": "Cache cleared successfully"}
    return {"status": "info", "message": "Cache was already empty"}

# --- Notification Config Endpoints ---
from api.core.signal_scanner import get_notification_config, update_notification_config
from typing import List, Optional


class NotificationConfigUpdate(PydanticBaseModel):
    enabled: Optional[bool] = None
    monitored_symbols: Optional[List[str]] = None


@app.get("/notifications/config")
def get_notif_config():
    """Get the current notification settings."""
    return get_notification_config()


@app.post("/notifications/config")
def update_notif_config(body: NotificationConfigUpdate):
    """Update notification settings (toggle on/off, select symbols)."""
    return update_notification_config(
        enabled=body.enabled,
        monitored_symbols=body.monitored_symbols,
    )


@app.post("/notifications/test")
async def test_notification():
    """Send a test notification to verify Telegram integration."""
    from api.core.notifier import send_telegram_message
    success = await send_telegram_message("✅ Solo-Quant test notification — Telegram integration is working!")
    if success:
        return {"status": "success", "message": "Test notification sent to Telegram."}
    return {"status": "error", "message": "Failed to send. Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."}


@app.post("/notifications/scan-now")
async def trigger_scan_now():
    """Manually trigger a signal scan (useful for testing without waiting 15 min)."""
    from api.core.signal_scanner import scan_and_notify
    await scan_and_notify()
    return {"status": "success", "message": "Manual scan completed."}


from api.core.indicators import IndicatorEngine

@app.get("/market/{symbol}")
def get_market_data(
    symbol: str, 
    timeframe: str = '1d', 
    limit: int = 100, 
    ranging_threshold: int = 3, 
    trending_threshold: int = 3, 
    enable_protection: bool = False,
    use_dynamic_profiles: bool = True
):
    """
    Get generic market data (Price + Funding + Sentiment).
    """
    # Fix symbol format
    formatted_symbol = symbol.replace('-', '/')
    
    try:
        fetcher = get_fetcher()
        
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
        
        # 1. Fetch Basic Data and Indicator Data Concurrently
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            future_data = pool.submit(fetcher.fetch_market_data, formatted_symbol, timeframe, limit)
            future_ob = pool.submit(fetcher.fetch_order_book_depth, formatted_symbol, limit=400)
            
            future_ls = pool.submit(fetcher.fetch_long_short_ratio, formatted_symbol, period=indicator_period, limit=200)
            future_ls_daily = pool.submit(fetcher.fetch_long_short_ratio, formatted_symbol, period='1D', limit=100)
            
            future_taker = pool.submit(fetcher.fetch_taker_volume, formatted_symbol, period=indicator_period, limit=1000)
            future_taker_daily = pool.submit(fetcher.fetch_taker_volume, formatted_symbol, period='1D', limit=100)
            
            future_oi_raw = pool.submit(fetcher.fetch_open_interest, formatted_symbol, timeframe=indicator_period, limit=500)
            future_oi_daily = pool.submit(fetcher.fetch_open_interest, formatted_symbol, timeframe='1D', limit=100)
            
            data = future_data.result()
            orderbook = future_ob.result()
            
            ls_ratio_history_raw = future_ls.result()
            ls_ratio_daily = future_ls_daily.result()
            
            taker_volume_raw = future_taker.result()
            taker_volume_daily = future_taker_daily.result()
            
            open_interest_raw = future_oi_raw.result()
            daily_oi_for_percentile = future_oi_daily.result()
            
        # --- Data Alignment: Merge High-Res and Daily for extended history ---
        import pandas as pd
        
        # 1. Prepare Price DataFrame
        # --- Extended History Merging ---
        def merge_history(high_res, daily):
            combined = (high_res or []) + (daily or [])
            if not combined: return []
            df = pd.DataFrame(combined)
            df['time'] = df['time'].astype(int)
            # Drop duplicates keeping high-res (which is appended first)
            df.drop_duplicates(subset=['time'], keep='first', inplace=True)
            df.sort_values('time', inplace=True)
            return df.to_dict('records')

        if data['price']:
            df_price = pd.DataFrame(data['price'])
            df_price['time'] = df_price['time'].astype(int)
            df_price.sort_values('time', inplace=True)

            ls_ratio_history = merge_history(ls_ratio_history_raw, ls_ratio_daily)
            taker_volume = merge_history(taker_volume_raw, taker_volume_daily)
            
            # 2. Align Open Interest
            combined_oi = merge_history(open_interest_raw, daily_oi_for_percentile)
            if combined_oi:
                df_oi = pd.DataFrame(combined_oi)
                merged_oi = pd.merge_asof(
                    df_price[['time']], 
                    df_oi[['time', 'value']], 
                    on='time', 
                    direction='backward'
                )
                import numpy as np
                merged_oi['value'] = merged_oi['value'].ffill().replace(np.nan, None)
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
                import numpy as np
                merged_funding['value'] = merged_funding['value'].ffill().replace(np.nan, None)
                funding_aligned = merged_funding[['time', 'value']].to_dict('records')
            else:
                funding_aligned = []
                
        # 3.5 Align LS Ratio
            if ls_ratio_history:
                df_ls = pd.DataFrame(ls_ratio_history)
                df_ls['time'] = df_ls['time'].astype(int)
                df_ls.sort_values('time', inplace=True)
                
                merged_ls = pd.merge_asof(
                    df_price[['time']], 
                    df_ls[['time', 'value']], 
                    on='time', 
                    direction='backward'
                )
                merged_ls['value'] = merged_ls['value'].ffill().fillna(0)
                ls_aligned_history_val = merged_ls[['time', 'value']].to_dict('records')
            else:
                ls_aligned_history_val = []

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
                cvd_aligned = [] # Fallback

        else:
            open_interest = []
            if open_interest_raw:
                open_interest = open_interest_raw
            funding_aligned = data.get('funding', [])
            
            # Fix UnboundLocalError by properly merging if missing price data
            ls_ratio_history = merge_history(ls_ratio_history_raw, ls_ratio_daily) if 'ls_ratio_history_raw' in locals() else []
            ls_aligned_history_val = ls_ratio_history
            cvd_aligned = [] # Fallback

        # 3. Calculate Indicators
        # Get current price from last close
        current_price = data['price'][-1]['close'] if data['price'] else 0
        
        # removed: liquidity_walls = IndicatorEngine.calculate_liquidity_density(orderbook, current_price)
        lsur_z_score = IndicatorEngine.calculate_lsur_z_score(ls_aligned_history_val)
        
        # 4. LSUR Z-Score History (Already aligned to price)
        lsur_z_aligned = IndicatorEngine.calculate_lsur_z_score_history(ls_aligned_history_val)
        
        # 5. OI Percentile (from daily data — always has months of history)
        oi_percentile = IndicatorEngine.calculate_oi_percentile(daily_oi_for_percentile)
        
        # 5.5. EMA Trend Filter (50/200 from price data)
        ema_trend = IndicatorEngine.calculate_ema_trend(data['price'], symbol=formatted_symbol)
        trend_state = ema_trend['trend_state']
        
        # 5.6. RSI (14-period)
        rsi_history = IndicatorEngine.calculate_rsi(data['price'])
        
        # 5.7. Bollinger Bands %B (20-period, 2 std)
        bb_data = IndicatorEngine.calculate_bollinger_bands(data['price'])
        bb_pctb = bb_data['bb_pctb']
        
        # 5.8. Donchian Channel and MACD for Breakout Strategy
        donchian = IndicatorEngine.calculate_donchian_channel(data['price'])
        macd_history = IndicatorEngine.calculate_macd(data['price'])

        # 6. Multi-Indicator Confluence Signals v4
        # Timeframe-adaptive thresholds, trend filter, per-bar rolling OI percentile
        confluence_markers, market_regime = IndicatorEngine.calculate_confluence_signals(
            price_data=data['price'],
            lsur_z_aligned=lsur_z_aligned,
            cvd_aligned=cvd_aligned,
            oi_percentile=oi_percentile,
            funding_aligned=funding_aligned,
            trend_state=trend_state,
            rsi_aligned=rsi_history,
            ema_fast_aligned=ema_trend['ema_fast'],
            bb_pctb_aligned=bb_pctb,
            donchian_aligned=donchian,
            macd_aligned=macd_history,
            timeframe=timeframe,
            oi_aligned=open_interest,
            ranging_threshold=ranging_threshold,
            trending_threshold=trending_threshold,
            enable_protection=enable_protection,
            symbol=formatted_symbol,
            use_dynamic_profiles=use_dynamic_profiles,
        )
        
        # 7 & 8. Composite Score (Market Pulse) v5 & History
        composite_score_history = IndicatorEngine.calculate_composite_score(
            price_data=data['price'],
            lsur_z_aligned=lsur_z_aligned,
            cvd_aligned=cvd_aligned,
            funding_aligned=funding_aligned,
            rsi_aligned=rsi_history,
            ema_fast_aligned=ema_trend['ema_fast'],
            bb_pctb_aligned=bb_pctb,
            oi_aligned=open_interest,
            timeframe=timeframe,
            symbol=formatted_symbol,
            use_dynamic_profiles=use_dynamic_profiles,
        )
        composite_score = composite_score_history[-1]['value'] if composite_score_history else 50.0

        # 9. Market Regime Detection History
        market_regime_history = IndicatorEngine.calculate_market_regime_history(
            price_data=data['price'],
            cvd_aligned=cvd_aligned
        )
        
        return {
            "symbol": formatted_symbol,
            "data": {
                "price": df_price.to_dict('records') if not df_price.empty else [],
                "funding": funding_aligned
            },
            "indicators": {
                "lsur_z_score": lsur_z_score,
                "lsur_history": ls_ratio_history,
                "lsur_z_history": lsur_z_aligned,
                "lsur_markers": confluence_markers,
                "cvd_history": cvd_aligned,
                "open_interest": open_interest,
                "oi_percentile": oi_percentile,
                "ema_fast": ema_trend['ema_fast'],
                "ema_slow": ema_trend['ema_slow'],
                "trend_state": trend_state,
                "rsi_history": rsi_history,
                "market_regime": market_regime,
                "market_regime_history": market_regime_history,
                "composite_score": composite_score,
                "composite_score_history": composite_score_history,
                "exchange_breakdown": fetcher.latest_oi_breakdown
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
executor = ExecutionHandler(get_fetcher().exchange, dry_run=True)

@app.get("/quant/smart-params/{symbol}")
def get_smart_grid_params(symbol: str, duration_days: int = 0):
    """
    Returns AI-suggested Grid Parameters based on Liquidity Walls (Live) 
    or Historical Volatility (Backtest).
    """
    formatted_symbol = symbol.replace('-', '/')
    try:
        fetcher = get_fetcher()
        
        if duration_days > 0:
            import time
            # Backtest Mode: Establish range from the starting point in the past
            end_time = int(time.time() * 1000)
            start_time = end_time - (duration_days * 24 * 3600 * 1000)
            
            history = fetcher.fetch_history(formatted_symbol, start_time, end_time, '1h')
            if not history:
                raise HTTPException(status_code=404, detail="No historical data found for duration")
            
            start_price = history[0]['close']
            current_price = history[-1]['close']
            
            # Volatility mapping logic based on duration and asset class
            vol_factor = 0.03 if duration_days <= 3 else (0.06 if duration_days <= 7 else 0.125)
            if 'BTC' not in symbol and 'ETH' not in symbol:
                vol_factor *= 1.5 # Altcoins generally fluctuate more
                
            # Range encompassing both the historical start price and the current price
            min_price = min(start_price, current_price)
            max_price = max(start_price, current_price)
                
            lower_price = min_price * (1 - vol_factor)
            upper_price = max_price * (1 + vol_factor)
            z_score = 0.0 # Sentiment uncalculated for that specific exact split second
            
        else:
            # 1. Fetch needed data (Live Mode)
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
        fetcher = get_fetcher()
        ticker = fetcher.binance.fetch_ticker(formatted_symbol)
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
        fetcher = get_fetcher()
        ticker = fetcher.binance.fetch_ticker(formatted_symbol)
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
    fee_rate: float = 0.0008 # 0.08% default spot fee
    is_ai_mode: bool = False
    ranging_threshold: int = 3
    trending_threshold: int = 3
    enable_protection: bool = False
    use_dynamic_profiles: bool = True

@app.post("/quant/backtest")
def run_backtest(params: BacktestParams):
    try:
        formatted_symbol = params.symbol.replace('-', '/')
        fetcher = get_fetcher()
        
        # 1. Fetch Price History
        end_time = int(time.time() * 1000)
        start_time = end_time - (params.duration_days * 24 * 60 * 60 * 1000)
        
        history = fetcher.fetch_history(formatted_symbol, start_time, end_time, '1h')
        
        if not history:
             raise HTTPException(status_code=404, detail="No historical data found")

        # 2. Fetch AI Indicators History if AI mode is ON
        # In a real heavy backtester, we'd cache this heavily or pull from DB.
        # For our lightweight demo, we fetch or compute on the fly.
        regime_data = []
        pulse_data = []
        
        # Simple LSUR fallback for non-AI mode
        hours_needed = params.duration_days * 24
        lsur_raw = fetcher.fetch_long_short_ratio(formatted_symbol, period='1H', limit=hours_needed + 50) 
        
        import pandas as pd
        import numpy as np
        
        lsur_df = pd.DataFrame(lsur_raw)
        if not lsur_df.empty:
            lsur_df['value'] = lsur_df['value'].astype(float)
            lsur_df = lsur_df.sort_values('time')
            window = 20
            lsur_df['mean'] = lsur_df['value'].rolling(window=window).mean()
            lsur_df['std'] = lsur_df['value'].rolling(window=window).std()
            lsur_df['z_score'] = (lsur_df['value'] - lsur_df['mean']) / lsur_df['std']
            sentiment_data = lsur_df[['time', 'z_score']].dropna().rename(columns={'z_score': 'value'}).to_dict('records')
        else:
            sentiment_data = []

        if params.is_ai_mode:
            # Reusing the existing calculation pipelines
            taker_vol_raw = fetcher.fetch_taker_volume(formatted_symbol, period='1h', limit=hours_needed + 50)
            
            # Align CVD
            df_price = pd.DataFrame(history)
            df_price.sort_values('time', inplace=True)
            
            if taker_vol_raw:
                cvd_raw = IndicatorEngine.calculate_cvd_history(taker_vol_raw)
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
                
            regime_history_full = IndicatorEngine.calculate_market_regime_history(
                price_data=history,
                cvd_aligned=cvd_aligned
            )
            # Map for quick O(1) time lookups
            regime_data = {r['time']: r for r in regime_history_full}
            
            # (Optional: Also calculate Pulse for visual backtest overlay)
            # pulse_score_full = IndicatorEngine.calculate_composite_score_history(...)
            # pulse_data = {p['time']: p['value'] for p in pulse_score_full}

        # 3. Init Bot
        bot = GridBot(
            params.symbol, 
            params.lower_price, 
            params.upper_price, 
            params.grid_count, 
            params.investment
        )
        
        # 4. Run Backtest
        tester = Backtester(
            bot, 
            history, 
            sentiment_data=sentiment_data, 
            regime_data=regime_data,
            enable_protection=params.enable_protection,
            fee_rate=params.fee_rate
        )
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
                "total_trades": len(result['trades']),
                "total_fees_paid": result.get("total_fees_paid", 0.0)
            },
            "ai_metrics": result.get("ai_metrics", {}),
            "equity_curve": result['equity'],
            "trades": result['trades'] # Return all trades for full details
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# --- Signal-Driven Backtesting API (v2) ---
from api.quant.signal_backtester import SignalBacktester
from api.quant.signal_strategy import SignalStrategyConfig

class SignalBacktestParams(BaseModel):
    symbol: str = 'BTC/USDT'
    investment: float = 10000.0
    duration_days: int = 30
    timeframe: str = '1h'
    # Risk & Position Management
    risk_per_trade_pct: float = 2.0
    take_profit_pct: float = 4.0
    stop_loss_pct: float = 2.0
    trailing_stop_pct: float = 1.5
    trailing_activation_pct: float = 1.0
    max_positions: int = 3
    fee_rate: float = 0.0008
    allow_short: bool = True
    reverse_on_signal: bool = True
    # Confluence Signal Tuning
    ranging_threshold: int = 3
    trending_threshold: int = 3
    enable_protection: bool = True
    use_dynamic_profiles: bool = True

@app.post("/quant/signal-backtest")
def run_signal_backtest(params: SignalBacktestParams):
    """
    Run a Signal-driven backtest using confluence signals as entry triggers,
    with TP/SL/Trailing Stop position management.
    Supports both Long and Short positions.
    """
    try:
        formatted_symbol = params.symbol.replace('-', '/')
        
        # 1. Fetch exactly the same data as the main page chart to ensure 100% signal consistency
        # We use limit=1000 to match the main page's warmup period perfectly.
        market_res = get_market_data(
            symbol=params.symbol,
            timeframe=params.timeframe,
            limit=1000,
            ranging_threshold=params.ranging_threshold,
            trending_threshold=params.trending_threshold,
            enable_protection=params.enable_protection,
            use_dynamic_profiles=params.use_dynamic_profiles
        )

        history = market_res["data"]["price"]
        confluence_markers = market_res["indicators"]["lsur_markers"]

        if not history:
            raise HTTPException(status_code=404, detail="No historical data found")

        # 2. Compute actual start time for the backtest
        import time
        end_time = int(time.time() * 1000)
        actual_start_time = end_time - (params.duration_days * 24 * 3600 * 1000)

        # 4. Build Config & Run Signal Backtester
        config = SignalStrategyConfig(
            symbol=formatted_symbol,
            investment=params.investment,
            risk_per_trade_pct=params.risk_per_trade_pct,
            take_profit_pct=params.take_profit_pct,
            stop_loss_pct=params.stop_loss_pct,
            trailing_stop_pct=params.trailing_stop_pct,
            trailing_activation_pct=params.trailing_activation_pct,
            max_positions=params.max_positions,
            fee_rate=params.fee_rate,
            allow_short=params.allow_short,
            reverse_on_signal=params.reverse_on_signal,
        )
        config.validate()

        # Filter back down to actual requested duration for the backtest
        actual_start_sec = actual_start_time / 1000
        backtest_history = [c for c in history if c['time'] >= actual_start_sec]
        backtest_markers = [m for m in confluence_markers if m['time'] >= actual_start_sec]

        tester = SignalBacktester(config, backtest_history, backtest_markers)
        result = tester.run()

        # 5. Build Response
        initial = params.investment
        final = result['final_balance']
        pnl = final - initial
        pnl_percent = (pnl / initial) * 100

        return {
            "metrics": {
                "initial_balance": initial,
                "final_balance": round(final, 2),
                "pnl": round(pnl, 2),
                "pnl_percent": round(pnl_percent, 2),
                "total_trades": result['metrics']['total_trades'],
                "win_rate": result['metrics']['win_rate'],
                "winning_trades": result['metrics']['winning_trades'],
                "losing_trades": result['metrics']['losing_trades'],
                "avg_win_pct": result['metrics']['avg_win_pct'],
                "avg_loss_pct": result['metrics']['avg_loss_pct'],
                "profit_factor": result['metrics']['profit_factor'],
                "max_drawdown_pct": result['metrics']['max_drawdown_pct'],
                "sharpe_ratio": result['metrics']['sharpe_ratio'],
                "total_fees_paid": result['total_fees_paid'],
            },
            "equity_curve": result['equity'],
            "trades": result['trades'],
            "signals_used": backtest_markers,
            "positions": result['positions'],
            "price_data": backtest_history,
            "debug_history_len": len(history),
            "debug_markers_len": len(confluence_markers)
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
