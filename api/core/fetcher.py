import ccxt
import pandas as pd
import time
import concurrent.futures
from typing import Tuple, Dict, List, Optional
from datetime import datetime, timezone

from api.db.database import SessionLocal
from api.db import crud

class DataFetcher:
    """
    SoloQuant Data Handler with PostgreSQL Integration (Aggregator Edition).
    """
    def __init__(self):
        self.okx = ccxt.okx()
        self.binance = ccxt.binance({
            'options': {
                'defaultType': 'future',
            }
        })
        self.exchange = self.okx
        self.latest_oi_breakdown = {"binance": 0, "okx": 0, "total": 0}

    def _ms_to_dt(self, ms: int) -> datetime:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)

    def fetch_market_data(self, symbol: str, timeframe: str = '1d', limit: int = 90) -> Dict:
        """
        Fetches OHLCV (Spot) and Funding Rate (Perp) History.
        """
        # Use swap symbol for fetching OHLCV to ensure maximum history (often listed before spot)
        db_symbol = symbol
        swap_symbol = f"{symbol.split('/')[0]}-USDT-SWAP" if '/' in symbol else f"{symbol.split('-')[0]}-USDT-SWAP"
        fetch_symbol = swap_symbol
        funding_symbol = swap_symbol
        
        with SessionLocal() as db:
            db_ohlcv = crud.get_market_data(db, symbol=db_symbol, timeframe=timeframe, exchange="okx", limit=limit)
            db_ohlcv = [x for x in db_ohlcv if x.open is not None]
            
            is_full_fetch = len(db_ohlcv) < limit
            
            # Calculate missing candles to fill any time gaps
            missed_candles = 10
            if db_ohlcv:
                latest_ts = db_ohlcv[-1].timestamp.timestamp()
                first_ts = db_ohlcv[0].timestamp.timestamp()
                now_ts = time.time()
                
                tf_sec = 60
                tf_l = timeframe.lower()
                if 'm' in tf_l: tf_sec = int(tf_l.replace('m', '')) * 60
                elif 'h' in tf_l: tf_sec = int(tf_l.replace('h', '')) * 3600
                elif 'd' in tf_l: tf_sec = int(tf_l.replace('d', '')) * 86400
                elif 'w' in tf_l: tf_sec = int(tf_l.replace('w', '')) * 86400 * 7
                
                diff = now_ts - latest_ts
                span = latest_ts - first_ts
                expected_span = (len(db_ohlcv) - 1) * tf_sec
                
                # If there's a gap in the timeline (actual span > expected span), fetch the full limit again to patch it
                if span > expected_span + tf_sec:
                    is_full_fetch = True
                    missed_candles = limit
                elif diff > 0:
                    calc_missed = int((diff // tf_sec) + 2)
                    missed_candles = max(10, min(calc_missed, limit))
            
            # Only fetch delta if DB has enough data, otherwise fetch deeply backward                                                                                       
            target_limit_ohlcv = max(limit, 300) if is_full_fetch else missed_candles
            target_limit_funding = max(limit * 3, 300) if is_full_fetch else missed_candles * 3
            def fetch_paginated(fetch_func, target_symbol, target_limit, is_ohlcv=True):
                collected = []
                max_per_req = 100 if not is_ohlcv else 300
                while len(collected) < target_limit:
                    this_limit = min(target_limit - len(collected), max_per_req)
                    params = {}
                    if collected:
                        oldest_ts = collected[0][0] if is_ohlcv else collected[0]['timestamp']
                        params = {'after': oldest_ts}
                    try:
                        if is_ohlcv:
                            batch = fetch_func(target_symbol, timeframe=timeframe, limit=this_limit, params=params)
                        else:
                            batch = fetch_func(target_symbol, limit=this_limit, params=params)
                        
                        if not batch: break
                        collected = batch + collected
                        if len(batch) < 2 or len(collected) >= target_limit: break
                        time.sleep(0.1)
                    except Exception as e:
                        print(f"Pagination error for {target_symbol}: {e}")
                        break
                return collected[-target_limit:]

            try:
                ohlcv_batch = fetch_paginated(self.exchange.fetch_ohlcv, fetch_symbol, target_limit_ohlcv, is_ohlcv=True)
                if ohlcv_batch:
                    records = []
                    for x in ohlcv_batch:
                        records.append({
                            'timestamp': self._ms_to_dt(x[0]),
                            'exchange': 'okx',
                            'symbol': db_symbol,
                            'timeframe': timeframe,
                            'open': x[1], 'high': x[2], 'low': x[3], 'close': x[4], 'volume': x[5]
                        })
                    crud.upsert_market_data(db, records)
            except Exception as e:
                print(f"Error fetching OHLCV for {fetch_symbol}: {e}")

            try:
                funding_batch = fetch_paginated(self.exchange.fetch_funding_rate_history, funding_symbol, target_limit_funding, is_ohlcv=False)
                if funding_batch:
                    f_records = []
                    for x in funding_batch:
                        f_records.append({
                            'timestamp': self._ms_to_dt(x['timestamp']),
                            'exchange': 'okx',
                            'symbol': funding_symbol, 
                            'funding_rate': x['fundingRate']
                        })
                    crud.upsert_funding_rates(db, f_records)
            except Exception as e:
                print(f"Error fetching Funding for {funding_symbol}: {e}")

            final_ohlcv = crud.get_market_data(db, symbol=db_symbol, timeframe=timeframe, exchange="okx", limit=limit)
            price_data = []
            for x in final_ohlcv:
                if x.open is not None:
                    price_data.append({
                        "time": int(x.timestamp.timestamp()), 
                        "open": x.open, "high": x.high, "low": x.low, "close": x.close, "volume": x.volume
                    })

            funding_data = []
            if price_data:
                latest_funding = db.query(crud.FundingRate).filter(
                    crud.FundingRate.symbol == funding_symbol, 
                    crud.FundingRate.exchange == 'okx'
                ).order_by(crud.FundingRate.timestamp.desc()).limit(limit * 3).all()

                if latest_funding:
                    df_price_times = pd.DataFrame([x['time'] * 1000 for x in price_data], columns=['timestamp'])
                    df_price_times.sort_values('timestamp', inplace=True)
                    f_data = [{"timestamp": int(x.timestamp.timestamp() * 1000), "fundingRate": x.funding_rate} for x in latest_funding]
                    df_funding = pd.DataFrame(f_data)
                    df_funding.sort_values('timestamp', inplace=True)

                    merged = pd.merge_asof(
                        df_price_times, 
                        df_funding[['timestamp', 'fundingRate']], 
                        on='timestamp', 
                        direction='backward'
                    )
                    merged['fundingRate'] = merged['fundingRate'].fillna(0)
                    funding_data = [{"time": int(row['timestamp'] / 1000), "value": row['fundingRate'] * 100} for _, row in merged.iterrows()]

            return {"price": price_data, "funding": funding_data}

    def fetch_taker_volume(self, symbol: str, period: str = '5m', limit: int = 100) -> list:
        ccy = symbol.split('/')[0] if '/' in symbol else symbol.split('-')[0]
        binance_symbol = f"{ccy}USDT"
        db_symbol = symbol 
        
        with SessionLocal() as db:
            db_bin = crud.get_market_data(db, symbol=db_symbol, timeframe=period, exchange="binance", limit=limit)
            db_bin = [x for x in db_bin if x.taker_buy_vol is not None]
            
            missed_candles = 20
            if db_bin:
                latest_ts = db_bin[-1].timestamp.timestamp()
                first_ts = db_bin[0].timestamp.timestamp()
                now_ts = time.time()
                
                tf_sec = 300
                tf_l = period.lower()
                if 'm' in tf_l: tf_sec = int(tf_l.replace('m', '')) * 60
                elif 'h' in tf_l: tf_sec = int(tf_l.replace('h', '')) * 3600
                elif 'd' in tf_l: tf_sec = int(tf_l.replace('d', '')) * 86400
                
                diff = now_ts - latest_ts
                span = latest_ts - first_ts
                expected_span = (len(db_bin) - 1) * tf_sec
                
                if span > expected_span + tf_sec:
                    missed_candles = max(limit, 100)
                elif diff > 0:
                    calc_missed = int((diff // tf_sec) + 2)
                    missed_candles = max(20, min(calc_missed, limit))
            
            limit_to_fetch = missed_candles if len(db_bin) >= limit else max(limit, 100)

            def fetch_binance():
                binance_period = '5m'
                p_lower = period.lower()
                if p_lower in ['1h', '2h', '4h', '6h', '8h', '12h']: binance_period = '1h'
                elif p_lower in ['1d', '2d', '3d', '1w', '1m']: binance_period = '1d'
                
                max_pages = min((limit_to_fetch + 499) // 500, 3)
                end_ts = None
                records = []
                for page in range(max_pages):
                    params = {'symbol': binance_symbol, 'period': binance_period, 'limit': min(limit_to_fetch, 500)}
                    if end_ts is not None: params['endTime'] = int(end_ts)
                    try:
                        res = self.binance.fapidataGetTakerlongshortratio(params)
                        if not isinstance(res, list) or not res: break
                        for item in res:
                            records.append({
                                'timestamp': self._ms_to_dt(int(item['timestamp'])),
                                'exchange': 'binance',
                                'symbol': db_symbol,
                                'timeframe': period,
                                'taker_sell_vol': float(item['sellVol']),
                                'taker_buy_vol': float(item['buyVol'])
                            })
                        earliest_ts = min(int(item['timestamp']) for item in res)
                        if end_ts is not None and earliest_ts >= end_ts: break
                        end_ts = earliest_ts - 1
                        if len(res) < 500: break
                    except Exception as e: print(f"Error fetching data: {e}"); break
                
                if records:
                    with SessionLocal() as session:
                        crud.upsert_market_data(session, records)

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(fetch_binance).result()

            bin_data = crud.get_market_data(db, symbol=db_symbol, timeframe=period, exchange="binance", limit=limit)
            df_bin = pd.DataFrame([{ "time": int(x.timestamp.timestamp()), "sell_vol": x.taker_sell_vol or 0, "buy_vol": x.taker_buy_vol or 0 } for x in bin_data])
            
            merged = df_bin
            if merged.empty: return []

            period_seconds = 300
            if 'm' in period.lower(): period_seconds = int(period.lower().replace('m', '')) * 60
            elif 'h' in period.lower(): period_seconds = int(period.lower().replace('h', '')) * 3600
            elif 'd' in period.lower(): period_seconds = 86400
            
            merged['rounded_time'] = (merged['time'] // period_seconds) * period_seconds
            agg_df = merged.groupby('rounded_time').agg({'sell_vol': 'sum', 'buy_vol': 'sum'}).reset_index()
            agg_df.rename(columns={'rounded_time': 'time'}, inplace=True)
            agg_df.sort_values('time', inplace=True)
            return agg_df.to_dict('records')[-limit:]

    def fetch_open_interest(self, symbol: str, limit: int = 90, timeframe: str = '1h') -> list:
        ccy = symbol.split('/')[0] if '/' in symbol else symbol.split('-')[0]
        binance_symbol = f"{ccy}/USDT:USDT"
        okx_symbol = f"{symbol.split('/')[0]}-USDT-SWAP" if '/' in symbol else f"{symbol.split('-')[0]}-USDT-SWAP"
        db_symbol = symbol 
        
        with SessionLocal() as db:
            db_okx = crud.get_market_data(db, symbol=db_symbol, timeframe=timeframe, exchange="okx", limit=limit)
            db_okx = [x for x in db_okx if x.open_interest is not None]
            
            missed_candles = 20
            if db_okx:
                latest_ts = db_okx[-1].timestamp.timestamp()
                first_ts = db_okx[0].timestamp.timestamp()
                now_ts = time.time()
                
                tf_sec = 3600
                tf_l = timeframe.lower()
                if 'm' in tf_l: tf_sec = int(tf_l.replace('m', '')) * 60
                elif 'h' in tf_l: tf_sec = int(tf_l.replace('h', '')) * 3600
                elif 'd' in tf_l: tf_sec = int(tf_l.replace('d', '')) * 86400
                
                diff = now_ts - latest_ts
                span = latest_ts - first_ts
                expected_span = (len(db_okx) - 1) * tf_sec
                
                if span > expected_span + tf_sec:
                    missed_candles = max(limit, 100)
                elif diff > 0:
                    calc_missed = int((diff // tf_sec) + 2)
                    missed_candles = max(20, min(calc_missed, limit))
            
            limit_to_fetch = missed_candles if len(db_okx) >= limit else max(limit, 90)

            def fetch_okx():
                okx_tf = '5m'
                p_lower = timeframe.lower()
                if p_lower in ['1h', '2h', '4h', '6h', '8h', '12h']: okx_tf = '1H'
                elif p_lower in ['1d', '2d', '3d', '1w', '1m']: okx_tf = '1D'
                
                period_seconds = 3600
                if 'm' in timeframe.lower(): period_seconds = int(timeframe.lower().replace('m', '')) * 60
                elif 'h' in timeframe.lower(): period_seconds = int(timeframe.lower().replace('h', '')) * 3600
                elif 'd' in timeframe.lower(): period_seconds = 86400
                
                # Expand limit if we fetch '1h' to cover '4h'
                tf_ratio = max(1, period_seconds // 3600 if okx_tf == '1H' else 1)
                adjusted_limit = limit_to_fetch * tf_ratio
                
                per_page = 100
                max_pages = min((adjusted_limit + per_page - 1) // per_page, 5)
                since = None
                records = []
                for page in range(max_pages):
                    params = {}
                    if since: params['until'] = since
                    try:
                        res = self.okx.fetch_open_interest_history(okx_symbol, okx_tf, limit=per_page, params=params)
                        if not res: break
                        for item in res:
                            ts = int(item['timestamp'])
                            if (ts // 1000) % period_seconds != 0:
                                continue # ensure alignment with requested interval bounds
                            
                            val = float(item.get('openInterestValue') or item.get('openInterest') or item.get('oi') or 0)
                            records.append({
                                'timestamp': self._ms_to_dt(ts),
                                'exchange': 'okx',
                                'symbol': db_symbol,
                                'timeframe': timeframe,
                                'open_interest': val
                            })
                        earliest_ts = min(item['timestamp'] for item in res)
                        if since and earliest_ts >= since: break
                        since = earliest_ts - 1
                        if len(res) < per_page: break
                        if page < max_pages - 1: time.sleep(0.2)
                    except Exception as e: print(f"Error fetching data OKX: {e}"); break
                if records:
                    with SessionLocal() as session:
                        crud.upsert_market_data(session, records)

            def fetch_binance():
                per_page = 500
                max_pages = min((limit_to_fetch + per_page - 1) // per_page, 2)
                since = None
                records = []
                for page in range(max_pages):
                    params = {}
                    if since: params['endTime'] = since
                    try:
                        res = self.binance.fetch_open_interest_history(binance_symbol, timeframe, limit=per_page, params=params)
                        if not res: break
                        for item in res:
                            val = float(item.get('openInterestValue') or item.get('openInterest') or item.get('oi') or 0)
                            records.append({
                                'timestamp': self._ms_to_dt(item['timestamp']),
                                'exchange': 'binance',
                                'symbol': db_symbol,
                                'timeframe': timeframe,
                                'open_interest': val
                            })
                        earliest_ts = min(item['timestamp'] for item in res)
                        if since and earliest_ts >= since: break
                        since = earliest_ts - 1
                        if len(res) < per_page: break
                    except Exception as e: print(f"Error fetching data: {e}"); break
                if records:
                    with SessionLocal() as session:
                        crud.upsert_market_data(session, records)

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                executor.submit(fetch_okx)
                executor.submit(fetch_binance)

            okx_data = crud.get_market_data(db, symbol=db_symbol, timeframe=timeframe, exchange="okx", limit=limit)
            bin_data = crud.get_market_data(db, symbol=db_symbol, timeframe=timeframe, exchange="binance", limit=limit)

            df_okx = pd.DataFrame([{ "time": int(x.timestamp.timestamp()), "value": x.open_interest or 0 } for x in okx_data])
            df_bin = pd.DataFrame([{ "time": int(x.timestamp.timestamp()), "value": x.open_interest or 0 } for x in bin_data])
            
            if not df_bin.empty: self.latest_oi_breakdown["binance"] = float(df_bin.iloc[-1]['value'])
            if not df_okx.empty: self.latest_oi_breakdown["okx"] = float(df_okx.iloc[-1]['value'])
            self.latest_oi_breakdown["total"] = self.latest_oi_breakdown["binance"] + self.latest_oi_breakdown["okx"]

            merged = pd.concat([df_okx, df_bin])
            if merged.empty: return []

            period_seconds = 3600
            if 'm' in timeframe.lower(): period_seconds = int(timeframe.lower().replace('m', '')) * 60
            elif 'h' in timeframe.lower(): period_seconds = int(timeframe.lower().replace('h', '')) * 3600
            elif 'd' in timeframe.lower(): period_seconds = 86400
            
            merged['rounded_time'] = (merged['time'] // period_seconds) * period_seconds
            agg_df = merged.groupby('rounded_time')['value'].sum().reset_index()
            agg_df.rename(columns={'rounded_time': 'time'}, inplace=True)
            agg_df.sort_values('time', inplace=True)
            return agg_df.to_dict('records')[-limit:]

    def fetch_order_book_depth(self, symbol: str, limit: int = 400) -> Dict:
        """ Orderbook is live snapshot logic, untouched and un-stored. """
        try:
            orderbook = self.exchange.fetch_order_book(symbol, limit=limit)
            return {
                "bids": orderbook['bids'],
                "asks": orderbook['asks'],
                "timestamp": orderbook.get('timestamp', int(time.time() * 1000))
            }
        except Exception:
            return {"bids": [], "asks": [], "timestamp": int(time.time() * 1000)}

    def fetch_long_short_ratio(self, symbol: str, period: str = '5m', limit: int = 100) -> list:
        ccy = symbol.split('/')[0] if '/' in symbol else symbol.split('-')[0]
        binance_symbol = f"{ccy}USDT"
        db_symbol = symbol 
        
        with SessionLocal() as db:
            db_okx = crud.get_market_data(db, symbol=db_symbol, timeframe=period, exchange="okx", limit=limit)
            db_okx = [x for x in db_okx if x.long_short_ratio is not None]
            
            missed_candles = 20
            if db_okx:
                latest_ts = db_okx[-1].timestamp.timestamp()
                first_ts = db_okx[0].timestamp.timestamp()
                now_ts = time.time()
                
                tf_sec = 300
                tf_l = period.lower()
                if 'm' in tf_l: tf_sec = int(tf_l.replace('m', '')) * 60
                elif 'h' in tf_l: tf_sec = int(tf_l.replace('h', '')) * 3600
                elif 'd' in tf_l: tf_sec = int(tf_l.replace('d', '')) * 86400
                
                diff = now_ts - latest_ts
                span = latest_ts - first_ts
                expected_span = (len(db_okx) - 1) * tf_sec
                
                if span > expected_span + tf_sec:
                    missed_candles = max(limit, 100)
                elif diff > 0:
                    calc_missed = int((diff // tf_sec) + 2)
                    missed_candles = max(20, min(calc_missed, limit))
            
            limit_to_fetch = missed_candles if len(db_okx) >= limit else max(limit, 100)

            def fetch_okx():
                okx_period = '5m'
                p_lower = period.lower()
                if p_lower in ['1h', '2h', '4h', '6h', '8h', '12h']: okx_period = '1H'
                elif p_lower in ['1d', '2d', '3d', '1w', '1m']: okx_period = '1D'
                
                if not hasattr(self.okx, 'publicGetRubikStatContractsLongShortAccountRatio'): return
                records = []
                try:
                    res = self.okx.publicGetRubikStatContractsLongShortAccountRatio({'ccy': ccy, 'period': okx_period, 'limit': min(limit_to_fetch, 100)})
                    if res.get('code') == '0' and res.get('data'):
                        for item in res['data']:
                            ts, ratio = (item[0], item[1]) if isinstance(item, list) else (item['ts'], item['ratio'])
                            records.append({
                                'timestamp': self._ms_to_dt(int(ts)),
                                'exchange': 'okx',
                                'symbol': db_symbol,
                                'timeframe': period,
                                'long_short_ratio': float(ratio)
                            })
                except Exception: pass

                if records:
                    with SessionLocal() as session:
                        crud.upsert_market_data(session, records)

            def fetch_binance():
                binance_period = '5m'
                p_lower = period.lower()
                if p_lower in ['1h', '2h', '4h', '6h', '8h', '12h']: binance_period = '1h'
                elif p_lower in ['1d', '2d', '3d', '1w', '1m']: binance_period = '1d'
                
                max_pages = min((limit_to_fetch + 499) // 500, 2)
                end_ts = None
                records = []
                for page in range(max_pages):
                    params = {'symbol': binance_symbol, 'period': binance_period, 'limit': min(limit_to_fetch, 500)}
                    if end_ts: params['endTime'] = int(end_ts)
                    try:
                        res = self.binance.fapidataGetToplongshortaccountratio(params)
                        if not isinstance(res, list) or not res: break
                        for item in res:
                            records.append({
                                'timestamp': self._ms_to_dt(int(item['timestamp'])),
                                'exchange': 'binance',
                                'symbol': db_symbol,
                                'timeframe': period,
                                'long_short_ratio': float(item['longShortRatio'])
                            })
                        earliest_ts = min(int(item['timestamp']) for item in res)
                        if end_ts and earliest_ts >= end_ts: break
                        end_ts = earliest_ts - 1
                        if len(res) < 500: break
                    except Exception as e: print(f"Error fetching data: {e}"); break
                
                if records:
                    with SessionLocal() as session:
                        crud.upsert_market_data(session, records)

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                executor.submit(fetch_okx)
                executor.submit(fetch_binance)

            okx_data = crud.get_market_data(db, symbol=db_symbol, timeframe=period, exchange="okx", limit=limit)
            bin_data = crud.get_market_data(db, symbol=db_symbol, timeframe=period, exchange="binance", limit=limit)

            df_okx = pd.DataFrame([{ "time": int(x.timestamp.timestamp()), "value": x.long_short_ratio or 0 } for x in okx_data if x.long_short_ratio is not None])
            df_bin = pd.DataFrame([{ "time": int(x.timestamp.timestamp()), "value": x.long_short_ratio or 0 } for x in bin_data if x.long_short_ratio is not None])
            
            merged = pd.concat([df_okx, df_bin])
            if merged.empty: return []

            period_seconds = 300
            if 'm' in period.lower(): period_seconds = int(period.lower().replace('m', '')) * 60
            elif 'h' in period.lower(): period_seconds = int(period.lower().replace('h', '')) * 3600
            elif 'd' in period.lower(): period_seconds = 86400
            
            merged['rounded_time'] = (merged['time'] // period_seconds) * period_seconds
            agg_df = merged.groupby('rounded_time')['value'].mean().reset_index()
            agg_df.rename(columns={'rounded_time': 'time'}, inplace=True)
            agg_df.sort_values('time', inplace=True)
            return agg_df.to_dict('records')[-limit:]

    def fetch_history(self, symbol: str, start_time: int, end_time: int, timeframe: str = '1h') -> List[Dict]:
        """ History Endpoint explicitly requested via Backend Backtest logic untouched. """
        all_ohlcv = []
        current_since = start_time
        
        # Make sure Backtester also uses Swap markets for continuity
        swap_symbol = f"{symbol.split('/')[0]}-USDT-SWAP" if '/' in symbol else f"{symbol.split('-')[0]}-USDT-SWAP"
        
        while current_since < end_time:
            try:
                batch = self.exchange.fetch_ohlcv(swap_symbol, timeframe, since=current_since, limit=100)
                if not batch: break
                all_ohlcv.extend(batch)
                last_ts = batch[-1][0]
                if last_ts >= end_time: break
                current_since = last_ts + 1
                time.sleep(self.exchange.rateLimit / 1000)
            except Exception as e: print(f"Error fetching data: {e}"); break
                
        return [
            {"time": int(x[0] / 1000), "open": x[1], "high": x[2], "low": x[3], "close": x[4], "volume": x[5]}
            for x in all_ohlcv if start_time <= x[0] <= end_time
        ]
