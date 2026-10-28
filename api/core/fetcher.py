import ccxt
import pandas as pd
import numpy as np
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
        self.okx = ccxt.okx({
            'options': {
                'defaultType': 'swap',
            }
        })
        self.binance = ccxt.binance({
            'options': {
                'defaultType': 'future',
            }
        })
        self.exchange = self.okx
        self.latest_oi_breakdown = {"binance": 0, "okx": 0, "total": 0}
        self._breakdown_cache: Dict[str, Dict[str, Any]] = {}
        self._latest_valid_oi: Dict[str, Dict[str, float]] = {}

    def _ms_to_dt(self, ms: int) -> datetime:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)

    def fetch_market_data(self, symbol: str, timeframe: str = '1d', limit: int = 90) -> Dict:
        """
        Fetches OHLCV (Spot) and Funding Rate (Perp) History.
        """
        # Use swap symbol for DB storage
        db_symbol = symbol
        base_asset = symbol.split('/')[0] if '/' in symbol else symbol.split('-')[0]
        swap_symbol = f"{base_asset}-USDT-SWAP"
        
        # Use CCXT Unified Symbol for API fetching to avoid safeMarket ambiguity errors
        ccxt_symbol = f"{base_asset}/USDT:USDT"
        funding_symbol = swap_symbol
        
        if not self.exchange.markets:
            try:
                self.exchange.load_markets()
            except Exception:
                pass

        with SessionLocal() as db:
            db_ohlcv = crud.get_market_data(db, symbol=db_symbol, timeframe=timeframe, exchange="okx", limit=limit, require_ohlcv=True)
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
                        
                        # Fallback for OKX OHLCV when regular candles (1440 limit) run dry
                        if not batch and is_ohlcv and collected:
                            try:
                                okx_bar = timeframe.upper()
                                res_hist = self.exchange.publicGetMarketHistoryCandles({
                                    'instId': swap_symbol,
                                    'bar': okx_bar,
                                    'after': str(collected[0][0]),
                                    'limit': str(min(this_limit, 100))
                                })
                                raw_hist = res_hist.get('data', [])
                                if raw_hist:
                                    market = self.exchange.market(target_symbol) if target_symbol in self.exchange.markets else None
                                    batch = self.exchange.parse_ohlcvs(raw_hist, market, timeframe)
                            except Exception:
                                pass
                        
                        if not batch: break
                        collected = batch + collected
                        if len(batch) < 2 or len(collected) >= target_limit: break
                        time.sleep(0.05)
                    except Exception as e:
                        # Fallback attempt on error
                        if is_ohlcv and collected:
                            try:
                                okx_bar = timeframe.upper()
                                res_hist = self.exchange.publicGetMarketHistoryCandles({
                                    'instId': swap_symbol,
                                    'bar': okx_bar,
                                    'after': str(collected[0][0]),
                                    'limit': str(min(this_limit, 100))
                                })
                                raw_hist = res_hist.get('data', [])
                                if raw_hist:
                                    market = self.exchange.market(target_symbol) if target_symbol in self.exchange.markets else None
                                    batch = self.exchange.parse_ohlcvs(raw_hist, market, timeframe)
                                    if batch:
                                        collected = batch + collected
                                        if len(collected) >= target_limit: break
                                        continue
                            except Exception:
                                pass
                        print(f"Pagination error for {target_symbol}: {e}")
                        break
                return collected[-target_limit:]

            try:
                ohlcv_batch = fetch_paginated(self.exchange.fetch_ohlcv, ccxt_symbol, target_limit_ohlcv, is_ohlcv=True)
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
                print(f"Error fetching OHLCV for {ccxt_symbol}: {e}")

            try:
                funding_batch = fetch_paginated(self.exchange.fetch_funding_rate_history, ccxt_symbol, target_limit_funding, is_ohlcv=False)
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

            final_ohlcv = crud.get_market_data(db, symbol=db_symbol, timeframe=timeframe, exchange="okx", limit=limit, require_ohlcv=True)
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
                    import numpy as np
                    merged['fundingRate'] = merged['fundingRate'].replace(np.nan, None)
                    funding_data = [{"time": int(row['timestamp'] / 1000), "value": row['fundingRate'] * 100 if row['fundingRate'] is not None else None} for _, row in merged.iterrows()]

            return {"price": price_data, "funding": funding_data}

    def fetch_taker_volume(self, symbol: str, period: str = '5m', limit: int = 100) -> list:
        ccy = symbol.split('/')[0] if '/' in symbol else symbol.split('-')[0]
        binance_symbol = f"{ccy}USDT"
        db_symbol = symbol 
        
        p_lower = period.lower()
        period_seconds = 300
        if 'm' in p_lower: period_seconds = int(p_lower.replace('m', '')) * 60
        elif 'h' in p_lower: period_seconds = int(p_lower.replace('h', '')) * 3600
        elif 'd' in p_lower: period_seconds = 86400

        tf_ratio = max(1, period_seconds // 3600) if p_lower in ['2h', '4h', '6h', '8h', '12h'] else 1
        query_limit = limit * tf_ratio

        with SessionLocal() as db:
            if p_lower == '1d':
                db_bin_lower = crud.get_market_data(db, symbol=db_symbol, timeframe='1d', exchange="binance", limit=query_limit)
                db_bin_upper = crud.get_market_data(db, symbol=db_symbol, timeframe='1D', exchange="binance", limit=query_limit)
                seen_ts = set()
                db_bin = []
                for x in sorted(db_bin_lower + db_bin_upper, key=lambda item: item.timestamp):
                    if x.timestamp not in seen_ts and x.taker_buy_vol is not None:
                        seen_ts.add(x.timestamp)
                        db_bin.append(x)
                if len(db_bin) > query_limit:
                    db_bin = db_bin[-query_limit:]
            else:
                db_bin = crud.get_market_data(db, symbol=db_symbol, timeframe=period, exchange="binance", limit=query_limit)
                db_bin = [x for x in db_bin if x.taker_buy_vol is not None]
            
            missed_candles = 20 * tf_ratio
            if db_bin:
                latest_ts = db_bin[-1].timestamp.timestamp()
                first_ts = db_bin[0].timestamp.timestamp()
                now_ts = time.time()
                
                raw_step_sec = 3600 if p_lower in ['1h', '2h', '4h', '6h', '8h', '12h'] else period_seconds
                diff = now_ts - latest_ts
                span = latest_ts - first_ts
                expected_span = (len(db_bin) - 1) * raw_step_sec
                
                if span > expected_span + raw_step_sec:
                    missed_candles = max(query_limit, 100 * tf_ratio)
                elif diff > 0:
                    calc_missed = int((diff // raw_step_sec) + 2)
                    missed_candles = max(20 * tf_ratio, min(calc_missed, query_limit))
            
            limit_to_fetch = missed_candles if len(db_bin) >= query_limit else max(query_limit, 100 * tf_ratio)

            def fetch_binance():
                binance_period = '5m'
                if p_lower in ['1h', '2h', '4h', '6h', '8h', '12h']: binance_period = '1h'
                elif p_lower in ['1d', '2d', '3d', '1w', '1m']: binance_period = '1d'
                
                max_pages = min((limit_to_fetch + 499) // 500, 10)
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

            if p_lower == '1d':
                bin_data_lower = crud.get_market_data(db, symbol=db_symbol, timeframe='1d', exchange="binance", limit=query_limit)
                bin_data_upper = crud.get_market_data(db, symbol=db_symbol, timeframe='1D', exchange="binance", limit=query_limit)
                seen_ts = set()
                bin_data = []
                for x in sorted(bin_data_lower + bin_data_upper, key=lambda item: item.timestamp):
                    if x.timestamp not in seen_ts and x.taker_buy_vol is not None:
                        seen_ts.add(x.timestamp)
                        bin_data.append(x)
                if len(bin_data) > query_limit:
                    bin_data = bin_data[-query_limit:]
            else:
                bin_data = crud.get_market_data(db, symbol=db_symbol, timeframe=period, exchange="binance", limit=query_limit)
            df_bin = pd.DataFrame([{ "time": int(x.timestamp.timestamp()), "sell_vol": x.taker_sell_vol or 0, "buy_vol": x.taker_buy_vol or 0 } for x in bin_data])
            
            merged = df_bin
            if merged.empty: return []

            merged['rounded_time'] = (merged['time'] // period_seconds) * period_seconds
            agg_df = merged.groupby('rounded_time').agg({'sell_vol': 'sum', 'buy_vol': 'sum'}).reset_index()
            agg_df.rename(columns={'rounded_time': 'time'}, inplace=True)
            agg_df.sort_values('time', inplace=True)
            return agg_df.to_dict('records')[-limit:]

    def get_exchange_breakdown(self, symbol: str, current_price: Optional[float] = None) -> Dict[str, float]:
        """
        Lightweight live dual-exchange open interest breakdown (USD value).
        Cached in-memory for 60 seconds per symbol.
        """
        now = time.time()
        cached = self._breakdown_cache.get(symbol)
        if cached and (now - cached.get('ts', 0) < 60):
            return cached['data']

        ccy = symbol.split('/')[0] if '/' in symbol else symbol.split('-')[0]
        binance_symbol = f"{ccy}/USDT:USDT"
        okx_symbol = f"{ccy}-USDT-SWAP"

        # 1. Fetch Binance Live OI
        binance_usd = 0.0
        try:
            b_res = self.binance.fetch_open_interest(binance_symbol)
            if b_res.get('openInterestValue'):
                binance_usd = float(b_res['openInterestValue'])
            elif isinstance(b_res.get('info'), dict) and b_res['info'].get('sumOpenInterestValue'):
                binance_usd = float(b_res['info']['sumOpenInterestValue'])
            else:
                amount = float(b_res.get('openInterestAmount') or (b_res.get('info') or {}).get('openInterest') or 0.0)
                if amount > 0:
                    if not current_price or current_price <= 0:
                        try:
                            ticker = self.binance.fetch_ticker(binance_symbol)
                            current_price = float((ticker or {}).get('last', 0))
                        except Exception:
                            pass
                    if current_price and current_price > 0:
                        binance_usd = amount * current_price
        except Exception:
            pass

        # 2. Fetch OKX Live OI
        okx_usd = 0.0
        try:
            o_res = self.okx.fetch_open_interest(okx_symbol)
            info = o_res.get('info', {}) if isinstance(o_res.get('info'), dict) else {}
            if info.get('oiUsd'):
                okx_usd = float(info['oiUsd'])
            elif o_res.get('openInterestValue'):
                okx_usd = float(o_res['openInterestValue'])
            else:
                oi_ccy = float(info.get('oiCcy') or 0.0)
                if oi_ccy > 0:
                    if not current_price or current_price <= 0:
                        try:
                            ticker = self.okx.fetch_ticker(okx_symbol)
                            current_price = float((ticker or {}).get('last', 0))
                        except Exception:
                            pass
                    if current_price and current_price > 0:
                        okx_usd = oi_ccy * current_price
                else:
                    amount = float(o_res.get('openInterestAmount') or 0.0)
                    if amount > 0 and current_price and current_price > 0:
                        okx_usd = amount * current_price
        except Exception:
            okx_usd = 0.0

        # Fallback to latest valid values from historical series if live fetch returned 0
        if binance_usd == 0 and symbol in self._latest_valid_oi:
            binance_usd = self._latest_valid_oi[symbol].get('binance', 0.0)
        if okx_usd == 0 and symbol in self._latest_valid_oi:
            okx_usd = self._latest_valid_oi[symbol].get('okx', 0.0)

        total_usd = binance_usd + okx_usd
        breakdown = {
            "binance": binance_usd,
            "okx": okx_usd,
            "total": total_usd
        }

        if total_usd > 0:
            self._breakdown_cache[symbol] = {
                'ts': now,
                'data': breakdown
            }
            self._latest_valid_oi[symbol] = breakdown
            self.latest_oi_breakdown = breakdown

        return breakdown

    def fetch_open_interest(self, symbol: str, limit: int = 90, timeframe: str = '1h') -> list:
        ccy = symbol.split('/')[0] if '/' in symbol else symbol.split('-')[0]
        binance_symbol = f"{ccy}/USDT:USDT"
        okx_symbol = f"{symbol.split('/')[0]}-USDT-SWAP" if '/' in symbol else f"{symbol.split('-')[0]}-USDT-SWAP"
        db_symbol = symbol 
        
        p_lower = timeframe.lower()
        period_seconds = 3600
        if 'm' in p_lower: period_seconds = int(p_lower.replace('m', '')) * 60
        elif 'h' in p_lower: period_seconds = int(p_lower.replace('h', '')) * 3600
        elif 'd' in p_lower: period_seconds = 86400
        
        tf_ratio = max(1, period_seconds // 3600) if p_lower in ['2h', '4h', '6h', '8h', '12h'] else 1
        query_limit = limit * tf_ratio

        with SessionLocal() as db:
            if p_lower == '1d':
                db_okx_lower = crud.get_market_data(db, symbol=db_symbol, timeframe='1d', exchange="okx", limit=query_limit)
                db_okx_upper = crud.get_market_data(db, symbol=db_symbol, timeframe='1D', exchange="okx", limit=query_limit)
                seen_ts = set()
                db_okx = []
                for x in sorted(db_okx_lower + db_okx_upper, key=lambda item: item.timestamp):
                    if x.timestamp not in seen_ts and x.open_interest is not None:
                        seen_ts.add(x.timestamp)
                        db_okx.append(x)
                if len(db_okx) > query_limit:
                    db_okx = db_okx[-query_limit:]
            else:
                db_okx = crud.get_market_data(db, symbol=db_symbol, timeframe=p_lower, exchange="okx", limit=query_limit)
                db_okx = [x for x in db_okx if x.open_interest is not None]
            
            missed_candles = 20 * tf_ratio
            if db_okx:
                latest_ts = db_okx[-1].timestamp.timestamp()
                first_ts = db_okx[0].timestamp.timestamp()
                now_ts = time.time()
                
                tf_sec = period_seconds
                diff = now_ts - latest_ts
                span = latest_ts - first_ts
                expected_span = (len(db_okx) - 1) * tf_sec
                
                if span > expected_span + tf_sec:
                    missed_candles = max(query_limit, 100 * tf_ratio)
                elif diff > 0:
                    calc_missed = int((diff // tf_sec) + 2)
                    missed_candles = max(20 * tf_ratio, min(calc_missed, query_limit))
            
            limit_to_fetch = missed_candles if len(db_okx) >= query_limit else max(query_limit, 90 * tf_ratio)

            def fetch_okx():
                okx_tf = '5m'
                if p_lower in ['1h', '2h', '4h', '6h', '8h', '12h']: okx_tf = '1H'
                elif p_lower in ['1d', '2d', '3d', '1w', '1m']: okx_tf = '1D'
                
                adjusted_limit = limit_to_fetch * tf_ratio
                per_page = 100
                max_pages = min((adjusted_limit + per_page - 1) // per_page, 10)
                since = None
                records = []
                for page in range(max_pages):
                    params = {}
                    if since: params['until'] = since
                    try:
                        res = self.okx.fetch_open_interest_history(okx_symbol, okx_tf, limit=min(per_page, 100), params=params)
                        if not res: break
                        for item in res:
                            ts = int(item['timestamp'])
                            # Only filter intra-hour bounds for sub-daily timeframes; 1D from OKX is daily at 16:00 UTC
                            if p_lower not in ['1d', '2d', '3d', '1w', '1m'] and period_seconds < 86400:
                                if (ts // 1000) % period_seconds != 0:
                                    continue # ensure alignment with requested interval bounds
                            
                            val = 0.0
                            if item.get('openInterestValue'):
                                val = float(item['openInterestValue'])
                            elif isinstance(item.get('info'), dict) and item['info'].get('oiUsd'):
                                val = float(item['info']['oiUsd'])
                            elif isinstance(item.get('info'), list) and len(item['info']) >= 2:
                                val = float(item['info'][1])
                            elif item.get('openInterest'):
                                val = float(item['openInterest'])
                            
                            records.append({
                                'timestamp': self._ms_to_dt(ts),
                                'exchange': 'okx',
                                'symbol': db_symbol,
                                'timeframe': p_lower,
                                'open_interest': val
                            })
                        earliest_ts = min(item['timestamp'] for item in res)
                        if since and earliest_ts >= since: break
                        since = earliest_ts - 1
                        if len(res) < per_page: break
                        if page < max_pages - 1: time.sleep(0.2)
                    except Exception:
                        break
                if records:
                    with SessionLocal() as session:
                        crud.upsert_market_data(session, records)

            def fetch_binance():
                per_page = 500
                max_pages = min((limit_to_fetch + per_page - 1) // per_page, 10)
                since = None
                records = []
                binance_tf = p_lower if p_lower in ['5m', '15m', '30m', '1h', '2h', '4h', '6h', '12h', '1d'] else '1h'
                for page in range(max_pages):
                    params = {}
                    if since: params['endTime'] = since
                    try:
                        res = self.binance.fetch_open_interest_history(binance_symbol, binance_tf, limit=per_page, params=params)
                        if not res: break
                        for item in res:
                            val = float(item.get('openInterestValue') or (item.get('info') or {}).get('sumOpenInterestValue') or item.get('openInterest') or item.get('oi') or 0)
                            records.append({
                                'timestamp': self._ms_to_dt(item['timestamp']),
                                'exchange': 'binance',
                                'symbol': db_symbol,
                                'timeframe': p_lower,
                                'open_interest': val
                            })
                        earliest_ts = min(item['timestamp'] for item in res)
                        if since and earliest_ts >= since: break
                        since = earliest_ts - 1
                        if len(res) < per_page: break
                    except Exception:
                        break
                if records:
                    with SessionLocal() as session:
                        crud.upsert_market_data(session, records)

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                executor.submit(fetch_okx)
                executor.submit(fetch_binance)

            if p_lower == '1d':
                okx_data_lower = crud.get_market_data(db, symbol=db_symbol, timeframe='1d', exchange="okx", limit=query_limit)
                okx_data_upper = crud.get_market_data(db, symbol=db_symbol, timeframe='1D', exchange="okx", limit=query_limit)
                seen_ts = set()
                okx_data = []
                for x in sorted(db_okx_lower + db_okx_upper, key=lambda item: item.timestamp):
                    if x.timestamp not in seen_ts and x.open_interest is not None:
                        seen_ts.add(x.timestamp)
                        okx_data.append(x)
                if len(okx_data) > query_limit:
                    okx_data = okx_data[-query_limit:]

                bin_data_lower = crud.get_market_data(db, symbol=db_symbol, timeframe='1d', exchange="binance", limit=query_limit)
                bin_data_upper = crud.get_market_data(db, symbol=db_symbol, timeframe='1D', exchange="binance", limit=query_limit)
                seen_ts_b = set()
                bin_data = []
                for x in sorted(bin_data_lower + bin_data_upper, key=lambda item: item.timestamp):
                    if x.timestamp not in seen_ts_b and x.open_interest is not None:
                        seen_ts_b.add(x.timestamp)
                        bin_data.append(x)
                if len(bin_data) > query_limit:
                    bin_data = bin_data[-query_limit:]
            else:
                okx_data = crud.get_market_data(db, symbol=db_symbol, timeframe=p_lower, exchange="okx", limit=query_limit)
                bin_data = crud.get_market_data(db, symbol=db_symbol, timeframe=p_lower, exchange="binance", limit=query_limit)

            df_okx = pd.DataFrame([{ "time": int(x.timestamp.timestamp()), "value": x.open_interest or 0 } for x in okx_data if x.open_interest is not None])
            df_bin = pd.DataFrame([{ "time": int(x.timestamp.timestamp()), "value": x.open_interest or 0 } for x in bin_data if x.open_interest is not None])
            
            if not df_bin.empty and not df_okx.empty:
                b_last = float(df_bin.iloc[-1]['value'])
                o_last = float(df_okx.iloc[-1]['value'])
                if b_last > 0 or o_last > 0:
                    self._latest_valid_oi[symbol] = {
                        'binance': b_last,
                        'okx': o_last,
                        'total': b_last + o_last
                    }
                    self.latest_oi_breakdown = self._latest_valid_oi[symbol]

            if df_okx.empty and df_bin.empty:
                return []

            if not df_okx.empty:
                df_okx['rounded_time'] = (df_okx['time'] // period_seconds) * period_seconds
                df_okx = df_okx.groupby('rounded_time')['value'].mean().reset_index().rename(columns={'rounded_time': 'time'})
            if not df_bin.empty:
                df_bin['rounded_time'] = (df_bin['time'] // period_seconds) * period_seconds
                df_bin = df_bin.groupby('rounded_time')['value'].mean().reset_index().rename(columns={'rounded_time': 'time'})

            if df_okx.empty:
                merged = df_bin.rename(columns={'value': 'value_bin'})
                merged['value_okx'] = np.nan
            elif df_bin.empty:
                merged = df_okx.rename(columns={'value': 'value_okx'})
                merged['value_bin'] = np.nan
            else:
                merged = pd.merge(df_okx, df_bin, on='time', how='outer', suffixes=('_okx', '_bin')).sort_values('time')

            merged['value_okx'] = merged['value_okx'].ffill(limit=2)
            merged['value_bin'] = merged['value_bin'].ffill(limit=2)

            # Smooth scaling if one side is missing to prevent cliff jumps
            overlap = merged.dropna(subset=['value_okx', 'value_bin'])
            if not overlap.empty:
                # Past boundary scaling (oldest overlapping point)
                first_overlap = overlap.iloc[0]
                okx_val_0 = float(first_overlap['value_okx'])
                bin_val_0 = float(first_overlap['value_bin'])
                scale_to_bin_past = ((okx_val_0 + bin_val_0) / bin_val_0) if bin_val_0 > 0 else 1.0
                scale_to_okx_past = ((okx_val_0 + bin_val_0) / okx_val_0) if okx_val_0 > 0 else 1.0

                # Future boundary scaling (newest overlapping point)
                last_overlap = overlap.iloc[-1]
                okx_val_last = float(last_overlap['value_okx'])
                bin_val_last = float(last_overlap['value_bin'])
                scale_to_bin_future = ((okx_val_last + bin_val_last) / bin_val_last) if bin_val_last > 0 else 1.0
                scale_to_okx_future = ((okx_val_last + bin_val_last) / okx_val_last) if okx_val_last > 0 else 1.0

                first_overlap_time = first_overlap['time']
                last_overlap_time = last_overlap['time']

                values = []
                for _, row in merged.iterrows():
                    v_okx = row['value_okx']
                    v_bin = row['value_bin']
                    t = row['time']
                    if pd.notna(v_okx) and pd.notna(v_bin):
                        values.append(v_okx + v_bin)
                    elif pd.notna(v_bin):
                        scale = scale_to_bin_past if t < first_overlap_time else scale_to_bin_future
                        values.append(v_bin * scale)
                    elif pd.notna(v_okx):
                        scale = scale_to_okx_past if t < first_overlap_time else scale_to_okx_future
                        values.append(v_okx * scale)
                    else:
                        values.append(0.0)
                merged['value'] = values
            else:
                merged['value'] = merged['value_okx'].fillna(0) + merged['value_bin'].fillna(0)

            merged.sort_values('time', inplace=True)
            return merged[['time', 'value']].to_dict('records')[-limit:]

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
                        if hasattr(self.binance, 'fapidataGetGloballongshortaccountratio'):
                            res = self.binance.fapidataGetGloballongshortaccountratio(params)
                        else:
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
