"""
Unit, behavioral, causality, and end-to-end verification tests for Phase 1.5 Macro Cycle Prototype
(scripts/run_macro_cycle_experiments.py):
  1. Dataset C keeps ALL deduplicated OKX 1d OHLCV bars from DB start + causal known_ts + has_deriv flag
  2. Strict prefix-truncation invariance (0..k vs 0..N produces identical entries, exits, and state
     for Cycle_P_1d, Cycle_PD_1d, and Cycle_PD_BearShort_1d)
  3. Behavioral verification:
     - Normal -18% bull pullback above EMA50_1d after +40% gain does NOT exit
     - EUPHORIA_TOP distribution breakdown & extreme blow-off exit cleanly (and deriv overheat gating)
     - REGIME_BEAR_EXIT & Cycle_PD_BearShort_1d 0.50x bear short + SHORT_COVER / SHORT_STOP
     - BASE_INVALIDATION stops losing early entries before +20% and disables permanently >= +20%
     - Derivative Washout Gate + pre-2023-07 fallback + 10-day post-exit cooldown + PnL conservation
  4. AST guard against .bfill(), method='bfill', and inplace=True
  5. End-to-end --mode synthetic run under -W error (filtering only untouched ^api.)
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


# ─── 1. Dataset C Full History Retention & Causal Alignment ────────────────────

def test_dataset_c_keeps_all_okx_1d_bars_and_causal_has_deriv():
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

        # Simulate BTC from 2022-05-22 16:00 UTC (600 bars); derivatives start ONLY at bar 400!
        start_okx = _utc_ts(2022, 5, 22, 16)
        n_days = 600
        deriv_start = 400
        target_idx = 480
        t_okx_target = start_okx + target_idx * 86400
        t_bin_next = t_okx_target + 28800  # Day D+1 00:00 UTC -> known at D+2 00:00 > D+1 16:00

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
                    t_b = t_c - 57600  # 00:00 UTC same UTC day (known D+1 00:00 <= D+1 16:00)
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
            # Future Binance spike on Day D+1 00:00 UTC must NOT leak into Day D 16:00 UTC
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
            # Funding in dual formats starting at bar 500
            for i in range(500, n_days):
                t_c = start_okx + i * 86400
                fmt = "BTC/USDT:USDT" if i < 550 else "BTC-USDT-SWAP"
                db.add(FundingRate(exchange="okx", symbol=fmt, timestamp=_utc_dt(t_c), funding_rate=0.0001))
            db.commit()

        ds_map = rmc.load_dataset_c_from_db(["BTC/USDT"], session_factory=session_factory)
        ds = ds_map["BTC/USDT"]
        assert ds["valid"] is True
        # Keeps ALL 600 bars from 2022-05-22 (NO truncation to deriv_start!)
        assert ds["total_bars"] == 600
        assert ds["clean_start"] == start_okx
        assert ds["warmup_bars"] == 120
        assert ds["clean_bars"] == 480

        df = ds["df_1d"]
        assert not df["has_deriv"].iloc[:deriv_start].any()
        assert df["has_deriv"].iloc[deriv_start:].all()

        row_d = df.loc[df["time"] == t_okx_target].iloc[0]
        row_d1 = df.loc[df["time"] == (t_okx_target + 86400)].iloc[0]
        assert row_d["taker_ratio"] == pytest.approx(0.50, abs=1e-9)
        assert row_d["oi_usd"] == pytest.approx(5e8, abs=1e-3)
        assert row_d1["taker_ratio"] == pytest.approx(0.95, abs=1e-9)
        assert row_d1["oi_usd"] == pytest.approx(9e9, abs=1e-3)

        # Verify short-history coin (CC 386 bars -> warmup_bars = min(120, max(50, 386 // 5)) == 77)
        # and overlapping OKX 1d bar deduplication (< 43200s keeps newer bar)
        cc_raw = [
            {
                "time": start_okx + i * 86400,
                "open": 0.08,
                "high": 0.09,
                "low": 0.07,
                "close": 0.085,
                "volume": 1000.0,
            }
            for i in range(386)
        ]
        # Inject overlapping duplicate bar +6h after bar 10 with distinct close
        cc_raw.append({
            "time": start_okx + 10 * 86400 + 21600,
            "open": 0.08,
            "high": 0.10,
            "low": 0.07,
            "close": 0.095,
            "volume": 1500.0,
        })
        ds_cc = rmc.build_dataset_c_from_raw("CC/USDT", cc_raw, {"okx": [], "binance": []}, [])
        assert ds_cc["valid"] is True
        assert ds_cc["total_bars"] == 386
        assert ds_cc["warmup_bars"] == 77
        assert ds_cc["clean_bars"] == 309
        assert ds_cc["df_1d"].iloc[10]["close"] == pytest.approx(0.095)
    finally:
        engine.dispose()


# ─── 2. Strict Prefix-Truncation Invariance (0..k vs 0..N) ─────────────────────

def test_prefix_truncation_invariance_cycle_p_pd_and_bearshort():
    """
    Truncating raw streams at bar k (0..k) vs full 0..N must produce IDENTICAL:
      - all feature columns at 0..k-1
      - all entry signals & entry types up to t_cut
      - all closed exits (excluding terminal BACKTEST_END) up to t_cut
      - open position state at bar k-1 ('FLAT' | 'LONG' | 'SHORT')
    for Cycle_P_1d, Cycle_PD_1d, and Cycle_PD_BearShort_1d.
    """
    ds_full_map = rmc.make_synthetic_cycle_datasets(["BTC/USDT", "ETH/USDT"], seed=2026)

    for sym in ("BTC/USDT", "ETH/USDT"):
        ds_full = ds_full_map[sym]
        df_full = ds_full["df_1d"]
        feat_full = rmc.evaluate_cycle_features_1d(df_full)

        # Feature truncation invariance across early cut (k=280) and late cut (k=len-250)
        for cut_k in (280, len(df_full) - 250):
            assert cut_k > 200
            feat_pref = rmc.evaluate_cycle_features_1d(df_full.iloc[:cut_k].copy())
            for col in (
                "ema20", "ema50", "ema200", "atr14", "rsi14", "atr_pct_median60",
                "coin_oi_dd_60d", "coin_oi_pct_180d", "fr_7d_mean", "fr_pct_180d",
            ):
                np.testing.assert_allclose(
                    feat_pref[col].to_numpy(dtype=float),
                    feat_full[col].iloc[:cut_k].to_numpy(dtype=float),
                    rtol=1e-12,
                    atol=1e-12,
                    equal_nan=True,
                )
            for bcol in (
                "has_deriv", "path_a_ok", "path_b_ok", "has_washout_deriv_30d", "deriv_washout_30d",
                "euphoria_price_30d", "deriv_overheated_30d", "extreme_blowoff_30d",
                "euphoria_breakdown_right", "regime_bear_exit", "bear_short_entry", "bear_short_cover",
            ):
                assert list(feat_pref[bcol]) == list(feat_full[bcol].iloc[:cut_k])

        # Full-pipeline signal/entry/exit/state truncation invariance using shared warmup=120
        # Check across multiple cut points covering pre-deriv, bull run, top, and bear crash!
        warmup = int(ds_full["warmup_bars"])
        t_all = feat_full["time"].to_numpy(dtype=int)
        for cut_k in (650, len(feat_full) - 260, len(feat_full) - 80):
            assert cut_k >= 600  # Ensures min(120, max(50, cut_k // 5)) == 120 identically
            t_cut = int(t_all[cut_k - 1])
            t_cut_known = t_cut + 86400
            funding_pref = [f for f in ds_full["all_funding_settlements"] if int(f["time"]) <= t_cut_known]

            # Rebuild df_1d from truncated raw streams directly via build_dataset_c_from_raw
            raw_candles_pref = [c for c in ds_full["price_with_warmup"] if int(c["time"]) <= t_cut]
            assert len(raw_candles_pref) == cut_k
            df_raw_src = df_full.iloc[:cut_k]
            okx_1d_pref = [
                {
                    "time": int(r["time"]),
                    "open_interest": float(r["oi_usd"]) if math.isfinite(r["oi_usd"]) else None,
                    "long_short_ratio": None,
                    "taker_buy_vol": (1000.0 * float(r["taker_ratio"])) if math.isfinite(r["taker_ratio"]) else None,
                    "taker_sell_vol": (1000.0 * (1.0 - float(r["taker_ratio"]))) if math.isfinite(r["taker_ratio"]) else None,
                }
                for _, r in df_raw_src.iterrows()
                if bool(r["has_deriv"])
            ]
            ds_rebuilt_pref = rmc.build_dataset_c_from_raw(sym, raw_candles_pref, {"okx": okx_1d_pref, "binance": []}, funding_pref)
            assert ds_rebuilt_pref["valid"] is True
            assert ds_rebuilt_pref["warmup_bars"] == warmup
            feat_rebuilt_pref = rmc.evaluate_cycle_features_1d(ds_rebuilt_pref["df_1d"])
            for col in ("ema20", "ema50", "ema200", "atr14", "rsi14", "atr_pct_median60", "fr_7d_mean", "fr_pct_180d"):
                np.testing.assert_allclose(
                    feat_rebuilt_pref[col].to_numpy(dtype=float),
                    feat_full[col].iloc[:cut_k].to_numpy(dtype=float),
                    rtol=1e-12,
                    atol=1e-12,
                    equal_nan=True,
                )

            feat_pref = rmc.evaluate_cycle_features_1d(df_full.iloc[:cut_k].copy())

            for var in ("Cycle_P_1d", "Cycle_PD_1d", "Cycle_PD_BearShort_1d"):
                res_full = rmc.simulate_cycle_strategy(
                    sym, feat_full, var, start_idx=warmup,
                    funding_rates=ds_full["all_funding_settlements"], slippage_bps=5.0,
                )
                res_pref = rmc.simulate_cycle_strategy(
                    sym, feat_pref, var, start_idx=warmup,
                    funding_rates=funding_pref, slippage_bps=5.0,
                )

                full_entries_cut = [
                    (int(p.entry_time), p.side, p.entry_type, round(p.entry_price, 8))
                    for p in res_full["closed_positions"]
                    if int(p.entry_time) <= t_cut
                ]
                pref_entries = [
                    (int(p.entry_time), p.side, p.entry_type, round(p.entry_price, 8))
                    for p in res_pref["closed_positions"]
                ]
                assert pref_entries == full_entries_cut

                full_exits_cut = [
                    (int(p.exit_time), p.exit_reason, round(p.exit_price, 8))
                    for p in res_full["closed_positions"]
                    if int(p.exit_time) <= t_cut and p.exit_reason != "BACKTEST_END"
                ]
                pref_exits = [
                    (int(p.exit_time), p.exit_reason, round(p.exit_price, 8))
                    for p in res_pref["closed_positions"]
                    if p.exit_reason != "BACKTEST_END"
                ]
                assert pref_exits == full_exits_cut

                # Verify position state at bar cut_k - 1 matches
                active_in_full_at_cut = [
                    p for p in res_full["closed_positions"]
                    if int(p.entry_time) <= t_cut and int(p.exit_time) > t_cut
                ]
                expected_state = active_in_full_at_cut[0].side.upper() if active_in_full_at_cut else "FLAT"
                assert res_pref["final_state"] == expected_state

    # End-to-end raw-stream truncation invariance test directly on raw OKX/Binance/Funding inputs
    rng = np.random.default_rng(314)
    t_base = _utc_ts(2023, 1, 1, 16)
    n_raw = 700
    raw_ohlcv, raw_okx, raw_bin, raw_fund = [], [], [], []
    px = 20000.0
    for d in range(n_raw):
        t_d = t_base + d * 86400
        drift = 0.004 * math.sin(2.0 * math.pi * d / 160.0)
        c = max(5000.0, px * (1.0 + drift + float(rng.normal(0.0, 0.02))))
        h = max(px, c) * 1.015
        l = min(px, c) * 0.985
        raw_ohlcv.append({"time": t_d, "open": px, "high": h, "low": l, "close": c, "volume": 1e6})
        px = c
        if d >= 180:
            raw_okx.append({
                "time": t_d,
                "open_interest": 5e8 * (1.0 + 0.3 * math.sin(d / 30.0)),
                "long_short_ratio": 1.1 + 0.3 * math.sin(d / 25.0),
                "taker_buy_vol": 5e5,
                "taker_sell_vol": 4.8e5,
            })
            raw_bin.append({
                "time": t_d - 57600,
                "open_interest": 7e8 * (1.0 + 0.3 * math.sin(d / 30.0)),
                "long_short_ratio": 1.2 + 0.3 * math.sin(d / 25.0),
                "taker_buy_vol": 8e5,
                "taker_sell_vol": 7.5e5,
            })
        if d >= 300:
            for off in (0, 28800, 57600):
                raw_fund.append({"time": t_d + off, "funding_rate": 0.0001 + 0.0002 * math.sin(d / 35.0)})

    cut_raw = 620
    t_cut_raw = raw_ohlcv[cut_raw - 1]["time"]
    t_cut_raw_known = t_cut_raw + 86400
    ds_raw_full = rmc.build_dataset_c_from_raw("BTC/USDT", raw_ohlcv, {"okx": raw_okx, "binance": raw_bin}, raw_fund)
    ds_raw_pref = rmc.build_dataset_c_from_raw(
        "BTC/USDT",
        [b for b in raw_ohlcv if b["time"] <= t_cut_raw],
        {
            "okx": [r for r in raw_okx if r["time"] + 86400 <= t_cut_raw_known],
            "binance": [r for r in raw_bin if r["time"] + 86400 <= t_cut_raw_known],
        },
        [f for f in raw_fund if f["time"] <= t_cut_raw_known],
    )
    feat_raw_full = rmc.evaluate_cycle_features_1d(ds_raw_full["df_1d"])
    feat_raw_pref = rmc.evaluate_cycle_features_1d(ds_raw_pref["df_1d"])
    for var in ("Cycle_P_1d", "Cycle_PD_1d", "Cycle_PD_BearShort_1d"):
        rf = rmc.simulate_cycle_strategy("BTC/USDT", feat_raw_full, var, start_idx=120, funding_rates=ds_raw_full["all_funding_settlements"])
        rp = rmc.simulate_cycle_strategy("BTC/USDT", feat_raw_pref, var, start_idx=120, funding_rates=ds_raw_pref["all_funding_settlements"])
        assert [(int(p.entry_time), p.side, p.entry_type) for p in rp["closed_positions"]] == [
            (int(p.entry_time), p.side, p.entry_type) for p in rf["closed_positions"] if int(p.entry_time) <= t_cut_raw
        ]
        assert [
            (int(p.exit_time), p.exit_reason) for p in rp["closed_positions"] if p.exit_reason != "BACKTEST_END"
        ] == [
            (int(p.exit_time), p.exit_reason)
            for p in rf["closed_positions"]
            if int(p.exit_time) <= t_cut_raw and p.exit_reason != "BACKTEST_END"
        ]


# ─── 3. Behavioral Tests: Pullback Holding, Euphoria, Bear Exit, Base Stop ─────

def test_normal_18pct_bull_pullback_above_ema50_does_not_exit():
    """
    A -18% bull pullback above EMA50_1d after a +40% gain MUST NOT trigger
    EUPHORIA_TOP, REGIME_BEAR_EXIT, or BASE_INVALIDATION (hold through bull pullbacks).
    """
    t0 = _utc_ts(2023, 1, 1, 16)
    closes: List[float] = []
    # Bars 0..79: gentle decline 160 -> 100
    for i in range(80):
        closes.append(160.0 - 0.75 * i)
    # Bars 80..119: bear crash bottom 100 -> 62 (RSI <= 34, >38% dd from 160) then flat base at 62
    for i in range(40):
        closes.append(62.0 if i >= 20 else 100.0 - 1.9 * i)
    # Bars 120..145: breakout recovery 62 -> 95 (crosses EMA50 + 20d high -> enters BEAR_BOTTOM!)
    for i in range(26):
        closes.append(62.0 + (95.0 - 62.0) * (i + 1) / 26.0)
    # Bars 146..215: flat oscillating base around ~105 (keeps EMA50 ~ 104, EMA200 catches up)
    px = 95.0
    for i in range(70):
        px = px * (1.011 if (i % 2 == 0) else 0.990)
        closes.append(px)
    # Bars 216..245: healthy oscillating bull leg ~98 -> ~160 (30 bars, RSI < 74, EMA50 lags ~128)
    for i in range(30):
        px = px * (1.050 if (i % 3 != 2) else 0.955)
        closes.append(px)
    peak_px = closes[-1]
    # Bars 246..253: sharp -18% bull pullback (stays strictly ABOVE EMA50, no euphoria!)
    target_pb = peak_px * 0.82
    for i in range(8):
        closes.append(peak_px - (peak_px - target_pb) * (i + 1) / 8.0)
    # Bars 254..291: bull resumption
    for i in range(38):
        closes.append(target_pb + (peak_px * 1.15 - target_pb) * (i + 1) / 38.0)

    df = _make_df_from_closes(t0, closes, high_mult=1.01, low_mult=0.99, has_deriv=False)
    feat = rmc.evaluate_cycle_features_1d(df)

    # Ensure EMA50 stayed below the pullback low AND euphoria did not trigger
    pullback_slice = feat.iloc[246:254]
    assert (pullback_slice["close"] > pullback_slice["ema50"]).all()
    assert not pullback_slice["euphoria_price_30d"].any()

    for var in ("Cycle_P_1d", "Cycle_PD_1d"):
        res = rmc.simulate_cycle_strategy("BTC/USDT", feat, var, start_idx=120, slippage_bps=5.0)
        assert len(res["closed_positions"]) == 1
        pos = res["closed_positions"][0]
        assert pos.entry_type == "BEAR_BOTTOM"
        assert pos.exit_reason == "BACKTEST_END"
        assert pos.base_stop_disabled is True
        assert pos.realized_pnl > 0.0


def test_euphoria_top_and_deriv_overheated_vs_extreme_blowoff():
    """
    Verify EUPHORIA_TOP behavior:
      - Cycle_P_1d exits on pure-price Euphoria Climax + (<EMA20 & <14d low) breakdown when gain >= +25%.
      - Cycle_PD_1d holds if derivatives exist and are NOT overheated (unless extreme blow-off),
        exits cleanly when deriv_overheated is True OR extreme blow-off (with multi-day RSI divergence) occurs.
    """
    t0 = _utc_ts(2023, 1, 1, 16)
    closes: List[float] = []
    for i in range(80):
        closes.append(150.0 - 0.5 * i)
    for i in range(40):
        closes.append(65.0 if i >= 22 else 110.0 - 2.0 * i)
    for i in range(31):
        closes.append(65.0 + (105.0 - 65.0) * (i + 1) / 31.0)
    # Slow steady climb 105 -> 130 (bars 151..185) then sharp euphoria surge 130 -> 225 (bars 186..208)
    for i in range(35):
        closes.append(105.0 + 25.0 * (i + 1) / 35.0)
    for i in range(23):
        closes.append(130.0 + 95.0 * ((i + 1) / 23.0) ** 1.3)
    # Distribution breakdown: drop below EMA20 and 14d low while still ~175 (> +65% above entry ~100) and above EMA50
    for i in range(12):
        closes.append(225.0 - 50.0 * (i + 1) / 12.0)

    df_nod = _make_df_from_closes(t0, closes, high_mult=1.01, low_mult=0.99, has_deriv=False)
    feat_nod = rmc.evaluate_cycle_features_1d(df_nod)
    res_p = rmc.simulate_cycle_strategy("BTC/USDT", feat_nod, "Cycle_P_1d", start_idx=120, slippage_bps=5.0)
    assert len(res_p["closed_positions"]) == 1
    assert res_p["closed_positions"][0].exit_reason == "EUPHORIA_TOP"
    assert res_p["closed_positions"][0].realized_pnl > 0.0

    # Case 1: Derivatives NOT overheated AND monotonic peak (no multi-day RSI divergence) -> holds past EUPHORIA_TOP
    df_cool = _make_df_from_closes(t0, closes, high_mult=1.01, low_mult=0.99, has_deriv=True)
    df_cool["coin_oi"] = 1_000_000.0
    df_cool.loc[110:135, "coin_oi"] = 700_000.0
    df_cool.loc[170:, "coin_oi"] = 650_000.0
    df_cool["lsur_z_90d"] = -1.2
    df_cool["funding_daily"] = 0.00001
    feat_cool = rmc.evaluate_cycle_features_1d(df_cool)
    assert feat_cool["euphoria_price_30d"].iloc[-12:].any()
    assert not feat_cool["deriv_overheated_30d"].iloc[-12:].any()
    assert not feat_cool["extreme_blowoff_30d"].iloc[-12:].any()
    res_pd_cool = rmc.simulate_cycle_strategy("BTC/USDT", feat_cool, "Cycle_PD_1d", start_idx=120, slippage_bps=5.0)
    assert all(p.exit_reason != "EUPHORIA_TOP" for p in res_pd_cool["closed_positions"])

    # Case 2: Overheated OI + LSUR/FR at top -> Cycle_PD_1d exits on EUPHORIA_TOP
    df_hot = df_cool.copy()
    df_hot.loc[170:, "coin_oi"] = 2_000_000.0
    df_hot.loc[170:, "lsur_z_90d"] = 1.6
    df_hot.loc[170:, "funding_daily"] = 0.0005
    feat_hot = rmc.evaluate_cycle_features_1d(df_hot)
    res_pd_hot = rmc.simulate_cycle_strategy("BTC/USDT", feat_hot, "Cycle_PD_1d", start_idx=120, slippage_bps=5.0)
    assert any(p.exit_reason == "EUPHORIA_TOP" for p in res_pd_hot["closed_positions"])

    # Case 3: Cool derivatives, BUT genuine two-wave bearish RSI divergence at >= 6 ATR blow-off -> exits EUPHORIA_TOP
    closes_div = list(closes[:209]) + [212.0, 210.0, 214.0, 224.0, 228.0, 218.0, 205.0, 192.0, 182.0, 174.0]
    df_div = _make_df_from_closes(t0, closes_div, high_mult=1.01, low_mult=0.99, has_deriv=True)
    df_div["coin_oi"] = 1_000_000.0
    df_div.loc[110:135, "coin_oi"] = 700_000.0
    df_div.loc[170:, "coin_oi"] = 650_000.0
    df_div["lsur_z_90d"] = -1.2
    df_div["funding_daily"] = 0.00001
    feat_div = rmc.evaluate_cycle_features_1d(df_div)
    assert feat_div["extreme_blowoff_30d"].iloc[-6:].any()
    res_pd_div = rmc.simulate_cycle_strategy("BTC/USDT", feat_div, "Cycle_PD_1d", start_idx=120, slippage_bps=5.0)
    assert any(p.exit_reason == "EUPHORIA_TOP" for p in res_pd_div["closed_positions"])

    # Case 4: Partial derivatives matching 2024..2025-11 live DB (coin_oi present, lsur_z_90d & funding_daily NaN):
    # deriv_overheated cannot be evaluated -> has_exit_deriv_30d MUST be False so Cycle_PD_1d falls back
    # cleanly to euphoria_price_30d and exits EUPHORIA_TOP (also guard 0.0 OI with zero warnings).
    df_partial = _make_df_from_closes(t0, closes, high_mult=1.01, low_mult=0.99, has_deriv=True)
    df_partial["coin_oi"] = 1_000_000.0
    df_partial.loc[0:50, "coin_oi"] = 0.0
    df_partial.loc[110:135, "coin_oi"] = 700_000.0
    df_partial.loc[170:, "coin_oi"] = 2_000_000.0
    df_partial["lsur_z_90d"] = float("nan")
    df_partial["funding_daily"] = float("nan")
    with warnings.catch_warnings(record=True) as w_part:
        warnings.simplefilter("error")
        feat_partial = rmc.evaluate_cycle_features_1d(df_partial)
    assert len(w_part) == 0
    assert not feat_partial["has_exit_deriv_30d"].any()
    res_pd_partial = rmc.simulate_cycle_strategy("BTC/USDT", feat_partial, "Cycle_PD_1d", start_idx=120, slippage_bps=5.0)
    assert any(p.exit_reason == "EUPHORIA_TOP" for p in res_pd_partial["closed_positions"])


def test_regime_bear_exit_and_bear_short_lifecycle():
    """
    Verify REGIME_BEAR_EXIT closes longs on secular bear breakdown and
    Cycle_PD_BearShort_1d opens 0.50x short -> covers on close > EMA50_1d.
    """
    t0 = _utc_ts(2023, 1, 1, 16)
    closes: List[float] = []
    # 0..79 drop 150->100, 80..119 crash 100->65, 120..155 recover 65->105 (enters long ~94)
    for i in range(80):
        closes.append(150.0 - 0.62 * i)
    for i in range(40):
        closes.append(65.0 if i >= 20 else 100.0 - 1.75 * i)
    for i in range(36):
        closes.append(65.0 + (105.0 - 65.0) * (i + 1) / 36.0)
    # Realistic oscillating climb 105 -> ~138 (+45% from entry, disabling BASE_INVALIDATION while RSI < 74)
    px = 105.0
    for i in range(70):
        px = px * (1.015 if (i % 3 != 2) else 0.982)
        closes.append(px)
    # Secular bear breakdown: peak -> 55 (breaks < EMA50, EMA20 < EMA50, < 30d low, < EMA200)
    top_px = closes[-1]
    for i in range(95):
        closes.append(max(55.0, top_px - (top_px - 55.0) * (i + 1) / 75.0))
    # Recovery back above EMA50: 55 -> 95
    for i in range(55):
        closes.append(55.0 + 40.0 * (i + 1) / 55.0)

    df = _make_df_from_closes(t0, closes, high_mult=1.01, low_mult=0.99, has_deriv=False)
    feat = rmc.evaluate_cycle_features_1d(df)

    res_pd = rmc.simulate_cycle_strategy("BTC/USDT", feat, "Cycle_PD_1d", start_idx=120, slippage_bps=5.0)
    assert any(p.exit_reason == "REGIME_BEAR_EXIT" for p in res_pd["closed_positions"])

    res_bs = rmc.simulate_cycle_strategy("BTC/USDT", feat, "Cycle_PD_BearShort_1d", start_idx=120, slippage_bps=5.0)
    sides_reasons = [(p.side, p.exit_reason) for p in res_bs["closed_positions"]]
    assert ("long", "REGIME_BEAR_EXIT") in sides_reasons
    assert any(side == "short" and reason == "SHORT_COVER" for side, reason in sides_reasons)
    short_pos = [p for p in res_bs["closed_positions"] if p.side == "short"][0]
    eq_after_long = 10000.0 + res_bs["closed_positions"][0].realized_pnl
    assert short_pos.cost == pytest.approx(eq_after_long * 0.50, rel=1e-6)
    assert short_pos.realized_pnl > 0.0


def test_base_invalidation_stop_and_short_stop_and_cooldown():
    """
    Verify:
      1) BASE_INVALIDATION triggers BEFORE close when pre-bar highest_since_entry < 1.20 * entry_price
         (even if same bar's high spikes >= 1.20 * entry_price).
      2) BASE_INVALIDATION disables permanently once highest_since_entry >= 1.20 * entry_price.
      3) 10-day post-exit cooldown blocks re-entry for bars exit_idx+1 .. exit_idx+9 and allows >= exit_idx+10.
      4) PnL accounting conservation holds exactly across all Cycle variants & Buy_And_Hold.
    """
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
            "path_a_ok": False,
            "path_b_ok": False,
            "has_washout_deriv_30d": False,
            "deriv_washout_30d": False,
            "euphoria_price_30d": False,
            "deriv_overheated_30d": False,
            "has_exit_deriv_30d": False,
            "extreme_blowoff_30d": False,
            "euphoria_breakdown_right": False,
            "regime_bear_exit": False,
            "bear_short_entry": False,
            "bear_short_cover": False,
        })
    df_feat = pd.DataFrame(rows)

    # Case A: Entry at bar 20 (close=100, atr=2, low20=95 -> base_stop = max(100-6.4, 95*0.98) = 93.6).
    # Bar 23 has high=125 (>=1.20) AND low=90 (<=93.6), while pre-bar highest_since_entry=101 < 120!
    # Conservative physical ordering MUST trigger BASE_INVALIDATION!
    df_a = df_feat.copy()
    df_a.loc[20, "path_a_ok"] = True
    df_a.loc[23, ["open", "high", "low", "close"]] = [101.0, 125.0, 90.0, 92.0]
    # Cooldown test: signal at bar 28 (28-23=5 < 10) blocked; signal at bar 33 (33-23=10 >= 10) allowed!
    df_a.loc[28, "path_a_ok"] = True
    df_a.loc[33, "path_a_ok"] = True

    res_a = rmc.simulate_cycle_strategy("BTC/USDT", df_a, "Cycle_P_1d", start_idx=10, slippage_bps=0.0)
    assert len(res_a["closed_positions"]) == 2
    assert res_a["closed_positions"][0].entry_idx == 20
    assert res_a["closed_positions"][0].exit_idx == 23
    assert res_a["closed_positions"][0].exit_reason == "BASE_INVALIDATION"
    assert res_a["closed_positions"][1].entry_idx == 33  # bar 28 blocked by 10d cooldown!

    # Case B: Bar 22 hits high=122 (>= 1.20 * entry) cleanly WITHOUT breaching base_stop,
    # permanently disabling BASE_INVALIDATION. Then bar 25 dips to low=90 -> MUST NOT exit!
    df_b = df_feat.copy()
    df_b.loc[20, "path_a_ok"] = True
    df_b.loc[22, ["open", "high", "low", "close"]] = [102.0, 122.0, 101.0, 118.0]
    df_b.loc[25, ["open", "high", "low", "close"]] = [105.0, 106.0, 90.0, 104.0]
    res_b = rmc.simulate_cycle_strategy("BTC/USDT", df_b, "Cycle_P_1d", start_idx=10, slippage_bps=5.0)
    assert len(res_b["closed_positions"]) == 1
    assert res_b["closed_positions"][0].exit_reason == "BACKTEST_END"
    assert res_b["closed_positions"][0].base_stop_disabled is True

    # Conservation check: final_balance - investment == sum(realized_pnl)
    m_b = res_b["metrics"]
    assert abs((m_b["final_balance"] - 10000.0) - sum(p.realized_pnl for p in res_b["closed_positions"])) < 1e-2

    # Case C: Short safety stop (3.5x ATR14 while gain < +15%)
    df_c = df_feat.copy()
    df_c.loc[20, "bear_short_entry"] = True
    df_c.loc[24, ["open", "high", "low", "close"]] = [101.0, 110.0, 99.0, 109.0]  # > 100 + 3.5*2 = 107!
    res_c = rmc.simulate_cycle_strategy("BTC/USDT", df_c, "Cycle_PD_BearShort_1d", start_idx=10, slippage_bps=5.0)
    assert len(res_c["closed_positions"]) == 1
    assert res_c["closed_positions"][0].side == "short"
    assert res_c["closed_positions"][0].exit_reason == "SHORT_STOP"


def test_derivative_washout_gate_and_buy_and_hold_slippage_sensitivity():
    t0 = _utc_ts(2024, 1, 1, 16)
    n = 100
    rows = []
    for i in range(n):
        rows.append({
            "time": t0 + i * 86400,
            "known_ts": t0 + (i + 1) * 86400,
            "open": 100.0 + i * 0.2,
            "high": 102.0 + i * 0.2,
            "low": 98.0 + i * 0.2,
            "close": 100.0 + i * 0.2,
            "volume": 1000.0,
            "atr14": 2.0,
            "low_min_20d": 95.0,
            "path_a_ok": False,
            "path_b_ok": (i == 40),
            "has_washout_deriv_30d": True,
            "deriv_washout_30d": False,
            "euphoria_price_30d": False,
            "deriv_overheated_30d": False,
            "has_exit_deriv_30d": True,
            "extreme_blowoff_30d": False,
            "euphoria_breakdown_right": False,
            "regime_bear_exit": False,
            "bear_short_entry": False,
            "bear_short_cover": False,
        })
    df_no_wash = pd.DataFrame(rows)
    # Without washout, Cycle_PD_1d blocks entry while Cycle_P_1d enters
    res_pd_blk = rmc.simulate_cycle_strategy("BTC/USDT", df_no_wash, "Cycle_PD_1d", start_idx=10)
    res_p_ok = rmc.simulate_cycle_strategy("BTC/USDT", df_no_wash, "Cycle_P_1d", start_idx=10)
    assert len(res_pd_blk["closed_positions"]) == 0
    assert len(res_p_ok["closed_positions"]) == 1

    # When has_washout_deriv_30d is False (pre-2023-07 fallback), Cycle_PD_1d enters identically to Cycle_P_1d
    df_pre = df_no_wash.copy()
    df_pre["has_washout_deriv_30d"] = False
    res_pd_pre = rmc.simulate_cycle_strategy("BTC/USDT", df_pre, "Cycle_PD_1d", start_idx=10)
    assert len(res_pd_pre["closed_positions"]) == 1

    # Buy_And_Hold EW Port Ret must reflect 5 bps vs 15 bps entry slippage
    candles = df_no_wash[["time", "open", "high", "low", "close", "volume"]].to_dict("records")
    bah5 = rmc.simulate_buy_and_hold("BTC/USDT", candles, slippage_bps=5.0)
    bah15 = rmc.simulate_buy_and_hold("BTC/USDT", candles, slippage_bps=15.0)
    assert bah5["metrics"]["total_return_pct"] > bah15["metrics"]["total_return_pct"]
    p5 = rmc._pool_cycle_stats([bah5["metrics"]], [bah5["metrics"]["_trade_stats"]])
    p15 = rmc._pool_cycle_stats([bah15["metrics"]], [bah15["metrics"]["_trade_stats"]])
    assert p5["port_cum_ret"] > p15["port_cum_ret"]


def test_short_stop_does_not_block_same_bar_long_and_ew_calendar_alignment():
    """
    Verify two regression fixes:
      1) If BearShort hits SHORT_STOP intra-bar on bar i and path_a_ok triggers at close[i],
         Cycle_PD_BearShort_1d MUST still take the Long entry identically to Cycle_PD_1d.
      2) _pool_cycle_stats aligns mixed UTC bar open hours (00:00 vs 16:00) onto the same calendar day.
    """
    t0 = _utc_ts(2024, 1, 1, 16)
    rows = []
    for i in range(60):
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
            "path_a_ok": (i == 24),
            "path_b_ok": False,
            "has_washout_deriv_30d": False,
            "deriv_washout_30d": False,
            "euphoria_price_30d": False,
            "deriv_overheated_30d": False,
            "has_exit_deriv_30d": False,
            "extreme_blowoff_30d": False,
            "euphoria_breakdown_right": False,
            "regime_bear_exit": False,
            "bear_short_entry": (i == 20),
            "bear_short_cover": False,
        })
    df_s = pd.DataFrame(rows)
    # Bar 24 hits short_stop (100 + 3.5*2 = 107) intra-bar AND closes at 108 triggering path_a_ok;
    # keep bars 25+ at 108 so the new long holds cleanly to BACKTEST_END.
    df_s.loc[24, ["open", "high", "low", "close"]] = [101.0, 110.0, 100.0, 108.0]
    df_s.loc[25:, ["open", "high", "low", "close"]] = [108.0, 109.0, 107.0, 108.0]

    r_pd = rmc.simulate_cycle_strategy("BTC/USDT", df_s, "Cycle_PD_1d", start_idx=10, slippage_bps=5.0)
    r_bs = rmc.simulate_cycle_strategy("BTC/USDT", df_s, "Cycle_PD_BearShort_1d", start_idx=10, slippage_bps=5.0)
    assert len(r_pd["closed_positions"]) == 1
    assert [(p.side, p.entry_idx, p.exit_reason) for p in r_bs["closed_positions"]] == [
        ("short", 20, "SHORT_STOP"),
        ("long", 24, "BACKTEST_END"),
    ]
    assert r_bs["signals"] == r_pd["signals"]

    # Mixed UTC hours (00:00 vs 16:00) on identical +1% daily growth must yield exact +1%/day EW return
    t_00 = _utc_ts(2025, 1, 1, 0)
    t_16 = _utc_ts(2025, 1, 1, 16)
    eq_a = [{"time": t_00 + d * 86400, "value": 10000.0 * (1.01 ** d)} for d in range(30)]
    eq_b = [{"time": t_16 + d * 86400, "value": 10000.0 * (1.01 ** d)} for d in range(30)]
    stat_a = {"trades": 0, "wins_count": 0, "gross_profit": 0.0, "gross_loss": 0.0, "trade_rets": [], "win_rets": [], "loss_rets": [], "hold_days": [], "days": 29.0, "investment": 10000.0, "equity_curve": eq_a}
    stat_b = {"trades": 0, "wins_count": 0, "gross_profit": 0.0, "gross_loss": 0.0, "trade_rets": [], "win_rets": [], "loss_rets": [], "hold_days": [], "days": 29.0, "investment": 10000.0, "equity_curve": eq_b}
    row_stub = {"total_return_pct": 33.45, "cagr_pct": 100.0, "max_drawdown_pct": 0.0, "mar_ratio": 10.0, "sharpe": 10.0, "time_in_market_pct": 100.0, "total_funding_pnl": 0.0, "total_fees_paid": 0.0}
    pooled = rmc._pool_cycle_stats([row_stub, row_stub], [stat_a, stat_b])
    expected_cum = ((1.01 ** 29) - 1.0) * 100.0
    assert pooled["port_cum_ret"] == pytest.approx(expected_cum, rel=1e-4)


# ─── 4. AST Guard & End-to-End Synthetic Mode Check ───────────────────────────

def test_no_bfill_or_inplace_in_macro_cycle_script():
    script_path = Path(rmc.__file__).resolve()
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
        warnings.filterwarnings("ignore", category=Warning, module=r"^api\.")
        summary = rmc.run_all_cycle_experiments(mode="synthetic", output_dir=tmp_path)

    assert len(caught) == 0
    md_path = Path(summary["md_path"])
    json_path = Path(summary["json_path"])
    assert md_path.exists()
    assert json_path.exists()
    assert md_path.name == "macro_cycle_report.md"
    assert json_path.name == "macro_cycle_report.json"

    parsed = json.loads(json_path.read_text(encoding="utf-8"))
    json.dumps(parsed, allow_nan=False)

    assert len(parsed["section0_inventory"]) == 5
    s1_vars = {r["variant"] for r in parsed["section1_forward_pooled"]}
    assert s1_vars == {
        "Legacy_v8_1d (Bull)",
        "Phase1_Macro_PD_1d (Bull)",
        "Cycle_P_1d",
        "Cycle_PD_1d",
    }
    boot_windows = {(r["scope"], r["window"]) for r in parsed["section1_bootstrap"]}
    assert ("POOLED", "Full_Cycle") in boot_windows
    assert ("POOLED", "Post2023_07_HasDeriv") in boot_windows

    assert len(parsed["section2_backtest_pooled"]) == 14  # 7 variant lines x 2 slippage levels (5 bps, 15 bps)
    assert len(parsed["section2_cycle_pd_trade_log"]) > 0
    assert len(parsed["section3_walkforward_pooled"]) == 7
    assert len(parsed["section4_verdict"]["checks"]) == 5

    md_text = md_path.read_text(encoding="utf-8")
    assert "## 0. Full-Cycle Dataset C Inventory" in md_text
    assert "## 1. Long-Horizon Bottom Entry Forward Quality" in md_text
    assert "## 2. Full-Cycle Portfolio Backtest" in md_text
    assert "### 2.3 Complete Trade-by-Trade Cycle Log Table (`Cycle_PD_1d`, `5 bps`)" in md_text
    assert "## 3. Chronological `60% IS` vs `40% OOS` Blind Walk-Forward" in md_text
    assert "## 4. Automated Objective Falsification & Viability Verdict (`H1..H5`)" in md_text
