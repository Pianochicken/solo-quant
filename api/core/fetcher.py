import ccxt
import pandas as pd
import time
from typing import Tuple, Dict

class DataFetcher:
    """
    SoloQuant Data Handler (OKX Edition).
    """
    def __init__(self):
        self.exchange = ccxt.okx()
        
    def fetch_market_data(self, symbol: str, timeframe: str = '1d', limit: int = 90) -> Dict:
        """
        Fetches OHLCV (Spot) and Funding Rate (Perp) History.
        """
        # 1. Determine Symbols
        # User requests "BTC/USDT" (Spot). 
        # Price -> "BTC/USDT"
        # Funding -> "BTC/USDT:USDT" (Perp)
        
        ohlcv_symbol = symbol
        funding_symbol = symbol
        if '/' in symbol and ':' not in symbol:
             funding_symbol = f"{symbol}:USDT"

        def fetch_paginated(fetch_func, target_symbol, target_limit, is_ohlcv=True):
            collected = []
            max_per_req = 100 if not is_ohlcv else 300
            
            while len(collected) < target_limit:
                remaining = target_limit - len(collected)
                this_limit = min(remaining, max_per_req)
                
                params = {}
                if collected:
                    oldest_ts = collected[0][0] if is_ohlcv else collected[0]['timestamp']
                    params = {'after': oldest_ts}
                
                try:
                    if is_ohlcv:
                        batch = fetch_func(target_symbol, timeframe=timeframe, limit=max_per_req, params=params)
                    else:
                        batch = fetch_func(target_symbol, limit=max_per_req, params=params)
                    
                    if not batch:
                        break
                        
                    collected = batch + collected
                    
                    if len(batch) < 2: 
                        break
                        
                    time.sleep(0.1)
                    
                except Exception as e:
                    print(f"Pagination error for {target_symbol}: {e}")
                    break
                    
            return collected[-limit:]

        try:
            # 1. Fetch OHLCV (Spot Price)
            # We use the paginated helper adapted for our specific inputs
            # Actually, let's just inline the loops for clarity as before or use the helper with symbol arg.
            # The helper above takes `target_symbol`.
            
            ohlcv = fetch_paginated(self.exchange.fetch_ohlcv, ohlcv_symbol, limit, is_ohlcv=True)
            
            # Format Price Data
            price_data = [
                {
                    "time": int(x[0] / 1000), 
                    "open": x[1], "high": x[2], "low": x[3], "close": x[4], "volume": x[5]
                }
                for x in ohlcv
            ]
            
            # 2. Fetch Funding Rate (Perp)
            funding = fetch_paginated(self.exchange.fetch_funding_rate_history, funding_symbol, limit, is_ohlcv=False)

            # --- Data Alignment Logic (Upsampling) ---
            df_price_times = pd.DataFrame([x[0] for x in ohlcv], columns=['timestamp'])
            df_funding = pd.DataFrame(funding)
            
            # Ensure sorting
            df_price_times.sort_values('timestamp', inplace=True)
            df_funding.sort_values('timestamp', inplace=True)
            
            if not df_funding.empty:
                merged = pd.merge_asof(
                    df_price_times, 
                    df_funding[['timestamp', 'fundingRate']], 
                    on='timestamp', 
                    direction='backward'
                )
                merged['fundingRate'] = merged['fundingRate'].fillna(0)
                
                funding_data = [
                    {
                        "time": int(row['timestamp'] / 1000),
                        "value": row['fundingRate'] * 100
                    }
                    for _, row in merged.iterrows()
                ]
            else:
                 funding_data = []
            
            return {
                "price": price_data,
                "funding": funding_data
            }
            
        except Exception as e:
            print(f"Error fetching data from OKX: {e}")
            raise e

    def fetch_history(self, symbol: str, start_time: int, end_time: int, timeframe: str = '1h') -> List[Dict]:
        """
        Fetches historical OHLCV data for backtesting.
        start_time, end_time: Timestamp in ms.
        """
        all_ohlcv = []
        current_since = start_time
        
        while current_since < end_time:
            try:
                # CCXT fetch_ohlcv(symbol, timeframe, since, limit)
                # We limit to 100 per request to be safe, loops until end_time
                batch = self.exchange.fetch_ohlcv(symbol, timeframe, since=current_since, limit=100)
                if not batch:
                    break
                
                all_ohlcv.extend(batch)
                
                # Update since to the last timestamp + 1 timeframe (approx) or just last timestamp + 1ms
                last_ts = batch[-1][0]
                if last_ts >= end_time:
                    break
                    
                current_since = last_ts + 1
                time.sleep(self.exchange.rateLimit / 1000) # Respect rate limits
                
            except Exception as e:
                print(f"History Fetch Error: {e}")
                break
                
        # Filter strictly within range and format
        formatted = [
            {
                "time": int(x[0] / 1000), 
                "open": x[1], "high": x[2], "low": x[3], "close": x[4], "volume": x[5]
            }
            for x in all_ohlcv if start_time <= x[0] <= end_time
        ]
        return formatted

    def fetch_open_interest(self, symbol: str, limit: int = 90, timeframe: str = '1h') -> list:
        """
        Fetches Open Interest History from OKX.
        """
        # Logic: If Spot (no :), convert to Perp (add :USDT) to get OI
        if '/' in symbol and ':' not in symbol:
            symbol = f"{symbol}:USDT"

        try:
            oi_data = self.exchange.fetch_open_interest_history(symbol, timeframe, limit=limit)
            return [
                {
                    "time": int(item['timestamp'] / 1000),
                    "value": float(item.get('openInterest', item.get('oi', 0))) 
                }
                for item in oi_data
            ]
        except Exception as e:
             print(f"Failed to fetch OI history: {e}")
             return []
