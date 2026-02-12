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
    def calculate_confluence_signals(
        price_data: List[Dict],
        lsur_z_aligned: List[Dict],
        cvd_aligned: List[Dict],
        oi_percentile: float,
        funding_aligned: List[Dict],
        lookback: int = 3
    ) -> List[Dict]:
        """
        Multi-Indicator Confluence Signal System.
        
        Combines 4 indicators at each price bar to generate high-confidence signals.
        Only emits markers when multiple indicators agree (score ≥ 3).
        
        For BULLISH confluence (potential bottom / short squeeze):
          1. LSUR Z-Score ≤ -1.5 (overcrowded shorts)
          2. CVD momentum turning UP (3-bar slope positive)
          3. OI at high percentile > 75% (lots of leverage fuel for squeeze)
          4. Funding Rate deeply negative (< -0.005%)
          
        For BEARISH confluence (potential top / long squeeze):
          1. LSUR Z-Score ≥ 1.5 (overcrowded longs)
          2. CVD momentum turning DOWN (3-bar slope negative)
          3. OI at high percentile > 75% (lots of leverage fuel for liquidation)
          4. Funding Rate elevated (> 0.015%)
        
        Args:
          oi_percentile: Current OI's percentile rank (0-100) from daily OI history.
                         High value = more leverage = more fuel for squeeze.
        
        Returns markers with confluence score for rendering on price chart.
        """
        if not price_data or len(price_data) < lookback + 1:
            return []
        
        # Build lookup dicts by time for O(1) access
        z_by_time = {item['time']: item['value'] for item in lsur_z_aligned}
        cvd_by_time = {item['time']: item['value'] for item in cvd_aligned}
        funding_by_time = {item['time']: item['value'] for item in funding_aligned}
        
        # OI check: is leverage high enough to fuel a squeeze?
        oi_is_high = oi_percentile >= 75.0  # Top quartile = lots of fuel
        
        times = [p['time'] for p in price_data]
        markers = []
        
        for i in range(lookback, len(times)):
            t = times[i]
            
            # --- Gather indicator values ---
            z_val = z_by_time.get(t)
            cvd_now = cvd_by_time.get(t)
            funding_now = funding_by_time.get(t)
            
            # CVD lookback values for momentum
            cvd_prev = cvd_by_time.get(times[i - lookback])
            
            if z_val is None:
                continue
            
            # --- Score BULLISH confluence ---
            bull_score = 0
            bull_reasons = []
            
            # 1. LSUR Z-Score: overcrowded shorts
            if z_val <= -1.5:
                bull_score += 1
                bull_reasons.append('Z')
            
            # 2. CVD momentum: buying pressure picking up
            if cvd_now is not None and cvd_prev is not None:
                cvd_delta = cvd_now - cvd_prev
                if cvd_delta > 0:
                    bull_score += 1
                    bull_reasons.append('CVD↑')
            
            # 3. OI high percentile: lots of leverage fuel for short squeeze
            if oi_is_high:
                bull_score += 1
                bull_reasons.append(f'OI{int(oi_percentile)}%')
            
            # 4. Funding deep negative: capitulation
            if funding_now is not None and funding_now < -0.005:
                bull_score += 1
                bull_reasons.append('FR-')
            
            # --- Score BEARISH confluence ---
            bear_score = 0
            bear_reasons = []
            
            # 1. LSUR Z-Score: overcrowded longs
            if z_val >= 1.5:
                bear_score += 1
                bear_reasons.append('Z')
            
            # 2. CVD momentum: selling pressure increasing
            if cvd_now is not None and cvd_prev is not None:
                cvd_delta = cvd_now - cvd_prev
                if cvd_delta < 0:
                    bear_score += 1
                    bear_reasons.append('CVD↓')
            
            # 3. OI high percentile: lots of leverage fuel for long liquidation
            if oi_is_high:
                bear_score += 1
                bear_reasons.append(f'OI{int(oi_percentile)}%')
            
            # 4. Funding elevated: greed / overleveraged
            if funding_now is not None and funding_now > 0.015:
                bear_score += 1
                bear_reasons.append('FR+')
            
            # --- Emit marker if confluence is strong enough ---
            if bull_score >= 3:
                markers.append({
                    "time": t,
                    "position": "belowBar",
                    "color": "#22c55e",       # Green
                    "shape": "arrowUp",
                    "text": f"⚡{bull_score}/4 {'+'.join(bull_reasons)}",
                    "score": bull_score,
                    "direction": "bullish"
                })
            elif bear_score >= 3:
                markers.append({
                    "time": t,
                    "position": "aboveBar",
                    "color": "#ef4444",       # Red
                    "shape": "arrowDown",
                    "text": f"⚡{bear_score}/4 {'+'.join(bear_reasons)}",
                    "score": bear_score,
                    "direction": "bearish"
                })
        
        return markers
