#!/usr/bin/env python3
"""
Standalone Quantitative Red-Team Audit & Falsification Experiment Suite.

Probes PostgreSQL for clean native sub-daily (1h / 4h) derivative windows
(strictly excluding 1D daily fallback rows), then executes:
  - Phase 0 / Stage 0: Raw Baseline snapshot
  - Phase 2 Experiment 1: Stage 0 -> 1A -> 1B -> 1C (0 / 5 / 15 bps + funding + exit architecture)
  - Phase 2 Experiment 2: Walk-Forward 60% IS / 40% OOS subtraction ablation (Variants B, C, D live + Pre-Pruning Variant A reference)
  - Phase 2 Experiment 3: Fixed-horizon (+4/+12/+24) forward return & MFE/MAE + 1000x Bootstrap p-value
                          comparing Group P vs Group D1 (retail LSUR) vs Group D2 (top_ls_position_ratio)

Usage:
  python scripts/run_audit_experiments.py
  python scripts/run_audit_experiments.py --mode db
  python scripts/run_audit_experiments.py --mode synthetic
  python scripts/run_audit_experiments.py --output-dir scripts/debug
  python scripts/run_audit_experiments.py --synthetic-selftest   # offline pipeline verification
"""

from __future__ import annotations

import argparse
import inspect
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.core.indicators import IndicatorEngine
from api.quant.signal_backtester import SignalBacktester
from api.quant.signal_strategy import SignalStrategyConfig, get_risk_profile

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "HYPE/USDT", "CC/USDT"]
TIMEFRAMES = ["1h", "4h"]
TF_SECONDS = {"1h": 3600, "4h": 14400}


# ---------------------------------------------------------------------------
# Causal cross-exchange merging helpers (NO .bfill() look-ahead)
# ---------------------------------------------------------------------------

def merge_oi_causal(okx_rows: List[Dict], bin_rows: List[Dict], period_seconds: int) -> List[Dict]:
    if not okx_rows and not bin_rows:
        return []
    df_okx = pd.DataFrame(okx_rows)
    df_bin = pd.DataFrame(bin_rows)

    if not df_okx.empty:
        df_okx["rounded_time"] = (df_okx["time"] // period_seconds) * period_seconds
        df_okx = df_okx.groupby("rounded_time")["value"].mean().reset_index().rename(columns={"rounded_time": "time"})
    if not df_bin.empty:
        df_bin["rounded_time"] = (df_bin["time"] // period_seconds) * period_seconds
        df_bin = df_bin.groupby("rounded_time")["value"].mean().reset_index().rename(columns={"rounded_time": "time"})

    if df_okx.empty:
        return df_bin.sort_values("time")[["time", "value"]].to_dict("records")
    if df_bin.empty:
        return df_okx.sort_values("time")[["time", "value"]].to_dict("records")

    merged = pd.merge(df_okx, df_bin, on="time", how="outer", suffixes=("_okx", "_bin")).sort_values("time")
    merged["value_okx"] = merged["value_okx"].ffill(limit=2)
    merged["value_bin"] = merged["value_bin"].ffill(limit=2)

    overlap = merged["value_okx"].notna() & merged["value_bin"].notna()
    if overlap.any():
        r_bin_arr = np.where(
            merged["value_okx"].notna() & (merged["value_bin"] > 0),
            (merged["value_okx"] + merged["value_bin"]) / merged["value_bin"],
            np.nan,
        )
        r_okx_arr = np.where(
            merged["value_bin"].notna() & (merged["value_okx"] > 0),
            (merged["value_okx"] + merged["value_bin"]) / merged["value_okx"],
            np.nan,
        )
        r_bin = pd.Series(r_bin_arr, index=merged.index).ffill().fillna(1.0)
        r_okx = pd.Series(r_okx_arr, index=merged.index).ffill().fillna(1.0)
        vals = []
        for idx, row in merged.iterrows():
            vo, vb = row["value_okx"], row["value_bin"]
            if pd.notna(vo) and pd.notna(vb):
                vals.append(float(vo + vb))
            elif pd.notna(vb):
                vals.append(float(vb * r_bin.loc[idx]))
            elif pd.notna(vo):
                vals.append(float(vo * r_okx.loc[idx]))
            else:
                vals.append(0.0)
        merged["value"] = vals
    else:
        merged["value"] = merged["value_okx"].fillna(0.0) + merged["value_bin"].fillna(0.0)
    return merged.sort_values("time")[["time", "value"]].to_dict("records")


def merge_lsur_causal(okx_rows: List[Dict], bin_rows: List[Dict], period_seconds: int) -> List[Dict]:
    if not okx_rows and not bin_rows:
        return []
    df_okx = pd.DataFrame(okx_rows)
    df_bin = pd.DataFrame(bin_rows)

    if not df_okx.empty:
        df_okx["rounded_time"] = (df_okx["time"] // period_seconds) * period_seconds
        df_okx = df_okx.groupby("rounded_time")["value"].mean().reset_index().rename(columns={"rounded_time": "time"})
    if not df_bin.empty:
        df_bin["rounded_time"] = (df_bin["time"] // period_seconds) * period_seconds
        df_bin = df_bin.groupby("rounded_time")["value"].mean().reset_index().rename(columns={"rounded_time": "time"})

    if df_okx.empty:
        return df_bin.sort_values("time")[["time", "value"]].to_dict("records")
    if df_bin.empty:
        return df_okx.sort_values("time")[["time", "value"]].to_dict("records")

    merged = pd.merge(df_okx, df_bin, on="time", how="outer", suffixes=("_okx", "_bin")).sort_values("time")
    merged = merged.reset_index(drop=True)
    overlap = merged["value_okx"].notna() & merged["value_bin"].notna()
    if overlap.any():
        r_bin_arr = np.where(
            merged["value_okx"].notna() & (merged["value_bin"] > 0),
            ((merged["value_okx"] + merged["value_bin"]) / 2.0) / merged["value_bin"],
            np.nan,
        )
        r_okx_arr = np.where(
            merged["value_bin"].notna() & (merged["value_okx"] > 0),
            ((merged["value_okx"] + merged["value_bin"]) / 2.0) / merged["value_okx"],
            np.nan,
        )
        r_bin = pd.Series(r_bin_arr, index=merged.index).ffill().fillna(1.0)
        r_okx = pd.Series(r_okx_arr, index=merged.index).ffill().fillna(1.0)
        vals = []
        for idx, row in merged.iterrows():
            vo, vb = row["value_okx"], row["value_bin"]
            if pd.notna(vo) and pd.notna(vb):
                vals.append(float((vo + vb) / 2.0))
            elif pd.notna(vb):
                vals.append(float(vb * r_bin.loc[idx]))
            elif pd.notna(vo):
                vals.append(float(vo * r_okx.loc[idx]))
            else:
                vals.append(1.0)
        merged["value"] = vals
    else:
        merged["value"] = merged["value_okx"].fillna(merged["value_bin"]).fillna(1.0)
    return merged.sort_values("time")[["time", "value"]].to_dict("records")


def _find_longest_recent_contiguous_window(
    timestamps: List[int],
    step_sec: int,
    max_gap_mult: int = 4,
) -> Tuple[Optional[int], Optional[int], int]:
    """Return (start_ts, end_ts, count) of the best contiguous segment (favoring longest recent run)."""
    if not timestamps:
        return None, None, 0
    ts_sorted = sorted(set(timestamps))
    max_gap = step_sec * max_gap_mult
    segments: List[Tuple[int, int, int]] = []
    seg_start = ts_sorted[0]
    seg_prev = ts_sorted[0]
    seg_count = 1
    for t in ts_sorted[1:]:
        if (t - seg_prev) <= max_gap:
            seg_prev = t
            seg_count += 1
        else:
            segments.append((seg_start, seg_prev, seg_count))
            seg_start = t
            seg_prev = t
            seg_count = 1
    segments.append((seg_start, seg_prev, seg_count))
    # Choose the segment with most observations (tie-break by most recent end_ts)
    best = max(segments, key=lambda s: (s[2], s[1]))
    return best


# ---------------------------------------------------------------------------
# Database Loader (strictly native sub-daily derivatives; zero 1d leakage)
# ---------------------------------------------------------------------------

def load_clean_dataset_from_db(symbol: str, timeframe: str, require_top_ls: bool = False) -> Dict[str, Any]:
    """
    Probe PostgreSQL for `symbol` and `timeframe` (`1h` or `4h`), isolate the
    longest contiguous native sub-daily derivatives window (excluding `1d`),
    and retain up to 250 prior native OHLCV bars solely for price-EMA/ATR warmup.

    When `require_top_ls=True`, restricts the contiguous window to timestamps where
    native `top_ls_position_ratio` is also present (Window B).
    """
    from api.db.database import SessionLocal
    from api.db.models import MarketDataPoint, FundingRate

    tf = timeframe.lower()
    step_sec = TF_SECONDS[tf]
    deriv_tfs = ["1h", "4h"] if tf == "4h" else ["1h"]
    base_asset = symbol.split("/")[0]
    funding_sym = f"{base_asset}-USDT-SWAP"

    with SessionLocal() as db:
        ohlcv_rows = (
            db.query(MarketDataPoint)
            .filter(
                MarketDataPoint.symbol == symbol,
                MarketDataPoint.timeframe == tf,
                MarketDataPoint.exchange == "okx",
                MarketDataPoint.open.isnot(None),
            )
            .order_by(MarketDataPoint.timestamp.asc())
            .all()
        )
        deriv_rows = (
            db.query(MarketDataPoint)
            .filter(
                MarketDataPoint.symbol == symbol,
                MarketDataPoint.timeframe.in_(deriv_tfs),
            )
            .order_by(MarketDataPoint.timestamp.asc())
            .all()
        )
        funding_rows = (
            db.query(FundingRate)
            .filter(
                FundingRate.symbol == funding_sym,
                FundingRate.exchange == "okx",
            )
            .order_by(FundingRate.timestamp.asc())
            .all()
        )

    price_all = [
        {
            "time": int(r.timestamp.replace(tzinfo=timezone.utc).timestamp()) if r.timestamp.tzinfo is None else int(r.timestamp.timestamp()),
            "open": float(r.open),
            "high": float(r.high),
            "low": float(r.low),
            "close": float(r.close),
            "volume": float(r.volume or 0.0),
        }
        for r in ohlcv_rows
        if r.open is not None and r.close is not None
    ]

    # Merge native '1h' rows (bucketed to step_sec) with any exact 'tf' rows,
    # preferring '1h' buckets on overlap so stale '4h' rows never mask fresh '1h' derivatives.
    def _row_ts(r) -> int:
        return int((r.timestamp if r.timestamp.tzinfo else r.timestamp.replace(tzinfo=timezone.utc)).timestamp())

    def collect_scalar_series(col_name: str, exchange: str) -> List[Dict]:
        by_bucket: Dict[int, List[float]] = {}
        exact_rows = [r for r in deriv_rows if r.exchange == exchange and r.timeframe == tf and getattr(r, col_name) is not None]
        for r in exact_rows:
            bucket = (_row_ts(r) // step_sec) * step_sec
            by_bucket.setdefault(bucket, []).append(float(getattr(r, col_name)))

        h1_buckets: Dict[int, List[float]] = {}
        if tf == "4h":
            for r in deriv_rows:
                if r.exchange == exchange and r.timeframe == "1h" and getattr(r, col_name) is not None:
                    bucket = (_row_ts(r) // step_sec) * step_sec
                    h1_buckets.setdefault(bucket, []).append(float(getattr(r, col_name)))
            for bucket, vals in h1_buckets.items():
                by_bucket[bucket] = vals

        return [
            {"time": b, "value": float(sum(vals) / len(vals))}
            for b, vals in sorted(by_bucket.items())
            if vals
        ]

    oi_okx = collect_scalar_series("open_interest", "okx")
    oi_bin = collect_scalar_series("open_interest", "binance")
    lsur_okx = collect_scalar_series("long_short_ratio", "okx")
    lsur_bin = collect_scalar_series("long_short_ratio", "binance")
    top_ls_agg = collect_scalar_series("top_ls_position_ratio", "binance")

    taker_by_bucket: Dict[int, List[Tuple[float, float]]] = {}
    for r in deriv_rows:
        if r.exchange == "binance" and r.timeframe == tf and r.taker_buy_vol is not None and r.taker_sell_vol is not None:
            bucket = (_row_ts(r) // step_sec) * step_sec
            taker_by_bucket.setdefault(bucket, []).append((float(r.taker_buy_vol), float(r.taker_sell_vol)))
    if tf == "4h":
        h1_taker: Dict[int, List[Tuple[float, float]]] = {}
        for r in deriv_rows:
            if r.exchange == "binance" and r.timeframe == "1h" and r.taker_buy_vol is not None and r.taker_sell_vol is not None:
                bucket = (_row_ts(r) // step_sec) * step_sec
                h1_taker.setdefault(bucket, []).append((float(r.taker_buy_vol), float(r.taker_sell_vol)))
        for bucket, pairs in h1_taker.items():
            taker_by_bucket[bucket] = pairs
    taker_agg = [
        {
            "time": b,
            "buy_vol": float(sum(p[0] for p in pairs)),
            "sell_vol": float(sum(p[1] for p in pairs)),
        }
        for b, pairs in sorted(taker_by_bucket.items())
        if pairs
    ]

    oi_merged = merge_oi_causal(oi_okx, oi_bin, step_sec)
    lsur_merged = merge_lsur_causal(lsur_okx, lsur_bin, step_sec)

    funding_settlements = [
        {
            "time": int((r.timestamp if r.timestamp.tzinfo else r.timestamp.replace(tzinfo=timezone.utc)).timestamp()),
            "funding_rate": float(r.funding_rate),
        }
        for r in funding_rows
        if r.funding_rate is not None
    ]

    return _assemble_clean_window(
        symbol=symbol,
        timeframe=tf,
        price_all=price_all,
        oi_series=oi_merged,
        taker_series=taker_agg,
        lsur_series=lsur_merged,
        top_ls_series=top_ls_agg,
        funding_settlements=funding_settlements,
        require_top_ls=require_top_ls,
    )


def _assemble_clean_window(
    symbol: str,
    timeframe: str,
    price_all: List[Dict],
    oi_series: List[Dict],
    taker_series: List[Dict],
    lsur_series: List[Dict],
    top_ls_series: List[Dict],
    funding_settlements: List[Dict],
    require_top_ls: bool = False,
) -> Dict[str, Any]:
    step_sec = TF_SECONDS[timeframe]

    price_times = {p["time"] for p in price_all}
    oi_times = {x["time"] for x in oi_series}
    lsur_times = {x["time"] for x in lsur_series}
    taker_times = {x["time"] for x in taker_series}
    top_times = {x["time"] for x in top_ls_series}

    # Core required streams: OHLCV + OI + LSUR (+ Top LS if required) (+ Taker if sufficient overlap exists for symbol)
    base_common = price_times & oi_times & lsur_times
    if require_top_ls:
        base_common = base_common & top_times
    taker_overlap = base_common & taker_times
    taker_available = len(taker_overlap) >= 24
    if taker_available:
        common_ts = sorted(taker_overlap)
    else:
        common_ts = sorted(base_common)

    clean_start, clean_end, clean_count = _find_longest_recent_contiguous_window(common_ts, step_sec=step_sec)

    if clean_start is None or clean_end is None or clean_count < 24:
        top_ls_clean_count = (
            len([x for x in top_ls_series if clean_start <= x["time"] <= clean_end])
            if clean_start is not None and clean_end is not None
            else 0
        )
        reason = f"Insufficient contiguous native data (count={clean_count}, taker_ok={taker_available})"
        if require_top_ls:
            reason += f" [require_top_ls=True, top_ls_total={len(top_times)}]"
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "valid": False,
            "reason": reason,
            "clean_start": clean_start,
            "clean_end": clean_end,
            "clean_days": 0.0,
            "top_ls_count": top_ls_clean_count,
            "top_ls_total_count": len(top_times),
            "taker_available": taker_available,
            "require_top_ls": require_top_ls,
        }

    # Include up to 250 prior OHLCV bars for EMA50/EMA200/ATR/Donchian warmup ONLY (no 1d derivatives!)
    prior_price = [p for p in price_all if p["time"] < clean_start][-250:]
    clean_price = [p for p in price_all if clean_start <= p["time"] <= clean_end]
    price_with_warmup = prior_price + clean_price

    # Skip first 14 bars of native derivative window for Z-score/OI percentile warmup
    eval_bars = [p for p in clean_price]
    deriv_warmup_bars = min(14, max(0, len(eval_bars) // 6))
    eval_start = eval_bars[deriv_warmup_bars]["time"] if len(eval_bars) > deriv_warmup_bars else clean_start

    # Restrict derivatives strictly to [clean_start, clean_end] (zero 1d pollution!)
    oi_clean = [x for x in oi_series if clean_start <= x["time"] <= clean_end]
    lsur_clean = [x for x in lsur_series if clean_start <= x["time"] <= clean_end]
    taker_clean = [x for x in taker_series if clean_start <= x["time"] <= clean_end]
    top_ls_clean = [x for x in top_ls_series if clean_start <= x["time"] <= clean_end]
    funding_clean = [
        f for f in funding_settlements
        if (clean_start - 8 * 3600) <= f["time"] <= (clean_end + step_sec)
    ]

    # Align series to price_with_warmup (derivatives start at clean_start; backward fill inside clean window only)
    df_p = pd.DataFrame(price_with_warmup).sort_values("time")

    def align_to_price(series: List[Dict], fill_zero: bool = False) -> List[Dict]:
        if not series:
            return []
        df_s = pd.DataFrame(series).sort_values("time")
        df_s = df_s[df_s["time"] >= clean_start]
        if df_s.empty:
            return []
        merged = pd.merge_asof(
            df_p[df_p["time"] >= clean_start][["time"]],
            df_s[["time", "value"]],
            on="time",
            direction="backward",
            tolerance=step_sec * 4,
        )
        if fill_zero:
            merged["value"] = merged["value"].ffill().fillna(0.0)
        else:
            merged = merged.dropna(subset=["value"])
        return merged[["time", "value"]].to_dict("records")

    oi_aligned = align_to_price(oi_clean)
    lsur_aligned = align_to_price(lsur_clean)
    top_ls_aligned = align_to_price(top_ls_clean)

    cvd_raw = IndicatorEngine.calculate_cvd_history(taker_clean) if taker_clean else []
    cvd_aligned = align_to_price(cvd_raw, fill_zero=True) if cvd_raw else []

    if funding_clean:
        df_f = pd.DataFrame([{"time": f["time"], "value": f["funding_rate"] * 100.0} for f in funding_clean]).sort_values("time")
        merged_f = pd.merge_asof(
            df_p[df_p["time"] >= clean_start][["time"]],
            df_f[["time", "value"]],
            on="time",
            direction="backward",
        )
        merged_f = merged_f.dropna(subset=["value"])
        funding_aligned = merged_f[["time", "value"]].to_dict("records")
    else:
        funding_aligned = []

    lsur_z_aligned = IndicatorEngine.calculate_lsur_z_score_history(lsur_aligned, window=90) if lsur_aligned else []
    top_ls_z_aligned = IndicatorEngine.calculate_lsur_z_score_history(top_ls_aligned, window=90) if top_ls_aligned else []
    oi_pct = IndicatorEngine.calculate_oi_percentile(oi_aligned) if oi_aligned else 50.0

    ema_trend = IndicatorEngine.calculate_ema_trend(price_with_warmup, symbol=symbol)
    rsi_hist = IndicatorEngine.calculate_rsi(price_with_warmup)
    bb_pctb = IndicatorEngine.calculate_bollinger_bands(price_with_warmup)["bb_pctb"]
    donchian_period = 48 if timeframe in ("15m", "1h") else 20
    donchian = IndicatorEngine.calculate_donchian_channel(price_with_warmup, period=donchian_period)
    macd_hist = IndicatorEngine.calculate_macd(price_with_warmup)

    clean_days = round((clean_end - eval_start) / 86400.0, 2)
    top_ls_eval_coverage = len([x for x in top_ls_aligned if x["time"] >= eval_start])

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "valid": True,
        "clean_start": clean_start,
        "eval_start": eval_start,
        "clean_end": clean_end,
        "clean_days": clean_days,
        "clean_bars": len([p for p in clean_price if p["time"] >= eval_start]),
        "warmup_bars": len(prior_price),
        "taker_available": taker_available,
        "top_ls_bars": top_ls_eval_coverage,
        "top_ls_count": len(top_ls_clean),
        "top_ls_total_count": len(top_times),
        "require_top_ls": require_top_ls,
        "funding_count": len(funding_clean),
        "price_with_warmup": price_with_warmup,
        "eval_price": [p for p in clean_price if p["time"] >= eval_start],
        "oi_aligned": oi_aligned,
        "oi_percentile": oi_pct,
        "cvd_aligned": cvd_aligned,
        "funding_aligned": funding_aligned,
        "funding_settlements": [f for f in funding_clean if f["time"] >= eval_start],
        "lsur_z_aligned": lsur_z_aligned,
        "top_ls_z_aligned": top_ls_z_aligned,
        "ema_fast": ema_trend["ema_fast"],
        "ema_slow": ema_trend["ema_slow"],
        "rsi_hist": rsi_hist,
        "bb_pctb": bb_pctb,
        "donchian": donchian,
        "macd_hist": macd_hist,
        "regime_history": IndicatorEngine.calculate_market_regime_history(price_with_warmup, cvd_aligned=cvd_aligned),
        "pulse_history": IndicatorEngine.calculate_composite_score(
            price_data=price_with_warmup,
            lsur_z_aligned=lsur_z_aligned,
            cvd_aligned=cvd_aligned,
            funding_aligned=funding_aligned,
            rsi_aligned=rsi_hist,
            ema_fast_aligned=ema_trend["ema_fast"],
            bb_pctb_aligned=bb_pctb,
            oi_aligned=oi_aligned,
            timeframe=timeframe,
            symbol=symbol,
            use_dynamic_profiles=True,
        ),
    }


def build_btc_macro_history(btc_ds: Optional[Dict[str, Any]]) -> Optional[List[Dict]]:
    if not btc_ds or not btc_ds.get("valid"):
        return None
    pulse_map = {p["time"]: p["value"] for p in btc_ds.get("pulse_history", [])}
    return [
        {
            "time": r["time"],
            "regime": r.get("regime", "ranging"),
            "direction": r.get("direction", "neutral"),
            "pulse": pulse_map.get(r["time"], 50.0),
        }
        for r in btc_ds.get("regime_history", [])
    ]


# ---------------------------------------------------------------------------
# Experiment Runners & Metrics
# ---------------------------------------------------------------------------

def generate_signals(
    ds: Dict[str, Any],
    htf_ds: Optional[Dict[str, Any]],
    btc_ds: Optional[Dict[str, Any]],
    *,
    mtf_close_aligned: bool = True,
    use_btc_history: bool = True,
    use_static_btc_leak: bool = False,
    setup_symmetry: bool = True,
    use_coin_oi_all: bool = True,
    price_group_cap: Optional[float] = None,
    single_trend_guard: bool = False,
    lsur_source: str = "lsur",
    price_only_mode: bool = False,
    enable_protection: bool = True,
    enable_mtf_filter: bool = True,
) -> List[Dict]:
    htf_regime = htf_ds["regime_history"] if (enable_mtf_filter and ds["timeframe"] == "1h" and htf_ds and htf_ds.get("valid")) else None
    btc_macro_hist = None
    btc_macro_static = None
    if "BTC" not in ds["symbol"]:
        if use_btc_history:
            btc_macro_hist = build_btc_macro_history(btc_ds)
        elif use_static_btc_leak:
            hist = build_btc_macro_history(btc_ds)
            if hist:
                btc_macro_static = hist[-1]

    if price_only_mode:
        z_series = []
        cvd_series = []
        funding_series = []
        oi_series = []
        oi_pct = 50.0
    else:
        z_series = ds["top_ls_z_aligned"] if lsur_source == "top_ls" else ds["lsur_z_aligned"]
        cvd_series = ds["cvd_aligned"]
        funding_series = ds["funding_aligned"]
        oi_series = ds["oi_aligned"]
        oi_pct = ds["oi_percentile"]

    markers, _ = IndicatorEngine.calculate_confluence_signals(
        price_data=ds["price_with_warmup"],
        lsur_z_aligned=z_series,
        cvd_aligned=cvd_series,
        oi_percentile=oi_pct,
        funding_aligned=funding_series,
        rsi_aligned=ds["rsi_hist"],
        ema_fast_aligned=ds["ema_fast"],
        ema_slow_aligned=ds["ema_slow"],
        bb_pctb_aligned=ds["bb_pctb"],
        donchian_aligned=ds["donchian"],
        macd_aligned=ds["macd_hist"],
        timeframe=ds["timeframe"],
        oi_aligned=oi_series,
        ranging_threshold=3,
        trending_threshold=3,
        enable_protection=enable_protection,
        symbol=ds["symbol"],
        use_dynamic_profiles=True,
        higher_tf_regime_history=htf_regime,
        btc_macro_regime=btc_macro_static,
        btc_macro_history=btc_macro_hist,
        mtf_close_aligned=mtf_close_aligned,
        setup_symmetry=setup_symmetry,
        use_coin_oi_all=use_coin_oi_all,
        price_group_cap=price_group_cap,
        single_trend_guard=single_trend_guard,
        price_only_mode=price_only_mode,
    )
    eval_start = ds["eval_start"]
    return [m for m in markers if m["time"] >= eval_start]


def run_backtest_slice(
    ds: Dict[str, Any],
    signals: List[Dict],
    *,
    price_slice: Optional[List[Dict]] = None,
    slippage_bps: float = 0.0,
    include_funding: bool = False,
    trailing_path_mode: str = "ohlc",
    enable_partial_tp: bool = False,
    trailing_atr_mult: float = 0.0,
    trailing_stop_pct_override: Optional[float] = None,
) -> Dict[str, Any]:
    candles = price_slice if price_slice is not None else ds["eval_price"]
    if not candles:
        return {}
    t0 = candles[0]["time"]
    t1 = candles[-1]["time"]
    step_sec = TF_SECONDS[ds["timeframe"]]
    slice_sigs = [s for s in signals if t0 <= s["time"] <= t1]
    slice_funding = [f for f in ds["funding_settlements"] if t0 <= f["time"] <= (t1 + step_sec)]

    profile = get_risk_profile(ds["symbol"], ds["timeframe"])
    trail_pct = trailing_stop_pct_override if trailing_stop_pct_override is not None else profile["trailing_stop_pct"]

    cfg = SignalStrategyConfig(
        symbol=ds["symbol"],
        investment=10000.0,
        risk_per_trade_pct=2.0,
        take_profit_pct=profile["take_profit_pct"],
        stop_loss_pct=profile["stop_loss_pct"],
        trailing_stop_pct=trail_pct,
        trailing_activation_pct=profile["trailing_activation_pct"],
        max_positions=1,
        fee_rate=0.0005,
        slippage_bps=slippage_bps,
        include_funding=include_funding,
        trailing_path_mode=trailing_path_mode,
        trailing_atr_mult=trailing_atr_mult,
        enable_partial_tp=enable_partial_tp,
        partial_tp_ratio=0.5,
        enable_protection=True,
        enable_mtf_filter=True,
        use_dynamic_profiles=True,
    )
    bt = SignalBacktester(cfg, candles, slice_sigs, funding_rates=slice_funding)
    res = bt.run()

    days = max((t1 - t0) / 86400.0, 1.0)
    m = res["metrics"]
    closed = bt.closed_positions
    trade_rets = [
        (p.realized_pnl / p.initial_cost * 100.0) if p.initial_cost > 0 else 0.0
        for p in closed
    ]
    expectancy_pct = float(np.mean(trade_rets)) if trade_rets else 0.0

    final_bal = float(res["final_balance"])
    init_bal = cfg.investment
    total_ret_pct = (final_bal - init_bal) / init_bal * 100.0
    if final_bal > 0:
        ann_ret_pct = ((final_bal / init_bal) ** (365.0 / days) - 1.0) * 100.0
    else:
        ann_ret_pct = -100.0
    max_dd = float(m["max_drawdown_pct"])
    mar = (ann_ret_pct / max(max_dd, 0.01)) if max_dd > 0 else (999.0 if ann_ret_pct > 0 else 0.0)
    avg_mfe = float(m.get("avg_mfe_pct", 0.0))
    avg_mae = float(m.get("avg_mae_pct", 0.0))
    mfe_mae_ratio = (avg_mfe / avg_mae) if avg_mae > 0 else 0.0

    return {
        "symbol": ds["symbol"],
        "timeframe": ds["timeframe"],
        "clean_days": round(days, 2),
        "trades": int(m["total_trades"]),
        "win_rate": float(m["win_rate"]),
        "profit_factor": float(m["profit_factor"]),
        "expectancy_pct": round(expectancy_pct, 3),
        "total_return_pct": round(total_ret_pct, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "mar_ratio": round(float(max(-999.0, min(999.0, mar))), 2),
        "sharpe": float(m["sharpe_ratio"]),
        "avg_mfe_pct": round(avg_mfe, 2),
        "avg_mae_pct": round(avg_mae, 2),
        "mfe_mae_ratio": round(mfe_mae_ratio, 2),
        "total_fees_paid": float(res["total_fees_paid"]),
        "total_funding_pnl": float(res.get("total_funding_pnl", 0.0)),
        "final_balance": round(final_bal, 2),
    }


def bootstrap_eratio_diff_pvalue(
    mfe_a: List[float],
    mae_a: List[float],
    mfe_b: List[float],
    mae_b: List[float],
    n_boot: int = 1000,
    seed: int = 42,
) -> float:
    """Two-sided permutation/bootstrap test for difference in E-Ratio = median(MFE)/median(MAE)."""
    if len(mfe_a) < 2 or len(mfe_b) < 2:
        return 1.0
    ma_f, ma_e = np.asarray(mfe_a, dtype=float), np.asarray(mae_a, dtype=float)
    mb_f, mb_e = np.asarray(mfe_b, dtype=float), np.asarray(mae_b, dtype=float)
    obs_a = float(np.median(ma_f) / max(float(np.median(ma_e)), 1e-4))
    obs_b = float(np.median(mb_f) / max(float(np.median(mb_e)), 1e-4))
    obs_diff = obs_a - obs_b
    if obs_diff == 0.0:
        return 1.0
    rng = np.random.default_rng(seed)
    comb_f = np.concatenate([ma_f, mb_f])
    comb_e = np.concatenate([ma_e, mb_e])
    na, nb = len(ma_f), len(mb_f)
    n_tot = na + nb
    ge_count = 0
    for _ in range(n_boot):
        idx = rng.integers(0, n_tot, size=n_tot)
        ea = float(np.median(comb_f[idx[:na]]) / max(float(np.median(comb_e[idx[:na]])), 1e-4))
        eb = float(np.median(comb_f[idx[na:]]) / max(float(np.median(comb_e[idx[na:]])), 1e-4))
        if abs(ea - eb) >= abs(obs_diff):
            ge_count += 1
    return round(ge_count / n_boot, 4)


def compute_forward_outcomes(price_data: List[Dict], signals: List[Dict], horizons: Tuple[int, ...] = (4, 12, 24)) -> List[Dict]:
    time_to_idx = {p["time"]: idx for idx, p in enumerate(price_data)}
    max_h = max(horizons)
    n = len(price_data)
    out = []
    for sig in signals:
        idx = time_to_idx.get(sig["time"])
        if idx is None or idx + max_h >= n:
            continue
        entry = price_data[idx]["close"]
        if entry <= 0:
            continue
        direction = sig.get("direction", "bullish")
        row = {"time": sig["time"], "direction": direction}
        for h in horizons:
            window = price_data[idx + 1 : idx + h + 1]
            close_h = window[-1]["close"]
            highs = [c["high"] for c in window]
            lows = [c["low"] for c in window]
            if direction == "bullish":
                ret = (close_h - entry) / entry * 100.0
                mfe = max(0.0, (max(highs) - entry) / entry * 100.0)
                mae = max(0.0, (entry - min(lows)) / entry * 100.0)
            else:
                ret = (entry - close_h) / entry * 100.0
                mfe = max(0.0, (entry - min(lows)) / entry * 100.0)
                mae = max(0.0, (max(highs) - entry) / entry * 100.0)
            row[f"ret_{h}"] = ret
            row[f"mfe_{h}"] = mfe
            row[f"mae_{h}"] = mae
        out.append(row)
    return out


def bootstrap_diff_pvalue(sample_a: List[float], sample_b: List[float], n_boot: int = 1000, seed: int = 42) -> float:
    """Two-sided bootstrap test for difference in means E[A] - E[B]."""
    if len(sample_a) < 2 or len(sample_b) < 2:
        return 1.0
    arr_a = np.asarray(sample_a, dtype=float)
    arr_b = np.asarray(sample_b, dtype=float)
    obs_diff = float(np.mean(arr_a) - np.mean(arr_b))
    if obs_diff == 0.0:
        return 1.0
    rng = np.random.default_rng(seed)
    combined = np.concatenate([arr_a, arr_b])
    na, nb = len(arr_a), len(arr_b)
    boot_diffs = np.empty(n_boot, dtype=float)
    for k in range(n_boot):
        perm = rng.choice(combined, size=na + nb, replace=True)
        boot_diffs[k] = np.mean(perm[:na]) - np.mean(perm[na:])
    p_val = float(np.mean(np.abs(boot_diffs) >= abs(obs_diff)))
    return round(p_val, 4)


# ---------------------------------------------------------------------------
# Synthetic Self-Test Dataset Generator (for offline validation ONLY)
# ---------------------------------------------------------------------------

def make_synthetic_datasets(require_top_ls: bool = False) -> Dict[Tuple[str, str], Dict[str, Any]]:
    rng = np.random.default_rng(2026)
    datasets: Dict[Tuple[str, str], Dict[str, Any]] = {}
    t_base = 1790000000 - (1790000000 % 14400)
    n_1h = 1000  # 250 warmup + 750 clean (~31.25 days)
    n_4h = 430   # 250 warmup + 180 clean (~30 days)

    for sym_idx, sym in enumerate(SYMBOLS):
        for tf in TIMEFRAMES:
            step = TF_SECONDS[tf]
            n = n_1h if tf == "1h" else n_4h
            prices = []
            p = 100.0 * (sym_idx + 1)
            for i in range(n):
                t = t_base + i * step
                drift = 0.0005 * math.sin(i / 25.0)
                shock = float(rng.normal(drift, 0.012 if tf == "1h" else 0.022))
                o = p
                c = max(0.01, p * (1.0 + shock))
                wick_up = abs(float(rng.normal(0, 0.007)))
                wick_dn = abs(float(rng.normal(0, 0.007)))
                h = max(o, c) * (1.0 + wick_up)
                l = min(o, c) * max(0.5, 1.0 - wick_dn)
                prices.append({"time": t, "open": o, "high": h, "low": l, "close": c, "volume": float(1e6 * (1 + abs(shock) * 50))})
                p = c

            clean_slice = prices[250:]
            oi_series = [{"time": bar["time"], "value": float(1e8 * (1 + 0.1 * math.sin(k / 15.0) + rng.normal(0, 0.03)))} for k, bar in enumerate(clean_slice)]
            lsur_series = [{"time": bar["time"], "value": float(max(0.4, 1.2 + 0.4 * math.sin(k / 12.0) + rng.normal(0, 0.15)))} for k, bar in enumerate(clean_slice)]
            top_ls_series = [{"time": bar["time"], "value": float(max(0.5, 1.6 + 0.5 * math.cos(k / 12.0) + rng.normal(0, 0.15)))} for k, bar in enumerate(clean_slice)]
            taker_series = []
            for k, bar in enumerate(clean_slice):
                buy = 1000.0 + (200.0 if bar["close"] >= bar["open"] else -150.0) + float(rng.normal(0, 80))
                sell = 1000.0 + (-150.0 if bar["close"] >= bar["open"] else 200.0) + float(rng.normal(0, 80))
                taker_series.append({"time": bar["time"], "buy_vol": max(10.0, buy), "sell_vol": max(10.0, sell)})
            funding = [
                {"time": bar["time"], "funding_rate": float(0.0001 + 0.00015 * math.sin(k / 20.0))}
                for k, bar in enumerate(clean_slice)
                if bar["time"] % 28800 == 0
            ]
            datasets[(sym, tf)] = _assemble_clean_window(
                symbol=sym,
                timeframe=tf,
                price_all=prices,
                oi_series=oi_series,
                taker_series=taker_series,
                lsur_series=lsur_series,
                top_ls_series=top_ls_series,
                funding_settlements=funding,
                require_top_ls=require_top_ls,
            )
    return datasets


# ---------------------------------------------------------------------------
# Experiment 3 / 3B Helpers & Metadata Inspection
# ---------------------------------------------------------------------------

def _get_indicators_confluence_defaults() -> Dict[str, Any]:
    sig = inspect.signature(IndicatorEngine.calculate_confluence_signals)
    return {
        "mtf_close_aligned": bool(sig.parameters["mtf_close_aligned"].default),
        "setup_symmetry": bool(sig.parameters["setup_symmetry"].default),
        "use_coin_oi_all": bool(sig.parameters["use_coin_oi_all"].default),
        "price_group_cap": sig.parameters["price_group_cap"].default,
        "single_trend_guard": bool(sig.parameters["single_trend_guard"].default),
        "is_hype_hacks_deleted": ("use_legacy_hype_rules" not in sig.parameters),
    }


def _fmt_utc(ts: Optional[int]) -> str:
    if ts is None:
        return "N/A"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _summarize_exp3_group(
    sym: str,
    tf: str,
    g_name: str,
    outcomes: List[Dict],
    ref_p: List[Dict],
    ref_d1: List[Dict],
) -> Dict[str, Any]:
    n_obs = len(outcomes)
    row: Dict[str, Any] = {"symbol": sym, "timeframe": tf, "group": g_name, "n": n_obs}
    for h in (4, 12, 24):
        rets = [o[f"ret_{h}"] for o in outcomes]
        mfes = [o[f"mfe_{h}"] for o in outcomes]
        maes = [o[f"mae_{h}"] for o in outcomes]
        row[f"ret_{h}"] = round(float(np.mean(rets)), 3) if rets else 0.0
        med_mfe = float(np.median(mfes)) if mfes else 0.0
        med_mae = float(np.median(maes)) if maes else 0.0
        row[f"e_ratio_{h}"] = round(med_mfe / max(med_mae, 1e-4), 2) if outcomes else 0.0
        row[f"p_ret_vs_P_{h}"] = (
            bootstrap_diff_pvalue(rets, [o[f"ret_{h}"] for o in ref_p])
            if outcomes and ref_p and g_name != "Group P"
            else 1.0
        )
        row[f"p_ret_vs_D1_{h}"] = (
            bootstrap_diff_pvalue(rets, [o[f"ret_{h}"] for o in ref_d1])
            if outcomes and ref_d1 and g_name == "Group D2"
            else 1.0
        )
        row[f"p_er_vs_P_{h}"] = (
            bootstrap_eratio_diff_pvalue(
                mfes, maes, [o[f"mfe_{h}"] for o in ref_p], [o[f"mae_{h}"] for o in ref_p]
            )
            if outcomes and ref_p and g_name != "Group P"
            else 1.0
        )
        row[f"p_er_vs_D1_{h}"] = (
            bootstrap_eratio_diff_pvalue(
                mfes, maes, [o[f"mfe_{h}"] for o in ref_d1], [o[f"mae_{h}"] for o in ref_d1]
            )
            if outcomes and ref_d1 and g_name == "Group D2"
            else 1.0
        )
    row["p_vs_P_12"] = row["p_ret_vs_P_12"]
    row["p_vs_D1_12"] = row["p_ret_vs_D1_12"]
    return row


def _evaluate_exp3_groups(
    datasets_map: Dict[Tuple[str, str], Dict[str, Any]],
    signal_kwargs: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    raw_outcomes: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for sym in SYMBOLS:
        for tf in TIMEFRAMES:
            ds = datasets_map.get((sym, tf))
            if not ds or not ds.get("valid"):
                continue
            htf_ds = datasets_map.get((sym, "4h"))
            btc_ds = datasets_map.get(("BTC/USDT", tf))

            sigs_p = generate_signals(ds, htf_ds, btc_ds, price_only_mode=True, **signal_kwargs)
            sigs_d1 = generate_signals(ds, htf_ds, btc_ds, lsur_source="lsur", **signal_kwargs)
            top_ls_z_times = [x["time"] for x in ds.get("top_ls_z_aligned", []) if x["time"] >= ds["eval_start"]]
            has_top_ls = len(top_ls_z_times) >= 14
            if has_top_ls:
                top_min_t, top_max_t = min(top_ls_z_times), max(top_ls_z_times)
                sigs_d2 = [
                    s for s in generate_signals(ds, htf_ds, btc_ds, lsur_source="top_ls", **signal_kwargs)
                    if top_min_t <= s["time"] <= top_max_t
                ]
                eval_first_t = ds["eval_price"][0]["time"] if ds["eval_price"] else None
                eval_last_t = ds["eval_price"][-1]["time"] if ds["eval_price"] else None
                partial_top_ls = (
                    eval_first_t is not None
                    and eval_last_t is not None
                    and (top_min_t > eval_first_t or top_max_t < eval_last_t)
                )
            else:
                top_min_t, top_max_t = None, None
                sigs_d2 = []
                partial_top_ls = False

            out_p = compute_forward_outcomes(ds["eval_price"], sigs_p)
            out_d1 = compute_forward_outcomes(ds["eval_price"], sigs_d1)
            out_d2 = compute_forward_outcomes(ds["eval_price"], sigs_d2) if sigs_d2 else []
            if partial_top_ls and top_min_t is not None and top_max_t is not None:
                ref_p_for_d2 = [o for o in out_p if top_min_t <= o["time"] <= top_max_t]
                ref_d1_for_d2 = [o for o in out_d1 if top_min_t <= o["time"] <= top_max_t]
            else:
                ref_p_for_d2 = out_p
                ref_d1_for_d2 = out_d1

            rows.append(_summarize_exp3_group(sym, tf, "Group P", out_p, out_p, out_d1))
            rows.append(_summarize_exp3_group(sym, tf, "Group D1", out_d1, out_p, out_d1))
            rows.append(_summarize_exp3_group(sym, tf, "Group D2", out_d2, ref_p_for_d2, ref_d1_for_d2))
            raw_outcomes[(sym, tf)] = {
                "Group P": out_p,
                "Group D1": out_d1,
                "Group D2": out_d2,
                "ref_p_d2": ref_p_for_d2,
                "ref_d1_d2": ref_d1_for_d2,
                "has_top_ls": has_top_ls,
            }

    aggregate_rows: List[Dict[str, Any]] = []
    if rows:
        for scope in ("All", "1h", "4h"):
            scope_items = [
                ((s, t), d) for (s, t), d in raw_outcomes.items()
                if scope == "All" or t == scope
            ]
            if not scope_items:
                continue
            for g_name in ("Group P", "Group D1", "Group D2"):
                g_rows = [
                    r for r in rows
                    if r["group"] == g_name and (scope == "All" or r["timeframe"] == scope)
                ]
                nonzero_rows = [r for r in g_rows if r["n"] > 0]
                pooled = [o for _, d in scope_items for o in d[g_name]]
                if g_name == "Group D2":
                    pooled_ref_p = [o for _, d in scope_items if d["has_top_ls"] for o in d["ref_p_d2"]]
                    pooled_ref_d1 = [o for _, d in scope_items if d["has_top_ls"] for o in d["ref_d1_d2"]]
                else:
                    pooled_ref_p = [o for _, d in scope_items for o in d["Group P"]]
                    pooled_ref_d1 = [o for _, d in scope_items for o in d["Group D1"]]

                agg: Dict[str, Any] = {
                    "scope": scope,
                    "group": g_name,
                    "targets_total": len(g_rows),
                    "targets_nonzero": len(nonzero_rows),
                    "total_n": len(pooled),
                }
                for h in (4, 12, 24):
                    agg[f"mean_ret_{h}"] = (
                        round(float(np.mean([r[f"ret_{h}"] for r in nonzero_rows])), 3)
                        if nonzero_rows
                        else 0.0
                    )
                    agg[f"mean_e_ratio_{h}"] = (
                        round(float(np.mean([r[f"e_ratio_{h}"] for r in nonzero_rows])), 2)
                        if nonzero_rows
                        else 0.0
                    )
                    p_rets = [o[f"ret_{h}"] for o in pooled]
                    p_mfes = [o[f"mfe_{h}"] for o in pooled]
                    p_maes = [o[f"mae_{h}"] for o in pooled]
                    agg[f"pooled_ret_{h}"] = round(float(np.mean(p_rets)), 3) if p_rets else 0.0
                    med_mfe = float(np.median(p_mfes)) if p_mfes else 0.0
                    med_mae = float(np.median(p_maes)) if p_maes else 0.0
                    agg[f"pooled_e_ratio_{h}"] = round(med_mfe / max(med_mae, 1e-4), 2) if pooled else 0.0
                    agg[f"pooled_p_ret_vs_P_{h}"] = (
                        bootstrap_diff_pvalue(p_rets, [o[f"ret_{h}"] for o in pooled_ref_p])
                        if pooled and pooled_ref_p and g_name != "Group P"
                        else 1.0
                    )
                    agg[f"pooled_p_ret_vs_D1_{h}"] = (
                        bootstrap_diff_pvalue(p_rets, [o[f"ret_{h}"] for o in pooled_ref_d1])
                        if pooled and pooled_ref_d1 and g_name == "Group D2"
                        else 1.0
                    )
                    agg[f"pooled_p_er_vs_P_{h}"] = (
                        bootstrap_eratio_diff_pvalue(
                            p_mfes, p_maes, [o[f"mfe_{h}"] for o in pooled_ref_p], [o[f"mae_{h}"] for o in pooled_ref_p]
                        )
                        if pooled and pooled_ref_p and g_name != "Group P"
                        else 1.0
                    )
                    agg[f"pooled_p_er_vs_D1_{h}"] = (
                        bootstrap_eratio_diff_pvalue(
                            p_mfes, p_maes, [o[f"mfe_{h}"] for o in pooled_ref_d1], [o[f"mae_{h}"] for o in pooled_ref_d1]
                        )
                        if pooled and pooled_ref_d1 and g_name == "Group D2"
                        else 1.0
                    )
                aggregate_rows.append(agg)

    return rows, aggregate_rows


# ---------------------------------------------------------------------------
# Full Audit Pipeline
# ---------------------------------------------------------------------------

def run_all_experiments(
    use_synthetic: bool = False,
    output_dir: Path = ROOT / "scripts" / "debug",
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    if mode is not None:
        if mode not in ("db", "synthetic"):
            raise ValueError(f"Unsupported mode: {mode!r} (expected 'db' or 'synthetic')")
        use_synthetic = (mode == "synthetic")
    eff_mode = "synthetic" if use_synthetic else "db"

    output_dir.mkdir(parents=True, exist_ok=True)
    datasets: Dict[Tuple[str, str], Dict[str, Any]] = {}
    datasets_top_ls: Dict[Tuple[str, str], Dict[str, Any]] = {}

    ind_defaults = _get_indicators_confluence_defaults()
    exp3_signal_kwargs = dict(
        mtf_close_aligned=True,
        use_btc_history=True,
        use_static_btc_leak=False,
        setup_symmetry=True,
        use_coin_oi_all=True,
    )

    if eff_mode == "synthetic":
        print("⚠️ Running in OFFLINE SYNTHETIC SELFTEST mode (results verify code pipeline only, NOT market profitability).")
        datasets = make_synthetic_datasets(require_top_ls=False)
        datasets_top_ls = make_synthetic_datasets(require_top_ls=True)
    else:
        print("🔍 Probing PostgreSQL for Window A clean native 1h / 4h derivative windows (excluding 1D rows)...")
        for sym in SYMBOLS:
            for tf in TIMEFRAMES:
                ds = load_clean_dataset_from_db(sym, tf, require_top_ls=False)
                datasets[(sym, tf)] = ds
                if ds.get("valid"):
                    print(
                        f"  ✅ {sym:<10} {tf}: {_fmt_utc(ds['eval_start'])} ~ {_fmt_utc(ds['clean_end'])} UTC | "
                        f"{ds['clean_days']:.1f}d ({ds['clean_bars']} bars) | "
                        f"taker={ds['taker_available']} | top_ls={ds['top_ls_bars']} | funding={ds['funding_count']}"
                    )
                else:
                    print(f"  ⚠️ {sym:<10} {tf}: {ds.get('reason')}")

        print("\n🔍 Probing PostgreSQL for Window B clean native top_ls_position_ratio windows (require_top_ls=True)...")
        for sym in SYMBOLS:
            for tf in TIMEFRAMES:
                ds_b = load_clean_dataset_from_db(sym, tf, require_top_ls=True)
                datasets_top_ls[(sym, tf)] = ds_b
                if ds_b.get("valid"):
                    print(
                        f"  ✅ {sym:<10} {tf}: {_fmt_utc(ds_b['clean_start'])} (eval {_fmt_utc(ds_b['eval_start'])}) ~ "
                        f"{_fmt_utc(ds_b['clean_end'])} UTC | {ds_b['clean_days']:.1f}d ({ds_b['clean_bars']} eval bars) | "
                        f"top_ls_count={ds_b['top_ls_count']} | taker={ds_b['taker_available']} | funding={ds_b['funding_count']}"
                    )
                else:
                    print(f"  ⚠️ {sym:<10} {tf}: {ds_b.get('reason')}")

    # --- Phase 0 / Stage 0 + Experiment 1 (Stage 0 -> 1A -> 1B -> 1C) ---
    exp1_rows: List[Dict[str, Any]] = []
    exit_arch_rows: List[Dict[str, Any]] = []

    for sym in SYMBOLS:
        for tf in TIMEFRAMES:
            ds = datasets[(sym, tf)]
            if not ds.get("valid"):
                continue
            htf_ds = datasets.get((sym, "4h"))
            btc_ds = datasets.get(("BTC/USDT", tf))

            # Stage 0: Raw Baseline
            sigs_0 = generate_signals(
                ds, htf_ds, btc_ds,
                mtf_close_aligned=False, use_btc_history=False, use_static_btc_leak=True,
                setup_symmetry=False, use_coin_oi_all=False,
            )
            r0 = run_backtest_slice(ds, sigs_0, slippage_bps=0.0, include_funding=False, trailing_path_mode="legacy_clamp")
            r0["stage"] = "Stage 0 (Raw)"
            exp1_rows.append(r0)

            # Stage 1A: Fix MTF + BTC Macro Causality
            sigs_1a = generate_signals(
                ds, htf_ds, btc_ds,
                mtf_close_aligned=True, use_btc_history=True, use_static_btc_leak=False,
                setup_symmetry=False, use_coin_oi_all=False,
            )
            r1a = run_backtest_slice(ds, sigs_1a, slippage_bps=0.0, include_funding=False, trailing_path_mode="legacy_clamp")
            r1a["stage"] = "Stage 1A (Causality)"
            exp1_rows.append(r1a)

            # Stage 1B: Conservative intra-bar trailing + Setup Symmetry + Coin OI
            sigs_1b = generate_signals(
                ds, htf_ds, btc_ds,
                mtf_close_aligned=True, use_btc_history=True,
                setup_symmetry=True, use_coin_oi_all=True,
            )
            r1b = run_backtest_slice(ds, sigs_1b, slippage_bps=0.0, include_funding=False, trailing_path_mode="conservative")
            r1b["stage"] = "Stage 1B (Trail+SM+OI)"
            exp1_rows.append(r1b)

            # Stage 1C: Funding + Slippage (0, 5, 15 bps)
            for bps in (0.0, 5.0, 15.0):
                r1c = run_backtest_slice(ds, sigs_1b, slippage_bps=bps, include_funding=True, trailing_path_mode="conservative")
                r1c["stage"] = f"Stage 1C ({int(bps)}bps+Fund)"
                exp1_rows.append(r1c)

            # Exit Architecture comparison under 5 & 15 bps
            profile = get_risk_profile(sym, tf)
            wide_pct = max(profile["trailing_stop_pct"] * 2.5, profile["stop_loss_pct"] * 0.5)
            for bps in (5.0, 15.0):
                r_cur = run_backtest_slice(ds, sigs_1b, slippage_bps=bps, include_funding=True, trailing_path_mode="conservative", enable_partial_tp=False)
                r_cur["arch"] = f"SingleFullTP_Narrow ({bps:.0f}bps)"
                exit_arch_rows.append(r_cur)

                r_atr1 = run_backtest_slice(ds, sigs_1b, slippage_bps=bps, include_funding=True, trailing_path_mode="conservative", enable_partial_tp=True, trailing_atr_mult=1.0)
                r_atr1["arch"] = f"PartialTP+1.0xATR ({bps:.0f}bps)"
                exit_arch_rows.append(r_atr1)

                r_atr15 = run_backtest_slice(ds, sigs_1b, slippage_bps=bps, include_funding=True, trailing_path_mode="conservative", enable_partial_tp=True, trailing_atr_mult=1.5)
                r_atr15["arch"] = f"PartialTP+1.5xATR ({bps:.0f}bps)"
                exit_arch_rows.append(r_atr15)

                r_pct = run_backtest_slice(ds, sigs_1b, slippage_bps=bps, include_funding=True, trailing_path_mode="conservative", enable_partial_tp=True, trailing_stop_pct_override=wide_pct)
                r_pct["arch"] = f"PartialTP+WidePct ({bps:.0f}bps)"
                exit_arch_rows.append(r_pct)

    # --- Experiment 2: Walk-Forward 60% IS / 40% OOS Ablation (Variants B, C, D live on pruned engine) ---
    variants = [
        ("Variant B (Pruned Production)", dict(price_group_cap=None, single_trend_guard=False)),
        ("Variant C (Price Cap 1.5)", dict(price_group_cap=1.5, single_trend_guard=False)),
        ("Variant D (Single Guard)", dict(price_group_cap=1.5, single_trend_guard=True)),
    ]
    exp2_rows: List[Dict[str, Any]] = []
    for sym in SYMBOLS:
        for tf in TIMEFRAMES:
            ds = datasets[(sym, tf)]
            if not ds.get("valid") or len(ds["eval_price"]) < 20:
                continue
            htf_ds = datasets.get((sym, "4h"))
            btc_ds = datasets.get(("BTC/USDT", tf))
            eval_candles = ds["eval_price"]
            split_idx = max(10, int(len(eval_candles) * 0.6))
            is_slice = eval_candles[:split_idx]
            oos_slice = eval_candles[split_idx:]
            if len(oos_slice) < 5:
                continue

            for v_name, v_kwargs in variants:
                sigs = generate_signals(
                    ds, htf_ds, btc_ds,
                    mtf_close_aligned=True, use_btc_history=True,
                    setup_symmetry=True, use_coin_oi_all=True,
                    **v_kwargs,
                )
                r_is = run_backtest_slice(ds, sigs, price_slice=is_slice, slippage_bps=5.0, include_funding=True, trailing_path_mode="conservative")
                r_oos = run_backtest_slice(ds, sigs, price_slice=oos_slice, slippage_bps=5.0, include_funding=True, trailing_path_mode="conservative")
                exp2_rows.append({
                    "symbol": sym,
                    "timeframe": tf,
                    "variant": v_name,
                    "is_trades": r_is["trades"],
                    "is_wr": r_is["win_rate"],
                    "is_exp": r_is["expectancy_pct"],
                    "is_mar": r_is["mar_ratio"],
                    "oos_trades": r_oos["trades"],
                    "oos_wr": r_oos["win_rate"],
                    "oos_pf": r_oos["profit_factor"],
                    "oos_exp": r_oos["expectancy_pct"],
                    "oos_dd": r_oos["max_drawdown_pct"],
                    "oos_mar": r_oos["mar_ratio"],
                })

    # --- Experiment 3: Window A Forward Return (+4/+12/+24) & Top Trader Bootstrap ---
    exp3_rows, _ = _evaluate_exp3_groups(datasets, exp3_signal_kwargs)

    # --- Experiment 3B: Window B Clean top_ls_position_ratio Inventory & Head-to-Head ---
    window_b_inventory: List[Dict[str, Any]] = []
    for sym in SYMBOLS:
        for tf in TIMEFRAMES:
            ds_b = datasets_top_ls.get((sym, tf))
            is_valid = bool(ds_b and ds_b.get("valid"))
            window_b_inventory.append({
                "symbol": sym,
                "timeframe": tf,
                "valid": is_valid,
                "clean_start": ds_b.get("clean_start") if ds_b else None,
                "eval_start": ds_b.get("eval_start") if ds_b else None,
                "clean_end": ds_b.get("clean_end") if ds_b else None,
                "clean_start_utc": _fmt_utc(ds_b.get("clean_start")) if ds_b else "N/A",
                "eval_start_utc": _fmt_utc(ds_b.get("eval_start")) if ds_b else "N/A",
                "clean_end_utc": _fmt_utc(ds_b.get("clean_end")) if ds_b else "N/A",
                "clean_days": ds_b.get("clean_days", 0.0) if ds_b else 0.0,
                "eval_bars": ds_b.get("clean_bars", 0) if is_valid else 0,
                "top_ls_count": ds_b.get("top_ls_count", 0) if ds_b else 0,
                "top_ls_bars": ds_b.get("top_ls_bars", 0) if is_valid else 0,
                "taker_available": bool(ds_b.get("taker_available", False)) if ds_b else False,
                "funding_count": ds_b.get("funding_count", 0) if is_valid else 0,
                "reason": ds_b.get("reason", "") if (ds_b and not is_valid) else "",
            })

    exp3b_rows, exp3b_agg_rows = _evaluate_exp3_groups(datasets_top_ls, exp3_signal_kwargs)

    # --- Window B Stage 1C Backtest Check (5 bps, Funding=True, Conservative Trailing) ---
    window_b_stage1c_rows: List[Dict[str, Any]] = []
    for sym in SYMBOLS:
        for tf in TIMEFRAMES:
            ds_b = datasets_top_ls.get((sym, tf))
            if not ds_b or not ds_b.get("valid"):
                continue
            htf_ds_b = datasets_top_ls.get((sym, "4h"))
            btc_ds_b = datasets_top_ls.get(("BTC/USDT", tf))
            top_ls_z_times = [x["time"] for x in ds_b.get("top_ls_z_aligned", []) if x["time"] >= ds_b["eval_start"]]
            if len(top_ls_z_times) < 14:
                continue
            for src in ("lsur", "top_ls"):
                sigs_wb = generate_signals(
                    ds_b, htf_ds_b, btc_ds_b,
                    lsur_source=src,
                    **exp3_signal_kwargs,
                )
                r_wb = run_backtest_slice(
                    ds_b,
                    sigs_wb,
                    slippage_bps=5.0,
                    include_funding=True,
                    trailing_path_mode="conservative",
                )
                if r_wb:
                    r_wb["lsur_source"] = src
                    window_b_stage1c_rows.append(r_wb)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": eff_mode,
        "synthetic": use_synthetic,
        "metadata": {
            "mode": eff_mode,
            "indicators_defaults": ind_defaults,
            "exp3_signal_params": exp3_signal_kwargs,
            "window_b_stage1c_params": {
                "slippage_bps": 5.0,
                "include_funding": True,
                "trailing_path_mode": "conservative",
                **exp3_signal_kwargs,
            },
        },
        "exp1": exp1_rows,
        "exit_arch": exit_arch_rows,
        "exp2": exp2_rows,
        "exp3": exp3_rows,
        "window_b_inventory": window_b_inventory,
        "exp3b": exp3b_rows,
        "exp3b_aggregate": exp3b_agg_rows,
        "window_b_stage1c": window_b_stage1c_rows,
    }

    md_text = render_markdown_report(summary)
    md_path = output_dir / ("audit_experiment_selftest_report.md" if use_synthetic else "audit_experiment_report.md")
    json_path = output_dir / ("audit_experiment_selftest_results.json" if use_synthetic else "audit_experiment_results.json")
    md_path.write_text(md_text, encoding="utf-8")
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n✅ Saved report: {md_path}")
    print(f"✅ Saved JSON:   {json_path}")
    return summary


def render_markdown_report(summary: Dict[str, Any]) -> str:
    meta = summary.get("metadata", {})
    ind_defaults = meta.get("indicators_defaults", _get_indicators_confluence_defaults())
    exp3_params = meta.get("exp3_signal_params", {})
    is_hype_hacks_deleted = bool(ind_defaults.get("is_hype_hacks_deleted", True))
    eff_mode = summary.get("mode", "synthetic" if summary.get("synthetic") else "db")

    stage0_rows = [r for r in summary.get("exp1", []) if r.get("stage") == "Stage 0 (Raw)"]
    lines = [
        "# Solo-Quant Red-Team Audit & Falsification Experiments Report",
        f"**Generated at**: {summary['generated_at']} | **Mode**: `{eff_mode}` | **Synthetic**: {summary['synthetic']}",
        (
            f"> **Signal Engine Metadata (`api/core/indicators.py`)**: "
            f"`is_hype_hacks_deleted={is_hype_hacks_deleted}` "
            f"(`use_legacy_hype_rules` & all 5 `is_hype` special cases removed; unified `is_alt` `-10/+10` RSI & uniform ATR EMA50 bounds). "
            f"Phase 1/2 causal defaults enforced: "
            f"`mtf_close_aligned={exp3_params.get('mtf_close_aligned', True)}`, "
            f"`use_btc_history={exp3_params.get('use_btc_history', True)}`, "
            f"`setup_symmetry={exp3_params.get('setup_symmetry', True)}`, "
            f"`use_coin_oi_all={exp3_params.get('use_coin_oi_all', True)}`, "
            f"`price_group_cap={ind_defaults.get('price_group_cap', None)}`, "
            f"`single_trend_guard={ind_defaults.get('single_trend_guard', False)}`."
        ),
        "",
        "## 0. Phase 0 — Stage 0 (Raw Baseline Snapshot)",
        "| Symbol | Timeframe | Clean Window Days | Trades | Win Rate (%) | Profit Factor | Expectancy per Trade (%) | Max Drawdown (%) | MAR Ratio | Sharpe | Avg MFE (%) | Avg MAE (%) | MFE/MAE Ratio |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for r in stage0_rows:
        lines.append(
            f"| {r['symbol']} | {r['timeframe']} | {r['clean_days']} | {r['trades']} | {r['win_rate']:.1f} | "
            f"{r['profit_factor']:.2f} | {r['expectancy_pct']:+.3f} | {r['max_drawdown_pct']:.2f} | {r['mar_ratio']:.2f} | "
            f"{r['sharpe']:.2f} | {r['avg_mfe_pct']:.2f} | {r['avg_mae_pct']:.2f} | {r['mfe_mae_ratio']:.2f} |"
        )

    lines.extend([
        "",
        "## 1. Stage 0 -> Stage 1C De-hallucinated Baseline & Slippage/Funding Stress Test",
        "| Symbol | TF | Stage | Days | Trades | WR (%) | PF | Exp/Trade (%) | MaxDD (%) | MAR | Sharpe | Avg MFE (%) | Avg MAE (%) | MFE/MAE | Funding ($) |",
        "| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for r in summary.get("exp1", []):
        lines.append(
            f"| {r['symbol']} | {r['timeframe']} | {r['stage']} | {r['clean_days']} | {r['trades']} | {r['win_rate']:.1f} | "
            f"{r['profit_factor']:.2f} | {r['expectancy_pct']:+.3f} | {r['max_drawdown_pct']:.2f} | {r['mar_ratio']:.2f} | "
            f"{r['sharpe']:.2f} | {r['avg_mfe_pct']:.2f} | {r['avg_mae_pct']:.2f} | {r['mfe_mae_ratio']:.2f} | {r['total_funding_pnl']:+.2f} |"
        )

    lines.extend([
        "",
        "## 2. Exit Architecture Stress Test (Partial TP + Wide Trailing vs Narrow Trailing)",
        "| Symbol | TF | Architecture | Trades | WR (%) | PF | Exp/Trade (%) | MaxDD (%) | MAR |",
        "| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for r in summary.get("exit_arch", []):
        lines.append(
            f"| {r['symbol']} | {r['timeframe']} | {r['arch']} | {r['trades']} | {r['win_rate']:.1f} | "
            f"{r['profit_factor']:.2f} | {r['expectancy_pct']:+.3f} | {r['max_drawdown_pct']:.2f} | {r['mar_ratio']:.2f} |"
        )

    lines.extend([
        "",
        "## 3. Walk-Forward (60% IS vs 40% OOS) Ablation Study",
        "| Symbol | TF | Variant | IS Trades | IS Exp (%) | IS MAR | OOS Trades | OOS WR (%) | OOS PF | OOS Exp (%) | OOS DD (%) | OOS MAR |",
        "| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for r in summary.get("exp2", []):
        lines.append(
            f"| {r['symbol']} | {r['timeframe']} | {r['variant']} | {r['is_trades']} | {r['is_exp']:+.3f} | {r['is_mar']:.2f} | "
            f"{r['oos_trades']} | {r['oos_wr']:.1f} | {r['oos_pf']:.2f} | {r['oos_exp']:+.3f} | {r['oos_dd']:.2f} | {r['oos_mar']:.2f} |"
        )

    # Aggregate OOS verdict across variants
    if summary.get("exp2"):
        lines.extend(["", "### Automated Walk-Forward OOS Variant Ranking"])
        by_var: Dict[str, List[Dict]] = {}
        for r in summary["exp2"]:
            by_var.setdefault(r["variant"], []).append(r)
        for v_name, rows in by_var.items():
            mean_oos_exp = float(np.mean([x["oos_exp"] for x in rows]))
            mean_oos_mar = float(np.mean([x["oos_mar"] for x in rows]))
            mean_is_exp = float(np.mean([x["is_exp"] for x in rows]))
            lines.append(
                f"- **{v_name}**: Mean IS Exp={mean_is_exp:+.3f}% | Mean OOS Exp={mean_oos_exp:+.3f}% | Mean OOS MAR={mean_oos_mar:.2f}"
            )

    lines.extend([
        "",
        "### Pre-Pruning Variant A Reference Baseline (Frozen Empirical Observation before Deletion)",
        "> **Why Variant A is no longer executed live**: `use_legacy_hype_rules` and all 5 `is_hype` bespoke rules were formally deleted from `api/core/indicators.py` following Window A Walk-Forward OOS falsification (`2026-11-25`, 194–205d, 10 targets, `5 bps` + funding + `conservative` trailing).",
        "- **Variant A (Legacy Rules — Frozen Pre-Pruning Reference)**: Mean IS Exp=`-0.249%` | Mean OOS Exp=`+0.001%` | Mean OOS MAR=`1.06`",
        "  - `HYPE/USDT 4h` (Variant A): IS `19` trades (`-0.389%`, MAR `-1.42`) -> OOS `8` trades, WR `62.5%`, PF `0.59`, Exp **`-0.872%`**, DD `5.44%`, MAR `-2.08`.",
        "  - `HYPE/USDT 1h` (Variant A): IS `38` trades (`-0.223%`, MAR `-1.46`) -> OOS `32` trades, WR `68.8%`, PF `0.92`, Exp `-0.048%`, DD `9.83%`, MAR `-0.71`.",
        "- **Contrasted with Variant B (No Coin Hacks -> Pruned Production)**: Mean IS Exp=`-0.246%` | Mean OOS Exp=**`+0.046%`** | Mean OOS MAR=`0.66`; `HYPE/USDT 4h` OOS rose from `-0.872% (PF 0.59)` to **`+0.166%` (PF `1.09`, WR `68.8%`, `16` trades)**.",
        "",
        "### Phase 2 OOS Module Keep/Prune Verdict Table (模組去留判決表)",
        "| Module / Parameter | Decision (決策) | Window A / Window B Empirical OOS Evidence |",
        "| :--- | :---: | :--- |",
        "| `5x is_hype` bespoke rules & `use_legacy_hype_rules` | **PRUNE / DELETED (刪除)** | Window A 60/40 OOS: `Variant B` achieved best Mean OOS Exp **`+0.046%`** vs `Variant A` `+0.001%`; `HYPE 4h` OOS jumped `-0.872% (PF 0.59)` -> **`+0.166%` (PF `1.09`, WR `68.8%`)**. Eliminated coin-specific curve fitting; unified `is_alt` `-10/+10` RSI & ATR EMA50 bounds across all assets. |",
        "| `Price Group Cap 3.0` (`price_group_cap=None`) | **KEEP (保留)** | Lowering Price Cap to `1.5` (`Variant C`) degraded Mean OOS Exp `+0.046%` -> **`-0.020%`** (e.g., `ETH 4h` OOS `+0.347%` -> `-0.012%`, `SOL 4h` OOS `+0.602%` -> `-0.113%`, `HYPE 4h` OOS `+0.166%` -> `-0.145%`). |",
        "| `Multi-Layer EMA Guards` (`single_trend_guard=False`) | **KEEP (保留)** | Collapsing to Single Trend Guard (`Variant D`) further degraded Mean OOS Exp to **`-0.073%`** and halved Mean OOS MAR `0.66` -> **`0.30`** (`ETH 1h` OOS `-0.131%` -> `-0.359%`, `ETH 4h` OOS `+0.347%` -> `-0.260%`). |",
        "| `SingleFullTP_Narrow` (`enable_partial_tp=False`) | **KEEP (保留)** | Window A Section 2 Exit Stress (`5` & `15 bps` + funding): `SingleFullTP_Narrow` outperformed all `PartialTP` variants (`+1.0xATR`, `+1.5xATR`, `+WidePct`) across 4h swing targets (`ETH 4h 5bps`: `+0.057% PF 1.03` vs `-0.242%~-0.297%`; `SOL 4h 5bps`: `+0.064% PF 1.04` vs `-0.371%~-0.390%`; `CC 4h 5bps`: `+0.441% PF 1.29` vs `-0.214%~+0.031%`). |",
        "| `top_ls_position_ratio` as primary `lsur_source` | **DO NOT PROMOTE (不升格，維持診斷)** | Clean Window B (`34.46d 1h / 32.67d 4h`, 10/10 targets): `Group D2 (top_ls, N=194)` Pooled Ret+12 = `+0.656%` failed Bootstrap significance vs `Group P` (`p=0.6790`) and vs `Group D1 lsur` (`p=0.5940`, Pooled Ret+12 = `+0.809%`), 0/10 targets hit `p < 0.10`; Stage 1C `lsur` outperformed `top_ls` (Mean Exp `+0.877% / Sharpe 3.25` vs `+0.715% / 2.68`). |",
    ])

    lines.extend([
        "",
        "## 4. Fixed-Horizon Forward Return (+4/+12/+24) & Top Trader Bootstrap Test (Window A)",
        (
            f"> Causal config: `mtf_close_aligned=True`, `use_btc_history=True`, "
            f"`setup_symmetry=True`, `use_coin_oi_all=True`, "
            f"`is_hype_hacks_deleted={is_hype_hacks_deleted}`."
        ),
        "| Symbol | TF | Group | N | Ret+4 (%) | Ret+12 (%) | Ret+24 (%) | E-Ratio+12 | p(vs P @12) | p(vs D1 @12) |",
        "| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for r in summary.get("exp3", []):
        lines.append(
            f"| {r['symbol']} | {r['timeframe']} | {r['group']} | {r['n']} | {r['ret_4']:+.3f} | {r['ret_12']:+.3f} | "
            f"{r['ret_24']:+.3f} | {r['e_ratio_12']:.2f} | {r['p_vs_P_12']:.4f} | {r['p_vs_D1_12']:.4f} |"
        )

    if summary.get("exp3"):
        lines.extend(["", "### Automated Experiment 3 Statistical Flags (alpha = 0.10)"])
        for r in summary["exp3"]:
            if r["group"] in ("Group D1", "Group D2"):
                if r["n"] == 0:
                    lines.append(f"- ⚠️ **{r['symbol']} {r['timeframe']} {r['group']}**: 0 signals / insufficient data.")
                elif r["p_vs_P_12"] > 0.10:
                    lines.append(
                        f"- ⚠️ **{r['symbol']} {r['timeframe']} {r['group']}**: Not statistically significant vs Group P "
                        f"(p={r['p_vs_P_12']:.4f} > 0.10, Ret+12={r['ret_12']:+.3f}%)."
                    )
                else:
                    lines.append(
                        f"- ✅ **{r['symbol']} {r['timeframe']} {r['group']}**: Significant vs Group P "
                        f"(p={r['p_vs_P_12']:.4f}, Ret+12={r['ret_12']:+.3f}%, p_vs_D1={r['p_vs_D1_12']:.4f})."
                    )

    # --- Section 5: Experiment 3B (Window B Clean top_ls_position_ratio Head-to-Head) ---
    wb_inv = summary.get("window_b_inventory", [])
    exp3b_rows = summary.get("exp3b", [])
    exp3b_agg = summary.get("exp3b_aggregate", [])

    lines.extend([
        "",
        "## 5. Experiment 3B: Window B Clean `top_ls_position_ratio` Head-to-Head (`Group P` vs `Group D1 lsur` vs `Group D2 top_ls`)",
        (
            f"> Shared Window B `eval_price` slice (`require_top_ls=True`). Causal config: "
            f"`mtf_close_aligned=True`, `use_btc_history=True`, `setup_symmetry=True`, `use_coin_oi_all=True`, "
            f"`is_hype_hacks_deleted={is_hype_hacks_deleted}`."
        ),
        "",
        "### 5.1 Clean Window B Inventory",
    ])
    if wb_inv:
        lines.extend([
            "| Symbol | TF | Valid | Clean Start (UTC) | Eval Start (UTC) | Clean End (UTC) | Clean Days | Eval Bars | top_ls_count | top_ls_eval_bars | Taker | Funding |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
        ])
        for inv in wb_inv:
            lines.append(
                f"| {inv['symbol']} | {inv['timeframe']} | {'✅' if inv['valid'] else '⚠️'} | "
                f"{inv['clean_start_utc']} | {inv['eval_start_utc']} | {inv['clean_end_utc']} | "
                f"{inv['clean_days']:.2f} | {inv['eval_bars']} | {inv['top_ls_count']} | "
                f"{inv['top_ls_bars']} | {inv['taker_available']} | {inv['funding_count']} |"
            )
    else:
        lines.append("- No Window B inventory recorded.")

    lines.extend(["", "### 5.2 Window B Head-to-Head Forward Return (+4 / +12 / +24), E-Ratio & Return Bootstrap p-values (1,000x)"])
    if exp3b_rows:
        lines.extend([
            "| Symbol | TF | Group | N | Ret+4 (%) | Ret+12 (%) | Ret+24 (%) | E-Ratio+4 | E-Ratio+12 | E-Ratio+24 | pRet(vs P @4) | pRet(vs P @12) | pRet(vs P @24) | pRet(vs D1 @4) | pRet(vs D1 @12) | pRet(vs D1 @24) |",
            "| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
        ])
        for r in exp3b_rows:
            lines.append(
                f"| {r['symbol']} | {r['timeframe']} | {r['group']} | {r['n']} | "
                f"{r['ret_4']:+.3f} | {r['ret_12']:+.3f} | {r['ret_24']:+.3f} | "
                f"{r['e_ratio_4']:.2f} | {r['e_ratio_12']:.2f} | {r['e_ratio_24']:.2f} | "
                f"{r['p_ret_vs_P_4']:.4f} | {r['p_ret_vs_P_12']:.4f} | {r['p_ret_vs_P_24']:.4f} | "
                f"{r['p_ret_vs_D1_4']:.4f} | {r['p_ret_vs_D1_12']:.4f} | {r['p_ret_vs_D1_24']:.4f} |"
            )

        lines.extend([
            "",
            "### 5.3 Window B E-Ratio 1,000x Bootstrap p-values (+4 / +12 / +24)",
            "| Symbol | TF | Group | N | E-Ratio+4 | E-Ratio+12 | E-Ratio+24 | pER(vs P @4) | pER(vs P @12) | pER(vs P @24) | pER(vs D1 @4) | pER(vs D1 @12) | pER(vs D1 @24) |",
            "| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
        ])
        for r in exp3b_rows:
            lines.append(
                f"| {r['symbol']} | {r['timeframe']} | {r['group']} | {r['n']} | "
                f"{r['e_ratio_4']:.2f} | {r['e_ratio_12']:.2f} | {r['e_ratio_24']:.2f} | "
                f"{r['p_er_vs_P_4']:.4f} | {r['p_er_vs_P_12']:.4f} | {r['p_er_vs_P_24']:.4f} | "
                f"{r.get('p_er_vs_D1_4', 1.0):.4f} | {r.get('p_er_vs_D1_12', 1.0):.4f} | {r.get('p_er_vs_D1_24', 1.0):.4f} |"
            )
    else:
        lines.append("- No valid Window B targets with `top_ls_position_ratio` available.")

    if exp3b_agg:
        lines.extend([
            "",
            "### 5.4 Window B Aggregate Summary (`All` / `1h` / `4h`): `Group P` vs `Group D1` vs `Group D2`",
            "| Scope | Group | Targets (N>0/Total) | Total N | Target-Mean Ret+4 (%) | Target-Mean Ret+12 (%) | Target-Mean Ret+24 (%) | Target-Mean ER+4 | Target-Mean ER+12 | Target-Mean ER+24 | Pooled Ret+4 (%) | Pooled Ret+12 (%) | Pooled Ret+24 (%) | Pooled ER+4 | Pooled ER+12 | Pooled ER+24 | Pooled pRet(vs P @12) | Pooled pRet(vs D1 @12) | Pooled pER(vs P @12) | Pooled pER(vs D1 @12) |",
            "| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
        ])
        for a in exp3b_agg:
            lines.append(
                f"| {a['scope']} | {a['group']} | {a['targets_nonzero']}/{a['targets_total']} | {a['total_n']} | "
                f"{a['mean_ret_4']:+.3f} | {a['mean_ret_12']:+.3f} | {a['mean_ret_24']:+.3f} | "
                f"{a['mean_e_ratio_4']:.2f} | {a['mean_e_ratio_12']:.2f} | {a['mean_e_ratio_24']:.2f} | "
                f"{a['pooled_ret_4']:+.3f} | {a['pooled_ret_12']:+.3f} | {a['pooled_ret_24']:+.3f} | "
                f"{a['pooled_e_ratio_4']:.2f} | {a['pooled_e_ratio_12']:.2f} | {a['pooled_e_ratio_24']:.2f} | "
                f"{a['pooled_p_ret_vs_P_12']:.4f} | {a['pooled_p_ret_vs_D1_12']:.4f} | "
                f"{a['pooled_p_er_vs_P_12']:.4f} | {a['pooled_p_er_vs_D1_12']:.4f} |"
            )

    if exp3b_rows:
        lines.extend(["", "### 5.5 Automated Experiment 3B Statistical Flags (alpha = 0.10)"])
        for r in exp3b_rows:
            if r["group"] in ("Group D1", "Group D2"):
                if r["n"] == 0:
                    lines.append(f"- ⚠️ **{r['symbol']} {r['timeframe']} {r['group']}**: 0 signals / insufficient data.")
                elif r["p_ret_vs_P_12"] > 0.10:
                    lines.append(
                        f"- ⚠️ **{r['symbol']} {r['timeframe']} {r['group']}**: Not statistically significant vs Group P "
                        f"(pRet@12={r['p_ret_vs_P_12']:.4f} > 0.10, Ret+12={r['ret_12']:+.3f}%, pER@12={r['p_er_vs_P_12']:.4f})."
                    )
                else:
                    lines.append(
                        f"- ✅ **{r['symbol']} {r['timeframe']} {r['group']}**: Significant vs Group P "
                        f"(pRet@12={r['p_ret_vs_P_12']:.4f}, Ret+12={r['ret_12']:+.3f}%, "
                        f"pRet_vs_D1@12={r['p_ret_vs_D1_12']:.4f}, pER@12={r['p_er_vs_P_12']:.4f})."
                    )

    # --- Section 6: Window B Stage 1C Backtest Check ---
    wb_stage1c = summary.get("window_b_stage1c", [])
    lines.extend([
        "",
        "## 6. Window B Stage 1C Backtest Check (`5 bps`, `include_funding=True`, `trailing_path_mode='conservative'`): `lsur` vs `top_ls`",
    ])
    if wb_stage1c:
        lines.extend([
            "### 6.1 Per-Target Stage 1C Results",
            "| Symbol | TF | lsur_source | Days | Trades | WR (%) | PF | Exp/Trade (%) | MaxDD (%) | Sharpe | Total Ret (%) | Funding ($) |",
            "| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
        ])
        for r in wb_stage1c:
            lines.append(
                f"| {r['symbol']} | {r['timeframe']} | {r['lsur_source']} | {r['clean_days']} | {r['trades']} | "
                f"{r['win_rate']:.1f} | {r['profit_factor']:.2f} | {r['expectancy_pct']:+.3f} | "
                f"{r['max_drawdown_pct']:.2f} | {r['sharpe']:.2f} | {r['total_return_pct']:+.2f} | {r['total_funding_pnl']:+.2f} |"
            )

        lines.extend([
            "",
            "### 6.2 Window B Stage 1C Aggregate Comparison (`All` / `1h` / `4h`)",
            "| Scope | lsur_source | Targets | Total Trades | Mean WR (%) | Mean PF | Mean Exp (%) | Mean MaxDD (%) | Mean Sharpe |",
            "| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
        ])
        for scope in ("All", "1h", "4h"):
            lsur_keys = {(r["symbol"], r["timeframe"]) for r in wb_stage1c if r["lsur_source"] == "lsur" and (scope == "All" or r["timeframe"] == scope)}
            top_keys = {(r["symbol"], r["timeframe"]) for r in wb_stage1c if r["lsur_source"] == "top_ls" and (scope == "All" or r["timeframe"] == scope)}
            paired_keys = lsur_keys & top_keys
            for src in ("lsur", "top_ls"):
                s_rows = [
                    r for r in wb_stage1c
                    if r["lsur_source"] == src and (r["symbol"], r["timeframe"]) in paired_keys
                ]
                if not s_rows:
                    continue
                lines.append(
                    f"| {scope} | {src} | {len(s_rows)} | {sum(r['trades'] for r in s_rows)} | "
                    f"{float(np.mean([r['win_rate'] for r in s_rows])):.1f} | "
                    f"{float(np.mean([r['profit_factor'] for r in s_rows])):.2f} | "
                    f"{float(np.mean([r['expectancy_pct'] for r in s_rows])):+.3f} | "
                    f"{float(np.mean([r['max_drawdown_pct'] for r in s_rows])):.2f} | "
                    f"{float(np.mean([r['sharpe'] for r in s_rows])):.2f} |"
                )
    else:
        lines.append("- No valid Window B targets available for Stage 1C Backtest Check.")

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Solo-Quant Red-Team Audit Experiment Runner")
    parser.add_argument(
        "--mode",
        choices=["db", "synthetic"],
        default="db",
        help="Execution mode: 'db' (PostgreSQL) or 'synthetic' (offline selftest).",
    )
    parser.add_argument(
        "--synthetic-selftest",
        action="store_true",
        help="Legacy alias for '--mode synthetic' (run on synthetic data offline to verify pipeline code).",
    )
    parser.add_argument("--output-dir", type=str, default=str(ROOT / "scripts" / "debug"))
    args = parser.parse_args()
    use_synthetic = args.synthetic_selftest or (args.mode == "synthetic")
    eff_mode = "synthetic" if use_synthetic else "db"
    run_all_experiments(use_synthetic=use_synthetic, output_dir=Path(args.output_dir), mode=eff_mode)


if __name__ == "__main__":
    main()
