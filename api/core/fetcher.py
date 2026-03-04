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
        self.cache = {}  # In-memory cache for historical data

    def _merge_history(self, cached: list, new_data: list, time_key: str = 'time') -> list:
        """
        Merges new fetched data into the cached data, overwriting overlapping timestamps 
        and appending new ones, keeping the array sorted by time.
        """
        # Convert cache to dict for O(1) updates
        merged_dict = {item[time_key]: item for item in cached}
        for item in new_data:
            merged_dict[item[time_key]] = item
            
        # Sort back to list
        return sorted(merged_dict.values(), key=lambda x: x[time_key])

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
                    
                    if len(batch) < 2 or len(collected) >= target_limit: 
                        break
                        
                    time.sleep(0.1)
                    
                except Exception as e:
                    print(f"Pagination error for {target_symbol}: {e}")
                    break
                    
            return collected[-limit:]

        cache_key_ohlcv = f"ohlcv_{ohlcv_symbol}_{timeframe}"
        cache_key_funding = f"funding_{funding_symbol}"

        try:
            # 1. Fetch OHLCV (Spot Price)
            t0 = time.time()
            if cache_key_ohlcv in self.cache:
                # Fast update: only fetch the last 5 candles
                recent_ohlcv = fetch_paginated(self.exchange.fetch_ohlcv, ohlcv_symbol, 5, is_ohlcv=True)
                recent_price_data = [
                    {
                        "time": int(x[0] / 1000), 
                        "open": x[1], "high": x[2], "low": x[3], "close": x[4], "volume": x[5]
                    }
                    for x in recent_ohlcv
                ]
                self.cache[cache_key_ohlcv] = self._merge_history(self.cache[cache_key_ohlcv], recent_price_data)
            else:
                # Full fetch: build cache
                ohlcv = fetch_paginated(self.exchange.fetch_ohlcv, ohlcv_symbol, limit, is_ohlcv=True)
                self.cache[cache_key_ohlcv] = [
                    {
                        "time": int(x[0] / 1000), 
                        "open": x[1], "high": x[2], "low": x[3], "close": x[4], "volume": x[5]
                    }
                    for x in ohlcv
                ]
            
            price_data = self.cache[cache_key_ohlcv][-limit:]
            
            # 1.5 Prepare raw OHLCV for alignment (needed for funding alignment later)
            # Reconstruct the raw list of lists format for the alignment logic below
            raw_ohlcv_for_alignment = [[x['time']*1000, x['open'], x['high'], x['low'], x['close'], x['volume']] for x in price_data]


            # 2. Fetch Funding Rate (Perp)
            t1 = time.time()
            funding_limit = max(limit * 3, 300)
            
            if cache_key_funding in self.cache:
                # Fast update: fetch last 10 funding rates
                recent_funding = fetch_paginated(self.exchange.fetch_funding_rate_history, funding_symbol, 10, is_ohlcv=False)
                self.cache[cache_key_funding] = self._merge_history(self.cache[cache_key_funding], recent_funding, time_key='timestamp')
            else:
                funding = fetch_paginated(self.exchange.fetch_funding_rate_history, funding_symbol, funding_limit, is_ohlcv=False)
                self.cache[cache_key_funding] = funding

            funding_to_align = self.cache[cache_key_funding]

            # --- Data Alignment Logic (Upsampling) ---
            t2 = time.time()
            df_price_times = pd.DataFrame([x[0] for x in raw_ohlcv_for_alignment], columns=['timestamp'])
            # Ensure sorting
            df_price_times.sort_values('timestamp', inplace=True)
            
            if not funding_to_align:
                df_funding = pd.DataFrame(columns=['timestamp', 'fundingRate'])
            else:
                df_funding = pd.DataFrame(funding_to_align)
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
            
            cache_key = f"taker_vol_{ccy}_{period}"
            
            if cache_key in self.cache:
                # Incremental Update: Just fetch 1 page (100 items)
                max_pages = 1
            else:
                # Full Fetch
                max_pages = min((limit + 99) // 100, 5)  # Cap at 5 pages to avoid rate limiting
                
            all_results = []
            end_ts = None  # Start from latest
            
            for page in range(max_pages):
                params = {
                    'ccy': ccy,
                    'instType': 'CONTRACTS',
                    'period': period,
                }
                if end_ts is not None:
                    params['end'] = str(end_ts)
                
                t0 = time.time()
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
                
                if page < max_pages - 1:
                    time.sleep(0.5)  # Rate limit: avoid OKX 50011 Too Many Requests
            
            # Deduplicate and sort chronologically
            seen = set()
            unique = []
            for item in all_results:
                if item['time'] not in seen:
                    seen.add(item['time'])
                    unique.append(item)
            unique.sort(key=lambda x: x['time'])
            
            if cache_key in self.cache:
                self.cache[cache_key] = self._merge_history(self.cache[cache_key], unique)
            else:
                self.cache[cache_key] = unique
                
            return self.cache[cache_key][-limit:]
            
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
            cache_key = f"oi_{symbol}_{timeframe}"
            
            if cache_key in self.cache:
                # Incremental Update
                max_pages = 1
            else:
                # Full Fetch
                per_page = 100  # OKX typical max per request
                total_needed = limit
                pages_needed = (total_needed + per_page - 1) // per_page
                max_pages = min(pages_needed, 3)  # Cap at 3 pages to avoid rate limiting
            
            all_data = []
            per_page = 100
            since = None  # Start from latest, paginate backward
            
            for page in range(max_pages):
                params = {}
                if since is not None:
                    params['until'] = since  # Fetch data before this timestamp
                
                t0 = time.time()
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
                
                if page < max_pages - 1:
                    time.sleep(0.5)  # Rate limit: avoid OKX 50011 Too Many Requests
            
            # Deduplicate by time and sort chronologically
            seen_times = set()
            unique_data = []
            for item in all_data:
                if item['time'] not in seen_times:
                    seen_times.add(item['time'])
                    unique_data.append(item)
            
            unique_data.sort(key=lambda x: x['time'])
            
            if cache_key in self.cache:
                self.cache[cache_key] = self._merge_history(self.cache[cache_key], unique_data)
            else:
                self.cache[cache_key] = unique_data
                
            return self.cache[cache_key][-limit:]
            
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
            
            cache_key = f"lsr_{ccy}_{period}"
            
            fetch_limit = limit
            if cache_key in self.cache:
                 # Fast update
                 fetch_limit = min(50, limit)
                 
            # 2. Call OKX Implicit API
            # Endpoint: GET /api/v5/rubik/stat/contracts/long-short-account-ratio
            # Params: ccy=BTC, period=5m
            # CCXT method: publicGetRubikStatContractsLongShortAccountRatio
            if hasattr(self.exchange, 'publicGetRubikStatContractsLongShortAccountRatio'):
                response = self.exchange.publicGetRubikStatContractsLongShortAccountRatio({
                    'ccy': ccy,
                    'period': period,
                    'limit': fetch_limit
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
                        
                    results = results[::-1] # Reverse to chronological order
                    
                    if cache_key in self.cache:
                        self.cache[cache_key] = self._merge_history(self.cache[cache_key], results)
                    else:
                        self.cache[cache_key] = results
                        
                    return self.cache[cache_key][-limit:]
                
            return []
        except Exception as e:
            print(f"Failed to fetch Long/Short Ratio: {e}")
            return []
