"""
Comprehensive regression tests for Red-Team Audit Repairs (Phases 1, 2, 3):
  1. MTF 4h -> 1h strict candle-close alignment & causal BTC macro history (zero look-ahead)
  2. Trailing stop intra-bar physical/conservative check without close*0.999 / close*1.001 clamp
  3. Symmetric SETUP_WINDOW state machine (CAP↑ + same-bar CVD↓ not destroyed; peak preserved)
  4. One-way slippage_bps (open, signal_reverse, sl, trailing; not limit tp) & FundingRate PnL
  5. Coin-denominated OI for all symbols, missing CVD graceful degradation, no .bfill() in fetcher
  6. Signal scanner closed-candle confirmation, correlation risk warning, and notifier sizing parity
"""

import ast
import asyncio
import inspect
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.core.fetcher import DataFetcher
from api.core.indicators import IndicatorEngine
from api.core.notifier import format_signal_message
from api.core import signal_scanner
from api.db.database import Base
from api.db.models import MarketDataPoint, FundingRate
from api.quant.position import Position
from api.quant.signal_backtester import SignalBacktester
from api.quant.signal_strategy import SignalStrategyConfig, get_risk_profile


# ─── 1. MTF Strict Close Alignment & Causal BTC Macro History ───────────────────

def test_mtf_strict_close_alignment_no_future_leak():
    """
    1h bar at t=3600 (01:00..02:00, closes 02:00) MUST NOT observe 4h bar opened at t=0
    (00:00..04:00, closes 04:00). Only 1h bar at t=10800 (03:00..04:00, closes 04:00)
    may observe 4h bar t=0.
    """
    # Build 60 1h bars from t = -56*3600 up to t = 4*3600
    # So indicators (RSI, BB, EMA) are well-warmed before t=0.
    price_data = []
    for k in range(-56, 6):
        t = k * 3600
        close_p = 100.0
        # Trigger oversold dip at t=3600 (01:00, unclosed 4h bar t=0)
        # and another oversold dip at t=10800 (03:00, when 4h bar t=0 closes!)
        if k in (1, 3):  # t=3600 and t=10800
            price_data.append({"time": t, "open": 95.0, "high": 95.5, "low": 90.0, "close": 94.0, "volume": 1000.0})
        else:
            price_data.append({"time": t, "open": 100.0, "high": 100.5, "low": 99.5, "close": close_p, "volume": 1000.0})

    # Strong bullish env at t=3600 and t=10800 (LSUR Z <= -1.2 + CVD↑ + FR-)
    lsur_z = [{"time": p["time"], "value": -2.5 if p["time"] in (3600, 10800) else 0.0} for p in price_data]
    cvd = [{"time": p["time"], "value": float(idx * 100)} for idx, p in enumerate(price_data)]
    funding = [{"time": p["time"], "value": -0.01 if p["time"] in (3600, 10800) else 0.0} for p in price_data]
    rsi = [{"time": p["time"], "value": 20.0 if p["time"] in (3600, 10800) else 50.0} for p in price_data]
    bb = [{"time": p["time"], "value": 0.01 if p["time"] in (3600, 10800) else 0.5} for p in price_data]

    # 4h regime history:
    # t=-14400 (20:00..00:00, closed at 00:00) -> ranging
    # t=0      (00:00..04:00, closes at 04:00 = 14400) -> trending DOWN (blocks bull!)
    htf_regime = [
        {"time": -14400, "regime": "ranging", "direction": "neutral"},
        {"time": 0, "regime": "trending", "direction": "down"},
    ]

    # Enable causal close alignment (default)
    markers_causal, _ = IndicatorEngine.calculate_confluence_signals(
        price_data=price_data,
        lsur_z_aligned=lsur_z,
        cvd_aligned=cvd,
        oi_percentile=50.0,
        funding_aligned=funding,
        rsi_aligned=rsi,
        bb_pctb_aligned=bb,
        timeframe="1h",
        higher_tf_regime_history=htf_regime,
        enable_protection=False,
        mtf_close_aligned=True,
    )

    bull_times = {m["time"] for m in markers_causal if m["direction"] == "bullish"}
    # At t=3600, 4h t=0 has NOT closed yet, so prior 4h t=-14400 (ranging) allows bull!
    assert 3600 in bull_times
    # At t=10800 (03:00..04:00), 4h t=0 HAS closed -> trending down blocks bull!
    assert 10800 not in bull_times


def test_causal_btc_macro_history_no_future_leak():
    """Verify altcoin bars only see causal historical BTC macro state, not future BTC states."""
    price_data = [
        {"time": i * 3600, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1000.0}
        for i in range(40)
    ]
    # Bullish setup on bar 20 (t=20*3600) with score=3.0 (meets base threshold 3.0, fails if BTC raises to 4.0)
    t_sig = 20 * 3600
    price_data[20] = {"time": t_sig, "open": 95.0, "high": 95.5, "low": 90.0, "close": 95.0, "volume": 1000.0}
    lsur_z = [{"time": p["time"], "value": -2.5 if p["time"] == t_sig else 0.0} for p in price_data]
    cvd = [{"time": p["time"], "value": float(idx * 100)} for idx, p in enumerate(price_data)]
    rsi = [{"time": p["time"], "value": 20.0 if p["time"] == t_sig else 50.0} for p in price_data]
    bb = [{"time": p["time"], "value": 0.01 if p["time"] == t_sig else 0.5} for p in price_data]
    funding = [{"time": p["time"], "value": 0.0} for p in price_data]

    # BTC is ranging at t <= 20*3600, and ONLY turns trending down in the FUTURE at t=25*3600!
    btc_hist = [
        {"time": i * 3600, "regime": "trending" if i >= 25 else "ranging", "direction": "down" if i >= 25 else "neutral", "pulse": 50.0}
        for i in range(40)
    ]

    markers, _ = IndicatorEngine.calculate_confluence_signals(
        price_data=price_data,
        lsur_z_aligned=lsur_z,
        cvd_aligned=cvd,
        oi_percentile=50.0,
        funding_aligned=funding,
        rsi_aligned=rsi,
        bb_pctb_aligned=bb,
        timeframe="1h",
        symbol="SOL/USDT",
        btc_macro_history=btc_hist,
    )
    # Because BTC at t_sig was ranging (future trending-down at bar 25 must NOT leak back!), signal fires!
    assert any(m["time"] == t_sig and m["direction"] == "bullish" for m in markers)


# ─── 2. Same-Candle Trailing Activation & Exit Without Clamping ─────────────────

def test_same_candle_trailing_activation_and_exit_no_clamp():
    """
    Verify Position.update does not clamp trailing_stop_price down to close*0.999 (or up to close*1.001)
    and SignalBacktester triggers same-candle trailing exit at candidate_trail.
    """
    # Direct Position check: no close*0.999 clamp
    pos = Position(
        side="long",
        entry_price=100.0,
        entry_time=1000,
        size=10.0,
        take_profit=120.0,
        stop_loss=95.0,
        trailing_stop_pct=1.5,
        trailing_activation_pct=1.0,
    )
    pos.update(high=105.0, low=100.5, close=101.5)
    assert pos.trailing_active is True
    # Must be exact 105 * (1 - 0.015) = 103.425, NOT 101.5 * 0.999 = 101.3985!
    assert abs(pos.trailing_stop_price - 103.425) < 1e-6

    # Short symmetry check: no close*1.001 clamp
    pos_s = Position(
        side="short",
        entry_price=100.0,
        entry_time=1000,
        size=10.0,
        take_profit=80.0,
        stop_loss=105.0,
        trailing_stop_pct=1.5,
        trailing_activation_pct=1.0,
    )
    pos_s.update(high=99.5, low=95.0, close=98.5)
    assert pos_s.trailing_active is True
    # Must be exact 95 * (1 + 0.015) = 96.425, NOT 98.5 * 1.001 = 98.5985!
    assert abs(pos_s.trailing_stop_price - 96.425) < 1e-6

    # Backtester same-candle activation + pullback exit check
    candles = [
        {"time": 1000, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0},
        {"time": 2000, "open": 100.0, "high": 105.0, "low": 100.5, "close": 101.5},  # spikes & dumps below 103.425
        {"time": 3000, "open": 101.5, "high": 102.0, "low": 94.0, "close": 94.5},
    ]
    signals = [{"time": 1000, "direction": "bullish", "score": 4}]
    cfg = SignalStrategyConfig(
        investment=10000.0,
        take_profit_pct=20.0,
        stop_loss_pct=5.0,
        trailing_stop_pct=1.5,
        trailing_activation_pct=1.0,
        fee_rate=0.0,
        slippage_bps=0.0,
        include_funding=False,
        trailing_path_mode="ohlc",
    )
    res = SignalBacktester(cfg, candles, signals).run()
    close_trades = [t for t in res["trades"] if t["side"] == "close_long"]
    assert len(close_trades) == 1
    assert close_trades[0]["time"] == 2000
    assert close_trades[0]["exit_reason"] == "trailing"
    assert abs(close_trades[0]["price"] - 103.425) < 1e-6


def test_conservative_vs_ohlc_intraday_trailing_path():
    """
    In 'conservative' mode, if a candle activates trailing at 105 (trail=103.425) and also has
    low=99 <= 103.425 while closing at 103.6, conservative triggers same-bar trailing exit.
    """
    candles = [
        {"time": 1000, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0},
        {"time": 2000, "open": 100.0, "high": 105.0, "low": 99.0, "close": 103.6},
        {"time": 3000, "open": 103.6, "high": 104.0, "low": 101.0, "close": 102.0},
    ]
    signals = [{"time": 1000, "direction": "bullish", "score": 4}]
    cfg_cons = SignalStrategyConfig(
        take_profit_pct=20.0,
        stop_loss_pct=10.0,
        trailing_stop_pct=1.5,
        trailing_activation_pct=1.0,
        fee_rate=0.0,
        slippage_bps=0.0,
        trailing_path_mode="conservative",
    )
    res_cons = SignalBacktester(cfg_cons, candles, signals).run()
    close_cons = [t for t in res_cons["trades"] if t["side"] == "close_long"]
    assert close_cons[0]["time"] == 2000
    assert close_cons[0]["exit_reason"] == "trailing"


# ─── 3. SETUP_WINDOW Symmetry & Non-Destruction ─────────────────────────────────

def test_cap_bull_not_wiped_by_single_bar_cvd_bear():
    """
    When CAP↑ (bullish Structure, e.g. 1.5~3.5 pts) fires on the same bar as a single-bar
    CVD↓ (1.0 pt), bull_setup_timer MUST NOT be wiped to zero by bear_setup check.
    Also verifies peak score retention across SETUP_WINDOW.
    """
    # Build 60 ranging/baseline 4h bars (SETUP_WINDOW=3 in 4h), then a Capitulation bottom bar
    price_data = []
    oi_aligned = []
    cvd_aligned = []
    funding = []
    rsi = []
    bb = []

    for i in range(60):
        t = i * 14400
        price_data.append({"time": t, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1000.0})
        oi_aligned.append({"time": t, "value": 10000.0})
        cvd_aligned.append({"time": t, "value": 1000.0 - i * 10.0})  # steadily falling CVD leading into cap
        funding.append({"time": t, "value": 0.0})
        rsi.append({"time": t, "value": 50.0})
        bb.append({"time": t, "value": 0.5})

    # Bar 56..59: price drops from 100 to 94, OI drops -15% from 10000 -> 8500 (CAP↑ triggers at bar 59!)
    # AND on bar 59, CVD ticks slightly down from bar 58 (so t_bear_env_score = 1.0 CVD↓!),
    # while lower wick > 30% range gives bullish absorption PA, and Price triggers (RSI=25, BB=0.02 -> 2.0)!
    price_data[56] = {"time": 56 * 14400, "open": 100.0, "high": 100.0, "low": 98.0, "close": 98.5, "volume": 2000.0}
    price_data[57] = {"time": 57 * 14400, "open": 98.5, "high": 98.5, "low": 96.0, "close": 96.5, "volume": 2000.0}
    price_data[58] = {"time": 58 * 14400, "open": 96.5, "high": 96.5, "low": 94.5, "close": 95.0, "volume": 2000.0}
    # Bar 59: lower wick hammer (open=95, high=95.5, low=91.0, close=94.5 -> lower_wick=3.5 / 4.5 = 78% > 30%)
    price_data[59] = {"time": 59 * 14400, "open": 95.0, "high": 95.5, "low": 91.0, "close": 94.5, "volume": 3000.0}
    oi_aligned[59] = {"time": 59 * 14400, "value": 8500.0}  # -15% drop from 10000 -> triggers CAP↑ (1.5) + OI去槓 (1.0)!
    cvd_aligned[59] = {"time": 59 * 14400, "value": cvd_aligned[58]["value"] - 5.0}  # CVD↓ on same bar -> t_bear_env=1.0
    rsi[59] = {"time": 59 * 14400, "value": 24.0}
    bb[59] = {"time": 59 * 14400, "value": 0.02}

    markers, _ = IndicatorEngine.calculate_confluence_signals(
        price_data=price_data,
        lsur_z_aligned=[],
        cvd_aligned=cvd_aligned,
        oi_percentile=50.0,
        funding_aligned=funding,
        rsi_aligned=rsi,
        bb_pctb_aligned=bb,
        oi_aligned=oi_aligned,
        timeframe="4h",
        symbol="BTC/USDT",
        setup_symmetry=True,
    )
    bar59_bull = [m for m in markers if m["time"] == 59 * 14400 and m["direction"] == "bullish"]
    assert len(bar59_bull) == 1
    assert "CAP↑" in bar59_bull[0]["text"]

    # Contrast with legacy bug (setup_symmetry=False) where CVD↓ wiped CAP↑:
    markers_legacy, _ = IndicatorEngine.calculate_confluence_signals(
        price_data=price_data,
        lsur_z_aligned=[],
        cvd_aligned=cvd_aligned,
        oi_percentile=50.0,
        funding_aligned=funding,
        rsi_aligned=rsi,
        bb_pctb_aligned=bb,
        oi_aligned=oi_aligned,
        timeframe="4h",
        symbol="BTC/USDT",
        setup_symmetry=False,
    )
    assert [m for m in markers_legacy if m["time"] == 59 * 14400 and m["direction"] == "bullish"] == []


# ─── 4. Slippage & Funding Rate Accounting ──────────────────────────────────────

def test_slippage_bps_applied_adversely_on_market_and_stops_not_tp():
    """
    Verify slippage_bps=10 (0.10%) worsens entry, sl, trailing, signal_reverse,
    and does NOT alter limit tp price.
    """
    # Test 1: Long entry + SL exit with 10 bps slippage
    candles_sl = [
        {"time": 0, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0},
        {"time": 3600, "open": 100.0, "high": 100.5, "low": 97.5, "close": 98.0},  # hits SL at 98.0
    ]
    sigs = [{"time": 0, "direction": "bullish", "score": 5}]
    cfg = SignalStrategyConfig(
        investment=10000.0,
        take_profit_pct=5.0,
        stop_loss_pct=2.0,
        fee_rate=0.0,
        slippage_bps=10.0,  # 0.1%
        include_funding=False,
    )
    res_sl = SignalBacktester(cfg, candles_sl, sigs).run()
    open_t = res_sl["trades"][0]
    close_t = res_sl["trades"][1]
    assert abs(open_t["price"] - 100.1) < 1e-6      # 100 * (1 + 0.001)
    assert abs(close_t["price"] - (98.0 * 0.999)) < 1e-6  # 98 * (1 - 0.001)

    # Test 2: Limit TP has NO exit slippage, only entry slippage
    candles_tp = [
        {"time": 0, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0},
        {"time": 3600, "open": 100.0, "high": 106.0, "low": 99.5, "close": 105.5},  # hits TP at 105.0
    ]
    res_tp = SignalBacktester(cfg, candles_tp, sigs).run()
    assert abs(res_tp["trades"][0]["price"] - 100.1) < 1e-6
    assert abs(res_tp["trades"][1]["price"] - 105.0) < 1e-6

    # Test 3: Short signal_reverse applies adverse slippage on both close_short and open_long
    candles_rev = [
        {"time": 0, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0},
        {"time": 3600, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0},
        {"time": 7200, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0},
    ]
    sigs_rev = [
        {"time": 0, "direction": "bearish", "score": 5},
        {"time": 3600, "direction": "bullish", "score": 5},
    ]
    res_rev = SignalBacktester(cfg, candles_rev, sigs_rev).run()
    open_short = res_rev["trades"][0]
    close_short = res_rev["trades"][1]
    open_long = res_rev["trades"][2]
    assert abs(open_short["price"] - 99.9) < 1e-6
    assert abs(close_short["price"] - 100.1) < 1e-6
    assert close_short["exit_reason"] == "signal_reverse"
    assert abs(open_long["price"] - 100.1) < 1e-6


def test_funding_rate_pnl_long_and_short_bidirectional_conservation():
    """
    Verify historical FundingRate settlement PnL:
      - Positive funding_rate (+0.001 = 0.1%): Long pays (-), Short receives (+)
      - Negative funding_rate (-0.002 = -0.2%): Long receives (+), Short pays (-)
      - Account balance change strictly equals sum of position realized_pnl (cash conservation).
      - include_funding=False produces zero funding PnL.
    """
    # 4 hourly candles: t = 0, 3600, 7200, 10800
    # Signal opens on candle t=0 (entry close = t=3600).
    # Settlements at t=7200 (+0.001) and t=10800 (-0.002) are crossed while open!
    # Settlement at t=3600 (entry instant) MUST NOT be charged to a position opened at candle t=0 close.
    candles = [
        {"time": 0, "open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0},
        {"time": 3600, "open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0},
        {"time": 7200, "open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0},
        {"time": 10800, "open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0},
    ]
    funding = [
        {"time": 3600, "funding_rate": 0.01},    # Should NOT apply to position entering at t=0 close (3600)
        {"time": 7200, "funding_rate": 0.001},   # Crossed at end of candle 3600
        {"time": 10800, "funding_rate": -0.002}, # Crossed at end of candle 7200
    ]

    # Long position
    cfg_long = SignalStrategyConfig(
        investment=10000.0,
        risk_per_trade_pct=2.0,
        stop_loss_pct=10.0,
        take_profit_pct=20.0,
        fee_rate=0.0,
        slippage_bps=0.0,
        include_funding=True,
    )
    res_long = SignalBacktester(cfg_long, candles, [{"time": 0, "direction": "bullish"}], funding_rates=funding).run()
    pos_l = res_long["positions"][0]
    notional_l = pos_l["size"] * 100.0
    # Net rate = -0.001 + 0.002 = +0.001
    expected_fund_l = round(notional_l * 0.001, 4)
    assert abs(res_long["total_funding_pnl"] - expected_fund_l) < 1e-3
    assert abs(pos_l["funding_pnl"] - expected_fund_l) < 1e-3
    assert abs((res_long["final_balance"] - 10000.0) - pos_l["realized_pnl"]) < 1e-2

    # Short position with same funding series -> exact opposite funding PnL
    res_short = SignalBacktester(cfg_long, candles, [{"time": 0, "direction": "bearish"}], funding_rates=funding).run()
    pos_s = res_short["positions"][0]
    expected_fund_s = round(-notional_l * 0.001, 4)
    assert abs(res_short["total_funding_pnl"] - expected_fund_s) < 1e-3
    assert abs(pos_s["funding_pnl"] - expected_fund_s) < 1e-3
    assert abs((res_short["final_balance"] - 10000.0) - pos_s["realized_pnl"]) < 1e-2

    # include_funding=False disables funding settlement
    cfg_nofund = SignalStrategyConfig(
        investment=10000.0, risk_per_trade_pct=2.0, stop_loss_pct=10.0, take_profit_pct=20.0,
        fee_rate=0.0, slippage_bps=0.0, include_funding=False,
    )
    res_nofund = SignalBacktester(cfg_nofund, candles, [{"time": 0, "direction": "bullish"}], funding_rates=funding).run()
    assert res_nofund["total_funding_pnl"] == 0.0
    assert res_nofund["final_balance"] == 10000.0


# ─── 5. Coin-Denominated OI, Missing CVD Degradation, & No .bfill() ──────────────

def test_coin_oi_unification_prevents_nominal_usd_illusion():
    """
    For BTC/USDT, if price jumps +10% while USD OI rises +5%, coin-denominated OI actually
    fell (~-4.5%). Unified coin OI should NOT emit a false OI↑P↑ momentum score.
    """
    price_data = [{"time": i * 3600, "open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0} for i in range(40)]
    oi_aligned = [{"time": i * 3600, "value": 10000.0} for i in range(40)]
    # Bar 38 & 39: price jumps 100 -> 110 (+10%), USD OI rises 10000 -> 10500 (+5%)
    # Coin OI: 10000/100 = 100 -> 10500/110 = 95.45 (-4.55%)
    price_data[39] = {"time": 39 * 3600, "open": 100.0, "high": 111.0, "low": 100.0, "close": 110.0}
    oi_aligned[39] = {"time": 39 * 3600, "value": 10500.0}

    # Combine with RSI/BB/LSUR? Force overbought bearish or bullish check:
    # Make bar 39 have Z=-2.5 + RSI=25? Instead check direct marker text: no 'OI↑P↑'!
    lsur_z = [{"time": p["time"], "value": -2.5 if p["time"] == 39 * 3600 else 0.0} for p in price_data]
    bb = [{"time": p["time"], "value": 0.01 if p["time"] == 39 * 3600 else 0.5} for p in price_data]
    rsi = [{"time": p["time"], "value": 20.0 if p["time"] == 39 * 3600 else 50.0} for p in price_data]
    markers, _ = IndicatorEngine.calculate_confluence_signals(
        price_data=price_data,
        lsur_z_aligned=lsur_z,
        cvd_aligned=[],
        oi_percentile=50.0,
        funding_aligned=[],
        rsi_aligned=rsi,
        bb_pctb_aligned=bb,
        oi_aligned=oi_aligned,
        timeframe="1h",
        symbol="BTC/USDT",
        use_coin_oi_all=True,
    )
    assert not any("OI↑P↑" in m["text"] for m in markers)


def test_missing_cvd_graceful_degradation_breakout_and_cap():
    """When cvd_aligned is empty (e.g. CC/USDT lacking taker_volume), Breakout still fires via VOL↑ fallback."""
    price_data = []
    for i in range(45):
        p = 100.0 + i * 0.5
        price_data.append({"time": i * 3600, "open": p - 0.2, "high": p + 0.3, "low": p - 0.3, "close": p, "volume": 1000.0})
    for i in range(45, 50):
        price_data.append({"time": i * 3600, "open": 122.0, "high": 122.5, "low": 121.5, "close": 122.0, "volume": 1000.0})
    price_data.append({"time": 50 * 3600, "open": 122.0, "high": 126.5, "low": 121.8, "close": 126.0, "volume": 3500.0})

    donchian = IndicatorEngine.calculate_donchian_channel(price_data, period=20)
    macd = IndicatorEngine.calculate_macd(price_data)
    oi_aligned = [{"time": p["time"], "value": float(1000 + idx * 50)} for idx, p in enumerate(price_data)]

    markers, _ = IndicatorEngine.calculate_confluence_signals(
        price_data=price_data,
        lsur_z_aligned=[],
        cvd_aligned=[],  # missing!
        oi_percentile=50.0,
        funding_aligned=[],
        donchian_aligned=donchian,
        macd_aligned=macd,
        oi_aligned=oi_aligned,
        timeframe="1h",
        symbol="CC/USDT",
    )
    bo = [m for m in markers if m["strategy_type"] == "breakout"]
    assert len(bo) >= 1
    assert "VOL↑" in bo[-1]["text"]


def test_fetcher_no_bfill_on_early_single_exchange_oi():
    """Verify DataFetcher.fetch_open_interest does NOT backfill future OKX/Binance overlap ratio onto earlier bars."""
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)

        @contextmanager
        def fake_session_local():
            sess = TestSession()
            try:
                yield sess
            finally:
                sess.close()

        with TestSession() as db:
            # Bar 0, 1: Binance only = 100.0
            # Bar 2: Overlap starts -> Binance = 100.0, OKX = 100.0 (ratio = 2.0)
            for idx, val in enumerate([100.0, 100.0, 100.0]):
                db.add(MarketDataPoint(
                    exchange="binance", symbol="BTC/USDT", timeframe="1h",
                    timestamp=datetime.fromtimestamp(1700000000 + idx * 3600, tz=timezone.utc),
                    open_interest=val,
                ))
            db.add(MarketDataPoint(
                exchange="okx", symbol="BTC/USDT", timeframe="1h",
                timestamp=datetime.fromtimestamp(1700000000 + 2 * 3600, tz=timezone.utc),
                open_interest=100.0,
            ))
            db.commit()

        with patch("api.core.fetcher.SessionLocal", fake_session_local):
            fetcher = DataFetcher()
            fetcher.okx.fetch_open_interest_history = MagicMock(return_value=[])
            fetcher.binance.fetch_open_interest_history = MagicMock(return_value=[])
            res = fetcher.fetch_open_interest("BTC/USDT", limit=10, timeframe="1h")

        assert len(res) == 3
        # Bar 0 & Bar 1 must remain 100.0 (ratio=1.0), NOT scaled to 200.0 via future .bfill()!
        assert res[0]["value"] == 100.0
        assert res[1]["value"] == 100.0
        assert res[2]["value"] == 200.0
    finally:
        engine.dispose()


# ─── 6. Live-Backtest Parity: Notifier, Risk Profile & Signal Scanner ───────────

def test_risk_profile_lookup_and_notifier_sizing():
    p_hype = get_risk_profile("HYPE/USDT", "4h")
    assert p_hype["stop_loss_pct"] == 5.5
    assert p_hype["take_profit_pct"] == 5.20

    msg = format_signal_message(
        signal={"time": 1700000000, "direction": "bullish", "score": 4.0, "strategy_type": "reversion", "text": "⚡(3G) 4/10 [R] Z+CVD↑+RSI25"},
        symbol="BTC/USDT",
        price=90000.0,
        timeframe="1h",
        correlation_warning=True,
        is_intraday_prealert=True,
    )
    assert "[盤中未收線預警]" in msg
    assert "單段全倉追蹤" in msg
    assert "建議名目倉位" in msg
    assert "0.95x" in msg
    assert "跨幣種高度共線警示" in msg


def test_signal_scanner_closed_candle_and_correlation_warning():
    """
    Verify scan_and_notify:
      - Suppresses unclosed latest candle by default (anti-repainting)
      - Emits closed candle (price_data[-2])
      - Appends correlation warning when >= 3 symbols fire same direction
    """
    now_sec = 1790000025  # 25 seconds after a 1h bar opened
    closed_bar_t = 1790000000 - 3600
    unclosed_bar_t = 1790000000

    price_bars = [
        {"time": closed_bar_t - 3600, "open": 100, "high": 101, "low": 99, "close": 100},
        {"time": closed_bar_t, "open": 100, "high": 101, "low": 99, "close": 100},
        {"time": unclosed_bar_t, "open": 100, "high": 101, "low": 99, "close": 100.5},
    ]

    def fake_get_market_data(symbol, timeframe="1h", **kwargs):
        assert kwargs.get("include_orderbook") is False
        assert kwargs.get("include_breakdown") is False
        assert kwargs.get("allow_live_btc_cache") is False
        markers = [
            {"time": closed_bar_t, "direction": "bullish", "score": 4.0, "strategy_type": "reversion", "text": "⚡(3G) 4/10 [R] Z+CVD↑+RSI25"},
            {"time": unclosed_bar_t, "direction": "bearish", "score": 6.0, "strategy_type": "reversion", "text": "⚡(3G) 6/10 [R] CAP↓+Z+RSI75"},
        ]
        return {"data": {"price": price_bars}, "indicators": {"lsur_markers": markers}}

    sent_messages = []

    async def fake_send_chart(text, **kwargs):
        sent_messages.append(text)
        return True

    # Reset scanner state cleanly for test
    signal_scanner._notifications_enabled = True
    signal_scanner._monitored_symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    signal_scanner._allow_intraday_prealert = False
    signal_scanner._notified_signal_keys.clear()
    signal_scanner._recent_directional_signals.clear()

    with patch("api.core.signal_scanner.send_signal_with_chart", side_effect=fake_send_chart), \
         patch("api.core.signal_scanner.time.time", return_value=float(now_sec)), \
         patch("api.core.signal_scanner.asyncio.sleep", return_value=None):
        asyncio.run(signal_scanner.scan_and_notify(timeframes=["1h"], market_data_fn=fake_get_market_data))

    # Must send exactly 3 messages (1 closed-bar bullish per symbol), ZERO unclosed CAP↓ pre-alerts!
    assert len(sent_messages) == 3
    for msg in sent_messages:
        assert "BUY" in msg
        assert "SELL" not in msg
        assert "跨幣種高度共線警示" in msg


# ─── 7. Deep Red-Team Fixes: Boundary Conservation, Partial TP Ordering, DB Loader ─

def test_confluence_empty_input_returns_two_tuple():
    """calculate_confluence_signals on empty/short input must return (markers, regime) tuple."""
    markers, regime = IndicatorEngine.calculate_confluence_signals([], [], [], 50.0, [])
    assert markers == []
    assert isinstance(regime, dict)
    assert regime["regime"] == "ranging"

    # calculate_oi_percentile must tolerate None/NaN/inf values without TypeError
    oi_pct = IndicatorEngine.calculate_oi_percentile([
        {"time": i * 86400, "value": None if i == 0 else (float("nan") if i == 1 else (float("inf") if i == 2 else 100.0 + i))}
        for i in range(15)
    ])
    assert oi_pct == 100.0


def test_backtest_end_cash_and_equity_conservation_with_fees():
    """
    When a position stays open until backtest_end with non-zero fee_rate and slippage_bps,
    final_balance, equity_curve[-1]['value'], bt.balance, and investment + sum(realized_pnl) must match.
    """
    candles = [
        {"time": 0, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0},
        {"time": 3600, "open": 100.0, "high": 101.5, "low": 99.5, "close": 101.0},
        {"time": 7200, "open": 101.0, "high": 102.5, "low": 100.5, "close": 102.0},
    ]
    sigs = [{"time": 0, "direction": "bullish", "score": 5}]
    cfg = SignalStrategyConfig(
        investment=10000.0,
        take_profit_pct=20.0,
        stop_loss_pct=10.0,
        trailing_activation_pct=10.0,
        fee_rate=0.001,
        slippage_bps=5.0,
        include_funding=False,
    )
    bt = SignalBacktester(cfg, candles, sigs)
    res = bt.run()
    pos = bt.closed_positions[0]
    assert pos.exit_reason == "backtest_end"
    assert abs(res["final_balance"] - bt.balance) < 1e-4
    assert abs(res["equity"][-1]["value"] - res["final_balance"]) < 1e-4
    assert abs((res["final_balance"] - 10000.0) - pos.realized_pnl) < 1e-2


def test_partial_tp1_executes_before_tp2_on_same_candle():
    """
    If enable_partial_tp=True and a candle rallies continuously from open=100 across TP1=101
    through TP2=104 (without gap-opening past TP2), TP1 partial must fill 50% at 101 before TP2 fills at 104.
    """
    candles = [
        {"time": 0, "open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0},
        {"time": 3600, "open": 100.0, "high": 105.0, "low": 99.9, "close": 104.5},
    ]
    sigs = [{"time": 0, "direction": "bullish", "score": 5}]
    cfg = SignalStrategyConfig(
        investment=10000.0,
        take_profit_pct=4.0,
        stop_loss_pct=5.0,
        trailing_activation_pct=1.0,
        enable_partial_tp=True,
        partial_tp_ratio=0.5,
        fee_rate=0.0,
        slippage_bps=0.0,
        include_funding=False,
    )
    res = SignalBacktester(cfg, candles, sigs).run()
    reasons = [t["exit_reason"] for t in res["trades"]]
    assert reasons == ["", "tp1_partial", "tp"]
    assert abs(res["trades"][1]["price"] - 101.0) < 1e-6
    assert abs(res["trades"][2]["price"] - 104.0) < 1e-6
    assert abs(res["trades"][1]["amount"] - res["trades"][2]["amount"]) < 1e-6


def test_fetcher_naive_utc_timestamps_not_shifted_by_local_tz():
    """Naive UTC datetimes from SQLite must convert to exact UTC epoch regardless of TZ."""
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)

        @contextmanager
        def fake_session():
            s = TestSession()
            try:
                yield s
            finally:
                s.close()

        expected_ts = 1789999200  # exact 1h boundary
        with TestSession() as db:
            db.add(MarketDataPoint(
                exchange="okx",
                symbol="BTC/USDT",
                timeframe="1h",
                timestamp=datetime.fromtimestamp(expected_ts, tz=timezone.utc),
                open=100.0, high=101.0, low=99.0, close=100.5, volume=1000.0,
                open_interest=5000.0,
                long_short_ratio=1.25,
            ))
            db.commit()

        with patch("api.core.fetcher.SessionLocal", fake_session):
            fetcher = DataFetcher()
            fetcher.exchange.markets = {"BTC/USDT:USDT": {}}
            fetcher.exchange.fetch_ohlcv = MagicMock(return_value=[])
            fetcher.exchange.fetch_funding_rate_history = MagicMock(return_value=[])
            fetcher.okx.fetch_open_interest_history = MagicMock(return_value=[])
            fetcher.binance.fetch_open_interest_history = MagicMock(return_value=[])
            fetcher.okx.publicGetRubikStatContractsLongShortAccountRatio = MagicMock(return_value={"code": "0", "data": []})
            fetcher.binance.fapidataGetGloballongshortaccountratio = MagicMock(return_value=[])
            mkt = fetcher.fetch_market_data("BTC/USDT", "1h", limit=10)
            oi = fetcher.fetch_open_interest("BTC/USDT", limit=10, timeframe="1h")
            ls = fetcher.fetch_long_short_ratio("BTC/USDT", period="1h", limit=10)

        assert mkt["price"][0]["time"] == expected_ts
        assert oi[0]["time"] == expected_ts
        assert ls[0]["time"] == expected_ts
    finally:
        engine.dispose()


def test_audit_script_db_loader_excludes_1d_and_merges_4h_with_1h_derivatives():
    """
    Verify load_clean_dataset_from_db:
      - Ignores '1d' rows completely
      - Merges stale '4h' rows with fresh '1h' derivative rows (without discarding OKX 1h data)
      - Captures closing-boundary funding settlement at t1 + bar_interval
    """
    import scripts.run_audit_experiments as rae

    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)

        @contextmanager
        def fake_session():
            s = TestSession()
            try:
                yield s
            finally:
                s.close()

        t0 = 1790000000 - (1790000000 % 14400)
        with TestSession() as db:
            for i in range(120):
                ts_4h = datetime.fromtimestamp(t0 + i * 14400, tz=timezone.utc)
                db.add(MarketDataPoint(
                    exchange="okx", symbol="BTC/USDT", timeframe="4h", timestamp=ts_4h,
                    open=100.0, high=101.0, low=99.0, close=100.0, volume=1000.0,
                    open_interest=(1e8 if i < 30 else None),
                    long_short_ratio=(1.1 if i < 30 else None),
                ))
            for h in range(120, 480):
                ts_1h = datetime.fromtimestamp(t0 + h * 3600, tz=timezone.utc)
                db.add(MarketDataPoint(
                    exchange="okx", symbol="BTC/USDT", timeframe="1h", timestamp=ts_1h,
                    open=100.0, high=101.0, low=99.0, close=100.0, volume=500.0,
                    open_interest=2e8, long_short_ratio=1.2,
                ))
                db.add(MarketDataPoint(
                    exchange="binance", symbol="BTC/USDT", timeframe="1h", timestamp=ts_1h,
                    open_interest=2e8, long_short_ratio=1.4, taker_buy_vol=600.0, taker_sell_vol=500.0,
                    top_ls_position_ratio=1.7,
                ))
                if (t0 + h * 3600) % 28800 == 0:
                    db.add(FundingRate(
                        exchange="okx", symbol="BTC-USDT-SWAP", timestamp=ts_1h, funding_rate=0.0005,
                    ))
            # Boundary funding at exact closing time of last 4h bar (t0 + 480*3600)
            db.add(FundingRate(
                exchange="okx", symbol="BTC-USDT-SWAP",
                timestamp=datetime.fromtimestamp(t0 + 480 * 3600, tz=timezone.utc),
                funding_rate=0.0005,
            ))
            # Polluted 1d row that must NEVER leak into 4h clean dataset
            db.add(MarketDataPoint(
                exchange="okx", symbol="BTC/USDT", timeframe="1d",
                timestamp=datetime.fromtimestamp(t0 + 200 * 3600, tz=timezone.utc),
                open=100.0, high=101.0, low=99.0, close=100.0, open_interest=9e12,
            ))
            db.commit()

        with patch("api.db.database.SessionLocal", fake_session):
            ds_4h = rae.load_clean_dataset_from_db("BTC/USDT", "4h")

        assert ds_4h["valid"] is True
        assert ds_4h["taker_available"] is True
        # Because OKX 1h OI (2e8) + Binance 1h OI (2e8) were both merged into 4h buckets -> ~4e8, NOT 9e12 or Binance-only 2e8
        assert ds_4h["oi_aligned"][-1]["value"] == pytest.approx(4e8)
        # Boundary settlement at clean_end + 14400 must be preserved
        assert any(f["time"] == ds_4h["clean_end"] + 14400 for f in ds_4h["funding_settlements"])
    finally:
        engine.dispose()


# ─── 8. Phase 2 OOS Pruning: HYPE Hack Removal, Symbol Parity & lsur_source ───

def test_legacy_hype_rules_deleted_from_signature_and_defaults():
    """
    Verify formal Phase 2 OOS pruning: `use_legacy_hype_rules` and all `is_hype` special cases
    are completely removed from IndicatorEngine and scripts.run_audit_experiments,
    while optional ablation kwargs (`price_group_cap`, `single_trend_guard`) remain clean.
    """
    import scripts.run_audit_experiments as rae

    sig_ind = inspect.signature(IndicatorEngine.calculate_confluence_signals)
    assert "use_legacy_hype_rules" not in sig_ind.parameters
    assert sig_ind.parameters["price_group_cap"].default is None
    assert sig_ind.parameters["single_trend_guard"].default is False
    assert sig_ind.parameters["mtf_close_aligned"].default is True
    assert sig_ind.parameters["setup_symmetry"].default is True
    assert sig_ind.parameters["use_coin_oi_all"].default is True

    confluence_src = inspect.getsource(IndicatorEngine.calculate_confluence_signals)
    composite_src = inspect.getsource(IndicatorEngine.calculate_composite_score)
    for banned in ("use_legacy_hype_rules", "is_hype", "is_alpha_decoupled_bull", "hype_breakout_ok"):
        assert banned not in confluence_src
        assert banned not in composite_src

    sig_gen = inspect.signature(rae.generate_signals)
    assert "use_legacy_hype_rules" not in sig_gen.parameters
    assert rae._get_indicators_confluence_defaults()["is_hype_hacks_deleted"] is True


def test_hype_and_cc_symbol_parity_all_pruned_rules():
    """
    Given identical inputs, 'HYPE/USDT' and 'CC/USDT' (both sharing is_alt=True)
    must produce 100% identical markers and regimes across all 5 formerly special-cased rules:
      1) Unified is_alt RSI -10/+10 offset (not -6/+6)
      2) No EMA200 alpha decoupling exemption vs BTC macro downtrend
      3) Uniform ATR-normalized EMA50 pullback bounds across all coins (incl. BTC/ETH)
      4) No HYPE-only breakout body >= 0.45*ATR / half-close / coin_oi >= 0.5% gate
      5) No HYPE-only reversion score >= 3.5 / cvd_rising gate
    """
    import pandas as pd

    # --- Case 1 & 5: Ranging 1h RSI offset (-10 vs -6) + score=3.0 reversion with cvd_falling ---
    price_r = []
    cvd_r = []
    for i in range(55):
        t = i * 3600
        # Slight upward base 99.0 -> 100.0 so ema50 > ema200 (<1% diff -> ranging)
        base = 99.0 if i < 20 else 100.0
        price_r.append({"time": t, "open": base - 0.05, "high": base + 0.15, "low": base - 0.15, "close": base, "volume": 1000.0})
        # Alternating CVD keeps cvd_consistency < 0.7 (ranging)
        cvd_r.append({"time": t, "value": 1000.0 + (10.0 if i % 2 == 0 else -5.0)})

    # Bar 30: rsi=22.0 (would trigger under legacy -6 -> rsi_bull=24, MUST NOT trigger under unified -10 -> rsi_bull=20)
    price_r[30] = {"time": 30 * 3600, "open": 99.3, "high": 99.7, "low": 99.2, "close": 99.5, "volume": 1000.0}
    # Bar 42: rsi=19.0 (< 20 -> triggers RSI19), score=3.0 (< 3.5), close < ema50, cvd falling on bar 42
    price_r[42] = {"time": 42 * 3600, "open": 99.3, "high": 99.7, "low": 99.2, "close": 99.5, "volume": 1000.0}
    cvd_r[41] = {"time": 41 * 3600, "value": 1020.0}
    cvd_r[42] = {"time": 42 * 3600, "value": 1010.0}  # cvd_now < cvd_prev (cvd_rising=False)

    lsur_r = [{"time": p["time"], "value": -2.5 if idx in (30, 42) else 0.0} for idx, p in enumerate(price_r)]
    bb_r = [{"time": p["time"], "value": 0.01 if idx in (30, 42) else 0.5} for idx, p in enumerate(price_r)]
    rsi_r = [{"time": p["time"], "value": 22.0 if idx == 30 else (19.0 if idx == 42 else 50.0)} for idx, p in enumerate(price_r)]
    fund_r = [{"time": p["time"], "value": 0.0} for p in price_r]

    hype_m1, hype_reg1 = IndicatorEngine.calculate_confluence_signals(
        price_data=price_r, lsur_z_aligned=lsur_r, cvd_aligned=cvd_r, oi_percentile=50.0,
        funding_aligned=fund_r, rsi_aligned=rsi_r, bb_pctb_aligned=bb_r,
        timeframe="1h", symbol="HYPE/USDT", enable_protection=True,
    )
    cc_m1, cc_reg1 = IndicatorEngine.calculate_confluence_signals(
        price_data=price_r, lsur_z_aligned=lsur_r, cvd_aligned=cvd_r, oi_percentile=50.0,
        funding_aligned=fund_r, rsi_aligned=rsi_r, bb_pctb_aligned=bb_r,
        timeframe="1h", symbol="CC/USDT", enable_protection=True,
    )
    assert hype_m1 == cc_m1
    assert hype_reg1 == cc_reg1
    assert not any(m["time"] == 30 * 3600 for m in hype_m1)  # RSI 22 must NOT fire under -10 offset
    bar42 = [m for m in hype_m1 if m["time"] == 42 * 3600 and m["direction"] == "bullish"]
    assert len(bar42) == 1
    assert bar42[0]["score"] == 3.0  # Proves 3.5 gate & cvd_rising HYPE override are gone

    # --- Case 3: Uniform ATR-normalized EMA50 pullback bounds across ALL coins ---
    price_pb = []
    for i in range(60):
        p = 100.0 + i * 0.6
        # High-ATR bars (~4.0 range on ~135 close => atr_pct ~ 3.0% => low_min ~ -3.3%)
        price_pb.append({"time": i * 3600, "open": p - 0.3, "high": p + 2.0, "low": p - 2.0, "close": p, "volume": 1000.0})
    ema50_pb = float(pd.DataFrame(price_pb)["close"].ewm(span=50, adjust=False).mean().iloc[-1])
    t_pb = 60 * 3600
    # low_ema_dist = -2.0% (outside legacy static -1.2%, inside uniform ATR bound)
    price_pb.append({
        "time": t_pb,
        "open": ema50_pb + 0.4,
        "high": ema50_pb + 2.2,
        "low": ema50_pb * 0.98,
        "close": ema50_pb + 1.5,
        "volume": 1000.0,
    })
    rsi_pb = [{"time": p["time"], "value": 45.0 if p["time"] == t_pb else 55.0} for p in price_pb]
    bb_pb = [{"time": p["time"], "value": 0.20 if p["time"] == t_pb else 0.5} for p in price_pb]
    cvd_pb = [{"time": p["time"], "value": float(idx * 10)} for idx, p in enumerate(price_pb)]
    macd_pb = IndicatorEngine.calculate_macd(price_pb)

    pb_results = {}
    for sym in ("BTC/USDT", "ETH/USDT", "HYPE/USDT", "CC/USDT"):
        ms, reg = IndicatorEngine.calculate_confluence_signals(
            price_data=price_pb, lsur_z_aligned=[], cvd_aligned=cvd_pb, oi_percentile=50.0,
            funding_aligned=[], rsi_aligned=rsi_pb, bb_pctb_aligned=bb_pb, macd_aligned=macd_pb,
            timeframe="1h", symbol=sym,
        )
        pb_results[sym] = (ms, reg)
        assert any(m["time"] == t_pb and "EMA支撐↑" in m["text"] for m in ms), f"ATR pullback missed for {sym}"
    assert pb_results["HYPE/USDT"] == pb_results["CC/USDT"]

    # --- Case 4: Breakout without HYPE-only body >= 0.45*ATR / coin_oi >= 0.5% restriction ---
    price_bo = []
    for i in range(50):
        p = 100.0 + i * 0.5
        price_bo.append({"time": i * 3600, "open": p - 0.3, "high": p + 2.0, "low": p - 2.0, "close": p, "volume": 1000.0})
    for i in range(50, 55):
        price_bo.append({"time": i * 3600, "open": 124.5, "high": 126.0, "low": 123.0, "close": 124.5, "volume": 1000.0})
    # Bar 55: small green body (0.3 < 0.45 * ATR) crossing Donchian upper (126.5 > 126.0)
    t_bo = 55 * 3600
    price_bo.append({"time": t_bo, "open": 126.3, "high": 127.0, "low": 125.0, "close": 126.6, "volume": 3000.0})
    don_bo = IndicatorEngine.calculate_donchian_channel(price_bo, period=48)
    macd_bo = IndicatorEngine.calculate_macd(price_bo)
    cvd_bo = [{"time": p["time"], "value": float(idx * 20)} for idx, p in enumerate(price_bo)]
    # Make coin OI (oi / close) rise only +0.2% over oi_lookback=3 (< 0.5% legacy HYPE filter, > 0% unified filter)
    oi_bo = [{"time": p["time"], "value": float(1000.0 * p["close"] * (1.0 + idx * 0.00067))} for idx, p in enumerate(price_bo)]

    hype_bo, _ = IndicatorEngine.calculate_confluence_signals(
        price_data=price_bo, lsur_z_aligned=[], cvd_aligned=cvd_bo, oi_percentile=50.0,
        funding_aligned=[], donchian_aligned=don_bo, macd_aligned=macd_bo, oi_aligned=oi_bo,
        timeframe="1h", symbol="HYPE/USDT",
    )
    cc_bo, _ = IndicatorEngine.calculate_confluence_signals(
        price_data=price_bo, lsur_z_aligned=[], cvd_aligned=cvd_bo, oi_percentile=50.0,
        funding_aligned=[], donchian_aligned=don_bo, macd_aligned=macd_bo, oi_aligned=oi_bo,
        timeframe="1h", symbol="CC/USDT",
    )
    assert hype_bo == cc_bo
    assert any(m["time"] == t_bo and m["strategy_type"] == "breakout" for m in hype_bo)

    # --- Case 2: No EMA200 alpha decoupling exemption vs BTC macro downtrend ---
    btc_down_hist = [
        {"time": p["time"], "regime": "trending", "direction": "down", "pulse": 50.0}
        for p in price_pb
    ]
    # Strong coin OI expansion (+3% over 3 bars) + rsi=60 + close > ema50 > ema200 -> legacy is_alpha_decoupled_bull would be True.
    # Setup gives exact score=3.0 (FR-(OI↑)=1.0 + CVD↑=1.0 + EMA支撐↑=1.0): passes baseline (3.0), blocked under BTC downtrend (4.0).
    rsi_dec = [{"time": p["time"], "value": 60.0 if p["time"] == t_pb else 55.0} for p in price_pb]
    bb_neutral = [{"time": p["time"], "value": 0.5} for p in price_pb]
    fund_dec = [{"time": p["time"], "value": -0.02 if p["time"] == t_pb else 0.0} for p in price_pb]
    cvd_dec = [
        {"time": p["time"], "value": 1000.0 if idx < 50 else (1055.0 if p["time"] == t_pb else 1050.0)}
        for idx, p in enumerate(price_pb)
    ]
    oi_dec = [{"time": p["time"], "value": float(1000.0 * p["close"] * (1.01 ** idx))} for idx, p in enumerate(price_pb)]

    hype_base, _ = IndicatorEngine.calculate_confluence_signals(
        price_data=price_pb, lsur_z_aligned=[], cvd_aligned=cvd_dec, oi_percentile=50.0,
        funding_aligned=fund_dec, rsi_aligned=rsi_dec, bb_pctb_aligned=bb_neutral, macd_aligned=macd_pb,
        oi_aligned=oi_dec, timeframe="1h", symbol="HYPE/USDT", btc_macro_history=None,
    )
    assert any(m["time"] == t_pb and m["direction"] == "bullish" and m["score"] == 3.0 for m in hype_base)

    hype_dec, _ = IndicatorEngine.calculate_confluence_signals(
        price_data=price_pb, lsur_z_aligned=[], cvd_aligned=cvd_dec, oi_percentile=50.0,
        funding_aligned=fund_dec, rsi_aligned=rsi_dec, bb_pctb_aligned=bb_neutral, macd_aligned=macd_pb,
        oi_aligned=oi_dec, timeframe="1h", symbol="HYPE/USDT", btc_macro_history=btc_down_hist,
    )
    cc_dec, _ = IndicatorEngine.calculate_confluence_signals(
        price_data=price_pb, lsur_z_aligned=[], cvd_aligned=cvd_dec, oi_percentile=50.0,
        funding_aligned=fund_dec, rsi_aligned=rsi_dec, bb_pctb_aligned=bb_neutral, macd_aligned=macd_pb,
        oi_aligned=oi_dec, timeframe="1h", symbol="CC/USDT", btc_macro_history=btc_down_hist,
    )
    assert hype_dec == cc_dec
    # With BTC trending down raising bull_threshold to 4.0 and no decoupling exemption, score=3.0 is blocked for both
    assert not any(m["time"] == t_pb and m["direction"] == "bullish" for m in hype_dec)

    # Composite score parity between HYPE and CC
    cs_hype = IndicatorEngine.calculate_composite_score(
        price_data=price_r, lsur_z_aligned=lsur_r, cvd_aligned=cvd_r,
        funding_aligned=fund_r, rsi_aligned=rsi_r, bb_pctb_aligned=bb_r,
        timeframe="1h", symbol="HYPE/USDT",
    )
    cs_cc = IndicatorEngine.calculate_composite_score(
        price_data=price_r, lsur_z_aligned=lsur_r, cvd_aligned=cvd_r,
        funding_aligned=fund_r, rsi_aligned=rsi_r, bb_pctb_aligned=bb_r,
        timeframe="1h", symbol="CC/USDT",
    )
    assert cs_hype == cs_cc

    # Parity also holds under use_coin_oi_all=False (deleted is_hype fallback branch)
    hype_usd_oi, _ = IndicatorEngine.calculate_confluence_signals(
        price_data=price_bo, lsur_z_aligned=[], cvd_aligned=cvd_bo, oi_percentile=50.0,
        funding_aligned=[], donchian_aligned=don_bo, macd_aligned=macd_bo, oi_aligned=oi_bo,
        timeframe="1h", symbol="HYPE/USDT", use_coin_oi_all=False,
    )
    cc_usd_oi, _ = IndicatorEngine.calculate_confluence_signals(
        price_data=price_bo, lsur_z_aligned=[], cvd_aligned=cvd_bo, oi_percentile=50.0,
        funding_aligned=[], donchian_aligned=don_bo, macd_aligned=macd_bo, oi_aligned=oi_bo,
        timeframe="1h", symbol="CC/USDT", use_coin_oi_all=False,
    )
    assert hype_usd_oi == cc_usd_oi

    # --- Short-side parity checks for all 5 pruned rules ---
    # S1 & S5: Bearish ranging RSI +10 (rsi_bear=80, so 78 blocked, 81 fires) & score=3.0 with cvd_rising and close > ema50
    price_rb = []
    cvd_rb = []
    for i in range(55):
        t = i * 3600
        base = 101.0 if i < 20 else 100.0
        price_rb.append({"time": t, "open": base + 0.05, "high": base + 0.15, "low": base - 0.15, "close": base, "volume": 1000.0})
        cvd_rb.append({"time": t, "value": 1000.0 + (10.0 if i % 2 == 0 else -5.0)})
    # Bar 30: rsi=78.0 (would trigger under legacy +6 -> rsi_bear=76, blocked under unified +10 -> rsi_bear=80)
    price_rb[30] = {"time": 30 * 3600, "open": 100.7, "high": 100.8, "low": 100.3, "close": 100.5, "volume": 1000.0}
    # Bar 42: rsi=81.0 (> 80), score=3.0 (< 3.5), close=100.5 > ema50 (< ema200 so not is_bull_macro_trend), cvd rising on bar 42
    price_rb[42] = {"time": 42 * 3600, "open": 100.7, "high": 100.8, "low": 100.3, "close": 100.5, "volume": 1000.0}
    cvd_rb[41] = {"time": 41 * 3600, "value": 1000.0}
    cvd_rb[42] = {"time": 42 * 3600, "value": 1015.0}  # cvd_now > cvd_prev (cvd_falling=False)
    lsur_rb = [{"time": p["time"], "value": 2.5 if idx in (30, 42) else 0.0} for idx, p in enumerate(price_rb)]
    bb_rb = [{"time": p["time"], "value": 0.99 if idx in (30, 42) else 0.5} for idx, p in enumerate(price_rb)]
    rsi_rb = [{"time": p["time"], "value": 78.0 if idx == 30 else (81.0 if idx == 42 else 50.0)} for idx, p in enumerate(price_rb)]

    hype_sr, hype_sr_reg = IndicatorEngine.calculate_confluence_signals(
        price_data=price_rb, lsur_z_aligned=lsur_rb, cvd_aligned=cvd_rb, oi_percentile=50.0,
        funding_aligned=fund_r, rsi_aligned=rsi_rb, bb_pctb_aligned=bb_rb,
        timeframe="1h", symbol="HYPE/USDT", enable_protection=True,
    )
    cc_sr, cc_sr_reg = IndicatorEngine.calculate_confluence_signals(
        price_data=price_rb, lsur_z_aligned=lsur_rb, cvd_aligned=cvd_rb, oi_percentile=50.0,
        funding_aligned=fund_r, rsi_aligned=rsi_rb, bb_pctb_aligned=bb_rb,
        timeframe="1h", symbol="CC/USDT", enable_protection=True,
    )
    assert hype_sr == cc_sr
    assert hype_sr_reg == cc_sr_reg
    assert not any(m["time"] == 30 * 3600 for m in hype_sr)  # RSI 78 blocked under +10 offset
    bar42_s = [m for m in hype_sr if m["time"] == 42 * 3600 and m["direction"] == "bearish"]
    assert len(bar42_s) == 1
    assert bar42_s[0]["score"] == 3.0  # Proves 3.5 gate & cvd_falling HYPE override are gone

    # S3: Short-side uniform ATR-normalized EMA50 bounce (EMA壓力↓) across ALL coins
    price_pbs = []
    for i in range(60):
        p = 160.0 - i * 0.6
        price_pbs.append({"time": i * 3600, "open": p + 0.3, "high": p + 2.0, "low": p - 2.0, "close": p, "volume": 1000.0})
    ema50_pbs = float(pd.DataFrame(price_pbs)["close"].ewm(span=50, adjust=False).mean().iloc[-1])
    t_pbs = 60 * 3600
    # high_ema_dist = +2.0% (outside legacy static +1.2%, inside uniform ATR bound ~+3.3%)
    price_pbs.append({
        "time": t_pbs,
        "open": ema50_pbs - 0.4,
        "high": ema50_pbs * 1.02,
        "low": ema50_pbs - 2.2,
        "close": ema50_pbs - 1.5,
        "volume": 1000.0,
    })
    rsi_pbs = [{"time": p["time"], "value": 55.0 if p["time"] == t_pbs else 45.0} for p in price_pbs]
    bb_pbs = [{"time": p["time"], "value": 0.80 if p["time"] == t_pbs else 0.5} for p in price_pbs]
    cvd_pbs = [{"time": p["time"], "value": float(5000 - idx * 10)} for idx, p in enumerate(price_pbs)]
    macd_pbs = IndicatorEngine.calculate_macd(price_pbs)

    pbs_results = {}
    for sym in ("BTC/USDT", "ETH/USDT", "HYPE/USDT", "CC/USDT"):
        ms, reg = IndicatorEngine.calculate_confluence_signals(
            price_data=price_pbs, lsur_z_aligned=[], cvd_aligned=cvd_pbs, oi_percentile=50.0,
            funding_aligned=[], rsi_aligned=rsi_pbs, bb_pctb_aligned=bb_pbs, macd_aligned=macd_pbs,
            timeframe="1h", symbol=sym,
        )
        pbs_results[sym] = (ms, reg)
        assert any(m["time"] == t_pbs and "EMA壓力↓" in m["text"] for m in ms), f"Short ATR bounce missed for {sym}"
    assert pbs_results["HYPE/USDT"] == pbs_results["CC/USDT"]

    # S4: Bearish breakdown without HYPE-only body >= 0.45*ATR / coin_oi >= 0.5% restriction
    price_bd = []
    for i in range(50):
        p = 150.0 - i * 0.5
        price_bd.append({"time": i * 3600, "open": p + 0.3, "high": p + 2.0, "low": p - 2.0, "close": p, "volume": 1000.0})
    for i in range(50, 55):
        price_bd.append({"time": i * 3600, "open": 125.5, "high": 127.0, "low": 124.0, "close": 125.5, "volume": 1000.0})
    t_bd = 55 * 3600
    # Small red body (0.3 < 0.45 * ATR) crossing Donchian lower (< 123.5)
    price_bd.append({"time": t_bd, "open": 123.6, "high": 125.0, "low": 122.8, "close": 123.3, "volume": 3000.0})
    don_bd = IndicatorEngine.calculate_donchian_channel(price_bd, period=48)
    macd_bd = IndicatorEngine.calculate_macd(price_bd)
    cvd_bd = [{"time": p["time"], "value": float(5000 - idx * 20)} for idx, p in enumerate(price_bd)]
    oi_bd = [{"time": p["time"], "value": float(1000.0 * p["close"] * (1.0 + idx * 0.00067))} for idx, p in enumerate(price_bd)]

    hype_bd, _ = IndicatorEngine.calculate_confluence_signals(
        price_data=price_bd, lsur_z_aligned=[], cvd_aligned=cvd_bd, oi_percentile=50.0,
        funding_aligned=[], donchian_aligned=don_bd, macd_aligned=macd_bd, oi_aligned=oi_bd,
        timeframe="1h", symbol="HYPE/USDT",
    )
    cc_bd, _ = IndicatorEngine.calculate_confluence_signals(
        price_data=price_bd, lsur_z_aligned=[], cvd_aligned=cvd_bd, oi_percentile=50.0,
        funding_aligned=[], donchian_aligned=don_bd, macd_aligned=macd_bd, oi_aligned=oi_bd,
        timeframe="1h", symbol="CC/USDT",
    )
    assert hype_bd == cc_bd
    assert any(m["time"] == t_bd and m["strategy_type"] == "breakout" and m["direction"] == "bearish" for m in hype_bd)

    # S2: No is_alpha_decoupled_bull unconditional short-blocking when enable_protection=False
    price_s2 = list(price_pb[:-1])
    t_s2 = 60 * 3600
    price_s2.append({
        "time": t_s2,
        "open": 139.0,
        "high": 139.5,
        "low": 137.8,
        "close": 138.0,  # Bearish PA while well above EMA50 > EMA200
        "volume": 1000.0,
    })
    rsi_s2 = [{"time": p["time"], "value": 60.0 if p["time"] == t_s2 else 55.0} for p in price_s2]
    bb_hi = [{"time": p["time"], "value": 0.99 if p["time"] == t_s2 else 0.5} for p in price_s2]
    lsur_hi = [{"time": p["time"], "value": 2.5 if p["time"] == t_s2 else 0.0} for p in price_s2]
    cvd_hi = [
        {"time": p["time"], "value": 1000.0 if idx < 50 else (1040.0 if p["time"] == t_s2 else 1050.0)}
        for idx, p in enumerate(price_s2)
    ]
    oi_s2 = [{"time": p["time"], "value": float(1000.0 * p["close"] * (1.01 ** idx))} for idx, p in enumerate(price_s2)]
    hype_dec_off, _ = IndicatorEngine.calculate_confluence_signals(
        price_data=price_s2, lsur_z_aligned=lsur_hi, cvd_aligned=cvd_hi, oi_percentile=50.0,
        funding_aligned=[], rsi_aligned=rsi_s2, bb_pctb_aligned=bb_hi,
        oi_aligned=oi_s2, timeframe="1h", symbol="HYPE/USDT", enable_protection=False,
    )
    cc_dec_off, _ = IndicatorEngine.calculate_confluence_signals(
        price_data=price_s2, lsur_z_aligned=lsur_hi, cvd_aligned=cvd_hi, oi_percentile=50.0,
        funding_aligned=[], rsi_aligned=rsi_s2, bb_pctb_aligned=bb_hi,
        oi_aligned=oi_s2, timeframe="1h", symbol="CC/USDT", enable_protection=False,
    )
    assert hype_dec_off == cc_dec_off
    assert any(m["time"] == t_s2 and m["direction"] == "bearish" for m in hype_dec_off)


def test_api_main_lsur_source_default_ast():
    """
    Verify offline via AST that api/main.py keeps `lsur_source = 'lsur'` as default
    on SignalBacktestParams, get_market_data, and _get_market_data_impl,
    and passes lsur_source through run_signal_backtest -> get_market_data.
    """
    main_path = Path(__file__).resolve().parent.parent / "main.py"
    src = main_path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    cls_node = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SignalBacktestParams"
    )
    lsur_default = None
    for stmt in cls_node.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.target.id == "lsur_source":
            lsur_default = ast.literal_eval(stmt.value)
    assert lsur_default == "lsur"

    for fn_name in ("get_market_data", "_get_market_data_impl"):
        fn_node = next(
            n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == fn_name
        )
        arg_names = [a.arg for a in fn_node.args.args]
        defaults = fn_node.args.defaults
        offset = len(arg_names) - len(defaults)
        idx = arg_names.index("lsur_source")
        assert ast.literal_eval(defaults[idx - offset]) == "lsur"

    run_bt_node = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_signal_backtest"
    )
    get_mkt_calls = [
        n for n in ast.walk(run_bt_node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "get_market_data"
    ]
    assert len(get_mkt_calls) == 1
    assert any(
        kw.arg == "lsur_source"
        and isinstance(kw.value, ast.Attribute)
        and kw.value.attr == "lsur_source"
        for kw in get_mkt_calls[0].keywords
    )


def test_audit_report_phase2_verdict_and_causal_merge():
    """Verify audit script merge_lsur_causal and markdown report Phase 2 verdict rendering."""
    import scripts.run_audit_experiments as rae

    merged = rae.merge_lsur_causal(
        [{"time": 3600, "value": 1.2}, {"time": 7200, "value": 1.3}],
        [{"time": 0, "value": 1.1}, {"time": 3600, "value": 1.4}],
        period_seconds=3600,
    )
    assert [m["time"] for m in merged] == [0, 3600, 7200]
    assert merged[0]["value"] == pytest.approx(1.1)  # No .bfill() future scaling

    report = rae.render_markdown_report({
        "generated_at": "2026-11-26T00:00:00+00:00",
        "mode": "synthetic",
        "synthetic": True,
        "metadata": {
            "indicators_defaults": rae._get_indicators_confluence_defaults(),
            "exp3_signal_params": {"mtf_close_aligned": True, "use_btc_history": True, "setup_symmetry": True, "use_coin_oi_all": True},
        },
        "exp1": [],
        "exit_arch": [],
        "exp2": [
            {
                "symbol": "HYPE/USDT", "timeframe": "4h", "variant": "Variant B (Pruned Production)",
                "is_trades": 40, "is_wr": 65.0, "is_exp": -0.141, "is_mar": -0.73,
                "oos_trades": 16, "oos_wr": 68.8, "oos_pf": 1.09, "oos_exp": 0.166, "oos_dd": 6.30, "oos_mar": 0.61,
            },
        ],
        "exp3": [],
        "window_b_inventory": [],
        "exp3b": [],
        "exp3b_aggregate": [],
        "window_b_stage1c": [],
    })
    assert "is_hype_hacks_deleted=True" in report
    assert "use_legacy_hype_rules=True" not in report
    assert "Pre-Pruning Variant A Reference Baseline" in report
    assert "Phase 2 OOS Module Keep/Prune Verdict Table (模組去留判決表)" in report
    assert "DO NOT PROMOTE" in report


def test_signal_backtest_params_lsur_source_default_and_override():
    """
    Runtime FastAPI/Pydantic check (runs in Docker where fastapi is installed):
    verifies SignalBacktestParams().lsur_source == 'lsur' and optional 'top_ls' override.
    """
    pytest.importorskip("fastapi")
    from api.main import SignalBacktestParams, get_market_data, _get_market_data_impl

    default_params = SignalBacktestParams()
    assert default_params.lsur_source == "lsur"

    top_params = SignalBacktestParams(lsur_source="top_ls")
    assert top_params.lsur_source == "top_ls"

    assert inspect.signature(get_market_data).parameters["lsur_source"].default == "lsur"
    assert inspect.signature(_get_market_data_impl).parameters["lsur_source"].default == "lsur"


def test_get_market_data_empty_price_no_unbound_local_error():
    """
    Regression test for empty OKX price rows (e.g. GET /market/BTCUSDT?timeframe=4h&limit=120):
    _get_market_data_impl must initialize df_price and all payload variables cleanly,
    return JSON-compliant res['data']['price'] == [] instead of raising UnboundLocalError,
    and run_signal_backtest must return HTTP 404 (not 500) on empty history.
    """
    fastapi = pytest.importorskip("fastapi")
    import api.main as api_main

    mock_fetcher = MagicMock()
    mock_fetcher.fetch_market_data.return_value = {
        "price": [],
        "funding": [],
        "funding_settlements": [],
    }
    mock_fetcher.fetch_open_interest.return_value = []
    mock_fetcher.fetch_long_short_ratio.return_value = []
    mock_fetcher.fetch_top_trader_position_ratio.return_value = []
    mock_fetcher.fetch_taker_volume.return_value = []
    mock_fetcher.fetch_order_book_depth.return_value = []
    mock_fetcher.get_exchange_breakdown.return_value = []

    with patch.object(api_main, "get_fetcher", return_value=mock_fetcher):
        res_btc = api_main._get_market_data_impl("BTCUSDT", timeframe="4h", limit=120)
        res_alt = api_main._get_market_data_impl(
            "UNKNOWN-USDT",
            timeframe="1h",
            limit=120,
            enable_mtf_filter=True,
            lsur_source="top_ls",
        )

    for res, expected_sym in ((res_btc, "BTCUSDT"), (res_alt, "UNKNOWN/USDT")):
        json.dumps(res, allow_nan=False)
        assert res["symbol"] == expected_sym
        assert res["data"]["price"] == []
        assert res["data"]["funding"] == []
        assert res["data"]["funding_settlements"] == []
        ind = res["indicators"]
        assert ind["lsur_z_score"] == 0.0
        assert ind["lsur_ratio"] is None
        assert ind["lsur_history"] == []
        assert ind["lsur_z_history"] == []
        assert ind["top_ls_ratio"] is None
        assert ind["top_ls_z_score"] == 0.0
        assert ind["top_ls_history"] == []
        assert ind["top_ls_z_history"] == []
        assert ind["lsur_markers"] == []
        assert ind["cvd_history"] == []
        assert ind["open_interest"] == []
        assert ind["oi_percentile"] == 50.0
        assert ind["ema_fast"] == []
        assert ind["ema_slow"] == []
        assert ind["trend_state"] == "neutral"
        assert ind["rsi_history"] == []
        assert ind["market_regime"]["regime"] == "ranging"
        assert ind["market_regime_history"] == []
        assert ind["composite_score"] == 50.0
        assert ind["composite_score_history"] == []
        assert ind["exchange_breakdown"] == []
        assert ind["mtf_4h_regime"] is None
        assert ind["donchian_channel"] == []

    # run_signal_backtest must propagate HTTP 404 (not wrap into 500) when price is empty
    with patch.object(api_main, "get_fetcher", return_value=mock_fetcher):
        with pytest.raises(fastapi.HTTPException) as exc_info:
            api_main.run_signal_backtest(api_main.SignalBacktestParams(symbol="UNKNOWN-USDT", timeframe="4h"))
        assert exc_info.value.status_code == 404

    # Partial / malformed auxiliary series (None, NaN, inf) while price is empty must also stay JSON-safe
    mock_fetcher.fetch_market_data.return_value = {
        "price": [],
        "funding": [{"time": 1700000000, "value": float("nan")}],
        "funding_settlements": [],
    }
    mock_fetcher.fetch_open_interest.side_effect = lambda sym, timeframe="1h", limit=90: (
        [{"time": 1700000000 + i * 86400, "value": None if i == 0 else 1000.0 + i} for i in range(12)]
        if timeframe == "1D"
        else [{"time": 1700000000, "value": 1234.5}, {"time": 1700003600, "value": float("nan")}]
    )
    mock_fetcher.fetch_long_short_ratio.return_value = [
        {"time": 1700000000, "value": 1.25},
        {"time": 1700003600, "value": None},
        {"time": 1700007200, "value": float("inf")},
    ]
    mock_fetcher.fetch_top_trader_position_ratio.return_value = [
        {"time": 1700000000, "value": 1.5},
        {"time": 1700003600, "value": None},
        {"time": 1700007200, "value": float("nan")},
    ]
    with patch.object(api_main, "get_fetcher", return_value=mock_fetcher):
        res_partial = api_main._get_market_data_impl("BTC-USDT", timeframe="4h", limit=120)

    json.dumps(res_partial, allow_nan=False)
    assert res_partial["data"]["price"] == []
    assert res_partial["data"]["funding"] == [{"time": 1700000000, "value": None}]
    assert res_partial["indicators"]["open_interest"] == [
        {"time": 1700000000, "value": 1234.5},
        {"time": 1700003600, "value": None},
    ]
    assert res_partial["indicators"]["lsur_ratio"] == 1.25
    assert res_partial["indicators"]["top_ls_ratio"] == 1.5
