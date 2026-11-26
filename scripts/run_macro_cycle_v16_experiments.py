#!/usr/bin/env python3
"""
Phase 1.6 Empirical Research Prototype: Anti-Bear-Trap & Secular Hold-to-Top Cycle Model.

Evaluates pre-registered Phase 1.6 rules (zero coin-specific hacks, strictly causal,
zero .bfill(), zero inplace=True) on Fair Full-Cycle Dataset C
(warmup_bars = min(60, max(40, len(bars) // 6))) against 5 head-to-head variants:
  1) Buy_And_Hold (0.95x notional)
  2) Legacy_v8_1d (Conservative) (trailing_path_mode="conservative", risk_per_trade_pct=2.0, 1d profile)
  3) Phase15_Cycle_PD_1d (exact Phase 1.5 rules on identical warmup=60 Dataset C slice)
  4) Cycle_P_v16_1d (Long-Flat Pure Price Anti-Bear-Trap + Hold-to-Top)
  5) Cycle_PD_v16_1d (Long-Flat Price + Selective Derivatives Filter)

Outputs:
  - <output-dir>/macro_cycle_v16_report.md & .json

Usage:
  python scripts/run_macro_cycle_v16_experiments.py
  python scripts/run_macro_cycle_v16_experiments.py --mode db --output-dir scripts/debug
  python scripts/run_macro_cycle_v16_experiments.py --mode synthetic --output-dir scripts/debug/_v16_selftest
"""

from __future__ import annotations

import argparse
import json
import math
import sys
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
import scripts.run_macro_cycle_experiments as rmc
import scripts.run_macro_inflection_experiments as rme

SYMBOLS: List[str] = list(rmc.SYMBOLS)
DAY_SEC = rme.DAY_SEC
H1_SEC = rme.H1_SEC

CYCLE_COOLDOWN_BARS = 10
LONG_NOTIONAL_PCT = 0.95
FEE_RATE = 0.0005
SLIPPAGE_LEVELS: Tuple[float, ...] = (5.0, 15.0)


# ---------------------------------------------------------------------------
# Fair Full-Cycle Dataset C Builder (warmup_bars = min(60, max(40, n // 6)))
# ---------------------------------------------------------------------------

def build_dataset_c_v16_from_raw(
    symbol: str,
    ohlcv_1d_raw: Sequence[Dict[str, Any]],
    deriv_1d_by_exch: Dict[str, Sequence[Dict[str, Any]]],
    funding_settlements: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Build Fair Full-Cycle Dataset C for Phase 1.6:
      - Keeps ALL deduplicated OKX 1d OHLCV bars from DB start.
      - warmup_bars = min(60, max(40, len(bars) // 6))
      - Strict known_ts = t_row + 86400 causal alignment for 1d derivatives + dual FundingRate union.
      - Zero .bfill(), zero inplace=True.
    """
    candles_1d = rme.deduplicate_okx_1d_ohlcv(ohlcv_1d_raw)
    n = len(candles_1d)
    if n < 80:
        return {
            "symbol": symbol,
            "timeframe": "1d",
            "dataset_name": "Dataset C v16 (Full 1d Cycle, warmup=60)",
            "valid": False,
            "reason": f"Insufficient 1d OHLCV bars ({n} < 80)",
        }

    warmup_bars = min(60, max(40, n // 6))
    if n <= warmup_bars + 20:
        return {
            "symbol": symbol,
            "timeframe": "1d",
            "dataset_name": "Dataset C v16 (Full 1d Cycle, warmup=60)",
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
        "dataset_name": "Dataset C v16 (Full 1d Cycle, warmup=60)",
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


def load_dataset_c_v16_from_db(
    symbols: Sequence[str] = SYMBOLS,
    session_factory: Optional[Callable[[], Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Load Fair Full-Cycle Dataset C (warmup=60) from PostgreSQL (or injected SQLAlchemy session factory)."""
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
        datasets_c[sym] = build_dataset_c_v16_from_raw(sym, ohlcv_1d_raw, deriv_1d_by_exch, funding_settlements)

    return datasets_c


# ---------------------------------------------------------------------------
# Phase 1.6 Anti-Bear-Trap & Secular Hold-to-Top Feature Engine (Causal)
# ---------------------------------------------------------------------------

def evaluate_cycle_v16_features_1d(df_1d: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all strictly causal Phase 1.6 daily indicators and path flags on df_1d.
    Zero .bfill(), zero inplace=True. Prefix 0..k produces identical values at 0..k-1.
    """
    df = df_1d.sort_values("time").reset_index(drop=True).copy()
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()
    atr14 = rme.compute_wilder_atr(high, low, close, period=14)
    rsi14 = rme.compute_wilder_rsi(close, period=14)

    close_pos = close.where(close > 1e-12, np.nan)
    ema200_pos = ema200.where(ema200 > 1e-12, np.nan)
    atr_pos = atr14.where(atr14 > 1e-12, np.nan)
    atr_pct = atr14 / close_pos
    atr_pct_median60 = atr_pct.rolling(window=60, min_periods=30).median()

    high_max_180d = high.rolling(window=180, min_periods=45).max()
    high_max_90d = high.rolling(window=90, min_periods=30).max()
    high_max_10d = high.rolling(window=10, min_periods=5).max()

    high_max_60_prev = high.rolling(window=60, min_periods=30).max().shift(1)
    high_max_30_prev = high.rolling(window=30, min_periods=30).max().shift(1)
    high_max_20_prev = high.rolling(window=20, min_periods=20).max().shift(1)

    low_min_20d = low.rolling(window=20, min_periods=10).min()
    low_min_20_prev = low.rolling(window=20, min_periods=20).min().shift(1)
    low_min_30_prev = low.rolling(window=30, min_periods=30).min().shift(1)

    rsi_min_10d = rsi14.rolling(window=10, min_periods=5).min()
    rsi_max_15d = rsi14.rolling(window=15, min_periods=5).max()

    ema50_shift10 = ema50.shift(10)
    ema200_shift20 = ema200.shift(20)

    # --- Entry Path A_v16: Secular Bear-to-Bull Reversal ---
    dd_180_pct = (high_max_180d - low) / high_max_180d.where(high_max_180d > 1e-12, np.nan)
    dyn_dd_180_thresh = np.clip(6.0 * atr_pct_median60, 0.30, 0.52)
    bear_left_bar_v16 = (
        ((dd_180_pct >= dyn_dd_180_thresh) | ((close / ema200_pos) <= 0.78))
        & (rsi_min_10d <= 33.0)
    ).fillna(False)
    bear_left_active_v16 = (
        bear_left_bar_v16.astype(int).rolling(window=90, min_periods=1).max() > 0
    ).fillna(False)
    bear_right_ok_v16 = (
        (ema20 > ema50)
        & (ema50 > ema50_shift10)
        & (
            ((close > ema200) & (close > high_max_30_prev))
            | ((close > high_max_60_prev) & (rsi14 >= 55.0))
        )
    ).fillna(False)
    path_a_v16_ok = bear_left_active_v16 & bear_right_ok_v16

    # --- Entry Path B_v16: Bull-Market Regional Value Bottom ---
    reg_context_ok_v16 = (
        (ema50 > ema200)
        & (ema200 > ema200_shift20)
        & ((close / ema200_pos) <= 1.35)
    ).fillna(False)
    dd_90_pct = (high_max_90d - low) / high_max_90d.where(high_max_90d > 1e-12, np.nan)
    dyn_dd_90_thresh = np.clip(4.0 * atr_pct_median60, 0.16, 0.36)
    reg_left_bar_v16 = (
        (dd_90_pct >= dyn_dd_90_thresh)
        & ((low <= ema50 * 0.98) | (low <= ema200 * 1.05))
        & (rsi_min_10d <= 42.0)
    ).fillna(False)
    reg_left_active_v16 = (
        reg_left_bar_v16.astype(int).rolling(window=35, min_periods=1).max() > 0
    ).fillna(False)
    reg_right_ok_v16 = (
        (close > ema50)
        & (ema20 >= ema50 * 0.995)
        & (ema50 >= ema50_shift10 * 0.998)
        & (close > high_max_20_prev)
    ).fillna(False)
    path_b_v16_ok = reg_context_ok_v16 & reg_left_active_v16 & reg_right_ok_v16

    # --- Entry Path C_v16: Secular Stage-2 Trend Ignition ---
    path_c_v16_ok = (
        (ema20 > ema50)
        & (ema50 > ema200)
        & (ema50 > ema50_shift10)
        & (ema200 >= ema200_shift20 * 0.998)
        & (close > high_max_60_prev)
        & ((close / ema200_pos) <= 1.40)
    ).fillna(False)

    # --- Causal Derivatives Features (180d min_periods=45, 90d min_periods=30, 60d min_periods=30) ---
    coin_oi = df["coin_oi"].astype(float)
    coin_oi_pos = coin_oi.where(coin_oi > 0.0, np.nan)
    coin_oi_max_60d = coin_oi_pos.rolling(window=60, min_periods=30).max()
    coin_oi_max_60d_pos = coin_oi_max_60d.where(coin_oi_max_60d > 0.0, np.nan)
    coin_oi_dd_60d = ((coin_oi_pos / coin_oi_max_60d_pos) - 1.0) * 100.0
    coin_oi_dd_60d = coin_oi_dd_60d.where(coin_oi_pos.notna() & coin_oi_max_60d_pos.notna(), np.nan)
    coin_oi_pct_180d = pd.Series(
        rme.rolling_percentile_causal(coin_oi_pos.to_numpy(dtype=float), window=180, min_periods=45),
        index=df.index,
    )

    funding_daily = df["funding_daily"].astype(float)
    fr_7d_raw = funding_daily.rolling(window=7, min_periods=1).mean()
    fr_7d_mean = pd.Series(
        np.where(funding_daily.notna(), fr_7d_raw.to_numpy(dtype=float), np.nan),
        index=df.index,
    )
    fr_pct_180d = pd.Series(
        rme.rolling_percentile_causal(funding_daily.to_numpy(dtype=float), window=180, min_periods=45),
        index=df.index,
    )
    lsur_z_90d = df["lsur_z_90d"].astype(float)

    taker_ratio_col = (
        df["taker_ratio"].astype(float)
        if "taker_ratio" in df.columns
        else pd.Series(np.nan, index=df.index)
    )
    has_deriv = (
        df["has_deriv"].fillna(False).astype(bool)
        if "has_deriv" in df.columns
        else (coin_oi_pos.notna() | taker_ratio_col.notna() | lsur_z_90d.notna() | funding_daily.notna())
    )

    # Selective Derivative Washout Gate (Path A W=60, Path B W=35)
    washout_evaluable_bar_v16 = (
        coin_oi_dd_60d.notna()
        | coin_oi_pct_180d.notna()
        | fr_7d_mean.notna()
        | lsur_z_90d.notna()
    )
    washout_bar_v16 = (
        (coin_oi_dd_60d <= -20.0)
        | (coin_oi_pct_180d <= 20.0)
        | (fr_7d_mean < 0.0)
        | (lsur_z_90d <= -1.3)
    ).fillna(False)

    has_washout_deriv_60d = (
        (has_deriv & washout_evaluable_bar_v16).astype(int).rolling(window=60, min_periods=1).max() > 0
    ).fillna(False)
    deriv_washout_60d = (
        (has_deriv & washout_bar_v16).astype(int).rolling(window=60, min_periods=1).max() > 0
    ).fillna(False)

    has_washout_deriv_35d = (
        (has_deriv & washout_evaluable_bar_v16).astype(int).rolling(window=35, min_periods=1).max() > 0
    ).fillna(False)
    deriv_washout_35d = (
        (has_deriv & washout_bar_v16).astype(int).rolling(window=35, min_periods=1).max() > 0
    ).fillna(False)

    # Path C Anti-Crowding Gate at bar i
    deriv_not_crowded_c = (
        (~has_deriv)
        | (
            (coin_oi_pct_180d.isna() | (coin_oi_pct_180d < 85.0))
            & (fr_pct_180d.isna() | (fr_pct_180d < 85.0))
        )
    ).fillna(True)

    # --- Exit 1_v16: Euphoria Climax + Distribution Breakdown ---
    mayer_10d = high_max_10d / ema200_pos
    euphoria_mayer_thresh = np.clip(1.0 + 12.0 * atr_pct_median60, 1.55, 2.20)
    euphoria_ext_atr = (high_max_10d - ema200) / atr_pos
    euphoria_price_bar_v16 = (
        (mayer_10d >= euphoria_mayer_thresh)
        & (euphoria_ext_atr >= 5.5)
        & (rsi_max_15d >= 76.0)
    ).fillna(False)
    euphoria_price_30d_v16 = (
        euphoria_price_bar_v16.astype(int).rolling(window=30, min_periods=1).max() > 0
    ).fillna(False)

    exit_deriv_evaluable_bar_v16 = (
        coin_oi_pct_180d.notna()
        & (fr_pct_180d.notna() | fr_7d_mean.notna() | lsur_z_90d.notna())
    )
    has_exit_deriv_30d_v16 = (
        (has_deriv & exit_deriv_evaluable_bar_v16).astype(int).rolling(window=30, min_periods=1).max() > 0
    ).fillna(False)

    deriv_overheated_bar_v16 = (
        (coin_oi_pct_180d >= 80.0)
        & ((fr_pct_180d >= 80.0) | (fr_7d_mean >= 0.00020) | (lsur_z_90d >= 1.2))
    ).fillna(False)
    deriv_overheated_30d_v16 = (
        (has_deriv & deriv_overheated_bar_v16).astype(int).rolling(window=30, min_periods=1).max() > 0
    ).fillna(False)

    extreme_blowoff_bar_v16 = (
        (mayer_10d >= 2.0)
        & (rsi_max_15d >= 80.0)
    ).fillna(False)
    extreme_blowoff_30d_v16 = (
        extreme_blowoff_bar_v16.astype(int).rolling(window=30, min_periods=1).max() > 0
    ).fillna(False)

    euphoria_breakdown_right_v16 = (
        (close < ema20)
        & (close < low_min_20_prev)
    ).fillna(False)

    # --- Exit 2_v16: Secular Bear Regime Breakdown ---
    regime_bear_exit_v16 = (
        (close < ema50)
        & (ema20 < ema50)
        & (close < low_min_30_prev)
        & ((close < ema200) | (ema50 < ema50_shift10))
    ).fillna(False)

    df["ema20"] = ema20
    df["ema50"] = ema50
    df["ema200"] = ema200
    df["atr14"] = atr14
    df["rsi14"] = rsi14
    df["atr_pct"] = atr_pct
    df["atr_pct_median60"] = atr_pct_median60
    df["low_min_20d"] = low_min_20d
    df["dd_180_pct"] = dd_180_pct
    df["dd_90_pct"] = dd_90_pct
    df["coin_oi_dd_60d"] = coin_oi_dd_60d
    df["coin_oi_pct_180d"] = coin_oi_pct_180d
    df["fr_7d_mean"] = fr_7d_mean
    df["fr_pct_180d"] = fr_pct_180d
    df["has_deriv"] = has_deriv.to_numpy(dtype=bool)

    df["bear_left_active_v16"] = bear_left_active_v16.to_numpy(dtype=bool)
    df["reg_left_active_v16"] = reg_left_active_v16.to_numpy(dtype=bool)
    df["path_a_v16_ok"] = path_a_v16_ok.to_numpy(dtype=bool)
    df["path_b_v16_ok"] = path_b_v16_ok.to_numpy(dtype=bool)
    df["path_c_v16_ok"] = path_c_v16_ok.to_numpy(dtype=bool)

    df["washout_evaluable_bar_v16"] = washout_evaluable_bar_v16.to_numpy(dtype=bool)
    df["washout_bar_v16"] = washout_bar_v16.to_numpy(dtype=bool)
    df["has_washout_deriv_60d"] = has_washout_deriv_60d.to_numpy(dtype=bool)
    df["deriv_washout_60d"] = deriv_washout_60d.to_numpy(dtype=bool)
    df["has_washout_deriv_35d"] = has_washout_deriv_35d.to_numpy(dtype=bool)
    df["deriv_washout_35d"] = deriv_washout_35d.to_numpy(dtype=bool)
    df["deriv_not_crowded_c"] = deriv_not_crowded_c.to_numpy(dtype=bool)

    df["euphoria_price_30d_v16"] = euphoria_price_30d_v16.to_numpy(dtype=bool)
    df["has_exit_deriv_30d_v16"] = has_exit_deriv_30d_v16.to_numpy(dtype=bool)
    df["deriv_overheated_30d_v16"] = deriv_overheated_30d_v16.to_numpy(dtype=bool)
    df["extreme_blowoff_30d_v16"] = extreme_blowoff_30d_v16.to_numpy(dtype=bool)
    df["euphoria_breakdown_right_v16"] = euphoria_breakdown_right_v16.to_numpy(dtype=bool)
    df["regime_bear_exit_v16"] = regime_bear_exit_v16.to_numpy(dtype=bool)
    return df


# ---------------------------------------------------------------------------
# Phase 1.6 Simulation Engine & Legacy Conservative Benchmark Runner
# ---------------------------------------------------------------------------

def simulate_cycle_v16_strategy(
    symbol: str,
    df_feat: pd.DataFrame,
    variant: str,
    *,
    start_idx: int,
    end_idx: Optional[int] = None,
    funding_rates: Optional[Sequence[Dict[str, Any]]] = None,
    slippage_bps: float = 5.0,
    fee_rate: float = FEE_RATE,
    investment: float = 10000.0,
    include_funding: bool = True,
) -> Dict[str, Any]:
    """
    Simulate Phase 1.6 asymmetric macro cycle strategy over df_feat[start_idx : end_idx].
    Supports:
      - 'Cycle_P_v16_1d'
      - 'Cycle_PD_v16_1d'
    """
    if variant not in ("Cycle_P_v16_1d", "Cycle_PD_v16_1d"):
        raise ValueError(f"Unsupported Phase 1.6 variant: {variant!r}")
    if start_idx < 0:
        raise ValueError(f"start_idx must be >= 0, got {start_idx!r}")

    n_total = len(df_feat)
    stop_idx = n_total if end_idx is None else min(n_total, int(end_idx))
    if start_idx >= stop_idx:
        empty_m = rmc.compute_unified_portfolio_metrics(
            symbol, [], [], investment=investment, final_balance=investment, slippage_bps=slippage_bps
        )
        return {"metrics": empty_m, "closed_positions": [], "equity_curve": [], "signals": [], "final_state": "FLAT"}

    use_deriv = (variant == "Cycle_PD_v16_1d")

    times = df_feat["time"].to_numpy(dtype=int)
    opens = df_feat["open"].to_numpy(dtype=float)
    highs = df_feat["high"].to_numpy(dtype=float)
    lows = df_feat["low"].to_numpy(dtype=float)
    closes = df_feat["close"].to_numpy(dtype=float)
    atr14 = df_feat["atr14"].to_numpy(dtype=float)
    low_min_20d = df_feat["low_min_20d"].to_numpy(dtype=float)

    path_a_ok = df_feat["path_a_v16_ok"].to_numpy(dtype=bool)
    path_b_ok = df_feat["path_b_v16_ok"].to_numpy(dtype=bool)
    path_c_ok = df_feat["path_c_v16_ok"].to_numpy(dtype=bool)

    has_washout_deriv_60d = df_feat["has_washout_deriv_60d"].to_numpy(dtype=bool)
    deriv_washout_60d = df_feat["deriv_washout_60d"].to_numpy(dtype=bool)
    has_washout_deriv_35d = df_feat["has_washout_deriv_35d"].to_numpy(dtype=bool)
    deriv_washout_35d = df_feat["deriv_washout_35d"].to_numpy(dtype=bool)
    deriv_not_crowded_c = df_feat["deriv_not_crowded_c"].to_numpy(dtype=bool)

    euphoria_price_30d = df_feat["euphoria_price_30d_v16"].to_numpy(dtype=bool)
    has_exit_deriv_30d = df_feat["has_exit_deriv_30d_v16"].to_numpy(dtype=bool)
    deriv_overheated_30d = df_feat["deriv_overheated_30d_v16"].to_numpy(dtype=bool)
    extreme_blowoff_30d = df_feat["extreme_blowoff_30d_v16"].to_numpy(dtype=bool)
    euphoria_breakdown_right = df_feat["euphoria_breakdown_right_v16"].to_numpy(dtype=bool)
    regime_bear_exit = df_feat["regime_bear_exit_v16"].to_numpy(dtype=bool)

    funding_events = rmc._prep_funding_events(funding_rates)
    f_idx = 0
    first_t = int(times[start_idx])
    while f_idx < len(funding_events) and funding_events[f_idx]["time"] <= first_t:
        f_idx += 1

    balance = float(investment)
    open_pos: Optional[rmc.CyclePosition] = None
    closed_positions: List[rmc.CyclePosition] = []
    entry_signals: List[Dict[str, Any]] = []
    equity_curve: List[Dict[str, Any]] = []
    total_fees = 0.0
    total_funding = 0.0
    bars_in_mkt = 0
    last_long_exit_idx = -1000

    def _calc_equity(px: float) -> float:
        if open_pos is None:
            return balance
        return balance + open_pos.size * px

    def _close_pos(pos: rmc.CyclePosition, fill_px: float, bar_i: int, reason: str) -> None:
        nonlocal balance, total_fees, open_pos, last_long_exit_idx
        raw_pnl = (fill_px - pos.entry_price) * pos.size
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
        last_long_exit_idx = bar_i
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

        # Step 1: Physical pre-close BASE_INVALIDATION_V16 (ONLY while pre-bar highest_since_entry < 1.25 * entry_price)
        if open_pos is not None and i > open_pos.entry_idx:
            if not open_pos.base_stop_disabled and open_pos.highest_since_entry < open_pos.entry_price * 1.25:
                if oi <= open_pos.base_stop:
                    fill = rmc._apply_slippage(oi, "long", is_entry=False, slippage_bps=slippage_bps)
                    _close_pos(open_pos, fill, i, "BASE_INVALIDATION_V16")
                    long_stopped_today = True
                elif li <= open_pos.base_stop:
                    raw_fill = min(open_pos.base_stop, hi)
                    fill = rmc._apply_slippage(raw_fill, "long", is_entry=False, slippage_bps=slippage_bps)
                    _close_pos(open_pos, fill, i, "BASE_INVALIDATION_V16")
                    long_stopped_today = True

            if open_pos is not None:
                if hi > open_pos.highest_since_entry:
                    open_pos.highest_since_entry = hi
                if li < open_pos.lowest_since_entry:
                    open_pos.lowest_since_entry = li
                if open_pos.highest_since_entry >= open_pos.entry_price * 1.25:
                    open_pos.base_stop_disabled = True

        # Step 2: Causal FundingRate settlement over (ti, next_t]
        while f_idx < len(funding_events) and funding_events[f_idx]["time"] <= next_t:
            fs = funding_events[f_idx]
            if include_funding and fs["time"] > ti and open_pos is not None:
                notional = open_pos.size * ci
                f_pnl = -notional * fs["funding_rate"]
                balance += f_pnl
                open_pos.funding_pnl += f_pnl
                total_funding += f_pnl
            f_idx += 1

        # Step 3: Close-based exits (i > entry_idx)
        closed_long_at_close = False
        if open_pos is not None and i > open_pos.entry_idx:
            gain_ok = (open_pos.highest_since_entry >= open_pos.entry_price * 1.45)
            if use_deriv and has_exit_deriv_30d[i]:
                euph_left = (bool(euphoria_price_30d[i]) and bool(deriv_overheated_30d[i])) or bool(extreme_blowoff_30d[i])
            else:
                euph_left = bool(euphoria_price_30d[i])

            exit_euphoria = gain_ok and euph_left and bool(euphoria_breakdown_right[i])
            exit_regime = bool(regime_bear_exit[i])

            if exit_euphoria:
                fill = rmc._apply_slippage(ci, "long", is_entry=False, slippage_bps=slippage_bps)
                _close_pos(open_pos, fill, i, "EUPHORIA_TOP_V16")
                closed_long_at_close = True
            elif exit_regime:
                fill = rmc._apply_slippage(ci, "long", is_entry=False, slippage_bps=slippage_bps)
                _close_pos(open_pos, fill, i, "REGIME_BEAR_EXIT_V16")
                closed_long_at_close = True

        # Step 4: Long entry gate when FLAT (after 10-day post-exit cooldown)
        if open_pos is None:
            long_cooldown_ok = (i - last_long_exit_idx >= CYCLE_COOLDOWN_BARS)
            if long_cooldown_ok and not closed_long_at_close and not long_stopped_today:
                if use_deriv:
                    pa = bool(path_a_ok[i]) and (not bool(has_washout_deriv_60d[i]) or bool(deriv_washout_60d[i]))
                    pb = bool(path_b_ok[i]) and (not bool(has_washout_deriv_35d[i]) or bool(deriv_washout_35d[i]))
                    pc = bool(path_c_ok[i]) and bool(deriv_not_crowded_c[i])
                else:
                    pa = bool(path_a_ok[i])
                    pb = bool(path_b_ok[i])
                    pc = bool(path_c_ok[i])

                entry_type: Optional[str] = None
                if pa:
                    entry_type = "BEAR_BOTTOM_V16"
                elif pb:
                    entry_type = "REGIONAL_BOTTOM_V16"
                elif pc:
                    entry_type = "STAGE2_IGNITION_V16"

                if entry_type is not None:
                    curr_eq = _calc_equity(ci)
                    if curr_eq > 0.0 and balance > 0.0:
                        ep = rmc._apply_slippage(ci, "long", is_entry=True, slippage_bps=slippage_bps)
                        atr_e = float(atr14[i]) if math.isfinite(atr14[i]) and atr14[i] > 0.0 else max(hi - li, ci * 0.01)
                        low20_e = float(low_min_20d[i]) if math.isfinite(low_min_20d[i]) and low_min_20d[i] > 0.0 else li
                        b_stop = max(ep - 3.0 * atr_e, low20_e * 0.98)
                        if b_stop >= ep:
                            b_stop = ep * 0.999

                        notional = min(balance, curr_eq) * LONG_NOTIONAL_PCT
                        size = notional / ep
                        cost = size * ep
                        if size > 0.0 and cost > 0.0:
                            e_fee = cost * fee_rate
                            balance -= (cost + e_fee)
                            total_fees += e_fee
                            open_pos = rmc.CyclePosition(
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

        if was_in_mkt_today or (open_pos is not None):
            bars_in_mkt += 1

        equity_curve.append({"time": ti, "value": _calc_equity(ci)})

    final_state = "FLAT" if open_pos is None else open_pos.side.upper()

    if open_pos is not None:
        last_idx = stop_idx - 1
        _close_pos(open_pos, float(closes[last_idx]), last_idx, "BACKTEST_END")
        if equity_curve:
            equity_curve[-1]["value"] = balance

    metrics = rmc.compute_unified_portfolio_metrics(
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


def run_legacy_conservative_slice(
    ds_c: Dict[str, Any],
    signals: Sequence[Dict[str, Any]],
    *,
    price_slice: Optional[Sequence[Dict[str, Any]]] = None,
    slippage_bps: float = 5.0,
    investment: float = 10000.0,
) -> Dict[str, Any]:
    """Run production IndicatorEngine signals through Legacy v8 1d optimal profile with strict conservative path mode."""
    candles = list(price_slice) if price_slice is not None else list(ds_c["eval_price"])
    if not candles:
        return {
            "metrics": rmc.compute_unified_portfolio_metrics(
                ds_c["symbol"], [], [], investment=investment, final_balance=investment, slippage_bps=slippage_bps
            ),
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
        trailing_path_mode="conservative",
        allow_short=True,
        reverse_on_signal=True,
        enable_partial_tp=False,
    )
    cfg.validate()
    bt = SignalBacktester(cfg, candles, slice_sigs, funding_rates=slice_funding)
    res = bt.run()
    bars_mkt = rmc._count_bars_in_market(candles, bt.closed_positions)
    metrics = rmc.compute_unified_portfolio_metrics(
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
# Section 1: Bootstrap Comparisons & Section 4: Falsification Verdict (H1..H5)
# ---------------------------------------------------------------------------

def _build_cycle_v16_bootstrap_comparisons(
    pooled_outcomes: Dict[str, List[Dict[str, Any]]],
    per_coin_outcomes: Dict[Tuple[str, str], List[Dict[str, Any]]],
    symbols: Sequence[str],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    def _compare(
        scope: str,
        window_label: str,
        var_a: str,
        var_b: str,
        out_a: Sequence[Dict[str, Any]],
        out_b: Sequence[Dict[str, Any]],
    ) -> None:
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

    full_pairs = [
        ("Cycle_PD_v16_1d", "Cycle_P_v16_1d"),
        ("Cycle_PD_v16_1d", "Phase15_Cycle_PD_1d"),
        ("Cycle_PD_v16_1d", "Legacy_v8_1d (Bull)"),
        ("Cycle_P_v16_1d", "Phase15_Cycle_PD_1d"),
        ("Cycle_P_v16_1d", "Legacy_v8_1d (Bull)"),
    ]
    for var_a, var_b in full_pairs:
        _compare("POOLED", "Full_Cycle", var_a, var_b, pooled_outcomes.get(var_a, []), pooled_outcomes.get(var_b, []))
        for sym in symbols:
            _compare(sym, "Full_Cycle", var_a, var_b, per_coin_outcomes.get((sym, var_a), []), per_coin_outcomes.get((sym, var_b), []))

    # Paired Post2023_07_HasDeriv comparisons
    deriv_pairs = [
        ("Cycle_PD_v16_1d", "Cycle_P_v16_1d"),
        ("Cycle_PD_v16_1d", "Phase15_Cycle_PD_1d"),
    ]
    for var_a, var_b in deriv_pairs:
        pa_deriv = [o for o in pooled_outcomes.get(var_a, []) if o.get("has_deriv")]
        pb_deriv = [o for o in pooled_outcomes.get(var_b, []) if o.get("has_deriv")]
        _compare("POOLED", "Post2023_07_HasDeriv", var_a, var_b, pa_deriv, pb_deriv)
        for sym in symbols:
            ca = [o for o in per_coin_outcomes.get((sym, var_a), []) if o.get("has_deriv")]
            cb = [o for o in per_coin_outcomes.get((sym, var_b), []) if o.get("has_deriv")]
            _compare(sym, "Post2023_07_HasDeriv", var_a, var_b, ca, cb)

    return rows


def _evaluate_cycle_v16_verdict(
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

    pd16_5 = s2_map.get(("Cycle_PD_v16_1d", 5.0), {})
    pd16_15 = s2_map.get(("Cycle_PD_v16_1d", 15.0), {})
    p16_5 = s2_map.get(("Cycle_P_v16_1d", 5.0), {})
    p16_15 = s2_map.get(("Cycle_P_v16_1d", 15.0), {})
    p15_15 = s2_map.get(("Phase15_Cycle_PD_1d", 15.0), {})
    bah_15 = s2_map.get(("Buy_And_Hold", 15.0), {})

    s3_pd16 = s3_map.get("Cycle_PD_v16_1d", {})
    s3_p16 = s3_map.get("Cycle_P_v16_1d", {})
    s3_p15 = s3_map.get("Phase15_Cycle_PD_1d", {})
    s3_bah = s3_map.get("Buy_And_Hold", {})

    # H1: Beats Phase 1.5 Full-Cycle & OOS
    if pd16_15.get("total_trades", 0) < 3 or not s3_pd16 or not s3_p15:
        add_check(
            "H1_Beats_Phase15_FullCycle_and_OOS",
            None,
            f"Insufficient data for H1 (Cycle_PD_v16_1d trades={pd16_15.get('total_trades', 0)}, OOS={bool(s3_pd16)})",
        )
    else:
        h1_full = (
            pd16_15.get("pooled_pf", 0.0) > p15_15.get("pooled_pf", 0.0)
            and pd16_15.get("port_mar", -999.0) > p15_15.get("port_mar", -999.0)
            and pd16_15.get("port_cum_ret", -999.0) > p15_15.get("port_cum_ret", -999.0)
        )
        h1_oos = (
            s3_pd16.get("oos_pooled_pf", 0.0) > s3_p15.get("oos_pooled_pf", 0.0)
            and s3_pd16.get("oos_port_mar", -999.0) > s3_p15.get("oos_port_mar", -999.0)
            and s3_pd16.get("oos_port_ret", -999.0) > s3_p15.get("oos_port_ret", -999.0)
        )
        add_check(
            "H1_Beats_Phase15_FullCycle_and_OOS",
            bool(h1_full and h1_oos),
            (
                f"Full@15bps: PD_v16 PF={pd16_15.get('pooled_pf', 0.0):.2f}, EW Ret={pd16_15.get('port_cum_ret', 0.0):+.2f}%, "
                f"EW MAR={pd16_15.get('port_mar', 0.0):.2f} vs P1.5 PF={p15_15.get('pooled_pf', 0.0):.2f}, "
                f"EW Ret={p15_15.get('port_cum_ret', 0.0):+.2f}%, EW MAR={p15_15.get('port_mar', 0.0):.2f} | "
                f"OOS: PD_v16 PF={s3_pd16.get('oos_pooled_pf', 0.0):.2f}, EW Ret={s3_pd16.get('oos_port_ret', 0.0):+.2f}%, "
                f"EW MAR={s3_pd16.get('oos_port_mar', 0.0):.2f} vs P1.5 PF={s3_p15.get('oos_pooled_pf', 0.0):.2f}, "
                f"EW Ret={s3_p15.get('oos_port_ret', 0.0):+.2f}%, EW MAR={s3_p15.get('oos_port_mar', 0.0):.2f}"
            ),
        )

    # H2: EW Port MAR beats Buy&Hold with lower MaxDD
    if not bah_15 or not pd16_15 or pd16_15.get("total_trades", 0) < 1:
        add_check("H2_EW_Port_MAR_vs_BuyAndHold", None, "Missing trades or Buy_And_Hold baseline")
    else:
        h2_ok = (
            pd16_15.get("port_mar", -999.0) > bah_15.get("port_mar", -999.0)
            and pd16_15.get("port_max_dd", 999.0) < bah_15.get("port_max_dd", 0.0)
        )
        add_check(
            "H2_EW_Port_MAR_vs_BuyAndHold",
            bool(h2_ok),
            (
                f"Full@15bps PD_v16 EW MAR={pd16_15.get('port_mar', 0.0):.2f}, EW MaxDD={pd16_15.get('port_max_dd', 0.0):.2f}% "
                f"(Mean MaxDD={pd16_15.get('mean_max_dd', 0.0):.2f}%) vs "
                f"B&H EW MAR={bah_15.get('port_mar', 0.0):.2f}, EW MaxDD={bah_15.get('port_max_dd', 0.0):.2f}% "
                f"(Mean MaxDD={bah_15.get('mean_max_dd', 0.0):.2f}%)"
            ),
        )

    # H3: OOS Bear Protection: OOS EW DD <= 25% & beats Buy&Hold OOS Return by >= +15%
    if not s3_pd16 or not s3_bah:
        add_check("H3_OOS_Bear_Protection", None, "Missing OOS walk-forward results")
    else:
        oos_spread = s3_pd16.get("oos_port_ret", -999.0) - s3_bah.get("oos_port_ret", 0.0)
        h3_ok = (
            s3_pd16.get("oos_port_dd", 999.0) <= 25.0
            and oos_spread >= 15.0
        )
        add_check(
            "H3_OOS_Bear_Protection",
            bool(h3_ok),
            (
                f"OOS EW DD={s3_pd16.get('oos_port_dd', 0.0):.2f}% (<=25%), "
                f"OOS EW Ret={s3_pd16.get('oos_port_ret', 0.0):+.2f}% vs B&H {s3_bah.get('oos_port_ret', 0.0):+.2f}% "
                f"(spread={oos_spread:+.2f}%, target >=+15.00%; Mean OOS Ret {s3_pd16.get('oos_mean_ret', 0.0):+.2f}% "
                f"vs B&H {s3_bah.get('oos_mean_ret', 0.0):+.2f}%)"
            ),
        )

    # H4: Derivatives Selectivity: Cycle_PD_v16_1d differs from and improves Pooled PF / EW MAR over Cycle_P_v16_1d
    b_deriv = boot_map.get(("Post2023_07_HasDeriv", "Cycle_PD_v16_1d", "Cycle_P_v16_1d"), {})
    s1_pd = s1_map.get("Cycle_PD_v16_1d", {})
    s1_p = s1_map.get("Cycle_P_v16_1d", {})
    if pd16_15.get("total_trades", 0) < 1 or p16_15.get("total_trades", 0) < 1:
        add_check("H4_Derivatives_Selectivity", None, "Insufficient trades for Cycle_PD_v16_1d vs Cycle_P_v16_1d")
    else:
        differs = (
            pd16_15.get("total_trades", 0) != p16_15.get("total_trades", 0)
            or s1_pd.get("signals", 0) != s1_p.get("signals", 0)
            or abs(pd16_15.get("port_cum_ret", 0.0) - p16_15.get("port_cum_ret", 0.0)) > 1e-6
            or abs(pd16_15.get("pooled_pf", 0.0) - p16_15.get("pooled_pf", 0.0)) > 1e-6
        )
        improves = (
            pd16_15.get("pooled_pf", 0.0) > p16_15.get("pooled_pf", 0.0)
            and pd16_15.get("port_mar", -999.0) > p16_15.get("port_mar", -999.0)
        )
        add_check(
            "H4_Derivatives_Selectivity",
            bool(differs and improves),
            (
                f"Trades {pd16_15.get('total_trades', 0)} vs {p16_15.get('total_trades', 0)} | "
                f"@15bps PF={pd16_15.get('pooled_pf', 0.0):.2f} vs {p16_15.get('pooled_pf', 0.0):.2f}, "
                f"EW MAR={pd16_15.get('port_mar', 0.0):.2f} vs {p16_15.get('port_mar', 0.0):.2f} "
                f"(@5bps PF={pd16_5.get('pooled_pf', 0.0):.2f} vs {p16_5.get('pooled_pf', 0.0):.2f}, "
                f"EW MAR={pd16_5.get('port_mar', 0.0):.2f} vs {p16_5.get('port_mar', 0.0):.2f}) | "
                f"Post2023_07_HasDeriv N={b_deriv.get('n_a_90d', 0)}/{b_deriv.get('n_b_90d', 0)}, "
                f"Ret90={b_deriv.get('ret_90d_a', 0.0):+.2f}% vs {b_deriv.get('ret_90d_b', 0.0):+.2f}% "
                f"(p={b_deriv.get('p_ret_90d', 1.0):.4f})"
            ),
        )

    # H5: Cycle_PD_v16_1d @15 bps Pooled PF > 1.3 and positive EW Port Ret & Mean Cum Ret
    if pd16_15.get("total_trades", 0) < 3:
        add_check("H5_FullCycle_15bps_Viability", None, f"Sparse Cycle_PD_v16_1d trades ({pd16_15.get('total_trades', 0)} < 3)")
    else:
        h5_ok = (
            pd16_15.get("pooled_pf", 0.0) > 1.3
            and pd16_15.get("port_cum_ret", -999.0) > 0.0
            and pd16_15.get("mean_cum_ret", -999.0) > 0.0
        )
        add_check(
            "H5_FullCycle_15bps_Viability",
            bool(h5_ok),
            (
                f"PD_v16@15bps Pooled PF={pd16_15.get('pooled_pf', 0.0):.2f} (>1.3), "
                f"EW Port Ret={pd16_15.get('port_cum_ret', 0.0):+.2f}% (>0), "
                f"Mean Cum Ret={pd16_15.get('mean_cum_ret', 0.0):+.2f}% (>0), "
                f"OOS EW Ret={s3_pd16.get('oos_port_ret', 0.0):+.2f}%"
            ),
        )

    passed_n = sum(1 for c in checks if c["passed"] is True)
    failed_n = sum(1 for c in checks if c["passed"] is False)
    insuff_n = sum(1 for c in checks if c["passed"] is None)

    by_name = {c["check"]: c["passed"] for c in checks}
    core_ok = all(
        by_name.get(k) is True
        for k in (
            "H1_Beats_Phase15_FullCycle_and_OOS",
            "H2_EW_Port_MAR_vs_BuyAndHold",
            "H3_OOS_Bear_Protection",
            "H5_FullCycle_15bps_Viability",
        )
    )
    if core_ok and by_name.get("H4_Derivatives_Selectivity") is True:
        verdict = "VALIDATED (PHASE 1.6 ANTI-BEAR-TRAP + SELECTIVE DERIVATIVES)"
    elif core_ok:
        verdict = "VALIDATED_PRICE_CYCLE (DERIVATIVES_SELECTIVITY_UNPROVEN)"
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
# Offline Synthetic Full-Cycle Dataset Generator (warmup_bars = 60)
# ---------------------------------------------------------------------------

def make_synthetic_cycle_v16_datasets(
    symbols: Sequence[str] = SYMBOLS,
    seed: int = 2026,
) -> Dict[str, Dict[str, Any]]:
    """
    Generate realistic multi-year crypto cycle Dataset C v16 across all 5 symbols
    using build_dataset_c_v16_from_raw (warmup_bars = min(60, max(40, len // 6)) == 60).
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

    n_master = 1520
    for sym in symbols:
        coin = sym.split("/")[0].upper()
        n_bars = coin_lengths.get(coin, 900)
        start_open = end_1d_open - (n_bars - 1) * DAY_SEC
        vol_base = 0.024 if coin == "BTC" else (0.032 if coin in ("ETH", "SOL") else 0.040)
        p = base_prices.get(coin, 100.0)

        ohlcv_1d: List[Dict[str, Any]] = []
        master_offset = n_master - n_bars

        for d in range(n_bars):
            m_d = master_offset + d
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

        deriv_start_d = 360 if coin == "BTC" else 0
        okx_1d_derivs: List[Dict[str, Any]] = []
        bin_1d_derivs: List[Dict[str, Any]] = []
        closes_arr = np.array([b["close"] for b in ohlcv_1d], dtype=float)

        for d in range(deriv_start_d, n_bars):
            bar = ohlcv_1d[d]
            t_okx = bar["time"]
            t_bin = t_okx - 57600
            m_d = master_offset + d
            prev_c = closes_arr[max(0, d - 1)]
            ret1d = (bar["close"] - prev_c) / prev_c
            ret30d = (bar["close"] - closes_arr[max(0, d - 30)]) / closes_arr[max(0, d - 30)]

            oi_trend = 1.0 + 0.35 * math.tanh(ret30d * 3.0) + float(rng.normal(0.0, 0.025))
            coin_oi_level = max(1e5, 1e6 * oi_trend)
            oi_usd_okx = coin_oi_level * bar["close"] * 0.45
            oi_usd_bin = coin_oi_level * bar["close"] * 0.55

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
        datasets_c[sym] = build_dataset_c_v16_from_raw(sym, ohlcv_1d, deriv_1d_by_exch, funding_dedup)

    return datasets_c


# ---------------------------------------------------------------------------
# Experiment Orchestration & Report Rendering
# ---------------------------------------------------------------------------

def _variant_order() -> List[str]:
    return [
        "Buy_And_Hold",
        "Legacy_v8_1d (Conservative)",
        "Phase15_Cycle_PD_1d",
        "Cycle_P_v16_1d",
        "Cycle_PD_v16_1d",
    ]


def _format_trade_log_row(sym: str, pos: rmc.CyclePosition) -> Dict[str, Any]:
    net_ret = (pos.realized_pnl / pos.cost * 100.0) if pos.cost > 0.0 else 0.0
    return {
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
    }


def run_all_cycle_v16_experiments(
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
        print("Running Phase 1.6 Anti-Bear-Trap Macro Cycle Experiments in OFFLINE SYNTHETIC mode...")
        datasets_c = make_synthetic_cycle_v16_datasets(SYMBOLS)
    else:
        print("Probing PostgreSQL for Fair Full-Cycle Dataset C (warmup=60)...")
        datasets_c = load_dataset_c_v16_from_db(SYMBOLS, session_factory=session_factory)

    btc_ds_c = datasets_c.get("BTC/USDT")

    cycle_features_v16: Dict[str, pd.DataFrame] = {}
    cycle_features_p15: Dict[str, pd.DataFrame] = {}
    legacy_signals: Dict[str, List[Dict[str, Any]]] = {}
    has_deriv_maps: Dict[str, Dict[int, bool]] = {}

    for sym in SYMBOLS:
        ds = datasets_c.get(sym)
        if not ds or not ds.get("valid"):
            continue
        df_v16 = evaluate_cycle_v16_features_1d(ds["df_1d"])
        df_p15 = rmc.evaluate_cycle_features_1d(ds["df_1d"])
        cycle_features_v16[sym] = df_v16
        cycle_features_p15[sym] = df_p15
        has_deriv_maps[sym] = {
            int(row["time"]): bool(row["has_deriv"])
            for _, row in df_v16.iterrows()
        }
        legacy_signals[sym] = rme.run_legacy_v8_signals(ds, btc_ds_c)

    # --- Section 0: Fair Full-Cycle Dataset C Inventory ---
    inventory: List[Dict[str, Any]] = []
    for sym in SYMBOLS:
        ds = datasets_c.get(sym, {})
        valid = bool(ds.get("valid"))
        if valid:
            bars_all = ds["price_with_warmup"]
            min_px = min(float(b["low"]) for b in bars_all)
            max_px = max(float(b["high"]) for b in bars_all)
            last_px = float(bars_all[-1]["close"])
            bah_5 = rmc.simulate_buy_and_hold(
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

    # --- Section 2: Full-Cycle Portfolio Backtest (5 bps & 15 bps + Causal Funding) ---
    section2_rows: List[Dict[str, Any]] = []
    section2_pooled: List[Dict[str, Any]] = []
    cycle_p_v16_trade_log: List[Dict[str, Any]] = []
    cycle_pd_v16_trade_log: List[Dict[str, Any]] = []
    entry_signals_for_s1: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}

    for sym in SYMBOLS:
        ds = datasets_c.get(sym)
        if not ds or not ds.get("valid"):
            continue
        entry_signals_for_s1[(sym, "Legacy_v8_1d (Bull)")] = [
            s for s in legacy_signals[sym] if s.get("direction") == "bullish"
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
                warmup = int(ds["warmup_bars"])
                funding_all = ds["all_funding_settlements"]

                if var == "Buy_And_Hold":
                    res = rmc.simulate_buy_and_hold(sym, ds["eval_price"], funding_rates=funding_all, slippage_bps=bps)
                elif var == "Legacy_v8_1d (Conservative)":
                    res = run_legacy_conservative_slice(ds, legacy_signals[sym], slippage_bps=bps)
                elif var == "Phase15_Cycle_PD_1d":
                    res = rmc.simulate_cycle_strategy(
                        sym,
                        cycle_features_p15[sym],
                        "Cycle_PD_1d",
                        start_idx=warmup,
                        funding_rates=funding_all,
                        slippage_bps=bps,
                    )
                    if bps == 5.0:
                        entry_signals_for_s1[(sym, var)] = list(res["signals"])
                elif var in ("Cycle_P_v16_1d", "Cycle_PD_v16_1d"):
                    res = simulate_cycle_v16_strategy(
                        sym,
                        cycle_features_v16[sym],
                        var,
                        start_idx=warmup,
                        funding_rates=funding_all,
                        slippage_bps=bps,
                    )
                    if bps == 5.0:
                        entry_signals_for_s1[(sym, var)] = list(res["signals"])
                        target_log = cycle_p_v16_trade_log if var == "Cycle_P_v16_1d" else cycle_pd_v16_trade_log
                        for pos in res["closed_positions"]:
                            target_log.append(_format_trade_log_row(sym, pos))
                else:
                    raise ValueError(f"Unknown variant: {var}")

                m = dict(res["metrics"])
                coin_stats.append(m.pop("_trade_stats"))
                m["variant"] = var
                section2_rows.append(m)
                coin_rows.append(m)

            if coin_rows:
                pooled = rmc._pool_cycle_stats(coin_rows, coin_stats)
                pooled["variant"] = var
                pooled["slippage_bps"] = float(bps)
                section2_pooled.append(pooled)

    # --- Section 1: Long-Horizon Entry Forward Quality (+30d, +90d, +180d) ---
    s1_variants = ["Legacy_v8_1d (Bull)", "Phase15_Cycle_PD_1d", "Cycle_P_v16_1d", "Cycle_PD_v16_1d"]
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
            sigs = entry_signals_for_s1.get((sym, var), [])
            outs = rmc.compute_long_horizon_outcomes(ds["eval_price"], sigs, has_deriv_by_time=has_deriv_maps[sym])
            per_coin_outcomes[(sym, var)] = outs
            pooled_outcomes[var].extend(outs)
            row = rmc.summarize_cycle_forward_metrics(
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
            pooled_row = rmc.summarize_cycle_forward_metrics(
                symbol="POOLED",
                variant=var,
                clean_days=tot_days,
                total_signals=tot_sigs,
                outcomes=pooled_outcomes[var],
            )
            pooled_row["total_asset_days"] = round(tot_days, 2)
            section1_pooled.append(pooled_row)

    bootstrap_rows = _build_cycle_v16_bootstrap_comparisons(pooled_outcomes, per_coin_outcomes, SYMBOLS)

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
            warmup = int(ds["warmup_bars"])
            eval_candles = ds["eval_price"]
            split_rel = max(20, int(len(eval_candles) * 0.6))
            split_abs = warmup + split_rel
            is_slice = eval_candles[:split_rel]
            oos_slice = eval_candles[split_rel:]
            if len(oos_slice) < 10:
                continue

            funding_all = ds["all_funding_settlements"]
            n_df = len(cycle_features_v16[sym])

            def _run_slice(slice_candles: Sequence[Dict[str, Any]], abs_start: int, abs_end: int) -> Dict[str, Any]:
                if var == "Buy_And_Hold":
                    return rmc.simulate_buy_and_hold(sym, slice_candles, funding_rates=funding_all, slippage_bps=5.0)
                if var == "Legacy_v8_1d (Conservative)":
                    return run_legacy_conservative_slice(ds, legacy_signals[sym], price_slice=slice_candles, slippage_bps=5.0)
                if var == "Phase15_Cycle_PD_1d":
                    return rmc.simulate_cycle_strategy(
                        sym,
                        cycle_features_p15[sym],
                        "Cycle_PD_1d",
                        start_idx=abs_start,
                        end_idx=abs_end,
                        funding_rates=funding_all,
                        slippage_bps=5.0,
                    )
                return simulate_cycle_v16_strategy(
                    sym,
                    cycle_features_v16[sym],
                    var,
                    start_idx=abs_start,
                    end_idx=abs_end,
                    funding_rates=funding_all,
                    slippage_bps=5.0,
                )

            res_is = _run_slice(is_slice, warmup, split_abs)
            res_oos = _run_slice(oos_slice, split_abs, n_df)
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
            p_is = rmc._pool_cycle_stats(is_coin_rows, is_stats)
            p_oos = rmc._pool_cycle_stats(oos_coin_rows, oos_stats)
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
    section4 = _evaluate_cycle_v16_verdict(
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
            "dataset": "Dataset C v16 (Full 1d Cycle, warmup=min(60, max(40, n // 6)))",
            "cooldown_bars": CYCLE_COOLDOWN_BARS,
            "long_notional_pct": LONG_NOTIONAL_PCT,
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
        "section2_cycle_p_v16_trade_log": cycle_p_v16_trade_log,
        "section2_cycle_pd_v16_trade_log": cycle_pd_v16_trade_log,
        "section3_walkforward_per_coin": section3_rows,
        "section3_walkforward_pooled": section3_pooled,
        "section4_verdict": section4,
    })

    md_text = render_cycle_v16_markdown_report(summary)
    md_path = output_dir / "macro_cycle_v16_report.md"
    json_path = output_dir / "macro_cycle_v16_report.json"
    md_path.write_text(md_text, encoding="utf-8")
    json_path.write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    summary["md_path"] = str(md_path)
    summary["json_path"] = str(json_path)
    print(f"Saved report: {md_path}")
    print(f"Saved JSON:   {json_path}")
    return summary


def render_cycle_v16_markdown_report(summary: Dict[str, Any]) -> str:
    lines: List[str] = [
        "# Solo-Quant Phase 1.6 Anti-Bear-Trap & Secular Hold-to-Top Macro Cycle Research Report",
        f"**Generated at**: {summary['generated_at']} | **Mode**: `{summary['mode']}` | **Synthetic**: {summary['synthetic']}",
        "",
        "## 0. Full-Cycle Dataset C Inventory (`okx 1d` Full History, `warmup = min(60, max(40, n // 6))`)",
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
        "## 2. Full-Cycle Portfolio Backtest (`0.95x` Long / `0.0x` Flat, `0.05%` Fee + `5/15 bps` Slippage + Causal Funding)",
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
        "### 2.3 Complete Trade-by-Trade Cycle Log Table (`Cycle_P_v16_1d`, `5 bps`)",
        "| Symbol | Entry Date & Price & Entry Type | Exit Date & Price & Exit Reason | Hold Days | Net Return (%) | Peak MFE (%) | Funding ($) | Fees ($) |",
        "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: |",
    ])
    for t in summary.get("section2_cycle_p_v16_trade_log", []):
        ent_s = f"{t['entry_date']} @ ${t['entry_price']:,.4f} ({t['entry_type']})"
        ext_s = f"{t['exit_date']} @ ${t['exit_price']:,.4f} ({t['exit_reason']})"
        lines.append(
            f"| {t['symbol']} | {ent_s} | {ext_s} | {t['hold_days']} | "
            f"{t['net_return_pct']:+.2f}% | {t['peak_mfe_pct']:.2f}% | {t['funding_pnl']:+.2f} | {t['fees_paid']:.2f} |"
        )

    lines.extend([
        "",
        "### 2.4 Complete Trade-by-Trade Cycle Log Table (`Cycle_PD_v16_1d`, `5 bps`)",
        "| Symbol | Entry Date & Price & Entry Type | Exit Date & Price & Exit Reason | Hold Days | Net Return (%) | Peak MFE (%) | Funding ($) | Fees ($) |",
        "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: |",
    ])
    for t in summary.get("section2_cycle_pd_v16_trade_log", []):
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
        "| Variant | IS Trades | IS WR (%) | IS PF | IS Mean Ret (%) | IS Mean CAGR (%) | IS Mean DD (%) | IS MAR | IS EW Ret (%) | IS EW DD (%) | IS EW MAR | IS Time (%) | OOS Trades | OOS WR (%) | OOS PF | OOS Mean Ret (%) | OOS Mean CAGR (%) | OOS Mean DD (%) | OOS MAR | OOS EW Ret (%) | OOS EW DD (%) | OOS EW MAR | OOS Time (%) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for r in summary.get("section3_walkforward_pooled", []):
        lines.append(
            f"| {r['variant']} | {r['is_total_trades']} | {r['is_pooled_wr']:.1f} | {r['is_pooled_pf']:.2f} | "
            f"{r['is_mean_ret']:+.2f} | {r['is_mean_cagr']:+.2f} | {r['is_mean_dd']:.2f} | {r['is_mean_mar']:.2f} | "
            f"{r['is_port_ret']:+.2f} | {r['is_port_dd']:.2f} | {r['is_port_mar']:.2f} | {r['is_time_in_mkt']:.1f} | "
            f"{r['oos_total_trades']} | {r['oos_pooled_wr']:.1f} | {r['oos_pooled_pf']:.2f} | "
            f"{r['oos_mean_ret']:+.2f} | {r['oos_mean_cagr']:+.2f} | {r['oos_mean_dd']:.2f} | {r['oos_mean_mar']:.2f} | "
            f"{r['oos_port_ret']:+.2f} | {r['oos_port_dd']:.2f} | {r['oos_port_mar']:.2f} | {r['oos_time_in_mkt']:.1f} |"
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
    parser = argparse.ArgumentParser(description="Solo-Quant Phase 1.6 Anti-Bear-Trap Macro Cycle Empirical Research Runner")
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
        help="Directory to write macro_cycle_v16_report.md and macro_cycle_v16_report.json.",
    )
    args = parser.parse_args()
    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    run_all_cycle_v16_experiments(mode=args.mode, output_dir=out_dir)


if __name__ == "__main__":
    main()
