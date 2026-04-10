import pandas as pd
import numpy as np
from typing import List, Dict
from api.quant.grid_bot import GridBot

class Backtester:
    def __init__(self, bot: GridBot, data: List[Dict], sentiment_data: List[Dict] = None, regime_data: Dict = None, enable_protection: bool = False):
        self.bot = bot
        self.data = data # List of {'time', 'open', 'high', 'low', 'close'}
        # sentiment_data: List of {'time', 'value'} (LSUR Z-Score)
        # Convert to dict for fast lookup: {time_ms: z_score}
        self.sentiment_map = {d['time']: d['value'] for d in sentiment_data} if sentiment_data else {}
        self.regime_map = regime_data if regime_data else {}
        self.enable_protection = enable_protection
        
        self.trades = []
        self.equity_curve = []
        
        # State
        self.balance = bot.investment
        self.inventory = 0.0 # Amount of Base Asset
        self.open_orders = [] # List of {'price', 'side', 'amount'}
        
        # Initial Setup matches "Dry Run" logic: 
        # But for backtest, we assume we START with USDT and place Buy Orders below, Sell Orders above?
        # A standard Grid Bot starts by buying ~50% inventory if price is in middle.
        # For simplicity MVP: 
        # We assume we enter at the first candle's Close Price.
        # We buy necessary inventory for the "Sell Grids" (grids above current price).
        # We place "Buy Grids" (grids below current price).
        
    def run(self):
        if not self.data:
            return {}

        self.protected_buys = 0
        self.protected_sells = 0

        # ... existing initialisation ...
        start_price = self.data[0]['close']
        start_time = self.data[0]['time']
        self._initialize_grid(start_price, start_time)
        
        # 2. Loop
        for candle in self.data:
            self._process_candle(candle)
            
            # Record Equity DO NOT record every candle for performance if list is huge?
            # 1h candles are fine.
            # Equity = Cash + Asset Value
            asset_value = self.inventory * candle['close']
            total_equity = self.balance + asset_value
            self.equity_curve.append({"time": candle['time'], "value": total_equity})
            
        return {
            "trades": self.trades,
            "equity": self.equity_curve,
            "final_balance": self.equity_curve[-1]['value'] if self.equity_curve else 0,
            "ai_metrics": {
                "protected_buys": self.protected_buys,
                "protected_sells": self.protected_sells
            }
        }

    def _initialize_grid(self, current_price, time):
        """
        Buy initial inventory for grids ABOVE current price.
        """
        # Grids are fixed levels
        grids = self.bot.grids
        
        # Determine which grids are "Sell Orders" (Above Price) and "Buy Orders" (Below Price)
        # Actually, in a pure geometric grid, you HOLD the asset for the levels above you.
        # So for every grid level > current_price, you need 1 unit of base asset (conceptually).
        
        sell_grids = [g for g in grids if g > current_price]
        buy_grids = [g for g in grids if g < current_price]
        
        # Calculate amount per grid roughly
        # If we have 1000 USDT and 10 grids, and price is 100.
        # We need to buy inventory for 5 sell grids. 5 * (1000/10/100) = 5 units. Cost 500.
        # We keep 500 USDT for 5 buy grids.
        
        # Correct calculation:
        total_grids = self.bot.grid_count
        amount_per_grid = (self.bot.investment / total_grids) / current_price
        
        initial_buy_cost = len(sell_grids) * amount_per_grid * current_price
        
        if initial_buy_cost > self.balance:
            # Adjust amount if not enough funds (simplified)
            factor = self.balance / initial_buy_cost
            amount_per_grid *= factor
            initial_buy_cost = self.balance
            
        self.balance -= initial_buy_cost
        self.inventory += len(sell_grids) * amount_per_grid
        self.amount_per_grid = amount_per_grid
        
        # Record initial grid inventory purchase if any
        if self.inventory > 0:
            self.trades.append({
                "time": time,
                "side": 'buy',
                "price": current_price,
                "amount": self.inventory,
                "realized_pnl": 0.0,
                "equity": self.balance + (self.inventory * current_price)
            })
        
        # Setup Open Orders
        self.open_orders = []
        # Sells at Sell Grids
        for p in sell_grids:
            self.open_orders.append({'price': p, 'side': 'sell', 'amount': amount_per_grid})
        # Buys at Buy Grids
        for p in buy_grids:
            self.open_orders.append({'price': p, 'side': 'buy', 'amount': amount_per_grid})
            
    def _process_candle(self, candle):
        low = candle['low']
        high = candle['high']
        time = candle['time']
        
        # Get Sentiment & Regime for this candle
        sentiment_score = self.sentiment_map.get(time, 0.0)
        regime_state = self.regime_map.get(time, {})
        APPLY_DIRECTIONAL_PROTECTION = self.enable_protection
        
        # Filter out executed orders
        remaining_orders = []
        new_orders = []
        
        for order in self.open_orders:
            price = order['price']
            
            # HIT?
            if low <= price <= high:
                
                # --- AI SMART GUARDRAILS ---
                # Check if we should PAUSE execution due to market conditions
                
                # Sells: We pause selling if the market is trending UP strongly (no_short = True)
                if APPLY_DIRECTIONAL_PROTECTION and order['side'] == 'sell' and regime_state.get('no_short', False):
                     # Market is heavily bullish. HODL inventory instead of selling early.
                     remaining_orders.append(order)
                     self.protected_sells += 1
                     continue
                     
                # Buys: We pause buying if the market is trending DOWN strongly (no_long = True)
                if APPLY_DIRECTIONAL_PROTECTION and order['side'] == 'buy' and regime_state.get('no_long', False):
                     # Catching knives. Wait for trend to break before buying more grids.
                     remaining_orders.append(order)
                     self.protected_buys += 1
                     continue
                
                # Legacy basic sentiment guard fallback if no regime data
                if not regime_state:
                    if order['side'] == 'buy' and sentiment_score > 2.0:
                         remaining_orders.append(order)
                         continue
                    if order['side'] == 'sell' and sentiment_score < -2.0:
                         remaining_orders.append(order)
                         continue
                # -----------------------

                # EXECUTE
                self._execute_trade(order, time)
                
                # RE-GRID logic:
                grid_index = self._find_nearest_grid_index(price)
                
                if order['side'] == 'sell':
                    # Sold High -> Buy Low (Index - 1)
                    if grid_index > 0:
                        buy_price = self.bot.grids[grid_index - 1]
                        new_orders.append({'price': buy_price, 'side': 'buy', 'amount': self.amount_per_grid})
                else:
                    # Bought Low -> Sell High (Index + 1)
                    if grid_index < len(self.bot.grids) - 1:
                        sell_price = self.bot.grids[grid_index + 1]
                        new_orders.append({'price': sell_price, 'side': 'sell', 'amount': self.amount_per_grid})
            else:
                remaining_orders.append(order)
        
        self.open_orders = remaining_orders + new_orders

    def _execute_trade(self, order, time):
        price = order['price']
        cost = price * order['amount']
        
        realized_pnl = 0.0
        
        if order['side'] == 'buy':
            self.balance -= cost
            self.inventory += order['amount']
        else:
            self.balance += cost
            self.inventory -= order['amount']
            # Compute Grid Profit for Sell Orders
            idx = self._find_nearest_grid_index(price)
            if idx > 0:
                buy_price = self.bot.grids[idx - 1]
                realized_pnl = (price - buy_price) * order['amount']
                
        current_equity = self.balance + (self.inventory * price)
            
        self.trades.append({
            "time": time,
            "side": order['side'],
            "price": price,
            "amount": order['amount'],
            "realized_pnl": realized_pnl,
            "equity": current_equity
        })

    def _find_nearest_grid_index(self, price):
        # Find index in self.bot.grids closest to price
        array = np.array(self.bot.grids)
        idx = (np.abs(array - price)).argmin()
        return idx
