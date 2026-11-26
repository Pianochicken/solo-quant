"""
Unit & causality verification tests for Phase 1 Macro Inflection Prototype
(scripts/run_macro_inflection_experiments.py):
  1. OKX 16:00 UTC 1d candle never leaks 00:00 UTC next-day derivative rows (known_ts alignment)
  2. OKX 1d OHLCV deduplication (t_curr - t_prev < 43200 keeps newer bar)
  3. 1d -> 4h alignment never leaks an unclosed 1d zone (t_1d + 86400 <= t_4h + 14400)
  4. Dual FundingRate symbol formats (-USDT-SWAP + /USDT:USDT) union, deduplication & 2023-2025 degradation
  5. Strict truncation invariance (prefix 0..k == full 0..N at index k-1, zero look-ahead)
  6. Scale-invariant taker_ratio per-exchange computation & Binance->OKX fallback
  7. Major Wave Capture strictly-before-MAE ordering & WideATRBacktester cash/sizing/Chandelier accounting
  8. AST guard against .bfill() and inplace=True
  9. End-to-end --mode synthetic run without errors or pandas inplace warnings
"""

from __future__ import annotations

import ast
import json
import math
import warnings
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import scripts.run_macro_inflection_experiments as rme
from api.db.database import Base
from api.db.models import FundingRate, MarketDataPoint


def _utc_ts(year: int, month: int, day: int, hour: int = 0) -> int:
    return int(datetime(year, month, day, hour, 0, tzinfo=timezone.utc).timestamp())


def _utc_dt(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _make_1d_bars(start_ts: int, n: int, base_price: float = 100.0) -> List[Dict]:
    bars = []
    px = base_price
    for i in range(n):
        t = start_ts + i * 86400
        wave = 0.02 * math.sin(i / 6.0) + 0.002 * math.cos(i / 15.0)
        o = px
        c = max(10.0, px * (1.0 + wave))
        h = max(o, c) * 1.015
        l = min(o, c) * 0.985
        bars.append({"time": t, "open": o, "high": h, "low": l, "close": c, "volume": 1000.0 + i})
        px = c
    return bars


# ─── 1. OKX 16:00 UTC 1d Candle vs 00:00 UTC Next-Day Derivatives ───────────────

def test_okx_16utc_1d_candle_never_leaks_next_day_00utc_derivatives():
    """
    OKX 1d candle opened at Day D 16:00 UTC closes at Day D+1 16:00 UTC (known_ts = D+1 16:00).
    Binance 1d derivative opened at Day D+1 00:00 UTC closes at Day D+2 00:00 UTC (known_ts = D+2 00:00).
    Therefore OKX candle D 16:00 UTC MUST NEVER observe Binance derivative D+1 00:00 UTC!
    """
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)

        @contextmanager
        def session_factory():
            sess = TestSession()
            try:
                yield sess
            finally:
                sess.close()

        # 100 OKX 1d candles at 16:00 UTC starting 2025-07-01 16:00 UTC
        start_okx = _utc_ts(2025, 7, 1, 16)
        n_days = 100
        target_idx = 80
        t_okx_target = start_okx + target_idx * 86400        # Day D 16:00 UTC
        t_bin_same_day = t_okx_target - 57600                # Day D 00:00 UTC (known at D+1 00:00 <= D+1 16:00)
        t_bin_next_day = t_okx_target + 28800                # Day D+1 00:00 UTC (known at D+2 00:00 > D+1 16:00!)

        with TestSession() as db:
            for i in range(n_days):
                t_c = start_okx + i * 86400
                db.add(MarketDataPoint(
                    exchange="okx",
                    symbol="BTC/USDT",
                    timeframe="1d",
                    timestamp=_utc_dt(t_c),
                    open=100.0,
                    high=102.0,
                    low=98.0,
                    close=100.0,
                    volume=5000.0,
                ))
            # Put Binance 1d derivatives starting ONLY on Day D+1 00:00 UTC at first?
            # Test A: Put normal derivatives up to Day D 00:00 UTC, and an extreme spike on Day D+1 00:00 UTC.
            for i in range(target_idx + 1):
                t_b = (start_okx + i * 86400) - 57600  # 00:00 UTC
                db.add(MarketDataPoint(
                    exchange="binance",
                    symbol="BTC/USDT",
                    timeframe="1d",
                    timestamp=_utc_dt(t_b),
                    open_interest=10000.0,
                    long_short_ratio=1.0,
                    taker_buy_vol=500.0,
                    taker_sell_vol=500.0,  # taker_ratio = 0.50
                ))
            # Spike at Day D+1 00:00 UTC (should only appear on OKX Day D+1 16:00 UTC, NEVER on Day D 16:00 UTC!)
            db.add(MarketDataPoint(
                exchange="binance",
                symbol="BTC/USDT",
                timeframe="1d",
                timestamp=_utc_dt(t_bin_next_day),
                open_interest=999999.0,
                long_short_ratio=5.0,
                taker_buy_vol=900.0,
                taker_sell_vol=100.0,  # taker_ratio = 0.90
            ))
            # Also provide >= 240 4h bars so Dataset M can build too without blocking
            start_4h = start_okx
            for j in range(300):
                db.add(MarketDataPoint(
                    exchange="okx",
                    symbol="BTC/USDT",
                    timeframe="4h",
                    timestamp=_utc_dt(start_4h + j * 14400),
                    open=100.0,
                    high=101.0,
                    low=99.0,
                    close=100.0,
                    volume=1000.0,
                ))
            db.commit()

        ds_l_map, _ = rme.load_datasets_from_db(["BTC/USDT"], session_factory=session_factory)
        ds_l = ds_l_map["BTC/USDT"]
        assert ds_l["valid"] is True

        df_1d = ds_l["df_1d"]
        row_d = df_1d.loc[df_1d["time"] == t_okx_target].iloc[0]
        row_d1 = df_1d.loc[df_1d["time"] == (t_okx_target + 86400)].iloc[0]

        # At Day D 16:00 UTC (known_ts = D+1 16:00), Day D+1 00:00 UTC (known_ts = D+2 00:00) MUST NOT leak!
        assert row_d["taker_ratio"] == pytest.approx(0.50, abs=1e-9)
        assert row_d["oi_usd"] == pytest.approx(10000.0, abs=1e-6)
        assert math.isnan(row_d["lsur_z_90d"])  # Constant 1.0 lsur prior to spike -> std==0 -> NaN, NEVER polluted by 5.0!
        # At Day D+1 16:00 UTC (known_ts = D+2 16:00), Day D+1 00:00 UTC IS known!
        assert row_d1["taker_ratio"] == pytest.approx(0.90, abs=1e-9)
        assert row_d1["oi_usd"] == pytest.approx(999999.0, abs=1e-6)
        assert row_d1["lsur_z_90d"] > 5.0

        # Direct no-bfill check: if earlier bars have NO prior derivatives, align_series_by_known_ts returns NaN
        candle_known = [t_okx_target + 86400, t_okx_target + 2 * 86400]
        only_future_bin = [{"time": t_bin_next_day, "value": 42.0}]
        aligned = rme.align_series_by_known_ts(candle_known, only_future_bin, source_shift_sec=86400)
        assert math.isnan(aligned[0])
        assert aligned[1] == pytest.approx(42.0)
    finally:
        engine.dispose()


def test_okx_1d_ohlcv_deduplication_keeps_newer_overlapping_bar():
    t0 = _utc_ts(2025, 1, 1, 16)
    bars = [
        {"time": t0 + 86400, "open": 110, "high": 115, "low": 108, "close": 112, "volume": 200},
        {"time": t0, "open": 100, "high": 105, "low": 95, "close": 102, "volume": 100},
        # Overlapping bar +8h (< 43200s) -> must replace older t0 bar
        {"time": t0 + 28800, "open": 101, "high": 106, "low": 99, "close": 104, "volume": 150},
    ]
    dedup = rme.deduplicate_okx_1d_ohlcv(bars)
    assert [b["time"] for b in dedup] == [t0 + 28800, t0 + 86400]
    assert dedup[0]["close"] == 104.0


# ─── 2. 1d -> 4h Alignment Never Leaks Unclosed 1d Zone ───────────────────────

def test_1d_to_4h_alignment_never_leaks_unclosed_1d_zone():
    """
    1d bar t_1d (16:00..next day 16:00) closes at t_1d + 86400.
    4h bar at t_4h = t_1d + 57600 (08:00..12:00 UTC, closes 12:00 UTC) MUST NOT see t_1d's zone.
    4h bar at t_4h = t_1d + 72000 (12:00..16:00 UTC, closes 16:00 UTC) MAY see t_1d's zone.
    """
    t_base_1d = _utc_ts(2025, 8, 1, 16)
    t_1d_arm = t_base_1d + 5 * 86400  # closes at t_1d_arm + 86400

    l1_df = rme.pd.DataFrame([
        {
            "time": t_base_1d + d * 86400,
            "known_ts": t_base_1d + (d + 1) * 86400,
            "pd_bottom_zone": (d == 5),
            "pd_top_zone": False,
        }
        for d in range(10)
    ])

    # Build 80 4h bars: first 60 bars steady at 100.0 so EMA50 & Donchian20 are warmed up,
    # then a breakout candle BEFORE 1d close (t_4h = t_1d_arm + 57600 -> close 12:00 UTC)
    # and another breakout candle AT 1d close (t_4h = t_1d_arm + 72000 -> close 16:00 UTC).
    t_4h_unclosed = t_1d_arm + 57600   # t_4h + 14400 = t_1d_arm + 72000 < t_1d_arm + 86400!
    t_4h_closed = t_1d_arm + 72000     # t_4h + 14400 = t_1d_arm + 86400 == t_1d_arm + 86400!

    start_4h = t_4h_unclosed - 65 * 14400
    price_4h = []
    for m in range(70):
        t = start_4h + m * 14400
        if t < t_4h_unclosed:
            price_4h.append({"time": t, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1000.0})
        elif t == t_4h_unclosed:
            # Strong breakout (RSI>=52, > EMA50, > Donchian20_upper) while 1d bar is STILL UNCLOSED!
            price_4h.append({"time": t, "open": 100.0, "high": 104.5, "low": 100.0, "close": 104.0, "volume": 2000.0})
        elif t == t_4h_closed:
            # Breakout at exact 1d close timestamp (close > previous bar's high 104.5!)
            price_4h.append({"time": t, "open": 104.0, "high": 106.5, "low": 103.8, "close": 106.0, "volume": 2500.0})
        else:
            price_4h.append({"time": t, "open": 106.0, "high": 106.2, "low": 105.5, "close": 106.0, "volume": 1000.0})

    ds_m = {
        "eval_start": start_4h + 50 * 14400,
        "price_with_warmup": price_4h,
    }
    sigs = rme.compute_4h_macro_signals(ds_m, l1_df)
    sig_times = {s["time"] for s in sigs if s["direction"] == "bullish"}

    assert t_4h_unclosed not in sig_times
    assert t_4h_closed in sig_times


# ─── 3. Dual FundingRate Format Union, Dedup & Graceful Early Degradation ─────

def test_dual_funding_rate_union_deduplication_and_early_degradation():
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)

        @contextmanager
        def session_factory():
            sess = TestSession()
            try:
                yield sess
            finally:
                sess.close()

        start_1d = _utc_ts(2024, 1, 1, 16)
        n_1d = 220  # days 0..219; FundingRate only on days 150..219!
        t_overlap = start_1d + 170 * 86400

        with TestSession() as db:
            for d in range(n_1d):
                t = start_1d + d * 86400
                wave = 0.015 * math.sin(d / 8.0)
                db.add(MarketDataPoint(
                    exchange="okx",
                    symbol="ETH/USDT",
                    timeframe="1d",
                    timestamp=_utc_dt(t),
                    open=2000.0,
                    high=2050.0,
                    low=1950.0,
                    close=2000.0 * (1.0 + wave),
                    volume=10000.0,
                    open_interest=5e7 * (1.0 + 0.1 * math.cos(d / 10.0)),
                    long_short_ratio=1.2 + 0.3 * math.sin(d / 9.0),
                    taker_buy_vol=1000.0,
                    taker_sell_vol=900.0,
                ))
                if d >= 150:
                    for off in (0, 28800, 57600):
                        ft = t + off
                        if d < 170:
                            db.add(FundingRate(exchange="okx", symbol="ETH/USDT:USDT", timestamp=_utc_dt(ft), funding_rate=-0.0002))
                        elif d == 170 and off == 0:
                            # Exact collision between both formats -> '-USDT-SWAP' wins cleanly
                            db.add(FundingRate(exchange="okx", symbol="ETH/USDT:USDT", timestamp=_utc_dt(ft), funding_rate=-0.0011))
                            db.add(FundingRate(exchange="okx", symbol="ETH-USDT-SWAP", timestamp=_utc_dt(ft), funding_rate=0.0004))
                        else:
                            db.add(FundingRate(exchange="okx", symbol="ETH-USDT-SWAP", timestamp=_utc_dt(ft), funding_rate=0.0003))

            start_4h = start_1d + 100 * 86400
            for j in range(300):
                db.add(MarketDataPoint(
                    exchange="okx",
                    symbol="ETH/USDT",
                    timeframe="4h",
                    timestamp=_utc_dt(start_4h + j * 14400),
                    open=2000.0,
                    high=2020.0,
                    low=1980.0,
                    close=2000.0,
                    volume=2000.0,
                ))
            db.commit()

        ds_l_map, ds_m_map = rme.load_datasets_from_db(["ETH/USDT"], session_factory=session_factory)
        ds_l = ds_l_map["ETH/USDT"]
        ds_m = ds_m_map["ETH/USDT"]
        assert ds_l["valid"] is True
        assert ds_m["valid"] is True

        # Early 2024 bars closing strictly before first FundingRate settlement are NaN (zero .bfill()),
        # while bar 149 (known_ts == start_1d + 150*86400) sees only that boundary settlement.
        first_funding_ts = start_1d + 150 * 86400
        df_1d = ds_l["df_1d"]
        early_fr = df_1d.loc[df_1d["known_ts"] < first_funding_ts, "funding_daily"]
        late_fr = df_1d.loc[df_1d["known_ts"] >= first_funding_ts, "funding_daily"]
        assert len(early_fr) == 149
        assert early_fr.isna().all()
        assert late_fr.notna().all()

        # Deduplicated funding settlements prefer '-USDT-SWAP' on collision
        f_map = {f["time"]: f["funding_rate"] for f in ds_l["funding_settlements"]}
        assert f_map[t_overlap] == pytest.approx(0.0004)
        assert f_map[start_1d + 155 * 86400] == pytest.approx(-0.0002)

        # Layer 1 degrades gracefully on early bars lacking FundingRate (evaluates Coin-OI / Taker / LSUR)
        l1 = rme.evaluate_layer1_1d(df_1d)
        assert len(l1) == len(df_1d)
        assert l1["deriv_bottom_ok"].iloc[65:145].any()  # Taker=1000/1900 >= 0.51 activates on early bars without FR!
    finally:
        engine.dispose()


# ─── 4. Strict Truncation Invariance (Zero Look-Ahead) ────────────────────────

def test_strict_truncation_invariance_1d_and_4h():
    """
    Prefix 0..k MUST yield identical Layer 1 features/zones at k-1 and identical signals in [0..k-1]
    as the full 0..N series for Macro_LeftOnly_1d, Macro_P_1d, Macro_PD_1d, Macro_PD_1d_4h, and Legacy_v8.
    """
    ds_l_full_map, ds_m_full_map = rme.make_synthetic_datasets(["BTC/USDT", "ETH/USDT"], seed=99)
    ds_l_full = ds_l_full_map["ETH/USDT"]
    ds_m_full = ds_m_full_map["ETH/USDT"]
    btc_l_full = ds_l_full_map["BTC/USDT"]

    df_1d_full = ds_l_full["df_1d"]
    l1_full = rme.evaluate_layer1_1d(df_1d_full)

    # Check truncation invariance across multiple prefix lengths
    cut_1d = len(df_1d_full) - 80
    assert cut_1d > 150
    df_1d_pref = df_1d_full.iloc[:cut_1d].copy()
    l1_pref = rme.evaluate_layer1_1d(df_1d_pref)

    for col in ("ema20", "ema50", "atr14", "rsi14", "bb_pctb", "z_ema50", "dd_60d_atr", "rally_60d_atr"):
        np.testing.assert_allclose(
            l1_pref[col].to_numpy(dtype=float),
            l1_full[col].iloc[:cut_1d].to_numpy(dtype=float),
            rtol=1e-12,
            atol=1e-12,
            equal_nan=True,
        )
    for bcol in ("price_bottom_zone", "price_top_zone", "deriv_bottom_ok", "deriv_top_ok", "pd_bottom_zone", "pd_top_zone"):
        assert list(l1_pref[bcol]) == list(l1_full[bcol].iloc[:cut_1d])

    # Signal prefix invariance for 1d macro variants
    t_cut_1d = int(df_1d_pref["time"].iloc[-1])
    ds_l_pref = dict(ds_l_full)
    ds_l_pref["df_1d"] = df_1d_pref
    for var in ("Macro_LeftOnly_1d", "Macro_P_1d", "Macro_PD_1d"):
        sigs_full, _ = rme.compute_1d_macro_signals(ds_l_full, var)
        sigs_pref, _ = rme.compute_1d_macro_signals(ds_l_pref, var)
        expected_pref = [s for s in sigs_full if s["time"] <= t_cut_1d]
        assert sigs_pref == expected_pref

    # Legacy_v8_1d truncation invariance
    t_cut_btc = t_cut_1d
    btc_l_pref = dict(btc_l_full)
    btc_l_pref["price_with_warmup"] = [p for p in btc_l_full["price_with_warmup"] if p["time"] <= t_cut_btc]
    btc_l_pref["cvd_aligned"] = [x for x in btc_l_full["cvd_aligned"] if x["time"] <= t_cut_btc]
    btc_l_pref["regime_history"] = [x for x in btc_l_full["regime_history"] if x["time"] <= t_cut_btc]
    btc_l_pref["pulse_history"] = [x for x in btc_l_full["pulse_history"] if x["time"] <= t_cut_btc]

    ds_leg_pref = dict(ds_l_full)
    ds_leg_pref["price_with_warmup"] = [p for p in ds_l_full["price_with_warmup"] if p["time"] <= t_cut_1d]
    for key in ("lsur_z_aligned", "cvd_aligned", "funding_aligned", "oi_aligned", "rsi_hist", "ema_fast", "ema_slow", "bb_pctb", "donchian", "macd_hist"):
        ds_leg_pref[key] = [x for x in ds_l_full[key] if x["time"] <= t_cut_1d]

    leg_full = rme.run_legacy_v8_signals(ds_l_full, btc_l_full)
    leg_pref = rme.run_legacy_v8_signals(ds_leg_pref, btc_l_pref)
    assert leg_pref == [s for s in leg_full if s["time"] <= t_cut_1d]

    # 4h Macro_PD_1d_4h truncation invariance (both 4h series AND closed 1d zones truncated at t_4h_cut + 14400)
    price_4h_full = ds_m_full["price_with_warmup"]
    cut_4h = len(price_4h_full) - 240
    price_4h_pref = price_4h_full[:cut_4h]
    t_4h_cut = int(price_4h_pref[-1]["time"])
    l1_4h_pref = l1_full[l1_full["known_ts"] <= (t_4h_cut + 14400)].copy()

    ds_m_pref = dict(ds_m_full)
    ds_m_pref["price_with_warmup"] = price_4h_pref
    sigs_4h_full = rme.compute_4h_macro_signals(ds_m_full, l1_full)
    sigs_4h_pref = rme.compute_4h_macro_signals(ds_m_pref, l1_4h_pref)
    assert sigs_4h_pref == [s for s in sigs_4h_full if s["time"] <= t_4h_cut]


# ─── 5. Scale-Invariant Taker Ratio & Fallback ────────────────────────────────

def test_taker_ratio_scale_invariant_and_fallback():
    t0 = _utc_ts(2025, 1, 1, 16)
    known_ts = [t0 + 86400, t0 + 2 * 86400]
    # Binance has day 1 (in USD millions), missing day 2; OKX has both days (in contracts)
    bin_rows = rme.compute_taker_ratio_rows([
        {"time": t0, "taker_buy_vol": 60_000_000.0, "taker_sell_vol": 40_000_000.0},
    ])
    okx_rows = rme.compute_taker_ratio_rows([
        {"time": t0, "taker_buy_vol": 100.0, "taker_sell_vol": 300.0},
        {"time": t0 + 86400, "taker_buy_vol": 300.0, "taker_sell_vol": 100.0},
    ])
    # Tolerance 0 so day 2 only tests exact fallback from OKX when Binance row is absent
    tb = rme.align_series_by_known_ts(known_ts, bin_rows, source_shift_sec=86400, tolerance_sec=0)
    to = rme.align_series_by_known_ts(known_ts, okx_rows, source_shift_sec=86400, tolerance_sec=0)
    combined = np.where(np.isfinite(tb), tb, to)
    assert combined[0] == pytest.approx(0.60)  # Prefers Binance
    assert combined[1] == pytest.approx(0.75)  # Falls back cleanly to OKX


# ─── 6. Major Wave Capture & WideATRBacktester Verification ───────────────────

def test_major_wave_capture_strictly_before_mae_and_backtest_conservation():
    t0 = _utc_ts(2025, 1, 1, 16)
    # 35 daily bars: signal at bar 0 (close=100)
    # Case A: bar 2 hits +12% MFE (high=112, low=98), bar 5 hits -6% MAE (low=94) -> Capture=True
    bars_a = [{"time": t0 + i * 86400, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0} for i in range(35)]
    bars_a[2] = {"time": t0 + 2 * 86400, "open": 100.0, "high": 112.0, "low": 98.0, "close": 110.0}
    bars_a[5] = {"time": t0 + 5 * 86400, "open": 100.0, "high": 101.0, "low": 94.0, "close": 95.0}
    out_a = rme.compute_multi_horizon_outcomes(bars_a, [{"time": t0, "direction": "bullish"}], step_sec=86400)
    assert out_a[0]["major_wave_capture"] is True

    # Case B: BOTH +12% MFE and -6% MAE occur on bar 2 (same bar) -> Conservative False!
    bars_b = [{"time": t0 + i * 86400, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0} for i in range(35)]
    bars_b[2] = {"time": t0 + 2 * 86400, "open": 100.0, "high": 112.0, "low": 94.0, "close": 102.0}
    out_b = rme.compute_multi_horizon_outcomes(bars_b, [{"time": t0, "direction": "bullish"}], step_sec=86400)
    assert out_b[0]["major_wave_capture"] is False

    # WideATRBacktester conservation, sizing cap (<=0.95x), Chandelier trailing & funding test
    candles = []
    for i in range(30):
        px = 100.0 + (i - 15) * 1.5 if i >= 15 else 100.0
        candles.append({"time": t0 + i * 86400, "open": px - 0.5, "high": px + 2.0, "low": px - 2.0, "close": px})
    # Bar 22 activates Chandelier (+1.5x ATR) and bar 24 pulls back to trigger Chandelier trailing stop
    candles[22] = {"time": t0 + 22 * 86400, "open": 110.0, "high": 122.0, "low": 109.5, "close": 120.0}
    candles[23] = {"time": t0 + 23 * 86400, "open": 120.0, "high": 124.0, "low": 118.0, "close": 121.0}
    candles[24] = {"time": t0 + 24 * 86400, "open": 121.0, "high": 121.5, "low": 105.0, "close": 106.0}

    sigs = [{"time": t0 + 15 * 86400, "direction": "bullish"}]
    funding = [{"time": t0 + k * 86400, "funding_rate": 0.0002} for k in range(16, 26)]

    bt = rme.WideATRBacktester(
        candles,
        sigs,
        funding_rates=funding,
        slippage_bps=5.0,
        fee_rate=0.0005,
        include_funding=True,
        risk_per_trade_pct=1.5,
        max_notional_pct=0.95,
        initial_sl_atr_mult=2.5,
        chandelier_act_atr_mult=1.5,
        chandelier_trail_atr_mult=3.0,
        investment=10000.0,
    )
    res = bt.run()
    assert len(bt.closed_positions) == 1
    pos = bt.closed_positions[0]
    assert pos.exit_reason == "trailing"
    assert pos.cost <= 10000.0 * 0.95 + 1e-6
    assert res["total_funding_pnl"] < 0.0
    assert abs((res["final_balance"] - 10000.0) - sum(p.realized_pnl for p in bt.closed_positions)) < 1e-2


def test_opposite_armed_window_cleared_only_on_confirmed_bos_and_cooldown():
    """
    Verify on 1d:
      - Layer 1 top trigger does NOT clear an active bottom armed window (only confirmed opposite BOS does).
      - cond3 (3-day strong close BOS) requires i >= arm_bar + 2.
      - Minimum 15-day same-direction cooldown is enforced.
    """
    from unittest.mock import patch

    t0 = _utc_ts(2025, 1, 1, 16)
    n = 110
    rows = []
    for i in range(n):
        rows.append({
            "time": t0 + i * 86400,
            "known_ts": t0 + (i + 1) * 86400,
            "open": 100.0,
            "high": 100.5,
            "low": 99.5,
            "close": 100.0,
            "volume": 1000.0,
            "ema20": 105.0,
            "ema50": 105.0,
            "ema200": 105.0,
            "atr14": 2.0,
            "rsi14": 50.0,
            "bb_pctb": 0.5,
            "z_ema50": 0.0,
            "dd_60d_atr": 0.0,
            "rally_60d_atr": 0.0,
            "price_bottom_zone": False,
            "price_top_zone": False,
            "deriv_bottom_ok": False,
            "deriv_top_ok": False,
            "pd_bottom_zone": False,
            "pd_top_zone": False,
        })

    # Arm bottom at bar 70; trigger UNCONFIRMED top zone at bar 71 (must NOT clear bottom!)
    rows[70]["pd_bottom_zone"] = True
    rows[71]["pd_top_zone"] = True
    # Bar 71 has close > 3d high? Even if high/close > 3d high with strong body, i=71 < 70+2 blocks cond3!
    rows[71]["open"] = 99.0
    rows[71]["high"] = 101.0
    rows[71]["low"] = 99.0
    rows[71]["close"] = 100.9  # strong close > prev_high(100.5), < ema20(105), < 5d high(if bar 68 had high=102)
    rows[67]["high"] = 102.0
    # Bar 72 (i == 70 + 2): cond3 activates (close=101.2 > prev_high(101.0), strong close >= 60%, > 3d high) -> fires!
    rows[72]["open"] = 100.0
    rows[72]["low"] = 100.0
    rows[72]["high"] = 101.4
    rows[72]["close"] = 101.2
    # Re-arm bottom at bar 78 and break 5d high at bar 80 -> blocked by 15d cooldown (80 - 72 < 15)!
    rows[78]["pd_bottom_zone"] = True
    rows[80]["open"] = 100.0
    rows[80]["low"] = 99.8
    rows[80]["high"] = 105.0
    rows[80]["close"] = 104.5
    # Re-arm bottom at bar 88 and break 5d high at bar 89 -> 89 - 72 = 17 >= 15 -> fires!
    rows[88]["pd_bottom_zone"] = True
    rows[89]["open"] = 100.0
    rows[89]["low"] = 100.0
    rows[89]["high"] = 108.0
    rows[89]["close"] = 107.5

    fake_l1 = rme.pd.DataFrame(rows)
    ds_fake = {"eval_start": t0 + 60 * 86400, "df_1d": fake_l1}

    with patch.object(rme, "evaluate_layer1_1d", return_value=fake_l1):
        sigs, _ = rme.compute_1d_macro_signals(ds_fake, "Macro_PD_1d")

    bull_times = [s["time"] for s in sigs if s["direction"] == "bullish"]
    assert bull_times == [t0 + 72 * 86400, t0 + 89 * 86400]


def test_wide_atr_backtester_reverse_on_signal_and_initial_sl():
    t0 = _utc_ts(2025, 1, 1, 16)
    candles = [
        {"time": t0 + i * 86400, "open": 100.0, "high": 102.0, "low": 98.0, "close": 100.0}
        for i in range(25)
    ]
    # Bullish signal at bar 15 -> enters long around 100.0; bearish signal at bar 18 reverses to short;
    # bar 20 spikes sharply to hit short initial SL (+2.5 * ATR)
    candles[20] = {"time": t0 + 20 * 86400, "open": 100.0, "high": 120.0, "low": 99.5, "close": 115.0}
    sigs = [
        {"time": t0 + 15 * 86400, "direction": "bullish"},
        {"time": t0 + 18 * 86400, "direction": "bearish"},
    ]
    bt = rme.WideATRBacktester(candles, sigs, slippage_bps=15.0, fee_rate=0.0005, include_funding=False)
    res = bt.run()
    reasons = [p.exit_reason for p in bt.closed_positions]
    assert reasons == ["signal_reverse", "sl"]
    assert abs((res["final_balance"] - 10000.0) - sum(p.realized_pnl for p in bt.closed_positions)) < 1e-2


# ─── 7. AST Guard & End-to-End Synthetic Mode Check ───────────────────────────

def test_no_bfill_or_inplace_in_macro_experiment_script():
    script_path = Path(rme.__file__).resolve()
    src = script_path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr != "bfill", "Forbidden .bfill() look-ahead found!"
            for kw in node.keywords:
                if kw.arg == "inplace" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    raise AssertionError(f"Forbidden inplace=True found in {node.func.attr}!")
                if kw.arg == "method" and isinstance(kw.value, ast.Constant) and str(kw.value.value).lower() == "bfill":
                    raise AssertionError("Forbidden method='bfill' found!")


def test_end_to_end_synthetic_mode_no_warnings(tmp_path: Path):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("error")
        # Production api/ files are untouched in Phase 1 and emit pre-existing Pandas4Warning in Docker.
        warnings.filterwarnings("ignore", category=Warning, module=r"^api\.")
        summary = rme.run_all_macro_experiments(mode="synthetic", output_dir=tmp_path)

    assert len(caught) == 0
    md_path = Path(summary["md_path"])
    json_path = Path(summary["json_path"])
    assert md_path.exists()
    assert json_path.exists()

    parsed = json.loads(json_path.read_text(encoding="utf-8"))
    json.dumps(parsed, allow_nan=False)

    assert len(parsed["section0_inventory"]) == 10  # 5 coins x (Dataset L + Dataset M)
    pooled_vars = {r["variant"] for r in parsed["section1_inflection_pooled"]}
    assert pooled_vars == {
        "Legacy_v8_1d",
        "Macro_LeftOnly_1d",
        "Macro_P_1d",
        "Macro_PD_1d",
        "Legacy_v8_4h",
        "Macro_PD_1d_4h",
    }
    assert all(r["signals"] > 0 for r in parsed["section1_inflection_pooled"])
    assert len(parsed["section2_backtest_pooled"]) == 12  # 6 variants x 2 slippage levels (5 bps, 15 bps)
    assert len(parsed["section3_walkforward_pooled"]) == 6
    assert "overall_verdict" in parsed["section4_verdict"]

    md_text = md_path.read_text(encoding="utf-8")
    assert "## 0. Clean Dataset Inventory" in md_text
    assert "## 1. Multi-Horizon Inflection Quality" in md_text
    assert "## 2. Wide-ATR Macro Swing Backtest" in md_text
    assert "## 3. Chronological 60% IS vs 40% OOS Blind Walk-Forward" in md_text
    assert "## 4. Automated Objective Falsification Verdict" in md_text


# ─── 8. Adversarial Regression Tests (OI Gap, Raw Truncation, 4h Expiry, Verdict) ──

def test_combine_oi_causal_preserves_scale_across_multibar_outage():
    """
    When OKX starts alone (40M) and Binance joins mid-history (60M), chain-linked OI
    must stay on the ~40M scale — and MUST NOT jump +150% to 100M if both exchanges
    suffer a >4-bar outage and resume together.
    """
    okx = np.array([40e6, 40e6, 42e6, 42e6, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, 44e6, 44e6])
    bin_ = np.array([np.nan, np.nan, 60e6, 60e6, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, 63e6, 66e6])
    out = rme.combine_oi_causal(okx, bin_)

    assert out[1] == pytest.approx(40e6)
    assert out[2] == pytest.approx(42e6)
    assert math.isnan(out[5])
    # After 6-bar outage (4..9), resuming at idx 10 must scale smoothly (~44M, NOT 107M!)
    assert out[10] == pytest.approx(42e6 * ((44e6 + 63e6) / (42e6 + 60e6)))
    assert out[10] < 50e6

    # Also test switching back to OKX-only after Binance-only bridge
    okx2 = np.array([40e6, 40e6, np.nan, np.nan, np.nan, 44e6])
    bin2 = np.array([np.nan, 60e6, 63e6, 66e6, np.nan, np.nan])
    out2 = rme.combine_oi_causal(okx2, bin2)
    assert out2[5] == pytest.approx(44e6)


def test_raw_dataset_builders_truncation_invariance_1d_and_4h():
    """
    Truncating raw OHLCV/derivatives/funding BEFORE calling build_dataset_l_from_raw
    and build_dataset_m_from_raw must yield identical features, Layer 1 zones, and signals
    over the prefix 0..t_cut as the full 0..N pipeline.
    """
    rng = np.random.default_rng(777)
    t_base = _utc_ts(2024, 6, 1, 16)
    n_1d = 360
    px_4h_all = []
    p = 2500.0
    for k in range(n_1d * 6):
        t_open = t_base + k * 14400
        drift = 0.002 * math.sin(2.0 * math.pi * (k / 6.0) / 90.0)
        shock = float(rng.normal(drift, 0.014))
        o = p
        c = max(200.0, o * (1.0 + shock))
        h = max(o, c) * 1.008
        l = min(o, c) * 0.992
        px_4h_all.append({"time": t_open, "open": o, "high": h, "low": l, "close": c, "volume": 1e5})
        p = c

    ohlcv_1d = []
    okx_1d, bin_1d, funding = [], [], []
    for d in range(n_1d):
        chunk = px_4h_all[d * 6 : (d + 1) * 6]
        t_1d = chunk[0]["time"]
        ohlcv_1d.append({
            "time": t_1d,
            "open": chunk[0]["open"],
            "high": max(x["high"] for x in chunk),
            "low": min(x["low"] for x in chunk),
            "close": chunk[-1]["close"],
            "volume": sum(x["volume"] for x in chunk),
        })
        wave = math.sin(2.0 * math.pi * d / 90.0)
        okx_1d.append({
            "time": t_1d,
            "open_interest": 1e7 * chunk[-1]["close"] * (1.0 + 0.2 * wave),
            "long_short_ratio": 1.1 + 0.3 * wave,
            "taker_buy_vol": 1e5 * (0.5 + 0.1 * wave),
            "taker_sell_vol": 1e5 * (0.5 - 0.1 * wave),
        })
        if d >= 180:
            bin_1d.append({
                "time": t_1d - 57600,
                "open_interest": 2e7 * chunk[-1]["close"] * (1.0 + 0.2 * wave),
                "long_short_ratio": 1.2 + 0.3 * wave,
                "taker_buy_vol": 3e5 * (0.52 - 0.1 * wave),
                "taker_sell_vol": 3e5 * (0.48 + 0.1 * wave),
            })
        if d >= 120:
            for off in (0, 28800, 57600):
                funding.append({"time": t_1d + off, "funding_rate": 0.0001 + 0.0002 * wave})

    ohlcv_4h = [b for b in px_4h_all if b["time"] >= ohlcv_1d[60]["time"]]
    deriv_sub = []
    for b in ohlcv_4h[300:]:
        deriv_sub.append({
            "time": b["time"],
            "exchange": "binance",
            "timeframe": "1h",
            "open_interest": 2e7 * b["close"],
            "long_short_ratio": 1.15,
            "taker_buy_vol": 1e4,
            "taker_sell_vol": 9e3,
        })

    ds_l_full = rme.build_dataset_l_from_raw("ETH/USDT", ohlcv_1d, {"okx": okx_1d, "binance": bin_1d}, funding)
    ds_m_full = rme.build_dataset_m_from_raw("ETH/USDT", ohlcv_4h, ds_l_full, deriv_sub, {"okx": okx_1d, "binance": bin_1d}, funding)
    sigs_l_full, l1_full = rme.compute_1d_macro_signals(ds_l_full, "Macro_PD_1d")
    sigs_m_full = rme.compute_4h_macro_signals(ds_m_full, l1_full)
    leg_l_full = rme.run_legacy_v8_signals(ds_l_full, None)
    leg_m_full = rme.run_legacy_v8_signals(ds_m_full, None)

    # Truncate raw streams strictly at cut_d = 290 (so future 70 days do NOT exist anywhere!)
    cut_d = 290
    t_cut_1d = ohlcv_1d[cut_d]["time"]
    t_cut_1d_known = t_cut_1d + 86400
    t_cut_4h = t_cut_1d + 72000  # closes exactly at t_cut_1d_known

    ohlcv_1d_pref = [b for b in ohlcv_1d if b["time"] <= t_cut_1d]
    deriv_1d_pref = {
        "okx": [r for r in okx_1d if r["time"] + 86400 <= t_cut_1d_known],
        "binance": [r for r in bin_1d if r["time"] + 86400 <= t_cut_1d_known],
    }
    funding_pref = [f for f in funding if f["time"] <= t_cut_1d_known]
    ohlcv_4h_pref = [b for b in ohlcv_4h if b["time"] <= t_cut_4h]
    deriv_sub_pref = [r for r in deriv_sub if r["time"] + 14400 <= t_cut_4h + 14400]

    ds_l_pref = rme.build_dataset_l_from_raw("ETH/USDT", ohlcv_1d_pref, deriv_1d_pref, funding_pref)
    ds_m_pref = rme.build_dataset_m_from_raw("ETH/USDT", ohlcv_4h_pref, ds_l_pref, deriv_sub_pref, deriv_1d_pref, funding_pref)
    sigs_l_pref, l1_pref = rme.compute_1d_macro_signals(ds_l_pref, "Macro_PD_1d")
    sigs_m_pref = rme.compute_4h_macro_signals(ds_m_pref, l1_pref)
    leg_l_pref = rme.run_legacy_v8_signals(ds_l_pref, None)
    leg_m_pref = rme.run_legacy_v8_signals(ds_m_pref, None)

    assert len(l1_pref) == cut_d + 1
    for col in ("coin_oi", "taker_ratio", "lsur_z_90d", "funding_daily", "z_ema50", "dd_60d_atr", "rally_60d_atr"):
        np.testing.assert_allclose(
            l1_pref[col].to_numpy(dtype=float),
            l1_full[col].iloc[: cut_d + 1].to_numpy(dtype=float),
            rtol=1e-12,
            atol=1e-12,
            equal_nan=True,
        )
    assert sigs_l_pref == [s for s in sigs_l_full if s["time"] <= t_cut_1d]
    assert sigs_m_pref == [s for s in sigs_m_full if s["time"] <= t_cut_4h]
    assert leg_l_pref == [s for s in leg_l_full if s["time"] <= t_cut_1d]
    assert leg_m_pref == [s for s in leg_m_full if s["time"] <= t_cut_4h]


def test_4h_10day_window_expiry_and_opposite_bos_clear():
    """
    Verify on 4h:
      - Closed 1d bottom zone remains armed up to 10 * 86400 after 1d close, and expires at 10 * 86400 + 14400.
      - Confirmed opposite 4h BOS clears prior opposite 1d armed zone.
    """
    t_1d_open = _utc_ts(2025, 8, 1, 16)
    t_1d_close = t_1d_open + 86400
    l1_df = rme.pd.DataFrame([
        {"time": t_1d_open, "known_ts": t_1d_close, "pd_bottom_zone": True, "pd_top_zone": False},
    ])

    # Build steady 4h bars for 65 bars before t_1d_close, then breakout at exact +10d+4h (expired!)
    start_4h = t_1d_close - 60 * 14400
    t_4h_expired = t_1d_close + 10 * 86400  # bar open -> close is t_1d_close + 10*86400 + 14400 (> 10d!)
    price_4h = []
    for k in range(140):
        t = start_4h + k * 14400
        if t < t_4h_expired:
            price_4h.append({"time": t, "open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0, "volume": 1000.0})
        elif t == t_4h_expired:
            price_4h.append({"time": t, "open": 100.0, "high": 106.0, "low": 100.0, "close": 105.5, "volume": 2000.0})
        else:
            price_4h.append({"time": t, "open": 105.5, "high": 105.8, "low": 105.0, "close": 105.5, "volume": 1000.0})

    sigs_exp = rme.compute_4h_macro_signals({"eval_start": start_4h + 50 * 14400, "price_with_warmup": price_4h}, l1_df)
    assert sigs_exp == []

    # Now test opposite BOS clearing: 1d top closes at day 0, 1d bottom closes at day 2,
    # 4h bullish BOS fires at day 3 -> must clear the day-0 top armed zone!
    t_top_close = t_1d_close
    t_bot_close = t_1d_close + 2 * 86400
    l1_opp = rme.pd.DataFrame([
        {"time": t_1d_open, "known_ts": t_top_close, "pd_bottom_zone": False, "pd_top_zone": True},
        {"time": t_1d_open + 2 * 86400, "known_ts": t_bot_close, "pd_bottom_zone": True, "pd_top_zone": False},
    ])
    price_opp = []
    for k in range(110):
        t = start_4h + k * 14400
        if t < t_bot_close - 14400:
            price_opp.append({"time": t, "open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0, "volume": 1000.0})
        elif t == t_bot_close - 14400:
            # Bullish BOS right when bottom zone closes
            price_opp.append({"time": t, "open": 100.0, "high": 106.0, "low": 100.0, "close": 105.5, "volume": 2000.0})
        elif t == t_bot_close + 3 * 14400:
            # Sharp drop below Donchian20_lower & EMA50 & RSI<=48 while day-0 top zone is <10d old!
            price_opp.append({"time": t, "open": 105.0, "high": 105.0, "low": 90.0, "close": 91.0, "volume": 3000.0})
        else:
            last_c = price_opp[-1]["close"]
            price_opp.append({"time": t, "open": last_c, "high": last_c + 0.1, "low": last_c - 0.1, "close": last_c, "volume": 1000.0})

    sigs_opp = rme.compute_4h_macro_signals({"eval_start": start_4h + 50 * 14400, "price_with_warmup": price_opp}, l1_opp)
    assert [s["direction"] for s in sigs_opp] == ["bullish"]


def test_pooled_trade_stats_and_verdict_prevent_999_pf_distortion():
    """
    A single winning coin with PF=999.9 or a 0-trade coin must NOT distort pooled PF
    or falsely pass H4_OOS_Viability when pooled trade expectancy/PF are negative.
    """
    stats = [
        {"trades": 1, "wins_count": 1, "gross_profit": 20.0, "gross_loss": 0.0, "trade_rets": [0.2]},
        {"trades": 4, "wins_count": 0, "gross_profit": 0.0, "gross_loss": 200.0, "trade_rets": [-2.0, -2.0, -2.0, -2.0]},
        {"trades": 0, "wins_count": 0, "gross_profit": 0.0, "gross_loss": 0.0, "trade_rets": []},
    ]
    pooled = rme._pool_trade_stats(stats)
    assert pooled["total_trades"] == 5
    assert pooled["pooled_wr"] == pytest.approx(20.0)
    assert pooled["pooled_pf"] == pytest.approx(0.10)
    assert pooled["pooled_exp"] < 0.0

    # Verify single-day NaN gap in coin_oi doesn't wipe out 30 days of coin_oi_dd_30d
    t0 = _utc_ts(2025, 1, 1, 16)
    bars = _make_1d_bars(t0, 100, base_price=100.0)
    df = rme.pd.DataFrame(bars)
    df["known_ts"] = df["time"] + 86400
    df["coin_oi"] = 1000.0
    df.loc[65, "coin_oi"] = float("nan")
    df.loc[75:, "coin_oi"] = 850.0  # -15% OI drawdown
    df["taker_ratio"] = 0.50
    df["lsur_z_90d"] = 0.0
    df["funding_daily"] = float("nan")
    l1 = rme.evaluate_layer1_1d(df)
    assert bool(l1.loc[76, "deriv_bottom_ok"]) is True

