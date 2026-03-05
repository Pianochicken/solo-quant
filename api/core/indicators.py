import pandas as pd
import numpy as np
from typing import List, Dict

class IndicatorEngine:
    """
    Processes raw market data into 'CoinKarma' style indicators.
    """
    
    @staticmethod
    def calculate_lsur_z_score(lsur_history: List[Dict], window: int = 90) -> float:
        """
        Calculates the Z-Score of the latest Long/Short Ratio.
        Z = (Current - Mean) / StdDev
        window: data points to consider for mean/std (default 90 periods).
        """
        if not lsur_history or len(lsur_history) < window:
            return 0.0
            
        # Convert to Series
        values = [item['value'] for item in lsur_history]
        series = pd.Series(values)
        
        # Calculate Rolling Stats
        rolling_mean = series.rolling(window=window).mean()
        rolling_std = series.rolling(window=window).std()
        
        current_val = values[-1]
        mean_val = rolling_mean.iloc[-1]
        std_val = rolling_std.iloc[-1]
        
        if std_val == 0:
            return 0.0
            
        z_score = (current_val - mean_val) / std_val
        return float(z_score)

    @staticmethod
    def calculate_lsur_z_score_history(lsur_history: List[Dict], window: int = 90) -> List[Dict]:
        """
        Computes the FULL rolling Z-Score history for Long/Short Ratio.
        Returns: [{ time, value (z-score), signal ('bullish'|'bearish'|null) }]
        
        Signals:
          - Z > 2.0  → 'bearish' (Overcrowded Longs → likely squeeze down)
          - Z < -2.0 → 'bullish' (Overcrowded Shorts → likely squeeze up)
        """
        if not lsur_history or len(lsur_history) < window:
            return []
        
        times = [item['time'] for item in lsur_history]
        values = [item['value'] for item in lsur_history]
        series = pd.Series(values)
        
        rolling_mean = series.rolling(window=window).mean()
        rolling_std = series.rolling(window=window).std()
        
        results = []
        for i in range(len(values)):
            mean_val = rolling_mean.iloc[i]
            std_val = rolling_std.iloc[i]
            
            if pd.isna(mean_val) or pd.isna(std_val) or std_val == 0:
                continue
            
            z = (values[i] - mean_val) / std_val
            
            signal = None
            if z >= 2.0:
                signal = 'bearish'   # Too many longs → potential drop
            elif z <= -2.0:
                signal = 'bullish'   # Too many shorts → potential squeeze up
            
            results.append({
                "time": times[i],
                "value": round(float(z), 2),
                "signal": signal
            })
        
        return results

    @staticmethod
    def calculate_liquidity_density(orderbook: Dict, current_price: float, range_percent: float = 0.05) -> Dict:
        """
        Aggregates Order Book depth to find 'Liquidity Walls'.
        Returns specific price levels with high volume density within +/- range_percent.
        """
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])
        
        # Filter within range
        lower_bound = current_price * (1 - range_percent)
        upper_bound = current_price * (1 + range_percent)
        
        relevant_bids = [b for b in bids if b[0] >= lower_bound]
        relevant_asks = [a for a in asks if a[0] <= upper_bound]
        
        # Find major walls (Simple logic: Top 5 by volume)
        # Bids: [Price, Amount]
        sorted_bids = sorted(relevant_bids, key=lambda x: x[1], reverse=True)[:5]
        sorted_asks = sorted(relevant_asks, key=lambda x: x[1], reverse=True)[:5]
        
        return {
            "bid_walls": [{"price": b[0], "volume": b[1]} for b in sorted_bids],
            "ask_walls": [{"price": a[0], "volume": a[1]} for a in sorted_asks]
        }
        
    @staticmethod
    def calculate_cvd_history(taker_volume: List[Dict]) -> List[Dict]:
        """
        Calculates Cumulative Volume Delta (CVD) history.
        Delta = Buy Vol - Sell Vol.
        CVD = Cumulative Sum of Delta.
        """
        if not taker_volume:
            return []
            
        # Ensure sorting by time
        sorted_vol = sorted(taker_volume, key=lambda x: x['time'])
        
        cvd_history = []
        cumulative_delta = 0.0
        
        for item in sorted_vol:
            delta = item['buy_vol'] - item['sell_vol']
            cumulative_delta += delta
            
            cvd_history.append({
                "time": item['time'],
                "value": cumulative_delta
            })
            
        return cvd_history

    @staticmethod
    def calculate_oi_percentile(daily_oi: List[Dict]) -> float:
        """
        Calculate where the current OI sits relative to its historical range.
        Uses daily OI data (which has months of history) for robust percentile.
        
        Returns: percentile 0-100 (e.g., 85.0 means current OI is higher than 85% of history)
        """
        if not daily_oi or len(daily_oi) < 10:
            return 50.0  # Default to neutral if not enough data
        
        values = [item['value'] for item in daily_oi if item.get('value', 0) > 0]
        if not values:
            return 50.0
        
        current = values[-1]
        # Calculate percentile: what % of historical values are below current
        below_count = sum(1 for v in values if v <= current)
        percentile = (below_count / len(values)) * 100
        return round(percentile, 1)

    @staticmethod
    def calculate_ema_trend(price_data: List[Dict], fast_period: int = 50, slow_period: int = 200) -> Dict:
        """
        Calculate dual EMA trend filter from price close data.
        
        Returns:
            {
                'trend_state': 'uptrend' | 'downtrend' | 'neutral',
                'ema_fast': [{'time': ..., 'value': ...}, ...],  # EMA50
                'ema_slow': [{'time': ..., 'value': ...}, ...],  # EMA200
            }
        
        Trend logic:
            price > EMA_fast > EMA_slow → uptrend (block bearish signals)
            price < EMA_fast < EMA_slow → downtrend (block bullish signals)  
            otherwise → neutral (allow all signals)
        """
        if not price_data or len(price_data) < slow_period:
            return {'trend_state': 'neutral', 'ema_fast': [], 'ema_slow': []}
        
        df = pd.DataFrame(price_data)
        df['time'] = df['time'].astype(int)
        df.sort_values('time', inplace=True)
        
        # Calculate EMAs using pandas ewm
        df['ema_fast'] = df['close'].ewm(span=fast_period, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=slow_period, adjust=False).mean()
        
        # Determine current trend state from latest values
        latest = df.iloc[-1]
        price_now = latest['close']
        ema_fast_now = latest['ema_fast']
        ema_slow_now = latest['ema_slow']
        
        if price_now > ema_fast_now > ema_slow_now:
            trend_state = 'uptrend'
        elif price_now < ema_fast_now < ema_slow_now:
            trend_state = 'downtrend'
        else:
            trend_state = 'neutral'
        
        # Build output series (only where slow EMA is valid — after slow_period bars)
        valid_df = df.iloc[slow_period - 1:]
        ema_fast_series = [{'time': int(r['time']), 'value': round(r['ema_fast'], 2)} for _, r in valid_df.iterrows()]
        ema_slow_series = [{'time': int(r['time']), 'value': round(r['ema_slow'], 2)} for _, r in valid_df.iterrows()]
        
        return {
            'trend_state': trend_state,
            'ema_fast': ema_fast_series,
            'ema_slow': ema_slow_series,
        }

    @staticmethod
    def calculate_rsi(price_data: List[Dict], period: int = 14) -> List[Dict]:
        """
        Calculate RSI (Relative Strength Index) using Wilder's smoothing.
        
        RSI < 30 = oversold (potential buy)
        RSI > 70 = overbought (potential sell)
        
        Returns: [{'time': ..., 'value': ...}, ...]
        """
        if not price_data or len(price_data) < period + 1:
            return []
        
        df = pd.DataFrame(price_data)
        df['time'] = df['time'].astype(int)
        df.sort_values('time', inplace=True)
        
        # Calculate price changes
        delta = df['close'].diff()
        
        # Separate gains and losses
        gains = delta.where(delta > 0, 0.0)
        losses = (-delta).where(delta < 0, 0.0)
        
        # Wilder's smoothing (EMA with alpha=1/period)
        avg_gain = gains.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        avg_loss = losses.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        
        # Calculate RS and RSI
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        rsi = rsi.fillna(50)  # Default to neutral if undefined
        
        df['rsi'] = rsi
        
        # Return only valid RSI values (after period warmup)
        valid = df.iloc[period:]
        return [{'time': int(r['time']), 'value': round(r['rsi'], 1)} for _, r in valid.iterrows()]

    @staticmethod
    def calculate_bollinger_bands(price_data: List[Dict], period: int = 20, std_multiplier: float = 2.0) -> Dict:
        """
        Calculate Bollinger Bands.
        Returns %B (where price sits relative to bands):
          %B > 1.0 = above upper band (overbought)
          %B < 0.0 = below lower band (oversold)
          %B = 0.5 = at middle band
        """
        if not price_data or len(price_data) < period:
            return {'bb_pctb': []}
        
        df = pd.DataFrame(price_data)
        df['time'] = df['time'].astype(int)
        df.sort_values('time', inplace=True)
        
        df['sma'] = df['close'].rolling(window=period).mean()
        df['std'] = df['close'].rolling(window=period).std()
        df['upper'] = df['sma'] + std_multiplier * df['std']
        df['lower'] = df['sma'] - std_multiplier * df['std']
        
        # %B = (price - lower) / (upper - lower)
        band_width = df['upper'] - df['lower']
        df['pctb'] = (df['close'] - df['lower']) / band_width.replace(0, np.nan)
        df['pctb'] = df['pctb'].fillna(0.5)
        
        valid = df.iloc[period - 1:]
        return {
            'bb_pctb': [{'time': int(r['time']), 'value': round(r['pctb'], 3)} for _, r in valid.iterrows()]
        }

    @staticmethod
    def calculate_oi_percentile_series(oi_aligned: List[Dict], window: int = 90) -> List[Dict]:
        """
        Calculate rolling OI percentile for each bar.
        Returns: [{'time': ..., 'value': percentile}, ...]
        """
        if not oi_aligned or len(oi_aligned) < 10:
            return []
        
        df = pd.DataFrame(oi_aligned)
        df['time'] = df['time'].astype(int)
        df.sort_values('time', inplace=True)
        
        # Rolling percentile: for each bar, what % of the last `window` bars have OI <= current
        results = []
        values = df['value'].values
        times = df['time'].values
        
        for i in range(len(values)):
            start = max(0, i - window + 1)
            window_vals = values[start:i+1]
            if len(window_vals) < 10:
                results.append({'time': int(times[i]), 'value': 50.0})
                continue
            current = values[i]
            below = np.sum(window_vals <= current)
            pct = (below / len(window_vals)) * 100
            results.append({'time': int(times[i]), 'value': round(float(pct), 1)})
        
        return results

    @staticmethod
    def calculate_confluence_signals(
        price_data: List[Dict],
        lsur_z_aligned: List[Dict],
        cvd_aligned: List[Dict],
        oi_percentile: float,
        funding_aligned: List[Dict],
        trend_state: str = 'neutral',
        rsi_aligned: List[Dict] = None,
        ema_fast_aligned: List[Dict] = None,
        bb_pctb_aligned: List[Dict] = None,
        lookback: int = 3,
        timeframe: str = '1h',
        oi_aligned: List[Dict] = None,
    ) -> List[Dict]:
        """
        Multi-Indicator Confluence Signal System v4: Timeframe-Adaptive.
        
        7 indicators with timeframe-specific thresholds.
        EMA Trend Filter adjusts bull/bear thresholds dynamically.
        Per-bar rolling OI percentile replaces global OI check.
        
        INDICATORS (each = 1 point):
          1. LSUR Z-Score — crowded positioning
          2. CVD Momentum — buying/selling pressure direction
          3. OI Percentile — leverage fuel (rolling per-bar)
          4. Funding Rate — sentiment extreme
          5. RSI — overbought/oversold
          6. EMA Zone — price stretched from EMA50
          7. Bollinger %B — volatility-based extreme
        """
        if not price_data or len(price_data) < lookback + 1:
            return []
        
        # === Timeframe-Adaptive Parameter Profiles ===
        PROFILES = {
            '15m': {
                'rsi_bull': 25, 'rsi_bear': 75,
                'ema_pct': 0.5,
                'fr_bull': -0.005, 'fr_bear': 0.01,
                'bb_bull': 0.10, 'bb_bear': 0.90,
                'z_bull': -1.5, 'z_bear': 1.5,
                'cooldown': 8,
                'oi_lookback': 4,    # 4 bars = 1 hour
                'price_thresh': 0.3, # % price change threshold
            },
            '1h': {
                'rsi_bull': 30, 'rsi_bear': 70,
                'ema_pct': 1.0,
                'fr_bull': -0.003, 'fr_bear': 0.008,
                'bb_bull': 0.08, 'bb_bear': 0.92,
                'z_bull': -1.2, 'z_bear': 1.2,
                'cooldown': 5,
                'oi_lookback': 3,    # 3 bars = 3 hours
                'price_thresh': 0.5,
            },
            '4h': {
                'rsi_bull': 35, 'rsi_bear': 65,
                'ema_pct': 2.0,
                'fr_bull': -0.002, 'fr_bear': 0.006,
                'bb_bull': 0.05, 'bb_bear': 0.95,
                'z_bull': -1.0, 'z_bear': 1.0,
                'cooldown': 3,
                'oi_lookback': 3,    # 3 bars = 12 hours
                'price_thresh': 1.0,
            },
            '1d': {
                'rsi_bull': 40, 'rsi_bear': 60,
                'ema_pct': 3.0,
                'fr_bull': -0.001, 'fr_bear': 0.005,
                'bb_bull': 0.05, 'bb_bear': 0.95,
                'z_bull': -0.8, 'z_bear': 0.8,
                'cooldown': 2,
                'oi_lookback': 3,    # 3 bars = 3 days
                'price_thresh': 1.5,
            },
        }
        P = PROFILES.get(timeframe, PROFILES['1h'])
        COOLDOWN = P['cooldown']
        
        # === Signal Threshold ===
        # Fixed at 3/7 regardless of trend state.
        # Trend state is still displayed as context but does NOT alter thresholds.
        bull_threshold = 3
        bear_threshold = 3
        
        # Build lookup dicts by time for O(1) access
        z_by_time = {item['time']: item['value'] for item in lsur_z_aligned}
        cvd_by_time = {item['time']: item['value'] for item in cvd_aligned}
        funding_by_time = {item['time']: item['value'] for item in funding_aligned}
        rsi_by_time = {item['time']: item['value'] for item in (rsi_aligned or [])}
        ema_fast_by_time = {item['time']: item['value'] for item in (ema_fast_aligned or [])}
        bb_by_time = {item['time']: item['value'] for item in (bb_pctb_aligned or [])}
        
        # OI lookup by time (for OI change rate calculation)
        oi_by_time = {item['time']: item['value'] for item in (oi_aligned or [])}
        
        # Price lookup
        price_by_time = {p['time']: p for p in price_data}
        times = [p['time'] for p in price_data]
        
        markers = []
        last_bull_idx = -100
        last_bear_idx = -100
        
        for i in range(lookback, len(times)):
            t = times[i]
            
            z_val = z_by_time.get(t)
            cvd_now = cvd_by_time.get(t)
            funding_now = funding_by_time.get(t)
            rsi_now = rsi_by_time.get(t)
            ema_fast_now = ema_fast_by_time.get(t)
            bb_now = bb_by_time.get(t)
            price_bar = price_by_time.get(t)
            
            cvd_prev = cvd_by_time.get(times[i - lookback])
            
            # OI × Price divergence (method 2: N-bar change rate)
            oi_lookback = P['oi_lookback']
            price_thresh = P['price_thresh']
            oi_now = oi_by_time.get(t)
            oi_prev_t = times[i - oi_lookback] if i >= oi_lookback else times[0]
            oi_prev = oi_by_time.get(oi_prev_t)
            price_prev_bar = price_by_time.get(oi_prev_t)
            
            # Calculate changes
            price_chg_pct = None
            oi_chg_pct = None
            if price_bar and price_prev_bar and price_prev_bar['close'] > 0:
                price_chg_pct = (price_bar['close'] - price_prev_bar['close']) / price_prev_bar['close'] * 100
            if oi_now and oi_prev and oi_prev > 0:
                oi_chg_pct = (oi_now - oi_prev) / oi_prev * 100
            
            if z_val is None:
                continue
            
            price_close = price_bar['close'] if price_bar else None
            
            # ===== BULLISH confluence =====
            bull_score = 0
            bull_reasons = []
            
            if z_val <= P['z_bull']:
                bull_score += 1
                bull_reasons.append('Z')
            
            if cvd_now is not None and cvd_prev is not None and (cvd_now - cvd_prev) > 0:
                bull_score += 1
                bull_reasons.append('CVD↑')
            
            # OI × Price: bullish when price↑+OI↑ (new longs) or price↓+OI急降 (deleverage bottom)
            if price_chg_pct is not None and oi_chg_pct is not None:
                if price_chg_pct > price_thresh and oi_chg_pct > 0:
                    bull_score += 1
                    bull_reasons.append('OI↑P↑')
                elif price_chg_pct < -price_thresh and oi_chg_pct < -5.0:
                    bull_score += 1
                    bull_reasons.append('OI去槓')
            
            if funding_now is not None and funding_now < P['fr_bull']:
                bull_score += 1
                bull_reasons.append('FR-')
            
            if rsi_now is not None and rsi_now < P['rsi_bull']:
                bull_score += 1
                bull_reasons.append(f'RSI{int(rsi_now)}')
            
            if ema_fast_now is not None and price_close is not None:
                ema_dist = (price_close - ema_fast_now) / ema_fast_now * 100
                if ema_dist < -P['ema_pct']:
                    bull_score += 1
                    bull_reasons.append('EMA↑')
            
            if bb_now is not None and bb_now < P['bb_bull']:
                bull_score += 1
                bull_reasons.append('BB↑')
            
            # ===== BEARISH confluence =====
            bear_score = 0
            bear_reasons = []
            
            if z_val >= P['z_bear']:
                bear_score += 1
                bear_reasons.append('Z')
            
            if cvd_now is not None and cvd_prev is not None and (cvd_now - cvd_prev) < 0:
                bear_score += 1
                bear_reasons.append('CVD↓')
            
            # OI × Price: bearish when price↓+OI↑ (new shorts) or price↑+OI急降 (just short squeeze)
            if price_chg_pct is not None and oi_chg_pct is not None:
                if price_chg_pct < -price_thresh and oi_chg_pct > 0:
                    bear_score += 1
                    bear_reasons.append('OI↑P↓')
                elif price_chg_pct > price_thresh and oi_chg_pct < -5.0:
                    bear_score += 1
                    bear_reasons.append('OI去槓')
            
            if funding_now is not None and funding_now > P['fr_bear']:
                bear_score += 1
                bear_reasons.append('FR+')
            
            if rsi_now is not None and rsi_now > P['rsi_bear']:
                bear_score += 1
                bear_reasons.append(f'RSI{int(rsi_now)}')
            
            if ema_fast_now is not None and price_close is not None:
                ema_dist = (price_close - ema_fast_now) / ema_fast_now * 100
                if ema_dist > P['ema_pct']:
                    bear_score += 1
                    bear_reasons.append('EMA↓')
            
            if bb_now is not None and bb_now > P['bb_bear']:
                bear_score += 1
                bear_reasons.append('BB↓')
            
            # --- Emit signal if score >= threshold, respecting cooldown ---
            if bull_score >= bull_threshold and (i - last_bull_idx) >= COOLDOWN:
                markers.append({
                    "time": t,
                    "position": "belowBar",
                    "color": "#22c55e",
                    "shape": "arrowUp",
                    "text": f"⚡{bull_score}/7 {'+'.join(bull_reasons)}",
                    "score": bull_score,
                    "direction": "bullish"
                })
                last_bull_idx = i
            elif bear_score >= bear_threshold and (i - last_bear_idx) >= COOLDOWN:
                markers.append({
                    "time": t,
                    "position": "aboveBar",
                    "color": "#ef4444",
                    "shape": "arrowDown",
                    "text": f"⚡{bear_score}/7 {'+'.join(bear_reasons)}",
                    "score": bear_score,
                    "direction": "bearish"
                })
                last_bear_idx = i
        
        return markers

