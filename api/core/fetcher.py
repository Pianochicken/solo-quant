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
            # Funding rate is every 8h. To cover the same timespan as `limit` candles:
            # - 1D candles: need limit*3 funding entries
            # - 1H candles: need limit/8 but fetch more for safety
            funding_limit = max(limit * 3, 300)  # At least 300 to cover most ranges
            funding = fetch_paginated(self.exchange.fetch_funding_rate_history, funding_symbol, funding_limit, is_ohlcv=False)

            # --- Data Alignment Logic (Upsampling) ---
            df_price_times = pd.DataFrame([x[0] for x in ohlcv], columns=['timestamp'])
            # Ensure sorting
            df_price_times.sort_values('timestamp', inplace=True)
            
            if not funding:
                df_funding = pd.DataFrame(columns=['timestamp', 'fundingRate'])
            else:
                df_funding = pd.DataFrame(funding)
                if 'timestamp' in df_funding.columns:
                    df_funding.sort_values('timestamp', inplace=True)
            
            if not df_funding.empty and 'fundingRate' in df_funding.columns:
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

    def fetch_taker_volume(self, symbol: str, period: str = '5m', limit: int = 100) -> list:
        """
        Fetches Taker Buy/Sell Volume to calculate CVD.
        Uses OKX Rubik API: /api/v5/rubik/stat/taker-volume
        Paginates backward to get more historical data.
        """
        try:
            # 1. Parse Currency (e.g., BTC/USDT -> BTC)
            ccy = symbol.split('/')[0] if '/' in symbol else symbol.split('-')[0]
            
            if not hasattr(self.exchange, 'publicGetRubikStatTakerVolume'):
                return []
            
            all_results = []
            max_pages = min((limit + 99) // 100, 5)  # Cap at 5 pages to avoid rate limiting
            end_ts = None  # Start from latest
            
            for page in range(max_pages):
                params = {
                    'ccy': ccy,
                    'instType': 'CONTRACTS',
                    'period': period,
                }
                if end_ts is not None:
                    params['end'] = str(end_ts)
                
                response = self.exchange.publicGetRubikStatTakerVolume(params)
                
                if response.get('code') != '0':
                    print(f"OKX Taker Volume Error for {symbol} (ccy={ccy}, period={period}): {response}")
                    break

                data = response.get('data', [])
                if not data:
                    break
                
                for item in data:
                    # item: [ts, sellVol, buyVol]
                    all_results.append({
                        "time": int(int(item[0]) / 1000),
                        "sell_vol": float(item[1]),
                        "buy_vol": float(item[2])
                    })
                
                # Paginate backward: use the earliest timestamp in this batch
                earliest_ts = min(int(item[0]) for item in data)
                if end_ts is not None and earliest_ts >= end_ts:
                    break  # No more older data
                end_ts = earliest_ts - 1
                
                if len(data) < 100:
                    break  # Last page
                
                time.sleep(0.5)  # Rate limit: avoid OKX 50011 Too Many Requests
            
            # Deduplicate and sort chronologically
            seen = set()
            unique = []
            for item in all_results:
                if item['time'] not in seen:
                    seen.add(item['time'])
                    unique.append(item)
            unique.sort(key=lambda x: x['time'])
            return unique
            
        except Exception as e:
            print(f"Failed to fetch Taker Volume: {e}")
            return []

    def fetch_open_interest(self, symbol: str, limit: int = 90, timeframe: str = '1h') -> list:
        """
        Fetches Open Interest History from OKX with pagination.
        OKX returns max ~100 entries per request, so we paginate backward
        to get enough data to cover the full price chart range.
        """
        # Logic: If Spot (no :), convert to Perp (add :USDT) to get OI
        if '/' in symbol and ':' not in symbol:
            symbol = f"{symbol}:USDT"

        try:
            all_data = []
            # Calculate how many pages we need
            per_page = 100  # OKX typical max per request
            total_needed = limit
            pages_needed = (total_needed + per_page - 1) // per_page
            max_pages = min(pages_needed, 3)  # Cap at 3 pages to avoid rate limiting
            
            since = None  # Start from latest, paginate backward
            
            for page in range(max_pages):
                params = {}
                if since is not None:
                    params['until'] = since  # Fetch data before this timestamp
                
                oi_data = self.exchange.fetch_open_interest_history(
                    symbol, timeframe, limit=per_page, since=since, params=params
                )
                
                if not oi_data:
                    break
                
                page_results = [
                    {
                        "time": int(item['timestamp'] / 1000),
                        "value": float(item.get('openInterestValue') or item.get('openInterest') or item.get('oi') or 0)
                    }
                    for item in oi_data
                ]
                
                all_data.extend(page_results)
                
                # For next page, go further back in time
                # Find the earliest timestamp in this batch
                earliest_ts = min(item['timestamp'] for item in oi_data)
                
                if since is not None and earliest_ts >= since:
                    break  # No more older data available
                
                since = earliest_ts - 1  # Go back before the earliest point
                
                # If we got fewer results than requested, we've reached the API limit
                if len(oi_data) < per_page:
                    break
                
                time.sleep(0.5)  # Rate limit: avoid OKX 50011 Too Many Requests
            
            # Deduplicate by time and sort chronologically
            seen_times = set()
            unique_data = []
            for item in all_data:
                if item['time'] not in seen_times:
                    seen_times.add(item['time'])
                    unique_data.append(item)
            
            unique_data.sort(key=lambda x: x['time'])
            return unique_data
            
        except Exception as e:
             print(f"Failed to fetch OI history: {e}")
             return []

    def fetch_order_book_depth(self, symbol: str, limit: int = 400) -> Dict:
        """
        Fetches Order Book to visualize Liquidity Walls.
        Returns aggregated Bids and Asks.
        """
        try:
            # OKX Spot or Perp
            orderbook = self.exchange.fetch_order_book(symbol, limit=limit)
            return {
                "bids": orderbook['bids'], # [[price, amount], ...]
                "asks": orderbook['asks'],
                "timestamp": orderbook.get('timestamp', int(time.time() * 1000))
            }
        except Exception as e:
            print(f"Failed to fetch Order Book: {e}")
            return {"bids": [], "asks": [], "timestamp": int(time.time() * 1000)}

    def fetch_long_short_ratio(self, symbol: str, period: str = '5m', limit: int = 100) -> list:
        """
        Fetches 'Long/Short Account Ratio' from OKX Rubik (Trading Data) API.
        NOTE: CCXT does not have a unified endpoint for this, using implicit API.
        Symbol format for OKX Rubik: 'BTC' (ccy), not 'BTC/USDT'.
        """
        try:
            # 1. Parse Currency (e.g., BTC/USDT -> BTC)
            ccy = symbol.split('/')[0] if '/' in symbol else symbol.split('-')[0]
            
            # 2. Call OKX Implicit API
            # Endpoint: GET /api/v5/rubik/stat/contracts/long-short-account-ratio
            # Params: ccy=BTC, period=5m
            # CCXT method: publicGetRubikStatContractsLongShortAccountRatio
            if hasattr(self.exchange, 'publicGetRubikStatContractsLongShortAccountRatio'):
                response = self.exchange.publicGetRubikStatContractsLongShortAccountRatio({
                    'ccy': ccy,
                    'period': period,
                    'limit': limit
                })
                
                # Response format: {'code': '0', 'data': [{'ts': '...', 'ratio': '...'}, ...]}
                # Response format: {'code': '0', 'data': [['ts', 'ratio'], ...]} OR [{'ts': ..., 'ratio': ...}]
                if response['code'] == '0':
                    data = response['data']
                    results = []
                    
                    for item in data:
                        # Handle List format (common in V5 history)
                        if isinstance(item, list):
                            ts = item[0]
                            ratio = item[1]
                        # Handle Dict format
                        elif isinstance(item, dict):
                            ts = item['ts']
                            ratio = item['ratio']
                        else:
                            continue
                            
                        results.append({
                            "time": int(int(ts) / 1000),
                            "value": float(ratio)
                        })
                        
                    return results[::-1] # Reverse to chronological order
                
            return []
        except Exception as e:
            print(f"Failed to fetch Long/Short Ratio: {e}")
            return []
