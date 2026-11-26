#!/usr/bin/env python3
"""
Phase 1.5 Empirical Research Prototype: Asymmetric Macro Cycle Model & Falsification Suite.

Tests a pre-registered Asymmetric Macro Cycle architecture (holding full multi-month bull
waves without 3x ATR Chandelier shakeouts, with Bear/Capitulation Bottom & Bull Regional
Washout entries and Euphoria Climax / Regime Bear / Initial Base Invalidation exits)
across Dataset C (Full 1d Cycle from DB start) against:
  1) Buy_And_Hold (0.95x)
  2) Legacy_v8_1d (Narrow production risk profile AND Wide CycleHold benchmark)
  3) Phase1_Macro_PD_1d (Prior Phase 1 symmetric 3x ATR Chandelier model)
  4) Cycle_P_1d (Long-Flat Pure Price Cycle)
  5) Cycle_PD_1d (Long-Flat Price + Derivatives Cycle)
  6) Cycle_PD_BearShort_1d (Cycle_PD_1d Long + 0.50x Conservative Macro Bear Short)

Outputs:
  - <output-dir>/macro_cycle_report.md & .json

Usage:
  python scripts/run_macro_cycle_experiments.py
  python scripts/run_macro_cycle_experiments.py --mode db --output-dir scripts/debug
  python scripts/run_macro_cycle_experiments.py --mode synthetic --output-dir scripts/debug/_cycle_selftest
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.core.indicators import IndicatorEngine
from api.quant.signal_backtester import SignalBacktester
from api.quant.signal_strategy import SignalStrategyConfig, get_risk_profile
import scripts.run_macro_inflection_experiments as rme

SYMBOLS: List[str] = list(rme.SYMBOLS)
DAY_SEC = rme.DAY_SEC
H1_SEC = rme.H1_SEC
ALIGN_TOLERANCE_1D = rme.ALIGN_TOLERANCE_1D

CYCLE_COOLDOWN_BARS = 10
SHORT_COOLDOWN_BARS = 10
LONG_NOTIONAL_PCT = 0.95
SHORT_NOTIONAL_PCT = 0.50
FEE_RATE = 0.0005
SLIPPAGE_LEVELS: Tuple[float, ...] = (5.0, 15.0)


# ---------------------------------------------------------------------------
# Dataset C Builder (Full 1d OHLCV from DB start + strictly causal derivatives)
# ---------------------------------------------------------------------------

def build_dataset_c_from_raw(
    symbol: str,
    ohlcv_1d_raw: Sequence[Dict[str, Any]],
    deriv_1d_by_exch: Dict[str, Sequence[Dict[str, Any]]],
    funding_settlements: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Build Dataset C (Full 1d Cycle):
      - Keeps ALL deduplicated OKX 1d OHLCV bars from DB start (NO truncation to 2023-07).
      - warmup_bars = min(120, max(50, len(bars) // 5))
      - Strict known_ts = t_row + 86400 causal alignment for 1d derivatives + dual FundingRate union.
      - Zero .bfill(), zero inplace=True.
      - Exposes per-bar `has_deriv` boolean flag.
    """
    candles_1d = rme.deduplicate_okx_1d_ohlcv(ohlcv_1d_raw)
    n = len(candles_1d)
    if n < 80:
        return {
            "symbol": symbol,
            "timeframe": "1d",
            "dataset_name": "Dataset C (Full 1d Cycle)",
            "valid": False,
            "reason": f"Insufficient 1d OHLCV bars ({n} < 80)",
        }

    warmup_bars = min(120, max(50, n // 5))
    if n <= warmup_bars + 20:
        return {
            "symbol": symbol,
            "timeframe": "1d",
            "dataset_name": "Dataset C (Full 1d Cycle)",
            "valid": False,
            "reason": f"Insufficient eval bars after warmup (total={n}, warmup={warmup_bars})",
        }

    opens = [int(c["time"]) for c in candles_1d]
    known_ts = [int(c["time"]) + DAY_SEC for c in candles_1d]
    closes = np.array([float(c["close"]) for c in candles_1d], dtype=float)

    okx_rows = deriv_1d_by_exch.get("okx", [])
    bin_rows = deriv_1d_by_exch.get("binance", [])

    oi_okx = rme.align_series_by_known_ts(
        known_ts, okx_rows, source_shift_sec=DAY_SEC, value_key="open_interest", positive_only=True
    )
    oi_bin = rme.align_series_by_known_ts(
        known_ts, bin_rows, source_shift_sec=DAY_SEC, value_key="open_interest", positive_only=True
    )
    oi_usd = rme.combine_oi_causal(oi_okx, oi_bin)
    coin_oi = np.where(np.isfinite(oi_usd) & (oi_usd > 0.0) & (closes > 0.0), oi_usd / closes, np.nan)

    bin_taker_rows = rme.compute_taker_ratio_rows(bin_rows)
    okx_taker_rows = rme.compute_taker_ratio_rows(okx_rows)
    taker_bin = rme.align_series_by_known_ts(
        known_ts, bin_taker_rows, source_shift_sec=DAY_SEC, value_key="value", positive_only=False
    )
    taker_okx = rme.align_series_by_known_ts(
        known_ts, okx_taker_rows, source_shift_sec=DAY_SEC, value_key="value", positive_only=False
    )
    taker_ratio = np.where(np.isfinite(taker_bin), taker_bin, taker_okx)

    lsur_okx = rme.align_series_by_known_ts(
        known_ts, okx_rows, source_shift_sec=DAY_SEC, value_key="long_short_ratio", positive_only=True
    )
    lsur_bin = rme.align_series_by_known_ts(
        known_ts, bin_rows, source_shift_sec=DAY_SEC, value_key="long_short_ratio", positive_only=True
    )
    lsur_z_90d = rme.combine_lsur_z_causal(lsur_okx, lsur_bin, window=90, min_periods=30)

    funding_daily = rme.align_funding_to_1d(opens, known_ts, funding_settlements)

    has_deriv = (
        np.isfinite(coin_oi)
        | np.isfinite(taker_ratio)
        | np.isfinite(lsur_okx)
        | np.isfinite(lsur_bin)
        | np.isfinite(funding_daily)
    )

    df_1d = pd.DataFrame(candles_1d)
    df_1d["known_ts"] = known_ts
    df_1d["oi_usd"] = oi_usd
    df_1d["coin_oi"] = coin_oi
    df_1d["taker_ratio"] = taker_ratio
    df_1d["lsur_z_90d"] = lsur_z_90d
    df_1d["funding_daily"] = funding_daily
    df_1d["has_deriv"] = has_deriv

    eval_start = int(candles_1d[warmup_bars]["time"])
    clean_start = int(candles_1d[0]["time"])
    clean_end = int(candles_1d[-1]["time"])
    eval_price = candles_1d[warmup_bars:]

    # Build IndicatorEngine inputs for Legacy_v8_1d across ALL candles_1d
    oi_aligned = [
        {"time": opens[i], "value": float(oi_usd[i])}
        for i in range(n)
        if math.isfinite(oi_usd[i]) and oi_usd[i] > 0.0
    ]
    taker_for_cvd = [
        {
            "time": opens[i],
            "buy_vol": 1000.0 * float(taker_ratio[i]),
            "sell_vol": 1000.0 * (1.0 - float(taker_ratio[i])),
        }
        for i in range(n)
        if math.isfinite(taker_ratio[i])
    ]
    cvd_aligned = IndicatorEngine.calculate_cvd_history(taker_for_cvd) if taker_for_cvd else []
    lsur_z_aligned = [
        {"time": opens[i], "value": round(float(lsur_z_90d[i]), 3)}
        for i in range(n)
        if math.isfinite(lsur_z_90d[i])
    ]
    funding_aligned = [
        {"time": opens[i], "value": float(funding_daily[i]) * 100.0}
        for i in range(n)
        if math.isfinite(funding_daily[i])
    ]

    ema_trend = IndicatorEngine.calculate_ema_trend(candles_1d, symbol=symbol)
    rsi_hist = IndicatorEngine.calculate_rsi(candles_1d)
    bb_pctb = IndicatorEngine.calculate_bollinger_bands(candles_1d)["bb_pctb"]
    donchian = IndicatorEngine.calculate_donchian_channel(candles_1d, period=20)
    macd_hist = IndicatorEngine.calculate_macd(candles_1d)
    regime_hist = IndicatorEngine.calculate_market_regime_history(candles_1d, cvd_aligned=cvd_aligned)
    pulse_hist = IndicatorEngine.calculate_composite_score(
        price_data=candles_1d,
        lsur_z_aligned=lsur_z_aligned,
        cvd_aligned=cvd_aligned,
        funding_aligned=funding_aligned,
        rsi_aligned=rsi_hist,
        ema_fast_aligned=ema_trend["ema_fast"],
        bb_pctb_aligned=bb_pctb,
        oi_aligned=oi_aligned,
        timeframe="1d",
        symbol=symbol,
        use_dynamic_profiles=True,
    )

    funding_eval = [
        f for f in funding_settlements
        if (eval_start - 8 * H1_SEC) <= int(f["time"]) <= (clean_end + DAY_SEC)
    ]

    deriv_indices = np.where(has_deriv)[0]
    deriv_start = int(opens[int(deriv_indices[0])]) if len(deriv_indices) > 0 else None

    clean_days = round((clean_end - eval_start) / float(DAY_SEC), 2)
    return {
        "symbol": symbol,
        "timeframe": "1d",
        "dataset_name": "Dataset C (Full 1d Cycle)",
        "valid": True,
        "clean_start": clean_start,
        "eval_start": eval_start,
        "clean_end": clean_end,
        "deriv_start": deriv_start,
        "clean_days": clean_days,
        "total_bars": n,
        "clean_bars": len(eval_price),
        "warmup_bars": warmup_bars,
        "has_deriv_eval_bars": int(np.sum(has_deriv[warmup_bars:])),
        "coin_oi_eval_bars": int(np.sum(np.isfinite(coin_oi[warmup_bars:]))),
        "taker_eval_bars": int(np.sum(np.isfinite(taker_ratio[warmup_bars:]))),
        "lsur_eval_bars": int(np.sum(np.isfinite(lsur_z_90d[warmup_bars:]))),
        "funding_eval_bars": int(np.sum(np.isfinite(funding_daily[warmup_bars:]))),
        "funding_count": len(funding_eval),
        "price_with_warmup": candles_1d,
        "eval_price": eval_price,
        "df_1d": df_1d,
        "oi_aligned": oi_aligned,
        "cvd_aligned": cvd_aligned,
        "lsur_z_aligned": lsur_z_aligned,
        "funding_aligned": funding_aligned,
        "funding_settlements": funding_eval,
        "all_funding_settlements": list(funding_settlements),
        "ema_fast": ema_trend["ema_fast"],
        "ema_slow": ema_trend["ema_slow"],
        "rsi_hist": rsi_hist,
        "bb_pctb": bb_pctb,
        "donchian": donchian,
        "macd_hist": macd_hist,
        "regime_history": regime_hist,
        "pulse_history": pulse_hist,
    }


def load_dataset_c_from_db(
    symbols: Sequence[str] = SYMBOLS,
    session_factory: Optional[Callable[[], Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Load Dataset C (Full 1d Cycle) from PostgreSQL (or injected SQLAlchemy session factory)."""
    if session_factory is None:
        from api.db.database import SessionLocal
        session_factory = SessionLocal
    from api.db.models import FundingRate, MarketDataPoint

    datasets_c: Dict[str, Dict[str, Any]] = {}
    for sym in symbols:
        coin = sym.split("/")[0].split("-")[0].upper()
        funding_syms = [f"{coin}-USDT-SWAP", f"{coin}/USDT:USDT"]

        with session_factory() as db:
            rows_1d = (
                db.query(MarketDataPoint)
                .filter(MarketDataPoint.symbol == sym, MarketDataPoint.timeframe == "1d")
                .order_by(MarketDataPoint.timestamp.asc())
                .all()
            )
            funding_rows = (
                db.query(FundingRate)
                .filter(
                    FundingRate.exchange == "okx",
                    FundingRate.symbol.in_(funding_syms),
                )
                .order_by(FundingRate.timestamp.asc())
                .all()
            )

        ohlcv_1d_raw = [
            {
                "time": rme._dt_to_sec(r.timestamp),
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            }
            for r in rows_1d
            if str(r.exchange or "").lower() == "okx" and r.open is not None
        ]

        deriv_1d_by_exch: Dict[str, List[Dict[str, Any]]] = {"okx": [], "binance": []}
        for r in rows_1d:
            ex = str(r.exchange or "").lower()
            if ex in deriv_1d_by_exch:
                deriv_1d_by_exch[ex].append({
                    "time": rme._dt_to_sec(r.timestamp),
                    "open_interest": r.open_interest,
                    "long_short_ratio": r.long_short_ratio,
                    "taker_buy_vol": r.taker_buy_vol,
                    "taker_sell_vol": r.taker_sell_vol,
                })

        funding_raw = [
            {
                "time": rme._dt_to_sec(r.timestamp),
                "symbol": r.symbol,
                "funding_rate": r.funding_rate,
            }
            for r in funding_rows
        ]
        funding_settlements = rme.deduplicate_funding_records(funding_raw, coin=coin)
        datasets_c[sym] = build_dataset_c_from_raw(sym, ohlcv_1d_raw, deriv_1d_by_exch, funding_settlements)

    return datasets_c


# ---------------------------------------------------------------------------
# Pre-Registered Asymmetric Macro Cycle Feature Engine (Strictly Causal)
# ---------------------------------------------------------------------------

def evaluate_cycle_features_1d(df_1d: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all strictly causal daily cycle indicators and path flags on df_1d.
    Never uses .bfill() or inplace=True. Prefix 0..k produces identical values at 0..k-1.
    """
    df = df_1d.sort_values("time").reset_index(drop=True).copy()
    n = len(df)
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()
    atr14 = rme.compute_wilder_atr(high, low, close, period=14)
    rsi14 = rme.compute_wilder_rsi(close, period=14)

    close_pos = close.where(close > 1e-12, np.nan)
    atr_pos = atr14.where(atr14 > 1e-12, np.nan)
    atr_pct = atr14 / close_pos
    atr_pct_median60 = atr_pct.rolling(window=60, min_periods=30).median()

    high_max_180d = high.rolling(window=180, min_periods=60).max()
    high_max_90d = high.rolling(window=90, min_periods=30).max()
    high_max_20d = high.rolling(window=20, min_periods=10).max()
    high_max_10d = high.rolling(window=10, min_periods=5).max()

    high_max_20_prev = high.rolling(window=20, min_periods=20).max().shift(1)
    high_max_14_prev = high.rolling(window=14, min_periods=14).max().shift(1)

    low_min_14_prev = low.rolling(window=14, min_periods=14).min().shift(1)
    low_min_30_prev = low.rolling(window=30, min_periods=30).min().shift(1)
    low_min_20d = low.rolling(window=20, min_periods=10).min()

    rsi_min_10d = rsi14.rolling(window=10, min_periods=5).min()
    rsi_max_15d = rsi14.rolling(window=15, min_periods=5).max()
    rsi_max_20d = rsi14.rolling(window=20, min_periods=10).max()

    ema20_shift5 = ema20.shift(5)
    ema50_shift10 = ema50.shift(10)
    ema200_shift20 = ema200.shift(20)

    # --- Entry Path A: Bear Market / Capitulation Bottom ---
    dd_180_pct = (high_max_180d - low) / high_max_180d.where(high_max_180d > 1e-12, np.nan)
    dyn_dd_thresh = np.clip(6.0 * atr_pct_median60, 0.28, 0.50)
    bear_dd_cond = (dd_180_pct >= dyn_dd_thresh)
    bear_ema200_cond = ((low - ema200) / atr_pos <= -3.0)
    bear_left_bar = ((bear_dd_cond | bear_ema200_cond) & (rsi_min_10d <= 34.0)).fillna(False)
    bear_left_active = (
        bear_left_bar.astype(int).rolling(window=45, min_periods=1).max() > 0
    ).fillna(False)
    bear_right_ok = (
        (close > ema50)
        & (ema20 > ema20_shift5)
        & (close > high_max_20_prev)
    ).fillna(False)
    path_a_ok = bear_left_active & bear_right_ok

    # --- Entry Path B: Bull Regional Washout Bottom ---
    reg_context_ok = (
        (close > ema200 * 0.92)
        & (ema200 >= ema200_shift20 * 0.99)
    ).fillna(False)
    reg_dd_90_atr = (high_max_90d - low) / atr_pos
    reg_left_bar = (
        (reg_dd_90_atr >= 3.2)
        & ((rsi_min_10d <= 40.0) | (low <= ema200 * 1.03))
    ).fillna(False)
    reg_left_active = (
        reg_left_bar.astype(int).rolling(window=25, min_periods=1).max() > 0
    ).fillna(False)
    reg_right_ok = (
        (close > ema50)
        & (ema20 >= ema50 * 0.99)
        & (close > high_max_14_prev)
    ).fillna(False)
    path_b_ok = reg_context_ok & reg_left_active & reg_right_ok

    # --- Derivatives Features (Causal 180d / 90d / 60d windows) ---
    coin_oi = df["coin_oi"].astype(float)
    coin_oi_max_60d = coin_oi.rolling(window=60, min_periods=30).max()
    coin_oi_max_60d_pos = coin_oi_max_60d.where(coin_oi_max_60d > 0.0, np.nan)
    coin_oi_dd_60d = ((coin_oi / coin_oi_max_60d_pos) - 1.0) * 100.0
    coin_oi_dd_60d = coin_oi_dd_60d.where(coin_oi.notna() & coin_oi_max_60d_pos.notna(), np.nan)
    coin_oi_pct_180d = pd.Series(
        rme.rolling_percentile_causal(coin_oi.to_numpy(dtype=float), window=180, min_periods=60),
        index=df.index,
    )

    funding_daily = df["funding_daily"].astype(float)
    fr_7d_raw = funding_daily.rolling(window=7, min_periods=1).mean()
    fr_7d_mean = pd.Series(
        np.where(funding_daily.notna(), fr_7d_raw.to_numpy(dtype=float), np.nan),
        index=df.index,
    )
    fr_pct_180d = pd.Series(
        rme.rolling_percentile_causal(funding_daily.to_numpy(dtype=float), window=180, min_periods=60),
        index=df.index,
    )
    lsur_z_90d = df["lsur_z_90d"].astype(float)

    has_deriv = df["has_deriv"].astype(bool) if "has_deriv" in df.columns else (
        coin_oi.notna() | df["taker_ratio"].notna() | lsur_z_90d.notna() | funding_daily.notna()
    )

    # Washout Gate (within past 30 bars)
    washout_evaluable_bar = (
        coin_oi_dd_60d.notna()
        | coin_oi_pct_180d.notna()
        | fr_7d_mean.notna()
        | fr_pct_180d.notna()
        | lsur_z_90d.notna()
    )
    washout_bar = (
        (coin_oi_dd_60d <= -12.0)
        | (coin_oi_pct_180d <= 35.0)
        | (fr_7d_mean <= 0.00005)
        | (fr_pct_180d <= 30.0)
        | (lsur_z_90d <= -1.0)
    ).fillna(False)

    has_washout_deriv_30d = (
        (has_deriv & washout_evaluable_bar).astype(int).rolling(window=30, min_periods=1).max() > 0
    ).fillna(False)
    deriv_washout_30d = (
        washout_bar.astype(int).rolling(window=30, min_periods=1).max() > 0
    ).fillna(False)

    # --- Exit 1: Euphoria Climax + Distribution Breakdown ---
    euphoria_ext_atr = (high_max_10d - ema200) / atr_pos
    euphoria_price_bar = ((euphoria_ext_atr >= 4.5) & (rsi_max_15d >= 74.0)).fillna(False)
    euphoria_price_30d = (
        euphoria_price_bar.astype(int).rolling(window=30, min_periods=1).max() > 0
    ).fillna(False)

    deriv_overheated_bar = (
        (coin_oi_pct_180d >= 75.0)
        & ((fr_pct_180d >= 75.0) | (lsur_z_90d >= 1.0))
    ).fillna(False)
    deriv_overheated_30d = (
        deriv_overheated_bar.astype(int).rolling(window=30, min_periods=1).max() > 0
    ).fillna(False)

    exit_deriv_evaluable_bar = (
        coin_oi_pct_180d.notna() & (fr_pct_180d.notna() | lsur_z_90d.notna())
    )
    has_exit_deriv_30d = (
        (has_deriv & exit_deriv_evaluable_bar).astype(int).rolling(window=30, min_periods=1).max() > 0
    ).fillna(False)

    # Extreme blow-off: >= 6.0x ATR above EMA200 with bearish 20d RSI divergence while high near highs
    # (Require RSI peak to have occurred >= 3 bars ago so a single-day pullback after peak isn't mislabeled.)
    rsi_max_3d = rsi14.rolling(window=3, min_periods=1).max()
    extreme_blowoff_bar = (
        (euphoria_ext_atr >= 6.0)
        & (high >= high_max_20d * 0.97)
        & (rsi_max_3d < (rsi_max_20d - 1.5))
    ).fillna(False)
    extreme_blowoff_30d = (
        extreme_blowoff_bar.astype(int).rolling(window=30, min_periods=1).max() > 0
    ).fillna(False)

    euphoria_breakdown_right = (
        (close < ema20)
        & (close < low_min_14_prev)
    ).fillna(False)

    # --- Exit 2: Secular Bear Regime Breakdown ---
    regime_bear_exit = (
        (close < ema50)
        & (ema20 < ema50)
        & (close < low_min_30_prev)
        & ((close < ema200) | (ema50 < ema50_shift10))
    ).fillna(False)

    # --- Short Entry / Cover for Cycle_PD_BearShort_1d ---
    bear_short_entry = (
        (close < ema200)
        & (ema50 < ema200)
        & (close < low_min_30_prev)
    ).fillna(False)
    bear_short_cover = (close > ema50).fillna(False)

    df["ema20"] = ema20
    df["ema50"] = ema50
    df["ema200"] = ema200
    df["atr14"] = atr14
    df["rsi14"] = rsi14
    df["atr_pct"] = atr_pct
    df["atr_pct_median60"] = atr_pct_median60
    df["low_min_20d"] = low_min_20d
    df["coin_oi_dd_60d"] = coin_oi_dd_60d
    df["coin_oi_pct_180d"] = coin_oi_pct_180d
    df["fr_7d_mean"] = fr_7d_mean
    df["fr_pct_180d"] = fr_pct_180d
    df["has_deriv"] = has_deriv.to_numpy(dtype=bool)
    df["bear_left_active"] = bear_left_active.to_numpy(dtype=bool)
    df["reg_left_active"] = reg_left_active.to_numpy(dtype=bool)
    df["path_a_ok"] = path_a_ok.to_numpy(dtype=bool)
    df["path_b_ok"] = path_b_ok.to_numpy(dtype=bool)
    df["has_washout_deriv_30d"] = has_washout_deriv_30d.to_numpy(dtype=bool)
    df["deriv_washout_30d"] = deriv_washout_30d.to_numpy(dtype=bool)
    df["euphoria_price_30d"] = euphoria_price_30d.to_numpy(dtype=bool)
    df["deriv_overheated_30d"] = deriv_overheated_30d.to_numpy(dtype=bool)
    df["has_exit_deriv_30d"] = has_exit_deriv_30d.to_numpy(dtype=bool)
    df["extreme_blowoff_30d"] = extreme_blowoff_30d.to_numpy(dtype=bool)
    df["euphoria_breakdown_right"] = euphoria_breakdown_right.to_numpy(dtype=bool)
    df["regime_bear_exit"] = regime_bear_exit.to_numpy(dtype=bool)
    df["bear_short_entry"] = bear_short_entry.to_numpy(dtype=bool)
    df["bear_short_cover"] = bear_short_cover.to_numpy(dtype=bool)
    return df


# ---------------------------------------------------------------------------
# Cycle Simulation Engine & Unified Portfolio Metrics
# ---------------------------------------------------------------------------

@dataclass
class CyclePosition:
    symbol: str
    side: str               # "long" | "short"
    entry_price: float
    entry_time: int
    entry_idx: int
    entry_type: str
    size: float
    atr_entry: float
    base_stop: float
    short_stop: float
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    cost: float = 0.0
    highest_since_entry: float = 0.0
    lowest_since_entry: float = float("inf")
    base_stop_disabled: bool = False
    short_stop_disabled: bool = False
    funding_pnl: float = 0.0
    exit_price: float = 0.0
    exit_time: int = 0
    exit_idx: int = 0
    exit_reason: str = ""
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    is_closed: bool = False

    def __post_init__(self) -> None:
        self.cost = self.entry_price * self.size
        self.highest_since_entry = self.entry_price
        self.lowest_since_entry = self.entry_price

    def peak_mfe_pct(self) -> float:
        if self.entry_price <= 0.0:
            return 0.0
        if self.side == "long":
            return max(0.0, (self.highest_since_entry - self.entry_price) / self.entry_price * 100.0)
        return max(0.0, (self.entry_price - self.lowest_since_entry) / self.entry_price * 100.0)


def _apply_slippage(price: float, side: str, is_entry: bool, slippage_bps: float) -> float:
    slip = max(0.0, float(slippage_bps)) / 10000.0
    if slip <= 0.0:
        return price
    is_buy = (side == "long" and is_entry) or (side == "short" and not is_entry)
    return price * (1.0 + slip) if is_buy else price * (1.0 - slip)


def _prep_funding_events(funding_rates: Optional[Sequence[Dict[str, Any]]]) -> List[Dict[str, float]]:
    if not funding_rates:
        return []
    dedup: Dict[int, float] = {}
    for fs in funding_rates:
        if fs is None or "time" not in fs:
            continue
        raw_r = fs.get("funding_rate", fs.get("rate"))
        if not rme._is_finite(raw_r):
            continue
        dedup[int(fs["time"])] = float(raw_r)
    return [{"time": ft, "funding_rate": dedup[ft]} for ft in sorted(dedup.keys())]


def compute_unified_portfolio_metrics(
    symbol: str,
    equity_curve: Sequence[Dict[str, Any]],
    closed_positions: Sequence[Any],
    *,
    investment: float = 10000.0,
    final_balance: float = 10000.0,
    total_fees_paid: float = 0.0,
    total_funding_pnl: float = 0.0,
    bars_in_market: int = 0,
    total_bars: int = 0,
    slippage_bps: float = 5.0,
) -> Dict[str, Any]:
    """Compute consistent full-cycle portfolio metrics across all 6 (7) variants."""
    n_eq = len(equity_curve)
    days = 1.0
    if n_eq >= 2:
        days = max((int(equity_curve[-1]["time"]) - int(equity_curve[0]["time"])) / float(DAY_SEC), 1.0)

    total_trades = len(closed_positions)
    trades_per_yr = (total_trades / max(days / 365.0, 1e-4)) if total_trades > 0 else 0.0

    def _pos_pnl(p: Any) -> float:
        return float(getattr(p, "realized_pnl", 0.0))

    def _pos_cost(p: Any) -> float:
        c = getattr(p, "initial_cost", None)
        if c is None or c <= 0.0:
            c = getattr(p, "cost", 0.0)
        return float(c or 0.0)

    def _pos_hold_days(p: Any) -> float:
        et = int(getattr(p, "entry_time", 0))
        xt = int(getattr(p, "exit_time", 0))
        return max(0.0, (xt - et) / float(DAY_SEC))

    wins = [p for p in closed_positions if _pos_pnl(p) > 0.0]
    losses = [p for p in closed_positions if _pos_pnl(p) <= 0.0]
    win_rate = (len(wins) / total_trades * 100.0) if total_trades > 0 else 0.0

    win_rets = [(_pos_pnl(p) / _pos_cost(p) * 100.0) for p in wins if _pos_cost(p) > 0.0]
    loss_rets = [(_pos_pnl(p) / _pos_cost(p) * 100.0) for p in losses if _pos_cost(p) > 0.0]
    all_rets = [(_pos_pnl(p) / _pos_cost(p) * 100.0) if _pos_cost(p) > 0.0 else 0.0 for p in closed_positions]
    hold_days_list = [_pos_hold_days(p) for p in closed_positions]

    avg_win_pct = float(np.mean(win_rets)) if win_rets else 0.0
    avg_loss_pct = float(np.mean(loss_rets)) if loss_rets else 0.0
    avg_hold_days = float(np.mean(hold_days_list)) if hold_days_list else 0.0

    gross_profit = float(sum(_pos_pnl(p) for p in wins))
    gross_loss = float(abs(sum(_pos_pnl(p) for p in losses)))
    if gross_loss > 0.0:
        pf = min(gross_profit / gross_loss, 999.9)
    else:
        pf = 999.9 if gross_profit > 0.0 else 0.0

    total_ret_pct = (final_balance - investment) / investment * 100.0
    cagr_pct = ((final_balance / investment) ** (365.0 / days) - 1.0) * 100.0 if final_balance > 0.0 else -100.0

    max_dd = 0.0
    daily_rets: List[float] = []
    sharpe = 0.0
    if n_eq >= 1:
        vals = np.array([float(e["value"]) for e in equity_curve], dtype=float)
        peak = vals[0]
        for v in vals:
            if v > peak:
                peak = v
            if peak > 0.0:
                dd = (peak - v) / peak * 100.0
                if dd > max_dd:
                    max_dd = dd
        if n_eq >= 2:
            prev = vals[:-1]
            r_arr = np.where(prev > 0.0, np.diff(vals) / prev, 0.0)
            daily_rets = [float(x) for x in r_arr]
            sd = float(np.std(r_arr))
            if sd > 1e-12:
                sharpe = float(np.mean(r_arr) / sd * math.sqrt(365.0))

    if max_dd > 0.0:
        mar = cagr_pct / max(max_dd, 0.01)
    else:
        mar = 999.0 if cagr_pct > 0.0 else 0.0
    mar = max(-999.0, min(999.0, mar))

    time_in_mkt_pct = (bars_in_market / total_bars * 100.0) if total_bars > 0 else 0.0

    return {
        "symbol": symbol,
        "slippage_bps": float(slippage_bps),
        "days": round(float(days), 2),
        "trades": int(total_trades),
        "trades_per_yr": round(float(trades_per_yr), 2),
        "avg_hold_days": round(float(avg_hold_days), 1),
        "win_rate": round(float(win_rate), 1),
        "avg_win_pct": round(float(avg_win_pct), 2),
        "avg_loss_pct": round(float(avg_loss_pct), 2),
        "profit_factor": round(float(pf), 2),
        "expectancy_pct": round(float(np.mean(all_rets)) if all_rets else 0.0, 3),
        "total_return_pct": round(float(total_ret_pct), 2),
        "cagr_pct": round(float(cagr_pct), 2),
        "max_drawdown_pct": round(float(max_dd), 2),
        "mar_ratio": round(float(mar), 2),
        "sharpe": round(float(sharpe), 2),
        "time_in_market_pct": round(float(time_in_mkt_pct), 1),
        "total_fees_paid": round(float(total_fees_paid), 2),
        "total_funding_pnl": round(float(total_funding_pnl), 2),
        "final_balance": round(float(final_balance), 2),
        "_trade_stats": {
            "trades": int(total_trades),
            "wins_count": int(len(wins)),
            "gross_profit": float(gross_profit),
            "gross_loss": float(gross_loss),
            "trade_rets": list(all_rets),
            "win_rets": list(win_rets),
            "loss_rets": list(loss_rets),
            "hold_days": list(hold_days_list),
            "days": float(days),
            "investment": float(investment),
            "equity_curve": list(equity_curve),
        },
    }


def simulate_buy_and_hold(
    symbol: str,
    candles: Sequence[Dict[str, Any]],
    *,
    funding_rates: Optional[Sequence[Dict[str, Any]]] = None,
    slippage_bps: float = 5.0,
    fee_rate: float = FEE_RATE,
    investment: float = 10000.0,
    include_funding: bool = True,
) -> Dict[str, Any]:
    """Buy 0.95x notional on first candle close, hold to end, paying causal funding & fees."""
    if not candles:
        return compute_unified_portfolio_metrics(symbol, [], [], investment=investment, final_balance=investment, slippage_bps=slippage_bps)

    funding_events = _prep_funding_events(funding_rates)
    balance = float(investment)
    total_fees = 0.0
    total_funding = 0.0
    equity_curve: List[Dict[str, Any]] = []

    c0 = candles[0]
    t0 = int(c0["time"])
    close0 = float(c0["close"])
    entry_price = _apply_slippage(close0, "long", is_entry=True, slippage_bps=slippage_bps)
    notional = balance * LONG_NOTIONAL_PCT
    size = notional / entry_price
    cost = size * entry_price
    entry_fee = cost * fee_rate
    balance -= (cost + entry_fee)
    total_fees += entry_fee

    pos = CyclePosition(
        symbol=symbol,
        side="long",
        entry_price=entry_price,
        entry_time=t0,
        entry_idx=0,
        entry_type="BUY_AND_HOLD",
        size=size,
        atr_entry=0.0,
        base_stop=0.0,
        short_stop=0.0,
    )
    pos.fees_paid = entry_fee

    f_idx = 0
    while f_idx < len(funding_events) and funding_events[f_idx]["time"] <= t0:
        f_idx += 1

    n = len(candles)
    bars_in_mkt = 1
    equity_curve.append({"time": t0, "value": balance + pos.size * close0})

    for i in range(1, n):
        c = candles[i]
        ti = int(c["time"])
        hi = float(c["high"])
        ci = float(c["close"])
        next_t = int(candles[i + 1]["time"]) if i + 1 < n else (ti + DAY_SEC)

        if hi > pos.highest_since_entry:
            pos.highest_since_entry = hi
        if float(c["low"]) < pos.lowest_since_entry:
            pos.lowest_since_entry = float(c["low"])

        while f_idx < len(funding_events) and funding_events[f_idx]["time"] <= next_t:
            fs = funding_events[f_idx]
            if include_funding and fs["time"] > ti:
                f_pnl = -(pos.size * ci) * fs["funding_rate"]
                balance += f_pnl
                pos.funding_pnl += f_pnl
                total_funding += f_pnl
            f_idx += 1

        bars_in_mkt += 1
        equity_curve.append({"time": ti, "value": balance + pos.size * ci})

    last = candles[-1]
    last_close = float(last["close"])
    last_time = int(last["time"])
    exit_fee = last_close * pos.size * fee_rate
    raw_pnl = (last_close - pos.entry_price) * pos.size
    pos.exit_price = last_close
    pos.exit_time = last_time
    pos.exit_idx = n - 1
    pos.exit_reason = "BACKTEST_END"
    pos.fees_paid = entry_fee + exit_fee
    pos.realized_pnl = (raw_pnl - pos.fees_paid) + pos.funding_pnl
    pos.is_closed = True
    total_fees += exit_fee
    balance += pos.cost + raw_pnl - exit_fee
    equity_curve[-1]["value"] = balance

    metrics = compute_unified_portfolio_metrics(
        symbol,
        equity_curve,
        [pos],
        investment=investment,
        final_balance=balance,
        total_fees_paid=total_fees,
        total_funding_pnl=total_funding,
        bars_in_market=bars_in_mkt,
        total_bars=n,
        slippage_bps=slippage_bps,
    )
    return {
        "metrics": metrics,
        "closed_positions": [pos],
        "equity_curve": equity_curve,
        "signals": [{"time": t0, "direction": "bullish", "entry_type": "BUY_AND_HOLD", "price": close0}],
    }


def simulate_cycle_strategy(
    symbol: str,
    df_feat: pd.DataFrame,
    variant: str,
    *,
    start_idx: int,
    end_idx: Optional[int] = None,
    funding_rates: Optional[Sequence[Dict[str, Any]]] = None,
    external_signals: Optional[Sequence[Dict[str, Any]]] = None,
    slippage_bps: float = 5.0,
    fee_rate: float = FEE_RATE,
    investment: float = 10000.0,
    include_funding: bool = True,
) -> Dict[str, Any]:
    """
    Simulate asymmetric macro cycle strategy over df_feat[start_idx : end_idx].
    Variants supported:
      - 'Cycle_P_1d'
      - 'Cycle_PD_1d'
      - 'Cycle_PD_BearShort_1d'
      - 'Legacy_v8_1d_CycleHold' (uses external_signals bullish triggers + Cycle_P_1d exits)
    """
    n_total = len(df_feat)
    stop_idx = n_total if end_idx is None else min(n_total, int(end_idx))
    if start_idx >= stop_idx:
        empty_m = compute_unified_portfolio_metrics(
            symbol, [], [], investment=investment, final_balance=investment, slippage_bps=slippage_bps
        )
        return {"metrics": empty_m, "closed_positions": [], "equity_curve": [], "signals": [], "final_state": "FLAT"}

    use_deriv = variant in ("Cycle_PD_1d", "Cycle_PD_BearShort_1d")
    allow_bear_short = (variant == "Cycle_PD_BearShort_1d")
    use_external_bull = (variant == "Legacy_v8_1d_CycleHold")

    ext_bull_times = {
        int(s["time"])
        for s in (external_signals or [])
        if s.get("direction") == "bullish"
    }

    times = df_feat["time"].to_numpy(dtype=int)
    opens = df_feat["open"].to_numpy(dtype=float)
    highs = df_feat["high"].to_numpy(dtype=float)
    lows = df_feat["low"].to_numpy(dtype=float)
    closes = df_feat["close"].to_numpy(dtype=float)
    atr14 = df_feat["atr14"].to_numpy(dtype=float)
    low_min_20d = df_feat["low_min_20d"].to_numpy(dtype=float)

    path_a_ok = df_feat["path_a_ok"].to_numpy(dtype=bool)
    path_b_ok = df_feat["path_b_ok"].to_numpy(dtype=bool)
    has_washout_deriv_30d = df_feat["has_washout_deriv_30d"].to_numpy(dtype=bool)
    deriv_washout_30d = df_feat["deriv_washout_30d"].to_numpy(dtype=bool)

    euphoria_price_30d = df_feat["euphoria_price_30d"].to_numpy(dtype=bool)
    deriv_overheated_30d = df_feat["deriv_overheated_30d"].to_numpy(dtype=bool)
    has_exit_deriv_30d = df_feat["has_exit_deriv_30d"].to_numpy(dtype=bool)
    extreme_blowoff_30d = df_feat["extreme_blowoff_30d"].to_numpy(dtype=bool)
    euphoria_breakdown_right = df_feat["euphoria_breakdown_right"].to_numpy(dtype=bool)
    regime_bear_exit = df_feat["regime_bear_exit"].to_numpy(dtype=bool)
    bear_short_entry = df_feat["bear_short_entry"].to_numpy(dtype=bool)
    bear_short_cover = df_feat["bear_short_cover"].to_numpy(dtype=bool)

    funding_events = _prep_funding_events(funding_rates)
    f_idx = 0
    first_t = int(times[start_idx])
    while f_idx < len(funding_events) and funding_events[f_idx]["time"] <= first_t:
        f_idx += 1

    balance = float(investment)
    open_pos: Optional[CyclePosition] = None
    closed_positions: List[CyclePosition] = []
    entry_signals: List[Dict[str, Any]] = []
    equity_curve: List[Dict[str, Any]] = []
    total_fees = 0.0
    total_funding = 0.0
    bars_in_mkt = 0

    last_long_exit_idx = -1000
    last_short_exit_idx = -1000

    def _calc_equity(px: float) -> float:
        if open_pos is None:
            return balance
        if open_pos.side == "long":
            return balance + open_pos.size * px
        return balance + open_pos.cost + (open_pos.entry_price - px) * open_pos.size

    def _close_pos(pos: CyclePosition, fill_px: float, bar_i: int, reason: str) -> None:
        nonlocal balance, total_fees, open_pos, last_long_exit_idx, last_short_exit_idx
        raw_pnl = (
            (fill_px - pos.entry_price) * pos.size
            if pos.side == "long"
            else (pos.entry_price - fill_px) * pos.size
        )
        entry_fee = pos.cost * fee_rate
        exit_fee = fill_px * pos.size * fee_rate
        fees = entry_fee + exit_fee
        pos.exit_price = fill_px
        pos.exit_time = int(times[bar_i])
        pos.exit_idx = bar_i
        pos.exit_reason = reason
        pos.fees_paid = fees
        pos.realized_pnl = (raw_pnl - fees) + pos.funding_pnl
        pos.is_closed = True

        total_fees += exit_fee
        balance += pos.cost + raw_pnl - exit_fee
        closed_positions.append(pos)
        if pos.side == "long":
            last_long_exit_idx = bar_i
        else:
            last_short_exit_idx = bar_i
        open_pos = None

    for i in range(start_idx, stop_idx):
        ti = int(times[i])
        oi = float(opens[i])
        hi = float(highs[i])
        li = float(lows[i])
        ci = float(closes[i])
        next_t = int(times[i + 1]) if i + 1 < stop_idx else (ti + DAY_SEC)

        was_in_mkt_today = open_pos is not None
        long_stopped_today = False
        short_stopped_today = False

        # Step 1: Check physical intra-bar stops BEFORE close (i > entry_idx)
        if open_pos is not None and i > open_pos.entry_idx:
            if open_pos.side == "long":
                # Check Base Invalidation Stop ONLY while pre-bar highest_since_entry < entry_price * 1.20
                if not open_pos.base_stop_disabled and open_pos.highest_since_entry < open_pos.entry_price * 1.20:
                    if oi <= open_pos.base_stop:
                        fill = _apply_slippage(oi, "long", is_entry=False, slippage_bps=slippage_bps)
                        _close_pos(open_pos, fill, i, "BASE_INVALIDATION")
                        long_stopped_today = True
                    elif li <= open_pos.base_stop:
                        raw_fill = min(open_pos.base_stop, hi)
                        fill = _apply_slippage(raw_fill, "long", is_entry=False, slippage_bps=slippage_bps)
                        _close_pos(open_pos, fill, i, "BASE_INVALIDATION")
                        long_stopped_today = True

                if open_pos is not None:
                    if hi > open_pos.highest_since_entry:
                        open_pos.highest_since_entry = hi
                    if li < open_pos.lowest_since_entry:
                        open_pos.lowest_since_entry = li
                    if open_pos.highest_since_entry >= open_pos.entry_price * 1.20:
                        open_pos.base_stop_disabled = True
            else:
                # Short initial safety stop (3.5x ATR14 while pre-bar gain < +15%)
                if not open_pos.short_stop_disabled and open_pos.lowest_since_entry > open_pos.entry_price * 0.85:
                    if oi >= open_pos.short_stop:
                        fill = _apply_slippage(oi, "short", is_entry=False, slippage_bps=slippage_bps)
                        _close_pos(open_pos, fill, i, "SHORT_STOP")
                        short_stopped_today = True
                    elif hi >= open_pos.short_stop:
                        raw_fill = max(open_pos.short_stop, li)
                        fill = _apply_slippage(raw_fill, "short", is_entry=False, slippage_bps=slippage_bps)
                        _close_pos(open_pos, fill, i, "SHORT_STOP")
                        short_stopped_today = True

                if open_pos is not None:
                    if li < open_pos.lowest_since_entry:
                        open_pos.lowest_since_entry = li
                    if hi > open_pos.highest_since_entry:
                        open_pos.highest_since_entry = hi
                    if open_pos.lowest_since_entry <= open_pos.entry_price * 0.85:
                        open_pos.short_stop_disabled = True

        # Step 2: Causal FundingRate settlement over (ti, next_t]
        while f_idx < len(funding_events) and funding_events[f_idx]["time"] <= next_t:
            fs = funding_events[f_idx]
            if include_funding and fs["time"] > ti and open_pos is not None:
                notional = open_pos.size * ci
                f_pnl = (-notional * fs["funding_rate"]) if open_pos.side == "long" else (notional * fs["funding_rate"])
                balance += f_pnl
                open_pos.funding_pnl += f_pnl
                total_funding += f_pnl
            f_idx += 1

        # Step 3: Close-based exits (i > entry_idx)
        closed_long_at_close = False
        closed_short_at_close = False
        if open_pos is not None and i > open_pos.entry_idx:
            if open_pos.side == "long":
                gain_ok = (ci >= open_pos.entry_price * 1.25)
                if use_deriv and has_exit_deriv_30d[i]:
                    euph_left = (bool(euphoria_price_30d[i]) and bool(deriv_overheated_30d[i])) or bool(extreme_blowoff_30d[i])
                else:
                    euph_left = bool(euphoria_price_30d[i])

                exit_euphoria = gain_ok and euph_left and bool(euphoria_breakdown_right[i])
                exit_regime = bool(regime_bear_exit[i])

                if exit_euphoria:
                    fill = _apply_slippage(ci, "long", is_entry=False, slippage_bps=slippage_bps)
                    _close_pos(open_pos, fill, i, "EUPHORIA_TOP")
                    closed_long_at_close = True
                elif exit_regime:
                    fill = _apply_slippage(ci, "long", is_entry=False, slippage_bps=slippage_bps)
                    _close_pos(open_pos, fill, i, "REGIME_BEAR_EXIT")
                    closed_long_at_close = True
            else:
                if bool(bear_short_cover[i]):
                    fill = _apply_slippage(ci, "short", is_entry=False, slippage_bps=slippage_bps)
                    _close_pos(open_pos, fill, i, "SHORT_COVER")
                    closed_short_at_close = True

        # Step 4: Entries when FLAT
        if open_pos is None:
            # Long entry gate (after 10-day post-long-exit cooldown; short stop-out does NOT block Cycle_PD_1d longs)
            long_cooldown_ok = (i - last_long_exit_idx >= CYCLE_COOLDOWN_BARS)
            entered_long = False

            if long_cooldown_ok and not closed_long_at_close and not long_stopped_today:
                entry_type: Optional[str] = None
                if use_external_bull:
                    if ti in ext_bull_times:
                        entry_type = "LEGACY_V8_BULL"
                else:
                    pa = bool(path_a_ok[i])
                    pb = bool(path_b_ok[i])
                    if pa or pb:
                        if use_deriv and has_washout_deriv_30d[i] and not bool(deriv_washout_30d[i]):
                            entry_type = None
                        else:
                            entry_type = "BEAR_BOTTOM" if pa else "REGIONAL_BOTTOM"

                if entry_type is not None:
                    curr_eq = _calc_equity(ci)
                    if curr_eq > 0.0 and balance > 0.0:
                        ep = _apply_slippage(ci, "long", is_entry=True, slippage_bps=slippage_bps)
                        atr_e = float(atr14[i]) if math.isfinite(atr14[i]) and atr14[i] > 0.0 else max(hi - li, ci * 0.01)
                        low20_e = float(low_min_20d[i]) if math.isfinite(low_min_20d[i]) and low_min_20d[i] > 0.0 else li
                        b_stop = max(ep - 3.2 * atr_e, low20_e * 0.98)
                        if b_stop >= ep:
                            b_stop = ep * 0.999

                        notional = min(balance, curr_eq) * LONG_NOTIONAL_PCT
                        size = notional / ep
                        cost = size * ep
                        if size > 0.0 and cost > 0.0:
                            e_fee = cost * fee_rate
                            balance -= (cost + e_fee)
                            total_fees += e_fee
                            open_pos = CyclePosition(
                                symbol=symbol,
                                side="long",
                                entry_price=ep,
                                entry_time=ti,
                                entry_idx=i,
                                entry_type=entry_type,
                                size=size,
                                atr_entry=atr_e,
                                base_stop=b_stop,
                                short_stop=0.0,
                            )
                            open_pos.fees_paid = e_fee
                            entry_signals.append({
                                "time": ti,
                                "direction": "bullish",
                                "entry_type": entry_type,
                                "price": ci,
                                "score": 6.0,
                            })
                            entered_long = True

            # Bear short entry for Cycle_PD_BearShort_1d (0.50x conservative macro short when FLAT)
            if (
                allow_bear_short
                and not entered_long
                and not closed_short_at_close
                and not long_stopped_today
                and not short_stopped_today
                and (i - last_short_exit_idx >= SHORT_COOLDOWN_BARS)
                and bool(bear_short_entry[i])
            ):
                curr_eq = _calc_equity(ci)
                if curr_eq > 0.0 and balance > 0.0:
                    ep = _apply_slippage(ci, "short", is_entry=True, slippage_bps=slippage_bps)
                    atr_e = float(atr14[i]) if math.isfinite(atr14[i]) and atr14[i] > 0.0 else max(hi - li, ci * 0.01)
                    s_stop = ep + 3.5 * atr_e
                    notional = min(balance, curr_eq) * SHORT_NOTIONAL_PCT
                    size = notional / ep
                    cost = size * ep
                    if size > 0.0 and cost > 0.0:
                        e_fee = cost * fee_rate
                        balance -= (cost + e_fee)
                        total_fees += e_fee
                        open_pos = CyclePosition(
                            symbol=symbol,
                            side="short",
                            entry_price=ep,
                            entry_time=ti,
                            entry_idx=i,
                            entry_type="BEAR_SHORT",
                            size=size,
                            atr_entry=atr_e,
                            base_stop=0.0,
                            short_stop=s_stop,
                        )
                        open_pos.fees_paid = e_fee

        if was_in_mkt_today or (open_pos is not None):
            bars_in_mkt += 1

        equity_curve.append({"time": ti, "value": _calc_equity(ci)})

    final_state = "FLAT" if open_pos is None else open_pos.side.upper()

    # Close any remaining open position at backtest end
    if open_pos is not None:
        last_idx = stop_idx - 1
        _close_pos(open_pos, float(closes[last_idx]), last_idx, "BACKTEST_END")
        if equity_curve:
            equity_curve[-1]["value"] = balance

    metrics = compute_unified_portfolio_metrics(
        symbol,
        equity_curve,
        closed_positions,
        investment=investment,
        final_balance=balance,
        total_fees_paid=total_fees,
        total_funding_pnl=total_funding,
        bars_in_market=bars_in_mkt,
        total_bars=(stop_idx - start_idx),
        slippage_bps=slippage_bps,
    )
    return {
        "metrics": metrics,
        "closed_positions": closed_positions,
        "equity_curve": equity_curve,
        "signals": entry_signals,
        "final_state": final_state,
    }


def _count_bars_in_market(candles: Sequence[Dict[str, Any]], positions: Sequence[Any]) -> int:
    if not candles or not positions:
        return 0
    intervals = [
        (int(getattr(p, "entry_time", 0)), int(getattr(p, "exit_time", 0)))
        for p in positions
    ]
    count = 0
    for c in candles:
        t = int(c["time"])
        if any(et <= t <= xt for et, xt in intervals):
            count += 1
    return count


def run_legacy_narrow_slice(
    ds_c: Dict[str, Any],
    signals: Sequence[Dict[str, Any]],
    *,
    price_slice: Optional[Sequence[Dict[str, Any]]] = None,
    slippage_bps: float = 5.0,
    investment: float = 10000.0,
) -> Dict[str, Any]:
    """Run production IndicatorEngine signals through Legacy v8 narrow risk profile."""
    candles = list(price_slice) if price_slice is not None else list(ds_c["eval_price"])
    if not candles:
        return {
            "metrics": compute_unified_portfolio_metrics(ds_c["symbol"], [], [], investment=investment, final_balance=investment, slippage_bps=slippage_bps),
            "closed_positions": [],
            "equity_curve": [],
        }

    t0, t1 = int(candles[0]["time"]), int(candles[-1]["time"])
    slice_sigs = [s for s in signals if t0 <= int(s["time"]) <= t1]
    slice_funding = [f for f in ds_c["all_funding_settlements"] if t0 <= int(f["time"]) <= (t1 + DAY_SEC)]

    prof = get_risk_profile(ds_c["symbol"], "1d")
    cfg = SignalStrategyConfig(
        symbol=ds_c["symbol"],
        investment=investment,
        risk_per_trade_pct=2.0,
        take_profit_pct=prof["take_profit_pct"],
        stop_loss_pct=prof["stop_loss_pct"],
        trailing_stop_pct=prof["trailing_stop_pct"],
        trailing_activation_pct=prof["trailing_activation_pct"],
        max_positions=1,
        fee_rate=FEE_RATE,
        slippage_bps=slippage_bps,
        include_funding=True,
        trailing_path_mode="ohlc",
        allow_short=True,
        reverse_on_signal=True,
        enable_partial_tp=False,
    )
    cfg.validate()
    bt = SignalBacktester(cfg, candles, slice_sigs, funding_rates=slice_funding)
    res = bt.run()
    bars_mkt = _count_bars_in_market(candles, bt.closed_positions)
    metrics = compute_unified_portfolio_metrics(
        ds_c["symbol"],
        res["equity"],
        bt.closed_positions,
        investment=investment,
        final_balance=float(res["final_balance"]),
        total_fees_paid=float(res["total_fees_paid"]),
        total_funding_pnl=float(res["total_funding_pnl"]),
        bars_in_market=bars_mkt,
        total_bars=len(candles),
        slippage_bps=slippage_bps,
    )
    return {
        "metrics": metrics,
        "closed_positions": bt.closed_positions,
        "equity_curve": res["equity"],
    }


def run_phase1_wide_atr_slice(
    ds_c: Dict[str, Any],
    signals: Sequence[Dict[str, Any]],
    *,
    price_slice: Optional[Sequence[Dict[str, Any]]] = None,
    slippage_bps: float = 5.0,
    investment: float = 10000.0,
) -> Dict[str, Any]:
    """Run Phase1_Macro_PD_1d symmetric 3x ATR Chandelier model on Dataset C."""
    candles = list(price_slice) if price_slice is not None else list(ds_c["eval_price"])
    if not candles:
        return {
            "metrics": compute_unified_portfolio_metrics(ds_c["symbol"], [], [], investment=investment, final_balance=investment, slippage_bps=slippage_bps),
            "closed_positions": [],
            "equity_curve": [],
        }

    t0, t1 = int(candles[0]["time"]), int(candles[-1]["time"])
    slice_sigs = [s for s in signals if t0 <= int(s["time"]) <= t1]
    slice_funding = [f for f in ds_c["all_funding_settlements"] if t0 <= int(f["time"]) <= (t1 + DAY_SEC)]

    bt = rme.WideATRBacktester(
        candles,
        slice_sigs,
        funding_rates=slice_funding,
        atr_warmup_candles=ds_c["price_with_warmup"],
        slippage_bps=slippage_bps,
        fee_rate=FEE_RATE,
        include_funding=True,
        risk_per_trade_pct=1.5,
        max_notional_pct=0.95,
        initial_sl_atr_mult=2.5,
        chandelier_act_atr_mult=1.5,
        chandelier_trail_atr_mult=3.0,
        investment=investment,
    )
    res = bt.run()
    bars_mkt = _count_bars_in_market(candles, bt.closed_positions)
    metrics = compute_unified_portfolio_metrics(
        ds_c["symbol"],
        res["equity"],
        bt.closed_positions,
        investment=investment,
        final_balance=float(res["final_balance"]),
        total_fees_paid=float(res["total_fees_paid"]),
        total_funding_pnl=float(res["total_funding_pnl"]),
        bars_in_market=bars_mkt,
        total_bars=len(candles),
        slippage_bps=slippage_bps,
    )
    return {
        "metrics": metrics,
        "closed_positions": bt.closed_positions,
        "equity_curve": res["equity"],
    }


# ---------------------------------------------------------------------------
# Section 1: Long-Horizon Bottom Entry Forward Quality (+30d, +90d, +180d)
# ---------------------------------------------------------------------------

def compute_long_horizon_outcomes(
    price_data: Sequence[Dict[str, Any]],
    signals: Sequence[Dict[str, Any]],
    has_deriv_by_time: Optional[Dict[int, bool]] = None,
) -> List[Dict[str, Any]]:
    """
    Compute bullish forward outcomes over +30d, +90d, +180d:
      - ret_30d, ret_90d, ret_180d (%)
      - mfe_90d, mae_90d, mfe_180d, mae_180d (%)
      - wave_capture_30: +30% MFE within +180d strictly before -15% MAE bar-by-bar
      - wave_capture_50: +50% MFE within +180d strictly before -20% MAE bar-by-bar
    """
    time_to_idx = {int(p["time"]): idx for idx, p in enumerate(price_data)}
    n = len(price_data)
    outcomes: List[Dict[str, Any]] = []

    for sig in signals:
        if sig.get("direction", "bullish") != "bullish":
            continue
        t_sig = int(sig["time"])
        idx = time_to_idx.get(t_sig)
        if idx is None:
            continue
        entry = float(price_data[idx]["close"])
        if entry <= 0.0:
            continue

        row: Dict[str, Any] = {
            "time": t_sig,
            "has_deriv": bool(has_deriv_by_time.get(t_sig, False)) if has_deriv_by_time else False,
            "ret_30d": None,
            "ret_90d": None,
            "ret_180d": None,
            "mfe_90d": None,
            "mae_90d": None,
            "mfe_180d": None,
            "mae_180d": None,
            "wave_capture_30": None,
            "wave_capture_50": None,
        }

        for label, h_bars in (("30d", 30), ("90d", 90), ("180d", 180)):
            if idx + h_bars >= n:
                continue
            window = price_data[idx + 1 : idx + h_bars + 1]
            c_end = float(window[-1]["close"])
            highs_w = [float(b["high"]) for b in window]
            lows_w = [float(b["low"]) for b in window]
            row[f"ret_{label}"] = (c_end - entry) / entry * 100.0
            if label in ("90d", "180d"):
                row[f"mfe_{label}"] = max(0.0, (max(highs_w) - entry) / entry * 100.0)
                row[f"mae_{label}"] = max(0.0, (entry - min(lows_w)) / entry * 100.0)

        if idx + 180 < n:
            cap30 = False
            for k in range(idx + 1, idx + 181):
                fav = (float(price_data[k]["high"]) - entry) / entry * 100.0
                adv = (entry - float(price_data[k]["low"])) / entry * 100.0
                if adv >= 15.0:
                    cap30 = False
                    break
                if fav >= 30.0:
                    cap30 = True
                    break
            row["wave_capture_30"] = cap30

            cap50 = False
            for k in range(idx + 1, idx + 181):
                fav = (float(price_data[k]["high"]) - entry) / entry * 100.0
                adv = (entry - float(price_data[k]["low"])) / entry * 100.0
                if adv >= 20.0:
                    cap50 = False
                    break
                if fav >= 50.0:
                    cap50 = True
                    break
            row["wave_capture_50"] = cap50

        outcomes.append(row)
    return outcomes


def summarize_cycle_forward_metrics(
    symbol: str,
    variant: str,
    clean_days: float,
    total_signals: int,
    outcomes: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    r30 = [o["ret_30d"] for o in outcomes if o["ret_30d"] is not None]
    r90 = [o["ret_90d"] for o in outcomes if o["ret_90d"] is not None]
    r180 = [o["ret_180d"] for o in outcomes if o["ret_180d"] is not None]
    mfe90 = [o["mfe_90d"] for o in outcomes if o["mfe_90d"] is not None]
    mae90 = [o["mae_90d"] for o in outcomes if o["mae_90d"] is not None]
    mfe180 = [o["mfe_180d"] for o in outcomes if o["mfe_180d"] is not None]
    mae180 = [o["mae_180d"] for o in outcomes if o["mae_180d"] is not None]
    wc30 = [o["wave_capture_30"] for o in outcomes if o["wave_capture_30"] is not None]
    wc50 = [o["wave_capture_50"] for o in outcomes if o["wave_capture_50"] is not None]

    med_mfe90 = float(np.median(mfe90)) if mfe90 else 0.0
    med_mae90 = float(np.median(mae90)) if mae90 else 0.0
    med_mfe180 = float(np.median(mfe180)) if mfe180 else 0.0
    med_mae180 = float(np.median(mae180)) if mae180 else 0.0

    sig_yr = (total_signals / max(clean_days / 365.0, 1e-4)) if clean_days > 0.0 else 0.0
    hit90 = (sum(1 for x in r90 if x > 0.0) / len(r90) * 100.0) if r90 else 0.0
    hit180 = (sum(1 for x in r180 if x > 0.0) / len(r180) * 100.0) if r180 else 0.0
    wc30_pct = (sum(1 for x in wc30 if x) / len(wc30) * 100.0) if wc30 else 0.0
    wc50_pct = (sum(1 for x in wc50 if x) / len(wc50) * 100.0) if wc50 else 0.0

    return {
        "symbol": symbol,
        "variant": variant,
        "clean_days": round(float(clean_days), 2),
        "signals": int(total_signals),
        "signals_per_yr": round(float(sig_yr), 2),
        "n_30d": len(r30),
        "n_90d": len(r90),
        "n_180d": len(r180),
        "hit_90d": round(float(hit90), 1),
        "hit_180d": round(float(hit180), 1),
        "ret_30d": round(float(np.mean(r30)), 2) if r30 else 0.0,
        "ret_90d": round(float(np.mean(r90)), 2) if r90 else 0.0,
        "ret_180d": round(float(np.mean(r180)), 2) if r180 else 0.0,
        "med_mfe_90d": round(med_mfe90, 2),
        "med_mae_90d": round(med_mae90, 2),
        "e_ratio_90d": round(med_mfe90 / max(med_mae90, 1e-4), 2) if mfe90 else 0.0,
        "med_mfe_180d": round(med_mfe180, 2),
        "med_mae_180d": round(med_mae180, 2),
        "e_ratio_180d": round(med_mfe180 / max(med_mae180, 1e-4), 2) if mfe180 else 0.0,
        "wave_capture_30_pct": round(float(wc30_pct), 1),
        "wave_capture_50_pct": round(float(wc50_pct), 1),
    }


def _build_cycle_bootstrap_comparisons(
    pooled_outcomes: Dict[str, List[Dict[str, Any]]],
    per_coin_outcomes: Dict[Tuple[str, str], List[Dict[str, Any]]],
    symbols: Sequence[str],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    def _compare(scope: str, window_label: str, var_a: str, var_b: str, out_a: Sequence[Dict[str, Any]], out_b: Sequence[Dict[str, Any]]) -> None:
        r30_a = [o["ret_30d"] for o in out_a if o["ret_30d"] is not None]
        r30_b = [o["ret_30d"] for o in out_b if o["ret_30d"] is not None]
        r90_a = [o["ret_90d"] for o in out_a if o["ret_90d"] is not None]
        r90_b = [o["ret_90d"] for o in out_b if o["ret_90d"] is not None]
        r180_a = [o["ret_180d"] for o in out_a if o["ret_180d"] is not None]
        r180_b = [o["ret_180d"] for o in out_b if o["ret_180d"] is not None]

        mfe90_a = [o["mfe_90d"] for o in out_a if o["mfe_90d"] is not None]
        mae90_a = [o["mae_90d"] for o in out_a if o["mae_90d"] is not None]
        mfe90_b = [o["mfe_90d"] for o in out_b if o["mfe_90d"] is not None]
        mae90_b = [o["mae_90d"] for o in out_b if o["mae_90d"] is not None]

        mfe180_a = [o["mfe_180d"] for o in out_a if o["mfe_180d"] is not None]
        mae180_a = [o["mae_180d"] for o in out_a if o["mae_180d"] is not None]
        mfe180_b = [o["mfe_180d"] for o in out_b if o["mfe_180d"] is not None]
        mae180_b = [o["mae_180d"] for o in out_b if o["mae_180d"] is not None]

        er90_a = (float(np.median(mfe90_a)) / max(float(np.median(mae90_a)), 1e-4)) if mfe90_a else 0.0
        er90_b = (float(np.median(mfe90_b)) / max(float(np.median(mae90_b)), 1e-4)) if mfe90_b else 0.0
        er180_a = (float(np.median(mfe180_a)) / max(float(np.median(mae180_a)), 1e-4)) if mfe180_a else 0.0
        er180_b = (float(np.median(mfe180_b)) / max(float(np.median(mae180_b)), 1e-4)) if mfe180_b else 0.0

        rows.append({
            "scope": scope,
            "window": window_label,
            "variant_a": var_a,
            "variant_b": var_b,
            "n_a_90d": len(r90_a),
            "n_b_90d": len(r90_b),
            "n_a_180d": len(r180_a),
            "n_b_180d": len(r180_b),
            "ret_30d_a": round(float(np.mean(r30_a)), 2) if r30_a else 0.0,
            "ret_30d_b": round(float(np.mean(r30_b)), 2) if r30_b else 0.0,
            "p_ret_30d": rme.bootstrap_diff_pvalue(r30_a, r30_b),
            "ret_90d_a": round(float(np.mean(r90_a)), 2) if r90_a else 0.0,
            "ret_90d_b": round(float(np.mean(r90_b)), 2) if r90_b else 0.0,
            "p_ret_90d": rme.bootstrap_diff_pvalue(r90_a, r90_b),
            "ret_180d_a": round(float(np.mean(r180_a)), 2) if r180_a else 0.0,
            "ret_180d_b": round(float(np.mean(r180_b)), 2) if r180_b else 0.0,
            "p_ret_180d": rme.bootstrap_diff_pvalue(r180_a, r180_b),
            "er_90d_a": round(er90_a, 2),
            "er_90d_b": round(er90_b, 2),
            "p_er_90d": rme.bootstrap_eratio_diff_pvalue(mfe90_a, mae90_a, mfe90_b, mae90_b),
            "er_180d_a": round(er180_a, 2),
            "er_180d_b": round(er180_b, 2),
            "p_er_180d": rme.bootstrap_eratio_diff_pvalue(mfe180_a, mae180_a, mfe180_b, mae180_b),
        })

    pairs = [
        ("Cycle_PD_1d", "Cycle_P_1d"),
        ("Cycle_PD_1d", "Legacy_v8_1d (Bull)"),
        ("Cycle_PD_1d", "Phase1_Macro_PD_1d (Bull)"),
        ("Cycle_P_1d", "Legacy_v8_1d (Bull)"),
    ]
    for var_a, var_b in pairs:
        _compare("POOLED", "Full_Cycle", var_a, var_b, pooled_outcomes.get(var_a, []), pooled_outcomes.get(var_b, []))
        for sym in symbols:
            _compare(sym, "Full_Cycle", var_a, var_b, per_coin_outcomes.get((sym, var_a), []), per_coin_outcomes.get((sym, var_b), []))

    # Paired post-2023-07 (has_deriv) window comparison: Cycle_PD_1d vs Cycle_P_1d
    pd_deriv = [o for o in pooled_outcomes.get("Cycle_PD_1d", []) if o.get("has_deriv")]
    p_deriv = [o for o in pooled_outcomes.get("Cycle_P_1d", []) if o.get("has_deriv")]
    _compare("POOLED", "Post2023_07_HasDeriv", "Cycle_PD_1d", "Cycle_P_1d", pd_deriv, p_deriv)
    for sym in symbols:
        c_pd = [o for o in per_coin_outcomes.get((sym, "Cycle_PD_1d"), []) if o.get("has_deriv")]
        c_p = [o for o in per_coin_outcomes.get((sym, "Cycle_P_1d"), []) if o.get("has_deriv")]
        _compare(sym, "Post2023_07_HasDeriv", "Cycle_PD_1d", "Cycle_P_1d", c_pd, c_p)

    return rows


# ---------------------------------------------------------------------------
# Pooled / Equal-Weight Calendar Portfolio Aggregation
# ---------------------------------------------------------------------------

def _pool_cycle_stats(
    coin_rows: Sequence[Dict[str, Any]],
    stats_list: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    tot_trades = sum(int(s.get("trades", 0)) for s in stats_list)
    tot_wins = sum(int(s.get("wins_count", 0)) for s in stats_list)
    tot_gp = sum(float(s.get("gross_profit", 0.0)) for s in stats_list)
    tot_gl = sum(float(s.get("gross_loss", 0.0)) for s in stats_list)
    tot_asset_years = sum(float(s.get("days", 0.0)) / 365.0 for s in stats_list)

    all_rets: List[float] = []
    win_rets: List[float] = []
    loss_rets: List[float] = []
    hold_days: List[float] = []
    for s in stats_list:
        all_rets.extend(s.get("trade_rets", []))
        win_rets.extend(s.get("win_rets", []))
        loss_rets.extend(s.get("loss_rets", []))
        hold_days.extend(s.get("hold_days", []))

    pooled_wr = (tot_wins / tot_trades * 100.0) if tot_trades > 0 else 0.0
    if tot_gl > 0.0:
        pooled_pf = min(tot_gp / tot_gl, 999.9)
    else:
        pooled_pf = 999.9 if tot_gp > 0.0 else 0.0

    # Active-coin Equal-Weight Daily Portfolio Curve (strictly causal per UTC day, including day 0 friction)
    rets_by_day: Dict[int, List[float]] = {}
    for s in stats_list:
        eq = s.get("equity_curve", [])
        inv_s = float(s.get("investment", 10000.0))
        coin_day_rets: Dict[int, float] = {}
        if eq and inv_s > 0.0:
            t_0 = (int(eq[0]["time"]) // DAY_SEC) * DAY_SEC
            v_0 = float(eq[0]["value"])
            r_0 = (v_0 - inv_s) / inv_s
            coin_day_rets[t_0] = (1.0 + coin_day_rets.get(t_0, 0.0)) * (1.0 + r_0) - 1.0
        if len(eq) >= 2:
            for k in range(1, len(eq)):
                prev_v = float(eq[k - 1]["value"])
                curr_v = float(eq[k]["value"])
                t_k = (int(eq[k]["time"]) // DAY_SEC) * DAY_SEC
                if prev_v > 0.0:
                    r_k = (curr_v - prev_v) / prev_v
                    coin_day_rets[t_k] = (1.0 + coin_day_rets.get(t_k, 0.0)) * (1.0 + r_k) - 1.0
        for d_ts, d_ret in coin_day_rets.items():
            rets_by_day.setdefault(d_ts, []).append(d_ret)

    port_cum_ret = 0.0
    port_cagr = 0.0
    port_max_dd = 0.0
    port_mar = 0.0
    port_sharpe = 0.0
    if rets_by_day:
        sorted_ts = sorted(rets_by_day.keys())
        eq_val = 10000.0
        peak = eq_val
        port_daily_rets: List[float] = []
        for tk in sorted_ts:
            r_day = float(np.mean(rets_by_day[tk]))
            port_daily_rets.append(r_day)
            eq_val *= (1.0 + r_day)
            if eq_val > peak:
                peak = eq_val
            if peak > 0.0:
                dd = (peak - eq_val) / peak * 100.0
                if dd > port_max_dd:
                    port_max_dd = dd
        port_days = max((sorted_ts[-1] - sorted_ts[0]) / float(DAY_SEC), 1.0)
        port_cum_ret = (eq_val / 10000.0 - 1.0) * 100.0
        port_cagr = ((eq_val / 10000.0) ** (365.0 / port_days) - 1.0) * 100.0 if eq_val > 0.0 else -100.0
        port_mar = (port_cagr / max(port_max_dd, 0.01)) if port_max_dd > 0.0 else (999.0 if port_cagr > 0.0 else 0.0)
        port_mar = max(-999.0, min(999.0, port_mar))
        sd = float(np.std(port_daily_rets))
        if sd > 1e-12:
            port_sharpe = float(np.mean(port_daily_rets) / sd * math.sqrt(365.0))

    return {
        "targets": len(coin_rows),
        "total_trades": int(tot_trades),
        "trades_per_yr": round(float(tot_trades / max(tot_asset_years, 1e-4)), 2),
        "avg_hold_days": round(float(np.mean(hold_days)) if hold_days else 0.0, 1),
        "pooled_wr": round(float(pooled_wr), 1),
        "avg_win_pct": round(float(np.mean(win_rets)) if win_rets else 0.0, 2),
        "avg_loss_pct": round(float(np.mean(loss_rets)) if loss_rets else 0.0, 2),
        "pooled_pf": round(float(pooled_pf), 2),
        "pooled_exp": round(float(np.mean(all_rets)) if all_rets else 0.0, 2),
        "mean_cum_ret": round(float(np.mean([r["total_return_pct"] for r in coin_rows])), 2) if coin_rows else 0.0,
        "mean_cagr": round(float(np.mean([r["cagr_pct"] for r in coin_rows])), 2) if coin_rows else 0.0,
        "mean_max_dd": round(float(np.mean([r["max_drawdown_pct"] for r in coin_rows])), 2) if coin_rows else 0.0,
        "mean_mar": round(float(np.mean([r["mar_ratio"] for r in coin_rows])), 2) if coin_rows else 0.0,
        "mean_sharpe": round(float(np.mean([r["sharpe"] for r in coin_rows])), 2) if coin_rows else 0.0,
        "mean_time_in_mkt": round(float(np.mean([r["time_in_market_pct"] for r in coin_rows])), 1) if coin_rows else 0.0,
        "port_cum_ret": round(float(port_cum_ret), 2),
        "port_cagr": round(float(port_cagr), 2),
        "port_max_dd": round(float(port_max_dd), 2),
        "port_mar": round(float(port_mar), 2),
        "port_sharpe": round(float(port_sharpe), 2),
        "total_funding_pnl": round(sum(float(r["total_funding_pnl"]) for r in coin_rows), 2),
        "total_fees_paid": round(sum(float(r["total_fees_paid"]) for r in coin_rows), 2),
    }


# ---------------------------------------------------------------------------
# Offline Synthetic Full-Cycle Dataset Generator
# ---------------------------------------------------------------------------

def make_synthetic_cycle_datasets(
    symbols: Sequence[str] = SYMBOLS,
    seed: int = 2026,
) -> Dict[str, Dict[str, Any]]:
    """
    Generate realistic multi-year crypto cycle Dataset C across all 5 symbols:
      - Full 1d OKX 16:00 UTC bars matching real DB horizons:
        BTC ~1500d (with pre-deriv bear crash -> bottom -> multi-year bull -> euphoria top -> bear crash)
        ETH/SOL ~1150d, HYPE ~610d, CC ~385d
      - Binance 00:00 UTC 1d derivatives starting later (~day 360 on BTC, exposing pre-deriv fallback)
      - Dual-format FundingRate starting later
    """
    rng = np.random.default_rng(seed)
    datasets_c: Dict[str, Dict[str, Any]] = {}

    end_1d_open = int(datetime(2026, 11, 21, 16, 0, tzinfo=timezone.utc).timestamp())
    coin_lengths = {
        "BTC": 1520,
        "ETH": 1180,
        "SOL": 1160,
        "HYPE": 610,
        "CC": 385,
    }
    base_prices = {
        "BTC": 32000.0,
        "ETH": 1600.0,
        "SOL": 22.0,
        "HYPE": 12.0,
        "CC": 0.07,
    }

    # Build a 1520-day canonical cycle trajectory in log-return regime segments so all coins
    # share realistic macro cycles (bear bottom -> bull + pullbacks -> euphoria top -> bear market),
    # with coin-specific volatility and launch offsets.
    n_master = 1520
    for sym_idx, sym in enumerate(symbols):
        coin = sym.split("/")[0].upper()
        n_bars = coin_lengths.get(coin, 900)
        start_open = end_1d_open - (n_bars - 1) * DAY_SEC
        vol_base = 0.024 if coin == "BTC" else (0.032 if coin in ("ETH", "SOL") else 0.040)
        p = base_prices.get(coin, 100.0)

        ohlcv_1d: List[Dict[str, Any]] = []
        master_offset = n_master - n_bars

        for d in range(n_bars):
            m_d = master_offset + d
            # Deterministic macro cycle regime drift on master timeline [0..1520):
            #   0..180: Bear capitulation (-55% drop -> FTX-style bottom around d=180)
            #   180..480: Recovery + Bull Phase 1 (+160% rally)
            #   480..540: Bull Regional Washout (-22% pullback)
            #   540..980: Main Bull Expansion + Euphoria Blow-off (+220% rally, euphoria ~930..980)
            #   980..1360: Secular Bear Market (-58% bear crash in OOS!)
            #   1360..1520: Base building + bounce
            if m_d < 160:
                drift = -0.0055
            elif m_d < 195:
                drift = -0.0095 if m_d < 180 else 0.0110
            elif m_d < 470:
                drift = 0.0042 + 0.0020 * math.sin(2.0 * math.pi * (m_d - 195) / 140.0)
            elif m_d < 520:
                drift = -0.0058
            elif m_d < 555:
                drift = 0.0085
            elif m_d < 920:
                drift = 0.0028 + 0.0018 * math.sin(2.0 * math.pi * (m_d - 555) / 160.0)
            elif m_d < 980:
                drift = 0.0075 if m_d < 960 else -0.0110
            elif m_d < 1120:
                drift = -0.0045
            elif m_d < 1350:
                drift = -0.0032 + 0.0015 * math.sin(2.0 * math.pi * (m_d - 1120) / 90.0)
            else:
                drift = 0.0030

            shock = float(rng.normal(drift, vol_base * 0.72))
            o = p
            c = max(base_prices.get(coin, 100.0) * 0.15, o * (1.0 + shock))
            wu = abs(float(rng.normal(0.0, vol_base * 0.45)))
            wd = abs(float(rng.normal(0.0, vol_base * 0.45)))
            h = max(o, c) * (1.0 + wu)
            l = min(o, c) * max(0.5, 1.0 - wd)
            t_d = start_open + d * DAY_SEC
            ohlcv_1d.append({
                "time": t_d,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": float(1e7 * (1.0 + 15.0 * abs(shock))),
            })
            p = c

        # Derivatives start after day 360 on BTC (matching pre-2023-07 no-derivs vs post-2023-07!),
        # and from day 0 (or day 5) on newer coins.
        deriv_start_d = 360 if coin == "BTC" else 0
        okx_1d_derivs: List[Dict[str, Any]] = []
        bin_1d_derivs: List[Dict[str, Any]] = []
        closes_arr = np.array([b["close"] for b in ohlcv_1d], dtype=float)

        for d in range(deriv_start_d, n_bars):
            bar = ohlcv_1d[d]
            t_okx = bar["time"]
            t_bin = t_okx - 57600  # 00:00 UTC same UTC date -> known before t_okx + 86400
            m_d = master_offset + d
            prev_c = closes_arr[max(0, d - 1)]
            ret1d = (bar["close"] - prev_c) / prev_c
            ret30d = (bar["close"] - closes_arr[max(0, d - 30)]) / closes_arr[max(0, d - 30)]

            # Coin OI expands in euphoria (m_d 900..980) and washes out in crashes (m_d 480..540, 1050..1350)
            oi_trend = 1.0 + 0.35 * math.tanh(ret30d * 3.0) + float(rng.normal(0.0, 0.025))
            coin_oi_level = max(1e5, 1e6 * oi_trend)
            oi_usd_okx = coin_oi_level * bar["close"] * 0.45
            oi_usd_bin = coin_oi_level * bar["close"] * 0.55

            # LSUR elevated at tops, depressed on washouts
            lsur_val = max(0.35, 1.15 + 0.45 * math.tanh(ret30d * 4.0) + float(rng.normal(0.0, 0.10)))
            if 910 <= m_d <= 970:
                lsur_val += 0.65
            elif 490 <= m_d <= 535 or 1320 <= m_d <= 1390:
                lsur_val = max(0.35, lsur_val - 0.50)

            tr_val = min(0.75, max(0.25, 0.50 + 0.16 * math.tanh(ret1d * 14.0) + float(rng.normal(0.0, 0.03))))
            tot_vol = 2e6
            okx_1d_derivs.append({
                "time": t_okx,
                "open_interest": oi_usd_okx,
                "long_short_ratio": lsur_val * 0.96,
                "taker_buy_vol": tot_vol * tr_val * 0.45,
                "taker_sell_vol": tot_vol * (1.0 - tr_val) * 0.45,
            })
            bin_1d_derivs.append({
                "time": t_bin,
                "open_interest": oi_usd_bin if d >= max(deriv_start_d, n_bars - 320) else None,
                "long_short_ratio": lsur_val,
                "taker_buy_vol": tot_vol * tr_val,
                "taker_sell_vol": tot_vol * (1.0 - tr_val),
            })

        # Dual-format FundingRate starting in later portion (last ~380 days, matching DB!)
        funding_start_d = max(0, n_bars - 380)
        funding_raw: List[Dict[str, Any]] = []
        for d in range(funding_start_d, n_bars):
            m_d = master_offset + d
            ret30d = (closes_arr[d] - closes_arr[max(0, d - 30)]) / closes_arr[max(0, d - 30)]
            base_fr = 0.00006 + 0.00014 * math.tanh(ret30d * 3.0) + float(rng.normal(0.0, 0.00003))
            if 910 <= m_d <= 975:
                base_fr = max(base_fr, 0.00025)
            t_day = ohlcv_1d[d]["time"]
            for h_off in (0, 28800, 57600):
                ft = t_day + h_off
                if d < funding_start_d + 120:
                    funding_raw.append({"time": ft, "symbol": f"{coin}/USDT:USDT", "funding_rate": base_fr})
                elif d < funding_start_d + 160:
                    funding_raw.append({"time": ft, "symbol": f"{coin}/USDT:USDT", "funding_rate": base_fr * 0.99})
                    funding_raw.append({"time": ft, "symbol": f"{coin}-USDT-SWAP", "funding_rate": base_fr})
                else:
                    funding_raw.append({"time": ft, "symbol": f"{coin}-USDT-SWAP", "funding_rate": base_fr})

        funding_dedup = rme.deduplicate_funding_records(funding_raw, coin=coin)
        deriv_1d_by_exch = {"okx": okx_1d_derivs, "binance": bin_1d_derivs}
        datasets_c[sym] = build_dataset_c_from_raw(sym, ohlcv_1d, deriv_1d_by_exch, funding_dedup)

    return datasets_c


# ---------------------------------------------------------------------------
# Section 4: Automated Objective Falsification & Viability Verdict (H1..H5)
# ---------------------------------------------------------------------------

def _evaluate_cycle_verdict(
    section1_pooled: Sequence[Dict[str, Any]],
    bootstrap_rows: Sequence[Dict[str, Any]],
    section2_pooled: Sequence[Dict[str, Any]],
    section3_pooled: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    s1_map = {r["variant"]: r for r in section1_pooled}
    s2_map = {(r["variant"], float(r["slippage_bps"])): r for r in section2_pooled}
    s3_map = {r["variant"]: r for r in section3_pooled}
    boot_map = {(r["window"], r["variant_a"], r["variant_b"]): r for r in bootstrap_rows if r["scope"] == "POOLED"}

    checks: List[Dict[str, Any]] = []

    def add_check(name: str, passed: Optional[bool], detail: str) -> None:
        status = "PASS" if passed is True else ("FAIL" if passed is False else "INSUFFICIENT_N")
        checks.append({"check": name, "status": status, "passed": passed, "detail": detail})

    # H1: Cycle_PD_1d vs Legacy_v8_1d (Narrow production risk profile)
    c_pd_5 = s2_map.get(("Cycle_PD_1d", 5.0), {})
    c_pd_15 = s2_map.get(("Cycle_PD_1d", 15.0), {})
    leg_n_15 = s2_map.get(("Legacy_v8_1d (Narrow)", 15.0), {})
    if c_pd_15.get("total_trades", 0) < 3:
        add_check("H1_Cycle_vs_Legacy_Narrow", None, f"Sparse Cycle_PD_1d trades ({c_pd_15.get('total_trades', 0)} < 3)")
    else:
        h1_ok = (
            c_pd_15.get("pooled_pf", 0.0) > 1.0
            and c_pd_15.get("mean_cagr", -999.0) > leg_n_15.get("mean_cagr", -999.0)
            and c_pd_15.get("mean_mar", -999.0) > leg_n_15.get("mean_mar", -999.0)
            and c_pd_15.get("mean_sharpe", -999.0) > leg_n_15.get("mean_sharpe", -999.0)
        )
        add_check(
            "H1_Cycle_vs_Legacy_Narrow",
            bool(h1_ok),
            (
                f"Cycle_PD_1d@15bps PF={c_pd_15.get('pooled_pf', 0.0):.2f}, CAGR={c_pd_15.get('mean_cagr', 0.0):+.2f}%, "
                f"MAR={c_pd_15.get('mean_mar', 0.0):.2f}, Sharpe={c_pd_15.get('mean_sharpe', 0.0):.2f} vs "
                f"Legacy_Narrow PF={leg_n_15.get('pooled_pf', 0.0):.2f}, CAGR={leg_n_15.get('mean_cagr', 0.0):+.2f}%, "
                f"MAR={leg_n_15.get('mean_mar', 0.0):.2f}, Sharpe={leg_n_15.get('mean_sharpe', 0.0):.2f}"
            ),
        )

    # H2: Cycle_PD_1d vs Phase1_Macro_PD_1d (removing 3x ATR Chandelier)
    p1_15 = s2_map.get(("Phase1_Macro_PD_1d", 15.0), {})
    s1_cpd = s1_map.get("Cycle_PD_1d", {})
    s1_p1 = s1_map.get("Phase1_Macro_PD_1d (Bull)", {})
    if c_pd_15.get("total_trades", 0) < 3 or p1_15.get("total_trades", 0) < 3:
        add_check("H2_Cycle_vs_Phase1_Chandelier", None, "Insufficient trades for comparison")
    else:
        er_better = (
            s1_cpd.get("e_ratio_90d", 0.0) > s1_p1.get("e_ratio_90d", 0.0)
            or s1_cpd.get("e_ratio_180d", 0.0) > s1_p1.get("e_ratio_180d", 0.0)
        )
        h2_ok = (
            c_pd_15.get("pooled_pf", 0.0) > p1_15.get("pooled_pf", 0.0)
            and c_pd_15.get("mean_cagr", -999.0) > p1_15.get("mean_cagr", -999.0)
            and c_pd_15.get("mean_mar", -999.0) > p1_15.get("mean_mar", -999.0)
            and er_better
        )
        add_check(
            "H2_Cycle_vs_Phase1_Chandelier",
            bool(h2_ok),
            (
                f"Cycle_PD_1d@15bps PF={c_pd_15.get('pooled_pf', 0.0):.2f}, CAGR={c_pd_15.get('mean_cagr', 0.0):+.2f}%, "
                f"MAR={c_pd_15.get('mean_mar', 0.0):.2f}, ER90/180={s1_cpd.get('e_ratio_90d', 0.0):.2f}/{s1_cpd.get('e_ratio_180d', 0.0):.2f} "
                f"vs Phase1 PF={p1_15.get('pooled_pf', 0.0):.2f}, CAGR={p1_15.get('mean_cagr', 0.0):+.2f}%, "
                f"MAR={p1_15.get('mean_mar', 0.0):.2f}, ER90/180={s1_p1.get('e_ratio_90d', 0.0):.2f}/{s1_p1.get('e_ratio_180d', 0.0):.2f}"
            ),
        )

    # H3: Paired post-2023-07 Derivatives Gate value-add (Cycle_PD_1d vs Cycle_P_1d)
    b_deriv = boot_map.get(("Post2023_07_HasDeriv", "Cycle_PD_1d", "Cycle_P_1d"), {})
    c_p_15 = s2_map.get(("Cycle_P_1d", 15.0), {})
    s3_cpd = s3_map.get("Cycle_PD_1d", {})
    s3_cp = s3_map.get("Cycle_P_1d", {})
    if b_deriv.get("n_a_90d", 0) < 5 or b_deriv.get("n_b_90d", 0) < 5:
        add_check(
            "H3_Derivatives_Gate_ValueAdd",
            None,
            (
                f"Sparse post-2023-07 sample (N_PD={b_deriv.get('n_a_90d', 0)}, N_P={b_deriv.get('n_b_90d', 0)} < 5); "
                f"Full15bps MAR {c_pd_15.get('mean_mar', 0.0):.2f} vs {c_p_15.get('mean_mar', 0.0):.2f}"
            ),
        )
    else:
        stat_ok = (
            (b_deriv["ret_90d_a"] > b_deriv["ret_90d_b"] and b_deriv["p_ret_90d"] <= 0.10)
            or (b_deriv["ret_180d_a"] > b_deriv["ret_180d_b"] and b_deriv["p_ret_180d"] <= 0.10)
            or (b_deriv["er_90d_a"] > b_deriv["er_90d_b"] and b_deriv["p_er_90d"] <= 0.10)
            or (b_deriv["er_180d_a"] > b_deriv["er_180d_b"] and b_deriv["p_er_180d"] <= 0.10)
        )
        risk_adj_ok = (
            c_pd_15.get("mean_mar", -999.0) > c_p_15.get("mean_mar", -999.0)
            and s3_cpd.get("oos_mean_mar", -999.0) >= s3_cp.get("oos_mean_mar", -999.0)
        )
        add_check(
            "H3_Derivatives_Gate_ValueAdd",
            bool(stat_ok and risk_adj_ok),
            (
                f"Paired HasDeriv N={b_deriv['n_a_90d']} vs {b_deriv['n_b_90d']}: "
                f"Ret90 {b_deriv['ret_90d_a']:+.2f}% vs {b_deriv['ret_90d_b']:+.2f}% (p={b_deriv['p_ret_90d']:.4f}), "
                f"ER90 {b_deriv['er_90d_a']:.2f} vs {b_deriv['er_90d_b']:.2f} (p={b_deriv['p_er_90d']:.4f}), "
                f"Full15bps MAR {c_pd_15.get('mean_mar', 0.0):.2f} vs {c_p_15.get('mean_mar', 0.0):.2f}, "
                f"OOS MAR {s3_cpd.get('oos_mean_mar', 0.0):.2f} vs {s3_cp.get('oos_mean_mar', 0.0):.2f}"
            ),
        )

    # H4: Cycle_PD_1d vs Buy_And_Hold Drawdown & MAR Protection
    bah_15 = s2_map.get(("Buy_And_Hold", 15.0), {})
    s3_bah = s3_map.get("Buy_And_Hold", {})
    if not bah_15 or not c_pd_15:
        add_check("H4_Drawdown_Protection_vs_BuyAndHold", None, "Missing backtest rows")
    else:
        h4_ok = (
            c_pd_15.get("mean_max_dd", 999.0) < bah_15.get("mean_max_dd", 0.0) * 0.65
            and c_pd_15.get("mean_mar", -999.0) > bah_15.get("mean_mar", -999.0)
            and s3_cpd.get("oos_mean_ret", -999.0) > s3_bah.get("oos_mean_ret", -999.0)
            and s3_cpd.get("oos_mean_dd", 999.0) < s3_bah.get("oos_mean_dd", 0.0)
        )
        add_check(
            "H4_Drawdown_Protection_vs_BuyAndHold",
            bool(h4_ok),
            (
                f"Full15bps MaxDD {c_pd_15.get('mean_max_dd', 0.0):.2f}% vs B&H {bah_15.get('mean_max_dd', 0.0):.2f}% | "
                f"MAR {c_pd_15.get('mean_mar', 0.0):.2f} vs {bah_15.get('mean_mar', 0.0):.2f} | "
                f"OOS Ret {s3_cpd.get('oos_mean_ret', 0.0):+.2f}% (DD {s3_cpd.get('oos_mean_dd', 0.0):.2f}%) "
                f"vs B&H {s3_bah.get('oos_mean_ret', 0.0):+.2f}% (DD {s3_bah.get('oos_mean_dd', 0.0):.2f}%)"
            ),
        )

    # H5: Blind OOS Survival & BearShort Extension
    bs_15 = s2_map.get(("Cycle_PD_BearShort_1d", 15.0), {})
    s3_bs = s3_map.get("Cycle_PD_BearShort_1d", {})
    if c_pd_15.get("total_trades", 0) < 3:
        add_check("H5_OOS_Bear_Survival_and_BearShort", None, "Insufficient trades for OOS survival check")
    else:
        h5_ok = (
            c_pd_15.get("pooled_pf", 0.0) > 1.2
            and c_pd_15.get("mean_cagr", -999.0) > 0.0
            and c_pd_5.get("mean_cagr", -999.0) > 0.0
            and s3_cpd.get("oos_mean_dd", 999.0) <= 30.0
            and s3_cpd.get("oos_mean_ret", -999.0) > s3_bah.get("oos_mean_ret", -999.0)
        )
        bs_adds_alpha = (
            bs_15.get("mean_mar", -999.0) > c_pd_15.get("mean_mar", -999.0)
            and s3_bs.get("oos_mean_mar", -999.0) > s3_cpd.get("oos_mean_mar", -999.0)
        )
        add_check(
            "H5_OOS_Bear_Survival_and_BearShort",
            bool(h5_ok),
            (
                f"Cycle_PD_1d Full15bps PF={c_pd_15.get('pooled_pf', 0.0):.2f}, CAGR={c_pd_15.get('mean_cagr', 0.0):+.2f}% | "
                f"OOS DD={s3_cpd.get('oos_mean_dd', 0.0):.2f}%, OOS Ret={s3_cpd.get('oos_mean_ret', 0.0):+.2f}% | "
                f"BearShort_15bps MAR={bs_15.get('mean_mar', 0.0):.2f} (OOS MAR={s3_bs.get('oos_mean_mar', 0.0):.2f}, "
                f"OOS Ret={s3_bs.get('oos_mean_ret', 0.0):+.2f}%, adds_alpha={bs_adds_alpha})"
            ),
        )

    passed_n = sum(1 for c in checks if c["passed"] is True)
    failed_n = sum(1 for c in checks if c["passed"] is False)
    insuff_n = sum(1 for c in checks if c["passed"] is None)

    by_name = {c["check"]: c["passed"] for c in checks}
    core_ok = all(
        by_name.get(k) is True
        for k in (
            "H1_Cycle_vs_Legacy_Narrow",
            "H2_Cycle_vs_Phase1_Chandelier",
            "H4_Drawdown_Protection_vs_BuyAndHold",
            "H5_OOS_Bear_Survival_and_BearShort",
        )
    )
    if core_ok and by_name.get("H3_Derivatives_Gate_ValueAdd") is True:
        verdict = "VALIDATED (FULL PRICE + DERIVATIVES CYCLE)"
    elif core_ok:
        verdict = "VALIDATED_PRICE_CYCLE (DERIVATIVES_UNPROVEN_OR_INSUFFICIENT)"
    elif insuff_n == len(checks):
        verdict = "INSUFFICIENT_DATA"
    elif passed_n >= 1:
        verdict = "PARTIAL / INCONCLUSIVE (SEE COMPONENT CHECKS)"
    else:
        verdict = "FALSIFIED"

    return {
        "alpha": 0.10,
        "overall_verdict": verdict,
        "passed_count": passed_n,
        "failed_count": failed_n,
        "insufficient_count": insuff_n,
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# Full Experiment Orchestration & Report Rendering
# ---------------------------------------------------------------------------

def _variant_order() -> List[str]:
    return [
        "Buy_And_Hold",
        "Legacy_v8_1d (Narrow)",
        "Legacy_v8_1d (CycleHold)",
        "Phase1_Macro_PD_1d",
        "Cycle_P_1d",
        "Cycle_PD_1d",
        "Cycle_PD_BearShort_1d",
    ]


def run_all_cycle_experiments(
    mode: str = "db",
    output_dir: Path = ROOT / "scripts" / "debug",
    session_factory: Optional[Callable[[], Any]] = None,
) -> Dict[str, Any]:
    if mode not in ("db", "synthetic"):
        raise ValueError(f"Unsupported mode: {mode!r} (expected 'db' or 'synthetic')")
    use_synthetic = (mode == "synthetic")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if use_synthetic:
        print("Running Phase 1.5 Macro Cycle Experiments in OFFLINE SYNTHETIC mode...")
        datasets_c = make_synthetic_cycle_datasets(SYMBOLS)
    else:
        print("Probing PostgreSQL for Dataset C (Full 1d Cycle)...")
        datasets_c = load_dataset_c_from_db(SYMBOLS, session_factory=session_factory)

    btc_ds_c = datasets_c.get("BTC/USDT")

    # Precompute causal cycle features, Legacy_v8_1d signals, Phase1_Macro_PD_1d signals
    cycle_features: Dict[str, pd.DataFrame] = {}
    legacy_signals: Dict[str, List[Dict[str, Any]]] = {}
    phase1_signals: Dict[str, List[Dict[str, Any]]] = {}
    has_deriv_maps: Dict[str, Dict[int, bool]] = {}

    for sym in SYMBOLS:
        ds = datasets_c.get(sym)
        if not ds or not ds.get("valid"):
            continue
        df_feat = evaluate_cycle_features_1d(ds["df_1d"])
        cycle_features[sym] = df_feat
        has_deriv_maps[sym] = {
            int(row["time"]): bool(row["has_deriv"])
            for _, row in df_feat.iterrows()
        }
        legacy_signals[sym] = rme.run_legacy_v8_signals(ds, btc_ds_c)
        p1_sigs, _ = rme.compute_1d_macro_signals(ds, "Macro_PD_1d")
        phase1_signals[sym] = p1_sigs

    # --- Section 0: Full-Cycle Dataset C Inventory ---
    inventory: List[Dict[str, Any]] = []
    for sym in SYMBOLS:
        ds = datasets_c.get(sym, {})
        valid = bool(ds.get("valid"))
        if valid:
            bars_all = ds["price_with_warmup"]
            min_px = min(float(b["low"]) for b in bars_all)
            max_px = max(float(b["high"]) for b in bars_all)
            last_px = float(bars_all[-1]["close"])
            bah_5 = simulate_buy_and_hold(
                sym, ds["eval_price"], funding_rates=ds["all_funding_settlements"], slippage_bps=5.0
            )["metrics"]
            bah_ret = float(bah_5["total_return_pct"])
            bah_dd = float(bah_5["max_drawdown_pct"])
        else:
            min_px = max_px = last_px = bah_ret = bah_dd = 0.0

        inventory.append({
            "symbol": sym,
            "valid": valid,
            "start_utc": rme._fmt_utc(ds.get("clean_start")) if valid else "N/A",
            "eval_start_utc": rme._fmt_utc(ds.get("eval_start")) if valid else "N/A",
            "end_utc": rme._fmt_utc(ds.get("clean_end")) if valid else "N/A",
            "deriv_start_utc": rme._fmt_utc(ds.get("deriv_start")) if valid and ds.get("deriv_start") else "None",
            "days": ds.get("clean_days", 0.0) if valid else 0.0,
            "total_bars": ds.get("total_bars", 0) if valid else 0,
            "warmup_bars": ds.get("warmup_bars", 0) if valid else 0,
            "eval_bars": ds.get("clean_bars", 0) if valid else 0,
            "min_price": round(min_px, 4),
            "max_price": round(max_px, 4),
            "last_price": round(last_px, 4),
            "bah_return_pct": round(bah_ret, 2),
            "bah_max_dd_pct": round(bah_dd, 2),
            "has_deriv_eval_bars": ds.get("has_deriv_eval_bars", 0) if valid else 0,
            "coin_oi_bars": ds.get("coin_oi_eval_bars", 0) if valid else 0,
            "taker_bars": ds.get("taker_eval_bars", 0) if valid else 0,
            "lsur_bars": ds.get("lsur_eval_bars", 0) if valid else 0,
            "fr_1d_bars": ds.get("funding_eval_bars", 0) if valid else 0,
            "funding_count": ds.get("funding_count", 0) if valid else 0,
            "reason": ds.get("reason", "") if not valid else "",
        })

    # --- Section 2 Full-Cycle Backtests (5 bps & 15 bps + Funding) & Cycle Signals ---
    section2_rows: List[Dict[str, Any]] = []
    section2_pooled: List[Dict[str, Any]] = []
    cycle_pd_trade_log: List[Dict[str, Any]] = []
    cycle_entry_signals_for_s1: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}

    for sym in SYMBOLS:
        ds = datasets_c.get(sym)
        if not ds or not ds.get("valid"):
            continue
        cycle_entry_signals_for_s1[(sym, "Legacy_v8_1d (Bull)")] = [
            s for s in legacy_signals[sym] if s.get("direction") == "bullish"
        ]
        cycle_entry_signals_for_s1[(sym, "Phase1_Macro_PD_1d (Bull)")] = [
            s for s in phase1_signals[sym] if s.get("direction") == "bullish"
        ]

    variants = _variant_order()
    for var in variants:
        for bps in SLIPPAGE_LEVELS:
            coin_rows: List[Dict[str, Any]] = []
            coin_stats: List[Dict[str, Any]] = []
            for sym in SYMBOLS:
                ds = datasets_c.get(sym)
                if not ds or not ds.get("valid"):
                    continue
                df_feat = cycle_features[sym]
                warmup = int(ds["warmup_bars"])
                funding_all = ds["all_funding_settlements"]

                if var == "Buy_And_Hold":
                    res = simulate_buy_and_hold(sym, ds["eval_price"], funding_rates=funding_all, slippage_bps=bps)
                elif var == "Legacy_v8_1d (Narrow)":
                    res = run_legacy_narrow_slice(ds, legacy_signals[sym], slippage_bps=bps)
                elif var == "Legacy_v8_1d (CycleHold)":
                    res = simulate_cycle_strategy(
                        sym,
                        df_feat,
                        "Legacy_v8_1d_CycleHold",
                        start_idx=warmup,
                        funding_rates=funding_all,
                        external_signals=legacy_signals[sym],
                        slippage_bps=bps,
                    )
                elif var == "Phase1_Macro_PD_1d":
                    res = run_phase1_wide_atr_slice(ds, phase1_signals[sym], slippage_bps=bps)
                elif var in ("Cycle_P_1d", "Cycle_PD_1d", "Cycle_PD_BearShort_1d"):
                    res = simulate_cycle_strategy(
                        sym,
                        df_feat,
                        var,
                        start_idx=warmup,
                        funding_rates=funding_all,
                        slippage_bps=bps,
                    )
                    if bps == 5.0 and var in ("Cycle_P_1d", "Cycle_PD_1d"):
                        cycle_entry_signals_for_s1[(sym, var)] = list(res["signals"])
                    if bps == 5.0 and var == "Cycle_PD_1d":
                        for pos in res["closed_positions"]:
                            net_ret = (pos.realized_pnl / pos.cost * 100.0) if pos.cost > 0.0 else 0.0
                            cycle_pd_trade_log.append({
                                "symbol": sym,
                                "entry_date": rme._fmt_utc(pos.entry_time)[:10],
                                "entry_price": round(float(pos.entry_price), 4),
                                "entry_type": pos.entry_type,
                                "exit_date": rme._fmt_utc(pos.exit_time)[:10],
                                "exit_price": round(float(pos.exit_price), 4),
                                "exit_reason": pos.exit_reason,
                                "hold_days": int(round((pos.exit_time - pos.entry_time) / float(DAY_SEC))),
                                "net_return_pct": round(float(net_ret), 2),
                                "peak_mfe_pct": round(float(pos.peak_mfe_pct()), 2),
                                "funding_pnl": round(float(pos.funding_pnl), 2),
                                "fees_paid": round(float(pos.fees_paid), 2),
                            })
                else:
                    raise ValueError(f"Unknown variant: {var}")

                m = dict(res["metrics"])
                coin_stats.append(m.pop("_trade_stats"))
                m["variant"] = var
                section2_rows.append(m)
                coin_rows.append(m)

            if coin_rows:
                pooled = _pool_cycle_stats(coin_rows, coin_stats)
                pooled["variant"] = var
                pooled["slippage_bps"] = float(bps)
                section2_pooled.append(pooled)

    # --- Section 1: Long-Horizon Bottom Entry Forward Quality (+30d, +90d, +180d) ---
    s1_variants = ["Legacy_v8_1d (Bull)", "Phase1_Macro_PD_1d (Bull)", "Cycle_P_1d", "Cycle_PD_1d"]
    section1_rows: List[Dict[str, Any]] = []
    section1_pooled: List[Dict[str, Any]] = []
    per_coin_outcomes: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    pooled_outcomes: Dict[str, List[Dict[str, Any]]] = {v: [] for v in s1_variants}

    for var in s1_variants:
        var_coin_rows: List[Dict[str, Any]] = []
        for sym in SYMBOLS:
            ds = datasets_c.get(sym)
            if not ds or not ds.get("valid"):
                continue
            sigs = cycle_entry_signals_for_s1.get((sym, var), [])
            outs = compute_long_horizon_outcomes(ds["eval_price"], sigs, has_deriv_by_time=has_deriv_maps[sym])
            per_coin_outcomes[(sym, var)] = outs
            pooled_outcomes[var].extend(outs)
            row = summarize_cycle_forward_metrics(
                symbol=sym,
                variant=var,
                clean_days=float(ds["clean_days"]),
                total_signals=len(sigs),
                outcomes=outs,
            )
            section1_rows.append(row)
            var_coin_rows.append(row)

        if var_coin_rows:
            tot_days = sum(float(r["clean_days"]) for r in var_coin_rows)
            tot_sigs = sum(int(r["signals"]) for r in var_coin_rows)
            pooled_row = summarize_cycle_forward_metrics(
                symbol="POOLED",
                variant=var,
                clean_days=tot_days,
                total_signals=tot_sigs,
                outcomes=pooled_outcomes[var],
            )
            pooled_row["total_asset_days"] = round(tot_days, 2)
            section1_pooled.append(pooled_row)

    bootstrap_rows = _build_cycle_bootstrap_comparisons(pooled_outcomes, per_coin_outcomes, SYMBOLS)

    # --- Section 3: Chronological 60% IS vs 40% OOS Blind Walk-Forward (5 bps, Independent Accounts) ---
    section3_rows: List[Dict[str, Any]] = []
    section3_pooled: List[Dict[str, Any]] = []

    for var in variants:
        wf_coin_rows: List[Dict[str, Any]] = []
        is_coin_rows: List[Dict[str, Any]] = []
        oos_coin_rows: List[Dict[str, Any]] = []
        is_stats: List[Dict[str, Any]] = []
        oos_stats: List[Dict[str, Any]] = []

        for sym in SYMBOLS:
            ds = datasets_c.get(sym)
            if not ds or not ds.get("valid") or len(ds["eval_price"]) < 40:
                continue
            df_feat = cycle_features[sym]
            warmup = int(ds["warmup_bars"])
            eval_candles = ds["eval_price"]
            split_rel = max(20, int(len(eval_candles) * 0.6))
            split_abs = warmup + split_rel
            is_slice = eval_candles[:split_rel]
            oos_slice = eval_candles[split_rel:]
            if len(oos_slice) < 10:
                continue

            funding_all = ds["all_funding_settlements"]

            def _run_slice(slice_candles: Sequence[Dict[str, Any]], abs_start: int, abs_end: int) -> Dict[str, Any]:
                if var == "Buy_And_Hold":
                    return simulate_buy_and_hold(sym, slice_candles, funding_rates=funding_all, slippage_bps=5.0)
                if var == "Legacy_v8_1d (Narrow)":
                    return run_legacy_narrow_slice(ds, legacy_signals[sym], price_slice=slice_candles, slippage_bps=5.0)
                if var == "Legacy_v8_1d (CycleHold)":
                    return simulate_cycle_strategy(
                        sym, df_feat, "Legacy_v8_1d_CycleHold",
                        start_idx=abs_start, end_idx=abs_end,
                        funding_rates=funding_all, external_signals=legacy_signals[sym], slippage_bps=5.0,
                    )
                if var == "Phase1_Macro_PD_1d":
                    return run_phase1_wide_atr_slice(ds, phase1_signals[sym], price_slice=slice_candles, slippage_bps=5.0)
                return simulate_cycle_strategy(
                    sym, df_feat, var,
                    start_idx=abs_start, end_idx=abs_end,
                    funding_rates=funding_all, slippage_bps=5.0,
                )

            res_is = _run_slice(is_slice, warmup, split_abs)
            res_oos = _run_slice(oos_slice, split_abs, len(df_feat))
            m_is = dict(res_is["metrics"])
            m_oos = dict(res_oos["metrics"])
            is_stats.append(m_is.pop("_trade_stats"))
            oos_stats.append(m_oos.pop("_trade_stats"))
            is_coin_rows.append(m_is)
            oos_coin_rows.append(m_oos)

            wf_row = {
                "symbol": sym,
                "variant": var,
                "is_start_utc": rme._fmt_utc(int(is_slice[0]["time"]))[:10],
                "is_end_utc": rme._fmt_utc(int(is_slice[-1]["time"]))[:10],
                "oos_start_utc": rme._fmt_utc(int(oos_slice[0]["time"]))[:10],
                "oos_end_utc": rme._fmt_utc(int(oos_slice[-1]["time"]))[:10],
                "is_days": m_is["days"],
                "is_trades": m_is["trades"],
                "is_wr": m_is["win_rate"],
                "is_pf": m_is["profit_factor"],
                "is_total_ret": m_is["total_return_pct"],
                "is_cagr": m_is["cagr_pct"],
                "is_dd": m_is["max_drawdown_pct"],
                "is_mar": m_is["mar_ratio"],
                "is_sharpe": m_is["sharpe"],
                "is_time_in_mkt": m_is["time_in_market_pct"],
                "oos_days": m_oos["days"],
                "oos_trades": m_oos["trades"],
                "oos_wr": m_oos["win_rate"],
                "oos_pf": m_oos["profit_factor"],
                "oos_total_ret": m_oos["total_return_pct"],
                "oos_cagr": m_oos["cagr_pct"],
                "oos_dd": m_oos["max_drawdown_pct"],
                "oos_mar": m_oos["mar_ratio"],
                "oos_sharpe": m_oos["sharpe"],
                "oos_time_in_mkt": m_oos["time_in_market_pct"],
            }
            section3_rows.append(wf_row)
            wf_coin_rows.append(wf_row)

        if wf_coin_rows:
            p_is = _pool_cycle_stats(is_coin_rows, is_stats)
            p_oos = _pool_cycle_stats(oos_coin_rows, oos_stats)
            section3_pooled.append({
                "variant": var,
                "targets": len(wf_coin_rows),
                "is_total_trades": p_is["total_trades"],
                "is_pooled_wr": p_is["pooled_wr"],
                "is_pooled_pf": p_is["pooled_pf"],
                "is_mean_ret": p_is["mean_cum_ret"],
                "is_mean_cagr": p_is["mean_cagr"],
                "is_mean_dd": p_is["mean_max_dd"],
                "is_mean_mar": p_is["mean_mar"],
                "is_mean_sharpe": p_is["mean_sharpe"],
                "is_port_ret": p_is["port_cum_ret"],
                "is_port_dd": p_is["port_max_dd"],
                "is_port_mar": p_is["port_mar"],
                "is_time_in_mkt": p_is["mean_time_in_mkt"],
                "oos_total_trades": p_oos["total_trades"],
                "oos_pooled_wr": p_oos["pooled_wr"],
                "oos_pooled_pf": p_oos["pooled_pf"],
                "oos_mean_ret": p_oos["mean_cum_ret"],
                "oos_mean_cagr": p_oos["mean_cagr"],
                "oos_mean_dd": p_oos["mean_max_dd"],
                "oos_mean_mar": p_oos["mean_mar"],
                "oos_mean_sharpe": p_oos["mean_sharpe"],
                "oos_port_ret": p_oos["port_cum_ret"],
                "oos_port_dd": p_oos["port_max_dd"],
                "oos_port_mar": p_oos["port_mar"],
                "oos_time_in_mkt": p_oos["mean_time_in_mkt"],
            })

    # --- Section 4: Automated Objective Falsification Verdict (H1..H5) ---
    section4 = _evaluate_cycle_verdict(
        section1_pooled=section1_pooled,
        bootstrap_rows=bootstrap_rows,
        section2_pooled=section2_pooled,
        section3_pooled=section3_pooled,
    )

    summary = rme._sanitize_json({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "synthetic": use_synthetic,
        "metadata": {
            "symbols": list(SYMBOLS),
            "dataset": "Dataset C (Full 1d Cycle)",
            "cooldown_bars": CYCLE_COOLDOWN_BARS,
            "long_notional_pct": LONG_NOTIONAL_PCT,
            "short_notional_pct": SHORT_NOTIONAL_PCT,
            "fee_rate": FEE_RATE,
            "slippage_bps_levels": list(SLIPPAGE_LEVELS),
            "wave_capture_definitions": {
                "wave_capture_30": "+30% MFE within +180d strictly before -15% MAE bar-by-bar",
                "wave_capture_50": "+50% MFE within +180d strictly before -20% MAE bar-by-bar",
            },
        },
        "section0_inventory": inventory,
        "section1_forward_per_coin": section1_rows,
        "section1_forward_pooled": section1_pooled,
        "section1_bootstrap": bootstrap_rows,
        "section2_backtest_per_coin": section2_rows,
        "section2_backtest_pooled": section2_pooled,
        "section2_cycle_pd_trade_log": cycle_pd_trade_log,
        "section3_walkforward_per_coin": section3_rows,
        "section3_walkforward_pooled": section3_pooled,
        "section4_verdict": section4,
    })

    md_text = render_cycle_markdown_report(summary)
    md_path = output_dir / "macro_cycle_report.md"
    json_path = output_dir / "macro_cycle_report.json"
    md_path.write_text(md_text, encoding="utf-8")
    json_path.write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    summary["md_path"] = str(md_path)
    summary["json_path"] = str(json_path)
    print(f"Saved report: {md_path}")
    print(f"Saved JSON:   {json_path}")
    return summary


def render_cycle_markdown_report(summary: Dict[str, Any]) -> str:
    lines: List[str] = [
        "# Solo-Quant Phase 1.5 Asymmetric Macro Cycle Empirical Research Report",
        f"**Generated at**: {summary['generated_at']} | **Mode**: `{summary['mode']}` | **Synthetic**: {summary['synthetic']}",
        "",
        "## 0. Full-Cycle Dataset C Inventory (`okx 1d` Full History)",
        "| Symbol | Valid | Start (UTC) | Eval Start (UTC) | End (UTC) | Days (Eval) | Bars (Total/Warmup/Eval) | Min -> Max -> Last Price | B&H Ret (%) | B&H MaxDD (%) | Deriv Start (UTC) | HasDeriv / CoinOI / Taker / LSUR / FR_1d |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]
    for inv in summary.get("section0_inventory", []):
        if inv["valid"]:
            px_rng = f"${inv['min_price']:,.2f} -> ${inv['max_price']:,.2f} -> ${inv['last_price']:,.2f}"
            bars_s = f"{inv['total_bars']}/{inv['warmup_bars']}/{inv['eval_bars']}"
            cov_s = (
                f"HasD={inv['has_deriv_eval_bars']}, OI={inv['coin_oi_bars']}, "
                f"Tk={inv['taker_bars']}, LSUR={inv['lsur_bars']}, FR={inv['fr_1d_bars']}"
            )
            deriv_st = inv["deriv_start_utc"][:10] if inv["deriv_start_utc"] != "None" else "None"
        else:
            px_rng = "N/A"
            bars_s = "0/0/0"
            cov_s = f"INVALID: {inv.get('reason', '')}"
            deriv_st = "N/A"
        lines.append(
            f"| {inv['symbol']} | {'YES' if inv['valid'] else 'NO'} | "
            f"{inv['start_utc'][:10]} | {inv['eval_start_utc'][:10]} | {inv['end_utc'][:10]} | "
            f"{inv['days']:.1f} | {bars_s} | {px_rng} | {inv['bah_return_pct']:+.2f}% | {inv['bah_max_dd_pct']:.2f}% | "
            f"{deriv_st} | {cov_s} |"
        )

    lines.extend([
        "",
        "## 1. Long-Horizon Bottom Entry Forward Quality (`+30d`, `+90d`, `+180d`)",
        "_Notes: `+30% Wave Capture` = `+30%` MFE within `+180d` strictly before `-15%` MAE; `+50% Wave Capture` = `+50%` MFE within `+180d` strictly before `-20%` MAE._",
        "",
        "### 1.1 Pooled Across Symbols",
        "| Variant | Signals | Signals/Yr | Hit@90d (%) | Hit@180d (%) | Mean Ret +30d (%) | Mean Ret +90d (%) | Mean Ret +180d (%) | Med MFE/MAE +90d (%) | Wave ER@90d | Med MFE/MAE +180d (%) | Wave ER@180d | +30% Wave Cap (%) | +50% Wave Cap (%) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for r in summary.get("section1_forward_pooled", []):
        lines.append(
            f"| {r['variant']} | {r['signals']} | {r['signals_per_yr']:.2f} | "
            f"{r['hit_90d']:.1f} | {r['hit_180d']:.1f} | "
            f"{r['ret_30d']:+.2f} | {r['ret_90d']:+.2f} | {r['ret_180d']:+.2f} | "
            f"{r['med_mfe_90d']:.2f} / {r['med_mae_90d']:.2f} | {r['e_ratio_90d']:.2f} | "
            f"{r['med_mfe_180d']:.2f} / {r['med_mae_180d']:.2f} | {r['e_ratio_180d']:.2f} | "
            f"{r['wave_capture_30_pct']:.1f} | {r['wave_capture_50_pct']:.1f} |"
        )

    lines.extend([
        "",
        "### 1.2 Per-Coin Breakdown",
        "| Symbol | Variant | Signals | Signals/Yr | Hit@90d (%) | Hit@180d (%) | Mean Ret +30d (%) | Mean Ret +90d (%) | Mean Ret +180d (%) | Med MFE/MAE +90d (%) | Wave ER@90d | Med MFE/MAE +180d (%) | Wave ER@180d | +30% Wave Cap (%) | +50% Wave Cap (%) |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for r in summary.get("section1_forward_per_coin", []):
        lines.append(
            f"| {r['symbol']} | {r['variant']} | {r['signals']} | {r['signals_per_yr']:.2f} | "
            f"{r['hit_90d']:.1f} | {r['hit_180d']:.1f} | "
            f"{r['ret_30d']:+.2f} | {r['ret_90d']:+.2f} | {r['ret_180d']:+.2f} | "
            f"{r['med_mfe_90d']:.2f} / {r['med_mae_90d']:.2f} | {r['e_ratio_90d']:.2f} | "
            f"{r['med_mfe_180d']:.2f} / {r['med_mae_180d']:.2f} | {r['e_ratio_180d']:.2f} | "
            f"{r['wave_capture_30_pct']:.1f} | {r['wave_capture_50_pct']:.1f} |"
        )

    lines.extend([
        "",
        "### 1.3 1,000x Bootstrap Significance Tests (Including Paired Post-2023-07 `has_deriv` Window)",
        "| Scope | Window | Comparison (A vs B) | N_90d (A/B) | Ret+30d A vs B | p(Ret@30d) | Ret+90d A vs B | p(Ret@90d) | Ret+180d A vs B | p(Ret@180d) | ER@90d A vs B | p(ER@90d) | ER@180d A vs B | p(ER@180d) |",
        "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for b in summary.get("section1_bootstrap", []):
        lines.append(
            f"| {b['scope']} | {b['window']} | {b['variant_a']} vs {b['variant_b']} | "
            f"{b['n_a_90d']}/{b['n_b_90d']} | "
            f"{b['ret_30d_a']:+.2f}% vs {b['ret_30d_b']:+.2f}% | {b['p_ret_30d']:.4f} | "
            f"{b['ret_90d_a']:+.2f}% vs {b['ret_90d_b']:+.2f}% | {b['p_ret_90d']:.4f} | "
            f"{b['ret_180d_a']:+.2f}% vs {b['ret_180d_b']:+.2f}% | {b['p_ret_180d']:.4f} | "
            f"{b['er_90d_a']:.2f} vs {b['er_90d_b']:.2f} | {b['p_er_90d']:.4f} | "
            f"{b['er_180d_a']:.2f} vs {b['er_180d_b']:.2f} | {b['p_er_180d']:.4f} |"
        )

    lines.extend([
        "",
        "## 2. Full-Cycle Portfolio Backtest (`0.95x` Long / `0.0x` Flat / `0.50x` BearShort, `0.05%` Fee + `5/15 bps` Slippage + Causal Funding)",
        "",
        "### 2.1 Pooled & Equal-Weight Portfolio Summary (`5 bps` & `15 bps`)",
        "| Variant | Slip (bps) | Trades | Trades/Yr | Avg Hold (d) | WR (%) | Avg Win / Loss (%) | Pooled PF | Mean Cum Ret (%) | Mean CAGR (%) | Mean MaxDD (%) | Mean MAR | Mean Sharpe | Time in Mkt (%) | EW Port Ret (%) | EW Port CAGR (%) | EW Port MaxDD (%) | EW Port MAR |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for r in summary.get("section2_backtest_pooled", []):
        lines.append(
            f"| {r['variant']} | {r['slippage_bps']:.0f} | {r['total_trades']} | {r['trades_per_yr']:.2f} | "
            f"{r['avg_hold_days']:.1f} | {r['pooled_wr']:.1f} | {r['avg_win_pct']:+.2f}% / {r['avg_loss_pct']:+.2f}% | "
            f"{r['pooled_pf']:.2f} | {r['mean_cum_ret']:+.2f} | {r['mean_cagr']:+.2f} | "
            f"{r['mean_max_dd']:.2f} | {r['mean_mar']:.2f} | {r['mean_sharpe']:.2f} | {r['mean_time_in_mkt']:.1f} | "
            f"{r['port_cum_ret']:+.2f} | {r['port_cagr']:+.2f} | {r['port_max_dd']:.2f} | {r['port_mar']:.2f} |"
        )

    lines.extend([
        "",
        "### 2.2 Per-Coin Full-Cycle Backtest Results",
        "| Symbol | Variant | Slip (bps) | Days | Trades | Trades/Yr | Avg Hold (d) | WR (%) | Avg Win / Loss (%) | PF | Cum Ret (%) | CAGR (%) | MaxDD (%) | MAR | Sharpe | Time in Mkt (%) | Funding ($) | Fees ($) |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for r in summary.get("section2_backtest_per_coin", []):
        lines.append(
            f"| {r['symbol']} | {r['variant']} | {r['slippage_bps']:.0f} | {r['days']:.0f} | "
            f"{r['trades']} | {r['trades_per_yr']:.2f} | {r['avg_hold_days']:.1f} | {r['win_rate']:.1f} | "
            f"{r['avg_win_pct']:+.2f}% / {r['avg_loss_pct']:+.2f}% | {r['profit_factor']:.2f} | "
            f"{r['total_return_pct']:+.2f} | {r['cagr_pct']:+.2f} | {r['max_drawdown_pct']:.2f} | "
            f"{r['mar_ratio']:.2f} | {r['sharpe']:.2f} | {r['time_in_market_pct']:.1f} | "
            f"{r['total_funding_pnl']:+.2f} | {r['total_fees_paid']:.2f} |"
        )

    lines.extend([
        "",
        "### 2.3 Complete Trade-by-Trade Cycle Log Table (`Cycle_PD_1d`, `5 bps`)",
        "| Symbol | Entry Date & Price & Entry Type | Exit Date & Price & Exit Reason | Hold Days | Net Return (%) | Peak MFE (%) | Funding ($) | Fees ($) |",
        "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: |",
    ])
    for t in summary.get("section2_cycle_pd_trade_log", []):
        ent_s = f"{t['entry_date']} @ ${t['entry_price']:,.4f} ({t['entry_type']})"
        ext_s = f"{t['exit_date']} @ ${t['exit_price']:,.4f} ({t['exit_reason']})"
        lines.append(
            f"| {t['symbol']} | {ent_s} | {ext_s} | {t['hold_days']} | "
            f"{t['net_return_pct']:+.2f}% | {t['peak_mfe_pct']:.2f}% | {t['funding_pnl']:+.2f} | {t['fees_paid']:.2f} |"
        )

    lines.extend([
        "",
        "## 3. Chronological `60% IS` vs `40% OOS` Blind Walk-Forward (`5 bps`, Independent Accounts at Boundaries)",
        "",
        "### 3.1 Pooled / Mean Walk-Forward Summary",
        "| Variant | IS Trades | IS WR (%) | IS PF | IS Mean Ret (%) | IS Mean CAGR (%) | IS Mean DD (%) | IS MAR | IS EW Ret (%) | IS EW DD (%) | IS Time (%) | OOS Trades | OOS WR (%) | OOS PF | OOS Mean Ret (%) | OOS Mean CAGR (%) | OOS Mean DD (%) | OOS MAR | OOS EW Ret (%) | OOS EW DD (%) | OOS Time (%) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for r in summary.get("section3_walkforward_pooled", []):
        lines.append(
            f"| {r['variant']} | {r['is_total_trades']} | {r['is_pooled_wr']:.1f} | {r['is_pooled_pf']:.2f} | "
            f"{r['is_mean_ret']:+.2f} | {r['is_mean_cagr']:+.2f} | {r['is_mean_dd']:.2f} | {r['is_mean_mar']:.2f} | "
            f"{r['is_port_ret']:+.2f} | {r['is_port_dd']:.2f} | {r['is_time_in_mkt']:.1f} | "
            f"{r['oos_total_trades']} | {r['oos_pooled_wr']:.1f} | {r['oos_pooled_pf']:.2f} | "
            f"{r['oos_mean_ret']:+.2f} | {r['oos_mean_cagr']:+.2f} | {r['oos_mean_dd']:.2f} | {r['oos_mean_mar']:.2f} | "
            f"{r['oos_port_ret']:+.2f} | {r['oos_port_dd']:.2f} | {r['oos_time_in_mkt']:.1f} |"
        )

    lines.extend([
        "",
        "### 3.2 Per-Coin Walk-Forward Breakdown",
        "| Symbol | Variant | IS Span | IS Trades | IS WR | IS PF | IS Ret (%) | IS DD (%) | IS MAR | OOS Span | OOS Trades | OOS WR | OOS PF | OOS Ret (%) | OOS DD (%) | OOS MAR | OOS Sharpe |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for r in summary.get("section3_walkforward_per_coin", []):
        is_span = f"{r['is_start_utc']}..{r['is_end_utc']}"
        oos_span = f"{r['oos_start_utc']}..{r['oos_end_utc']}"
        lines.append(
            f"| {r['symbol']} | {r['variant']} | {is_span} | {r['is_trades']} | {r['is_wr']:.1f} | {r['is_pf']:.2f} | "
            f"{r['is_total_ret']:+.2f} | {r['is_dd']:.2f} | {r['is_mar']:.2f} | "
            f"{oos_span} | {r['oos_trades']} | {r['oos_wr']:.1f} | {r['oos_pf']:.2f} | "
            f"{r['oos_total_ret']:+.2f} | {r['oos_dd']:.2f} | {r['oos_mar']:.2f} | {r['oos_sharpe']:.2f} |"
        )

    v = summary.get("section4_verdict", {})
    lines.extend([
        "",
        "## 4. Automated Objective Falsification & Viability Verdict (`H1..H5`)",
        f"**Overall Verdict**: `{v.get('overall_verdict', 'N/A')}` "
        f"(Passed: {v.get('passed_count', 0)}, Failed: {v.get('failed_count', 0)}, Insufficient_N: {v.get('insufficient_count', 0)})",
        "",
        "| Hypothesis / Check | Status | Quantitative Evidence |",
        "| :--- | :---: | :--- |",
    ])
    for chk in v.get("checks", []):
        lines.append(f"| {chk['check']} | **{chk['status']}** | {chk['detail']} |")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Solo-Quant Phase 1.5 Macro Cycle Empirical Research Runner")
    parser.add_argument(
        "--mode",
        choices=["db", "synthetic"],
        default="db",
        help="Data source mode: 'db' (PostgreSQL, default) or 'synthetic' (offline pipeline selftest).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(ROOT / "scripts" / "debug"),
        help="Directory to write macro_cycle_report.md and macro_cycle_report.json.",
    )
    args = parser.parse_args()
    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    run_all_cycle_experiments(mode=args.mode, output_dir=out_dir)


if __name__ == "__main__":
    main()
