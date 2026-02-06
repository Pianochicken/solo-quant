from typing import Dict, List, Any

class BaseStrategy:
    """
    Abstract Base Class for all SoloQuant strategies.
    """
    def __init__(self, symbol: str):
        self.symbol = symbol
        
    def on_market_data(self, data: Dict):
        """
        Called when new market data (candle/ticker) prevents.
        Should return a list of signals or orders.
        """
        raise NotImplementedError
    
    def generate_grid_levels(self, current_price: float) -> List[float]:
        """
        For grid bots: calculate price lines.
        """
        return []
