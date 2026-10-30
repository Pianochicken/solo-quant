"""
Signal-driven strategy configuration.
Defines all tunable parameters and empirical risk profiles for the signal-based backtester.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, List


OPTIMAL_RISK_PROFILES: Dict[str, Dict[str, Dict[str, float]]] = {
    'BTC': {
        '1h': {'stop_loss_pct': 1.4, 'take_profit_pct': 1.5, 'trailing_activation_pct': 0.65, 'trailing_stop_pct': 0.30},
        '4h': {'stop_loss_pct': 2.2, 'take_profit_pct': 2.8, 'trailing_activation_pct': 1.20, 'trailing_stop_pct': 0.50},
        '1d': {'stop_loss_pct': 5.0, 'take_profit_pct': 6.5, 'trailing_activation_pct': 2.80, 'trailing_stop_pct': 1.10},
    },
    'ETH': {
        '1h': {'stop_loss_pct': 1.8, 'take_profit_pct': 2.1, 'trailing_activation_pct': 0.90, 'trailing_stop_pct': 0.40},
        '4h': {'stop_loss_pct': 2.8, 'take_profit_pct': 3.8, 'trailing_activation_pct': 1.60, 'trailing_stop_pct': 0.70},
        '1d': {'stop_loss_pct': 7.5, 'take_profit_pct': 10.5, 'trailing_activation_pct': 4.20, 'trailing_stop_pct': 1.60},
    },
    'SOL': {
        '1h': {'stop_loss_pct': 2.0, 'take_profit_pct': 2.6, 'trailing_activation_pct': 1.00, 'trailing_stop_pct': 0.45},
        '4h': {'stop_loss_pct': 3.5, 'take_profit_pct': 3.6, 'trailing_activation_pct': 1.60, 'trailing_stop_pct': 0.70},
        '1d': {'stop_loss_pct': 9.0, 'take_profit_pct': 12.0, 'trailing_activation_pct': 5.00, 'trailing_stop_pct': 2.00},
    },
    'CC': {
        '1h': {'stop_loss_pct': 3.0, 'take_profit_pct': 3.0, 'trailing_activation_pct': 1.30, 'trailing_stop_pct': 0.55},
        '4h': {'stop_loss_pct': 6.0, 'take_profit_pct': 6.8, 'trailing_activation_pct': 3.00, 'trailing_stop_pct': 1.20},
        '1d': {'stop_loss_pct': 9.5, 'take_profit_pct': 11.5, 'trailing_activation_pct': 5.00, 'trailing_stop_pct': 2.00},
    },
    'HYPE': {
        '1h': {'stop_loss_pct': 2.8, 'take_profit_pct': 2.6, 'trailing_activation_pct': 1.10, 'trailing_stop_pct': 0.50},
        '4h': {'stop_loss_pct': 4.2, 'take_profit_pct': 3.2, 'trailing_activation_pct': 1.60, 'trailing_stop_pct': 0.70},
        '1d': {'stop_loss_pct': 10.0, 'take_profit_pct': 13.0, 'trailing_activation_pct': 5.50, 'trailing_stop_pct': 2.20},
    },
}


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
        fee_rate: Fee rate per trade (e.g. 0.0005 = 0.05%)
        allow_short: Whether short positions are allowed
        reverse_on_signal: Close opposite positions when a reverse signal fires
        enable_protection: Enable regime protection / trend filter
        enable_mtf_filter: Enable multi-timeframe 4h regime filter
        use_dynamic_profiles: Adapt indicator thresholds to asset volatility
    """
    symbol: str = 'BTC/USDT'
    investment: float = 10000.0
    risk_per_trade_pct: float = 2.0
    take_profit_pct: float = 1.5
    stop_loss_pct: float = 1.4
    trailing_stop_pct: float = 0.30
    trailing_activation_pct: float = 0.65
    max_positions: int = 1
    fee_rate: float = 0.0005
    allow_short: bool = True
    reverse_on_signal: bool = True
    enable_protection: bool = True
    enable_mtf_filter: bool = True
    use_dynamic_profiles: bool = True
    min_score: float = 0.0
    allowed_types: Optional[List[str]] = None

    def validate(self) -> None:
        """Validate configuration values."""
        if self.min_score < 0:
            raise ValueError("min_score must be >= 0")
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
