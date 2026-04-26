"""
Unit tests for Position and SignalBacktester.
Tests TP/SL/Trailing Stop logic for both Long and Short positions,
plus integration test with mock data.
"""

import pytest
from api.quant.position import Position
from api.quant.signal_strategy import SignalStrategyConfig
from api.quant.signal_backtester import SignalBacktester


# ─── Position Tests ─────────────────────────────────────────────────

class TestPositionLong:
    """Test Long position exit conditions."""

    def _make_long(self, entry=100.0, tp_pct=4.0, sl_pct=2.0, trail_pct=1.5, trail_act=1.0):
        return Position(
            side='long',
            entry_price=entry,
            entry_time=1000,
            size=1.0,
            take_profit=entry * (1 + tp_pct / 100),
            stop_loss=entry * (1 - sl_pct / 100),
            trailing_stop_pct=trail_pct,
            trailing_activation_pct=trail_act,
        )

    def test_stop_loss_hit(self):
        pos = self._make_long(entry=100.0, sl_pct=2.0)
        # SL at 98.0
        pos.update(high=101, low=97.5, close=97.5)
        reason = pos.check_exit(high=101, low=97.5, close=97.5)
        assert reason == 'sl'

    def test_take_profit_hit(self):
        pos = self._make_long(entry=100.0, tp_pct=4.0)
        # TP at 104.0
        pos.update(high=105, low=100, close=104)
        reason = pos.check_exit(high=105, low=100, close=104)
        assert reason == 'tp'

    def test_trailing_stop_activates_and_exits(self):
        # Use wide TP (20%) so it doesn't interfere with trailing test
        pos = self._make_long(entry=100.0, tp_pct=20.0, trail_pct=1.5, trail_act=1.0)
        # Price rises to 102 (2% gain > 1% activation threshold)
        pos.update(high=102, low=100.5, close=101.5)
        assert pos.trailing_active is True
        assert pos.highest_since_entry == 102.0
        # Trailing stop = 102 * (1 - 0.015) = 100.47
        assert abs(pos.trailing_stop_price - 100.47) < 0.01

        # No exit yet - price still above trailing
        reason = pos.check_exit(high=102, low=100.5, close=101.5)
        assert reason is None

        # Price spikes to 105
        pos.update(high=105, low=101, close=104)
        # Trailing stop = 105 * (1 - 0.015) = 103.425
        assert abs(pos.trailing_stop_price - 103.425) < 0.01

        # Now price drops through trailing stop
        pos.update(high=104, low=103, close=103.2)
        reason = pos.check_exit(high=104, low=103, close=103.2)
        assert reason == 'trailing'

    def test_trailing_stop_ratchets_up_never_down(self):
        pos = self._make_long(entry=100.0, trail_pct=1.5, trail_act=1.0)
        pos.update(high=103, low=100, close=102)
        trail_after_103 = pos.trailing_stop_price

        # Price drops but doesn't hit trailing
        pos.update(high=102, low=101.6, close=101.8)
        assert pos.trailing_stop_price == trail_after_103  # Not lowered

    def test_sl_priority_over_tp(self):
        """When both SL and TP are hit in same candle, SL wins."""
        pos = self._make_long(entry=100.0, tp_pct=4.0, sl_pct=2.0)
        # Big candle: low=97, high=105 → both SL(98) and TP(104) hit
        pos.update(high=105, low=97, close=100)
        reason = pos.check_exit(high=105, low=97, close=100)
        assert reason == 'sl'

    def test_no_exit_when_price_neutral(self):
        # Use tight price range that doesn't activate trailing (need >1% gain)
        # and doesn't hit SL (98) or TP (104)
        pos = self._make_long(entry=100.0, trail_act=3.0)
        pos.update(high=100.5, low=99.5, close=100.2)
        reason = pos.check_exit(high=100.5, low=99.5, close=100.2)
        assert reason is None

    def test_close_pnl_long_win(self):
        pos = self._make_long(entry=100.0)
        pnl = pos.close(exit_price=104.0, exit_time=2000, reason='tp', fee_rate=0.001)
        # Raw PnL = (104 - 100) * 1.0 = 4.0
        # Entry fee = 100 * 1.0 * 0.001 = 0.1
        # Exit fee = 104 * 1.0 * 0.001 = 0.104
        # Net = 4.0 - 0.1 - 0.104 = 3.796
        assert abs(pnl - 3.796) < 0.001
        assert pos.is_closed is True

    def test_close_pnl_long_loss(self):
        pos = self._make_long(entry=100.0)
        pnl = pos.close(exit_price=98.0, exit_time=2000, reason='sl', fee_rate=0.001)
        # Raw PnL = (98 - 100) * 1.0 = -2.0
        # Fees = 100*0.001 + 98*0.001 = 0.198
        # Net = -2.0 - 0.198 = -2.198
        assert abs(pnl - (-2.198)) < 0.001


class TestPositionShort:
    """Test Short position exit conditions (mirrored logic)."""

    def _make_short(self, entry=100.0, tp_pct=4.0, sl_pct=2.0, trail_pct=1.5, trail_act=1.0):
        return Position(
            side='short',
            entry_price=entry,
            entry_time=1000,
            size=1.0,
            take_profit=entry * (1 - tp_pct / 100),
            stop_loss=entry * (1 + sl_pct / 100),
            trailing_stop_pct=trail_pct,
            trailing_activation_pct=trail_act,
        )

    def test_stop_loss_hit(self):
        pos = self._make_short(entry=100.0, sl_pct=2.0)
        # SL at 102.0
        pos.update(high=102.5, low=99, close=102.5)
        reason = pos.check_exit(high=102.5, low=99, close=102.5)
        assert reason == 'sl'

    def test_take_profit_hit(self):
        pos = self._make_short(entry=100.0, tp_pct=4.0)
        # TP at 96.0
        pos.update(high=99, low=95.5, close=96)
        reason = pos.check_exit(high=99, low=95.5, close=96)
        assert reason == 'tp'

    def test_trailing_stop_activates_and_exits(self):
        pos = self._make_short(entry=100.0, trail_pct=1.5, trail_act=1.0)
        # Price drops to 98 (2% drop > 1% activation threshold)
        pos.update(high=99.5, low=98, close=98.5)
        assert pos.trailing_active is True
        assert pos.lowest_since_entry == 98.0
        # Trailing stop = 98 * (1 + 0.015) = 99.47
        assert abs(pos.trailing_stop_price - 99.47) < 0.01

        # Price drops further to 95
        pos.update(high=98, low=95, close=96)
        # Trailing stop = 95 * 1.015 = 96.425
        assert abs(pos.trailing_stop_price - 96.425) < 0.01

        # Now price rises through trailing stop
        pos.update(high=97, low=96.5, close=96.8)
        reason = pos.check_exit(high=97, low=96.5, close=96.8)
        assert reason == 'trailing'

    def test_close_pnl_short_win(self):
        pos = self._make_short(entry=100.0)
        pnl = pos.close(exit_price=96.0, exit_time=2000, reason='tp', fee_rate=0.001)
        # Raw PnL = (100 - 96) * 1.0 = 4.0
        # Fees = 100*0.001 + 96*0.001 = 0.196
        # Net = 4.0 - 0.196 = 3.804
        assert abs(pnl - 3.804) < 0.001

    def test_close_pnl_short_loss(self):
        pos = self._make_short(entry=100.0)
        pnl = pos.close(exit_price=102.0, exit_time=2000, reason='sl', fee_rate=0.001)
        # Raw PnL = (100 - 102) * 1.0 = -2.0
        # Fees = 100*0.001 + 102*0.001 = 0.202
        # Net = -2.0 - 0.202 = -2.202
        assert abs(pnl - (-2.202)) < 0.001


# ─── SignalStrategyConfig Tests ─────────────────────────────────────

class TestSignalStrategyConfig:
    def test_defaults(self):
        config = SignalStrategyConfig()
        assert config.investment == 10000.0
        assert config.risk_per_trade_pct == 2.0

    def test_validation_errors(self):
        with pytest.raises(ValueError):
            config = SignalStrategyConfig(investment=-100)
            config.validate()
        with pytest.raises(ValueError):
            config = SignalStrategyConfig(risk_per_trade_pct=0)
            config.validate()
        with pytest.raises(ValueError):
            config = SignalStrategyConfig(stop_loss_pct=-1)
            config.validate()


# ─── SignalBacktester Integration Tests ─────────────────────────────

def _make_candles(prices, start_time=1000000, interval=3600000):
    """Generate mock OHLCV candles from a list of close prices."""
    candles = []
    for i, p in enumerate(prices):
        t = start_time + i * interval
        candles.append({
            'time': t,
            'open': p * 0.999,
            'high': p * 1.005,
            'low': p * 0.995,
            'close': p,
        })
    return candles


def _make_signals(times_and_dirs):
    """Generate mock signals: [(time, 'bullish'|'bearish'), ...]"""
    return [
        {'time': t, 'direction': d, 'score': 4, 'text': 'test'}
        for t, d in times_and_dirs
    ]


class TestSignalBacktester:

    def test_no_signals_no_trades(self):
        config = SignalStrategyConfig(investment=10000)
        candles = _make_candles([100] * 20)
        result = SignalBacktester(config, candles, []).run()
        assert result['metrics']['total_trades'] == 0
        assert result['final_balance'] == 10000.0

    def test_single_long_tp_hit(self):
        """Bullish signal → Long entry → price rises → TP hit."""
        prices = [100] * 5 + [101, 102, 103, 104, 105, 106] + [106] * 5
        candles = _make_candles(prices)
        signals = _make_signals([(candles[2]['time'], 'bullish')])

        config = SignalStrategyConfig(
            investment=10000,
            take_profit_pct=4.0,
            stop_loss_pct=2.0,
            trailing_stop_pct=1.5,
            trailing_activation_pct=1.0,
            max_positions=1,
            fee_rate=0.0,
        )
        result = SignalBacktester(config, candles, signals).run()

        # Should have 1 entry + 1 exit = 2 trade records
        assert result['metrics']['total_trades'] >= 1
        # Should be profitable (TP at ~104 hit)
        assert result['final_balance'] > 10000

    def test_single_short_tp_hit(self):
        """Bearish signal → Short entry → price drops → TP hit."""
        prices = [100] * 5 + [99, 98, 97, 96, 95, 94] + [94] * 5
        candles = _make_candles(prices)
        signals = _make_signals([(candles[2]['time'], 'bearish')])

        config = SignalStrategyConfig(
            investment=10000,
            take_profit_pct=4.0,
            stop_loss_pct=2.0,
            trailing_stop_pct=1.5,
            trailing_activation_pct=1.0,
            max_positions=1,
            fee_rate=0.0,
            allow_short=True,
        )
        result = SignalBacktester(config, candles, signals).run()
        assert result['metrics']['total_trades'] >= 1
        assert result['final_balance'] > 10000

    def test_stop_loss_hit(self):
        """Bullish signal → Long entry → price drops → SL hit."""
        prices = [100] * 5 + [99, 98, 97, 96] + [96] * 5
        candles = _make_candles(prices)
        signals = _make_signals([(candles[2]['time'], 'bullish')])

        config = SignalStrategyConfig(
            investment=10000,
            take_profit_pct=10.0,  # Far away
            stop_loss_pct=2.0,
            trailing_stop_pct=5.0,  # Far away
            trailing_activation_pct=3.0,
            max_positions=1,
            fee_rate=0.0,
        )
        result = SignalBacktester(config, candles, signals).run()
        assert result['final_balance'] < 10000  # Lost money

    def test_reverse_signal_closes_opposite(self):
        """Bullish → Long open → Bearish signal → Long closes + Short opens."""
        prices = [100] * 3 + [101, 102] + [101, 100] + [100] * 5
        candles = _make_candles(prices)
        signals = _make_signals([
            (candles[1]['time'], 'bullish'),
            (candles[5]['time'], 'bearish'),
        ])

        config = SignalStrategyConfig(
            investment=10000,
            take_profit_pct=10.0,
            stop_loss_pct=10.0,
            trailing_stop_pct=10.0,
            trailing_activation_pct=5.0,
            max_positions=1,
            fee_rate=0.0,
            allow_short=True,
            reverse_on_signal=True,
        )
        result = SignalBacktester(config, candles, signals).run()

        # Should have trades from both the Long close and Short open
        close_trades = [t for t in result['trades'] if t['side'] == 'close_long']
        assert len(close_trades) >= 1
        assert close_trades[0]['exit_reason'] == 'signal_reverse'

    def test_max_positions_respected(self):
        """Multiple signals at same time don't exceed max_positions."""
        candles = _make_candles([100] * 20)
        signals = _make_signals([
            (candles[1]['time'], 'bullish'),
            (candles[2]['time'], 'bullish'),
            (candles[3]['time'], 'bullish'),
            (candles[4]['time'], 'bullish'),  # Should be rejected (max=3)
        ])

        config = SignalStrategyConfig(
            investment=10000,
            take_profit_pct=50.0,
            stop_loss_pct=50.0,
            trailing_stop_pct=50.0,
            trailing_activation_pct=50.0,
            max_positions=3,
            fee_rate=0.0,
        )
        result = SignalBacktester(config, candles, signals).run()
        open_entries = [t for t in result['trades'] if t['side'] == 'open_long']
        assert len(open_entries) == 3

    def test_metrics_calculation(self):
        """Verify metrics are computed correctly."""
        config = SignalStrategyConfig(investment=10000)
        candles = _make_candles([100] * 10)
        result = SignalBacktester(config, candles, []).run()
        metrics = result['metrics']
        assert 'win_rate' in metrics
        assert 'max_drawdown_pct' in metrics
        assert 'profit_factor' in metrics
        assert 'sharpe_ratio' in metrics

    def test_equity_curve_length(self):
        """Equity curve should have one entry per candle."""
        candles = _make_candles([100] * 50)
        config = SignalStrategyConfig(investment=10000)
        result = SignalBacktester(config, candles, []).run()
        assert len(result['equity']) == 50

    def test_fees_deducted(self):
        """With non-zero fees, final balance should be lower."""
        prices = [100] * 5 + [101, 102, 103, 104, 105] + [105] * 5
        candles = _make_candles(prices)
        signals = _make_signals([(candles[2]['time'], 'bullish')])

        config_no_fee = SignalStrategyConfig(investment=10000, fee_rate=0.0, max_positions=1,
                                             take_profit_pct=4.0, stop_loss_pct=2.0)
        config_with_fee = SignalStrategyConfig(investment=10000, fee_rate=0.001, max_positions=1,
                                                take_profit_pct=4.0, stop_loss_pct=2.0)

        result_no_fee = SignalBacktester(config_no_fee, candles, signals).run()
        result_with_fee = SignalBacktester(config_with_fee, candles, signals).run()

        assert result_with_fee['final_balance'] < result_no_fee['final_balance']
        assert result_with_fee['total_fees_paid'] > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
