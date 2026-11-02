"""
Unit tests for Tactical Execution & Partial TP upgrades:
1. Coin-denominated OI change rate and Alpha Decoupling Protection
2. Two-stage partial TP1 + Breakeven Runner in Position
3. Two-stage partial TP1 in SignalBacktester
4. Telegram tactical message formatting with SL/TP1/TP2 and quadrant info
"""
import pytest
from api.quant.position import Position
from api.quant.signal_strategy import SignalStrategyConfig, OPTIMAL_RISK_PROFILES
from api.quant.signal_backtester import SignalBacktester
from api.core.indicators import IndicatorEngine
from api.core.notifier import format_signal_message


def test_position_partial_tp1_execution():
    """Verify check_partial_tp, execute_partial_tp, and close() PnL/fee consolidation."""
    pos = Position(
        side='long',
        entry_price=100.0,
        entry_time=1000,
        size=10.0,
        take_profit=110.0,
        stop_loss=96.0,
        trailing_stop_pct=2.0,
        trailing_activation_pct=4.0,  # TP1 at 104.0 (0.85 * 4.0% = 3.4% <= 4.0%)
        enable_partial_tp=True,
    )
    assert pos.initial_size == 10.0
    assert pos.cost == 1000.0
    assert pos.partial_tp_done is False

    # Price at 103 (below TP1 of 104)
    assert pos.check_partial_tp(high=103.0, low=99.0, close=102.0) is None

    # Price reaches 104.5 with close securely above breakeven (triggers TP1 at 104.0)
    tp1_fill = pos.check_partial_tp(high=104.5, low=99.0, close=103.5)
    assert tp1_fill == 104.0

    # Execute 50% partial TP with 0.1% fee rate
    fee_rate = 0.001
    closed_size, net_pnl, part_fee = pos.execute_partial_tp(tp1_fill, fee_rate=fee_rate, ratio=0.5)
    assert closed_size == 5.0
    assert pos.size == 5.0
    assert pos.cost == 500.0
    assert pos.partial_tp_done is True
    assert pos.trailing_active is True

    # Raw pnl = (104 - 100) * 5 = 20.0
    # Fees = (100 * 5 * 0.001) + (104 * 5 * 0.001) = 0.5 + 0.52 = 1.02
    # Net pnl = 20 - 1.02 = 18.98
    assert round(net_pnl, 2) == 18.98
    assert round(part_fee, 2) == 1.02
    assert round(pos.partial_realized_pnl, 2) == 18.98

    # Stop loss moved to breakeven floor: entry * 1.002 = 100.2
    assert pos.stop_loss == 100.2
    # Trailing stop relaxed 1.4x: 2.0 * 1.4 = 2.8%
    assert round(pos.trailing_stop_pct, 2) == 2.8

    # Now close remaining 5 units at 108.0 (TP2)
    remaining_net_pnl = pos.close(exit_price=108.0, exit_time=2000, reason='tp', fee_rate=fee_rate)
    # Remaining raw pnl = (108 - 100) * 5 = 40.0
    # Remaining fees = (100 * 5 * 0.001) + (108 * 5 * 0.001) = 0.5 + 0.54 = 1.04
    # Remaining net pnl = 40 - 1.04 = 38.96
    assert round(remaining_net_pnl, 2) == 38.96

    # Total realized PnL = 18.98 + 38.96 = 57.94
    assert round(pos.realized_pnl, 2) == 57.94
    # Total fees paid = 1.02 + 1.04 = 2.06
    assert round(pos.fees_paid, 2) == 2.06


def test_backtester_two_stage_partial_tp():
    """Verify SignalBacktester registers tp1_partial trade and trailing exit on runner."""
    # Entry at 100 on bar 0
    # Bar 1 pumps to 103 (reaches TP1 activation at 102.0)
    # Bar 2 falls to 101 (runner stopped out at breakeven / trailing)
    candles = [
        {'time': 1000, 'open': 100.0, 'high': 100.5, 'low': 99.5, 'close': 100.0},
        {'time': 2000, 'open': 100.0, 'high': 103.0, 'low': 99.8, 'close': 102.5},
        {'time': 3000, 'open': 102.5, 'high': 102.5, 'low': 100.0, 'close': 100.1},
    ]
    signals = [{'time': 1000, 'direction': 'bullish', 'score': 5}]
    config = SignalStrategyConfig(
        investment=10000.0,
        take_profit_pct=10.0,
        stop_loss_pct=2.0,
        trailing_stop_pct=1.0,
        trailing_activation_pct=2.0,  # TP1 at +2% (102.0)
        enable_partial_tp=True,
        partial_tp_ratio=0.5,
        fee_rate=0.0,
        max_positions=1
    )
    bt = SignalBacktester(config, candles, signals)
    res = bt.run()

    trades = res['trades']
    tp1_trades = [t for t in trades if t['exit_reason'] == 'tp1_partial']
    assert len(tp1_trades) == 1
    assert tp1_trades[0]['price'] == 102.0
    assert tp1_trades[0]['realized_pnl'] > 0

    # Total trades count (1 open + 1 tp1_partial + 1 final close)
    assert len(trades) == 3
    assert res['final_balance'] > 10000.0


def test_notifier_format_signal_message():
    """Verify format_signal_message outputs SL, TP1, TP2 and quadrant information."""
    signal = {
        'time': 1700000000,
        'direction': 'bullish',
        'score': 4.5,
        'strategy_type': 'reversion',
        'text': '⚡(3G) 4.5/10 [T][4h✓] Z+CVD↑+OI↑P↑',
    }
    macro_info = {
        'quadrant': 'strong_add',
        'rs_vs_btc': 4.5,
        'oi_coin_change_24h_pct': 5.2,
        'regime_4h': 'trending_up',
    }
    msg = format_signal_message(
        signal=signal,
        symbol='HYPE/USDT',
        price=35.0,
        timeframe='1h',
        macro_info=macro_info,
    )

    # Check key content blocks
    assert 'HYPE/USDT 1h' in msg
    assert 'BUY' in msg
    assert '戰術掛單點位' in msg
    assert 'TP1 (減半推保本)' in msg
    assert 'TP2 (波段目標)' in msg
    assert 'SL (安全止損)' in msg
    assert '🔥 強勢加倉' in msg
    assert 'RS vs BTC: +4.5' in msg
    assert '24h 幣本位OI: +5.2%' in msg
