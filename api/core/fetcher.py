import ccxt
import pandas as pd
import time
import concurrent.futures
from typing import Tuple, Dict, List

class DataFetcher:
    """
    SoloQuant Data Handler (OKX + Binance Aggregator Edition).
    """
    def __init__(self):
        self.okx = ccxt.okx()
        self.binance = ccxt.binance({
            'options': {
                'defaultType': 'future',
            }
        })
        self.exchange = self.okx  # Fallback target for existing Spot OHLCV logic
        self.cache = {}  # In-memory cache for historical data
        self.latest_oi_breakdown = {"binance": 0, "okx": 0, "total": 0}

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
            funding_limit = max(limit * 3, 300)
            
            if cache_key_funding in self.cache:
                # Fast update: fetch last 10 funding rates
                recent_funding = fetch_paginated(self.exchange.fetch_funding_rate_history, funding_symbol, 10, is_ohlcv=False)
                self.cache[cache_key_funding] = self._merge_history(self.cache[cache_key_funding], recent_funding, time_key='timestamp')
            else:
                funding = fetch_paginated(self.exchange.fetch_funding_rate_history, funding_symbol, funding_limit, is_ohlcv=False)
                if funding:  # Only cache if we actually got data (avoid caching empty on transient errors)
                    self.cache[cache_key_funding] = funding

            funding_to_align = self.cache.get(cache_key_funding, [])

            # --- Data Alignment Logic (Upsampling) ---
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
        Aggregates data from OKX Rubik API and Binance USDⓈ-M Futures API.
        """
        ccy = symbol.split('/')[0] if '/' in symbol else symbol.split('-')[0]
        cache_key = f"taker_vol_agg_{ccy}_{period}"
        
        if cache_key in self.cache:
            # Short-circuit incremental fetch
            limit_to_fetch = min(limit, 20)
        else:
            limit_to_fetch = limit

        def fetch_okx():
            # OKX Rubik Taker Volume strictly supports: 5m, 1H, 1D.
            okx_period = '5m'
            p_lower = period.lower()
            if p_lower in ['1h', '2h', '4h', '6h', '8h', '12h']:
                okx_period = '1H'
            elif p_lower in ['1d', '2d', '3d', '1w', '1M']:
                okx_period = '1D'
                
            if not hasattr(self.okx, 'publicGetRubikStatTakerVolume'):
                return []
                
            max_pages = min((limit_to_fetch + 99) // 100, 5)
            results = []
            end_ts = None
            
            for page in range(max_pages):
                params = {'ccy': ccy, 'instType': 'CONTRACTS', 'period': okx_period}
                if end_ts is not None:
                    params['end'] = str(end_ts)
                try:
                    res = self.okx.publicGetRubikStatTakerVolume(params)
                    if res.get('code') != '0': break
                    data = res.get('data', [])
                    if not data: break
                    
                    for item in data:
                        results.append({"time": int(int(item[0])/1000), "sell_vol": float(item[1]), "buy_vol": float(item[2])})
                        
                    earliest_ts = min(int(item[0]) for item in data)
                    if end_ts is not None and earliest_ts >= end_ts: break
                    end_ts = earliest_ts - 1
                    if len(data) < 100: break
                    if page < max_pages - 1: time.sleep(0.2)
                except Exception as e:
                    print(f"OKX Taker Vol Error: {e}")
                    break
            return results

        def fetch_binance():
            binance_period = '5m'
            p_lower = period.lower()
            if p_lower in ['1h', '2h', '4h', '6h', '8h', '12h']: binance_period = '1h'
            elif p_lower in ['1d', '2d', '3d', '1w', '1M']: binance_period = '1d'
                
            binance_symbol = f"{ccy}USDT"
            max_pages = min((limit_to_fetch + 499) // 500, 3)
            results = []
            end_ts = None
            
            for page in range(max_pages):
                params = {'symbol': binance_symbol, 'period': binance_period, 'limit': min(limit_to_fetch, 500)}
                if end_ts is not None:
                    params['endTime'] = int(end_ts)
                try:
                    res = self.binance.fapidataGetTakerlongshortratio(params)
                    if not isinstance(res, list) or not res: break
                    
                    for item in res:
                        results.append({"time": int(int(item['timestamp'])/1000), "sell_vol": float(item['sellVol']), "buy_vol": float(item['buyVol'])})
                        
                    earliest_ts = min(int(item['timestamp']) for item in res)
                    if end_ts is not None and earliest_ts >= end_ts: break
                    end_ts = earliest_ts - 1
                    if len(res) < 500: break
                except Exception as e:
                    print(f"Binance Taker Vol Error: {e}")
                    break
            return results

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                f_okx = executor.submit(fetch_okx)
                f_bin = executor.submit(fetch_binance)
                okx_data = f_okx.result()
                bin_data = f_bin.result()
                
            if not okx_data and not bin_data:
                return []
                
            df_okx = pd.DataFrame(okx_data) if okx_data else pd.DataFrame(columns=['time', 'sell_vol', 'buy_vol'])
            df_bin = pd.DataFrame(bin_data) if bin_data else pd.DataFrame(columns=['time', 'sell_vol', 'buy_vol'])
            
            # Align by time using binance as basis if it has more tracking, or just concatenate and group
            # Taker Volume is discrete per period, so grouping by approximated time is easiest
            merged = pd.concat([df_okx, df_bin])
            if merged.empty: return []
            
            # Since OKX and Binance might have slight timestamp differences for the same 5m/1h candle 
            # (e.g., 1700000000 vs 1700000001), we round the time to the nearest period interval.
            period_seconds = 300 # default 5m
            if 'h' in period.lower() or 'H' in period: period_seconds = 3600
            elif 'd' in period.lower() or 'D' in period: period_seconds = 86400
            
            merged['rounded_time'] = (merged['time'] // period_seconds) * period_seconds
            
            # Group by rounded time and sum volumes
            agg_df = merged.groupby('rounded_time').agg({
                'sell_vol': 'sum',
                'buy_vol': 'sum'
            }).reset_index()
            
            agg_df.rename(columns={'rounded_time': 'time'}, inplace=True)
            agg_df.sort_values('time', inplace=True)
            
            unique = agg_df.to_dict('records')
            
            if cache_key in self.cache:
                self.cache[cache_key] = self._merge_history(self.cache[cache_key], unique)
            else:
                self.cache[cache_key] = unique
                
            return self.cache[cache_key][-limit:]
            
        except Exception as e:
            print(f"Failed to fetch Aggregated Taker Volume: {e}")
            return []

    def fetch_open_interest(self, symbol: str, limit: int = 90, timeframe: str = '1h') -> list:
        """
        Fetches Open Interest History from OKX and Binance.
        Sums up the OI values across both exchanges for a global metric.
        """
        ccy = symbol.split('/')[0] if '/' in symbol else symbol.split('-')[0]
        binance_symbol = f"{ccy}/USDT:USDT"
        
        # Keep original OKX logic handling
        if '/' in symbol and ':' not in symbol: okx_symbol = f"{symbol}:USDT"
        else: okx_symbol = symbol
        
        cache_key = f"oi_agg_{symbol}_{timeframe}"
        if cache_key in self.cache: limit_to_fetch = min(limit, 20)
        else: limit_to_fetch = limit

        def fetch_okx():
            try:
                per_page = 100
                max_pages = min((limit_to_fetch + per_page - 1) // per_page, 3)
                all_data = []
                since = None
                for page in range(max_pages):
                    params = {}
                    if since: params['until'] = since
                    res = self.okx.fetch_open_interest_history(okx_symbol, timeframe, limit=per_page, params=params)
                    if not res: break
                    for item in res:
                        all_data.append({"time": int(item['timestamp']/1000), "value": float(item.get('openInterestValue') or item.get('openInterest') or item.get('oi') or 0)})
                    earliest_ts = min(item['timestamp'] for item in res)
                    if since and earliest_ts >= since: break
                    since = earliest_ts - 1
                    if len(res) < per_page: break
                    if page < max_pages - 1: time.sleep(0.2)
                return all_data
            except Exception as e:
                print(f"OKX OI Error: {e}")
                return []

        def fetch_binance():
            try:
                per_page = 500
                max_pages = min((limit_to_fetch + per_page - 1) // per_page, 2)
                all_data = []
                since = None
                for page in range(max_pages):
                    params = {}
                    if since: params['endTime'] = since
                    res = self.binance.fetch_open_interest_history(binance_symbol, timeframe, limit=per_page, params=params)
                    if not res: break
                    for item in res:
                        all_data.append({"time": int(item['timestamp']/1000), "value": float(item.get('openInterestValue') or item.get('openInterest') or item.get('oi') or 0)})
                    earliest_ts = min(item['timestamp'] for item in res)
                    if since and earliest_ts >= since: break
                    since = earliest_ts - 1
                    if len(res) < per_page: break
                return all_data
            except Exception as e:
                print(f"Binance OI Error: {e}")
                return []

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                f_okx = executor.submit(fetch_okx)
                f_bin = executor.submit(fetch_binance)
                okx_data, bin_data = f_okx.result(), f_bin.result()
            
            df_okx = pd.DataFrame(okx_data) if okx_data else pd.DataFrame(columns=['time', 'value'])
            df_bin = pd.DataFrame(bin_data) if bin_data else pd.DataFrame(columns=['time', 'value'])
            
            dfs_to_concat = []
            if not df_okx.empty: dfs_to_concat.append(df_okx)
            if not df_bin.empty: dfs_to_concat.append(df_bin)
            
            if not dfs_to_concat:
                return []
                
            merged = pd.concat(dfs_to_concat)
            
            # Save latest proportions for UI Visualization
            latest_binance = float(df_bin.iloc[-1]['value']) if not df_bin.empty else 0
            latest_okx = float(df_okx.iloc[-1]['value']) if not df_okx.empty else 0
            self.latest_oi_breakdown = {
                "binance": latest_binance,
                "okx": latest_okx,
                "total": latest_binance + latest_okx
            }

            period_seconds = 3600
            if 'm' in timeframe.lower(): period_seconds = int(timeframe.lower().replace('m', '')) * 60
            elif 'd' in timeframe.lower(): period_seconds = 86400
            
            merged['rounded_time'] = (merged['time'] // period_seconds) * period_seconds
            agg_df = merged.groupby('rounded_time')['value'].sum().reset_index()
            agg_df.rename(columns={'rounded_time': 'time'}, inplace=True)
            agg_df.sort_values('time', inplace=True)
            
            unique = agg_df.to_dict('records')
            if cache_key in self.cache: self.cache[cache_key] = self._merge_history(self.cache[cache_key], unique)
            else: self.cache[cache_key] = unique
            return self.cache[cache_key][-limit:]
        except Exception as e:
            print(f"Agg OI Error: {e}")
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
        Fetches 'Long/Short Account Ratio' from OKX Rubik and Binance Futures.
        Uses ThreadPoolExecutor to aggregate the values globally.
        """
        ccy = symbol.split('/')[0] if '/' in symbol else symbol.split('-')[0]
        cache_key = f"lsr_agg_{ccy}_{period}"
        limit_to_fetch = min(limit, 20) if cache_key in self.cache else limit
        
        def fetch_okx():
            try:
                okx_period = '5m'
                p_lower = period.lower()
                if p_lower in ['1h', '2h', '4h', '6h', '8h', '12h']: okx_period = '1H'
                elif p_lower in ['1d', '2d', '3d', '1w', '1m']: okx_period = '1D'
                
                if not hasattr(self.okx, 'publicGetRubikStatContractsLongShortAccountRatio'): return []
                res = self.okx.publicGetRubikStatContractsLongShortAccountRatio({'ccy': ccy, 'period': okx_period, 'limit': min(limit_to_fetch, 100)})
                if res.get('code') != '0': return []
                data = res.get('data', [])
                results = []
                for item in data:
                    if isinstance(item, list): ts, ratio = item[0], item[1]
                    elif isinstance(item, dict): ts, ratio = item['ts'], item['ratio']
                    else: continue
                    results.append({"time": int(int(ts)/1000), "value": float(ratio)})
                return results
            except Exception as e:
                print(f"OKX LSR Error: {e}")
                return []
                
        def fetch_binance():
            try:
                max_pages = min((limit_to_fetch + 499) // 500, 2)
                results = []
                end_ts = None
                
                binance_period = '5m'
                p_lower = period.lower()
                if p_lower in ['1h', '2h', '4h', '6h', '8h', '12h']: binance_period = '1h'
                elif p_lower in ['1d', '2d', '3d', '1w', '1M']: binance_period = '1d'
                
                for page in range(max_pages):
                    params = {'symbol': f"{ccy}USDT", 'period': binance_period, 'limit': min(limit_to_fetch, 500)}
                    if end_ts: params['endTime'] = int(end_ts)
                    res = self.binance.fapidataGetToplongshortaccountratio(params)
                    if not isinstance(res, list) or not res: break
                    for item in res:
                        results.append({"time": int(int(item['timestamp'])/1000), "value": float(item['longShortRatio'])})
                    earliest_ts = min(int(item['timestamp']) for item in res)
                    if end_ts and earliest_ts >= end_ts: break
                    end_ts = earliest_ts - 1
                    if len(res) < 500: break
                return results
            except Exception as e:
                print(f"Binance LSR Error: {e}")
                return []
                
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                f_okx = executor.submit(fetch_okx)
                f_bin = executor.submit(fetch_binance)
                okx_data, bin_data = f_okx.result(), f_bin.result()
                
            df_okx = pd.DataFrame(okx_data) if okx_data else pd.DataFrame(columns=['time', 'value'])
            df_bin = pd.DataFrame(bin_data) if bin_data else pd.DataFrame(columns=['time', 'value'])
            
            dfs_to_concat = []
            if not df_okx.empty: dfs_to_concat.append(df_okx)
            if not df_bin.empty: dfs_to_concat.append(df_bin)
            
            if not dfs_to_concat:
                return []
                
            merged = pd.concat(dfs_to_concat)

            period_seconds = 300
            if 'h' in period.lower() or 'H' in period: period_seconds = 3600
            elif 'd' in period.lower() or 'D' in period: period_seconds = 86400
            
            merged['rounded_time'] = (merged['time'] // period_seconds) * period_seconds
            agg_df = merged.groupby('rounded_time')['value'].mean().reset_index()
            agg_df.rename(columns={'rounded_time': 'time'}, inplace=True)
            agg_df.sort_values('time', inplace=True)
            
            unique = agg_df.to_dict('records')
            if cache_key in self.cache: self.cache[cache_key] = self._merge_history(self.cache[cache_key], unique)
            else: self.cache[cache_key] = unique
            return self.cache[cache_key][-limit:]
        except Exception as e:
            print(f"Agg LSR Error: {e}")
            return []
