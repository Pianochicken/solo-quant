import ccxt
import logging
from typing import Dict, Optional

logger = logging.getLogger("solo_quant")

class ExecutionHandler:
    """
    Handles interactions with the exchange execution API.
    Enforces safety rules and 'Dry Run' mode.
    """
    def __init__(self, exchange: ccxt.Exchange, dry_run: bool = True):
        self.exchange = exchange
        self.dry_run = dry_run
        
    def place_order(self, symbol: str, side: str, order_type: str, amount: float, price: Optional[float] = None, params: Dict = {}) -> Dict:
        """
        Places an order or logs it if in Dry Run.
        """
        logger.info(f"[EXECUTION] Request: {side.upper()} {amount} {symbol} @ {price} ({order_type})")
        
        if self.dry_run:
            logger.info(">> DRY RUN BLOCKED: Order would be placed here.")
            # Limit orders are 'open' until filled. Market orders are immediate 'closed'.
            status = 'open' if order_type.lower() == 'limit' else 'closed'
            
            return {
                "id": f"dry_run_{int(price or 0)}_{side}_{amount}",
                "symbol": symbol,
                "side": side,
                "amount": amount,
                "price": price,
                "status": status,
                "type": order_type,
                "info": {"msg": "This is a simulated order"}
            }
            
        try:
            # Real Execution
            if order_type.lower() == 'limit':
                return self.exchange.create_limit_order(symbol, side, amount, price, params)
            elif order_type.lower() == 'market':
                return self.exchange.create_market_order(symbol, side, amount, params)
            else:
                raise ValueError(f"Unsupported order type: {order_type}")
                
        except Exception as e:
            logger.error(f"Order Placement Failed: {e}")
            raise e

    def cancel_all_orders(self, symbol: str):
        if self.dry_run:
            logger.info(f">> DRY RUN: Would cancel all orders for {symbol}")
            return True
            
        try:
            return self.exchange.cancel_all_orders(symbol)
        except Exception as e:
            logger.error(f"Cancel Failed: {e}")
            raise e
