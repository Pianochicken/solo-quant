import pandas as pd
import numpy as np
from typing import List, Dict

class IndicatorEngine:
    """
    Processes raw market data into quantitative trading indicators.
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
        
        # Return RSI for ALL timestamps (fillna(50) handles warmup period).
        # This keeps the array length matching price data for chart alignment.
        return [{'time': int(r['time']), 'value': round(r['rsi'], 1)} for _, r in df.iterrows()]

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
    def calculate_market_regime(
        price_data: List[Dict],
        cvd_aligned: List[Dict] = None,
        adx_period: int = 14,
        bb_period: int = 20,
        cvd_lookback: int = 10,
    ) -> Dict:
        """
        Market Regime Detection — determines if market is trending or ranging.
        
        Uses 3 factors (majority vote):
          1. ADX (Average Directional Index): ADX > 25 = trending
          2. BB Width Expansion: current width > 1.5x average width = trending
          3. CVD Slope: sustained directional pressure = trending
        
        Returns:
            {
                'regime': 'trending' | 'ranging',
                'direction': 'up' | 'down' | 'neutral',
                'adx': float,
                'no_short': bool,    # True = block bearish signals
                'no_long': bool,     # True = block bullish signals
            }
        """
        result = {
            'regime': 'ranging',
            'direction': 'neutral',
            'adx': 0.0,
            'no_short': False,
            'no_long': False,
        }
        
        if not price_data or len(price_data) < adx_period * 2 + 10:
            return result
        
        df = pd.DataFrame(price_data)
        df['time'] = df['time'].astype(int)
        df.sort_values('time', inplace=True)
        df.reset_index(drop=True, inplace=True)
        
        # === Factor 1: ADX ===
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        
        # True Range
        tr = np.zeros(len(close))
        tr[0] = high[0] - low[0]
        for j in range(1, len(close)):
            tr[j] = max(high[j] - low[j], abs(high[j] - close[j-1]), abs(low[j] - close[j-1]))
        
        # +DM / -DM
        plus_dm = np.zeros(len(close))
        minus_dm = np.zeros(len(close))
        for j in range(1, len(close)):
            up_move = high[j] - high[j-1]
            down_move = low[j-1] - low[j]
            plus_dm[j] = up_move if (up_move > down_move and up_move > 0) else 0
            minus_dm[j] = down_move if (down_move > up_move and down_move > 0) else 0
        
        # Wilder's smoothing (Running Sum)
        def wilder_sum(data, period):
            out = np.zeros(len(data))
            if len(data) < period + 1: return out
            out[period] = np.sum(data[1:period+1])
            for j in range(period + 1, len(data)):
                out[j] = out[j-1] - (out[j-1] / period) + data[j]
            return out
        
        atr = wilder_sum(tr, adx_period)
        plus_di_raw = wilder_sum(plus_dm, adx_period)
        minus_di_raw = wilder_sum(minus_dm, adx_period)
        
        # +DI / -DI
        with np.errstate(divide='ignore', invalid='ignore'):
            plus_di = np.where(atr > 0, 100 * plus_di_raw / atr, 0)
            minus_di = np.where(atr > 0, 100 * minus_di_raw / atr, 0)
        
        # DX
        di_sum = plus_di + minus_di
        with np.errstate(divide='ignore', invalid='ignore'):
            dx = np.where(di_sum > 0, 100 * np.abs(plus_di - minus_di) / di_sum, 0)
        
        # ADX = smoothed DX (Running Average, alpha = 1 / period)
        adx = np.zeros(len(dx))
        if len(dx) >= adx_period * 2:
            start_idx = adx_period * 2 - 1
            adx[start_idx] = np.mean(dx[adx_period:start_idx+1])
            for j in range(start_idx + 1, len(dx)):
                adx[j] = (adx[j-1] * (adx_period - 1) + dx[j]) / adx_period
        
        current_adx = float(adx[-1]) if len(adx) > 0 else 0
        result['adx'] = round(current_adx, 1)
        
        adx_trending = current_adx > 25
        adx_direction = 'up' if plus_di[-1] > minus_di[-1] else 'down'
        
        # === Factor 2: BB Width Expansion ===
        bb_trending = False
        if len(close) >= bb_period + 20:
            sma = pd.Series(close).rolling(window=bb_period).mean()
            std = pd.Series(close).rolling(window=bb_period).std()
            bb_width = (2 * std / sma).fillna(0)
            
            # Current BB width vs average of last 20 periods
            current_width = float(bb_width.iloc[-1])
            avg_width = float(bb_width.iloc[-21:-1].mean()) if len(bb_width) > 21 else current_width
            
            bb_trending = current_width > avg_width * 1.5 if avg_width > 0 else False
        
        # === Factor 3: CVD Slope ===
        cvd_trending = False
        cvd_direction = 'neutral'
        if cvd_aligned and len(cvd_aligned) >= cvd_lookback + 1:
            cvd_vals = [item['value'] for item in cvd_aligned[-cvd_lookback-1:]]
            cvd_slope = cvd_vals[-1] - cvd_vals[0]
            
            # Check if CVD has been mostly one-directional
            positive_moves = sum(1 for k in range(1, len(cvd_vals)) if cvd_vals[k] > cvd_vals[k-1])
            negative_moves = len(cvd_vals) - 1 - positive_moves
            
            consistency = max(positive_moves, negative_moves) / (len(cvd_vals) - 1)
            
            if consistency >= 0.7:  # 70%+ of moves in same direction
                cvd_trending = True
                cvd_direction = 'up' if cvd_slope > 0 else 'down'
        
        # === Majority Vote ===
        trending_votes = sum([adx_trending, bb_trending, cvd_trending])
        
        if trending_votes >= 2:
            result['regime'] = 'trending'
            # Direction: ADX direction takes priority, CVD confirms
            if adx_direction == cvd_direction:
                result['direction'] = adx_direction
            else:
                result['direction'] = adx_direction  # ADX as tiebreaker
            
            # No-Short / No-Long filters
            if result['direction'] == 'up':
                result['no_short'] = True
            elif result['direction'] == 'down':
                result['no_long'] = True
        
        return result

    @staticmethod
    def calculate_market_regime_history(
        price_data: List[Dict],
        cvd_aligned: List[Dict] = None,
        adx_period: int = 14,
        bb_period: int = 20,
        cvd_lookback: int = 10,
    ) -> List[Dict]:
        """
        Calculates the historical rolling Market Regime for every timestamp.
        Used by the Backtester AI Mode.
        """
        if not price_data or len(price_data) < adx_period * 2 + 10:
            return []
            
        df = pd.DataFrame(price_data)
        df['time'] = df['time'].astype(int)
        df.sort_values('time', inplace=True)
        df.reset_index(drop=True, inplace=True)
        
        # === 1. ADX Calculation (Vectorized / Rolling) ===
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        
        tr = np.zeros(len(close))
        tr[0] = high[0] - low[0]
        for j in range(1, len(close)):
            tr[j] = max(high[j] - low[j], abs(high[j] - close[j-1]), abs(low[j] - close[j-1]))
            
        plus_dm = np.zeros(len(close))
        minus_dm = np.zeros(len(close))
        for j in range(1, len(close)):
            up_move = high[j] - high[j-1]
            down_move = low[j-1] - low[j]
            plus_dm[j] = up_move if (up_move > down_move and up_move > 0) else 0
            minus_dm[j] = down_move if (down_move > up_move and down_move > 0) else 0
            
        def wilder_sum(data, period):
            out = np.zeros(len(data))
            if len(data) < period + 1: return out
            out[period] = np.sum(data[1:period+1])
            for j in range(period + 1, len(data)):
                out[j] = out[j-1] - (out[j-1] / period) + data[j]
            return out
            
        atr = wilder_sum(tr, adx_period)
        plus_di_raw = wilder_sum(plus_dm, adx_period)
        minus_di_raw = wilder_sum(minus_dm, adx_period)
        
        with np.errstate(divide='ignore', invalid='ignore'):
            plus_di = np.where(atr > 0, 100 * plus_di_raw / atr, 0)
            minus_di = np.where(atr > 0, 100 * minus_di_raw / atr, 0)
            
        di_sum = plus_di + minus_di
        with np.errstate(divide='ignore', invalid='ignore'):
            dx = np.where(di_sum > 0, 100 * np.abs(plus_di - minus_di) / di_sum, 0)
            
        adx = np.zeros(len(dx))
        start_idx = adx_period * 2 - 1
        if len(dx) >= adx_period * 2:
            adx[start_idx] = np.mean(dx[adx_period:start_idx+1])
            for j in range(start_idx + 1, len(dx)):
                adx[j] = (adx[j-1] * (adx_period - 1) + dx[j]) / adx_period
                
        adx_trending = adx > 25
        adx_direction = np.where(plus_di > minus_di, 'up', 'down')
        
        # === 2. BB Width Expansion (Vectorized) ===
        sma = df['close'].rolling(window=bb_period).mean()
        std = df['close'].rolling(window=bb_period).std()
        bb_width = (2 * std / sma).fillna(0)
        
        # Rolling average of BB Width over the last 20 periods
        avg_width = bb_width.rolling(window=20, min_periods=1).mean()
        # Shift avg_width by 1 so we compare current against PREVIOUS 20 average
        avg_width_shifted = avg_width.shift(1).fillna(0)
        bb_trending = (bb_width > avg_width_shifted * 1.5).values
        
        # === 3. CVD Slope (Rolling) ===
        cvd_trending = np.zeros(len(close), dtype=bool)
        cvd_direction = np.full(len(close), 'neutral', dtype=object)
        
        if cvd_aligned and len(cvd_aligned) > 0:
            cvd_df = pd.DataFrame(cvd_aligned)
            if 'timestamp' not in cvd_df.columns and 'time' in cvd_df.columns:
                cvd_df['timestamp'] = cvd_df['time']
            merged_cvd = pd.merge_asof(
                df[['time']], 
                cvd_df[['timestamp', 'value']], 
                left_on='time', 
                right_on='timestamp', 
                direction='backward'
            )
            cvd_vals = merged_cvd['value'].fillna(0).values
            
            for i in range(cvd_lookback + 1, len(cvd_vals)):
                window_cvd = cvd_vals[i-cvd_lookback:i+1]
                slope = window_cvd[-1] - window_cvd[0]
                
                positive_moves = sum(1 for k in range(1, len(window_cvd)) if window_cvd[k] > window_cvd[k-1])
                negative_moves = len(window_cvd) - 1 - positive_moves
                consistency = max(positive_moves, negative_moves) / (len(window_cvd) - 1)
                
                if consistency >= 0.7:
                    cvd_trending[i] = True
                    cvd_direction[i] = 'up' if slope > 0 else 'down'
                    
        # === Aggregate History ===
        history = []
        for i in range(len(close)):
            votes = sum([adx_trending[i], bb_trending[i], cvd_trending[i]])
            
            regime = 'ranging'
            direction = 'neutral'
            no_short = False
            no_long = False
            
            if votes >= 2:
                regime = 'trending'
                # ADX direction takes priority
                direction = adx_direction[i]
                
                if direction == 'up':
                    no_short = True
                elif direction == 'down':
                    no_long = True
                    
            history.append({
                "time": int(df['time'].iloc[i]),
                "regime": regime,
                "direction": direction,
                "adx": round(float(adx[i]), 1),
                "no_short": no_short,
                "no_long": no_long
            })
            
        return history

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
        ranging_threshold: int = 3,
        trending_threshold: int = 3,
        enable_protection: bool = False,
    ) -> List[Dict]:
        """
        Multi-Indicator Confluence Signal System v5: Regime-Adaptive.
        
        Upgrades from v4:
          - Market Regime Detection (ADX + BB Width + CVD slope)
                    - Fixed threshold: 3/7 in both ranging and trending regimes
          - No-Short Filter: blocks bearish signals in uptrend regime
          - No-Long Filter: blocks bullish signals in downtrend regime
          - LSUR Dulling Detection: skips Z-score when price contradicts
          - CVD Slope Discount: halves reversal indicator scores in strong CVD trends
        
        INDICATORS (each = 1 point):
          1. LSUR Z-Score — crowded positioning (+ dulling detection)
          2. CVD Momentum — buying/selling pressure direction
          3. OI × Price — leverage fuel divergence
          4. Funding Rate — sentiment extreme (+ OI-Weighted logic)
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
        APPLY_DIRECTIONAL_PROTECTION = enable_protection
        
        # === Signal Threshold ===
        # Adjust threshold based on market regime and provided configs
        regime_history = IndicatorEngine.calculate_market_regime_history(
            price_data=price_data,
            cvd_aligned=cvd_aligned,
        )
        regime_by_time = {r['time']: r for r in regime_history}
        
        # We need the most recent one to return for the frontend Sentiment Panel
        latest_regime = regime_history[-1] if regime_history else IndicatorEngine.calculate_market_regime(
            price_data=price_data,
            cvd_aligned=cvd_aligned,
        )
        
        # CVD slope for reversal-indicator discount
        cvd_slope_extreme = False
        if cvd_aligned and len(cvd_aligned) >= lookback + 1:
            cvd_recent = [item['value'] for item in cvd_aligned[-lookback-1:]]
            cvd_slope_val = cvd_recent[-1] - cvd_recent[0]
            # Normalize: compare against typical CVD range
            cvd_range = max(abs(cvd_aligned[-1]['value'] - cvd_aligned[0]['value']), 1)
            cvd_slope_ratio = abs(cvd_slope_val) / cvd_range
            cvd_slope_extreme = cvd_slope_ratio > 0.3  # 30%+ of total range in lookback
        
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
        
        SETUP_WINDOW = 3
        bull_setup_timer = 0
        bull_setup_env_score = 0
        bull_setup_env_reasons = []
        bull_setup_env_groups = set()
        
        bear_setup_timer = 0
        bear_setup_env_score = 0
        bear_setup_env_reasons = []
        bear_setup_env_groups = set()
        
        for i in range(lookback, len(times)):
            t = times[i]
            
            # --- Dynamic Regime & Thresholds ---
            current_regime = regime_by_time.get(t, {
                'regime': 'ranging',
                'direction': 'neutral',
                'no_short': False,
                'no_long': False,
            })
            if current_regime.get('regime') == 'trending':
                bull_threshold = trending_threshold
                bear_threshold = trending_threshold
            else:
                bull_threshold = ranging_threshold
                bear_threshold = ranging_threshold
                
            z_val = z_by_time.get(t)
            cvd_now = cvd_by_time.get(t)
            funding_now = funding_by_time.get(t)
            rsi_now = rsi_by_time.get(t)
            ema_fast_now = ema_fast_by_time.get(t)
            bb_now = bb_by_time.get(t)
            price_bar = price_by_time.get(t)
            price_close = price_bar['close'] if price_bar else None
            
            # --- Price Action (Structural) Validation ---
            is_bull_pa = True
            is_bear_pa = True
            if price_bar and 'open' in price_bar and 'high' in price_bar and 'low' in price_bar:
                p_o, p_h, p_l, p_c = price_bar['open'], price_bar['high'], price_bar['low'], price_bar['close']
                total_range = p_h - p_l
                
                # Bullish PA: Need either a green body (Close >= Open) or a noticeable lower wick (>30% of range)
                body_up = p_c >= p_o
                lower_wick = min(p_o, p_c) - p_l
                has_lower_wick = (lower_wick / total_range > 0.3) if total_range > 0 else False
                is_bull_pa = body_up or has_lower_wick
                
                # Bearish PA: Need either a red body (Close <= Open) or a noticeable upper wick (>30% of range)
                body_down = p_c <= p_o
                upper_wick = p_h - max(p_o, p_c)
                has_upper_wick = (upper_wick / total_range > 0.3) if total_range > 0 else False
                is_bear_pa = body_down or has_upper_wick
            
            # CVD immediate momentum (1-bar change)
            cvd_prev = cvd_by_time.get(times[i - 1])
            
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
            
            # --- LSUR Dulling Detection ---
            # If LSUR Z says bearish (overcrowded longs) but price is RISING, skip Z
            # If LSUR Z says bullish (overcrowded shorts) but price is FALLING, skip Z
            lsur_dulled = False
            if z_val is not None and price_chg_pct is not None:
                if z_val >= P['z_bear'] and price_chg_pct > price_thresh:
                    lsur_dulled = True  # Z says sell but price going up
                elif z_val <= P['z_bull'] and price_chg_pct < -price_thresh:
                    lsur_dulled = True  # Z says buy but price going down
            
            # ===== BULLISH confluence =====
            t_bull_env_score = 0
            t_bull_env_reasons = []
            t_bull_env_groups = set()
            t_bull_price_score = 0
            t_bull_price_reasons = []
            t_bull_price_groups = set()
            
            if z_val <= P['z_bull'] and not lsur_dulled:
                t_bull_env_score += 1
                t_bull_env_reasons.append('Z')
                t_bull_env_groups.add('Sentiment')
            
            if cvd_now is not None and cvd_prev is not None and (cvd_now - cvd_prev) > 0:
                t_bull_env_score += 1
                t_bull_env_reasons.append('CVD↑')
                t_bull_env_groups.add('Momentum')
            
            if price_chg_pct is not None and oi_chg_pct is not None:
                if price_chg_pct > price_thresh and oi_chg_pct > 0:
                    t_bull_env_score += 1
                    t_bull_env_reasons.append('OI↑P↑')
                    t_bull_env_groups.add('Momentum')
                elif price_chg_pct < -price_thresh and oi_chg_pct < -5.0:
                    t_bull_env_score += 1
                    t_bull_env_reasons.append('OI去槓')
                    t_bull_env_groups.add('Momentum')
            
            if funding_now is not None and funding_now < P['fr_bull']:
                discount = cvd_slope_extreme
                if oi_chg_pct is not None:
                    if oi_chg_pct > 0:
                        t_bull_env_score += 1.0 if not discount else 0.5
                        t_bull_env_reasons.append('FR-(OI↑)')
                    else:
                        t_bull_env_score += 0.5 if not discount else 0.25
                        t_bull_env_reasons.append('FR-(OI↓)')
                else:
                    t_bull_env_score += 1.0 if not discount else 0.5
                    t_bull_env_reasons.append('FR-')
                t_bull_env_groups.add('Sentiment')
            
            if rsi_now is not None and rsi_now < P['rsi_bull'] and is_bull_pa:
                t_bull_price_score += 1
                t_bull_price_reasons.append(f'RSI{int(rsi_now)}')
                t_bull_price_groups.add('Price')
            
            if ema_fast_now is not None and price_close is not None and is_bull_pa:
                ema_dist = (price_close - ema_fast_now) / ema_fast_now * 100
                if ema_dist < -P['ema_pct']:
                    t_bull_price_score += 1
                    t_bull_price_reasons.append('EMA↑')
                    t_bull_price_groups.add('Price')
            
            if bb_now is not None and bb_now < P['bb_bull'] and is_bull_pa:
                t_bull_price_score += 1
                t_bull_price_reasons.append('BB↑')
                t_bull_price_groups.add('Price')
            
            # ===== BEARISH confluence =====
            t_bear_env_score = 0
            t_bear_env_reasons = []
            t_bear_env_groups = set()
            t_bear_price_score = 0
            t_bear_price_reasons = []
            t_bear_price_groups = set()
            
            if z_val >= P['z_bear'] and not lsur_dulled:
                t_bear_env_score += 1
                t_bear_env_reasons.append('Z')
                t_bear_env_groups.add('Sentiment')
            
            if cvd_now is not None and cvd_prev is not None and (cvd_now - cvd_prev) < 0:
                t_bear_env_score += 1
                t_bear_env_reasons.append('CVD↓')
                t_bear_env_groups.add('Momentum')
            
            if price_chg_pct is not None and oi_chg_pct is not None:
                if price_chg_pct < -price_thresh and oi_chg_pct > 0:
                    t_bear_env_score += 1
                    t_bear_env_reasons.append('OI↑P↓')
                    t_bear_env_groups.add('Momentum')
                elif price_chg_pct > price_thresh and oi_chg_pct < -5.0:
                    t_bear_env_score += 1
                    t_bear_env_reasons.append('OI去槓')
                    t_bear_env_groups.add('Momentum')
            
            if funding_now is not None and funding_now > P['fr_bear']:
                discount = cvd_slope_extreme
                if oi_chg_pct is not None:
                    if oi_chg_pct > 0:
                        t_bear_env_score += 1.0 if not discount else 0.5
                        t_bear_env_reasons.append('FR+(OI↑)')
                    else:
                        t_bear_env_score += 0.5 if not discount else 0.25
                        t_bear_env_reasons.append('FR+(OI↓)')
                else:
                    t_bear_env_score += 1.0 if not discount else 0.5
                    t_bear_env_reasons.append('FR+')
                t_bear_env_groups.add('Sentiment')
            
            if rsi_now is not None and rsi_now > P['rsi_bear'] and is_bear_pa:
                t_bear_price_score += 1
                t_bear_price_reasons.append(f'RSI{int(rsi_now)}')
                t_bear_price_groups.add('Price')
            
            if ema_fast_now is not None and price_close is not None and is_bear_pa:
                ema_dist = (price_close - ema_fast_now) / ema_fast_now * 100
                if ema_dist > P['ema_pct']:
                    t_bear_price_score += 1
                    t_bear_price_reasons.append('EMA↓')
                    t_bear_price_groups.add('Price')
            
            if bb_now is not None and bb_now > P['bb_bear'] and is_bear_pa:
                t_bear_price_score += 1
                t_bear_price_reasons.append('BB↓')
                t_bear_price_groups.add('Price')
            
            # --- State Machine Update (Setup window) ---
            if t_bull_env_score >= 1.0:
                bull_setup_timer = SETUP_WINDOW
                bull_setup_env_score = t_bull_env_score
                bull_setup_env_reasons = list(t_bull_env_reasons)
                bull_setup_env_groups = set(t_bull_env_groups)
                # Mutual cancellation: A strong bullish environment instantly cancels out any lingering bearish setup
                bear_setup_timer = 0
            elif bull_setup_timer > 0:
                bull_setup_timer -= 1

            if t_bear_env_score >= 1.0:
                bear_setup_timer = SETUP_WINDOW
                bear_setup_env_score = t_bear_env_score
                bear_setup_env_reasons = list(t_bear_env_reasons)
                bear_setup_env_groups = set(t_bear_env_groups)
                # Mutual cancellation: A strong bearish environment instantly cancels out any lingering bullish setup
                bull_setup_timer = 0
            elif bear_setup_timer > 0:
                bear_setup_timer -= 1
                
            # --- Confluence Unification ---
            bull_score = 0
            bull_reasons = []
            bull_groups = set()
            if bull_setup_timer > 0 and t_bull_price_score >= 1.0:
                bull_score = bull_setup_env_score + t_bull_price_score
                bull_groups = bull_setup_env_groups.union(t_bull_price_groups)
                bull_reasons = bull_setup_env_reasons + t_bull_price_reasons

            bear_score = 0
            bear_reasons = []
            bear_groups = set()
            if bear_setup_timer > 0 and t_bear_price_score >= 1.0:
                bear_score = bear_setup_env_score + t_bear_price_score
                bear_groups = bear_setup_env_groups.union(t_bear_price_groups)
                bear_reasons = bear_setup_env_reasons + t_bear_price_reasons

            # --- Regime tag for signal text ---
            regime_tag = 'T' if current_regime.get('regime') == 'trending' else 'R'
            
            # --- Emit signal if score >= threshold AND from >= 2 distinct groups ---
            is_bull_valid = bull_score >= bull_threshold and len(bull_groups) >= 2
            is_bear_valid = bear_score >= bear_threshold and len(bear_groups) >= 2

            if is_bull_valid and (i - last_bull_idx) >= COOLDOWN:
                # No-Long filter: block bullish signals in downtrend regime
                if APPLY_DIRECTIONAL_PROTECTION and current_regime.get('no_long', False):
                    pass  # Signal blocked by regime filter
                else:
                    markers.append({
                        "time": t,
                        "position": "belowBar",
                        "color": "#22c55e",
                        "shape": "arrowUp",
                        "text": f"⚡({len(bull_groups)}G) {bull_score}/7 [{regime_tag}] {'+'.join(bull_reasons)}",
                        "score": bull_score,
                        "direction": "bullish"
                    })
                    last_bull_idx = i
            elif is_bear_valid and (i - last_bear_idx) >= COOLDOWN:
                # No-Short filter: block bearish signals in uptrend regime
                if APPLY_DIRECTIONAL_PROTECTION and current_regime.get('no_short', False):
                    pass  # Signal blocked by regime filter
                else:
                    markers.append({
                        "time": t,
                        "position": "aboveBar",
                        "color": "#ef4444",
                        "shape": "arrowDown",
                        "text": f"⚡({len(bear_groups)}G) {bear_score}/7 [{regime_tag}] {'+'.join(bear_reasons)}",
                        "score": bear_score,
                        "direction": "bearish"
                    })
                    last_bear_idx = i
        
        return markers, latest_regime

    @staticmethod
    def calculate_composite_score(
        price_data: List[Dict],
        lsur_z_aligned: List[Dict],
        cvd_aligned: List[Dict],
        funding_aligned: List[Dict],
        rsi_aligned: List[Dict] = None,
        ema_fast_aligned: List[Dict] = None,
        bb_pctb_aligned: List[Dict] = None,
        oi_aligned: List[Dict] = None,
        timeframe: str = '1h'
    ) -> List[Dict]:
        """
        Calculates the Market Pulse (Composite Score) from 0 to 100 continuously.
        0-20: Extreme Bullish
        40-60: Neutral
        80-100: Extreme Bearish
        """
        if not price_data:
            return []
            
        # Simplified profiles for continuous scoring bounds
        PROFILES = {
            '15m': {'rsi': (20, 80), 'fr': (-0.006, 0.012), 'bb': (0, 1.0), 'z': (-1.8, 1.8), 'ema': 0.6},
            '1h':  {'rsi': (25, 75), 'fr': (-0.004, 0.010), 'bb': (0, 1.0), 'z': (-1.5, 1.5), 'ema': 1.2},
            '4h':  {'rsi': (30, 70), 'fr': (-0.003, 0.008), 'bb': (0, 1.0), 'z': (-1.2, 1.2), 'ema': 2.5},
            '1d':  {'rsi': (35, 65), 'fr': (-0.002, 0.006), 'bb': (0, 1.0), 'z': (-1.0, 1.0), 'ema': 4.0},
        }
        P = PROFILES.get(timeframe, PROFILES['1h'])

        # Build lookup dicts
        z_by_time = {item['time']: item['value'] for item in lsur_z_aligned}
        cvd_by_time = {item['time']: item['value'] for item in cvd_aligned}
        funding_by_time = {item['time']: item['value'] for item in funding_aligned}
        rsi_by_time = {item['time']: item['value'] for item in (rsi_aligned or [])}
        ema_fast_by_time = {item['time']: item['value'] for item in (ema_fast_aligned or [])}
        bb_by_time = {item['time']: item['value'] for item in (bb_pctb_aligned or [])}
        oi_by_time = {item['time']: item['value'] for item in (oi_aligned or [])}
        price_by_time = {p['time']: p for p in price_data}
        times = [p['time'] for p in price_data]

        scores = []
        lookback = 3

        def normalize(val, min_val, max_val, clamp=True):
            if val is None: return 0.5
            n = (val - min_val) / (max_val - min_val) if max_val != min_val else 0.5
            return max(0.0, min(1.0, n)) if clamp else n

        for i in range(lookback, len(times)):
            t = times[i]
            
            # --- 1. LSUR Z-Score (15%) ---
            z_val = z_by_time.get(t)
            s_z = normalize(z_val, P['z'][0], P['z'][1])
            
            # --- 2. CVD Momentum (20%) ---
            cvd_now = cvd_by_time.get(t)
            cvd_prev = cvd_by_time.get(times[i - 1])
            s_cvd = 0.5
            if cvd_now is not None and cvd_prev is not None:
                # Approximate normalization: if CVD has moved significantly
                # We use a recent range to estimate
                if i >= 10:
                    cvd_range_vals = [cvd_by_time.get(times[k], 0) for k in range(i-10, i+1)]
                    c_min, c_max = min(cvd_range_vals), max(cvd_range_vals)
                    c_delta = cvd_now - cvd_prev
                    c_range = max(c_max - c_min, 1)
                    # Normalize slope to roughly 0-1 where <0 is bullish(c_delta<0 means selling pressure, meaning bearish. WAIT: higher score = bearish)
                    # if cvd drops (selling pressure), score should be higher (bearish)
                    s_cvd = normalize(-c_delta, -c_range/2, c_range/2) 
            
            # --- 3. RSI (10%) ---
            rsi_val = rsi_by_time.get(t)
            s_rsi = normalize(rsi_val, P['rsi'][0], P['rsi'][1])
            
            # --- 4. Funding Rate (15%) ---
            fr_val = funding_by_time.get(t)
            s_fr = normalize(fr_val, P['fr'][0], P['fr'][1])
            
            # --- 5. EMA Zone Dist (15%) ---
            ema_val = ema_fast_by_time.get(t)
            price_bar = price_by_time.get(t)
            s_ema = 0.5
            if ema_val is not None and price_bar is not None:
                dist_pct = (price_bar['close'] - ema_val) / ema_val * 100
                s_ema = normalize(dist_pct, -P['ema'], P['ema'])
                
            # --- 6. Bollinger %B (10%) ---
            bb_val = bb_by_time.get(t)
            s_bb = normalize(bb_val, P['bb'][0], P['bb'][1])
            
            # --- 7. OI x Price Divergence (15%) ---
            # Approximated continuously:
            oi_now = oi_by_time.get(t)
            oi_prev = oi_by_time.get(times[i - lookback])
            price_prev = price_by_time.get(times[i - lookback])
            s_oi = 0.5
            if oi_now and oi_prev and oi_prev > 0 and price_bar and price_prev:
                oi_chg = (oi_now - oi_prev) / oi_prev * 100
                p_chg = (price_bar['close'] - price_prev['close']) / price_prev['close'] * 100
                
                # If price drops and OI rises (bearish buildup) -> score higher
                # If price rises and OI rises (bullish buildup) -> score lower
                if p_chg < -P['ema']/2 and oi_chg > 0:
                    s_oi = 0.8
                elif p_chg > P['ema']/2 and oi_chg > 0:
                    s_oi = 0.2
                elif oi_chg < -4.0: # Huge deleverage is neutral/reversal
                    s_oi = 0.5

            # Weighted sum
            w_z = 0.15 * s_z
            w_cvd = 0.20 * s_cvd
            w_rsi = 0.10 * s_rsi
            w_fr = 0.15 * s_fr
            w_ema = 0.15 * s_ema
            w_bb = 0.10 * s_bb
            w_oi = 0.15 * s_oi
            
            total = (w_z + w_cvd + w_rsi + w_fr + w_ema + w_bb + w_oi) * 100
            
            scores.append({
                'time': t,
                'value': round(total, 1)
            })

        return scores
