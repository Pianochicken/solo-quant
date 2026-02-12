import numpy as np
from .strategy import BaseStrategy
from typing import List, Dict

class GridBot(BaseStrategy):
    """
    Arithmetic Grid Trading Bot.
    """
    def __init__(self, symbol: str, lower_price: float, upper_price: float, grid_count: int, investment: float):
        super().__init__(symbol)
        self.lower_price = lower_price
        self.upper_price = upper_price
        self.grid_count = grid_count
        self.investment = investment
        
        # Calculate Grids immediately
        self.grids = self._calculate_grids()

    def _calculate_grids(self) -> List[float]:
        """
        Generates arithmetic grid levels.
        """
        if self.lower_price >= self.upper_price:
            raise ValueError("Lower price must be < Upper price")
            
        # Linspace generates 'grid_count' lines including start and end
        # But traditionally, grid_count is number of "zones" or number of lines?
        # Let's assume grid_count is number of ORDERS (lines).
        return np.linspace(self.lower_price, self.upper_price, self.grid_count).tolist()

    def get_orders_for_price(self, current_price: float, sentiment_score: float = 0.0) -> List[Dict]:
        """
        Given the current price and sentiment, determine which orders should be placed.
        Sentiment Score: LSUR Z-Score.
        > 2.0: Crowd Euphoria (Bearish) -> Skip BUY
        < -2.0: Crowd Panic (Bullish) -> Skip SELL
        """
        orders = []
        amount_per_grid = self.investment / self.grid_count / current_price 
        
        for price in self.grids:
            # Safer spread check
            if abs(price - current_price) / current_price < 0.002: 
                continue 
                
            if price < current_price:
                # BUY LOGIC
                # Sentiment Guard: If Crowd is Euphoric (Z > 2), Don't Buy (Wait for dump)
                if sentiment_score > 2.0:
                    continue
                    
                orders.append({
                    "symbol": self.symbol,
                    "side": "buy",
                    "type": "limit",
                    "price": price,
                    "amount": amount_per_grid
                })
            else:
                # SELL LOGIC
                # Sentiment Guard: If Crowd is Panic (Z < -2), Don't Sell (Wait for pump)
                if sentiment_score < -2.0:
                    continue
                    
                orders.append({
                    "symbol": self.symbol,
                    "side": "sell",
                    "type": "limit",
                    "price": price,
                    "amount": amount_per_grid
                })
        return orders
