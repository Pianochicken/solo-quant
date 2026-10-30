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
        assert config.take_profit_pct == 1.5
        assert config.stop_loss_pct == 1.4
        assert config.trailing_stop_pct == 0.30
        assert config.trailing_activation_pct == 0.65
        assert config.max_positions == 1
        assert config.fee_rate == 0.0005

    def test_optimal_risk_profiles(self):
        from api.quant.signal_strategy import OPTIMAL_RISK_PROFILES
        for sym in ['BTC', 'ETH', 'SOL', 'CC', 'HYPE']:
            assert sym in OPTIMAL_RISK_PROFILES
            for tf in ['1h', '4h', '1d']:
                assert tf in OPTIMAL_RISK_PROFILES[sym]
                p = OPTIMAL_RISK_PROFILES[sym][tf]
                assert p['stop_loss_pct'] > 0
                assert p['take_profit_pct'] > 0
                assert p['trailing_activation_pct'] > 0
                assert p['trailing_stop_pct'] > 0

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

    def test_mfe_mae_metrics(self):
        """Verify MFE and MAE forward metrics are populated."""
        prices = [100] * 5 + [102, 105, 98, 103] + [100] * 5
        candles = _make_candles(prices)
        signals = _make_signals([(candles[2]['time'], 'bullish')])
        config = SignalStrategyConfig(investment=10000, take_profit_pct=20.0, stop_loss_pct=20.0)
        result = SignalBacktester(config, candles, signals).run()
        metrics = result['metrics']
        assert 'avg_mfe_pct' in metrics
        assert 'avg_mae_pct' in metrics
        assert metrics['avg_mfe_pct'] > 0

    def test_trailing_stop_cross_candle_no_lookahead(self):
        """
        Verify that trailing stop does not exit on the same candle that pushed
        the high up, but on subsequent candle when low breaches previous bar's trailing stop.
        """
        # Candle 0: entry at 100
        # Candle 1: high=105, low=99 (ratchets trailing stop to 105*(1-0.015)=103.425; low 99 doesn't trigger trailing because exit check ran before update)
        # Candle 2: high=103, low=101 (low 101 triggers trailing stop at 103.425)
        candles = [
            {'time': 1000, 'open': 100, 'high': 100.5, 'low': 99.5, 'close': 100},
            {'time': 2000, 'open': 100, 'high': 105.0, 'low': 99.0, 'close': 103.5},
            {'time': 3000, 'open': 103.5, 'high': 103.5, 'low': 101.0, 'close': 102.0},
        ]
        signals = [{'time': 1000, 'direction': 'bullish', 'score': 5}]
        config = SignalStrategyConfig(
            investment=10000,
            take_profit_pct=20.0,
            stop_loss_pct=10.0,
            trailing_stop_pct=1.5,
            trailing_activation_pct=1.0,
            max_positions=1,
            fee_rate=0.0
        )
        result = SignalBacktester(config, candles, signals).run()
        close_trades = [t for t in result['trades'] if t['side'] == 'close_long']
        assert len(close_trades) == 1
        assert close_trades[0]['time'] == 3000
        assert close_trades[0]['exit_reason'] == 'trailing'


class TestIndicatorEngineV8:
    def test_btc_macro_regime_filtering(self):
        from api.core.indicators import IndicatorEngine
        price_data = [
            {'time': i * 3600, 'open': 100, 'high': 101, 'low': 99, 'close': 100}
            for i in range(50)
        ]
        # Neutral baseline
        markers, regime = IndicatorEngine.calculate_confluence_signals(
            price_data=price_data,
            lsur_z_aligned=[],
            cvd_aligned=[],
            oi_percentile=50.0,
            funding_aligned=[],
            symbol='SOL/USDT',
            btc_macro_regime={'regime': 'trending', 'direction': 'down', 'pulse': 85.0}
        )
        assert isinstance(markers, list)
        assert isinstance(regime, dict)

    def test_trend_pullback_detection(self):
        from api.core.indicators import IndicatorEngine
        # Construct candles with EMA50 > EMA200 uptrend, then pullback to EMA50
        # 100 bars baseline rising from 100 to 120
        price_data = []
        for i in range(60):
            p = 100 + i * 0.5
            price_data.append({'time': i * 3600, 'open': p - 0.2, 'high': p + 0.3, 'low': p - 0.3, 'close': p})
        
        # Calculate EMA50 on bar 59
        import pandas as pd
        df = pd.DataFrame(price_data)
        ema50_val = df['close'].ewm(span=50, adjust=False).mean().iloc[-1]
        
        # Add pullback candle touching EMA50 then closing green with RSI ~ 45
        t_pb = 60 * 3600
        price_data.append({
            'time': t_pb,
            'open': ema50_val - 0.1,
            'high': ema50_val + 0.5,
            'low': ema50_val - 0.2,  # low is within -1.5% to +0.4%
            'close': ema50_val + 0.3 # green candle
        })
        rsi_aligned = [{'time': p['time'], 'value': 45.0} for p in price_data]
        cvd_aligned = [{'time': p['time'], 'value': float(idx * 10)} for idx, p in enumerate(price_data)]
        macd_aligned = [{'time': p['time'], 'hist': float(idx * 0.1)} for idx, p in enumerate(price_data)]
        
        markers, _ = IndicatorEngine.calculate_confluence_signals(
            price_data=price_data,
            lsur_z_aligned=[],
            cvd_aligned=cvd_aligned,
            oi_percentile=50.0,
            funding_aligned=[],
            rsi_aligned=rsi_aligned,
            macd_aligned=macd_aligned,
            timeframe='1h'
        )
        pb_markers = [m for m in markers if 'EMA支撐↑' in m.get('text', '')]
        assert len(pb_markers) >= 1
        assert pb_markers[-1]['direction'] == 'bullish'
        assert pb_markers[-1]['strategy_type'] == 'reversion'

    def test_breakout_engine_detection(self):
        from api.core.indicators import IndicatorEngine
        # 45 bars rising then 5 bars consolidating
        price_data = []
        for i in range(45):
            p = 100 + i * 0.5
            price_data.append({'time': i * 3600, 'open': p - 0.2, 'high': p + 0.3, 'low': p - 0.3, 'close': p})
        for i in range(45, 50):
            price_data.append({'time': i * 3600, 'open': 122.0, 'high': 122.5, 'low': 121.5, 'close': 122.0})

        # Bar 50: Strong breakout above Donchian upper with expanding OI & CVD
        t_bo = 50 * 3600
        price_data.append({
            'time': t_bo,
            'open': 122.0,
            'high': 126.0,
            'low': 121.8,
            'close': 125.5
        })
        donchian_aligned = IndicatorEngine.calculate_donchian_channel(price_data, period=20)
        macd_aligned = IndicatorEngine.calculate_macd(price_data)
        cvd_aligned = [{'time': p['time'], 'value': float(idx * 10)} for idx, p in enumerate(price_data)]
        oi_aligned = [{'time': p['time'], 'value': float(1000 + idx * 50)} for idx, p in enumerate(price_data)]

        markers, _ = IndicatorEngine.calculate_confluence_signals(
            price_data=price_data,
            lsur_z_aligned=[],
            cvd_aligned=cvd_aligned,
            oi_percentile=50.0,
            funding_aligned=[],
            donchian_aligned=donchian_aligned,
            macd_aligned=macd_aligned,
            oi_aligned=oi_aligned,
            timeframe='1h'
        )
        bo_markers = [m for m in markers if m.get('strategy_type') == 'breakout']
        assert len(bo_markers) >= 1
        assert bo_markers[-1]['direction'] == 'bullish'
        assert 'BREAKOUT' in bo_markers[-1]['text']


class TestBreakevenAndDynamicTP:
    """Tests for Breakeven Floor and Structure/Breakout TP scaling."""

    def test_breakeven_floor_long(self):
        # trail_pct=5.0 > trail_act=1.0. Without floor, 101.5 * 0.95 = 96.425 (< entry!)
        pos = Position(
            side='long',
            entry_price=100.0,
            entry_time=1000,
            size=1.0,
            take_profit=120.0,
            stop_loss=90.0,
            trailing_stop_pct=5.0,
            trailing_activation_pct=1.0,
        )
        pos.update(high=101.5, low=100.0, close=101.2)
        assert pos.trailing_active is True
        # Breakeven floor must be at least entry * 1.002 = 100.2
        assert pos.trailing_stop_price >= 100.2

    def test_breakeven_floor_short(self):
        pos = Position(
            side='short',
            entry_price=100.0,
            entry_time=1000,
            size=1.0,
            take_profit=80.0,
            stop_loss=110.0,
            trailing_stop_pct=5.0,
            trailing_activation_pct=1.0,
        )
        pos.update(high=100.0, low=98.5, close=98.8)
        assert pos.trailing_active is True
        # Breakeven floor must be at most entry * 0.998 = 99.8
        assert pos.trailing_stop_price <= 99.8

    def test_structure_and_breakout_tp_expansion(self):
        candles = [
            {'time': 1000, 'open': 100, 'high': 101, 'low': 99, 'close': 100},
            {'time': 2000, 'open': 100, 'high': 102, 'low': 99, 'close': 101},
        ]
        # Standard signal (no Structure/Breakout)
        sig_std = [{'time': 1000, 'direction': 'bullish', 'score': 4, 'text': '⚡ standard'}]
        config = SignalStrategyConfig(take_profit_pct=4.0, stop_loss_pct=2.0)
        bt_std = SignalBacktester(config, candles, sig_std)
        bt_std.run()
        assert len(bt_std.open_positions) + len(bt_std.closed_positions) > 0
        pos_std = (bt_std.open_positions + bt_std.closed_positions)[0]
        assert abs(pos_std.take_profit - 104.0) < 0.01

        # Structure signal (CAP/DIV)
        sig_struct = [{'time': 1000, 'direction': 'bullish', 'score': 5, 'text': '⚡(2G) 5/10 [R] CAP+DIV'}]
        bt_struct = SignalBacktester(config, candles, sig_struct)
        bt_struct.run()
        pos_struct = (bt_struct.open_positions + bt_struct.closed_positions)[0]
        # TP should be 4.0 * 1.35 = 5.4% -> 105.4
        assert abs(pos_struct.take_profit - 105.4) < 0.01

        # Breakout signal (🚀)
        sig_bo = [{'time': 1000, 'direction': 'bullish', 'score': 7, 'strategy_type': 'breakout', 'text': '🚀 [BREAKOUT]'}]
        bt_bo = SignalBacktester(config, candles, sig_bo)
        bt_bo.run()
        pos_bo = (bt_bo.open_positions + bt_bo.closed_positions)[0]
        assert abs(pos_bo.take_profit - 105.4) < 0.01

    def test_atr_precomputation(self):
        candles = [
            {'time': i * 1000, 'open': 100, 'high': 105, 'low': 95, 'close': 100}
            for i in range(30)
        ]
        bt = SignalBacktester(SignalStrategyConfig(), candles, [])
        assert len(bt.atr_map) == 30
        for t, val in bt.atr_map.items():
            assert val > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
