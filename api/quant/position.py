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
        2. Evaluated every candle via check_exit() → if not exited, update()
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

    # Partial TP state (Two-stage TP1 + Breakeven Runner)
    enable_partial_tp: bool = False
    partial_tp_done: bool = False
    initial_size: float = 0.0
    initial_cost: float = 0.0
    partial_realized_pnl: float = 0.0
    partial_fees_paid: float = 0.0

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
        self.initial_size = self.size
        self.initial_cost = self.cost
        if self.side == 'long':
            self.highest_since_entry = self.entry_price
        else:
            self.lowest_since_entry = self.entry_price

    def update(self, high: float, low: float, close: float) -> None:
        """
        Update trailing stop tracking with the latest candle data.
        Cross-candle tracking with safe clamping to prevent underwater gap-through
        while avoiding premature exit on current candle.
        """
        if self.is_closed:
            return

        if self.side == 'long':
            if high > self.highest_since_entry:
                self.highest_since_entry = high

            unrealized_pct = (self.highest_since_entry - self.entry_price) / self.entry_price * 100
            if unrealized_pct >= self.trailing_activation_pct:
                self.trailing_active = True
                candidate_trail = max(self.highest_since_entry * (1 - self.trailing_stop_pct / 100), self.entry_price * 1.002)
                # If close dipped below candidate_trail, clamp trailing_stop_price below close
                # so next candle does not gap-through above market, while never dipping below stop_loss
                if close <= candidate_trail:
                    safe_trail = max(self.stop_loss, close * 0.999)
                else:
                    safe_trail = candidate_trail

                if safe_trail > self.trailing_stop_price:
                    self.trailing_stop_price = safe_trail

        else:  # short
            if low < self.lowest_since_entry:
                self.lowest_since_entry = low

            unrealized_pct = (self.entry_price - self.lowest_since_entry) / self.entry_price * 100
            if unrealized_pct >= self.trailing_activation_pct:
                self.trailing_active = True
                candidate_trail = min(self.lowest_since_entry * (1 + self.trailing_stop_pct / 100), self.entry_price * 0.998)
                # If close bounced above candidate_trail, clamp trailing_stop_price above close,
                # never exceeding stop_loss
                if close >= candidate_trail:
                    safe_trail = min(self.stop_loss, close * 1.001)
                else:
                    safe_trail = candidate_trail

                if self.trailing_stop_price == 0.0 or safe_trail < self.trailing_stop_price:
                    self.trailing_stop_price = safe_trail

    def check_exit(self, high: float, low: float, close: float, open_price: Optional[float] = None) -> Optional[str]:
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
            # Stop Loss: gap down on open or price drops to/below SL level
            if (open_price is not None and open_price <= self.stop_loss) or low <= self.stop_loss:
                return 'sl'
            # Take Profit: gap up on open or price rises to/above TP level
            if (open_price is not None and open_price >= self.take_profit) or high >= self.take_profit:
                return 'tp'
            # Trailing Stop: price drops to or below trailing level
            if self.trailing_active and ((open_price is not None and open_price <= self.trailing_stop_price) or low <= self.trailing_stop_price):
                return 'trailing'

        else:  # short
            # Stop Loss: gap up on open or price rises to/above SL level
            if (open_price is not None and open_price >= self.stop_loss) or high >= self.stop_loss:
                return 'sl'
            # Take Profit: gap down on open or price drops to/below TP level
            if (open_price is not None and open_price <= self.take_profit) or low <= self.take_profit:
                return 'tp'
            # Trailing Stop: price rises to or above trailing level
            if self.trailing_active and ((open_price is not None and open_price >= self.trailing_stop_price) or high >= self.trailing_stop_price):
                return 'trailing'

        return None

    def check_partial_tp(self, high: float, low: float, open_price: Optional[float] = None, close: Optional[float] = None) -> Optional[float]:
        """
        Check if TP1 (partial take profit) is hit.
        Triggered when price reaches trailing_activation_pct without hitting stop loss.
        """
        if not self.enable_partial_tp or self.partial_tp_done or self.is_closed or self.trailing_activation_pct <= 0:
            return None

        if self.side == 'long':
            tp1_price = self.entry_price * (1 + self.trailing_activation_pct / 100)
            if high >= tp1_price and low > self.stop_loss:
                if open_price is not None and open_price > tp1_price:
                    return open_price
                return tp1_price
        else:  # short
            tp1_price = self.entry_price * (1 - self.trailing_activation_pct / 100)
            if low <= tp1_price and high < self.stop_loss:
                if open_price is not None and open_price < tp1_price:
                    return open_price
                return tp1_price

        return None

    def execute_partial_tp(self, fill_price: float, fee_rate: float = 0.0, ratio: float = 0.5) -> tuple[float, float, float]:
        """
        Execute partial take profit (TP1):
          - Closes `ratio` of the position (defaults to 50%)
          - Updates remaining size and cost
          - Moves stop loss of remaining position to breakeven floor (entry ± 0.2%)
          - Relaxes trailing stop distance of remaining runner by 1.4x
          - Activates trailing stop
        Returns:
          (closed_size, net_pnl, part_fee)
        """
        closed_size = self.size * ratio
        self.size -= closed_size
        self.cost = self.entry_price * self.size

        if self.side == 'long':
            raw_pnl = (fill_price - self.entry_price) * closed_size
        else:
            raw_pnl = (self.entry_price - fill_price) * closed_size

        part_entry_fee = self.entry_price * closed_size * fee_rate
        part_exit_fee = fill_price * closed_size * fee_rate
        part_fee = part_entry_fee + part_exit_fee
        net_pnl = raw_pnl - part_fee

        self.partial_realized_pnl += net_pnl
        self.partial_fees_paid += part_fee
        self.partial_tp_done = True
        self.trailing_active = True

        # Move SL of runner to breakeven floor
        if self.side == 'long':
            self.stop_loss = max(self.stop_loss, self.entry_price * 1.002)
        else:
            self.stop_loss = min(self.stop_loss, self.entry_price * 0.998)

        # Relax trailing stop distance 1.4x for runner
        self.trailing_stop_pct *= 1.4

        return closed_size, net_pnl, part_fee

    def close(self, exit_price: float, exit_time: int, reason: str, fee_rate: float = 0.0) -> float:
        """
        Close this position and calculate remaining realized PnL.
        
        Args:
            exit_price: The price at which the position is closed.
            exit_time: Timestamp (ms) of exit.
            reason: Exit reason ('tp', 'sl', 'trailing', 'signal_reverse').
            fee_rate: Fee rate for the exit trade.
            
        Returns:
            Realized PnL (after fees) for the remaining position size.
        """
        if self.is_closed:
            return 0.0

        self.exit_price = exit_price
        self.exit_time = exit_time
        self.exit_reason = reason
        self.is_closed = True

        # Calculate raw PnL for remaining size
        if self.side == 'long':
            remaining_raw_pnl = (exit_price - self.entry_price) * self.size
        else:  # short
            remaining_raw_pnl = (self.entry_price - exit_price) * self.size

        # Fees for remaining size: entry fee + exit fee
        remaining_entry_fee = self.cost * fee_rate
        remaining_exit_fee = exit_price * self.size * fee_rate
        remaining_fees = remaining_entry_fee + remaining_exit_fee
        remaining_net_pnl = remaining_raw_pnl - remaining_fees

        self.fees_paid = self.partial_fees_paid + remaining_fees
        self.realized_pnl = self.partial_realized_pnl + remaining_net_pnl
        return remaining_net_pnl

    def get_exit_price_for_reason(self, reason: str, high: float, low: float, open_price: Optional[float] = None) -> float:
        """
        Determine the exact fill price for a given exit reason.
        Enforces realistic market execution constraints (gap slippage and high/low bounds).
        """
        if self.side == 'long':
            if reason == 'sl':
                if open_price is not None and open_price < self.stop_loss:
                    return open_price
                return min(self.stop_loss, high)
            elif reason == 'trailing':
                if open_price is not None and open_price < self.trailing_stop_price:
                    return open_price
                return min(self.trailing_stop_price, high)
            elif reason == 'tp':
                if open_price is not None and open_price > self.take_profit:
                    return open_price
                return max(self.take_profit, low)
        else:  # short
            if reason == 'sl':
                if open_price is not None and open_price > self.stop_loss:
                    return open_price
                return max(self.stop_loss, low)
            elif reason == 'trailing':
                if open_price is not None and open_price > self.trailing_stop_price:
                    return open_price
                return max(self.trailing_stop_price, low)
            elif reason == 'tp':
                if open_price is not None and open_price < self.take_profit:
                    return open_price
                return min(self.take_profit, high)

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
            "initial_size": round(self.initial_size, 8),
            "cost": round(self.cost, 4),
            "take_profit": round(self.take_profit, 4),
            "stop_loss": round(self.stop_loss, 4),
            "trailing_active": self.trailing_active,
            "trailing_stop_price": round(self.trailing_stop_price, 4),
            "partial_tp_done": self.partial_tp_done,
            "partial_realized_pnl": round(self.partial_realized_pnl, 4),
            "exit_price": round(self.exit_price, 4),
            "exit_time": self.exit_time,
            "exit_reason": self.exit_reason,
            "realized_pnl": round(self.realized_pnl, 4),
            "fees_paid": round(self.fees_paid, 4),
            "is_closed": self.is_closed,
        }
