#!/usr/bin/env python3
"""
Phase 1 Empirical Research Prototype: Macro Inflection Model & Falsification Suite.

Compares a pre-registered Two-Layer Macro Inflection Model (Layer 1 1d Causal State Gate +
Layer 2 Right-Side BOS Confirmation, zero symbol hacks) against Legacy v8 across:
  - Dataset L (1d Long Window)
  - Dataset M (14-Month 1d + 4h Window)

Outputs:
  - scripts/debug/macro_inflection_report.md & .json (in --mode db)
  - <output-dir>/macro_inflection_selftest_report.md & .json (in --mode synthetic)

Usage:
  python scripts/run_macro_inflection_experiments.py
  python scripts/run_macro_inflection_experiments.py --mode db --output-dir scripts/debug
  python scripts/run_macro_inflection_experiments.py --mode synthetic --output-dir scripts/debug/_macro_selftest
"""

from __future__ import annotations

import argparse
import bisect
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

SYMBOLS: List[str] = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "HYPE/USDT", "CC/USDT"]
DAY_SEC = 86400
H4_SEC = 14400
H1_SEC = 3600
DEDUP_MIN_GAP_1D = 43200
ALIGN_TOLERANCE_1D = DAY_SEC * 3
WARMUP_1D_BARS = 60
QUANTILE_WINDOW_1D = 90
QUANTILE_MIN_PERIODS_1D = 30
ARM_WINDOW_DAYS = 10
COOLDOWN_1D_BARS = 15
COOLDOWN_4H_BARS = 90


# ---------------------------------------------------------------------------
# Generic timestamp, formatting & sanitization helpers
# ---------------------------------------------------------------------------

def _dt_to_sec(dt: datetime) -> int:
    aware = dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    return int(aware.timestamp())


def _fmt_utc(ts: Optional[int]) -> str:
    if ts is None:
        return "N/A"
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _is_finite_pos(val: Any) -> bool:
    if val is None:
        return False
    try:
        f = float(val)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f) and f > 0.0


def _is_finite(val: Any) -> bool:
    if val is None:
        return False
    try:
        f = float(val)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f)


def _sanitize_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_json(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return f if math.isfinite(f) else None
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


# ---------------------------------------------------------------------------
# Deduplication, contiguity, and strict causal alignment (ZERO .bfill())
# ---------------------------------------------------------------------------

def deduplicate_okx_1d_ohlcv(bars: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Sort 1d OHLCV bars ascending and drop overlapping bars where t_curr - t_prev < 43200
    while keeping the newer bar cleanly.
    """
    valid: List[Dict[str, Any]] = []
    for b in bars:
        t = b.get("time")
        o, h, l, c = b.get("open"), b.get("high"), b.get("low"), b.get("close")
        if t is None or not (_is_finite_pos(o) and _is_finite_pos(h) and _is_finite_pos(l) and _is_finite_pos(c)):
            continue
        vol = float(b.get("volume") or 0.0)
        if not math.isfinite(vol):
            vol = 0.0
        valid.append({
            "time": int(t),
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": vol,
        })
    valid.sort(key=lambda x: x["time"])

    dedup: List[Dict[str, Any]] = []
    for bar in valid:
        if dedup and (bar["time"] - dedup[-1]["time"]) < DEDUP_MIN_GAP_1D:
            dedup[-1] = bar
        else:
            dedup.append(bar)
    return dedup


def deduplicate_subdaily_ohlcv(bars: Sequence[Dict[str, Any]], step_sec: int = H4_SEC) -> List[Dict[str, Any]]:
    """Sort ascending and keep latest bar on exact or sub-half-step duplicates."""
    valid: List[Dict[str, Any]] = []
    min_gap = max(1, step_sec // 2)
    for b in bars:
        t = b.get("time")
        o, h, l, c = b.get("open"), b.get("high"), b.get("low"), b.get("close")
        if t is None or not (_is_finite_pos(o) and _is_finite_pos(h) and _is_finite_pos(l) and _is_finite_pos(c)):
            continue
        vol = float(b.get("volume") or 0.0)
        if not math.isfinite(vol):
            vol = 0.0
        valid.append({
            "time": int(t),
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": vol,
        })
    valid.sort(key=lambda x: x["time"])

    dedup: List[Dict[str, Any]] = []
    for bar in valid:
        if dedup and (bar["time"] - dedup[-1]["time"]) < min_gap:
            dedup[-1] = bar
        else:
            dedup.append(bar)
    return dedup


def find_longest_recent_contiguous_window(
    timestamps: Sequence[int],
    step_sec: int,
    max_gap_mult: int = 4,
) -> Tuple[Optional[int], Optional[int], int]:
    """Return (start_ts, end_ts, count) of the longest recent contiguous segment."""
    if not timestamps:
        return None, None, 0
    ts_sorted = sorted(set(int(t) for t in timestamps))
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
    return max(segments, key=lambda s: (s[2], s[1]))


def align_series_by_known_ts(
    target_known_ts: Sequence[int],
    raw_rows: Sequence[Dict[str, Any]],
    *,
    source_shift_sec: int = DAY_SEC,
    tolerance_sec: int = ALIGN_TOLERANCE_1D,
    value_key: str = "value",
    positive_only: bool = False,
) -> np.ndarray:
    """
    Strictly causal alignment using known_ts = t_row + source_shift_sec.
    Aligns onto target_known_ts via pd.merge_asof(..., on='known_ts', direction='backward', tolerance=tolerance_sec).
    NEVER uses .bfill().
    """
    n = len(target_known_ts)
    if n == 0:
        return np.array([], dtype=float)
    if not raw_rows:
        return np.full(n, np.nan, dtype=float)

    clean_rows: List[Tuple[int, float]] = []
    for r in raw_rows:
        t_raw = r.get("time")
        v_raw = r.get(value_key)
        if t_raw is None:
            continue
        ok = _is_finite_pos(v_raw) if positive_only else _is_finite(v_raw)
        if not ok:
            continue
        clean_rows.append((int(t_raw) + source_shift_sec, float(v_raw)))

    if not clean_rows:
        return np.full(n, np.nan, dtype=float)

    df_src = pd.DataFrame(clean_rows, columns=["known_ts", "val"])
    df_src = df_src.sort_values("known_ts").drop_duplicates(subset=["known_ts"], keep="last").reset_index(drop=True)

    df_tgt = pd.DataFrame({"known_ts": [int(t) for t in target_known_ts], "_pos": np.arange(n)})
    df_tgt_sorted = df_tgt.sort_values("known_ts")

    merged = pd.merge_asof(
        df_tgt_sorted,
        df_src,
        on="known_ts",
        direction="backward",
        tolerance=tolerance_sec,
    )
    merged = merged.sort_values("_pos")
    return merged["val"].to_numpy(dtype=float)


def deduplicate_funding_records(
    raw_records: Sequence[Dict[str, Any]],
    coin: str,
) -> List[Dict[str, Any]]:
    """
    Union both f'{coin}-USDT-SWAP' and f'{coin}/USDT:USDT' FundingRate records,
    deduplicating on timestamp (known_ts = t_funding) and preferring '-USDT-SWAP' on tie.
    """
    swap_sym = f"{coin}-USDT-SWAP"
    ccxt_sym = f"{coin}/USDT:USDT"
    by_ts: Dict[int, Tuple[int, float]] = {}
    for rec in raw_records:
        sym = str(rec.get("symbol") or "")
        if sym not in (swap_sym, ccxt_sym):
            continue
        t = rec.get("time")
        rate = rec.get("funding_rate")
        if t is None or not _is_finite(rate):
            continue
        ts = int(t)
        prio = 1 if sym == swap_sym else 0
        prev = by_ts.get(ts)
        if prev is None or prio >= prev[0]:
            by_ts[ts] = (prio, float(rate))
    return [{"time": ts, "funding_rate": by_ts[ts][1]} for ts in sorted(by_ts.keys())]


def combine_oi_causal(okx_vals: np.ndarray, bin_vals: np.ndarray) -> np.ndarray:
    """
    Causal chain-linked USD Open Interest combination across OKX and Binance.
    Prevents fake step jumps both when a second exchange stream starts mid-history
    and when OI resumes after a multi-bar outage, without any .bfill() look-ahead.
    """
    n = max(len(okx_vals), len(bin_vals))
    out = np.full(n, np.nan, dtype=float)
    prev_valid_idx: Optional[int] = None
    last_o_val: Optional[float] = None
    last_o_out: Optional[float] = None
    last_b_val: Optional[float] = None
    last_b_out: Optional[float] = None

    for i in range(n):
        vo = float(okx_vals[i]) if i < len(okx_vals) else math.nan
        vb = float(bin_vals[i]) if i < len(bin_vals) else math.nan
        ok_o = math.isfinite(vo) and vo > 0.0
        ok_b = math.isfinite(vb) and vb > 0.0
        if not ok_o and not ok_b:
            continue

        if prev_valid_idx is None:
            curr = (vo if ok_o else 0.0) + (vb if ok_b else 0.0)
        else:
            p_o = float(okx_vals[prev_valid_idx]) if prev_valid_idx < len(okx_vals) else math.nan
            p_b = float(bin_vals[prev_valid_idx]) if prev_valid_idx < len(bin_vals) else math.nan
            p_ok_o = math.isfinite(p_o) and p_o > 0.0
            p_ok_b = math.isfinite(p_b) and p_b > 0.0
            prev_val = out[prev_valid_idx]

            if ok_o and ok_b and p_ok_o and p_ok_b:
                curr = prev_val * ((vo + vb) / (p_o + p_b))
            elif ok_o and p_ok_o:
                curr = prev_val * (vo / p_o)
            elif ok_b and p_ok_b:
                curr = prev_val * (vb / p_b)
            elif ok_o and last_o_val is not None and last_o_out is not None:
                curr = last_o_out * (vo / last_o_val)
            elif ok_b and last_b_val is not None and last_b_out is not None:
                curr = last_b_out * (vb / last_b_val)
            else:
                curr = prev_val

        out[i] = curr
        prev_valid_idx = i
        if ok_o:
            last_o_val = vo
            last_o_out = curr
        if ok_b:
            last_b_val = vb
            last_b_out = curr

    return out


def compute_taker_ratio_rows(raw_rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compute scale-invariant taker_ratio = buy / (buy + sell) per exchange row first."""
    out: List[Dict[str, Any]] = []
    for r in raw_rows:
        t = r.get("time")
        buy = r.get("taker_buy_vol")
        sell = r.get("taker_sell_vol")
        if t is None or not (_is_finite(buy) and _is_finite(sell)):
            continue
        b_f = float(buy)
        s_f = float(sell)
        if b_f < 0.0 or s_f < 0.0:
            continue
        tot = b_f + s_f
        if tot <= 0.0:
            continue
        out.append({"time": int(t), "value": b_f / tot})
    return out


def rolling_zscore_causal(values: np.ndarray, window: int = 90, min_periods: int = 30) -> np.ndarray:
    vals = np.asarray(values, dtype=float)
    n = len(vals)
    out = np.full(n, np.nan, dtype=float)
    for i in range(n):
        curr = vals[i]
        if not math.isfinite(curr):
            continue
        w = vals[max(0, i - window + 1) : i + 1]
        valid = w[np.isfinite(w)]
        if len(valid) < min_periods:
            continue
        sd = float(np.std(valid, ddof=1))
        if not math.isfinite(sd) or sd <= 1e-12:
            continue
        out[i] = (curr - float(np.mean(valid))) / sd
    return out


def rolling_percentile_causal(values: np.ndarray, window: int = 90, min_periods: int = 30) -> np.ndarray:
    vals = np.asarray(values, dtype=float)
    n = len(vals)
    out = np.full(n, np.nan, dtype=float)
    for i in range(n):
        curr = vals[i]
        if not math.isfinite(curr):
            continue
        w = vals[max(0, i - window + 1) : i + 1]
        valid = w[np.isfinite(w)]
        if len(valid) < min_periods:
            continue
        if float(np.ptp(valid)) == 0.0:
            out[i] = 50.0
        else:
            out[i] = float(np.sum(valid <= curr) / len(valid) * 100.0)
    return out


def combine_lsur_z_causal(
    okx_lsur: np.ndarray,
    bin_lsur: np.ndarray,
    *,
    window: int = 90,
    min_periods: int = 30,
) -> np.ndarray:
    """Compute causal per-exchange rolling LSUR Z-score and average available finite Z-scores."""
    z_okx = rolling_zscore_causal(okx_lsur, window=window, min_periods=min_periods)
    z_bin = rolling_zscore_causal(bin_lsur, window=window, min_periods=min_periods)
    n = len(okx_lsur)
    out = np.full(n, np.nan, dtype=float)
    for i in range(n):
        bo = math.isfinite(z_okx[i])
        bb = math.isfinite(z_bin[i])
        if bo and bb:
            out[i] = 0.5 * (z_okx[i] + z_bin[i])
        elif bb:
            out[i] = z_bin[i]
        elif bo:
            out[i] = z_okx[i]
    return out


def align_funding_to_1d(
    candle_opens: Sequence[int],
    candle_known_ts: Sequence[int],
    funding_settlements: Sequence[Dict[str, Any]],
) -> np.ndarray:
    """
    Align FundingRate settlements (known_ts = t_funding) onto 1d candles causally.
    Uses mean of settlements falling inside (t_open, t_open + 86400], falling back
    to pd.merge_asof(..., on='known_ts', direction='backward', tolerance=86400 * 3).
    """
    n = len(candle_opens)
    if n == 0 or not funding_settlements:
        return np.full(n, np.nan, dtype=float)

    f_times = [int(f["time"]) for f in funding_settlements if _is_finite(f.get("funding_rate"))]
    f_rates = [float(f["funding_rate"]) for f in funding_settlements if _is_finite(f.get("funding_rate"))]
    if not f_times:
        return np.full(n, np.nan, dtype=float)

    asof_rows = [{"time": t, "value": r} for t, r in zip(f_times, f_rates)]
    fallback = align_series_by_known_ts(
        candle_known_ts,
        asof_rows,
        source_shift_sec=0,
        tolerance_sec=ALIGN_TOLERANCE_1D,
        value_key="value",
        positive_only=False,
    )

    out = np.full(n, np.nan, dtype=float)
    for i in range(n):
        t_lo = int(candle_opens[i])
        t_hi = int(candle_known_ts[i])
        idx_lo = bisect.bisect_right(f_times, t_lo)
        idx_hi = bisect.bisect_right(f_times, t_hi)
        if idx_hi > idx_lo:
            out[i] = float(np.mean(f_rates[idx_lo:idx_hi]))
        elif math.isfinite(fallback[i]):
            out[i] = float(fallback[i])
    return out


# ---------------------------------------------------------------------------
# Wilder ATR / RSI & Bollinger helper functions (Pandas 3.0 CoW safe)
# ---------------------------------------------------------------------------

def compute_wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


def compute_wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gains = delta.where(delta > 0.0, 0.0)
    losses = (-delta).where(delta < 0.0, 0.0)
    avg_gain = gains.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    ag = avg_gain.to_numpy(dtype=float)
    al = avg_loss.to_numpy(dtype=float)
    rsi = np.full(len(ag), np.nan, dtype=float)
    for i in range(len(ag)):
        if not (math.isfinite(ag[i]) and math.isfinite(al[i])):
            continue
        if al[i] <= 1e-15:
            rsi[i] = 100.0 if ag[i] > 1e-15 else 50.0
        else:
            rs = ag[i] / al[i]
            rsi[i] = 100.0 - (100.0 / (1.0 + rs))
    return pd.Series(rsi, index=close.index)


def compute_bb_pctb(close: pd.Series, period: int = 20, std_mult: float = 2.0) -> pd.Series:
    sma = close.rolling(window=period, min_periods=period).mean()
    std = close.rolling(window=period, min_periods=period).std()
    upper = sma + std_mult * std
    lower = sma - std_mult * std
    bw = upper - lower
    c_arr = close.to_numpy(dtype=float)
    l_arr = lower.to_numpy(dtype=float)
    bw_arr = bw.to_numpy(dtype=float)
    out = np.full(len(c_arr), np.nan, dtype=float)
    for i in range(len(c_arr)):
        if not (math.isfinite(c_arr[i]) and math.isfinite(l_arr[i]) and math.isfinite(bw_arr[i])):
            continue
        out[i] = ((c_arr[i] - l_arr[i]) / bw_arr[i]) if bw_arr[i] > 1e-15 else 0.5
    return pd.Series(out, index=close.index)


# ---------------------------------------------------------------------------
# Dataset L (1d Long) & Dataset M (14-Month 1d + 4h) Builders
# ---------------------------------------------------------------------------

def build_dataset_l_from_raw(
    symbol: str,
    ohlcv_1d_raw: Sequence[Dict[str, Any]],
    deriv_1d_by_exch: Dict[str, Sequence[Dict[str, Any]]],
    funding_settlements: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Build Dataset L (1d Long Window) with strict known_ts = t_row + 86400 causality,
    up to 200 prior 1d OHLCV bars for EMA200 warmup, and contiguous derivative coverage
    (at least Coin-OI or Taker available during eval_price).
    """
    candles_1d = deduplicate_okx_1d_ohlcv(ohlcv_1d_raw)
    if not candles_1d:
        return {"symbol": symbol, "timeframe": "1d", "valid": False, "reason": "No 1d OHLCV bars"}

    c_start, c_end, c_cnt = find_longest_recent_contiguous_window(
        [c["time"] for c in candles_1d],
        step_sec=DAY_SEC,
        max_gap_mult=4,
    )
    if c_start is None or c_end is None or c_cnt < WARMUP_1D_BARS + 20:
        return {
            "symbol": symbol,
            "timeframe": "1d",
            "valid": False,
            "reason": f"Insufficient contiguous 1d OHLCV (count={c_cnt})",
        }

    candles_contig = [c for c in candles_1d if c_start <= c["time"] <= c_end]
    opens = [c["time"] for c in candles_contig]
    known_ts = [c["time"] + DAY_SEC for c in candles_contig]

    okx_rows = deriv_1d_by_exch.get("okx", [])
    bin_rows = deriv_1d_by_exch.get("binance", [])

    oi_okx = align_series_by_known_ts(known_ts, okx_rows, source_shift_sec=DAY_SEC, value_key="open_interest", positive_only=True)
    oi_bin = align_series_by_known_ts(known_ts, bin_rows, source_shift_sec=DAY_SEC, value_key="open_interest", positive_only=True)
    oi_usd = combine_oi_causal(oi_okx, oi_bin)

    closes = np.array([c["close"] for c in candles_contig], dtype=float)
    coin_oi = np.where(np.isfinite(oi_usd) & (oi_usd > 0.0) & (closes > 0.0), oi_usd / closes, np.nan)

    bin_taker_rows = compute_taker_ratio_rows(bin_rows)
    okx_taker_rows = compute_taker_ratio_rows(okx_rows)
    taker_bin = align_series_by_known_ts(known_ts, bin_taker_rows, source_shift_sec=DAY_SEC, value_key="value", positive_only=False)
    taker_okx = align_series_by_known_ts(known_ts, okx_taker_rows, source_shift_sec=DAY_SEC, value_key="value", positive_only=False)
    taker_ratio = np.where(np.isfinite(taker_bin), taker_bin, taker_okx)

    lsur_okx = align_series_by_known_ts(known_ts, okx_rows, source_shift_sec=DAY_SEC, value_key="long_short_ratio", positive_only=True)
    lsur_bin = align_series_by_known_ts(known_ts, bin_rows, source_shift_sec=DAY_SEC, value_key="long_short_ratio", positive_only=True)
    lsur_z = combine_lsur_z_causal(lsur_okx, lsur_bin, window=QUANTILE_WINDOW_1D, min_periods=QUANTILE_MIN_PERIODS_1D)

    funding_daily = align_funding_to_1d(opens, known_ts, funding_settlements)

    # Identify longest contiguous 1d derivative coverage window (Coin-OI or Taker available)
    deriv_cov_ts = [
        opens[i]
        for i in range(len(candles_contig))
        if math.isfinite(coin_oi[i]) or math.isfinite(taker_ratio[i])
    ]
    d_start, d_end, d_cnt = find_longest_recent_contiguous_window(deriv_cov_ts, step_sec=DAY_SEC, max_gap_mult=4)
    if d_start is None or d_end is None or d_cnt < 30:
        return {
            "symbol": symbol,
            "timeframe": "1d",
            "valid": False,
            "reason": f"Insufficient 1d derivative coverage (Coin-OI/Taker bars={d_cnt})",
        }

    start_idx = next(i for i, c in enumerate(candles_contig) if c["time"] >= d_start)
    end_idx = max(i for i, c in enumerate(candles_contig) if c["time"] <= d_end)
    warmup_start_idx = max(0, start_idx - 200)

    # Slice arrays from warmup_start_idx .. end_idx (retaining up to 200 prior 1d bars)
    candles_win = candles_contig[warmup_start_idx : end_idx + 1]
    opens_win = opens[warmup_start_idx : end_idx + 1]
    known_win = known_ts[warmup_start_idx : end_idx + 1]
    oi_usd_win = oi_usd[warmup_start_idx : end_idx + 1]
    coin_oi_win = coin_oi[warmup_start_idx : end_idx + 1]
    taker_win = taker_ratio[warmup_start_idx : end_idx + 1]
    lsur_z_win = lsur_z[warmup_start_idx : end_idx + 1]
    funding_win = funding_daily[warmup_start_idx : end_idx + 1]

    # Ensure eval_start satisfies >= 60 total 1d bars warmup AND >= min(30, clean//6) derivative bars
    clean_bars_count = end_idx - start_idx + 1
    deriv_skip = min(30, max(0, clean_bars_count // 6))
    min_eval_rel_idx = max(WARMUP_1D_BARS, (start_idx - warmup_start_idx) + deriv_skip)
    if min_eval_rel_idx >= len(candles_win) - 10:
        return {
            "symbol": symbol,
            "timeframe": "1d",
            "valid": False,
            "reason": f"Insufficient eval bars after warmup (total={len(candles_win)}, min_eval={min_eval_rel_idx})",
        }

    eval_start = candles_win[min_eval_rel_idx]["time"]
    clean_end = candles_win[-1]["time"]
    eval_price = candles_win[min_eval_rel_idx:]

    # Build IndicatorEngine inputs for Legacy_v8_1d
    oi_aligned = [
        {"time": opens_win[i], "value": float(oi_usd_win[i])}
        for i in range(len(candles_win))
        if math.isfinite(oi_usd_win[i]) and oi_usd_win[i] > 0.0
    ]
    taker_for_cvd = [
        {
            "time": opens_win[i],
            "buy_vol": 1000.0 * float(taker_win[i]),
            "sell_vol": 1000.0 * (1.0 - float(taker_win[i])),
        }
        for i in range(len(candles_win))
        if math.isfinite(taker_win[i])
    ]
    cvd_aligned = IndicatorEngine.calculate_cvd_history(taker_for_cvd) if taker_for_cvd else []
    lsur_z_aligned = [
        {"time": opens_win[i], "value": round(float(lsur_z_win[i]), 3)}
        for i in range(len(candles_win))
        if math.isfinite(lsur_z_win[i])
    ]
    funding_aligned = [
        {"time": opens_win[i], "value": float(funding_win[i]) * 100.0}
        for i in range(len(candles_win))
        if math.isfinite(funding_win[i])
    ]

    ema_trend = IndicatorEngine.calculate_ema_trend(candles_win, symbol=symbol)
    rsi_hist = IndicatorEngine.calculate_rsi(candles_win)
    bb_pctb = IndicatorEngine.calculate_bollinger_bands(candles_win)["bb_pctb"]
    donchian = IndicatorEngine.calculate_donchian_channel(candles_win, period=20)
    macd_hist = IndicatorEngine.calculate_macd(candles_win)
    regime_hist = IndicatorEngine.calculate_market_regime_history(candles_win, cvd_aligned=cvd_aligned)
    pulse_hist = IndicatorEngine.calculate_composite_score(
        price_data=candles_win,
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

    df_1d = pd.DataFrame(candles_win)
    df_1d["known_ts"] = known_win
    df_1d["oi_usd"] = oi_usd_win
    df_1d["coin_oi"] = coin_oi_win
    df_1d["taker_ratio"] = taker_win
    df_1d["lsur_z_90d"] = lsur_z_win
    df_1d["funding_daily"] = funding_win

    funding_eval = [
        f for f in funding_settlements
        if (eval_start - 8 * H1_SEC) <= f["time"] <= (clean_end + DAY_SEC)
    ]

    clean_days = round((clean_end - eval_start) / float(DAY_SEC), 2)
    return {
        "symbol": symbol,
        "timeframe": "1d",
        "dataset_name": "Dataset L (1d)",
        "valid": True,
        "clean_start": d_start,
        "eval_start": eval_start,
        "clean_end": clean_end,
        "clean_days": clean_days,
        "clean_bars": len(eval_price),
        "warmup_bars": min_eval_rel_idx,
        "coin_oi_eval_bars": int(np.sum(np.isfinite(coin_oi_win[min_eval_rel_idx:]))),
        "taker_eval_bars": int(np.sum(np.isfinite(taker_win[min_eval_rel_idx:]))),
        "lsur_eval_bars": int(np.sum(np.isfinite(lsur_z_win[min_eval_rel_idx:]))),
        "funding_eval_bars": int(np.sum(np.isfinite(funding_win[min_eval_rel_idx:]))),
        "funding_count": len(funding_eval),
        "price_with_warmup": candles_win,
        "eval_price": eval_price,
        "df_1d": df_1d,
        "oi_aligned": oi_aligned,
        "cvd_aligned": cvd_aligned,
        "lsur_z_aligned": lsur_z_aligned,
        "funding_aligned": funding_aligned,
        "funding_settlements": funding_eval,
        "ema_fast": ema_trend["ema_fast"],
        "ema_slow": ema_trend["ema_slow"],
        "rsi_hist": rsi_hist,
        "bb_pctb": bb_pctb,
        "donchian": donchian,
        "macd_hist": macd_hist,
        "regime_history": regime_hist,
        "pulse_history": pulse_hist,
    }


def _bucket_subdaily_to_4h(
    deriv_sub_rows: Sequence[Dict[str, Any]],
    exchange: str,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Aggregate native '4h' and '1h' derivative rows into 4h buckets [t_4h, t_4h + 14400),
    preferring native '1h' buckets over stale '4h' rows on overlap.
    Each bucket timestamp t_4h is known at t_4h + 14400.
    """
    oi_buckets: Dict[int, List[float]] = {}
    lsur_buckets: Dict[int, List[float]] = {}
    taker_buckets: Dict[int, List[Tuple[float, float]]] = {}

    for tf_name in ("4h", "1h"):
        temp_oi: Dict[int, List[float]] = {}
        temp_ls: Dict[int, List[float]] = {}
        temp_tk: Dict[int, List[Tuple[float, float]]] = {}
        for r in deriv_sub_rows:
            if r.get("exchange") != exchange or str(r.get("timeframe", "")).lower() != tf_name:
                continue
            t_raw = r.get("time")
            if t_raw is None:
                continue
            bucket = (int(t_raw) // H4_SEC) * H4_SEC
            if _is_finite_pos(r.get("open_interest")):
                temp_oi.setdefault(bucket, []).append(float(r["open_interest"]))
            if _is_finite_pos(r.get("long_short_ratio")):
                temp_ls.setdefault(bucket, []).append(float(r["long_short_ratio"]))
            buy, sell = r.get("taker_buy_vol"), r.get("taker_sell_vol")
            if _is_finite(buy) and _is_finite(sell) and float(buy) >= 0.0 and float(sell) >= 0.0 and (float(buy) + float(sell)) > 0.0:
                temp_tk.setdefault(bucket, []).append((float(buy), float(sell)))
        for b, vals in temp_oi.items():
            oi_buckets[b] = vals
        for b, vals in temp_ls.items():
            lsur_buckets[b] = vals
        for b, pairs in temp_tk.items():
            taker_buckets[b] = pairs

    oi_list = [{"time": b, "value": float(sum(v) / len(v))} for b, v in sorted(oi_buckets.items()) if v]
    ls_list = [{"time": b, "value": float(sum(v) / len(v))} for b, v in sorted(lsur_buckets.items()) if v]
    tk_list: List[Dict[str, Any]] = []
    for b, pairs in sorted(taker_buckets.items()):
        sb = float(sum(p[0] for p in pairs))
        ss = float(sum(p[1] for p in pairs))
        if (sb + ss) > 0.0:
            tk_list.append({"time": b, "value": sb / (sb + ss)})
    return {"oi": oi_list, "lsur": ls_list, "taker_ratio": tk_list}


def build_dataset_m_from_raw(
    symbol: str,
    ohlcv_4h_raw: Sequence[Dict[str, Any]],
    dataset_l: Dict[str, Any],
    deriv_sub_rows: Sequence[Dict[str, Any]],
    deriv_1d_by_exch: Dict[str, Sequence[Dict[str, Any]]],
    funding_settlements: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Build Dataset M (14-Month 1d + 4h Window):
      - 4h OKX OHLCV with >= 200 bars warmup
      - 4h derivatives from native 1h/4h + causal closed 1d fallback (t_1d + 86400 <= t_4h + 14400)
      - FundingRate settlements
    """
    if not dataset_l.get("valid"):
        return {"symbol": symbol, "timeframe": "4h", "valid": False, "reason": "Dataset L invalid"}

    candles_4h = deduplicate_subdaily_ohlcv(ohlcv_4h_raw, step_sec=H4_SEC)
    if not candles_4h:
        return {"symbol": symbol, "timeframe": "4h", "valid": False, "reason": "No 4h OHLCV bars"}

    c_start, c_end, c_cnt = find_longest_recent_contiguous_window(
        [c["time"] for c in candles_4h],
        step_sec=H4_SEC,
        max_gap_mult=4,
    )
    if c_start is None or c_end is None or c_cnt < 240:
        return {"symbol": symbol, "timeframe": "4h", "valid": False, "reason": f"Insufficient contiguous 4h OHLCV ({c_cnt})"}

    candles_win = [c for c in candles_4h if c_start <= c["time"] <= c_end]
    warmup_bars = min(200, max(50, len(candles_win) // 5))
    if len(candles_win) <= warmup_bars + 30:
        return {"symbol": symbol, "timeframe": "4h", "valid": False, "reason": f"Too few 4h bars ({len(candles_win)})"}

    opens_4h = [c["time"] for c in candles_win]
    known_4h = [c["time"] + H4_SEC for c in candles_win]

    # Native 4h derivatives (from 1h preferred + 4h)
    sub_okx = _bucket_subdaily_to_4h(deriv_sub_rows, "okx")
    sub_bin = _bucket_subdaily_to_4h(deriv_sub_rows, "binance")

    oi_okx_nat = align_series_by_known_ts(known_4h, sub_okx["oi"], source_shift_sec=H4_SEC, tolerance_sec=H4_SEC * 4, value_key="value", positive_only=True)
    oi_bin_nat = align_series_by_known_ts(known_4h, sub_bin["oi"], source_shift_sec=H4_SEC, tolerance_sec=H4_SEC * 4, value_key="value", positive_only=True)
    oi_nat = combine_oi_causal(oi_okx_nat, oi_bin_nat)

    # Closed 1d fallback OI (t_1d + 86400 <= t_4h + 14400)
    df_1d = dataset_l["df_1d"]
    oi_1d_rows = [
        {"time": int(row["time"]), "value": float(row["oi_usd"])}
        for _, row in df_1d.iterrows()
        if math.isfinite(row["oi_usd"]) and row["oi_usd"] > 0.0
    ]
    oi_1d_fallback = align_series_by_known_ts(
        known_4h,
        oi_1d_rows,
        source_shift_sec=DAY_SEC,
        tolerance_sec=ALIGN_TOLERANCE_1D,
        value_key="value",
        positive_only=True,
    )
    # Chain-link native 4h OI and causal 1d fallback OI cleanly without step jumps
    oi_4h_usd = combine_oi_causal(
        np.where(np.isfinite(oi_nat), oi_nat, np.nan),
        np.where(np.isfinite(oi_nat), np.nan, oi_1d_fallback),
    )

    # Taker ratio: native (binance > okx) -> closed 1d fallback
    tk_bin_nat = align_series_by_known_ts(known_4h, sub_bin["taker_ratio"], source_shift_sec=H4_SEC, tolerance_sec=H4_SEC * 4, value_key="value", positive_only=False)
    tk_okx_nat = align_series_by_known_ts(known_4h, sub_okx["taker_ratio"], source_shift_sec=H4_SEC, tolerance_sec=H4_SEC * 4, value_key="value", positive_only=False)
    tk_nat = np.where(np.isfinite(tk_bin_nat), tk_bin_nat, tk_okx_nat)

    tk_1d_rows = [
        {"time": int(row["time"]), "value": float(row["taker_ratio"])}
        for _, row in df_1d.iterrows()
        if math.isfinite(row["taker_ratio"])
    ]
    tk_1d_fallback = align_series_by_known_ts(
        known_4h,
        tk_1d_rows,
        source_shift_sec=DAY_SEC,
        tolerance_sec=ALIGN_TOLERANCE_1D,
        value_key="value",
        positive_only=False,
    )
    tk_is_native = np.isfinite(tk_nat)
    taker_4h = np.where(tk_is_native, tk_nat, tk_1d_fallback)

    # LSUR Z-score: native 4h per-exchange Z-score -> closed 1d Z-score fallback
    ls_okx_nat = align_series_by_known_ts(known_4h, sub_okx["lsur"], source_shift_sec=H4_SEC, tolerance_sec=H4_SEC * 4, value_key="value", positive_only=True)
    ls_bin_nat = align_series_by_known_ts(known_4h, sub_bin["lsur"], source_shift_sec=H4_SEC, tolerance_sec=H4_SEC * 4, value_key="value", positive_only=True)
    ls_z_nat = combine_lsur_z_causal(ls_okx_nat, ls_bin_nat, window=90, min_periods=14)

    ls_z_1d_rows = [
        {"time": int(row["time"]), "value": float(row["lsur_z_90d"])}
        for _, row in df_1d.iterrows()
        if math.isfinite(row["lsur_z_90d"])
    ]
    ls_z_1d_fallback = align_series_by_known_ts(
        known_4h,
        ls_z_1d_rows,
        source_shift_sec=DAY_SEC,
        tolerance_sec=ALIGN_TOLERANCE_1D,
        value_key="value",
        positive_only=False,
    )
    lsur_z_4h = np.where(np.isfinite(ls_z_nat), ls_z_nat, ls_z_1d_fallback)

    # Funding aligned causally at t_4h + 14400
    f_rows = [{"time": int(f["time"]), "value": float(f["funding_rate"]) * 100.0} for f in funding_settlements if _is_finite(f.get("funding_rate"))]
    funding_4h_pct = align_series_by_known_ts(
        known_4h,
        f_rows,
        source_shift_sec=0,
        tolerance_sec=ALIGN_TOLERANCE_1D,
        value_key="value",
        positive_only=False,
    )

    eval_start = candles_win[warmup_bars]["time"]
    clean_end = candles_win[-1]["time"]
    eval_price = candles_win[warmup_bars:]

    oi_aligned = [
        {"time": opens_4h[i], "value": float(oi_4h_usd[i])}
        for i in range(len(candles_win))
        if math.isfinite(oi_4h_usd[i]) and oi_4h_usd[i] > 0.0
    ]
    taker_for_cvd = [
        {
            "time": opens_4h[i],
            "buy_vol": (1000.0 if tk_is_native[i] else 1000.0 / 6.0) * float(taker_4h[i]),
            "sell_vol": (1000.0 if tk_is_native[i] else 1000.0 / 6.0) * (1.0 - float(taker_4h[i])),
        }
        for i in range(len(candles_win))
        if math.isfinite(taker_4h[i])
    ]
    cvd_aligned = IndicatorEngine.calculate_cvd_history(taker_for_cvd) if taker_for_cvd else []
    lsur_z_aligned = [
        {"time": opens_4h[i], "value": round(float(lsur_z_4h[i]), 3)}
        for i in range(len(candles_win))
        if math.isfinite(lsur_z_4h[i])
    ]
    funding_aligned = [
        {"time": opens_4h[i], "value": float(funding_4h_pct[i])}
        for i in range(len(candles_win))
        if math.isfinite(funding_4h_pct[i])
    ]

    ema_trend = IndicatorEngine.calculate_ema_trend(candles_win, symbol=symbol)
    rsi_hist = IndicatorEngine.calculate_rsi(candles_win)
    bb_pctb = IndicatorEngine.calculate_bollinger_bands(candles_win)["bb_pctb"]
    donchian = IndicatorEngine.calculate_donchian_channel(candles_win, period=20)
    macd_hist = IndicatorEngine.calculate_macd(candles_win)
    regime_hist = IndicatorEngine.calculate_market_regime_history(candles_win, cvd_aligned=cvd_aligned)
    pulse_hist = IndicatorEngine.calculate_composite_score(
        price_data=candles_win,
        lsur_z_aligned=lsur_z_aligned,
        cvd_aligned=cvd_aligned,
        funding_aligned=funding_aligned,
        rsi_aligned=rsi_hist,
        ema_fast_aligned=ema_trend["ema_fast"],
        bb_pctb_aligned=bb_pctb,
        oi_aligned=oi_aligned,
        timeframe="4h",
        symbol=symbol,
        use_dynamic_profiles=True,
    )

    funding_eval = [
        f for f in funding_settlements
        if (eval_start - 8 * H1_SEC) <= f["time"] <= (clean_end + H4_SEC)
    ]

    clean_days = round((clean_end - eval_start) / float(DAY_SEC), 2)
    return {
        "symbol": symbol,
        "timeframe": "4h",
        "dataset_name": "Dataset M (1d+4h)",
        "valid": True,
        "clean_start": candles_win[0]["time"],
        "eval_start": eval_start,
        "clean_end": clean_end,
        "clean_days": clean_days,
        "clean_bars": len(eval_price),
        "warmup_bars": warmup_bars,
        "native_oi_eval_bars": int(np.sum(np.isfinite(oi_nat[warmup_bars:]))),
        "fallback_oi_eval_bars": int(np.sum(~np.isfinite(oi_nat[warmup_bars:]) & np.isfinite(oi_4h_usd[warmup_bars:]))),
        "native_taker_eval_bars": int(np.sum(tk_is_native[warmup_bars:])),
        "fallback_taker_eval_bars": int(np.sum(~tk_is_native[warmup_bars:] & np.isfinite(taker_4h[warmup_bars:]))),
        "funding_count": len(funding_eval),
        "price_with_warmup": candles_win,
        "eval_price": eval_price,
        "oi_aligned": oi_aligned,
        "cvd_aligned": cvd_aligned,
        "lsur_z_aligned": lsur_z_aligned,
        "funding_aligned": funding_aligned,
        "funding_settlements": funding_eval,
        "ema_fast": ema_trend["ema_fast"],
        "ema_slow": ema_trend["ema_slow"],
        "rsi_hist": rsi_hist,
        "bb_pctb": bb_pctb,
        "donchian": donchian,
        "macd_hist": macd_hist,
        "regime_history": regime_hist,
        "pulse_history": pulse_hist,
    }


def load_datasets_from_db(
    symbols: Sequence[str] = SYMBOLS,
    session_factory: Optional[Callable[[], Any]] = None,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Load Dataset L (1d) and Dataset M (1d+4h) from PostgreSQL (or injected SQLAlchemy session factory)."""
    if session_factory is None:
        from api.db.database import SessionLocal
        session_factory = SessionLocal
    from api.db.models import MarketDataPoint, FundingRate

    datasets_l: Dict[str, Dict[str, Any]] = {}
    datasets_m: Dict[str, Dict[str, Any]] = {}

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
            rows_4h_ohlcv = (
                db.query(MarketDataPoint)
                .filter(
                    MarketDataPoint.symbol == sym,
                    MarketDataPoint.timeframe == "4h",
                    MarketDataPoint.exchange == "okx",
                    MarketDataPoint.open.isnot(None),
                )
                .order_by(MarketDataPoint.timestamp.asc())
                .all()
            )
            rows_sub_deriv = (
                db.query(MarketDataPoint)
                .filter(
                    MarketDataPoint.symbol == sym,
                    MarketDataPoint.timeframe.in_(["1h", "4h"]),
                )
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
                "time": _dt_to_sec(r.timestamp),
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            }
            for r in rows_1d
            if r.exchange == "okx" and r.open is not None
        ]

        deriv_1d_by_exch: Dict[str, List[Dict[str, Any]]] = {"okx": [], "binance": []}
        for r in rows_1d:
            ex = str(r.exchange or "").lower()
            if ex in deriv_1d_by_exch:
                deriv_1d_by_exch[ex].append({
                    "time": _dt_to_sec(r.timestamp),
                    "open_interest": r.open_interest,
                    "long_short_ratio": r.long_short_ratio,
                    "taker_buy_vol": r.taker_buy_vol,
                    "taker_sell_vol": r.taker_sell_vol,
                })

        ohlcv_4h_raw = [
            {
                "time": _dt_to_sec(r.timestamp),
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            }
            for r in rows_4h_ohlcv
        ]

        deriv_sub_rows = [
            {
                "time": _dt_to_sec(r.timestamp),
                "exchange": str(r.exchange or "").lower(),
                "timeframe": str(r.timeframe or "").lower(),
                "open_interest": r.open_interest,
                "long_short_ratio": r.long_short_ratio,
                "taker_buy_vol": r.taker_buy_vol,
                "taker_sell_vol": r.taker_sell_vol,
            }
            for r in rows_sub_deriv
        ]

        funding_raw = [
            {
                "time": _dt_to_sec(r.timestamp),
                "symbol": r.symbol,
                "funding_rate": r.funding_rate,
            }
            for r in funding_rows
        ]
        funding_settlements = deduplicate_funding_records(funding_raw, coin=coin)

        ds_l = build_dataset_l_from_raw(sym, ohlcv_1d_raw, deriv_1d_by_exch, funding_settlements)
        datasets_l[sym] = ds_l
        datasets_m[sym] = build_dataset_m_from_raw(
            sym, ohlcv_4h_raw, ds_l, deriv_sub_rows, deriv_1d_by_exch, funding_settlements
        )

    return datasets_l, datasets_m


# ---------------------------------------------------------------------------
# Pre-Registered Two-Layer Macro Inflection Model (Zero Symbol Hacks)
# ---------------------------------------------------------------------------

def evaluate_layer1_1d(df_1d: pd.DataFrame) -> pd.DataFrame:
    """
    Evaluate strictly causal 1d Layer 1 features and bottom/top state gates.
    Expects df_1d sorted ascending by time/known_ts with columns:
      time, known_ts, open, high, low, close, volume, coin_oi, taker_ratio, lsur_z_90d, funding_daily.
    """
    df = df_1d.sort_values("time").reset_index(drop=True).copy()
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()
    atr14 = compute_wilder_atr(high, low, close, period=14)
    rsi14 = compute_wilder_rsi(close, period=14)
    bb_pctb = compute_bb_pctb(close, period=20, std_mult=2.0)

    max_high_60d = high.rolling(window=60, min_periods=60).max()
    min_low_60d = low.rolling(window=60, min_periods=60).min()

    atr_pos = atr14.where(atr14 > 1e-12, np.nan)
    z_ema50 = (close - ema50) / atr_pos
    dd_60d_atr = (max_high_60d - low) / atr_pos
    rally_60d_atr = (high - min_low_60d) / atr_pos

    warm = pd.Series(np.arange(len(df)) >= WARMUP_1D_BARS, index=df.index)
    price_bottom_zone = (
        warm
        & ((z_ema50 <= -1.8) | (dd_60d_atr >= 3.5))
        & ((rsi14 <= 42.0) | (bb_pctb <= 0.15))
    ).fillna(False)

    price_top_zone = (
        warm
        & ((z_ema50 >= 2.4) | (rally_60d_atr >= 4.5))
        & ((rsi14 >= 66.0) | (bb_pctb >= 0.85))
    ).fillna(False)

    # Derivative condition 1: Coin-OI
    coin_oi = df["coin_oi"].astype(float)
    coin_oi_max_30d = coin_oi.rolling(window=30, min_periods=25).max()
    coin_oi_dd_30d = np.where(
        coin_oi.notna() & coin_oi_max_30d.notna() & (coin_oi_max_30d > 0.0),
        (coin_oi / coin_oi_max_30d - 1.0) * 100.0,
        np.nan,
    )
    coin_oi_pct_90d = rolling_percentile_causal(
        coin_oi.to_numpy(dtype=float), window=QUANTILE_WINDOW_1D, min_periods=QUANTILE_MIN_PERIODS_1D
    )
    coin_oi_shift14 = coin_oi.shift(14)
    coin_oi_chg_14d = np.where(
        coin_oi.notna() & coin_oi_shift14.notna() & (coin_oi_shift14 > 0.0),
        (coin_oi / coin_oi_shift14 - 1.0) * 100.0,
        np.nan,
    )

    # Derivative condition 2: Funding Rate & LSUR Z-Score
    funding_daily = df["funding_daily"].astype(float)
    fr_3d_raw = funding_daily.rolling(window=3, min_periods=1).mean()
    fr_3d = np.where(funding_daily.notna(), fr_3d_raw.to_numpy(dtype=float), np.nan)
    fr_pct_90d = rolling_percentile_causal(
        funding_daily.to_numpy(dtype=float), window=QUANTILE_WINDOW_1D, min_periods=QUANTILE_MIN_PERIODS_1D
    )
    lsur_z = df["lsur_z_90d"].to_numpy(dtype=float)

    # Derivative condition 3: Taker Ratio 5d price-taker divergence or directional threshold
    taker_ratio = df["taker_ratio"].astype(float)
    taker_3d_mean = taker_ratio.rolling(window=3, min_periods=3).mean()
    taker_prev5d_mean = taker_ratio.rolling(window=5, min_periods=5).mean().shift(3)
    close_5d_ago = close.shift(5)

    tr_arr = taker_ratio.to_numpy(dtype=float)
    tr3_arr = taker_3d_mean.to_numpy(dtype=float)
    trp5_arr = taker_prev5d_mean.to_numpy(dtype=float)
    c_arr = close.to_numpy(dtype=float)
    c5_arr = close_5d_ago.to_numpy(dtype=float)

    n = len(df)
    deriv_bottom_ok = np.zeros(n, dtype=bool)
    deriv_top_ok = np.zeros(n, dtype=bool)

    for i in range(n):
        if i < WARMUP_1D_BARS:
            continue

        # Condition 1 (Coin-OI)
        oi_b = (
            (math.isfinite(coin_oi_dd_30d[i]) and coin_oi_dd_30d[i] <= -7.0)
            or (math.isfinite(coin_oi_pct_90d[i]) and coin_oi_pct_90d[i] <= 35.0)
        )
        oi_t = (
            (math.isfinite(coin_oi_pct_90d[i]) and coin_oi_pct_90d[i] >= 75.0)
            or (math.isfinite(coin_oi_chg_14d[i]) and coin_oi_chg_14d[i] >= 12.0)
        )

        # Condition 2 (Funding / LSUR)
        pos_b = (
            (math.isfinite(fr_3d[i]) and fr_3d[i] <= 0.0)
            or (math.isfinite(fr_pct_90d[i]) and fr_pct_90d[i] <= 25.0)
            or (math.isfinite(lsur_z[i]) and lsur_z[i] <= -1.0)
        )
        pos_t = (
            (math.isfinite(fr_pct_90d[i]) and fr_pct_90d[i] >= 80.0)
            or (math.isfinite(lsur_z[i]) and lsur_z[i] >= 1.0)
        )

        # Condition 3 (Taker 5d divergence or taker_ratio threshold)
        div_b = (
            math.isfinite(c5_arr[i])
            and math.isfinite(tr3_arr[i])
            and math.isfinite(trp5_arr[i])
            and (c_arr[i] < c5_arr[i])
            and (tr3_arr[i] > trp5_arr[i])
        )
        tk_b = div_b or (math.isfinite(tr_arr[i]) and tr_arr[i] >= 0.51)

        div_t = (
            math.isfinite(c5_arr[i])
            and math.isfinite(tr3_arr[i])
            and math.isfinite(trp5_arr[i])
            and (c_arr[i] > c5_arr[i])
            and (tr3_arr[i] < trp5_arr[i])
        )
        tk_t = div_t or (math.isfinite(tr_arr[i]) and tr_arr[i] <= 0.48)

        deriv_bottom_ok[i] = oi_b or pos_b or tk_b
        deriv_top_ok[i] = oi_t or pos_t or tk_t

    df["ema20"] = ema20
    df["ema50"] = ema50
    df["ema200"] = ema200
    df["atr14"] = atr14
    df["rsi14"] = rsi14
    df["bb_pctb"] = bb_pctb
    df["z_ema50"] = z_ema50
    df["dd_60d_atr"] = dd_60d_atr
    df["rally_60d_atr"] = rally_60d_atr
    df["price_bottom_zone"] = price_bottom_zone.to_numpy(dtype=bool)
    df["price_top_zone"] = price_top_zone.to_numpy(dtype=bool)
    df["deriv_bottom_ok"] = deriv_bottom_ok
    df["deriv_top_ok"] = deriv_top_ok
    df["pd_bottom_zone"] = df["price_bottom_zone"].to_numpy(dtype=bool) & deriv_bottom_ok
    df["pd_top_zone"] = df["price_top_zone"].to_numpy(dtype=bool) & deriv_top_ok
    return df


def compute_1d_macro_signals(
    ds_l: Dict[str, Any],
    variant: str,
) -> Tuple[List[Dict[str, Any]], pd.DataFrame]:
    """
    Generate 1d macro signals for:
      - 'Macro_LeftOnly_1d': fires on first bar Layer 1 (price & deriv) activates, 15d cooldown
      - 'Macro_P_1d': Layer 1 price_zone ONLY + Layer 2 1d BOS, 15d cooldown
      - 'Macro_PD_1d': Layer 1 (price_zone & deriv_ok) + Layer 2 1d BOS, 15d cooldown
    """
    l1 = evaluate_layer1_1d(ds_l["df_1d"])
    eval_start = int(ds_l["eval_start"])
    n = len(l1)

    opens = l1["open"].to_numpy(dtype=float)
    highs = l1["high"].to_numpy(dtype=float)
    lows = l1["low"].to_numpy(dtype=float)
    closes = l1["close"].to_numpy(dtype=float)
    times = l1["time"].to_numpy(dtype=int)
    ema20 = l1["ema20"].to_numpy(dtype=float)

    if variant == "Macro_P_1d":
        l1_bull = l1["price_bottom_zone"].to_numpy(dtype=bool)
        l1_bear = l1["price_top_zone"].to_numpy(dtype=bool)
    elif variant in ("Macro_PD_1d", "Macro_LeftOnly_1d"):
        l1_bull = l1["pd_bottom_zone"].to_numpy(dtype=bool)
        l1_bear = l1["pd_top_zone"].to_numpy(dtype=bool)
    else:
        raise ValueError(f"Unsupported 1d macro variant: {variant!r}")

    markers: List[Dict[str, Any]] = []
    last_bull_idx = -1000
    last_bear_idx = -1000

    if variant == "Macro_LeftOnly_1d":
        prev_bull_active = False
        prev_bear_active = False
        bull_episode_emitted = False
        bear_episode_emitted = False
        for i in range(WARMUP_1D_BARS, n):
            curr_b = bool(l1_bull[i])
            curr_s = bool(l1_bear[i])
            if curr_b and not prev_bull_active:
                bull_episode_emitted = False
            if curr_s and not prev_bear_active:
                bear_episode_emitted = False

            if curr_b and not bull_episode_emitted and (i - last_bull_idx >= COOLDOWN_1D_BARS):
                markers.append({
                    "time": int(times[i]),
                    "direction": "bullish",
                    "score": 5.0,
                    "strategy_type": "macro_left",
                    "text": "MACRO_LEFT_BOTTOM",
                })
                bull_episode_emitted = True
                last_bull_idx = i
            elif curr_s and not bear_episode_emitted and (i - last_bear_idx >= COOLDOWN_1D_BARS):
                markers.append({
                    "time": int(times[i]),
                    "direction": "bearish",
                    "score": 5.0,
                    "strategy_type": "macro_left",
                    "text": "MACRO_LEFT_TOP",
                })
                bear_episode_emitted = True
                last_bear_idx = i

            prev_bull_active = curr_b
            prev_bear_active = curr_s
        return [m for m in markers if m["time"] >= eval_start], l1

    # Two-layer BOS variants (Macro_P_1d, Macro_PD_1d)
    roll_max_5 = l1["high"].rolling(window=5, min_periods=5).max().shift(1).to_numpy(dtype=float)
    roll_min_5 = l1["low"].rolling(window=5, min_periods=5).min().shift(1).to_numpy(dtype=float)
    roll_max_3 = l1["high"].rolling(window=3, min_periods=3).max().shift(1).to_numpy(dtype=float)
    roll_min_3 = l1["low"].rolling(window=3, min_periods=3).min().shift(1).to_numpy(dtype=float)
    prev_close = l1["close"].shift(1).to_numpy(dtype=float)
    prev_ema20 = l1["ema20"].shift(1).to_numpy(dtype=float)
    prev_high = l1["high"].shift(1).to_numpy(dtype=float)

    bottom_armed_until = -1
    bottom_arm_bar: Optional[int] = None
    top_armed_until = -1
    top_arm_bar: Optional[int] = None

    for i in range(WARMUP_1D_BARS, n):
        # Layer 1 arming (do NOT clear opposite armed window here!)
        if l1_bull[i]:
            if bottom_armed_until < i or bottom_arm_bar is None:
                bottom_arm_bar = i
            bottom_armed_until = i + ARM_WINDOW_DAYS
        if l1_bear[i]:
            if top_armed_until < i or top_arm_bar is None:
                top_arm_bar = i
            top_armed_until = i + ARM_WINDOW_DAYS

        bull_fired = False
        if i <= bottom_armed_until and (i - last_bull_idx >= COOLDOWN_1D_BARS) and closes[i] > opens[i]:
            cond_bos5 = math.isfinite(roll_max_5[i]) and closes[i] > roll_max_5[i]
            cond_ema20 = (
                math.isfinite(prev_close[i])
                and math.isfinite(prev_ema20[i])
                and math.isfinite(ema20[i])
                and closes[i] > ema20[i]
                and prev_close[i] <= prev_ema20[i]
            )
            cond_bos3 = (
                bottom_arm_bar is not None
                and i >= bottom_arm_bar + 2
                and math.isfinite(prev_high[i])
                and math.isfinite(roll_max_3[i])
                and closes[i] > prev_high[i]
                and highs[i] > lows[i]
                and (closes[i] - lows[i]) >= 0.6 * (highs[i] - lows[i])
                and closes[i] > roll_max_3[i]
            )
            if cond_bos5 or cond_ema20 or cond_bos3:
                markers.append({
                    "time": int(times[i]),
                    "direction": "bullish",
                    "score": 6.0,
                    "strategy_type": "macro_bos",
                    "text": "MACRO_BOTTOM",
                })
                last_bull_idx = i
                bull_fired = True
                bottom_armed_until = -1
                bottom_arm_bar = None
                top_armed_until = -1
                top_arm_bar = None

        if not bull_fired and i <= top_armed_until and (i - last_bear_idx >= COOLDOWN_1D_BARS) and closes[i] < opens[i]:
            cond_bos5 = math.isfinite(roll_min_5[i]) and closes[i] < roll_min_5[i]
            cond_ema20 = (
                math.isfinite(prev_close[i])
                and math.isfinite(prev_ema20[i])
                and math.isfinite(ema20[i])
                and closes[i] < ema20[i]
                and prev_close[i] >= prev_ema20[i]
            )
            cond_bos3 = (
                top_arm_bar is not None
                and i >= top_arm_bar + 2
                and math.isfinite(roll_min_3[i])
                and closes[i] < roll_min_3[i]
                and highs[i] > lows[i]
                and (highs[i] - closes[i]) >= 0.6 * (highs[i] - lows[i])
            )
            if cond_bos5 or cond_ema20 or cond_bos3:
                markers.append({
                    "time": int(times[i]),
                    "direction": "bearish",
                    "score": 6.0,
                    "strategy_type": "macro_bos",
                    "text": "MACRO_TOP",
                })
                last_bear_idx = i
                top_armed_until = -1
                top_arm_bar = None
                bottom_armed_until = -1
                bottom_arm_bar = None

    return [m for m in markers if m["time"] >= eval_start], l1


def compute_4h_macro_signals(
    ds_m: Dict[str, Any],
    l1_df: pd.DataFrame,
) -> List[Dict[str, Any]]:
    """
    Macro_PD_1d_4h:
      - Receives closed 1d Layer-1 (price_zone & deriv_ok) strictly when t_1d + 86400 <= t_4h + 14400.
      - Active while 0 <= t_4h_close - t_1d_last_active_close <= 10 * 86400.
      - Clears opposite armed window only upon confirmed opposite Layer 2 4h BOS.
      - Minimum 90 4h bars (15 days) same-direction cooldown.
      - MACRO_BOTTOM_4H: close_4h > Donchian20_upper_4h.shift(1) AND close_4h > EMA50_4h AND RSI14_4h >= 52
      - MACRO_TOP_4H: close_4h < Donchian20_lower_4h.shift(1) AND close_4h < EMA50_4h AND RSI14_4h <= 48
    """
    price_4h = ds_m["price_with_warmup"]
    if not price_4h or l1_df.empty:
        return []

    df_4h = pd.DataFrame(price_4h).sort_values("time").reset_index(drop=True)
    closes = df_4h["close"].astype(float)
    highs = df_4h["high"].astype(float)
    lows = df_4h["low"].astype(float)

    don_upper = highs.rolling(window=20, min_periods=20).max().shift(1).to_numpy(dtype=float)
    don_lower = lows.rolling(window=20, min_periods=20).min().shift(1).to_numpy(dtype=float)
    ema50 = closes.ewm(span=50, adjust=False).mean().to_numpy(dtype=float)
    rsi14 = compute_wilder_rsi(closes, period=14).to_numpy(dtype=float)

    c_arr = closes.to_numpy(dtype=float)
    t_arr = df_4h["time"].to_numpy(dtype=int)

    bottom_1d_closes = sorted(
        int(row["known_ts"])
        for _, row in l1_df.iterrows()
        if bool(row["pd_bottom_zone"])
    )
    top_1d_closes = sorted(
        int(row["known_ts"])
        for _, row in l1_df.iterrows()
        if bool(row["pd_top_zone"])
    )

    eval_start = int(ds_m["eval_start"])
    markers: List[Dict[str, Any]] = []
    last_bull_idx = -1000
    last_bear_idx = -1000
    cleared_bottom_until = -1
    cleared_top_until = -1

    for m in range(50, len(df_4h)):
        t_4h = int(t_arr[m])
        t_4h_close = t_4h + H4_SEC

        b_pos = bisect.bisect_right(bottom_1d_closes, t_4h_close) - 1
        t_1d_b = bottom_1d_closes[b_pos] if b_pos >= 0 else None
        bottom_armed = (
            t_1d_b is not None
            and t_1d_b > cleared_bottom_until
            and 0 <= (t_4h_close - t_1d_b) <= (ARM_WINDOW_DAYS * DAY_SEC)
        )

        t_pos = bisect.bisect_right(top_1d_closes, t_4h_close) - 1
        t_1d_t = top_1d_closes[t_pos] if t_pos >= 0 else None
        top_armed = (
            t_1d_t is not None
            and t_1d_t > cleared_top_until
            and 0 <= (t_4h_close - t_1d_t) <= (ARM_WINDOW_DAYS * DAY_SEC)
        )

        bull_fired = False
        if (
            bottom_armed
            and (m - last_bull_idx >= COOLDOWN_4H_BARS)
            and math.isfinite(don_upper[m])
            and math.isfinite(ema50[m])
            and math.isfinite(rsi14[m])
            and c_arr[m] > don_upper[m]
            and c_arr[m] > ema50[m]
            and rsi14[m] >= 52.0
        ):
            markers.append({
                "time": t_4h,
                "direction": "bullish",
                "score": 6.0,
                "strategy_type": "macro_bos_4h",
                "text": "MACRO_BOTTOM_4H",
            })
            last_bull_idx = m
            cleared_top_until = t_4h_close
            bull_fired = True

        if (
            not bull_fired
            and top_armed
            and (m - last_bear_idx >= COOLDOWN_4H_BARS)
            and math.isfinite(don_lower[m])
            and math.isfinite(ema50[m])
            and math.isfinite(rsi14[m])
            and c_arr[m] < don_lower[m]
            and c_arr[m] < ema50[m]
            and rsi14[m] <= 48.0
        ):
            markers.append({
                "time": t_4h,
                "direction": "bearish",
                "score": 6.0,
                "strategy_type": "macro_bos_4h",
                "text": "MACRO_TOP_4H",
            })
            last_bear_idx = m
            cleared_bottom_until = t_4h_close

    return [m for m in markers if m["time"] >= eval_start]


def build_btc_macro_history(btc_ds: Optional[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
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


def run_legacy_v8_signals(
    ds: Dict[str, Any],
    btc_ds: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Run IndicatorEngine.calculate_confluence_signals directly (mtf_close_aligned=True, causal BTC history)."""
    btc_macro_hist = None if "BTC" in ds["symbol"].upper() else build_btc_macro_history(btc_ds)
    markers, _ = IndicatorEngine.calculate_confluence_signals(
        price_data=ds["price_with_warmup"],
        lsur_z_aligned=ds["lsur_z_aligned"],
        cvd_aligned=ds["cvd_aligned"],
        oi_percentile=50.0,  # Causal rolling oi_pct_series covers valid bars; neutral fallback avoids full-series leak
        funding_aligned=ds["funding_aligned"],
        rsi_aligned=ds["rsi_hist"],
        ema_fast_aligned=ds["ema_fast"],
        ema_slow_aligned=ds["ema_slow"],
        bb_pctb_aligned=ds["bb_pctb"],
        donchian_aligned=ds["donchian"],
        macd_aligned=ds["macd_hist"],
        timeframe=ds["timeframe"],
        oi_aligned=ds["oi_aligned"],
        ranging_threshold=3,
        trending_threshold=3,
        enable_protection=True,
        symbol=ds["symbol"],
        use_dynamic_profiles=True,
        higher_tf_regime_history=None,
        btc_macro_regime=None,
        btc_macro_history=btc_macro_hist,
        mtf_close_aligned=True,
        setup_symmetry=True,
        use_coin_oi_all=True,
    )
    eval_start = int(ds["eval_start"])
    return [m for m in markers if m["time"] >= eval_start]


# ---------------------------------------------------------------------------
# Multi-Horizon Inflection Quality (+5d, +14d, +30d) & 1,000x Bootstrap
# ---------------------------------------------------------------------------

def compute_multi_horizon_outcomes(
    price_data: Sequence[Dict[str, Any]],
    signals: Sequence[Dict[str, Any]],
    step_sec: int,
) -> List[Dict[str, Any]]:
    """
    Compute directional forward outcomes over +5d, +14d, +30d:
      - ret_5d / ret_14d / ret_30d (%)
      - mfe_14d / mae_14d / mfe_30d / mae_30d (%)
      - major_wave_capture: +10% MFE within 30d strictly before -5% MAE bar-by-bar
    """
    bars_per_day = max(1, DAY_SEC // step_sec)
    h5 = 5 * bars_per_day
    h14 = 14 * bars_per_day
    h30 = 30 * bars_per_day

    time_to_idx = {int(p["time"]): idx for idx, p in enumerate(price_data)}
    n = len(price_data)
    outcomes: List[Dict[str, Any]] = []

    for sig in signals:
        idx = time_to_idx.get(int(sig["time"]))
        if idx is None:
            continue
        entry = float(price_data[idx]["close"])
        if entry <= 0.0:
            continue
        direction = sig.get("direction", "bullish")
        if direction not in ("bullish", "bearish"):
            continue

        row: Dict[str, Any] = {
            "time": int(sig["time"]),
            "direction": direction,
            "ret_5d": None,
            "ret_14d": None,
            "ret_30d": None,
            "mfe_14d": None,
            "mae_14d": None,
            "mfe_30d": None,
            "mae_30d": None,
            "major_wave_capture": None,
        }

        for label, h_bars in (("5d", h5), ("14d", h14), ("30d", h30)):
            if idx + h_bars >= n:
                continue
            window = price_data[idx + 1 : idx + h_bars + 1]
            c_end = float(window[-1]["close"])
            highs = [float(b["high"]) for b in window]
            lows = [float(b["low"]) for b in window]
            if direction == "bullish":
                ret = (c_end - entry) / entry * 100.0
                mfe = max(0.0, (max(highs) - entry) / entry * 100.0)
                mae = max(0.0, (entry - min(lows)) / entry * 100.0)
            else:
                ret = (entry - c_end) / entry * 100.0
                mfe = max(0.0, (entry - min(lows)) / entry * 100.0)
                mae = max(0.0, (max(highs) - entry) / entry * 100.0)
            row[f"ret_{label}"] = ret
            if label in ("14d", "30d"):
                row[f"mfe_{label}"] = mfe
                row[f"mae_{label}"] = mae

        if idx + h30 < n:
            captured = False
            for k in range(idx + 1, idx + h30 + 1):
                bh = float(price_data[k]["high"])
                bl = float(price_data[k]["low"])
                if direction == "bullish":
                    fav = (bh - entry) / entry * 100.0
                    adv = (entry - bl) / entry * 100.0
                else:
                    fav = (entry - bl) / entry * 100.0
                    adv = (bh - entry) / entry * 100.0
                # Conservative: if -5% MAE hits before OR on the same bar as +10% MFE -> False
                if adv >= 5.0:
                    captured = False
                    break
                if fav >= 10.0:
                    captured = True
                    break
            row["major_wave_capture"] = captured

        outcomes.append(row)
    return outcomes


def bootstrap_diff_pvalue(
    sample_a: Sequence[float],
    sample_b: Sequence[float],
    n_boot: int = 1000,
    seed: int = 42,
) -> float:
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
    return round(float(np.mean(np.abs(boot_diffs) >= abs(obs_diff))), 4)


def bootstrap_eratio_diff_pvalue(
    mfe_a: Sequence[float],
    mae_a: Sequence[float],
    mfe_b: Sequence[float],
    mae_b: Sequence[float],
    n_boot: int = 1000,
    seed: int = 42,
) -> float:
    """Two-sided bootstrap test for difference in Wave E-Ratio = median(MFE) / median(MAE)."""
    if len(mfe_a) < 2 or len(mfe_b) < 2:
        return 1.0
    ma_f = np.asarray(mfe_a, dtype=float)
    ma_e = np.asarray(mae_a, dtype=float)
    mb_f = np.asarray(mfe_b, dtype=float)
    mb_e = np.asarray(mae_b, dtype=float)
    obs_a = float(np.median(ma_f) / max(float(np.median(ma_e)), 1e-4))
    obs_b = float(np.median(mb_f) / max(float(np.median(mb_e)), 1e-4))
    obs_diff = obs_a - obs_b
    if obs_diff == 0.0:
        return 1.0
    rng = np.random.default_rng(seed)
    comb_f = np.concatenate([ma_f, mb_f])
    comb_e = np.concatenate([ma_e, mb_e])
    na, n_tot = len(ma_f), len(comb_f)
    ge_count = 0
    for _ in range(n_boot):
        idx = rng.integers(0, n_tot, size=n_tot)
        ea = float(np.median(comb_f[idx[:na]]) / max(float(np.median(comb_e[idx[:na]])), 1e-4))
        eb = float(np.median(comb_f[idx[na:]]) / max(float(np.median(comb_e[idx[na:]])), 1e-4))
        if abs(ea - eb) >= abs(obs_diff):
            ge_count += 1
    return round(ge_count / n_boot, 4)


def summarize_inflection_metrics(
    symbol: str,
    timeframe: str,
    variant: str,
    clean_days: float,
    total_signals: int,
    outcomes: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    r5 = [o["ret_5d"] for o in outcomes if o["ret_5d"] is not None]
    r14 = [o["ret_14d"] for o in outcomes if o["ret_14d"] is not None]
    r30 = [o["ret_30d"] for o in outcomes if o["ret_30d"] is not None]
    mfe14 = [o["mfe_14d"] for o in outcomes if o["mfe_14d"] is not None]
    mae14 = [o["mae_14d"] for o in outcomes if o["mae_14d"] is not None]
    mfe30 = [o["mfe_30d"] for o in outcomes if o["mfe_30d"] is not None]
    mae30 = [o["mae_30d"] for o in outcomes if o["mae_30d"] is not None]
    mwc = [o["major_wave_capture"] for o in outcomes if o["major_wave_capture"] is not None]

    med_mfe14 = float(np.median(mfe14)) if mfe14 else 0.0
    med_mae14 = float(np.median(mae14)) if mae14 else 0.0
    med_mfe30 = float(np.median(mfe30)) if mfe30 else 0.0
    med_mae30 = float(np.median(mae30)) if mae30 else 0.0

    sig_yr = (total_signals / max(clean_days / 365.0, 1e-4)) if clean_days > 0.0 else 0.0
    hit14 = (sum(1 for x in r14 if x > 0.0) / len(r14) * 100.0) if r14 else 0.0
    mwc_pct = (sum(1 for x in mwc if x) / len(mwc) * 100.0) if mwc else 0.0

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "variant": variant,
        "clean_days": round(float(clean_days), 2),
        "signals": int(total_signals),
        "signals_per_yr": round(float(sig_yr), 2),
        "n_5d": len(r5),
        "n_14d": len(r14),
        "n_30d": len(r30),
        "hit_14d": round(float(hit14), 1),
        "ret_5d": round(float(np.mean(r5)), 3) if r5 else 0.0,
        "ret_14d": round(float(np.mean(r14)), 3) if r14 else 0.0,
        "ret_30d": round(float(np.mean(r30)), 3) if r30 else 0.0,
        "med_mfe_14d": round(med_mfe14, 2),
        "med_mae_14d": round(med_mae14, 2),
        "med_mfe_30d": round(med_mfe30, 2),
        "med_mae_30d": round(med_mae30, 2),
        "e_ratio_14d": round(med_mfe14 / max(med_mae14, 1e-4), 2) if mfe14 else 0.0,
        "e_ratio_30d": round(med_mfe30 / max(med_mae30, 1e-4), 2) if mfe30 else 0.0,
        "major_wave_capture_pct": round(float(mwc_pct), 1),
    }


# ---------------------------------------------------------------------------
# Wide-ATR Macro Swing Backtester (Conservative OHLC Stops + Chandelier)
# ---------------------------------------------------------------------------

@dataclass
class _MacroPosition:
    side: str
    entry_price: float
    entry_time: int
    size: float
    stop_loss: float
    entry_atr: float
    signal_price: float
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    cost: float = 0.0
    trailing_active: bool = False
    trailing_stop_price: float = 0.0
    highest_since_entry: float = 0.0
    lowest_since_entry: float = float("inf")
    funding_pnl: float = 0.0
    exit_price: float = 0.0
    exit_time: int = 0
    exit_reason: str = ""
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    is_closed: bool = False

    def __post_init__(self) -> None:
        self.cost = self.entry_price * self.size
        self.highest_since_entry = self.entry_price
        self.lowest_since_entry = self.entry_price


class WideATRBacktester:
    """
    Wide-ATR Macro Swing Backtester:
      - 0.05% fee_rate + adverse slippage_bps on market/stop fills
      - Causal FundingRate settlement PnL
      - Initial SL: 2.5 * ATR14
      - Chandelier trailing: 3.0 * ATR14 activated at +1.5 * ATR14 unrealized move
      - No narrow TP cap; reverse on opposite macro signal
      - 1.5% equity risk sizing capped at <= 0.95x notional
      - Conservative intra-bar OHLC stop order
    """

    def __init__(
        self,
        price_data: Sequence[Dict[str, Any]],
        signals: Sequence[Dict[str, Any]],
        *,
        funding_rates: Optional[Sequence[Dict[str, Any]]] = None,
        atr_warmup_candles: Optional[Sequence[Dict[str, Any]]] = None,
        investment: float = 10000.0,
        risk_per_trade_pct: float = 1.5,
        max_notional_pct: float = 0.95,
        fee_rate: float = 0.0005,
        slippage_bps: float = 5.0,
        include_funding: bool = True,
        initial_sl_atr_mult: float = 2.5,
        chandelier_act_atr_mult: float = 1.5,
        chandelier_trail_atr_mult: float = 3.0,
    ) -> None:
        self.price_data = list(price_data)
        self.signals = list(signals)
        self.investment = float(investment)
        self.risk_per_trade_pct = float(risk_per_trade_pct)
        self.max_notional_pct = float(max_notional_pct)
        self.fee_rate = float(fee_rate)
        self.slippage_bps = float(slippage_bps)
        self.include_funding = bool(include_funding)
        self.initial_sl_atr_mult = float(initial_sl_atr_mult)
        self.chandelier_act_atr_mult = float(chandelier_act_atr_mult)
        self.chandelier_trail_atr_mult = float(chandelier_trail_atr_mult)

        self.signal_map: Dict[int, Dict[str, Any]] = {}
        for sig in self.signals:
            self.signal_map[int(sig["time"])] = sig

        # Causal Wilder ATR14 computed across warmup+eval candles when provided
        atr_source = list(atr_warmup_candles) if atr_warmup_candles else self.price_data
        self.atr_map: Dict[int, float] = {}
        if atr_source:
            df_atr = pd.DataFrame(atr_source).sort_values("time").reset_index(drop=True)
            atr_s = compute_wilder_atr(
                df_atr["high"].astype(float),
                df_atr["low"].astype(float),
                df_atr["close"].astype(float),
                period=14,
            )
            for idx, r in df_atr.iterrows():
                val = float(atr_s.iloc[idx])
                if not math.isfinite(val) or val <= 0.0:
                    val = max(float(r["high"]) - float(r["low"]), float(r["close"]) * 0.01)
                self.atr_map[int(r["time"])] = val

        self.bar_interval = DAY_SEC
        if len(self.price_data) >= 2:
            deltas = [
                int(self.price_data[k + 1]["time"]) - int(self.price_data[k]["time"])
                for k in range(len(self.price_data) - 1)
                if int(self.price_data[k + 1]["time"]) > int(self.price_data[k]["time"])
            ]
            if deltas:
                self.bar_interval = int(np.median(deltas))

        self.funding_events: List[Dict[str, float]] = []
        if funding_rates and self.price_data:
            dedup_f: Dict[int, float] = {}
            for fs in funding_rates:
                if fs is None or "time" not in fs:
                    continue
                raw_r = fs.get("funding_rate", fs.get("rate"))
                if not _is_finite(raw_r):
                    continue
                dedup_f[int(fs["time"])] = float(raw_r)
            self.funding_events = [
                {"time": ft, "funding_rate": dedup_f[ft]}
                for ft in sorted(dedup_f.keys())
            ]

        self.balance: float = self.investment
        self.open_positions: List[_MacroPosition] = []
        self.closed_positions: List[_MacroPosition] = []
        self.trades: List[Dict[str, Any]] = []
        self.equity_curve: List[Dict[str, Any]] = []
        self.total_fees_paid: float = 0.0
        self.total_funding_pnl: float = 0.0

    def _apply_slippage(self, price: float, side: str, is_entry: bool) -> float:
        slip = max(0.0, self.slippage_bps) / 10000.0
        if slip <= 0.0:
            return price
        is_buy = (side == "long" and is_entry) or (side == "short" and not is_entry)
        return price * (1.0 + slip) if is_buy else price * (1.0 - slip)

    def _calculate_equity(self, current_price: float) -> float:
        pos_val = 0.0
        for pos in self.open_positions:
            if pos.side == "long":
                pos_val += pos.size * current_price
            else:
                unrealized = (pos.entry_price - current_price) * pos.size
                pos_val += pos.cost + unrealized
        return self.balance + pos_val

    def _close_position(self, pos: _MacroPosition, exit_price: float, time: int, reason: str) -> None:
        if pos.is_closed:
            return
        pos.exit_price = exit_price
        pos.exit_time = time
        pos.exit_reason = reason
        pos.is_closed = True

        raw_pnl = (
            (exit_price - pos.entry_price) * pos.size
            if pos.side == "long"
            else (pos.entry_price - exit_price) * pos.size
        )
        entry_fee = pos.cost * self.fee_rate
        exit_fee = exit_price * pos.size * self.fee_rate
        fees = entry_fee + exit_fee
        pos.fees_paid = fees
        pos.realized_pnl = (raw_pnl - fees) + pos.funding_pnl
        self.total_fees_paid += fees

        returned_cash = pos.cost + raw_pnl - exit_fee
        self.balance += returned_cash
        self.closed_positions.append(pos)
        self.trades.append({
            "time": time,
            "side": f"close_{pos.side}",
            "price": exit_price,
            "amount": pos.size,
            "fee": fees,
            "realized_pnl": round(pos.realized_pnl, 4),
            "exit_reason": reason,
            "position_id": pos.id,
            "equity": self._calculate_equity(exit_price),
        })

    def _process_exits(self, open_p: float, high: float, low: float, close: float, time: int) -> None:
        still_open: List[_MacroPosition] = []
        atr_now = max(self.atr_map.get(time, max(high - low, close * 0.01)), 1e-12)

        for pos in self.open_positions:
            # Step A: Check existing SL / active Chandelier Trail from prior bars (or open gap)
            if pos.side == "long":
                eff_stop = max(pos.stop_loss, pos.trailing_stop_price) if pos.trailing_active else pos.stop_loss
                reason = "trailing" if (pos.trailing_active and pos.trailing_stop_price >= pos.stop_loss) else "sl"
                if open_p <= eff_stop:
                    fill = self._apply_slippage(open_p, "long", is_entry=False)
                    self._close_position(pos, fill, time, reason)
                    continue
                if low <= eff_stop:
                    raw_fill = min(eff_stop, high)
                    fill = self._apply_slippage(raw_fill, "long", is_entry=False)
                    self._close_position(pos, fill, time, reason)
                    continue
            else:
                eff_stop = min(pos.stop_loss, pos.trailing_stop_price) if pos.trailing_active else pos.stop_loss
                reason = "trailing" if (pos.trailing_active and pos.trailing_stop_price <= pos.stop_loss) else "sl"
                if open_p >= eff_stop:
                    fill = self._apply_slippage(open_p, "short", is_entry=False)
                    self._close_position(pos, fill, time, reason)
                    continue
                if high >= eff_stop:
                    raw_fill = max(eff_stop, low)
                    fill = self._apply_slippage(raw_fill, "short", is_entry=False)
                    self._close_position(pos, fill, time, reason)
                    continue

            # Step B: Update favorable extreme & Chandelier trailing stop
            if pos.side == "long":
                if high > pos.highest_since_entry:
                    pos.highest_since_entry = high
                if (pos.highest_since_entry - pos.entry_price) >= (self.chandelier_act_atr_mult * pos.entry_atr):
                    pos.trailing_active = True
                    cand = max(pos.stop_loss, pos.highest_since_entry - self.chandelier_trail_atr_mult * atr_now)
                    if cand > pos.trailing_stop_price:
                        pos.trailing_stop_price = cand

                # Conservative intra-bar OHLC stop order: if trailing active and low or close <= trailing_stop_price
                if pos.trailing_active and (low <= pos.trailing_stop_price or close <= pos.trailing_stop_price):
                    raw_fill = min(max(pos.trailing_stop_price, low), high)
                    fill = self._apply_slippage(raw_fill, "long", is_entry=False)
                    self._close_position(pos, fill, time, "trailing")
                    continue
            else:
                if low < pos.lowest_since_entry:
                    pos.lowest_since_entry = low
                if (pos.entry_price - pos.lowest_since_entry) >= (self.chandelier_act_atr_mult * pos.entry_atr):
                    pos.trailing_active = True
                    cand = min(pos.stop_loss, pos.lowest_since_entry + self.chandelier_trail_atr_mult * atr_now)
                    if pos.trailing_stop_price == 0.0 or cand < pos.trailing_stop_price:
                        pos.trailing_stop_price = cand

                if pos.trailing_active and (high >= pos.trailing_stop_price or close >= pos.trailing_stop_price):
                    raw_fill = min(max(pos.trailing_stop_price, low), high)
                    fill = self._apply_slippage(raw_fill, "short", is_entry=False)
                    self._close_position(pos, fill, time, "trailing")
                    continue

            still_open.append(pos)

        self.open_positions = still_open

    def _process_signal(self, signal: Dict[str, Any], candle: Dict[str, Any]) -> None:
        direction = signal.get("direction")
        if direction == "bullish":
            target_side, opposite_side = "long", "short"
        elif direction == "bearish":
            target_side, opposite_side = "short", "long"
        else:
            return

        close = float(candle["close"])
        time = int(candle["time"])

        # Reverse close any opposite open position
        remaining: List[_MacroPosition] = []
        for pos in self.open_positions:
            if pos.side == opposite_side:
                rev_fill = self._apply_slippage(close, pos.side, is_entry=False)
                self._close_position(pos, rev_fill, time, "signal_reverse")
            else:
                remaining.append(pos)
        self.open_positions = remaining

        if any(p.side == target_side for p in self.open_positions):
            return

        current_equity = self._calculate_equity(close)
        if current_equity <= 0.0 or self.balance <= 0.0:
            return

        entry_price = self._apply_slippage(close, target_side, is_entry=True)
        atr_entry = max(self.atr_map.get(time, max(float(candle["high"]) - float(candle["low"]), close * 0.01)), 1e-12)
        stop_loss = (
            close - self.initial_sl_atr_mult * atr_entry
            if target_side == "long"
            else close + self.initial_sl_atr_mult * atr_entry
        )
        if target_side == "long" and (stop_loss <= 0.0 or entry_price <= stop_loss):
            return
        if target_side == "short" and entry_price >= stop_loss:
            return

        sl_distance = abs(entry_price - stop_loss)
        if sl_distance <= 0.0:
            return

        risk_amount = current_equity * (self.risk_per_trade_pct / 100.0)
        size = risk_amount / sl_distance
        max_notional = min(self.balance, current_equity) * self.max_notional_pct
        max_size = max_notional / entry_price
        if size > max_size:
            size = max_size

        cost = size * entry_price
        if size <= 0.0 or cost <= 0.0:
            return

        entry_fee = cost * self.fee_rate
        self.balance -= (cost + entry_fee)

        pos = _MacroPosition(
            side=target_side,
            entry_price=entry_price,
            entry_time=time,
            size=size,
            stop_loss=stop_loss,
            entry_atr=atr_entry,
            signal_price=close,
        )
        self.open_positions.append(pos)
        self.trades.append({
            "time": time,
            "side": f"open_{target_side}",
            "price": entry_price,
            "amount": size,
            "fee": entry_fee,
            "realized_pnl": 0.0,
            "exit_reason": "",
            "position_id": pos.id,
            "equity": self._calculate_equity(close),
        })

    def run(self) -> Dict[str, Any]:
        if not self.price_data:
            return {
                "trades": [],
                "equity": [],
                "final_balance": self.investment,
                "total_fees_paid": 0.0,
                "total_funding_pnl": 0.0,
                "metrics": self._compute_metrics(),
            }

        f_idx = 0
        n_candles = len(self.price_data)
        first_time = int(self.price_data[0]["time"])
        while f_idx < len(self.funding_events) and self.funding_events[f_idx]["time"] <= first_time:
            f_idx += 1

        for i, candle in enumerate(self.price_data):
            open_p = float(candle["open"])
            high = float(candle["high"])
            low = float(candle["low"])
            close = float(candle["close"])
            time = int(candle["time"])
            next_time = int(self.price_data[i + 1]["time"]) if i + 1 < n_candles else (time + self.bar_interval)

            self._process_exits(open_p, high, low, close, time)

            while f_idx < len(self.funding_events) and self.funding_events[f_idx]["time"] <= next_time:
                fs = self.funding_events[f_idx]
                if self.include_funding and fs["time"] > time and self.open_positions:
                    rate = fs["funding_rate"]
                    for pos in self.open_positions:
                        notional = pos.size * close
                        f_pnl = (-notional * rate) if pos.side == "long" else (notional * rate)
                        self.balance += f_pnl
                        pos.funding_pnl += f_pnl
                        self.total_funding_pnl += f_pnl
                f_idx += 1

            sig = self.signal_map.get(time)
            if sig:
                self._process_signal(sig, candle)

            self.equity_curve.append({"time": time, "value": self._calculate_equity(close)})

        last = self.price_data[-1]
        if self.open_positions:
            for pos in list(self.open_positions):
                self._close_position(pos, float(last["close"]), int(last["time"]), "backtest_end")
            self.open_positions = []
            if self.equity_curve:
                self.equity_curve[-1]["value"] = self._calculate_equity(float(last["close"]))

        final_balance = self.balance
        return {
            "trades": self.trades,
            "equity": self.equity_curve,
            "final_balance": round(final_balance, 4),
            "total_fees_paid": round(self.total_fees_paid, 4),
            "total_funding_pnl": round(self.total_funding_pnl, 4),
            "metrics": self._compute_metrics(),
        }

    def _compute_metrics(self) -> Dict[str, Any]:
        if not self.closed_positions:
            return {
                "trades": 0,
                "wins_count": 0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "trade_rets": [],
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "expectancy_pct": 0.0,
                "total_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "mar_ratio": 0.0,
                "sharpe": 0.0,
            }

        wins = [p for p in self.closed_positions if p.realized_pnl > 0.0]
        losses = [p for p in self.closed_positions if p.realized_pnl <= 0.0]
        total = len(self.closed_positions)
        win_rate = len(wins) / total * 100.0 if total else 0.0

        gross_profit = sum(p.realized_pnl for p in wins)
        gross_loss = abs(sum(p.realized_pnl for p in losses))
        if gross_loss > 0.0:
            pf = min(gross_profit / gross_loss, 999.9)
        else:
            pf = 999.9 if gross_profit > 0.0 else 0.0

        trade_rets = [
            (p.realized_pnl / p.cost * 100.0) if p.cost > 0.0 else 0.0
            for p in self.closed_positions
        ]
        expectancy_pct = float(np.mean(trade_rets)) if trade_rets else 0.0

        final_bal = self.balance
        total_ret_pct = (final_bal - self.investment) / self.investment * 100.0

        days = 1.0
        if len(self.price_data) >= 2:
            days = max((int(self.price_data[-1]["time"]) - int(self.price_data[0]["time"])) / float(DAY_SEC), 1.0)
        ann_ret_pct = ((final_bal / self.investment) ** (365.0 / days) - 1.0) * 100.0 if final_bal > 0.0 else -100.0

        max_dd = 0.0
        if self.equity_curve:
            peak = float(self.equity_curve[0]["value"])
            for e in self.equity_curve:
                v = float(e["value"])
                if v > peak:
                    peak = v
                if peak > 0.0:
                    dd = (peak - v) / peak * 100.0
                    if dd > max_dd:
                        max_dd = dd

        mar = (ann_ret_pct / max(max_dd, 0.01)) if max_dd > 0.0 else (999.0 if ann_ret_pct > 0.0 else 0.0)
        mar = max(-999.0, min(999.0, mar))

        sharpe = 0.0
        if len(self.equity_curve) >= 2:
            vals = np.array([float(e["value"]) for e in self.equity_curve], dtype=float)
            prev = vals[:-1]
            rets = np.where(prev > 0.0, np.diff(vals) / prev, 0.0)
            sd = float(np.std(rets))
            if sd > 1e-12:
                interval_hours = max(self.bar_interval / float(H1_SEC), 1.0 / 60.0)
                sharpe = float(np.mean(rets) / sd * math.sqrt(8760.0 / interval_hours))

        return {
            "trades": total,
            "wins_count": len(wins),
            "gross_profit": float(gross_profit),
            "gross_loss": float(gross_loss),
            "trade_rets": trade_rets,
            "win_rate": round(float(win_rate), 1),
            "profit_factor": round(float(pf), 2),
            "expectancy_pct": round(float(expectancy_pct), 3),
            "total_return_pct": round(float(total_ret_pct), 2),
            "max_drawdown_pct": round(float(max_dd), 2),
            "mar_ratio": round(float(mar), 2),
            "sharpe": round(float(sharpe), 2),
        }


def run_wide_atr_backtest_slice(
    ds: Dict[str, Any],
    signals: Sequence[Dict[str, Any]],
    *,
    price_slice: Optional[Sequence[Dict[str, Any]]] = None,
    slippage_bps: float = 5.0,
) -> Dict[str, Any]:
    candles = list(price_slice) if price_slice is not None else list(ds["eval_price"])
    if not candles:
        return {}
    t0 = int(candles[0]["time"])
    t1 = int(candles[-1]["time"])
    step_sec = DAY_SEC if ds["timeframe"] == "1d" else H4_SEC
    slice_sigs = [s for s in signals if t0 <= int(s["time"]) <= t1]
    slice_funding = [f for f in ds["funding_settlements"] if t0 <= int(f["time"]) <= (t1 + step_sec)]

    bt = WideATRBacktester(
        candles,
        slice_sigs,
        funding_rates=slice_funding,
        atr_warmup_candles=ds["price_with_warmup"],
        slippage_bps=slippage_bps,
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
    m = res["metrics"]
    days = max((t1 - t0) / float(DAY_SEC), 1.0)
    return {
        "symbol": ds["symbol"],
        "timeframe": ds["timeframe"],
        "slippage_bps": float(slippage_bps),
        "days": round(days, 2),
        "trades": int(m["trades"]),
        "win_rate": float(m["win_rate"]),
        "profit_factor": float(m["profit_factor"]),
        "expectancy_pct": float(m["expectancy_pct"]),
        "total_return_pct": float(m["total_return_pct"]),
        "max_drawdown_pct": float(m["max_drawdown_pct"]),
        "mar_ratio": float(m["mar_ratio"]),
        "sharpe": float(m["sharpe"]),
        "total_fees_paid": float(res["total_fees_paid"]),
        "total_funding_pnl": float(res["total_funding_pnl"]),
        "final_balance": float(res["final_balance"]),
        "_trade_stats": {
            "trades": int(m["trades"]),
            "wins_count": int(m["wins_count"]),
            "gross_profit": float(m["gross_profit"]),
            "gross_loss": float(m["gross_loss"]),
            "trade_rets": list(m["trade_rets"]),
        },
    }


# ---------------------------------------------------------------------------
# Offline Synthetic Dataset Generator (Exercises all causal paths)
# ---------------------------------------------------------------------------

def make_synthetic_datasets(
    symbols: Sequence[str] = SYMBOLS,
    seed: int = 2026,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """
    Generate realistic multi-wave synthetic Dataset L (1d) and Dataset M (1d+4h)
    simulating OKX 16:00 UTC 1d candles, Binance 00:00 UTC 1d derivatives,
    partial historical FundingRate in dual formats, and 4h native+1d fallback derivatives.
    """
    rng = np.random.default_rng(seed)
    datasets_l: Dict[str, Dict[str, Any]] = {}
    datasets_m: Dict[str, Dict[str, Any]] = {}

    # Anchor OKX 1d open at 16:00 UTC (~750 days back from 2026-11-25 16:00 UTC)
    end_1d_open = int(datetime(2026, 11, 25, 16, 0, tzinfo=timezone.utc).timestamp())
    n_1d = 750
    start_1d_open = end_1d_open - (n_1d - 1) * DAY_SEC

    # First generate 4h base series over the last 400 days (2400 4h bars)
    n_4h = 2400
    start_4h_open = end_1d_open - (n_4h // 6 - 1) * DAY_SEC

    # Store BTC base wave to give realistic macro correlation + cross-asset waves
    for sym_idx, sym in enumerate(symbols):
        coin = sym.split("/")[0].upper()
        base_px = {"BTC": 50000.0, "ETH": 2500.0, "SOL": 120.0, "HYPE": 18.0, "CC": 0.25}.get(coin, 100.0)
        vol_scale = 0.024 if coin == "BTC" else (0.032 if coin in ("ETH", "SOL") else 0.042)

        # Build 4500 4h bars covering full 750d so 1d OHLCV and 4h OHLCV are strictly consistent!
        total_4h = n_1d * 6
        px_4h_all: List[Dict[str, Any]] = []
        p = base_px
        phase = sym_idx * 0.35
        for k in range(total_4h):
            t_open = start_1d_open + k * H4_SEC
            day_pos = k / 6.0
            # Multi-month macro bull/bear regime wave (~110d cycle + 45d sub-cycle)
            macro_drift = 0.0018 * math.sin(2.0 * math.pi * day_pos / 110.0 + phase) + 0.0008 * math.cos(2.0 * math.pi * day_pos / 45.0)
            shock = float(rng.normal(macro_drift, vol_scale / math.sqrt(6.0)))
            o = p
            c = max(base_px * 0.15, o * (1.0 + shock))
            wu = abs(float(rng.normal(0.0, vol_scale / 4.5)))
            wd = abs(float(rng.normal(0.0, vol_scale / 4.5)))
            h = max(o, c) * (1.0 + wu)
            l = min(o, c) * max(0.5, 1.0 - wd)
            px_4h_all.append({
                "time": t_open,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": float(1e6 * (1.0 + 30.0 * abs(shock))),
            })
            p = c

        # Aggregate exact 1d OKX candles (16:00 UTC open) from 6 consecutive 4h bars
        ohlcv_1d: List[Dict[str, Any]] = []
        for d in range(n_1d):
            chunk = px_4h_all[d * 6 : (d + 1) * 6]
            ohlcv_1d.append({
                "time": chunk[0]["time"],
                "open": chunk[0]["open"],
                "high": max(x["high"] for x in chunk),
                "low": min(x["low"] for x in chunk),
                "close": chunk[-1]["close"],
                "volume": sum(x["volume"] for x in chunk),
            })

        # Derivatives start after 200d warmup (so 550d of 1d derivatives), with Binance 00:00 UTC offset!
        deriv_start_d = 200
        okx_1d_derivs: List[Dict[str, Any]] = []
        bin_1d_derivs: List[Dict[str, Any]] = []
        for d in range(deriv_start_d, n_1d):
            bar = ohlcv_1d[d]
            t_okx = bar["time"]  # 16:00 UTC
            # Binance daily open at 00:00 UTC of that UTC day (= t_okx - 57600) or next day;
            # t_okx - 57600 closes at t_okx + 28800 (known BEFORE t_okx + 86400!).
            t_bin = t_okx - 57600
            prev_c = ohlcv_1d[d - 1]["close"]
            ret1d = (bar["close"] - prev_c) / prev_c
            ret5d = (bar["close"] - ohlcv_1d[max(0, d - 5)]["close"]) / ohlcv_1d[max(0, d - 5)]["close"]

            # Realistic anti-correlated positioning + OI expansion on rallies / washout on crashes
            wave = math.sin(2.0 * math.pi * d / 110.0 + phase)
            coin_oi_level = 1e6 * (1.0 + 0.25 * wave - 0.12 * min(0.0, ret5d * 5.0) + float(rng.normal(0.0, 0.03)))
            oi_usd_okx = max(1e5, coin_oi_level * bar["close"] * 0.4)
            oi_usd_bin = max(1e5, coin_oi_level * bar["close"] * 0.6)

            lsur_val = max(0.35, 1.2 + 0.45 * wave + float(rng.normal(0.0, 0.12)))
            # Taker ratio: net buying on turns & rallies, slightly contrarian absorption near bottoms
            tr_val = min(0.75, max(0.25, 0.50 + 0.18 * math.tanh(ret1d * 18.0) - 0.03 * wave + float(rng.normal(0.0, 0.03))))
            tot_vol = 2e6
            okx_1d_derivs.append({
                "time": t_okx,
                "open_interest": oi_usd_okx,
                "long_short_ratio": lsur_val * 0.95,
                "taker_buy_vol": tot_vol * tr_val * 0.4,
                "taker_sell_vol": tot_vol * (1.0 - tr_val) * 0.4,
            })
            # Binance OI/LSUR starts later (last 270 days, matching live DB asymmetry!)
            bin_1d_derivs.append({
                "time": t_bin,
                "open_interest": oi_usd_bin if d >= (n_1d - 270) else None,
                "long_short_ratio": lsur_val if d >= (n_1d - 270) else None,
                "taker_buy_vol": tot_vol * tr_val,
                "taker_sell_vol": tot_vol * (1.0 - tr_val),
            })

        # Dual-format FundingRate only in later half (days 400..750), simulating 2025-12..2026-11 DB coverage
        funding_raw: List[Dict[str, Any]] = []
        for d in range(400, n_1d):
            wave = math.sin(2.0 * math.pi * d / 110.0 + phase)
            base_fr = 0.0001 + 0.00035 * wave + float(rng.normal(0.0, 0.00008))
            t_day = ohlcv_1d[d]["time"]
            for h_off in (0, 28800, 57600):
                ft = t_day + h_off
                if d < 520:
                    funding_raw.append({"time": ft, "symbol": f"{coin}/USDT:USDT", "funding_rate": base_fr})
                elif d < 560:
                    # Overlap period containing both symbol formats!
                    funding_raw.append({"time": ft, "symbol": f"{coin}/USDT:USDT", "funding_rate": base_fr * 0.99})
                    funding_raw.append({"time": ft, "symbol": f"{coin}-USDT-SWAP", "funding_rate": base_fr})
                else:
                    funding_raw.append({"time": ft, "symbol": f"{coin}-USDT-SWAP", "funding_rate": base_fr})

        funding_dedup = deduplicate_funding_records(funding_raw, coin=coin)
        deriv_1d_by_exch = {"okx": okx_1d_derivs, "binance": bin_1d_derivs}

        ds_l = build_dataset_l_from_raw(sym, ohlcv_1d, deriv_1d_by_exch, funding_dedup)
        datasets_l[sym] = ds_l

        # 4h slice for Dataset M (last 400 days) + native 1h derivatives on recent 200 days ONLY
        ohlcv_4h = [b for b in px_4h_all if b["time"] >= start_4h_open]
        native_start_4h = ohlcv_4h[-1200]["time"]  # recent 200d (1200 4h bars)
        deriv_sub_rows: List[Dict[str, Any]] = []
        for b in ohlcv_4h:
            if b["time"] < native_start_4h:
                continue
            day_pos = (b["time"] - start_1d_open) / float(DAY_SEC)
            wave = math.sin(2.0 * math.pi * day_pos / 110.0 + phase)
            ret_b = (b["close"] - b["open"]) / b["open"]
            tr_4h = min(0.8, max(0.2, 0.50 + 0.22 * math.tanh(ret_b * 20.0) + float(rng.normal(0.0, 0.04))))
            oi_base = 1e6 * (1.0 + 0.25 * wave + float(rng.normal(0.0, 0.02))) * b["close"]
            ls_val = max(0.35, 1.2 + 0.45 * wave + float(rng.normal(0.0, 0.1)))
            for h_sub in range(4):
                t_1h = b["time"] + h_sub * H1_SEC
                deriv_sub_rows.append({
                    "time": t_1h,
                    "exchange": "okx",
                    "timeframe": "1h",
                    "open_interest": oi_base * 0.4,
                    "long_short_ratio": ls_val * 0.95,
                    "taker_buy_vol": None,
                    "taker_sell_vol": None,
                })
                deriv_sub_rows.append({
                    "time": t_1h,
                    "exchange": "binance",
                    "timeframe": "1h",
                    "open_interest": oi_base * 0.6,
                    "long_short_ratio": ls_val,
                    "taker_buy_vol": 5e5 * tr_4h,
                    "taker_sell_vol": 5e5 * (1.0 - tr_4h),
                })

        datasets_m[sym] = build_dataset_m_from_raw(
            sym, ohlcv_4h, ds_l, deriv_sub_rows, deriv_1d_by_exch, funding_dedup
        )

    return datasets_l, datasets_m


# ---------------------------------------------------------------------------
# Full Experiment Orchestration (Sections 0..4)
# ---------------------------------------------------------------------------

def _pool_inflection_row(
    timeframe: str,
    variant: str,
    per_coin_rows: Sequence[Dict[str, Any]],
    outcomes_pooled: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    total_days = sum(r["clean_days"] for r in per_coin_rows)
    total_sigs = sum(r["signals"] for r in per_coin_rows)
    # Pooled annualized rate weighted across asset-years
    asset_years = sum(r["clean_days"] / 365.0 for r in per_coin_rows)
    res = summarize_inflection_metrics(
        symbol="POOLED",
        timeframe=timeframe,
        variant=variant,
        clean_days=asset_years * 365.0,
        total_signals=total_sigs,
        outcomes=outcomes_pooled,
    )
    res["total_asset_days"] = round(total_days, 2)
    return res


def _build_bootstrap_comparisons(
    pooled_outcomes: Dict[str, List[Dict[str, Any]]],
    per_coin_outcomes: Dict[Tuple[str, str], List[Dict[str, Any]]],
    symbols: Sequence[str],
) -> List[Dict[str, Any]]:
    pairs = [
        ("1d", "Macro_PD_1d", "Macro_P_1d"),
        ("1d", "Macro_PD_1d", "Macro_LeftOnly_1d"),
        ("1d", "Macro_PD_1d", "Legacy_v8_1d"),
        ("4h", "Macro_PD_1d_4h", "Legacy_v8_4h"),
    ]
    rows: List[Dict[str, Any]] = []
    for tf, var_a, var_b in pairs:
        # Pooled comparison
        out_a = pooled_outcomes.get(var_a, [])
        out_b = pooled_outcomes.get(var_b, [])
        r14_a = [o["ret_14d"] for o in out_a if o["ret_14d"] is not None]
        r14_b = [o["ret_14d"] for o in out_b if o["ret_14d"] is not None]
        r30_a = [o["ret_30d"] for o in out_a if o["ret_30d"] is not None]
        r30_b = [o["ret_30d"] for o in out_b if o["ret_30d"] is not None]
        mfe14_a = [o["mfe_14d"] for o in out_a if o["mfe_14d"] is not None]
        mae14_a = [o["mae_14d"] for o in out_a if o["mae_14d"] is not None]
        mfe14_b = [o["mfe_14d"] for o in out_b if o["mfe_14d"] is not None]
        mae14_b = [o["mae_14d"] for o in out_b if o["mae_14d"] is not None]
        mfe30_a = [o["mfe_30d"] for o in out_a if o["mfe_30d"] is not None]
        mae30_a = [o["mae_30d"] for o in out_a if o["mae_30d"] is not None]
        mfe30_b = [o["mfe_30d"] for o in out_b if o["mfe_30d"] is not None]
        mae30_b = [o["mae_30d"] for o in out_b if o["mae_30d"] is not None]

        er14_a = (float(np.median(mfe14_a)) / max(float(np.median(mae14_a)), 1e-4)) if mfe14_a else 0.0
        er14_b = (float(np.median(mfe14_b)) / max(float(np.median(mae14_b)), 1e-4)) if mfe14_b else 0.0
        er30_a = (float(np.median(mfe30_a)) / max(float(np.median(mae30_a)), 1e-4)) if mfe30_a else 0.0
        er30_b = (float(np.median(mfe30_b)) / max(float(np.median(mae30_b)), 1e-4)) if mfe30_b else 0.0

        rows.append({
            "scope": "POOLED",
            "timeframe": tf,
            "variant_a": var_a,
            "variant_b": var_b,
            "n_a_14d": len(r14_a),
            "n_b_14d": len(r14_b),
            "ret_14d_a": round(float(np.mean(r14_a)), 3) if r14_a else 0.0,
            "ret_14d_b": round(float(np.mean(r14_b)), 3) if r14_b else 0.0,
            "p_ret_14d": bootstrap_diff_pvalue(r14_a, r14_b),
            "ret_30d_a": round(float(np.mean(r30_a)), 3) if r30_a else 0.0,
            "ret_30d_b": round(float(np.mean(r30_b)), 3) if r30_b else 0.0,
            "p_ret_30d": bootstrap_diff_pvalue(r30_a, r30_b),
            "er_14d_a": round(er14_a, 2),
            "er_14d_b": round(er14_b, 2),
            "p_er_14d": bootstrap_eratio_diff_pvalue(mfe14_a, mae14_a, mfe14_b, mae14_b),
            "er_30d_a": round(er30_a, 2),
            "er_30d_b": round(er30_b, 2),
            "p_er_30d": bootstrap_eratio_diff_pvalue(mfe30_a, mae30_a, mfe30_b, mae30_b),
        })

        # Per-coin comparison
        for sym in symbols:
            ca = per_coin_outcomes.get((sym, var_a), [])
            cb = per_coin_outcomes.get((sym, var_b), [])
            cr14_a = [o["ret_14d"] for o in ca if o["ret_14d"] is not None]
            cr14_b = [o["ret_14d"] for o in cb if o["ret_14d"] is not None]
            cr30_a = [o["ret_30d"] for o in ca if o["ret_30d"] is not None]
            cr30_b = [o["ret_30d"] for o in cb if o["ret_30d"] is not None]
            cmfe14_a = [o["mfe_14d"] for o in ca if o["mfe_14d"] is not None]
            cmae14_a = [o["mae_14d"] for o in ca if o["mae_14d"] is not None]
            cmfe14_b = [o["mfe_14d"] for o in cb if o["mfe_14d"] is not None]
            cmae14_b = [o["mae_14d"] for o in cb if o["mae_14d"] is not None]
            cmfe30_a = [o["mfe_30d"] for o in ca if o["mfe_30d"] is not None]
            cmae30_a = [o["mae_30d"] for o in ca if o["mae_30d"] is not None]
            cmfe30_b = [o["mfe_30d"] for o in cb if o["mfe_30d"] is not None]
            cmae30_b = [o["mae_30d"] for o in cb if o["mae_30d"] is not None]

            cer14_a = (float(np.median(cmfe14_a)) / max(float(np.median(cmae14_a)), 1e-4)) if cmfe14_a else 0.0
            cer14_b = (float(np.median(cmfe14_b)) / max(float(np.median(cmae14_b)), 1e-4)) if cmfe14_b else 0.0
            cer30_a = (float(np.median(cmfe30_a)) / max(float(np.median(cmae30_a)), 1e-4)) if cmfe30_a else 0.0
            cer30_b = (float(np.median(cmfe30_b)) / max(float(np.median(cmae30_b)), 1e-4)) if cmfe30_b else 0.0

            rows.append({
                "scope": sym,
                "timeframe": tf,
                "variant_a": var_a,
                "variant_b": var_b,
                "n_a_14d": len(cr14_a),
                "n_b_14d": len(cr14_b),
                "ret_14d_a": round(float(np.mean(cr14_a)), 3) if cr14_a else 0.0,
                "ret_14d_b": round(float(np.mean(cr14_b)), 3) if cr14_b else 0.0,
                "p_ret_14d": bootstrap_diff_pvalue(cr14_a, cr14_b),
                "ret_30d_a": round(float(np.mean(cr30_a)), 3) if cr30_a else 0.0,
                "ret_30d_b": round(float(np.mean(cr30_b)), 3) if cr30_b else 0.0,
                "p_ret_30d": bootstrap_diff_pvalue(cr30_a, cr30_b),
                "er_14d_a": round(cer14_a, 2),
                "er_14d_b": round(cer14_b, 2),
                "p_er_14d": bootstrap_eratio_diff_pvalue(cmfe14_a, cmae14_a, cmfe14_b, cmae14_b),
                "er_30d_a": round(cer30_a, 2),
                "er_30d_b": round(cer30_b, 2),
                "p_er_30d": bootstrap_eratio_diff_pvalue(cmfe30_a, cmae30_a, cmfe30_b, cmae30_b),
            })
    return rows


def _pool_trade_stats(stats_list: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    tot_trades = sum(int(s.get("trades", 0)) for s in stats_list)
    tot_wins = sum(int(s.get("wins_count", 0)) for s in stats_list)
    tot_gp = sum(float(s.get("gross_profit", 0.0)) for s in stats_list)
    tot_gl = sum(float(s.get("gross_loss", 0.0)) for s in stats_list)
    all_rets: List[float] = []
    for s in stats_list:
        all_rets.extend(s.get("trade_rets", []))

    pooled_wr = (tot_wins / tot_trades * 100.0) if tot_trades > 0 else 0.0
    if tot_gl > 0.0:
        pooled_pf = min(tot_gp / tot_gl, 999.9)
    else:
        pooled_pf = 999.9 if tot_gp > 0.0 else 0.0
    pooled_exp = float(np.mean(all_rets)) if all_rets else 0.0
    return {
        "total_trades": tot_trades,
        "pooled_wr": round(float(pooled_wr), 1),
        "pooled_pf": round(float(pooled_pf), 2),
        "pooled_exp": round(float(pooled_exp), 3),
    }


def _evaluate_falsification_verdict(
    section1_pooled: Sequence[Dict[str, Any]],
    bootstrap_rows: Sequence[Dict[str, Any]],
    section2_pooled: Sequence[Dict[str, Any]],
    section3_rows: Sequence[Dict[str, Any]],
    section3_pooled: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Automated objective Falsification Verdict (alpha = 0.10 & OOS checks)."""
    s1_map = {r["variant"]: r for r in section1_pooled}
    boot_pooled = {(r["variant_a"], r["variant_b"]): r for r in bootstrap_rows if r["scope"] == "POOLED"}
    s2_map = {(r["variant"], r["slippage_bps"]): r for r in section2_pooled}
    s3_map = {r["variant"]: r for r in section3_pooled}

    checks: List[Dict[str, Any]] = []

    def add_check(name: str, passed: Optional[bool], detail: str) -> None:
        status = "PASS" if passed is True else ("FAIL" if passed is False else "INSUFFICIENT_N")
        checks.append({"check": name, "status": status, "passed": passed, "detail": detail})

    # H1: Derivatives value-add (Macro_PD_1d vs Macro_P_1d)
    b_pd_p = boot_pooled.get(("Macro_PD_1d", "Macro_P_1d"), {})
    s3_pd = s3_map.get("Macro_PD_1d", {})
    s3_p = s3_map.get("Macro_P_1d", {})
    if b_pd_p.get("n_a_14d", 0) < 5 or b_pd_p.get("n_b_14d", 0) < 5:
        add_check(
            "H1_Derivatives_ValueAdd_1d",
            None,
            f"Sparse sample (N_PD={b_pd_p.get('n_a_14d', 0)}, N_P={b_pd_p.get('n_b_14d', 0)} < 5)",
        )
    else:
        stat_ok = (
            (b_pd_p["ret_14d_a"] > b_pd_p["ret_14d_b"] and b_pd_p["p_ret_14d"] <= 0.10)
            or (b_pd_p["er_14d_a"] > b_pd_p["er_14d_b"] and b_pd_p["p_er_14d"] <= 0.10)
            or (b_pd_p["ret_30d_a"] > b_pd_p["ret_30d_b"] and b_pd_p["p_ret_30d"] <= 0.10)
            or (b_pd_p["er_30d_a"] > b_pd_p["er_30d_b"] and b_pd_p["p_er_30d"] <= 0.10)
        )
        oos_better = (
            s3_pd.get("oos_total_trades", 0) > 0
            and s3_pd.get("oos_pooled_exp", -999.0) > s3_p.get("oos_pooled_exp", -999.0)
        )
        add_check(
            "H1_Derivatives_ValueAdd_1d",
            bool(stat_ok and oos_better),
            (
                f"Ret14 {b_pd_p['ret_14d_a']:+.3f}% vs {b_pd_p['ret_14d_b']:+.3f}% (p={b_pd_p['p_ret_14d']:.4f}), "
                f"ER14 {b_pd_p['er_14d_a']:.2f} vs {b_pd_p['er_14d_b']:.2f} (p={b_pd_p['p_er_14d']:.4f}), "
                f"OOS PooledExp {s3_pd.get('oos_pooled_exp', 0.0):+.3f}% vs {s3_p.get('oos_pooled_exp', 0.0):+.3f}%"
            ),
        )

    # H2: Layer 2 Right-Side BOS value-add (Macro_PD_1d vs Macro_LeftOnly_1d)
    b_pd_l = boot_pooled.get(("Macro_PD_1d", "Macro_LeftOnly_1d"), {})
    s3_left = s3_map.get("Macro_LeftOnly_1d", {})
    if b_pd_l.get("n_a_14d", 0) < 5 or b_pd_l.get("n_b_14d", 0) < 5:
        add_check(
            "H2_RightSide_BOS_ValueAdd_1d",
            None,
            f"Sparse sample (N_PD={b_pd_l.get('n_a_14d', 0)}, N_Left={b_pd_l.get('n_b_14d', 0)} < 5)",
        )
    else:
        stat_ok = (
            (b_pd_l["ret_14d_a"] > b_pd_l["ret_14d_b"] and b_pd_l["p_ret_14d"] <= 0.10)
            or (b_pd_l["er_14d_a"] > b_pd_l["er_14d_b"] and b_pd_l["p_er_14d"] <= 0.10)
            or (b_pd_l["ret_30d_a"] > b_pd_l["ret_30d_b"] and b_pd_l["p_ret_30d"] <= 0.10)
            or (b_pd_l["er_30d_a"] > b_pd_l["er_30d_b"] and b_pd_l["p_er_30d"] <= 0.10)
        )
        oos_better = (
            s3_pd.get("oos_total_trades", 0) > 0
            and s3_pd.get("oos_pooled_exp", -999.0) > s3_left.get("oos_pooled_exp", -999.0)
        )
        add_check(
            "H2_RightSide_BOS_ValueAdd_1d",
            bool(stat_ok and oos_better),
            (
                f"Ret14 {b_pd_l['ret_14d_a']:+.3f}% vs {b_pd_l['ret_14d_b']:+.3f}% (p={b_pd_l['p_ret_14d']:.4f}), "
                f"ER14 {b_pd_l['er_14d_a']:.2f} vs {b_pd_l['er_14d_b']:.2f} (p={b_pd_l['p_er_14d']:.4f}), "
                f"OOS PooledExp {s3_pd.get('oos_pooled_exp', 0.0):+.3f}% vs {s3_left.get('oos_pooled_exp', 0.0):+.3f}%"
            ),
        )

    # H3a: Macro_PD_1d vs Legacy_v8_1d
    b_pd_leg1d = boot_pooled.get(("Macro_PD_1d", "Legacy_v8_1d"), {})
    s3_leg1d = s3_map.get("Legacy_v8_1d", {})
    if b_pd_leg1d.get("n_a_14d", 0) < 5 or b_pd_leg1d.get("n_b_14d", 0) < 5:
        add_check(
            "H3a_MacroPD_1d_vs_Legacy_1d",
            None,
            f"Sparse sample (N_Macro={b_pd_leg1d.get('n_a_14d', 0)}, N_Legacy={b_pd_leg1d.get('n_b_14d', 0)} < 5)",
        )
    else:
        stat_ok = (
            (b_pd_leg1d["ret_14d_a"] > b_pd_leg1d["ret_14d_b"] and b_pd_leg1d["p_ret_14d"] <= 0.10)
            or (b_pd_leg1d["er_14d_a"] > b_pd_leg1d["er_14d_b"] and b_pd_leg1d["p_er_14d"] <= 0.10)
            or (b_pd_leg1d["ret_30d_a"] > b_pd_leg1d["ret_30d_b"] and b_pd_leg1d["p_ret_30d"] <= 0.10)
            or (b_pd_leg1d["er_30d_a"] > b_pd_leg1d["er_30d_b"] and b_pd_leg1d["p_er_30d"] <= 0.10)
        )
        oos_better = (
            s3_pd.get("oos_total_trades", 0) > 0
            and s3_pd.get("oos_pooled_exp", -999.0) > s3_leg1d.get("oos_pooled_exp", -999.0)
        )
        add_check(
            "H3a_MacroPD_1d_vs_Legacy_1d",
            bool(stat_ok and oos_better),
            (
                f"Ret14 {b_pd_leg1d['ret_14d_a']:+.3f}% vs {b_pd_leg1d['ret_14d_b']:+.3f}% (p={b_pd_leg1d['p_ret_14d']:.4f}), "
                f"ER30 {b_pd_leg1d['er_30d_a']:.2f} vs {b_pd_leg1d['er_30d_b']:.2f} (p={b_pd_leg1d['p_er_30d']:.4f}), "
                f"OOS PooledExp {s3_pd.get('oos_pooled_exp', 0.0):+.3f}% vs {s3_leg1d.get('oos_pooled_exp', 0.0):+.3f}%"
            ),
        )

    # H3b: Macro_PD_1d_4h vs Legacy_v8_4h
    b_4h_leg = boot_pooled.get(("Macro_PD_1d_4h", "Legacy_v8_4h"), {})
    s3_4h = s3_map.get("Macro_PD_1d_4h", {})
    s3_leg4h = s3_map.get("Legacy_v8_4h", {})
    if b_4h_leg.get("n_a_14d", 0) < 5 or b_4h_leg.get("n_b_14d", 0) < 5:
        add_check(
            "H3b_MacroPD_4h_vs_Legacy_4h",
            None,
            f"Sparse sample (N_Macro={b_4h_leg.get('n_a_14d', 0)}, N_Legacy={b_4h_leg.get('n_b_14d', 0)} < 5)",
        )
    else:
        stat_ok = (
            (b_4h_leg["ret_14d_a"] > b_4h_leg["ret_14d_b"] and b_4h_leg["p_ret_14d"] <= 0.10)
            or (b_4h_leg["er_14d_a"] > b_4h_leg["er_14d_b"] and b_4h_leg["p_er_14d"] <= 0.10)
            or (b_4h_leg["ret_30d_a"] > b_4h_leg["ret_30d_b"] and b_4h_leg["p_ret_30d"] <= 0.10)
            or (b_4h_leg["er_30d_a"] > b_4h_leg["er_30d_b"] and b_4h_leg["p_er_30d"] <= 0.10)
        )
        oos_better = (
            s3_4h.get("oos_total_trades", 0) > 0
            and s3_4h.get("oos_pooled_exp", -999.0) > s3_leg4h.get("oos_pooled_exp", -999.0)
        )
        add_check(
            "H3b_MacroPD_4h_vs_Legacy_4h",
            bool(stat_ok and oos_better),
            (
                f"Ret14 {b_4h_leg['ret_14d_a']:+.3f}% vs {b_4h_leg['ret_14d_b']:+.3f}% (p={b_4h_leg['p_ret_14d']:.4f}), "
                f"ER30 {b_4h_leg['er_30d_a']:.2f} vs {b_4h_leg['er_30d_b']:.2f} (p={b_4h_leg['p_er_30d']:.4f}), "
                f"OOS PooledExp {s3_4h.get('oos_pooled_exp', 0.0):+.3f}% vs {s3_leg4h.get('oos_pooled_exp', 0.0):+.3f}%"
            ),
        )

    # H4: Blind OOS viability & friction survival (5 bps & 15 bps)
    for var in ("Macro_PD_1d", "Macro_PD_1d_4h"):
        s3_v = s3_map.get(var, {})
        s1_v = s1_map.get(var, {})
        bt_5 = s2_map.get((var, 5.0), {})
        bt_15 = s2_map.get((var, 15.0), {})
        coin_oos = [r for r in section3_rows if r["variant"] == var]
        pos_exp_coins = sum(1 for r in coin_oos if r["oos_trades"] > 0 and r["oos_exp"] > 0.0)
        oos_trades_tot = int(s3_v.get("oos_total_trades", 0))
        if oos_trades_tot < 5:
            add_check(
                f"H4_OOS_Viability_{var}",
                None,
                f"Insufficient OOS trades ({oos_trades_tot} < 5)",
            )
        else:
            viable = (
                s3_v.get("oos_pooled_exp", 0.0) > 0.0
                and s3_v.get("oos_pooled_pf", 0.0) > 1.0
                and s3_v.get("oos_pooled_er_14d", 0.0) > 1.0
                and bt_15.get("pooled_exp", 0.0) > 0.0
                and bt_15.get("pooled_pf", 0.0) > 1.0
            )
            add_check(
                f"H4_OOS_Viability_{var}",
                bool(viable),
                (
                    f"OOS_Trades={oos_trades_tot} | OOS_PooledExp={s3_v.get('oos_pooled_exp', 0.0):+.3f}% | "
                    f"OOS_PooledPF={s3_v.get('oos_pooled_pf', 0.0):.2f} | OOS_ER14={s3_v.get('oos_pooled_er_14d', 0.0):.2f} | "
                    f"PosOOS_Coins={pos_exp_coins}/{len(coin_oos)} | "
                    f"Full5bps_PooledExp={bt_5.get('pooled_exp', 0.0):+.3f}% | "
                    f"Full15bps_PooledExp={bt_15.get('pooled_exp', 0.0):+.3f}% (PF={bt_15.get('pooled_pf', 0.0):.2f}) | "
                    f"MWC={s1_v.get('major_wave_capture_pct', 0.0):.1f}%"
                ),
            )

    passed_n = sum(1 for c in checks if c["passed"] is True)
    failed_n = sum(1 for c in checks if c["passed"] is False)
    insuff_n = sum(1 for c in checks if c["passed"] is None)

    h4_ok = any(c["check"].startswith("H4_OOS_Viability_") and c["passed"] is True for c in checks)
    h3_ok = any(c["check"].startswith("H3") and c["passed"] is True for c in checks)
    if h4_ok and h3_ok and failed_n == 0 and insuff_n == 0:
        verdict = "PROMOTE / VALIDATED"
    elif h4_ok or passed_n >= 1:
        verdict = "PARTIAL / INCONCLUSIVE (SEE COMPONENT CHECKS)"
    elif insuff_n == len(checks):
        verdict = "INSUFFICIENT_DATA"
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


def run_all_macro_experiments(
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
        print("Running Macro Inflection Experiments in OFFLINE SYNTHETIC mode...")
        datasets_l, datasets_m = make_synthetic_datasets(SYMBOLS)
    else:
        print("Probing PostgreSQL for Dataset L (1d) and Dataset M (1d+4h)...")
        datasets_l, datasets_m = load_datasets_from_db(SYMBOLS, session_factory=session_factory)

    # --- Section 0: Clean Inventory ---
    inventory: List[Dict[str, Any]] = []
    for ds_map, ds_label in ((datasets_l, "Dataset L (1d)"), (datasets_m, "Dataset M (1d+4h)")):
        for sym in SYMBOLS:
            ds = ds_map.get(sym, {})
            valid = bool(ds.get("valid"))
            row: Dict[str, Any] = {
                "dataset": ds_label,
                "symbol": sym,
                "timeframe": ds.get("timeframe", "1d" if "L" in ds_label else "4h"),
                "valid": valid,
                "clean_start_utc": _fmt_utc(ds.get("clean_start")) if valid else "N/A",
                "eval_start_utc": _fmt_utc(ds.get("eval_start")) if valid else "N/A",
                "clean_end_utc": _fmt_utc(ds.get("clean_end")) if valid else "N/A",
                "clean_days": ds.get("clean_days", 0.0) if valid else 0.0,
                "eval_bars": ds.get("clean_bars", 0) if valid else 0,
                "warmup_bars": ds.get("warmup_bars", 0) if valid else 0,
                "funding_count": ds.get("funding_count", 0) if valid else 0,
                "reason": ds.get("reason", "") if not valid else "",
            }
            if ds_label.startswith("Dataset L"):
                row["coin_oi_bars"] = ds.get("coin_oi_eval_bars", 0) if valid else 0
                row["taker_bars"] = ds.get("taker_eval_bars", 0) if valid else 0
                row["lsur_bars"] = ds.get("lsur_eval_bars", 0) if valid else 0
                row["funding_daily_bars"] = ds.get("funding_eval_bars", 0) if valid else 0
            else:
                row["native_oi_bars"] = ds.get("native_oi_eval_bars", 0) if valid else 0
                row["fallback_oi_bars"] = ds.get("fallback_oi_eval_bars", 0) if valid else 0
                row["native_taker_bars"] = ds.get("native_taker_eval_bars", 0) if valid else 0
                row["fallback_taker_bars"] = ds.get("fallback_taker_eval_bars", 0) if valid else 0
            inventory.append(row)

    # --- Generate Signals for all 6 variant instances (5 models; Legacy evaluated on both 1d & 4h) ---
    btc_ds_l = datasets_l.get("BTC/USDT")
    btc_ds_m = datasets_m.get("BTC/USDT")

    signals_map: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    layer1_map: Dict[str, pd.DataFrame] = {}

    for sym in SYMBOLS:
        ds_l = datasets_l.get(sym)
        if ds_l and ds_l.get("valid"):
            signals_map[(sym, "Legacy_v8_1d")] = run_legacy_v8_signals(ds_l, btc_ds_l)
            sigs_left, l1_df = compute_1d_macro_signals(ds_l, "Macro_LeftOnly_1d")
            sigs_p, _ = compute_1d_macro_signals(ds_l, "Macro_P_1d")
            sigs_pd, l1_pd = compute_1d_macro_signals(ds_l, "Macro_PD_1d")
            signals_map[(sym, "Macro_LeftOnly_1d")] = sigs_left
            signals_map[(sym, "Macro_P_1d")] = sigs_p
            signals_map[(sym, "Macro_PD_1d")] = sigs_pd
            layer1_map[sym] = l1_pd

        ds_m = datasets_m.get(sym)
        if ds_m and ds_m.get("valid") and sym in layer1_map:
            signals_map[(sym, "Legacy_v8_4h")] = run_legacy_v8_signals(ds_m, btc_ds_m)
            signals_map[(sym, "Macro_PD_1d_4h")] = compute_4h_macro_signals(ds_m, layer1_map[sym])

    variants_1d = ["Legacy_v8_1d", "Macro_LeftOnly_1d", "Macro_P_1d", "Macro_PD_1d"]
    variants_4h = ["Legacy_v8_4h", "Macro_PD_1d_4h"]
    all_variants = variants_1d + variants_4h

    # --- Section 1: Multi-Horizon Inflection Quality (+5d, +14d, +30d) ---
    section1_rows: List[Dict[str, Any]] = []
    section1_pooled: List[Dict[str, Any]] = []
    per_coin_outcomes: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    pooled_outcomes: Dict[str, List[Dict[str, Any]]] = {v: [] for v in all_variants}

    for var in all_variants:
        tf = "1d" if var in variants_1d else "4h"
        ds_map = datasets_l if tf == "1d" else datasets_m
        step_sec = DAY_SEC if tf == "1d" else H4_SEC
        var_coin_rows: List[Dict[str, Any]] = []

        for sym in SYMBOLS:
            ds = ds_map.get(sym)
            if not ds or not ds.get("valid"):
                continue
            sigs = signals_map.get((sym, var), [])
            outs = compute_multi_horizon_outcomes(ds["eval_price"], sigs, step_sec=step_sec)
            per_coin_outcomes[(sym, var)] = outs
            pooled_outcomes[var].extend(outs)
            row = summarize_inflection_metrics(
                symbol=sym,
                timeframe=tf,
                variant=var,
                clean_days=float(ds["clean_days"]),
                total_signals=len(sigs),
                outcomes=outs,
            )
            section1_rows.append(row)
            var_coin_rows.append(row)

        if var_coin_rows:
            section1_pooled.append(_pool_inflection_row(tf, var, var_coin_rows, pooled_outcomes[var]))

    bootstrap_rows = _build_bootstrap_comparisons(pooled_outcomes, per_coin_outcomes, SYMBOLS)

    # --- Section 2: Wide-ATR Macro Swing Backtest (5 bps & 15 bps) ---
    section2_rows: List[Dict[str, Any]] = []
    section2_pooled: List[Dict[str, Any]] = []

    for var in all_variants:
        tf = "1d" if var in variants_1d else "4h"
        ds_map = datasets_l if tf == "1d" else datasets_m
        for bps in (5.0, 15.0):
            coin_bt_rows: List[Dict[str, Any]] = []
            coin_bt_stats: List[Dict[str, Any]] = []
            for sym in SYMBOLS:
                ds = ds_map.get(sym)
                if not ds or not ds.get("valid"):
                    continue
                sigs = signals_map.get((sym, var), [])
                res_bt = run_wide_atr_backtest_slice(ds, sigs, slippage_bps=bps)
                if res_bt:
                    coin_bt_stats.append(res_bt.pop("_trade_stats"))
                    res_bt["variant"] = var
                    section2_rows.append(res_bt)
                    coin_bt_rows.append(res_bt)
            if coin_bt_rows:
                pooled_t = _pool_trade_stats(coin_bt_stats)
                active_rows = [r for r in coin_bt_rows if r["trades"] > 0]
                section2_pooled.append({
                    "variant": var,
                    "timeframe": tf,
                    "slippage_bps": bps,
                    "targets": len(coin_bt_rows),
                    "total_trades": pooled_t["total_trades"],
                    "pooled_wr": pooled_t["pooled_wr"],
                    "pooled_pf": pooled_t["pooled_pf"],
                    "pooled_exp": pooled_t["pooled_exp"],
                    "mean_wr": round(float(np.mean([r["win_rate"] for r in active_rows])), 1) if active_rows else 0.0,
                    "mean_pf": round(float(np.mean([r["profit_factor"] for r in active_rows])), 2) if active_rows else 0.0,
                    "mean_exp": round(float(np.mean([r["expectancy_pct"] for r in active_rows])), 3) if active_rows else 0.0,
                    "mean_total_ret": round(float(np.mean([r["total_return_pct"] for r in coin_bt_rows])), 2),
                    "mean_max_dd": round(float(np.mean([r["max_drawdown_pct"] for r in coin_bt_rows])), 2),
                    "mean_mar": round(float(np.mean([r["mar_ratio"] for r in coin_bt_rows])), 2),
                    "mean_sharpe": round(float(np.mean([r["sharpe"] for r in coin_bt_rows])), 2),
                    "total_funding_pnl": round(sum(r["total_funding_pnl"] for r in coin_bt_rows), 2),
                })

    # --- Section 3: Chronological 60% IS vs 40% OOS Blind Walk-Forward ---
    section3_rows: List[Dict[str, Any]] = []
    section3_pooled: List[Dict[str, Any]] = []

    for var in all_variants:
        tf = "1d" if var in variants_1d else "4h"
        ds_map = datasets_l if tf == "1d" else datasets_m
        step_sec = DAY_SEC if tf == "1d" else H4_SEC
        wf_coin_rows: List[Dict[str, Any]] = []
        is_trade_stats: List[Dict[str, Any]] = []
        oos_trade_stats: List[Dict[str, Any]] = []
        is_outs_pooled: List[Dict[str, Any]] = []
        oos_outs_pooled: List[Dict[str, Any]] = []

        for sym in SYMBOLS:
            ds = ds_map.get(sym)
            if not ds or not ds.get("valid") or len(ds["eval_price"]) < 40:
                continue
            eval_candles = ds["eval_price"]
            split_idx = max(20, int(len(eval_candles) * 0.6))
            is_slice = eval_candles[:split_idx]
            oos_slice = eval_candles[split_idx:]
            if len(oos_slice) < 10:
                continue

            sigs = signals_map.get((sym, var), [])
            is_t0, is_t1 = int(is_slice[0]["time"]), int(is_slice[-1]["time"])
            oos_t0, oos_t1 = int(oos_slice[0]["time"]), int(oos_slice[-1]["time"])

            sigs_is = [s for s in sigs if is_t0 <= int(s["time"]) <= is_t1]
            sigs_oos = [s for s in sigs if oos_t0 <= int(s["time"]) <= oos_t1]

            r_is = run_wide_atr_backtest_slice(ds, sigs_is, price_slice=is_slice, slippage_bps=5.0)
            r_oos = run_wide_atr_backtest_slice(ds, sigs_oos, price_slice=oos_slice, slippage_bps=5.0)
            if "_trade_stats" in r_is:
                is_trade_stats.append(r_is.pop("_trade_stats"))
            if "_trade_stats" in r_oos:
                oos_trade_stats.append(r_oos.pop("_trade_stats"))

            outs_is = compute_multi_horizon_outcomes(is_slice, sigs_is, step_sec=step_sec)
            outs_oos = compute_multi_horizon_outcomes(oos_slice, sigs_oos, step_sec=step_sec)
            is_outs_pooled.extend(outs_is)
            oos_outs_pooled.extend(outs_oos)

            is_mfe14 = [o["mfe_14d"] for o in outs_is if o["mfe_14d"] is not None]
            is_mae14 = [o["mae_14d"] for o in outs_is if o["mae_14d"] is not None]
            oos_mfe14 = [o["mfe_14d"] for o in outs_oos if o["mfe_14d"] is not None]
            oos_mae14 = [o["mae_14d"] for o in outs_oos if o["mae_14d"] is not None]

            is_er14 = round(float(np.median(is_mfe14)) / max(float(np.median(is_mae14)), 1e-4), 2) if is_mfe14 else 0.0
            oos_er14 = round(float(np.median(oos_mfe14)) / max(float(np.median(oos_mae14)), 1e-4), 2) if oos_mfe14 else 0.0

            row = {
                "symbol": sym,
                "timeframe": tf,
                "variant": var,
                "is_days": r_is.get("days", 0.0),
                "is_trades": r_is.get("trades", 0),
                "is_wr": r_is.get("win_rate", 0.0),
                "is_pf": r_is.get("profit_factor", 0.0),
                "is_exp": r_is.get("expectancy_pct", 0.0),
                "is_total_ret": r_is.get("total_return_pct", 0.0),
                "is_dd": r_is.get("max_drawdown_pct", 0.0),
                "is_mar": r_is.get("mar_ratio", 0.0),
                "is_sharpe": r_is.get("sharpe", 0.0),
                "is_er_14d": is_er14,
                "oos_days": r_oos.get("days", 0.0),
                "oos_trades": r_oos.get("trades", 0),
                "oos_wr": r_oos.get("win_rate", 0.0),
                "oos_pf": r_oos.get("profit_factor", 0.0),
                "oos_exp": r_oos.get("expectancy_pct", 0.0),
                "oos_total_ret": r_oos.get("total_return_pct", 0.0),
                "oos_dd": r_oos.get("max_drawdown_pct", 0.0),
                "oos_mar": r_oos.get("mar_ratio", 0.0),
                "oos_sharpe": r_oos.get("sharpe", 0.0),
                "oos_er_14d": oos_er14,
            }
            section3_rows.append(row)
            wf_coin_rows.append(row)

        if wf_coin_rows:
            is_f = [o["mfe_14d"] for o in is_outs_pooled if o["mfe_14d"] is not None]
            is_e = [o["mae_14d"] for o in is_outs_pooled if o["mae_14d"] is not None]
            oos_f = [o["mfe_14d"] for o in oos_outs_pooled if o["mfe_14d"] is not None]
            oos_e = [o["mae_14d"] for o in oos_outs_pooled if o["mae_14d"] is not None]
            is_pooled_er = round(float(np.median(is_f)) / max(float(np.median(is_e)), 1e-4), 2) if is_f else 0.0
            oos_pooled_er = round(float(np.median(oos_f)) / max(float(np.median(oos_e)), 1e-4), 2) if oos_f else 0.0

            is_pool = _pool_trade_stats(is_trade_stats)
            oos_pool = _pool_trade_stats(oos_trade_stats)
            is_active = [r for r in wf_coin_rows if r["is_trades"] > 0]
            oos_active = [r for r in wf_coin_rows if r["oos_trades"] > 0]

            section3_pooled.append({
                "variant": var,
                "timeframe": tf,
                "targets": len(wf_coin_rows),
                "is_total_trades": is_pool["total_trades"],
                "is_pooled_wr": is_pool["pooled_wr"],
                "is_pooled_pf": is_pool["pooled_pf"],
                "is_pooled_exp": is_pool["pooled_exp"],
                "is_mean_wr": round(float(np.mean([r["is_wr"] for r in is_active])), 1) if is_active else 0.0,
                "is_mean_pf": round(float(np.mean([r["is_pf"] for r in is_active])), 2) if is_active else 0.0,
                "is_mean_exp": round(float(np.mean([r["is_exp"] for r in is_active])), 3) if is_active else 0.0,
                "is_mean_ret": round(float(np.mean([r["is_total_ret"] for r in wf_coin_rows])), 2),
                "is_mean_dd": round(float(np.mean([r["is_dd"] for r in wf_coin_rows])), 2),
                "is_mean_mar": round(float(np.mean([r["is_mar"] for r in wf_coin_rows])), 2),
                "is_mean_sharpe": round(float(np.mean([r["is_sharpe"] for r in wf_coin_rows])), 2),
                "is_pooled_er_14d": is_pooled_er,
                "oos_total_trades": oos_pool["total_trades"],
                "oos_pooled_wr": oos_pool["pooled_wr"],
                "oos_pooled_pf": oos_pool["pooled_pf"],
                "oos_pooled_exp": oos_pool["pooled_exp"],
                "oos_mean_wr": round(float(np.mean([r["oos_wr"] for r in oos_active])), 1) if oos_active else 0.0,
                "oos_mean_pf": round(float(np.mean([r["oos_pf"] for r in oos_active])), 2) if oos_active else 0.0,
                "oos_mean_exp": round(float(np.mean([r["oos_exp"] for r in oos_active])), 3) if oos_active else 0.0,
                "oos_mean_ret": round(float(np.mean([r["oos_total_ret"] for r in wf_coin_rows])), 2),
                "oos_mean_dd": round(float(np.mean([r["oos_dd"] for r in wf_coin_rows])), 2),
                "oos_mean_mar": round(float(np.mean([r["oos_mar"] for r in wf_coin_rows])), 2),
                "oos_mean_sharpe": round(float(np.mean([r["oos_sharpe"] for r in wf_coin_rows])), 2),
                "oos_pooled_er_14d": oos_pooled_er,
            })

    # --- Section 4: Automated Objective Falsification Verdict ---
    section4 = _evaluate_falsification_verdict(
        section1_pooled=section1_pooled,
        bootstrap_rows=bootstrap_rows,
        section2_pooled=section2_pooled,
        section3_rows=section3_rows,
        section3_pooled=section3_pooled,
    )

    summary = _sanitize_json({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "synthetic": use_synthetic,
        "metadata": {
            "symbols": list(SYMBOLS),
            "warmup_1d_bars": WARMUP_1D_BARS,
            "quantile_window_1d": QUANTILE_WINDOW_1D,
            "quantile_min_periods_1d": QUANTILE_MIN_PERIODS_1D,
            "arm_window_days": ARM_WINDOW_DAYS,
            "cooldown_1d_bars": COOLDOWN_1D_BARS,
            "cooldown_4h_bars": COOLDOWN_4H_BARS,
            "backtest_params": {
                "fee_rate": 0.0005,
                "slippage_bps_levels": [5.0, 15.0],
                "include_funding": True,
                "initial_sl_atr_mult": 2.5,
                "chandelier_act_atr_mult": 1.5,
                "chandelier_trail_atr_mult": 3.0,
                "risk_per_trade_pct": 1.5,
                "max_notional_pct": 0.95,
                "stop_order": "conservative_ohlc",
            },
        },
        "section0_inventory": inventory,
        "section1_inflection_per_coin": section1_rows,
        "section1_inflection_pooled": section1_pooled,
        "section1_bootstrap": bootstrap_rows,
        "section2_backtest_per_coin": section2_rows,
        "section2_backtest_pooled": section2_pooled,
        "section3_walkforward_per_coin": section3_rows,
        "section3_walkforward_pooled": section3_pooled,
        "section4_verdict": section4,
    })

    md_text = render_macro_markdown_report(summary)
    md_name = "macro_inflection_selftest_report.md" if use_synthetic else "macro_inflection_report.md"
    json_name = "macro_inflection_selftest_report.json" if use_synthetic else "macro_inflection_report.json"
    md_path = output_dir / md_name
    json_path = output_dir / json_name
    md_path.write_text(md_text, encoding="utf-8")
    json_path.write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    summary["md_path"] = str(md_path)
    summary["json_path"] = str(json_path)
    print(f"Saved report: {md_path}")
    print(f"Saved JSON:   {json_path}")
    return summary


def render_macro_markdown_report(summary: Dict[str, Any]) -> str:
    lines: List[str] = [
        "# Solo-Quant Phase 1 Macro Inflection Empirical Research Report",
        f"**Generated at**: {summary['generated_at']} | **Mode**: `{summary['mode']}` | **Synthetic**: {summary['synthetic']}",
        "",
        "## 0. Clean Dataset Inventory (`Dataset L: 1d` & `Dataset M: 1d+4h`)",
        "| Dataset | Symbol | TF | Valid | Clean Start (UTC) | Eval Start (UTC) | Clean End (UTC) | Clean Days | Eval Bars | Warmup Bars | Funding Events | Coverage Details |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]
    for inv in summary.get("section0_inventory", []):
        if inv["dataset"].startswith("Dataset L"):
            detail = (
                f"CoinOI={inv.get('coin_oi_bars', 0)}, Taker={inv.get('taker_bars', 0)}, "
                f"LSUR={inv.get('lsur_bars', 0)}, FR_1d={inv.get('funding_daily_bars', 0)}"
            )
        else:
            detail = (
                f"NatOI={inv.get('native_oi_bars', 0)} + 1dFallbackOI={inv.get('fallback_oi_bars', 0)}, "
                f"NatTaker={inv.get('native_taker_bars', 0)} + 1dFallbackTaker={inv.get('fallback_taker_bars', 0)}"
            )
        if not inv["valid"] and inv.get("reason"):
            detail = f"INVALID: {inv['reason']}"
        lines.append(
            f"| {inv['dataset']} | {inv['symbol']} | {inv['timeframe']} | {'YES' if inv['valid'] else 'NO'} | "
            f"{inv['clean_start_utc']} | {inv['eval_start_utc']} | {inv['clean_end_utc']} | "
            f"{inv['clean_days']:.2f} | {inv['eval_bars']} | {inv['warmup_bars']} | {inv['funding_count']} | {detail} |"
        )

    lines.extend([
        "",
        "## 1. Multi-Horizon Inflection Quality (`+5d`, `+14d`, `+30d`)",
        "",
        "### 1.1 Pooled Across Symbols",
        "| Variant | TF | Signals | Signals/Yr | Hit@14d (%) | Ret +5d (%) | Ret +14d (%) | Ret +30d (%) | Med MFE +14d (%) | Med MAE +14d (%) | Wave ER@14d | Med MFE +30d (%) | Med MAE +30d (%) | Wave ER@30d | Major Wave Capture (%) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for r in summary.get("section1_inflection_pooled", []):
        lines.append(
            f"| {r['variant']} | {r['timeframe']} | {r['signals']} | {r['signals_per_yr']:.2f} | "
            f"{r['hit_14d']:.1f} | {r['ret_5d']:+.3f} | {r['ret_14d']:+.3f} | {r['ret_30d']:+.3f} | "
            f"{r['med_mfe_14d']:.2f} | {r['med_mae_14d']:.2f} | {r['e_ratio_14d']:.2f} | "
            f"{r['med_mfe_30d']:.2f} | {r['med_mae_30d']:.2f} | {r['e_ratio_30d']:.2f} | "
            f"{r['major_wave_capture_pct']:.1f} |"
        )

    lines.extend([
        "",
        "### 1.2 Per-Coin Breakdown",
        "| Symbol | TF | Variant | Signals | Signals/Yr | Hit@14d (%) | Ret +5d (%) | Ret +14d (%) | Ret +30d (%) | Med MFE +14d | Med MAE +14d | Wave ER@14d | Med MFE +30d | Med MAE +30d | Wave ER@30d | Major Wave Capture (%) |",
        "| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for r in summary.get("section1_inflection_per_coin", []):
        lines.append(
            f"| {r['symbol']} | {r['timeframe']} | {r['variant']} | {r['signals']} | {r['signals_per_yr']:.2f} | "
            f"{r['hit_14d']:.1f} | {r['ret_5d']:+.3f} | {r['ret_14d']:+.3f} | {r['ret_30d']:+.3f} | "
            f"{r['med_mfe_14d']:.2f} | {r['med_mae_14d']:.2f} | {r['e_ratio_14d']:.2f} | "
            f"{r['med_mfe_30d']:.2f} | {r['med_mae_30d']:.2f} | {r['e_ratio_30d']:.2f} | "
            f"{r['major_wave_capture_pct']:.1f} |"
        )

    lines.extend([
        "",
        "### 1.3 1,000x Bootstrap Significance Tests (Pooled & Per-Coin)",
        "| Scope | TF | Comparison (A vs B) | N_A | N_B | Ret+14d A vs B | p(Ret@14d) | Ret+30d A vs B | p(Ret@30d) | ER@14d A vs B | p(ER@14d) | ER@30d A vs B | p(ER@30d) |",
        "| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for b in summary.get("section1_bootstrap", []):
        lines.append(
            f"| {b['scope']} | {b['timeframe']} | {b['variant_a']} vs {b['variant_b']} | "
            f"{b['n_a_14d']} | {b['n_b_14d']} | "
            f"{b['ret_14d_a']:+.3f}% vs {b['ret_14d_b']:+.3f}% | {b['p_ret_14d']:.4f} | "
            f"{b['ret_30d_a']:+.3f}% vs {b['ret_30d_b']:+.3f}% | {b['p_ret_30d']:.4f} | "
            f"{b['er_14d_a']:.2f} vs {b['er_14d_b']:.2f} | {b['p_er_14d']:.4f} | "
            f"{b['er_30d_a']:.2f} vs {b['er_30d_b']:.2f} | {b['p_er_30d']:.4f} |"
        )

    lines.extend([
        "",
        "## 2. Wide-ATR Macro Swing Backtest (`2.5x ATR` Initial SL, `3.0x ATR` Chandelier @ `+1.5x ATR`, `1.5%` Risk, `<=0.95x` Notional, `0.05%` Fee + Funding)",
        "",
        "### 2.1 Pooled Summary Across Symbols (`5 bps` & `15 bps`)",
        "| Variant | TF | Slip (bps) | Targets | Total Trades | Pooled WR (%) | Pooled PF | Pooled Exp (%) | Mean Ret (%) | Mean MaxDD (%) | Mean MAR | Mean Sharpe | Total Funding ($) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for r in summary.get("section2_backtest_pooled", []):
        lines.append(
            f"| {r['variant']} | {r['timeframe']} | {r['slippage_bps']:.0f} | {r['targets']} | {r['total_trades']} | "
            f"{r['pooled_wr']:.1f} | {r['pooled_pf']:.2f} | {r['pooled_exp']:+.3f} | {r['mean_total_ret']:+.2f} | "
            f"{r['mean_max_dd']:.2f} | {r['mean_mar']:.2f} | {r['mean_sharpe']:.2f} | {r['total_funding_pnl']:+.2f} |"
        )

    lines.extend([
        "",
        "### 2.2 Per-Coin Wide-ATR Backtest Results",
        "| Symbol | TF | Variant | Slip (bps) | Days | Trades | WR (%) | PF | Exp (%) | Total Ret (%) | MaxDD (%) | MAR | Sharpe | Funding ($) | Fees ($) |",
        "| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for r in summary.get("section2_backtest_per_coin", []):
        lines.append(
            f"| {r['symbol']} | {r['timeframe']} | {r['variant']} | {r['slippage_bps']:.0f} | {r['days']:.1f} | "
            f"{r['trades']} | {r['win_rate']:.1f} | {r['profit_factor']:.2f} | {r['expectancy_pct']:+.3f} | "
            f"{r['total_return_pct']:+.2f} | {r['max_drawdown_pct']:.2f} | {r['mar_ratio']:.2f} | "
            f"{r['sharpe']:.2f} | {r['total_funding_pnl']:+.2f} | {r['total_fees_paid']:.2f} |"
        )

    lines.extend([
        "",
        "## 3. Chronological 60% IS vs 40% OOS Blind Walk-Forward (`5 bps`, Funding=True)",
        "",
        "### 3.1 Pooled / Mean Walk-Forward Summary",
        "| Variant | TF | IS Trades | IS WR (%) | IS PF | IS Exp (%) | IS Ret (%) | IS DD (%) | IS MAR | IS Sharpe | IS ER@14d | OOS Trades | OOS WR (%) | OOS PF | OOS Exp (%) | OOS Ret (%) | OOS DD (%) | OOS MAR | OOS Sharpe | OOS ER@14d |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for r in summary.get("section3_walkforward_pooled", []):
        lines.append(
            f"| {r['variant']} | {r['timeframe']} | "
            f"{r['is_total_trades']} | {r['is_pooled_wr']:.1f} | {r['is_pooled_pf']:.2f} | {r['is_pooled_exp']:+.3f} | "
            f"{r['is_mean_ret']:+.2f} | {r['is_mean_dd']:.2f} | {r['is_mean_mar']:.2f} | {r['is_mean_sharpe']:.2f} | {r['is_pooled_er_14d']:.2f} | "
            f"{r['oos_total_trades']} | {r['oos_pooled_wr']:.1f} | {r['oos_pooled_pf']:.2f} | {r['oos_pooled_exp']:+.3f} | "
            f"{r['oos_mean_ret']:+.2f} | {r['oos_mean_dd']:.2f} | {r['oos_mean_mar']:.2f} | {r['oos_mean_sharpe']:.2f} | {r['oos_pooled_er_14d']:.2f} |"
        )

    lines.extend([
        "",
        "### 3.2 Per-Coin Walk-Forward Breakdown",
        "| Symbol | TF | Variant | IS Trades | IS WR | IS PF | IS Exp (%) | IS Ret (%) | IS DD | IS MAR | IS Sharpe | IS ER@14d | OOS Trades | OOS WR | OOS PF | OOS Exp (%) | OOS Ret (%) | OOS DD | OOS MAR | OOS Sharpe | OOS ER@14d |",
        "| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for r in summary.get("section3_walkforward_per_coin", []):
        lines.append(
            f"| {r['symbol']} | {r['timeframe']} | {r['variant']} | "
            f"{r['is_trades']} | {r['is_wr']:.1f} | {r['is_pf']:.2f} | {r['is_exp']:+.3f} | "
            f"{r['is_total_ret']:+.2f} | {r['is_dd']:.2f} | {r['is_mar']:.2f} | {r['is_sharpe']:.2f} | {r['is_er_14d']:.2f} | "
            f"{r['oos_trades']} | {r['oos_wr']:.1f} | {r['oos_pf']:.2f} | {r['oos_exp']:+.3f} | "
            f"{r['oos_total_ret']:+.2f} | {r['oos_dd']:.2f} | {r['oos_mar']:.2f} | {r['oos_sharpe']:.2f} | {r['oos_er_14d']:.2f} |"
        )

    v = summary.get("section4_verdict", {})
    lines.extend([
        "",
        "## 4. Automated Objective Falsification Verdict (`alpha = 0.10` & Blind OOS Checks)",
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
    parser = argparse.ArgumentParser(description="Solo-Quant Phase 1 Macro Inflection Empirical Research Runner")
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
        help="Directory to write markdown and JSON reports.",
    )
    args = parser.parse_args()
    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    run_all_macro_experiments(mode=args.mode, output_dir=out_dir)


if __name__ == "__main__":
    main()
