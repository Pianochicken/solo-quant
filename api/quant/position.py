"""
Position management for Signal-driven strategy.
Handles TP/SL/Trailing Stop lifecycle for both Long and Short positions.
"""

from dataclasses import dataclass, field
from typing import Optional
import uuid


@dataclass
class Position:
    """
    Represents a single trading position with TP/SL/Trailing Stop management.
    
    Lifecycle:
        1. Created at entry with TP/SL levels pre-calculated
        2. Updated every candle via update() → check_exit()
        3. Closed via close() with exit reason
    """
    side: str               # 'long' | 'short'
    entry_price: float
    entry_time: int          # timestamp ms
    size: float              # base asset units
    take_profit: float       # absolute price level
    stop_loss: float         # absolute price level
    trailing_stop_pct: float # trailing stop retracement %
    trailing_activation_pct: float  # min profit % to activate trailing

    # Auto-generated
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    cost: float = 0.0       # entry_price * size (USDT notional)

    # Trailing Stop state
    trailing_active: bool = False
    trailing_stop_price: float = 0.0
    highest_since_entry: float = 0.0   # tracked for Long
    lowest_since_entry: float = float('inf')  # tracked for Short

    # Exit info (filled on close)
    exit_price: float = 0.0
    exit_time: int = 0
    exit_reason: str = ''    # 'tp' | 'sl' | 'trailing' | 'signal_reverse'
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    is_closed: bool = False

    def __post_init__(self):
        self.cost = self.entry_price * self.size
        if self.side == 'long':
            self.highest_since_entry = self.entry_price
        else:
            self.lowest_since_entry = self.entry_price

    def update(self, high: float, low: float, close: float) -> None:
        """
        Update trailing stop tracking with the latest candle data.
        Must be called BEFORE check_exit() each bar.
        """
        if self.is_closed:
            return

        if self.side == 'long':
            # Track the highest high since entry
            if high > self.highest_since_entry:
                self.highest_since_entry = high

            # Activate trailing once profit exceeds activation threshold
            unrealized_pct = (self.highest_since_entry - self.entry_price) / self.entry_price * 100
            if not self.trailing_active and unrealized_pct >= self.trailing_activation_pct:
                self.trailing_active = True

            # Update trailing stop price (ratchets up, never down)
            if self.trailing_active:
                new_trail = self.highest_since_entry * (1 - self.trailing_stop_pct / 100)
                if new_trail > self.trailing_stop_price:
                    self.trailing_stop_price = new_trail

        else:  # short
            # Track the lowest low since entry
            if low < self.lowest_since_entry:
                self.lowest_since_entry = low

            # Activate trailing once profit exceeds activation threshold
            unrealized_pct = (self.entry_price - self.lowest_since_entry) / self.entry_price * 100
            if not self.trailing_active and unrealized_pct >= self.trailing_activation_pct:
                self.trailing_active = True

            # Update trailing stop price (ratchets down, never up)
            if self.trailing_active:
                new_trail = self.lowest_since_entry * (1 + self.trailing_stop_pct / 100)
                if self.trailing_stop_price == 0.0 or new_trail < self.trailing_stop_price:
                    self.trailing_stop_price = new_trail

    def check_exit(self, high: float, low: float, close: float) -> Optional[str]:
        """
        Check if any exit condition is hit during this candle.
        
        Returns:
            exit_reason string ('sl', 'tp', 'trailing') or None if no exit.
        
        Priority: Stop Loss → Take Profit → Trailing Stop
        (SL first because it protects capital; in a gap-down scenario
         both SL and TP could be hit in the same candle — SL takes precedence.)
        """
        if self.is_closed:
            return None

        if self.side == 'long':
            # Stop Loss: price drops to or below SL level
            if low <= self.stop_loss:
                return 'sl'
            # Take Profit: price rises to or above TP level
            if high >= self.take_profit:
                return 'tp'
            # Trailing Stop: price drops to or below trailing level
            if self.trailing_active and low <= self.trailing_stop_price:
                return 'trailing'

        else:  # short
            # Stop Loss: price rises to or above SL level
            if high >= self.stop_loss:
                return 'sl'
            # Take Profit: price drops to or below TP level
            if low <= self.take_profit:
                return 'tp'
            # Trailing Stop: price rises to or above trailing level
            if self.trailing_active and high >= self.trailing_stop_price:
                return 'trailing'

        return None

    def close(self, exit_price: float, exit_time: int, reason: str, fee_rate: float = 0.0) -> float:
        """
        Close this position and calculate realized PnL.
        
        Args:
            exit_price: The price at which the position is closed.
            exit_time: Timestamp (ms) of exit.
            reason: Exit reason ('tp', 'sl', 'trailing', 'signal_reverse').
            fee_rate: Fee rate for the exit trade.
            
        Returns:
            Realized PnL (after fees) in quote currency (USDT).
        """
        if self.is_closed:
            return 0.0

        self.exit_price = exit_price
        self.exit_time = exit_time
        self.exit_reason = reason
        self.is_closed = True

        # Calculate raw PnL
        if self.side == 'long':
            raw_pnl = (exit_price - self.entry_price) * self.size
        else:  # short
            raw_pnl = (self.entry_price - exit_price) * self.size

        # Fees: entry fee + exit fee
        entry_fee = self.cost * fee_rate
        exit_fee = exit_price * self.size * fee_rate
        self.fees_paid = entry_fee + exit_fee

        self.realized_pnl = raw_pnl - self.fees_paid
        return self.realized_pnl

    def get_exit_price_for_reason(self, reason: str, high: float, low: float) -> float:
        """
        Determine the exact fill price for a given exit reason.
        
        In a real exchange, SL/TP are limit orders that fill at the order price.
        In backtesting, we simulate this by filling at the trigger level.
        """
        if self.side == 'long':
            if reason == 'sl':
                return self.stop_loss
            elif reason == 'tp':
                return self.take_profit
            elif reason == 'trailing':
                return self.trailing_stop_price
        else:  # short
            if reason == 'sl':
                return self.stop_loss
            elif reason == 'tp':
                return self.take_profit
            elif reason == 'trailing':
                return self.trailing_stop_price

        # Fallback: close price (for signal_reverse, etc.)
        return (high + low) / 2

    def unrealized_pnl(self, current_price: float) -> float:
        """Calculate unrealized PnL at a given mark price."""
        if self.is_closed:
            return 0.0
        if self.side == 'long':
            return (current_price - self.entry_price) * self.size
        else:
            return (self.entry_price - current_price) * self.size

    def to_dict(self) -> dict:
        """Serialize position to dict for API responses."""
        return {
            "id": self.id,
            "side": self.side,
            "entry_price": self.entry_price,
            "entry_time": self.entry_time,
            "size": round(self.size, 8),
            "cost": round(self.cost, 4),
            "take_profit": round(self.take_profit, 4),
            "stop_loss": round(self.stop_loss, 4),
            "trailing_active": self.trailing_active,
            "trailing_stop_price": round(self.trailing_stop_price, 4),
            "exit_price": round(self.exit_price, 4),
            "exit_time": self.exit_time,
            "exit_reason": self.exit_reason,
            "realized_pnl": round(self.realized_pnl, 4),
            "fees_paid": round(self.fees_paid, 4),
            "is_closed": self.is_closed,
        }
