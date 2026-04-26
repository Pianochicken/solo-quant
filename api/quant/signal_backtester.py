"""
Signal-driven Backtester for Solo-Quant v2.

Takes confluence signals from IndicatorEngine and simulates trading
with TP/SL/Trailing Stop position management.
Supports both Long and Short positions.
"""

import numpy as np
from typing import List, Dict, Optional
from api.quant.position import Position
from api.quant.signal_strategy import SignalStrategyConfig


class SignalBacktester:
    """
    Backtests a signal-driven strategy over historical OHLCV data.
    
    Flow per candle:
        1. Update all open positions (trailing high/low)
        2. Check exits (SL → TP → Trailing)
        3. Check for new signal at this timestamp
        4. Record equity snapshot
    """

    def __init__(
        self,
        config: SignalStrategyConfig,
        price_data: List[Dict],
        signals: List[Dict],
    ):
        """
        Args:
            config: Strategy configuration parameters.
            price_data: List of OHLCV dicts with keys: time, open, high, low, close.
            signals: List of confluence signal dicts from IndicatorEngine.
                     Each must have: time, direction ('bullish'|'bearish'), score.
        """
        self.config = config
        self.price_data = price_data
        self.signals = signals

        # Build signal lookup: {time_ms: signal_dict}
        self.signal_map: Dict[int, Dict] = {}
        for sig in signals:
            self.signal_map[sig['time']] = sig

        # State
        self.balance: float = config.investment
        self.open_positions: List[Position] = []
        self.closed_positions: List[Position] = []
        self.trades: List[Dict] = []
        self.equity_curve: List[Dict] = []
        self.total_fees_paid: float = 0.0

    def run(self) -> Dict:
        """
        Execute the backtest over all candles.
        
        Returns:
            Dict with keys: trades, equity, final_balance, total_fees_paid, metrics
        """
        if not self.price_data:
            return self._empty_result()

        for candle in self.price_data:
            high = candle['high']
            low = candle['low']
            close = candle['close']
            time = candle['time']

            # --- Step 1 & 2: Update positions and check exits ---
            self._process_exits(high, low, close, time)

            # --- Step 3: Check for new signals ---
            signal = self.signal_map.get(time)
            if signal:
                self._process_signal(signal, candle)

            # --- Step 4: Record equity ---
            equity = self._calculate_equity(close)
            self.equity_curve.append({"time": time, "value": equity})

        # Force-close any remaining open positions at last candle's close
        if self.price_data:
            last = self.price_data[-1]
            self._close_all_open(last['close'], last['time'], reason='backtest_end')

        return self._build_result()

    # ─── Internal: Exit Processing ──────────────────────────────────

    def _process_exits(self, high: float, low: float, close: float, time: int) -> None:
        """Update all open positions and close those that hit exit conditions."""
        still_open = []
        for pos in self.open_positions:
            # Update trailing stop tracking
            pos.update(high, low, close)

            # Check exit conditions
            exit_reason = pos.check_exit(high, low, close)
            if exit_reason:
                exit_price = pos.get_exit_price_for_reason(exit_reason, high, low)
                self._close_position(pos, exit_price, time, exit_reason)
            else:
                still_open.append(pos)

        self.open_positions = still_open

    def _close_position(self, pos: Position, exit_price: float, time: int, reason: str) -> None:
        """Close a position and record the trade."""
        pnl = pos.close(exit_price, time, reason, fee_rate=self.config.fee_rate)
        self.total_fees_paid += pos.fees_paid

        # Return capital: for Long, we get back exit_price * size; for Short, entry + pnl
        if pos.side == 'long':
            self.balance += exit_price * pos.size - (exit_price * pos.size * self.config.fee_rate)
        else:
            # Short: we initially "locked" the notional; now settle PnL
            self.balance += pos.cost + pnl + (pos.cost * self.config.fee_rate)
            # The entry fee was already deducted from balance at open; pnl already subtracts both fees

        self.closed_positions.append(pos)
        self.trades.append({
            "time": time,
            "side": f"close_{pos.side}",
            "price": exit_price,
            "amount": pos.size,
            "fee": pos.fees_paid,
            "realized_pnl": round(pnl, 4),
            "exit_reason": reason,
            "position_id": pos.id,
            "equity": self._calculate_equity(exit_price),
        })

    def _close_all_open(self, price: float, time: int, reason: str = 'backtest_end') -> None:
        """Force-close all remaining open positions (end of backtest)."""
        for pos in list(self.open_positions):
            self._close_position(pos, price, time, reason)
        self.open_positions = []

    # ─── Internal: Signal Processing ────────────────────────────────

    def _process_signal(self, signal: Dict, candle: Dict) -> None:
        """
        Process a confluence signal: handle reverse closes and new entries.
        
        If reverse_on_signal is True:
            - Bullish signal closes all Short positions
            - Bearish signal closes all Long positions
        Then opens a new position in the signal direction.
        """
        direction = signal.get('direction')  # 'bullish' or 'bearish'
        entry_price = candle['close']
        time = candle['time']

        if direction == 'bullish':
            target_side = 'long'
            opposite_side = 'short'
        elif direction == 'bearish':
            if not self.config.allow_short:
                return  # Skip bearish signals in long-only mode
            target_side = 'short'
            opposite_side = 'long'
        else:
            return  # Unknown direction

        # --- Reverse close: close all opposite-side positions ---
        if self.config.reverse_on_signal:
            opposite_positions = [p for p in self.open_positions if p.side == opposite_side]
            for pos in opposite_positions:
                self._close_position(pos, entry_price, time, 'signal_reverse')
            self.open_positions = [p for p in self.open_positions if p.side != opposite_side]

        # --- Check if we can open a new position ---
        same_side_count = sum(1 for p in self.open_positions if p.side == target_side)
        if same_side_count >= self.config.max_positions:
            return  # Max positions reached for this side

        # --- Calculate position size (risk-based) ---
        current_equity = self._calculate_equity(entry_price)
        pos = self._open_position(target_side, entry_price, time, current_equity)
        if pos:
            self.open_positions.append(pos)

    def _open_position(
        self, side: str, entry_price: float, time: int, current_equity: float
    ) -> Optional[Position]:
        """
        Open a new position with risk-based sizing.
        
        Size = risk_amount / SL_distance
        Capped by available balance.
        """
        # Calculate TP/SL levels
        if side == 'long':
            take_profit = entry_price * (1 + self.config.take_profit_pct / 100)
            stop_loss = entry_price * (1 - self.config.stop_loss_pct / 100)
        else:
            take_profit = entry_price * (1 - self.config.take_profit_pct / 100)
            stop_loss = entry_price * (1 + self.config.stop_loss_pct / 100)

        # Risk-based position sizing
        risk_amount = current_equity * (self.config.risk_per_trade_pct / 100)
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance == 0:
            return None

        size = risk_amount / sl_distance  # base asset units
        cost = size * entry_price         # USDT notional

        # Cap at available balance (leave some margin)
        max_affordable = self.balance * 0.95 / entry_price  # 95% of balance
        if size > max_affordable:
            size = max_affordable
            cost = size * entry_price

        if size <= 0 or cost <= 0:
            return None

        # Deduct entry cost from balance
        entry_fee = cost * self.config.fee_rate
        self.total_fees_paid += entry_fee  # entry fee tracked separately
        self.balance -= (cost + entry_fee)

        pos = Position(
            side=side,
            entry_price=entry_price,
            entry_time=time,
            size=size,
            take_profit=take_profit,
            stop_loss=stop_loss,
            trailing_stop_pct=self.config.trailing_stop_pct,
            trailing_activation_pct=self.config.trailing_activation_pct,
        )

        # Record entry trade
        self.trades.append({
            "time": time,
            "side": f"open_{side}",
            "price": entry_price,
            "amount": pos.size,
            "fee": entry_fee,
            "realized_pnl": 0.0,
            "exit_reason": "",
            "position_id": pos.id,
            "equity": self._calculate_equity(entry_price),
        })

        return pos

    # ─── Internal: Equity & Metrics ─────────────────────────────────

    def _calculate_equity(self, current_price: float) -> float:
        """Total equity = cash balance + sum of all open position values."""
        position_value = 0.0
        for pos in self.open_positions:
            if pos.side == 'long':
                position_value += pos.size * current_price
            else:
                # Short: value = notional_at_entry + unrealized_pnl
                position_value += pos.cost + pos.unrealized_pnl(current_price)
        return self.balance + position_value

    def _calculate_metrics(self) -> Dict:
        """Compute performance metrics from closed positions."""
        if not self.closed_positions:
            return {
                "win_rate": 0.0,
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "avg_win_pct": 0.0,
                "avg_loss_pct": 0.0,
                "profit_factor": 0.0,
                "max_drawdown_pct": 0.0,
                "sharpe_ratio": 0.0,
            }

        wins = [p for p in self.closed_positions if p.realized_pnl > 0]
        losses = [p for p in self.closed_positions if p.realized_pnl <= 0]
        total = len(self.closed_positions)

        # Win rate
        win_rate = (len(wins) / total * 100) if total > 0 else 0.0

        # Average win/loss %
        def pnl_pct(pos: Position) -> float:
            return (pos.realized_pnl / pos.cost * 100) if pos.cost > 0 else 0.0

        avg_win_pct = np.mean([pnl_pct(p) for p in wins]) if wins else 0.0
        avg_loss_pct = np.mean([pnl_pct(p) for p in losses]) if losses else 0.0

        # Profit factor
        total_gross_profit = sum(p.realized_pnl for p in wins) if wins else 0.0
        total_gross_loss = abs(sum(p.realized_pnl for p in losses)) if losses else 0.0
        profit_factor = (total_gross_profit / total_gross_loss) if total_gross_loss > 0 else float('inf')

        # Max drawdown from equity curve
        max_drawdown_pct = self._calculate_max_drawdown()

        # Simplified Sharpe ratio (daily returns approximation)
        sharpe = self._calculate_sharpe()

        return {
            "win_rate": round(win_rate, 1),
            "total_trades": total,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "avg_win_pct": round(float(avg_win_pct), 2),
            "avg_loss_pct": round(float(avg_loss_pct), 2),
            "profit_factor": round(float(min(profit_factor, 999.9)), 2),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "sharpe_ratio": round(sharpe, 2),
        }

    def _calculate_max_drawdown(self) -> float:
        """Calculate maximum drawdown percentage from equity curve."""
        if not self.equity_curve:
            return 0.0

        values = [e['value'] for e in self.equity_curve]
        peak = values[0]
        max_dd = 0.0

        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak * 100 if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        return max_dd

    def _calculate_sharpe(self, risk_free_rate: float = 0.0) -> float:
        """
        Simplified Sharpe Ratio from equity curve.
        Uses hourly returns (since we typically run on 1h candles).
        Annualized assuming ~8760 hours/year.
        """
        if len(self.equity_curve) < 2:
            return 0.0

        values = np.array([e['value'] for e in self.equity_curve])
        returns = np.diff(values) / values[:-1]

        if len(returns) == 0 or np.std(returns) == 0:
            return 0.0

        mean_return = np.mean(returns) - risk_free_rate / 8760
        std_return = np.std(returns)
        sharpe = (mean_return / std_return) * np.sqrt(8760)  # Annualized

        return float(sharpe)

    # ─── Result Building ────────────────────────────────────────────

    def _build_result(self) -> Dict:
        """Assemble the final backtest result."""
        final_balance = self.equity_curve[-1]['value'] if self.equity_curve else self.config.investment
        metrics = self._calculate_metrics()

        return {
            "trades": self.trades,
            "equity": self.equity_curve,
            "final_balance": round(final_balance, 4),
            "total_fees_paid": round(self.total_fees_paid, 4),
            "metrics": metrics,
            "positions": [p.to_dict() for p in self.closed_positions],
        }

    def _empty_result(self) -> Dict:
        """Return empty result when no data is available."""
        return {
            "trades": [],
            "equity": [],
            "final_balance": self.config.investment,
            "total_fees_paid": 0.0,
            "metrics": self._calculate_metrics(),
            "positions": [],
        }
