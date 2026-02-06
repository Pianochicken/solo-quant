import pandas as pd
import numpy as np
from typing import List, Dict
from api.quant.grid_bot import GridBot

class Backtester:
    def __init__(self, bot: GridBot, data: List[Dict]):
        self.bot = bot
        self.data = data # List of {'time', 'open', 'high', 'low', 'close'}
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

        # 1. Initialization
        start_price = self.data[0]['close']
        self._initialize_grid(start_price)
        
        # 2. Loop
        for candle in self.data:
            self._process_candle(candle)
            self._record_equity(candle['time'], candle['close'])
            
        return {
            "trades": self.trades,
            "equity": self.equity_curve,
            "final_balance": self.equity_curve[-1]['value'] if self.equity_curve else 0
        }

    def _initialize_grid(self, current_price):
        """
        Buy initial inventory for grids ABOVE current price.
        """
        # Grids are fixed levels
        grids = self.bot.grids
        
        # Determine which grids are "Sell Orders" (Above Price) and "Buy Orders" (Below Price)
        # Actually, in a pure geometric grid, you HOLD the asset for the levels above you.
        # So for every grid level > current_price, you need 1 unit of base asset (conceptually).
        
        amount_per_grid = (self.bot.investment / self.bot.grid_count) / current_price
        
        sell_grids = [g for g in grids if g > current_price]
        buy_grids = [g for g in grids if g < current_price]
        
        # Buy initial inventory
        initial_buy_cost = len(sell_grids) * amount_per_grid * current_price
        if initial_buy_cost > self.balance:
            # Adjust amount if not enough funds (simplified)
            amount_per_grid = self.balance / (len(sell_grids) * current_price)
            initial_buy_cost = self.balance
            
        self.balance -= initial_buy_cost
        self.inventory += len(sell_grids) * amount_per_grid
        self.amount_per_grid = amount_per_grid
        
        # Setup Open Orders
        # Sells at Sell Grids
        for p in sell_grids:
            self.open_orders.append({'price': p, 'side': 'sell', 'amount': amount_per_grid})
        # Buys at Buy Grids
        for p in buy_grids:
            self.open_orders.append({'price': p, 'side': 'buy', 'amount': amount_per_grid})
            
    def _process_candle(self, candle):
        low = candle['low']
        high = candle['high']
        
        # Check Execution
        # We need to handle multiple fills in one candle?
        # For MVP, check if any open order price is within [low, high]
        
        # Filter out executed orders
        remaining_orders = []
        new_orders = []
        
        for order in self.open_orders:
            price = order['price']
            
            # HIT?
            if low <= price <= high:
                # EXECUTE
                self._execute_trade(order, candle['time'])
                
                # RE-GRID logic:
                # If we Sold at X, we place a Buy at the grid below X.
                # If we Bought at Y, we place a Sell at the grid above Y.
                # Since our grids are fixed arithmetic levels, we just find the neighbor index.
                
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
        
        if order['side'] == 'buy':
            self.balance -= cost
            self.inventory += order['amount']
        else:
            self.balance += cost
            self.inventory -= order['amount']
            
        self.trades.append({
            "time": time,
            "side": order['side'],
            "price": price,
            "amount": order['amount']
        })

    def _record_equity(self, time, current_price):
        # Equity = Cash + Asset Value
        asset_value = self.inventory * current_price
        total_equity = self.balance + asset_value
        self.equity_curve.append({"time": time, "value": total_equity})

    def _find_nearest_grid_index(self, price):
        # Find index in self.bot.grids closest to price
        array = np.array(self.bot.grids)
        idx = (np.abs(array - price)).argmin()
        return idx
