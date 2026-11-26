"""
Unit, behavioral, causality, and end-to-end verification tests for Phase 1.6 Macro Cycle Prototype
(scripts/run_macro_cycle_v16_experiments.py):
  1. Fair Dataset C (warmup_bars = min(60, max(40, len(bars) // 6))) & strict causal alignment
  2. Raw-stream prefix-truncation invariance (0..k vs 0..N identical for features, entries, exits, state)
  3. Anti-bear-trap regression test (-40% crash + +18% dead-cat bounce above falling EMA50, < EMA200)
  4. Early-bull hold regression test (+35% rally, low ATR, Mayer=1.25 < 1.55 -> no EUPHORIA_TOP_V16)
  5. Selective derivative washout & anti-crowding tests (Path A/B washout, Path A blocked + Path C passes,
     Path C crowding block, exit_deriv_evaluable_bar_v16 FR/LSUR fallback & fr_7d_mean check, extreme blowoff)
  6. BASE_INVALIDATION_V16 (3.0x ATR, < 1.25x threshold, 10d cooldown, PnL conservation) & zero-ATR safety
  7. AST guard against .bfill(), method='bfill', inplace=True + --mode synthetic -W error check
"""

from __future__ import annotations

import ast
import json
import math
import warnings
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import scripts.run_macro_cycle_experiments as rmc
import scripts.run_macro_cycle_v16_experiments as v16
from api.db.database import Base
from api.db.models import FundingRate, MarketDataPoint


def _utc_ts(year: int, month: int, day: int, hour: int = 0) -> int:
    return int(datetime(year, month, day, hour, 0, tzinfo=timezone.utc).timestamp())


def _utc_dt(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _make_df_from_closes(
    start_ts: int,
    closes: List[float],
    *,
    high_mult: float = 1.015,
    low_mult: float = 0.985,
    has_deriv: bool = False,
) -> pd.DataFrame:
    rows = []
    prev_c = closes[0]
    for i, c in enumerate(closes):
        o = prev_c if i > 0 else c
        h = max(o, c) * high_mult
        l = min(o, c) * low_mult
        rows.append({
            "time": start_ts + i * 86400,
            "known_ts": start_ts + (i + 1) * 86400,
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": 10000.0,
            "oi_usd": 1e8 if has_deriv else float("nan"),
            "coin_oi": 1e6 if has_deriv else float("nan"),
            "taker_ratio": 0.52 if has_deriv else float("nan"),
            "lsur_z_90d": 0.0 if has_deriv else float("nan"),
            "funding_daily": 0.0001 if has_deriv else float("nan"),
            "has_deriv": has_deriv,
        })
        prev_c = c
    return pd.DataFrame(rows)


# ─── 1. Fair Dataset C Warmup Formula & Causal Alignment ──────────────────────

def test_dataset_c_v16_warmup_and_causal_alignment():
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

        start_okx = _utc_ts(2022, 5, 22, 16)
        n_days = 600
        deriv_start = 400
        target_idx = 480
        t_okx_target = start_okx + target_idx * 86400
        t_bin_next = t_okx_target + 28800

        with TestSession() as db:
            for i in range(n_days):
                t_c = start_okx + i * 86400
                px = 20000.0 + 1000.0 * math.sin(i / 25.0)
                db.add(MarketDataPoint(
                    exchange="okx",
                    symbol="BTC/USDT",
                    timeframe="1d",
                    timestamp=_utc_dt(t_c),
                    open=px,
                    high=px * 1.02,
                    low=px * 0.98,
                    close=px,
                    volume=5000.0,
                ))
                if deriv_start <= i < n_days and i != (target_idx + 1):
                    t_b = t_c - 57600
                    db.add(MarketDataPoint(
                        exchange="binance",
                        symbol="BTC/USDT",
                        timeframe="1d",
                        timestamp=_utc_dt(t_b),
                        open_interest=5e8,
                        long_short_ratio=1.0,
                        taker_buy_vol=500.0,
                        taker_sell_vol=500.0,
                    ))
            db.add(MarketDataPoint(
                exchange="binance",
                symbol="BTC/USDT",
                timeframe="1d",
                timestamp=_utc_dt(t_bin_next),
                open_interest=9e9,
                long_short_ratio=4.5,
                taker_buy_vol=950.0,
                taker_sell_vol=50.0,
            ))
            for i in range(500, n_days):
                t_c = start_okx + i * 86400
                fmt = "BTC/USDT:USDT" if i < 550 else "BTC-USDT-SWAP"
                db.add(FundingRate(exchange="okx", symbol=fmt, timestamp=_utc_dt(t_c), funding_rate=0.0001))
            db.commit()

        ds_map = v16.load_dataset_c_v16_from_db(["BTC/USDT"], session_factory=session_factory)
        ds = ds_map["BTC/USDT"]
        assert ds["valid"] is True
        assert ds["total_bars"] == 600
        assert ds["warmup_bars"] == 60  # min(60, max(40, 600 // 6)) == 60
        assert ds["clean_bars"] == 540

        df = ds["df_1d"]
        assert not df["has_deriv"].iloc[:deriv_start].any()
        assert df["has_deriv"].iloc[deriv_start:].all()
        row_d = df.loc[df["time"] == t_okx_target].iloc[0]
        row_d1 = df.loc[df["time"] == (t_okx_target + 86400)].iloc[0]
        assert row_d["taker_ratio"] == pytest.approx(0.50, abs=1e-9)
        assert row_d["oi_usd"] == pytest.approx(5e8, abs=1e-3)
        assert row_d1["taker_ratio"] == pytest.approx(0.95, abs=1e-9)
        assert row_d1["oi_usd"] == pytest.approx(9e9, abs=1e-3)

        # Verify warmup_bars formula across boundary lengths (386 -> 60, 240 -> 40, 100 -> 40, 79 -> invalid)
        for length, exp_valid, exp_warm in [(386, True, 60), (240, True, 40), (100, True, 40), (79, False, None)]:
            bars = [
                {"time": start_okx + i * 86400, "open": 100.0, "high": 102.0, "low": 98.0, "close": 101.0, "volume": 1000.0}
                for i in range(length)
            ]
            d_test = v16.build_dataset_c_v16_from_raw("CC/USDT", bars, {"okx": [], "binance": []}, [])
            assert d_test["valid"] is exp_valid
            if exp_valid:
                assert d_test["warmup_bars"] == exp_warm
    finally:
        engine.dispose()


# ─── 2. Strict Raw-Stream Prefix-Truncation Invariance (0..k vs 0..N) ─────────

def test_raw_stream_prefix_truncation_invariance_v16():
    """
    Truncating raw OHLCV/derivatives/funding streams at bar k (0..k) vs full 0..N must produce
    IDENTICAL features, entry signals, closed exits (excluding BACKTEST_END), and final_state
    for both Cycle_P_v16_1d and Cycle_PD_v16_1d.
    """
    rng = np.random.default_rng(2026)
    t_base = _utc_ts(2022, 6, 1, 16)
    n_raw = 900
    raw_ohlcv, raw_okx, raw_bin, raw_fund = [], [], [], []
    px = 25000.0
    for d in range(n_raw):
        t_d = t_base + d * 86400
        if d < 120:
            drift = -0.0055
        elif d < 320:
            drift = 0.0045
        elif d < 400:
            drift = -0.0040
        elif d < 620:
            drift = 0.0050
        elif d < 780:
            drift = -0.0045
        else:
            drift = 0.0035
        c = max(5000.0, px * (1.0 + drift + float(rng.normal(0.0, 0.022))))
        h = max(px, c) * 1.015
        l = min(px, c) * 0.985
        raw_ohlcv.append({"time": t_d, "open": px, "high": h, "low": l, "close": c, "volume": 1e6})
        px = c
        if d >= 200:
            oi_wave = 1.0 + 0.35 * math.sin(d / 35.0)
            raw_okx.append({
                "time": t_d,
                "open_interest": 5e8 * oi_wave,
                "long_short_ratio": 1.1 + 0.4 * math.sin(d / 28.0),
                "taker_buy_vol": 5e5,
                "taker_sell_vol": 4.8e5,
            })
            raw_bin.append({
                "time": t_d - 57600,
                "open_interest": 7e8 * oi_wave,
                "long_short_ratio": 1.2 + 0.4 * math.sin(d / 28.0),
                "taker_buy_vol": 8e5,
                "taker_sell_vol": 7.5e5,
            })
        if d >= 350:
            for off in (0, 28800, 57600):
                raw_fund.append({"time": t_d + off, "funding_rate": 0.0001 + 0.00025 * math.sin(d / 32.0)})

    ds_full = v16.build_dataset_c_v16_from_raw("BTC/USDT", raw_ohlcv, {"okx": raw_okx, "binance": raw_bin}, raw_fund)
    feat_full = v16.evaluate_cycle_v16_features_1d(ds_full["df_1d"])
    assert ds_full["warmup_bars"] == 60

    # Feature truncation invariance across multiple early and late cuts
    for cut_k in (240, 420, 720):
        t_cut = raw_ohlcv[cut_k - 1]["time"]
        t_cut_known = t_cut + 86400
        ds_pref = v16.build_dataset_c_v16_from_raw(
            "BTC/USDT",
            [b for b in raw_ohlcv if b["time"] <= t_cut],
            {
                "okx": [r for r in raw_okx if r["time"] + 86400 <= t_cut_known],
                "binance": [r for r in raw_bin if r["time"] + 86400 <= t_cut_known],
            },
            [f for f in raw_fund if f["time"] <= t_cut_known],
        )
        feat_pref = v16.evaluate_cycle_v16_features_1d(ds_pref["df_1d"])

        for col in (
            "ema20", "ema50", "ema200", "atr14", "rsi14", "atr_pct_median60",
            "dd_180_pct", "dd_90_pct", "coin_oi_dd_60d", "coin_oi_pct_180d",
            "fr_7d_mean", "fr_pct_180d",
        ):
            np.testing.assert_allclose(
                feat_pref[col].to_numpy(dtype=float),
                feat_full[col].iloc[:cut_k].to_numpy(dtype=float),
                rtol=1e-12,
                atol=1e-12,
                equal_nan=True,
            )
        for bcol in (
            "has_deriv", "bear_left_active_v16", "reg_left_active_v16",
            "path_a_v16_ok", "path_b_v16_ok", "path_c_v16_ok",
            "washout_evaluable_bar_v16", "washout_bar_v16",
            "has_washout_deriv_60d", "deriv_washout_60d",
            "has_washout_deriv_35d", "deriv_washout_35d",
            "deriv_not_crowded_c",
            "euphoria_price_30d_v16", "has_exit_deriv_30d_v16",
            "deriv_overheated_30d_v16", "extreme_blowoff_30d_v16",
            "euphoria_breakdown_right_v16", "regime_bear_exit_v16",
        ):
            assert list(feat_pref[bcol]) == list(feat_full[bcol].iloc[:cut_k])

        if cut_k >= 360:
            assert ds_pref["warmup_bars"] == 60
            for var in ("Cycle_P_v16_1d", "Cycle_PD_v16_1d"):
                rf = v16.simulate_cycle_v16_strategy(
                    "BTC/USDT", feat_full, var, start_idx=60, funding_rates=ds_full["all_funding_settlements"]
                )
                rp = v16.simulate_cycle_v16_strategy(
                    "BTC/USDT", feat_pref, var, start_idx=60, funding_rates=ds_pref["all_funding_settlements"]
                )
                assert [
                    (int(p.entry_time), p.entry_type, round(p.entry_price, 8))
                    for p in rp["closed_positions"]
                ] == [
                    (int(p.entry_time), p.entry_type, round(p.entry_price, 8))
                    for p in rf["closed_positions"]
                    if int(p.entry_time) <= t_cut
                ]
                assert [
                    (int(p.exit_time), p.exit_reason, round(p.exit_price, 8))
                    for p in rp["closed_positions"]
                    if p.exit_reason != "BACKTEST_END"
                ] == [
                    (int(p.exit_time), p.exit_reason, round(p.exit_price, 8))
                    for p in rf["closed_positions"]
                    if int(p.exit_time) <= t_cut and p.exit_reason != "BACKTEST_END"
                ]
                assert rp["signals"] == [
                    s for s in rf["signals"] if int(s["time"]) <= t_cut
                ]
                active_at_cut = [
                    p for p in rf["closed_positions"]
                    if int(p.entry_time) <= t_cut and int(p.exit_time) > t_cut
                ]
                expected_state = active_at_cut[0].side.upper() if active_at_cut else "FLAT"
                assert rp["final_state"] == expected_state


# ─── 3. Anti-Bear-Trap Regression Test ────────────────────────────────────────

def test_anti_bear_trap_dead_cat_bounce_blocked_in_v16_while_p15_triggered():
    """
    -40% bear crash followed by +18% dead-cat bounce closing above falling EMA50 (< EMA50[10d ago])
    and below EMA200 MUST NOT trigger Path A_v16 (or Path B/C_v16), whereas Phase 1.5 Path A did.
    """
    t0 = _utc_ts(2025, 1, 1, 16)
    closes: List[float] = []
    # Bars 0..149: steady secular price at 150.0 (warms up EMA200=150, EMA50=150, EMA20=150)
    for _ in range(150):
        closes.append(150.0)
    # Bars 150..199: -44% bear crash 150 -> 84 (RSI <= 33, dd_180 >= 0.44, EMA50 slopes down)
    for i in range(50):
        closes.append(150.0 - (150.0 - 84.0) * (i + 1) / 50.0)
    # Bars 200..220: flat consolidation at 84 (lets 20d high settle near ~89 while EMA50 keeps falling)
    for _ in range(21):
        closes.append(84.0)
    # Bars 221..227: +18% dead-cat bounce 84 -> 99.12 (closes above falling EMA50, below EMA200!)
    for i in range(7):
        closes.append(84.0 + (99.12 - 84.0) * (i + 1) / 7.0)

    df = _make_df_from_closes(t0, closes, high_mult=1.005, low_mult=0.995, has_deriv=False)
    feat_p15 = rmc.evaluate_cycle_features_1d(df)
    feat_v16 = v16.evaluate_cycle_v16_features_1d(df)

    # Verify exact bear-trap geometry at the dead-cat bounce window (bars 221..227)
    assert (feat_v16["ema50"] < feat_v16["ema50"].shift(10)).iloc[221:].all()
    assert float(feat_v16["close"].iloc[-1]) > float(feat_v16["ema50"].iloc[-1])
    assert float(feat_v16["close"].iloc[-1]) < float(feat_v16["ema200"].iloc[-1])

    # Phase 1.5 Path A fires into the bear trap!
    assert feat_p15["path_a_ok"].iloc[221:].any()
    res_p15 = rmc.simulate_cycle_strategy("BTC/USDT", feat_p15, "Cycle_PD_1d", start_idx=60, slippage_bps=5.0)
    assert any(p.entry_type == "BEAR_BOTTOM" for p in res_p15["closed_positions"])

    # Phase 1.6 Path A_v16 (and B/C) strictly BLOCK the bear trap!
    assert not feat_v16["path_a_v16_ok"].iloc[60:].any()
    assert not feat_v16["path_b_v16_ok"].iloc[60:].any()
    assert not feat_v16["path_c_v16_ok"].iloc[60:].any()
    for var in ("Cycle_P_v16_1d", "Cycle_PD_v16_1d"):
        res_v16 = v16.simulate_cycle_v16_strategy("BTC/USDT", feat_v16, var, start_idx=60, slippage_bps=5.0)
        assert len(res_v16["closed_positions"]) == 0


# ─── 4. Early-Bull Hold Regression Test (Mayer < 1.55) ────────────────────────

def test_early_bull_hold_mayer_below_155_does_not_trigger_euphoria_top():
    """
    +35% early-bull rally with low ATR & Mayer Multiple = 1.25 < 1.55 followed by a 20d low break
    (while staying above EMA50) MUST NOT prematurely trigger EUPHORIA_TOP_V16.
    """
    t0 = _utc_ts(2024, 1, 1, 16)
    closes: List[float] = []
    # Bars 0..179: base at 100 (EMA200 = 100)
    for _ in range(180):
        closes.append(100.0)
    # Bars 180..199: quiet early-bull ignition 100 -> 106 (Path C triggers above 60d high)
    for i in range(20):
        closes.append(100.0 + 6.0 * (i + 1) / 20.0)
    # Bars 200..209: climb 106 -> 127 (EMA50 lags way behind ~109)
    for i in range(10):
        closes.append(106.0 + 21.0 * (i + 1) / 10.0)
    # Bars 210..219: tight shelf 127..127.5 (raises 20d low near ~126 while EMA50 ~115)
    for i in range(10):
        closes.append(127.0 + 0.2 * (i % 2))
    # Bars 220..226: low-ATR burst 127 -> 137 (Mayer ~1.28 < 1.55, RSI >= 76, high_ext/ATR >= 5.5)
    for i in range(7):
        closes.append(127.0 + 10.0 * (i + 1) / 7.0)
    # Bars 227..230: pullback breaking 20d low (~124) & EMA20 (~128) to 122.0, staying strictly ABOVE EMA50 (~118)
    for i in range(4):
        closes.append(137.0 - 15.0 * (i + 1) / 4.0)
    # Bars 231..265: secular bull continuation 122 -> 152
    for i in range(35):
        closes.append(122.0 + 30.0 * (i + 1) / 35.0)

    df = _make_df_from_closes(t0, closes, high_mult=1.003, low_mult=0.997, has_deriv=False)
    feat = v16.evaluate_cycle_v16_features_1d(df)

    # Confirm Mayer Multiple at rally peak (bar 226) is ~1.25 < 1.55 while RSI >= 76,
    # pullback breaks < EMA20 & < 20d low while staying > EMA50, and euphoria_price_30d_v16 is False!
    mayer_peak = float(feat["high"].iloc[226] / feat["ema200"].iloc[226])
    assert 1.18 <= mayer_peak <= 1.35
    assert float(feat["rsi14"].iloc[226]) >= 76.0
    assert (feat["close"].iloc[227:231] > feat["ema50"].iloc[227:231]).all()
    assert feat["euphoria_breakdown_right_v16"].iloc[227:231].any()
    assert not feat["euphoria_price_30d_v16"].iloc[227:231].any()

    for var in ("Cycle_P_v16_1d", "Cycle_PD_v16_1d"):
        res = v16.simulate_cycle_v16_strategy("BTC/USDT", feat, var, start_idx=60, slippage_bps=5.0)
        assert len(res["closed_positions"]) == 1
        pos = res["closed_positions"][0]
        assert pos.entry_type == "STAGE2_IGNITION_V16"
        assert pos.exit_reason == "BACKTEST_END"
        assert pos.realized_pnl > 0.0


# ─── 5. Selective Derivative Washout, Anti-Crowding, Path Priority & Exit Fallback ──

def test_selective_derivative_gates_priority_and_exit_fallbacks():
    t0 = _utc_ts(2024, 1, 1, 16)
    n = 120

    def _base_feat_df() -> pd.DataFrame:
        rows = []
        for i in range(n):
            rows.append({
                "time": t0 + i * 86400,
                "known_ts": t0 + (i + 1) * 86400,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1000.0,
                "atr14": 2.0,
                "low_min_20d": 95.0,
                "path_a_v16_ok": False,
                "path_b_v16_ok": False,
                "path_c_v16_ok": False,
                "has_washout_deriv_60d": False,
                "deriv_washout_60d": False,
                "has_washout_deriv_35d": False,
                "deriv_washout_35d": False,
                "deriv_not_crowded_c": True,
                "euphoria_price_30d_v16": False,
                "has_exit_deriv_30d_v16": False,
                "deriv_overheated_30d_v16": False,
                "extreme_blowoff_30d_v16": False,
                "euphoria_breakdown_right_v16": False,
                "regime_bear_exit_v16": False,
            })
        return pd.DataFrame(rows)

    # Case 1: Path A fails washout gate while Path C passes anti-crowding gate:
    # Cycle_P_v16_1d enters BEAR_BOTTOM_V16; Cycle_PD_v16_1d STILL evaluates Path C -> STAGE2_IGNITION_V16!
    df1 = _base_feat_df()
    df1.loc[65, "path_a_v16_ok"] = True
    df1.loc[65, "path_c_v16_ok"] = True
    df1.loc[65, "has_washout_deriv_60d"] = True
    df1.loc[65, "deriv_washout_60d"] = False
    df1.loc[65, "deriv_not_crowded_c"] = True

    res_p1 = v16.simulate_cycle_v16_strategy("BTC/USDT", df1, "Cycle_P_v16_1d", start_idx=60)
    res_pd1 = v16.simulate_cycle_v16_strategy("BTC/USDT", df1, "Cycle_PD_v16_1d", start_idx=60)
    assert res_p1["closed_positions"][0].entry_type == "BEAR_BOTTOM_V16"
    assert res_pd1["closed_positions"][0].entry_type == "STAGE2_IGNITION_V16"

    # Case 2: Priority BEAR_BOTTOM_V16 > REGIONAL_BOTTOM_V16 > STAGE2_IGNITION_V16
    df2 = _base_feat_df()
    df2.loc[65, ["path_b_v16_ok", "path_c_v16_ok"]] = True
    res_b_over_c = v16.simulate_cycle_v16_strategy("BTC/USDT", df2, "Cycle_PD_v16_1d", start_idx=60)
    assert res_b_over_c["closed_positions"][0].entry_type == "REGIONAL_BOTTOM_V16"

    # Case 3: Path C crowded derivatives (coin_oi_pct_180d >= 85 or fr_pct_180d >= 85) blocked in Cycle_PD_v16_1d
    closes_c = [100.0] * 180 + [100.0 + 0.5 * k for k in range(1, 45)]
    df_crowd = _make_df_from_closes(t0, closes_c, high_mult=1.005, low_mult=0.995, has_deriv=True)
    df_crowd["coin_oi"] = [1_000_000.0 + 1000.0 * k for k in range(len(closes_c))]  # monotonically new 180d highs -> pct=100 >= 85
    df_crowd["funding_daily"] = [0.0001 + 0.000002 * k for k in range(len(closes_c))]
    feat_crowd = v16.evaluate_cycle_v16_features_1d(df_crowd)
    assert feat_crowd["path_c_v16_ok"].iloc[180:].any()
    assert not feat_crowd["deriv_not_crowded_c"].iloc[180:].any()
    r_p_crowd = v16.simulate_cycle_v16_strategy("BTC/USDT", feat_crowd, "Cycle_P_v16_1d", start_idx=60)
    r_pd_crowd = v16.simulate_cycle_v16_strategy("BTC/USDT", feat_crowd, "Cycle_PD_v16_1d", start_idx=60)
    assert len(r_p_crowd["closed_positions"]) == 1
    assert len(r_pd_crowd["closed_positions"]) == 0

    # Case 4: Exit 1_v16 Euphoria behavior:
    #   4a) FR & LSUR both NaN (only coin_oi present + early 0.0 OI) -> has_exit_deriv_30d_v16 False -> falls back to pure price
    #   4b) coin_oi_pct_180d + fr_7d_mean present (even without fr_pct_180d/lsur) -> exit_deriv_evaluable_bar_v16 True!
    #   4c) Cool derivatives block moderate euphoria (1.8x Mayer < 2.0), whereas >= 2.0x Mayer & RSI >= 80 triggers extreme blowoff
    closes_euph: List[float] = []
    for _ in range(180):
        closes_euph.append(100.0)
    for i in range(25):
        closes_euph.append(100.0 + 8.0 * (i + 1) / 25.0)  # 180..204: slow climb -> Path C entry ~102
    for i in range(15):
        closes_euph.append(108.0 + 47.0 * (i + 1) / 15.0)  # 205..219: climb to 155
    for i in range(15):
        closes_euph.append(155.0 + 0.5 * (i % 2))  # 220..234: plateau ~155 -> raises 20d low to ~150
    for i in range(10):
        closes_euph.append(155.0 + 60.0 * (i + 1) / 10.0)  # 235..244: surge to 215 (Mayer ~1.80 >= 1.55, < 2.0)
    for i in range(6):
        closes_euph.append(215.0 - 70.0 * (i + 1) / 6.0)  # 245..250: breakdown to 145 (< ema20 & < 20d low ~150, while ema20 > ema50)

    df_e_part = _make_df_from_closes(t0, closes_euph, high_mult=1.01, low_mult=0.99, has_deriv=True)
    df_e_part["coin_oi"] = 1_500_000.0
    df_e_part.loc[0:30, "coin_oi"] = 0.0  # guard 0.0 OI with zero warnings
    df_e_part.loc[150:215, "coin_oi"] = 900_000.0  # low OI during Path C entry (~bar 185..204)
    df_e_part.loc[230:, "coin_oi"] = 2_200_000.0  # high OI during top
    df_e_part["lsur_z_90d"] = float("nan")
    df_e_part["funding_daily"] = float("nan")

    with warnings.catch_warnings(record=True) as w_part:
        warnings.simplefilter("error")
        feat_e_part = v16.evaluate_cycle_v16_features_1d(df_e_part)
    assert len(w_part) == 0
    assert not feat_e_part["has_exit_deriv_30d_v16"].any()
    r_pd_part = v16.simulate_cycle_v16_strategy("BTC/USDT", feat_e_part, "Cycle_PD_v16_1d", start_idx=60)
    assert any(p.exit_reason == "EUPHORIA_TOP_V16" for p in r_pd_part["closed_positions"])

    # Cool derivatives with fr_7d_mean present (< 0.00020) and Mayer < 2.0 -> holds past EUPHORIA_TOP_V16!
    df_e_cool = df_e_part.copy()
    df_e_cool.loc[230:, "coin_oi"] = 650_000.0
    df_e_cool.loc[230:, "funding_daily"] = 0.00001  # only 21 bars (< 45 for fr_pct_180d, so fr_7d_mean activates evaluable!)
    feat_e_cool = v16.evaluate_cycle_v16_features_1d(df_e_cool)
    assert feat_e_cool["has_exit_deriv_30d_v16"].iloc[-6:].any()
    assert not feat_e_cool["deriv_overheated_30d_v16"].iloc[-6:].any()
    assert not feat_e_cool["extreme_blowoff_30d_v16"].iloc[-6:].any()
    r_pd_cool = v16.simulate_cycle_v16_strategy("BTC/USDT", feat_e_cool, "Cycle_PD_v16_1d", start_idx=60)
    assert all(p.exit_reason != "EUPHORIA_TOP_V16" for p in r_pd_cool["closed_positions"])

    # Hot fr_7d_mean >= 0.00020 + coin_oi_pct_180d >= 80 -> exits EUPHORIA_TOP_V16!
    df_e_hot = df_e_cool.copy()
    df_e_hot.loc[230:, "coin_oi"] = 2_200_000.0
    df_e_hot.loc[230:, "funding_daily"] = 0.00025
    feat_e_hot = v16.evaluate_cycle_v16_features_1d(df_e_hot)
    r_pd_hot = v16.simulate_cycle_v16_strategy("BTC/USDT", feat_e_hot, "Cycle_PD_v16_1d", start_idx=60)
    assert any(p.exit_reason == "EUPHORIA_TOP_V16" for p in r_pd_hot["closed_positions"])

    # Cool derivatives BUT extreme blowoff (Mayer >= 2.0 & RSI >= 80) -> STILL exits EUPHORIA_TOP_V16!
    closes_blow = list(closes_euph[:235]) + [155.0 + 135.0 * (i + 1) / 10.0 for i in range(10)]
    peak_b = closes_blow[-1]
    closes_blow += [peak_b - (peak_b - 145.0) * (i + 1) / 6.0 for i in range(6)]
    df_blow = _make_df_from_closes(t0, closes_blow, high_mult=1.01, low_mult=0.99, has_deriv=True)
    df_blow["coin_oi"] = 1_500_000.0
    df_blow.loc[150:215, "coin_oi"] = 900_000.0
    df_blow.loc[230:, "coin_oi"] = 650_000.0
    df_blow.loc[230:, "funding_daily"] = 0.00001
    feat_blow = v16.evaluate_cycle_v16_features_1d(df_blow)
    assert feat_blow["extreme_blowoff_30d_v16"].iloc[-6:].any()
    r_pd_blow = v16.simulate_cycle_v16_strategy("BTC/USDT", feat_blow, "Cycle_PD_v16_1d", start_idx=60)
    assert any(p.exit_reason == "EUPHORIA_TOP_V16" for p in r_pd_blow["closed_positions"])

    # Case 5: Path B washout gate (W=35):
    # Without washout -> Cycle_PD_v16_1d blocks Path B; with fr_7d_mean < 0 or lsur_z_90d <= -1.3 -> enters!
    df_b_nowash = _base_feat_df()
    df_b_nowash.loc[70, "path_b_v16_ok"] = True
    df_b_nowash.loc[70, "has_washout_deriv_35d"] = True
    df_b_nowash.loc[70, "deriv_washout_35d"] = False
    assert len(v16.simulate_cycle_v16_strategy("BTC/USDT", df_b_nowash, "Cycle_P_v16_1d", start_idx=60)["closed_positions"]) == 1
    assert len(v16.simulate_cycle_v16_strategy("BTC/USDT", df_b_nowash, "Cycle_PD_v16_1d", start_idx=60)["closed_positions"]) == 0
    df_b_wash = df_b_nowash.copy()
    df_b_wash.loc[70, "deriv_washout_35d"] = True
    res_b_wash = v16.simulate_cycle_v16_strategy("BTC/USDT", df_b_wash, "Cycle_PD_v16_1d", start_idx=60)
    assert res_b_wash["closed_positions"][0].entry_type == "REGIONAL_BOTTOM_V16"


# ─── 6. BASE_INVALIDATION_V16, Cooldown, Conservative Legacy & Zero-ATR Safety ─

def test_base_invalidation_v16_threshold_cooldown_and_zero_atr_safety():
    t0 = _utc_ts(2024, 1, 1, 16)
    n = 100
    rows = []
    for i in range(n):
        rows.append({
            "time": t0 + i * 86400,
            "known_ts": t0 + (i + 1) * 86400,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1000.0,
            "atr14": 2.0,
            "low_min_20d": 95.0,
            "path_a_v16_ok": False,
            "path_b_v16_ok": False,
            "path_c_v16_ok": False,
            "has_washout_deriv_60d": False,
            "deriv_washout_60d": False,
            "has_washout_deriv_35d": False,
            "deriv_washout_35d": False,
            "deriv_not_crowded_c": True,
            "euphoria_price_30d_v16": False,
            "has_exit_deriv_30d_v16": False,
            "deriv_overheated_30d_v16": False,
            "extreme_blowoff_30d_v16": False,
            "euphoria_breakdown_right_v16": False,
            "regime_bear_exit_v16": False,
        })
    df_feat = pd.DataFrame(rows)

    # Case A: entry=100, atr=2, low20=95 -> base_stop = max(100 - 3.0*2, 95*0.98) = 94.0.
    # Bar 22 hits 122 (< 1.25*100) so base_stop MUST REMAIN ACTIVE!
    # Bar 24 spikes to 128 (>= 1.25) AND drops to 92 (<= 94) -> pre-bar highest=122 < 125 -> BASE_INVALIDATION_V16!
    df_a = df_feat.copy()
    df_a.loc[20, "path_a_v16_ok"] = True
    df_a.loc[22, ["open", "high", "low", "close"]] = [101.0, 122.0, 100.0, 118.0]
    df_a.loc[24, ["open", "high", "low", "close"]] = [102.0, 128.0, 92.0, 93.0]
    df_a.loc[29, "path_a_v16_ok"] = True  # blocked by 10d cooldown (29 - 24 = 5 < 10)
    df_a.loc[34, "path_a_v16_ok"] = True  # allowed (34 - 24 = 10 >= 10)

    res_a = v16.simulate_cycle_v16_strategy("BTC/USDT", df_a, "Cycle_P_v16_1d", start_idx=10, slippage_bps=0.0)
    assert len(res_a["closed_positions"]) == 2
    assert res_a["closed_positions"][0].exit_reason == "BASE_INVALIDATION_V16"
    assert res_a["closed_positions"][0].exit_idx == 24
    assert res_a["closed_positions"][1].entry_idx == 34

    # Case B: Bar 22 hits high=126 (>= 1.25*100) cleanly without hitting 94 -> permanently disables base_stop!
    df_b = df_feat.copy()
    df_b.loc[20, "path_a_v16_ok"] = True
    df_b.loc[22, ["open", "high", "low", "close"]] = [102.0, 126.0, 101.0, 120.0]
    df_b.loc[25, ["open", "high", "low", "close"]] = [105.0, 106.0, 90.0, 104.0]
    res_b = v16.simulate_cycle_v16_strategy("BTC/USDT", df_b, "Cycle_PD_v16_1d", start_idx=10, slippage_bps=5.0)
    assert len(res_b["closed_positions"]) == 1
    assert res_b["closed_positions"][0].exit_reason == "BACKTEST_END"
    assert res_b["closed_positions"][0].base_stop_disabled is True
    assert abs((res_b["metrics"]["final_balance"] - 10000.0) - sum(p.realized_pnl for p in res_b["closed_positions"])) < 1e-2

    # Case C: Completely flat candles (high == low == close, ATR == 0.0) must emit ZERO RuntimeWarnings
    df_flat = _make_df_from_closes(t0, [100.0] * 100, high_mult=1.0, low_mult=1.0, has_deriv=False)
    with warnings.catch_warnings(record=True) as w_flat:
        warnings.simplefilter("error")
        feat_flat = v16.evaluate_cycle_v16_features_1d(df_flat)
        res_flat = v16.simulate_cycle_v16_strategy("BTC/USDT", feat_flat, "Cycle_PD_v16_1d", start_idx=40)
    assert len(w_flat) == 0
    assert len(res_flat["closed_positions"]) == 0


def test_path_b_regional_bottom_and_regime_bear_exit_on_ohlcv():
    """
    End-to-end OHLCV behavioral check for:
      - Path B_v16 (REGIONAL_BOTTOM_V16) in a secular bull trend (EMA50 > EMA200, rising EMA200)
      - Exit 2_v16 (REGIME_BEAR_EXIT_V16) on secular bear breakdown
    """
    t0 = _utc_ts(2023, 1, 1, 16)
    closes: List[float] = []
    # 0..179: base at 100.0
    for _ in range(180):
        closes.append(100.0)
    # 180..279: steady secular bull climb 100 -> 170 (EMA50 > EMA200, EMA200 > EMA200[20d ago])
    for i in range(100):
        closes.append(100.0 + 70.0 * (i + 1) / 100.0)
    # 280..299: -22% bull regional pullback 170 -> 132 (breaks below EMA50, dd_90 >= ~22%, RSI <= 42)
    for i in range(20):
        closes.append(170.0 - 38.0 * (i + 1) / 20.0)
    # 300..314: hold base at 132..135 so 20d high settles while EMA200 stays rising & EMA50 > EMA200
    for i in range(15):
        closes.append(132.0 + 0.2 * i)
    # 315..329: resumption rally 135 -> 168 (crosses > EMA50, EMA20 >= EMA50*0.995, > 20d high -> REGIONAL_BOTTOM_V16!)
    for i in range(15):
        closes.append(135.0 + 33.0 * (i + 1) / 15.0)
    # 330..379: healthy oscillating bull leg 168 -> ~215 (disables BASE_INVALIDATION >= +25%, RSI < 76)
    px = 168.0
    for i in range(50):
        px = px * (1.016 if (i % 3 != 2) else 0.985)
        closes.append(px)
    # 380..449: secular bear breakdown peak -> 95 (< EMA50, EMA20 < EMA50, < 30d low, < EMA200 -> REGIME_BEAR_EXIT_V16!)
    top_px = closes[-1]
    for i in range(70):
        closes.append(max(95.0, top_px - (top_px - 95.0) * (i + 1) / 60.0))

    df = _make_df_from_closes(t0, closes, high_mult=1.01, low_mult=0.99, has_deriv=False)
    feat = v16.evaluate_cycle_v16_features_1d(df)

    assert feat["path_b_v16_ok"].iloc[315:335].any()
    assert feat["regime_bear_exit_v16"].iloc[335:].any()

    # Run starting at bar 275 (after initial Path C window) to cleanly isolate Path B entry & Bear exit
    res = v16.simulate_cycle_v16_strategy("BTC/USDT", feat, "Cycle_PD_v16_1d", start_idx=275, slippage_bps=5.0)
    assert len(res["closed_positions"]) >= 1
    first_pos = res["closed_positions"][0]
    assert first_pos.entry_type == "REGIONAL_BOTTOM_V16"
    assert first_pos.exit_reason == "REGIME_BEAR_EXIT_V16"


def test_legacy_conservative_slice_uses_conservative_trailing_mode():
    """Verify run_legacy_conservative_slice configures trailing_path_mode='conservative'."""
    t0 = _utc_ts(2024, 1, 1, 16)
    # Construct candles where bar 1 enters long at 100.0 (BTC 1d profile: act=2.8%, trail=1.1%, tp=6.5%, sl=5.0%)
    # and bar 2 opens=100, high=104 (+4% >= 2.8% activation), low=98, close=103.5.
    # Under 'ohlc', close=103.5 > 104*(1-0.011)=102.856 -> holds; under 'conservative', low=98 <= 102.856 -> exits trailing!
    candles = [
        {"time": t0, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1000.0},
        {"time": t0 + 86400, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1000.0},
        {"time": t0 + 2 * 86400, "open": 100.0, "high": 104.0, "low": 98.0, "close": 103.5, "volume": 1000.0},
        {"time": t0 + 3 * 86400, "open": 103.5, "high": 104.5, "low": 103.0, "close": 104.0, "volume": 1000.0},
    ]
    ds_stub = {"symbol": "BTC/USDT", "eval_price": candles, "all_funding_settlements": []}
    sigs = [{"time": t0 + 86400, "direction": "bullish", "score": 4.0}]
    res_cons = v16.run_legacy_conservative_slice(ds_stub, sigs, slippage_bps=5.0)
    assert len(res_cons["closed_positions"]) == 1
    assert res_cons["closed_positions"][0].exit_reason == "trailing"
    assert res_cons["closed_positions"][0].exit_time == t0 + 2 * 86400


# ─── 7. AST Guard & End-to-End Synthetic Mode Check ───────────────────────────

def test_no_bfill_or_inplace_in_macro_cycle_v16_script():
    script_path = Path(v16.__file__).resolve()
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


def test_end_to_end_v16_synthetic_mode_no_warnings(tmp_path: Path):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("error")
        warnings.filterwarnings("ignore", category=Warning, module=r"^api\.")
        summary = v16.run_all_cycle_v16_experiments(mode="synthetic", output_dir=tmp_path)

    assert len(caught) == 0
    md_path = Path(summary["md_path"])
    json_path = Path(summary["json_path"])
    assert md_path.exists()
    assert json_path.exists()
    assert md_path.name == "macro_cycle_v16_report.md"
    assert json_path.name == "macro_cycle_v16_report.json"

    parsed = json.loads(json_path.read_text(encoding="utf-8"))
    json.dumps(parsed, allow_nan=False)

    assert len(parsed["section0_inventory"]) == 5
    assert all(inv["warmup_bars"] == 60 for inv in parsed["section0_inventory"])

    s1_vars = {r["variant"] for r in parsed["section1_forward_pooled"]}
    assert s1_vars == {
        "Legacy_v8_1d (Bull)",
        "Phase15_Cycle_PD_1d",
        "Cycle_P_v16_1d",
        "Cycle_PD_v16_1d",
    }

    boot_keys = {(r["scope"], r["window"], r["variant_a"], r["variant_b"]) for r in parsed["section1_bootstrap"]}
    assert ("POOLED", "Full_Cycle", "Cycle_PD_v16_1d", "Cycle_P_v16_1d") in boot_keys
    assert ("POOLED", "Post2023_07_HasDeriv", "Cycle_PD_v16_1d", "Cycle_P_v16_1d") in boot_keys
    assert ("POOLED", "Post2023_07_HasDeriv", "Cycle_PD_v16_1d", "Phase15_Cycle_PD_1d") in boot_keys

    assert len(parsed["section2_backtest_pooled"]) == 10  # 5 variants x 2 slippage levels
    assert len(parsed["section2_cycle_p_v16_trade_log"]) > 0
    assert len(parsed["section2_cycle_pd_v16_trade_log"]) > 0
    assert len(parsed["section3_walkforward_pooled"]) == 5
    assert len(parsed["section3_walkforward_per_coin"]) == 25
    assert len(parsed["section4_verdict"]["checks"]) == 5

    # Verify all 5 variants evaluate over identical eval_price slice (identical days per coin)
    for sym in v16.SYMBOLS:
        days_set = {
            r["days"]
            for r in parsed["section2_backtest_per_coin"]
            if r["symbol"] == sym and r["slippage_bps"] == 5.0
        }
        assert len(days_set) == 1

    md_text = md_path.read_text(encoding="utf-8")
    assert "## 0. Full-Cycle Dataset C Inventory" in md_text
    assert "## 1. Long-Horizon Bottom Entry Forward Quality" in md_text
    assert "## 2. Full-Cycle Portfolio Backtest" in md_text
    assert "### 2.3 Complete Trade-by-Trade Cycle Log Table (`Cycle_P_v16_1d`, `5 bps`)" in md_text
    assert "### 2.4 Complete Trade-by-Trade Cycle Log Table (`Cycle_PD_v16_1d`, `5 bps`)" in md_text
    assert "## 3. Chronological `60% IS` vs `40% OOS` Blind Walk-Forward" in md_text
    assert "IS EW MAR" in md_text
    assert "OOS EW MAR" in md_text
    assert "## 4. Automated Objective Falsification & Viability Verdict (`H1..H5`)" in md_text


def test_evaluate_v16_washout_thresholds_path_fallback_and_input_guards():
    """
    Verify:
      1) evaluate_cycle_v16_features_1d handles missing taker_ratio & NaN has_deriv safely.
      2) simulate_cycle_v16_strategy rejects negative start_idx with ValueError.
      3) Each of the 4 washout_bar_v16 criteria (OI 60d DD <= -20%, OI 180d pct <= 20, FR 7d < 0, LSUR Z <= -1.3)
         works via actual feature computation.
      4) End-to-end Path A_v16 blocked by missing washout while Path C_v16 passes anti-crowding
         enters STAGE2_IGNITION_V16 in Cycle_PD_v16_1d (vs BEAR_BOTTOM_V16 in Cycle_P_v16_1d).
    """
    t0 = _utc_ts(2024, 1, 1, 16)
    n_guard = 70
    df_guard = _make_df_from_closes(t0, [100.0] * n_guard, has_deriv=False).drop(columns=["taker_ratio"])
    df_guard["has_deriv"] = float("nan")
    feat_guard = v16.evaluate_cycle_v16_features_1d(df_guard)
    assert not feat_guard["has_deriv"].any()

    with pytest.raises(ValueError, match="start_idx must be >= 0"):
        v16.simulate_cycle_v16_strategy("BTC/USDT", feat_guard, "Cycle_P_v16_1d", start_idx=-1)

    # Check all 4 washout triggers through evaluate_cycle_v16_features_1d
    n_w = 190
    base_df = _make_df_from_closes(t0, [100.0] * n_w, has_deriv=True)
    # Neutral baseline: gradual upward OI so pct > 20, no drawdown, positive FR, neutral LSUR
    base_df["coin_oi"] = [1_000_000.0 + 1000.0 * k for k in range(n_w)]
    base_df["funding_daily"] = 0.0001
    base_df["lsur_z_90d"] = 0.0
    feat_none = v16.evaluate_cycle_v16_features_1d(base_df)
    assert feat_none["washout_evaluable_bar_v16"].iloc[-1]
    assert not feat_none["washout_bar_v16"].iloc[-1]

    # (a) coin_oi_dd_60d <= -20%
    df_oi_dd = base_df.copy()
    df_oi_dd.loc[n_w - 1, "coin_oi"] = df_oi_dd.loc[n_w - 2, "coin_oi"] * 0.78
    assert v16.evaluate_cycle_v16_features_1d(df_oi_dd)["washout_bar_v16"].iloc[-1]

    # (b) coin_oi_pct_180d <= 20% (with < 20% 60d drawdown by stepping down gently then reaching new 180d low)
    df_oi_pct = base_df.copy()
    df_oi_pct.loc[0 : n_w - 70, "coin_oi"] = 2_000_000.0
    df_oi_pct.loc[n_w - 70 : n_w - 2, "coin_oi"] = 1_800_000.0
    df_oi_pct.loc[n_w - 1, "coin_oi"] = 1_750_000.0  # only -2.8% 60d DD (> -20%), <= 20th pct over 180d!
    feat_oi_pct = v16.evaluate_cycle_v16_features_1d(df_oi_pct)
    assert feat_oi_pct["coin_oi_dd_60d"].iloc[-1] > -20.0
    assert feat_oi_pct["coin_oi_pct_180d"].iloc[-1] <= 20.0
    assert feat_oi_pct["washout_bar_v16"].iloc[-1]

    # (c) fr_7d_mean < 0.0
    df_fr = base_df.copy()
    df_fr.loc[n_w - 7 :, "funding_daily"] = -0.00005
    assert v16.evaluate_cycle_v16_features_1d(df_fr)["washout_bar_v16"].iloc[-1]

    # (d) lsur_z_90d <= -1.3
    df_ls = base_df.copy()
    df_ls.loc[n_w - 1, "lsur_z_90d"] = -1.35
    assert v16.evaluate_cycle_v16_features_1d(df_ls)["washout_bar_v16"].iloc[-1]

    # End-to-end OHLCV where Path A_v16 AND Path C_v16 both pass price,
    # OI stays mid-range (no washout, not crowded) -> Cycle_P enters BEAR_BOTTOM_V16, Cycle_PD enters STAGE2_IGNITION_V16!
    closes_ac: List[float] = []
    for _ in range(120):
        closes_ac.append(150.0)
    for i in range(30):
        closes_ac.append(150.0 - 65.0 * (i + 1) / 30.0)  # crash to 85 (dd_180 >= 0.43, RSI <= 33)
    for i in range(60):
        closes_ac.append(85.0 + 85.0 * (i + 1) / 60.0)  # secular recovery 85 -> 170 (EMA20>EMA50>EMA200, >60d high, EMA200 rising)
    df_ac = _make_df_from_closes(t0, closes_ac, high_mult=1.005, low_mult=0.995, has_deriv=True)
    # OI stays in ~72nd percentile (20 < pct < 85) with -8.7% DD (> -20%) -> no washout, not crowded!
    df_ac["coin_oi"] = 1_000_000.0
    df_ac.loc[100:149, "coin_oi"] = 1_150_000.0
    df_ac.loc[150:, "coin_oi"] = 1_050_000.0
    df_ac["funding_daily"] = 0.00005
    df_ac["lsur_z_90d"] = 0.0
    feat_ac = v16.evaluate_cycle_v16_features_1d(df_ac)

    both_mask = feat_ac["path_a_v16_ok"] & feat_ac["path_c_v16_ok"]
    assert both_mask.iloc[150:].any()
    first_both = int(np.where(both_mask)[0][0])
    assert feat_ac["has_washout_deriv_60d"].iloc[first_both]
    assert not feat_ac["deriv_washout_60d"].iloc[first_both]
    assert feat_ac["deriv_not_crowded_c"].iloc[first_both]
    res_p_ac = v16.simulate_cycle_v16_strategy("BTC/USDT", feat_ac, "Cycle_P_v16_1d", start_idx=first_both)
    res_pd_ac = v16.simulate_cycle_v16_strategy("BTC/USDT", feat_ac, "Cycle_PD_v16_1d", start_idx=first_both)
    assert res_p_ac["closed_positions"][0].entry_type == "BEAR_BOTTOM_V16"
    assert res_pd_ac["closed_positions"][0].entry_type == "STAGE2_IGNITION_V16"
