"""
Signal-driven strategy configuration.
Defines all tunable parameters for the signal-based backtester.
"""

from dataclasses import dataclass


@dataclass
class SignalStrategyConfig:
    """
    Configuration for a Signal-driven trading strategy.
    
    The strategy uses confluence signals from IndicatorEngine to enter positions,
    and manages exits via fixed TP/SL levels and a percentage-based trailing stop.
    
    Attributes:
        symbol: Trading pair (e.g. 'BTC/USDT')
        investment: Initial capital in quote currency (USDT)
        risk_per_trade_pct: % of current equity risked per trade
            (used with SL distance to calculate position size)
        take_profit_pct: Fixed take profit distance from entry (%)
        stop_loss_pct: Fixed stop loss distance from entry (%)
        trailing_stop_pct: Trailing stop retracement from peak/trough (%)
        trailing_activation_pct: Min unrealized profit % before trailing activates
        max_positions: Maximum concurrent open positions
        fee_rate: Fee rate per trade (e.g. 0.0008 = 0.08%)
        allow_short: Whether short positions are allowed
        reverse_on_signal: Close opposite positions when a reverse signal fires
    """
    symbol: str = 'BTC/USDT'
    investment: float = 10000.0
    risk_per_trade_pct: float = 2.0
    take_profit_pct: float = 4.0
    stop_loss_pct: float = 2.0
    trailing_stop_pct: float = 1.5
    trailing_activation_pct: float = 1.0
    max_positions: int = 3
    fee_rate: float = 0.0008
    allow_short: bool = True
    reverse_on_signal: bool = True

    def validate(self) -> None:
        """Validate configuration values."""
        if self.investment <= 0:
            raise ValueError("investment must be > 0")
        if self.risk_per_trade_pct <= 0 or self.risk_per_trade_pct > 100:
            raise ValueError("risk_per_trade_pct must be between 0 and 100")
        if self.take_profit_pct <= 0:
            raise ValueError("take_profit_pct must be > 0")
        if self.stop_loss_pct <= 0:
            raise ValueError("stop_loss_pct must be > 0")
        if self.trailing_stop_pct <= 0:
            raise ValueError("trailing_stop_pct must be > 0")
        if self.trailing_activation_pct < 0:
            raise ValueError("trailing_activation_pct must be >= 0")
        if self.max_positions < 1:
            raise ValueError("max_positions must be >= 1")
        if self.fee_rate < 0:
            raise ValueError("fee_rate must be >= 0")
