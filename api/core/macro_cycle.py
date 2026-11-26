"""
Phase 1.6 Production Macro Cycle Engine (Cycle_P_v16_1d).

Self-contained, strictly causal long-term 1D cycle engine validated in Phase 1.6:
  - Entry paths (Long-Flat asymmetric cycle capture):
      1) BEAR_BOTTOM_V16      (Path A: secular bear drawdown + RSI washout -> EMA20>EMA50 & rising EMA50 breakout)
      2) REGIONAL_BOTTOM_V16  (Path B: established bull pullback + dip to EMA50/200 -> reclaim breakout)
      3) STAGE2_IGNITION_V16  (Path C: aligned bull MAs & 60d breakout below overheated zone)
  - Exit paths:
      1) BASE_INVALIDATION_V16 (Early structural stop ONLY while peak gain < +25%)
      2) EUPHORIA_TOP_V16      (Mayer Multiple >= adaptive threshold + +45% peak gain + close < EMA20 & 20d low)
      3) REGIME_BEAR_EXIT_V16  (Macro breakdown below EMA50 & 30d low with EMA20 < EMA50)
  - Derivative features (Coin OI, 7D Funding, LSUR Z) are computed causally ONLY as
    left-side conviction / overheating context for UI & Telegram alerts (never block v16 price signals).

Pandas 3.0 CoW safe: zero `.bfill()`, zero `inplace=True`.
"""

from __future__ import annotations

import bisect
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

DAY_SEC = 86400
DEDUP_MIN_GAP_1D = 43200
ALIGN_TOLERANCE_1D = DAY_SEC * 3

CYCLE_COOLDOWN_BARS = 10
LONG_NOTIONAL_PCT = 0.95
DEFAULT_FEE_RATE = 0.0005

CYCLE_EVENT_META: Dict[str, Dict[str, Any]] = {
    "BEAR_BOTTOM_V16": {
        "direction": "bullish",
        "position": "belowBar",
        "shape": "arrowUp",
        "color": "#10b981",
        "short_label": "熊市大底",
        "title": "熊市反轉大底建倉",
    },
    "REGIONAL_BOTTOM_V16": {
        "direction": "bullish",
        "position": "belowBar",
        "shape": "arrowUp",
        "color": "#22c55e",
        "short_label": "回調大底",
        "title": "牛市回調底部接回",
    },
    "STAGE2_IGNITION_V16": {
        "direction": "bullish",
        "position": "belowBar",
        "shape": "arrowUp",
        "color": "#0ea5e9",
        "short_label": "主升啟動",
        "title": "Stage-2 主升浪啟動",
    },
    "EUPHORIA_TOP_V16": {
        "direction": "bearish",
        "position": "aboveBar",
        "shape": "arrowDown",
        "color": "#f59e0b",
        "short_label": "過熱逃頂",
        "title": "牛市高檔過熱逃頂",
    },
    "REGIME_BEAR_EXIT_V16": {
        "direction": "bearish",
        "position": "aboveBar",
        "shape": "arrowDown",
        "color": "#ef4444",
        "short_label": "轉熊離場",
        "title": "趨勢破位轉熊防禦離場",
    },
    "BASE_INVALIDATION_V16": {
        "direction": "bearish",
        "position": "aboveBar",
        "shape": "arrowDown",
        "color": "#f43f5e",
        "short_label": "結構止損",
        "title": "建倉初期結構失效止損",
    },
}


def _is_finite(v: Any) -> bool:
    if v is None:
        return False
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def _is_finite_pos(v: Any) -> bool:
    if v is None:
        return False
    try:
        fv = float(v)
        return math.isfinite(fv) and fv > 0.0
    except (TypeError, ValueError):
        return False


def _clean_float(val: Any, digits: Optional[int] = None) -> Optional[float]:
    """Return finite Python float (optionally rounded) or None for JSON safety."""
    if not _is_finite(val):
        return None
    f = float(val)
    if digits is not None:
        f = round(f, digits)
    return f


def _apply_slippage(price: float, side: str, is_entry: bool, slippage_bps: float) -> float:
    slip = max(0.0, float(slippage_bps)) / 10000.0
    if slip <= 0.0:
        return float(price)
    is_buy = (side == "long" and is_entry) or (side == "short" and not is_entry)
    return float(price) * (1.0 + slip) if is_buy else float(price) * (1.0 - slip)


def _normalize_ts_sec(ts: Any) -> Optional[int]:
    if ts is None:
        return None
    try:
        t = int(float(ts))
    except (TypeError, ValueError):
        return None
    if abs(t) > 1e11:
        t = t // 1000
    return t


def deduplicate_1d_candles(price_data: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Sort 1d OHLCV bars ascending and drop overlapping bars where t_curr - t_prev < 43200s
    while keeping the newer bar cleanly.
    """
    valid: List[Dict[str, Any]] = []
    for b in price_data or []:
        t = _normalize_ts_sec(b.get("time"))
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


def rolling_percentile_causal(values: np.ndarray, window: int = 180, min_periods: int = 45) -> np.ndarray:
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


def align_bar_series_causal(
    candle_opens: Sequence[int],
    series_rows: Optional[Sequence[Dict[str, Any]]],
    *,
    value_key: str = "value",
    positive_only: bool = False,
    tolerance_sec: int = ALIGN_TOLERANCE_1D,
) -> np.ndarray:
    """Strictly causal backward alignment onto candle_opens with zero .bfill()."""
    n = len(candle_opens)
    if n == 0:
        return np.array([], dtype=float)
    if not series_rows:
        return np.full(n, np.nan, dtype=float)

    clean_rows: List[Tuple[int, float]] = []
    for r in series_rows:
        if not isinstance(r, dict):
            continue
        t_raw = _normalize_ts_sec(r.get("time"))
        v_raw = r.get(value_key)
        if t_raw is None:
            continue
        ok = _is_finite_pos(v_raw) if positive_only else _is_finite(v_raw)
        if not ok:
            continue
        clean_rows.append((t_raw, float(v_raw)))

    if not clean_rows:
        return np.full(n, np.nan, dtype=float)

    df_src = pd.DataFrame(clean_rows, columns=["time", "val"])
    df_src = df_src.sort_values("time").drop_duplicates(subset=["time"], keep="last").reset_index(drop=True)

    df_tgt = pd.DataFrame({"time": [int(t) for t in candle_opens], "_pos": np.arange(n)})
    df_tgt_sorted = df_tgt.sort_values("time")

    merged = pd.merge_asof(
        df_tgt_sorted,
        df_src,
        on="time",
        direction="backward",
        tolerance=tolerance_sec,
    )
    merged = merged.sort_values("_pos")
    return merged["val"].to_numpy(dtype=float)


def _prep_funding_events(funding_rates: Optional[Sequence[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if not funding_rates:
        return []
    dedup: Dict[int, float] = {}
    for fs in funding_rates:
        if not isinstance(fs, dict) or "time" not in fs:
            continue
        ft = _normalize_ts_sec(fs.get("time"))
        raw_r = fs.get("funding_rate", fs.get("rate"))
        if ft is None or not _is_finite(raw_r):
            continue
        dedup[ft] = float(raw_r)
    return [{"time": ft, "funding_rate": dedup[ft]} for ft in sorted(dedup.keys())]


def align_funding_daily_causal(
    candle_opens: Sequence[int],
    funding_settlements: Optional[Sequence[Dict[str, Any]]] = None,
    funding_aligned_pct: Optional[Sequence[Dict[str, Any]]] = None,
) -> np.ndarray:
    """
    Align FundingRate settlements causally onto 1d bars (mean over (t_open, t_open + 86400]).
    Falls back to backward merge_asof (<= 3 days) or aligned percentage funding series / 100.
    """
    n = len(candle_opens)
    if n == 0:
        return np.array([], dtype=float)

    events = _prep_funding_events(funding_settlements)
    if events:
        f_times = [int(f["time"]) for f in events]
        f_rates = [float(f["funding_rate"]) for f in events]

        df_src = pd.DataFrame({"known_ts": f_times, "val": f_rates})
        df_src = df_src.sort_values("known_ts").drop_duplicates(subset=["known_ts"], keep="last").reset_index(drop=True)
        known_ts = [int(t) + DAY_SEC for t in candle_opens]
        df_tgt = pd.DataFrame({"known_ts": known_ts, "_pos": np.arange(n)}).sort_values("known_ts")
        merged = pd.merge_asof(
            df_tgt,
            df_src,
            on="known_ts",
            direction="backward",
            tolerance=ALIGN_TOLERANCE_1D,
        ).sort_values("_pos")
        fallback = merged["val"].to_numpy(dtype=float)

        out = np.full(n, np.nan, dtype=float)
        for i in range(n):
            t_lo = int(candle_opens[i])
            t_hi = t_lo + DAY_SEC
            idx_lo = bisect.bisect_right(f_times, t_lo)
            idx_hi = bisect.bisect_right(f_times, t_hi)
            if idx_hi > idx_lo:
                out[i] = float(np.mean(f_rates[idx_lo:idx_hi]))
            elif math.isfinite(fallback[i]):
                out[i] = float(fallback[i])
        return out

    if funding_aligned_pct:
        raw_dec = [
            {"time": r.get("time"), "value": float(r["value"]) / 100.0}
            for r in funding_aligned_pct
            if isinstance(r, dict) and _is_finite(r.get("value"))
        ]
        return align_bar_series_causal(candle_opens, raw_dec, value_key="value", positive_only=False)

    return np.full(n, np.nan, dtype=float)


# ---------------------------------------------------------------------------
# Phase 1.6 Feature Engine (Exact Cycle_P_v16_1d + Causal UI Context)
# ---------------------------------------------------------------------------

def evaluate_macro_cycle_features_1d(
    candles_or_df: Sequence[Dict[str, Any]] | pd.DataFrame,
    *,
    oi_aligned: Optional[Sequence[Dict[str, Any]]] = None,
    funding_settlements: Optional[Sequence[Dict[str, Any]]] = None,
    funding_aligned: Optional[Sequence[Dict[str, Any]]] = None,
    lsur_z_aligned: Optional[Sequence[Dict[str, Any]]] = None,
) -> pd.DataFrame:
    """
    Compute all strictly causal Phase 1.6 daily indicators and cycle flags.
    Zero .bfill(), zero inplace=True. Prefix 0..k produces identical values at 0..k-1.
    """
    if isinstance(candles_or_df, pd.DataFrame):
        if candles_or_df.empty:
            return pd.DataFrame()
        df = candles_or_df.sort_values("time").reset_index(drop=True).copy()
    else:
        dedup = deduplicate_1d_candles(candles_or_df)
        if not dedup:
            return pd.DataFrame()
        df = pd.DataFrame(dedup)

    opens_ts = [int(t) for t in df["time"].to_numpy(dtype=int)]
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()
    atr14 = compute_wilder_atr(high, low, close, period=14)
    rsi14 = compute_wilder_rsi(close, period=14)

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
    dyn_dd_180_thresh = pd.Series(np.clip(6.0 * atr_pct_median60, 0.30, 0.52), index=df.index)
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
    dyn_dd_90_thresh = pd.Series(np.clip(4.0 * atr_pct_median60, 0.16, 0.36), index=df.index)
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

    # --- Exit 1_v16: Euphoria Climax + Distribution Breakdown ---
    mayer = close / ema200_pos
    mayer_10d = high_max_10d / ema200_pos
    euphoria_mayer_thresh = pd.Series(np.clip(1.0 + 12.0 * atr_pct_median60, 1.55, 2.20), index=df.index)
    euphoria_ext_atr = (high_max_10d - ema200) / atr_pos
    euphoria_price_bar_v16 = (
        (mayer_10d >= euphoria_mayer_thresh)
        & (euphoria_ext_atr >= 5.5)
        & (rsi_max_15d >= 76.0)
    ).fillna(False)
    euphoria_price_30d_v16 = (
        euphoria_price_bar_v16.astype(int).rolling(window=30, min_periods=1).max() > 0
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

    # --- UI-Only Causal Derivative Context (never alters Cycle_P_v16_1d trade signals) ---
    close_arr = close.to_numpy(dtype=float)
    if oi_aligned is not None:
        oi_usd = align_bar_series_causal(opens_ts, oi_aligned, value_key="value", positive_only=True)
        coin_oi = np.where(np.isfinite(oi_usd) & (oi_usd > 0.0) & (close_arr > 0.0), oi_usd / close_arr, np.nan)
    elif "coin_oi" in df.columns:
        coin_oi = df["coin_oi"].to_numpy(dtype=float)
    elif "oi_usd" in df.columns:
        oi_usd = df["oi_usd"].to_numpy(dtype=float)
        coin_oi = np.where(np.isfinite(oi_usd) & (oi_usd > 0.0) & (close_arr > 0.0), oi_usd / close_arr, np.nan)
    else:
        coin_oi = np.full(len(df), np.nan, dtype=float)

    if funding_settlements is not None or funding_aligned is not None:
        funding_daily = align_funding_daily_causal(opens_ts, funding_settlements, funding_aligned)
    elif "funding_daily" in df.columns:
        funding_daily = df["funding_daily"].to_numpy(dtype=float)
    else:
        funding_daily = np.full(len(df), np.nan, dtype=float)

    if lsur_z_aligned is not None:
        lsur_z_90d = align_bar_series_causal(opens_ts, lsur_z_aligned, value_key="value", positive_only=False)
    elif "lsur_z_90d" in df.columns:
        lsur_z_90d = df["lsur_z_90d"].to_numpy(dtype=float)
    else:
        lsur_z_90d = np.full(len(df), np.nan, dtype=float)

    coin_oi_series = pd.Series(coin_oi, index=df.index, dtype=float)
    coin_oi_pos = coin_oi_series.where(coin_oi_series > 0.0, np.nan)
    coin_oi_max_60d = coin_oi_pos.rolling(window=60, min_periods=30).max()
    coin_oi_max_60d_pos = coin_oi_max_60d.where(coin_oi_max_60d > 0.0, np.nan)
    coin_oi_dd_60d = ((coin_oi_pos / coin_oi_max_60d_pos) - 1.0) * 100.0
    coin_oi_dd_60d = coin_oi_dd_60d.where(coin_oi_pos.notna() & coin_oi_max_60d_pos.notna(), np.nan)
    coin_oi_pct_180d = pd.Series(
        rolling_percentile_causal(coin_oi_pos.to_numpy(dtype=float), window=180, min_periods=45),
        index=df.index,
    )

    funding_daily_series = pd.Series(funding_daily, index=df.index, dtype=float)
    fr_7d_raw = funding_daily_series.rolling(window=7, min_periods=1).mean()
    fr_7d_mean = pd.Series(
        np.where(funding_daily_series.notna(), fr_7d_raw.to_numpy(dtype=float), np.nan),
        index=df.index,
    )
    fr_pct_180d = pd.Series(
        rolling_percentile_causal(funding_daily_series.to_numpy(dtype=float), window=180, min_periods=45),
        index=df.index,
    )
    lsur_z_series = pd.Series(lsur_z_90d, index=df.index, dtype=float)

    has_deriv = (
        coin_oi_pos.notna()
        | fr_7d_mean.notna()
        | lsur_z_series.notna()
    ).fillna(False)

    washout_bar_v16 = (
        (coin_oi_dd_60d <= -20.0)
        | (coin_oi_pct_180d <= 20.0)
        | (fr_7d_mean < 0.0)
        | (lsur_z_series <= -1.3)
    ).fillna(False)
    deriv_washout_60d = (
        (has_deriv & washout_bar_v16).astype(int).rolling(window=60, min_periods=1).max() > 0
    ).fillna(False)

    deriv_overheated_bar_v16 = (
        (coin_oi_pct_180d >= 80.0)
        & ((fr_pct_180d >= 80.0) | (fr_7d_mean >= 0.00020) | (lsur_z_series >= 1.2))
    ).fillna(False)
    deriv_overheated_30d_v16 = (
        (has_deriv & deriv_overheated_bar_v16).astype(int).rolling(window=30, min_periods=1).max() > 0
    ).fillna(False)

    df["ema20"] = ema20
    df["ema50"] = ema50
    df["ema200"] = ema200
    df["ema50_rising"] = (ema50 > ema50_shift10).fillna(False).to_numpy(dtype=bool)
    df["ema200_rising"] = (ema200 > ema200_shift20).fillna(False).to_numpy(dtype=bool)
    df["atr14"] = atr14
    df["rsi14"] = rsi14
    df["atr_pct"] = atr_pct
    df["atr_pct_median60"] = atr_pct_median60
    df["low_min_20d"] = low_min_20d
    df["dd_180_pct"] = dd_180_pct
    df["dyn_dd_180_thresh"] = dyn_dd_180_thresh
    df["dd_90_pct"] = dd_90_pct
    df["dyn_dd_90_thresh"] = dyn_dd_90_thresh
    df["mayer"] = mayer
    df["mayer_10d"] = mayer_10d
    df["euphoria_mayer_thresh"] = euphoria_mayer_thresh

    df["coin_oi"] = coin_oi_pos
    df["coin_oi_dd_60d"] = coin_oi_dd_60d
    df["coin_oi_pct_180d"] = coin_oi_pct_180d
    df["fr_7d_mean"] = fr_7d_mean
    df["fr_pct_180d"] = fr_pct_180d
    df["lsur_z_90d"] = lsur_z_series
    df["has_deriv"] = has_deriv.to_numpy(dtype=bool)
    df["deriv_washout_60d"] = deriv_washout_60d.to_numpy(dtype=bool)
    df["deriv_overheated_30d_v16"] = deriv_overheated_30d_v16.to_numpy(dtype=bool)

    df["bear_left_active_v16"] = bear_left_active_v16.to_numpy(dtype=bool)
    df["reg_context_ok_v16"] = reg_context_ok_v16.to_numpy(dtype=bool)
    df["reg_left_active_v16"] = reg_left_active_v16.to_numpy(dtype=bool)
    df["path_a_v16_ok"] = path_a_v16_ok.to_numpy(dtype=bool)
    df["path_b_v16_ok"] = path_b_v16_ok.to_numpy(dtype=bool)
    df["path_c_v16_ok"] = path_c_v16_ok.to_numpy(dtype=bool)

    df["euphoria_price_30d_v16"] = euphoria_price_30d_v16.to_numpy(dtype=bool)
    df["euphoria_breakdown_right_v16"] = euphoria_breakdown_right_v16.to_numpy(dtype=bool)
    df["regime_bear_exit_v16"] = regime_bear_exit_v16.to_numpy(dtype=bool)
    return df


# ---------------------------------------------------------------------------
# Stateful Phase 1.6 Simulation Engine (Pure Price Cycle_P_v16_1d)
# ---------------------------------------------------------------------------

@dataclass
class MacroCyclePosition:
    symbol: str
    side: str
    entry_price: float
    entry_time: int
    entry_idx: int
    entry_type: str
    size: float
    atr_entry: float
    base_stop: float
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    cost: float = 0.0
    initial_cost: float = 0.0
    highest_since_entry: float = 0.0
    lowest_since_entry: float = float("inf")
    base_stop_disabled: bool = False
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
        self.initial_cost = self.cost
        self.highest_since_entry = self.entry_price
        self.lowest_since_entry = self.entry_price

    def peak_mfe_pct(self) -> float:
        if self.entry_price <= 0.0:
            return 0.0
        return max(0.0, (self.highest_since_entry - self.entry_price) / self.entry_price * 100.0)

    def max_mae_pct(self) -> float:
        if self.entry_price <= 0.0:
            return 0.0
        return max(0.0, (self.entry_price - self.lowest_since_entry) / self.entry_price * 100.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side,
            "entry_type": self.entry_type,
            "entry_price": round(float(self.entry_price), 6),
            "entry_time": int(self.entry_time),
            "size": round(float(self.size), 8),
            "cost": round(float(self.cost), 4),
            "take_profit": 0.0,
            "stop_loss": round(float(self.base_stop), 6),
            "trailing_active": bool(self.highest_since_entry >= self.entry_price * 1.45),
            "trailing_stop_price": 0.0,
            "exit_price": round(float(self.exit_price), 6),
            "exit_time": int(self.exit_time),
            "exit_reason": self.exit_reason,
            "realized_pnl": round(float(self.realized_pnl), 4),
            "fees_paid": round(float(self.fees_paid), 4),
            "is_closed": bool(self.is_closed),
            "peak_mfe_pct": round(self.peak_mfe_pct(), 2),
        }


def _extract_row_deriv_context(df_feat: pd.DataFrame, idx: int) -> Dict[str, Any]:
    row = df_feat.iloc[idx]
    has_d = bool(row.get("has_deriv", False))
    oi_dd = _clean_float(row.get("coin_oi_dd_60d"), 1)
    oi_pct = _clean_float(row.get("coin_oi_pct_180d"), 1)
    fr_7d_val = _clean_float(row.get("fr_7d_mean"))
    fr_7d_pct = round(fr_7d_val * 100.0, 4) if fr_7d_val is not None else None
    fr_pct = _clean_float(row.get("fr_pct_180d"), 1)
    lsur_z = _clean_float(row.get("lsur_z_90d"), 2)
    washout = bool(row.get("deriv_washout_60d", False))
    overheated = bool(row.get("deriv_overheated_30d_v16", False))

    if not has_d or (oi_dd is None and oi_pct is None and fr_7d_pct is None and lsur_z is None):
        summary = "暫無足夠衍生品歷史佐證（由純價格週期結構獨立決策）"
    elif overheated:
        summary = "衍生品擁擠與槓桿偏高，符合牛市派發/過熱背景佐證"
    elif washout:
        summary = "近 60 日出現 OI 去槓桿或負費率/空頭洗盤，左側底部佐證較充實"
    else:
        summary = "衍生品籌碼與槓桿位階處於中性常態區間"

    return {
        "has_deriv": has_d,
        "coin_oi_dd_60d": oi_dd,
        "coin_oi_pct_180d": oi_pct,
        "fr_7d_mean_pct": fr_7d_pct,
        "fr_pct_180d": fr_pct,
        "lsur_z_90d": lsur_z,
        "washout_60d": washout,
        "overheated_30d": overheated,
        "summary": summary,
    }


def compute_cycle_portfolio_metrics(
    equity_curve: Sequence[Dict[str, Any]],
    closed_positions: Sequence[MacroCyclePosition],
    *,
    investment: float = 10000.0,
    final_balance: float = 10000.0,
    total_fees_paid: float = 0.0,
    total_funding_pnl: float = 0.0,
    bars_in_market: int = 0,
    total_bars: int = 0,
) -> Dict[str, Any]:
    """Compute unified metrics compatible with SignalBacktestMetrics + cycle metrics."""
    n_eq = len(equity_curve)
    days = 1.0
    if n_eq >= 2:
        days = max((int(equity_curve[-1]["time"]) - int(equity_curve[0]["time"])) / float(DAY_SEC), 1.0)

    total_trades = len(closed_positions)
    trades_per_yr = (total_trades / max(days / 365.0, 1e-4)) if total_trades > 0 else 0.0

    wins = [p for p in closed_positions if p.realized_pnl > 0.0]
    losses = [p for p in closed_positions if p.realized_pnl <= 0.0]
    win_rate = (len(wins) / total_trades * 100.0) if total_trades > 0 else 0.0

    win_rets = [(p.realized_pnl / p.initial_cost * 100.0) for p in wins if p.initial_cost > 0.0]
    loss_rets = [(p.realized_pnl / p.initial_cost * 100.0) for p in losses if p.initial_cost > 0.0]
    hold_days_list = [max(0.0, (p.exit_time - p.entry_time) / float(DAY_SEC)) for p in closed_positions]

    avg_win_pct = float(np.mean(win_rets)) if win_rets else 0.0
    avg_loss_pct = float(np.mean(loss_rets)) if loss_rets else 0.0
    avg_hold_days = float(np.mean(hold_days_list)) if hold_days_list else 0.0
    avg_mfe_pct = float(np.mean([p.peak_mfe_pct() for p in closed_positions])) if closed_positions else 0.0
    avg_mae_pct = float(np.mean([p.max_mae_pct() for p in closed_positions])) if closed_positions else 0.0

    gross_profit = float(sum(p.realized_pnl for p in wins))
    gross_loss = float(abs(sum(p.realized_pnl for p in losses)))
    if gross_loss > 0.0:
        pf = min(gross_profit / gross_loss, 999.9)
    else:
        pf = 999.9 if gross_profit > 0.0 else 0.0

    pnl = final_balance - investment
    total_ret_pct = (pnl / investment * 100.0) if investment > 0.0 else 0.0
    cagr_pct = ((final_balance / investment) ** (365.0 / days) - 1.0) * 100.0 if (final_balance > 0.0 and investment > 0.0) else -100.0

    max_dd = 0.0
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
        "initial_balance": round(float(investment), 2),
        "final_balance": round(float(final_balance), 2),
        "pnl": round(float(pnl), 2),
        "pnl_percent": round(float(total_ret_pct), 2),
        "total_trades": int(total_trades),
        "win_rate": round(float(win_rate), 1),
        "winning_trades": int(len(wins)),
        "losing_trades": int(len(losses)),
        "avg_win_pct": round(float(avg_win_pct), 2),
        "avg_loss_pct": round(float(avg_loss_pct), 2),
        "profit_factor": round(float(pf), 2),
        "max_drawdown_pct": round(float(max_dd), 2),
        "sharpe_ratio": round(float(sharpe), 2),
        "total_fees_paid": round(float(total_fees_paid), 4),
        "total_funding_pnl": round(float(total_funding_pnl), 4),
        "avg_mfe_pct": round(float(avg_mfe_pct), 2),
        "avg_mae_pct": round(float(avg_mae_pct), 2),
        "cagr_pct": round(float(cagr_pct), 2),
        "mar_ratio": round(float(mar), 2),
        "avg_hold_days": round(float(avg_hold_days), 1),
        "time_in_market_pct": round(float(time_in_mkt_pct), 1),
        "trades_per_yr": round(float(trades_per_yr), 2),
    }


def _build_marker_from_event(event: Dict[str, Any]) -> Dict[str, Any]:
    ev_name = str(event["cycle_event"])
    meta = CYCLE_EVENT_META[ev_name]
    is_bull = meta["direction"] == "bullish"
    mayer = event.get("mayer")
    mayer_str = f"Mayer {mayer:.2f}x" if isinstance(mayer, (int, float)) else ""

    if is_bull:
        stop_px = event.get("base_stop")
        dd_180 = event.get("dd_180_pct")
        parts = [meta["short_label"]]
        if mayer_str:
            parts.append(mayer_str)
        if isinstance(dd_180, (int, float)):
            parts.append(f"180D回撤{dd_180 * 100.0:.0f}%")
        if isinstance(stop_px, (int, float)) and stop_px > 0:
            parts.append(f"初期停損 {stop_px:.4g}")
        text = f"🌊 [{ev_name}] " + " | ".join(parts)
    else:
        pnl_pct = event.get("realized_pnl_pct")
        mfe_pct = event.get("peak_mfe_pct")
        hold_d = event.get("hold_days")
        parts = [meta["short_label"]]
        if isinstance(pnl_pct, (int, float)):
            parts.append(f"報酬 {pnl_pct:+.1f}%")
        if isinstance(mfe_pct, (int, float)):
            parts.append(f"峰值 +{mfe_pct:.1f}%")
        if isinstance(hold_d, (int, float)):
            parts.append(f"抱{hold_d:.0f}天")
        if mayer_str:
            parts.append(mayer_str)
        text = f"🌊 [{ev_name}] " + " | ".join(parts)

    return {
        "time": int(event["time"]),
        "position": meta["position"],
        "color": meta["color"],
        "shape": meta["shape"],
        "size": 2,
        "direction": meta["direction"],
        "strategy_type": "macro_cycle",
        "archetype": "macro_cycle",
        "cycle_event": ev_name,
        "short_label": meta["short_label"],
        "text": text,
        "score": 5.0,
        "price": _clean_float(event.get("price")),
        "base_stop": _clean_float(event.get("base_stop")),
        "mayer": _clean_float(mayer, 3),
        "realized_pnl_pct": _clean_float(event.get("realized_pnl_pct"), 2),
        "peak_mfe_pct": _clean_float(event.get("peak_mfe_pct"), 2),
        "hold_days": _clean_float(event.get("hold_days"), 1),
        "deriv_context": event.get("deriv_context"),
    }


def simulate_macro_cycle_v16(
    symbol: str,
    df_feat: pd.DataFrame,
    *,
    start_idx: int,
    end_idx: Optional[int] = None,
    funding_rates: Optional[Sequence[Dict[str, Any]]] = None,
    slippage_bps: float = 5.0,
    fee_rate: float = DEFAULT_FEE_RATE,
    investment: float = 10000.0,
    include_funding: bool = True,
    force_close_end: bool = True,
) -> Dict[str, Any]:
    """
    Exact production simulation matching Phase 1.6 `Cycle_P_v16_1d` (Pure Price Anti-Bear-Trap + Hold-to-Top).
    """
    if start_idx < 0:
        raise ValueError(f"start_idx must be >= 0, got {start_idx!r}")

    n_total = len(df_feat)
    stop_idx = n_total if end_idx is None else min(n_total, int(end_idx))
    if n_total == 0 or start_idx >= stop_idx:
        empty_m = compute_cycle_portfolio_metrics([], [], investment=investment, final_balance=investment)
        return {
            "metrics": empty_m,
            "closed_positions": [],
            "open_position": None,
            "equity_curve": [],
            "trades": [],
            "events": [],
            "markers": [],
            "final_state": "FLAT",
        }

    times = df_feat["time"].to_numpy(dtype=int)
    opens = df_feat["open"].to_numpy(dtype=float)
    highs = df_feat["high"].to_numpy(dtype=float)
    lows = df_feat["low"].to_numpy(dtype=float)
    closes = df_feat["close"].to_numpy(dtype=float)
    atr14 = df_feat["atr14"].to_numpy(dtype=float)
    low_min_20d = df_feat["low_min_20d"].to_numpy(dtype=float)
    mayer_arr = df_feat["mayer"].to_numpy(dtype=float)
    dd_180_arr = df_feat["dd_180_pct"].to_numpy(dtype=float)
    dd_90_arr = df_feat["dd_90_pct"].to_numpy(dtype=float)

    path_a_ok = df_feat["path_a_v16_ok"].to_numpy(dtype=bool)
    path_b_ok = df_feat["path_b_v16_ok"].to_numpy(dtype=bool)
    path_c_ok = df_feat["path_c_v16_ok"].to_numpy(dtype=bool)

    euphoria_price_30d = df_feat["euphoria_price_30d_v16"].to_numpy(dtype=bool)
    euphoria_breakdown_right = df_feat["euphoria_breakdown_right_v16"].to_numpy(dtype=bool)
    regime_bear_exit = df_feat["regime_bear_exit_v16"].to_numpy(dtype=bool)

    funding_events = _prep_funding_events(funding_rates)
    f_idx = 0
    first_t = int(times[start_idx])
    while f_idx < len(funding_events) and funding_events[f_idx]["time"] <= first_t:
        f_idx += 1

    balance = float(investment)
    open_pos: Optional[MacroCyclePosition] = None
    closed_positions: List[MacroCyclePosition] = []
    trades: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []
    equity_curve: List[Dict[str, Any]] = []
    total_fees = 0.0
    total_funding = 0.0
    bars_in_mkt = 0
    last_long_exit_idx = -1000

    def _calc_equity(px: float) -> float:
        if open_pos is None:
            return balance
        return balance + open_pos.size * px

    def _close_pos(pos: MacroCyclePosition, fill_px: float, bar_i: int, reason: str, *, record_event: bool = True) -> None:
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

        pnl_pct = (pos.realized_pnl / pos.initial_cost * 100.0) if pos.initial_cost > 0.0 else 0.0
        hold_days = max(0.0, (pos.exit_time - pos.entry_time) / float(DAY_SEC))
        eq_now = balance

        trades.append({
            "time": pos.exit_time,
            "side": "close_long",
            "price": round(float(fill_px), 6),
            "amount": float(pos.size),
            "fee": round(float(exit_fee), 4),
            "realized_pnl": round(float(pos.realized_pnl), 4),
            "exit_reason": reason,
            "entry_type": pos.entry_type,
            "position_id": pos.id,
            "equity": round(float(eq_now), 2),
        })

        if record_event and reason in CYCLE_EVENT_META:
            events.append({
                "time": pos.exit_time,
                "cycle_event": reason,
                "direction": "bearish",
                "price": fill_px,
                "base_stop": None,
                "realized_pnl_pct": pnl_pct,
                "peak_mfe_pct": pos.peak_mfe_pct(),
                "hold_days": hold_days,
                "mayer": _clean_float(mayer_arr[bar_i], 3),
                "dd_180_pct": _clean_float(dd_180_arr[bar_i], 4),
                "dd_90_pct": _clean_float(dd_90_arr[bar_i], 4),
                "deriv_context": _extract_row_deriv_context(df_feat, bar_i),
            })

    for i in range(start_idx, stop_idx):
        ti = int(times[i])
        oi = float(opens[i])
        hi = float(highs[i])
        li = float(lows[i])
        ci = float(closes[i])
        next_t = int(times[i + 1]) if i + 1 < stop_idx else (ti + DAY_SEC)

        was_in_mkt_today = open_pos is not None
        long_stopped_today = False

        # Step 1: Physical pre-close BASE_INVALIDATION_V16 (ONLY while pre-bar peak < +25%)
        if open_pos is not None and i > open_pos.entry_idx:
            if not open_pos.base_stop_disabled and open_pos.highest_since_entry < open_pos.entry_price * 1.25:
                if oi <= open_pos.base_stop:
                    fill = _apply_slippage(oi, "long", is_entry=False, slippage_bps=slippage_bps)
                    _close_pos(open_pos, fill, i, "BASE_INVALIDATION_V16")
                    long_stopped_today = True
                elif li <= open_pos.base_stop:
                    raw_fill = min(open_pos.base_stop, hi)
                    fill = _apply_slippage(raw_fill, "long", is_entry=False, slippage_bps=slippage_bps)
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
            gain_ok = open_pos.highest_since_entry >= open_pos.entry_price * 1.45
            euph_left = bool(euphoria_price_30d[i])
            exit_euphoria = gain_ok and euph_left and bool(euphoria_breakdown_right[i])
            exit_regime = bool(regime_bear_exit[i])

            if exit_euphoria:
                fill = _apply_slippage(ci, "long", is_entry=False, slippage_bps=slippage_bps)
                _close_pos(open_pos, fill, i, "EUPHORIA_TOP_V16")
                closed_long_at_close = True
            elif exit_regime:
                fill = _apply_slippage(ci, "long", is_entry=False, slippage_bps=slippage_bps)
                _close_pos(open_pos, fill, i, "REGIME_BEAR_EXIT_V16")
                closed_long_at_close = True

        # Step 4: Long entry gate when FLAT (after 10-day post-exit cooldown)
        if open_pos is None:
            long_cooldown_ok = (i - last_long_exit_idx >= CYCLE_COOLDOWN_BARS)
            if long_cooldown_ok and not closed_long_at_close and not long_stopped_today:
                entry_type: Optional[str] = None
                if bool(path_a_ok[i]):
                    entry_type = "BEAR_BOTTOM_V16"
                elif bool(path_b_ok[i]):
                    entry_type = "REGIONAL_BOTTOM_V16"
                elif bool(path_c_ok[i]):
                    entry_type = "STAGE2_IGNITION_V16"

                if entry_type is not None:
                    curr_eq = _calc_equity(ci)
                    if curr_eq > 0.0 and balance > 0.0:
                        ep = _apply_slippage(ci, "long", is_entry=True, slippage_bps=slippage_bps)
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
                            open_pos = MacroCyclePosition(
                                symbol=symbol,
                                side="long",
                                entry_price=ep,
                                entry_time=ti,
                                entry_idx=i,
                                entry_type=entry_type,
                                size=size,
                                atr_entry=atr_e,
                                base_stop=b_stop,
                            )
                            open_pos.fees_paid = e_fee
                            eq_after_entry = _calc_equity(ci)
                            trades.append({
                                "time": ti,
                                "side": "open_long",
                                "price": round(float(ep), 6),
                                "amount": float(size),
                                "fee": round(float(e_fee), 4),
                                "realized_pnl": 0.0,
                                "exit_reason": "",
                                "entry_type": entry_type,
                                "position_id": open_pos.id,
                                "equity": round(float(eq_after_entry), 2),
                            })
                            events.append({
                                "time": ti,
                                "cycle_event": entry_type,
                                "direction": "bullish",
                                "price": ep,
                                "base_stop": b_stop,
                                "realized_pnl_pct": None,
                                "peak_mfe_pct": None,
                                "hold_days": None,
                                "mayer": _clean_float(mayer_arr[i], 3),
                                "dd_180_pct": _clean_float(dd_180_arr[i], 4),
                                "dd_90_pct": _clean_float(dd_90_arr[i], 4),
                                "deriv_context": _extract_row_deriv_context(df_feat, i),
                            })

        if was_in_mkt_today or (open_pos is not None):
            bars_in_mkt += 1

        equity_curve.append({"time": ti, "value": round(float(_calc_equity(ci)), 4)})

    final_state = "FLAT" if open_pos is None else "LONG"

    if force_close_end and open_pos is not None:
        last_idx = stop_idx - 1
        _close_pos(open_pos, float(closes[last_idx]), last_idx, "backtest_end", record_event=False)
        if equity_curve:
            equity_curve[-1]["value"] = round(float(balance), 4)

    final_eval_equity = (
        equity_curve[-1]["value"]
        if (open_pos is not None and equity_curve)
        else balance
    )
    metrics = compute_cycle_portfolio_metrics(
        equity_curve,
        closed_positions,
        investment=investment,
        final_balance=final_eval_equity,
        total_fees_paid=total_fees,
        total_funding_pnl=total_funding,
        bars_in_market=bars_in_mkt,
        total_bars=(stop_idx - start_idx),
    )

    markers = [_build_marker_from_event(ev) for ev in events]

    return {
        "metrics": metrics,
        "closed_positions": closed_positions,
        "open_position": open_pos,
        "equity_curve": equity_curve,
        "trades": trades,
        "events": events,
        "markers": markers,
        "final_state": final_state,
    }


def _classify_zone(row: pd.Series) -> str:
    if bool(row.get("euphoria_price_30d_v16", False)):
        return "euphoria_top"
    if bool(row.get("bear_left_active_v16", False)):
        return "bear_value"
    if bool(row.get("reg_left_active_v16", False)) and bool(row.get("reg_context_ok_v16", False)):
        return "regional_value"
    if bool(row.get("regime_bear_exit_v16", False)):
        return "bear_regime"
    return "neutral"


def _resolve_macro_stage(row: pd.Series, open_pos: Optional[MacroCyclePosition]) -> Tuple[str, str, str]:
    close = float(row["close"])
    ema20 = _clean_float(row.get("ema20"))
    ema50 = _clean_float(row.get("ema50"))
    euph = bool(row.get("euphoria_price_30d_v16", False))
    bear_val = bool(row.get("bear_left_active_v16", False))
    reg_val = bool(row.get("reg_left_active_v16", False)) and bool(row.get("reg_context_ok_v16", False))
    bear_reg = bool(row.get("regime_bear_exit_v16", False))

    if open_pos is not None:
        if euph:
            return (
                "EUPHORIA_WATCH",
                "🔥 牛市過熱區追蹤停利中",
                "已達 Mayer 高檔過熱門檻，持倉等待跌破 EMA20 與 20 日低點再行逃頂鎖盈。",
            )
        return (
            "HOLDING_TREND",
            "🌊 多頭主升浪持倉中",
            "右側確認持有中，抱住趨勢結構；除非觸發過熱逃頂或轉熊防禦，否則不輕易洗出。",
        )

    if euph:
        return (
            "OVERHEATED_FLAT",
            "🔥 高檔過熱派發警戒 (空手)",
            "價格處於 EMA200 過熱延伸帶，空手等待估值消化或結構重置後再進場。",
        )
    if bear_val:
        return (
            "BEAR_VALUE_WAIT",
            "🐻 熊市左側極端超跌價值區",
            "已進入深幅超跌價值區，但尚未滿足 EMA20>EMA50 且均線上揚與突破之右側轉強確認，謹防死貓反彈。",
        )
    if reg_val:
        return (
            "REGIONAL_VALUE_WAIT",
            "💎 牛市回調左側低估觀察區",
            "大週期多頭回踩均線超跌帶，等待站回 EMA50 並突破近 20 日高點時接回主升。",
        )
    if bear_reg or (ema20 is not None and ema50 is not None and close < ema50 and ema20 < ema50):
        return (
            "BEAR_DEFENSE",
            "🛡️ 熊市空頭防禦期 (空手避險)",
            "價格與均線處於空頭排列結構，策略自動空手避開主跌段與反覆震盪。",
        )
    return (
        "NEUTRAL_OBSERVE",
        "⚖️ 趨勢觀察／盤整蓄勢期",
        "暫未出現極端左側超跌與右側大週期突破重合，持續空手觀望等待高盈虧比機會。",
    )


def analyze_macro_cycle(
    symbol: str,
    price_data: Sequence[Dict[str, Any]],
    *,
    timeframe: str = "1d",
    oi_aligned: Optional[Sequence[Dict[str, Any]]] = None,
    funding_settlements: Optional[Sequence[Dict[str, Any]]] = None,
    funding_aligned: Optional[Sequence[Dict[str, Any]]] = None,
    lsur_z_aligned: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Live & chart analysis entry point for `macro_cycle` mode.
    Returns paired markers, EMA20 series, left-side risk zones, and latest stage summary.
    """
    dedup = deduplicate_1d_candles(price_data)
    if not dedup:
        return {
            "markers": [],
            "macro_cycle_zones": [],
            "ema_20": [],
            "macro_cycle_state": None,
        }

    timeframe_warning = (
        None
        if str(timeframe).lower() == "1d"
        else f"大週期策略為 1D 日線模型（當前為 {timeframe}），請切換至「🌊 大週期 (1D)」以符合實證參數"
    )

    df_feat = evaluate_macro_cycle_features_1d(
        dedup,
        oi_aligned=oi_aligned,
        funding_settlements=funding_settlements,
        funding_aligned=funding_aligned,
        lsur_z_aligned=lsur_z_aligned,
    )

    ema_20 = [
        {"time": int(row["time"]), "value": float(row["ema20"])}
        for _, row in df_feat.iterrows()
        if _is_finite(row.get("ema20"))
    ]

    if len(df_feat) < 60:
        last_row = df_feat.iloc[-1]
        zones = [
            {
                "time": int(row["time"]),
                "zone": "neutral",
                "mayer": _clean_float(row.get("mayer"), 3),
                "dd_180_pct": _clean_float(row.get("dd_180_pct"), 4),
                "dd_90_pct": _clean_float(row.get("dd_90_pct"), 4),
            }
            for _, row in df_feat.iterrows()
        ]
        state = {
            "mode": "macro_cycle",
            "version": "v1.6",
            "timeframe": timeframe,
            "timeframe_warning": timeframe_warning,
            "position_state": "FLAT",
            "stage": "WARMUP",
            "stage_label": "⏳ 資料預熱中（需至少 60 根 1D K 線）",
            "stage_description": f"目前僅有 {len(df_feat)} 根去重日線，指標穩定暖機後才會產出大週期訊號。",
            "mayer_multiple": _clean_float(last_row.get("mayer"), 2),
            "euphoria_mayer_threshold": _clean_float(last_row.get("euphoria_mayer_thresh"), 2),
            "dd_180_pct": _clean_float((last_row.get("dd_180_pct") or 0.0) * 100.0, 1) if _is_finite(last_row.get("dd_180_pct")) else None,
            "dd_180_threshold_pct": None,
            "dd_90_pct": _clean_float((last_row.get("dd_90_pct") or 0.0) * 100.0, 1) if _is_finite(last_row.get("dd_90_pct")) else None,
            "rsi_14": _clean_float(last_row.get("rsi14"), 1),
            "ema20": _clean_float(last_row.get("ema20"), 4),
            "ema50": _clean_float(last_row.get("ema50"), 4),
            "ema200": _clean_float(last_row.get("ema200"), 4),
            "ema50_rising": bool(last_row.get("ema50_rising", False)),
            "ema200_rising": bool(last_row.get("ema200_rising", False)),
            "left_zones": {
                "bear_value_active": False,
                "regional_value_active": False,
                "euphoria_overheated_active": False,
                "bear_regime_active": False,
            },
            "active_position": None,
            "derivative_context": _extract_row_deriv_context(df_feat, len(df_feat) - 1),
            "latest_event": None,
        }
        return {
            "markers": [],
            "macro_cycle_zones": zones,
            "ema_20": ema_20,
            "macro_cycle_state": state,
        }

    warmup_bars = min(60, max(40, len(df_feat) // 6))
    sim_res = simulate_macro_cycle_v16(
        symbol=symbol,
        df_feat=df_feat,
        start_idx=warmup_bars,
        funding_rates=None,
        slippage_bps=0.0,
        fee_rate=0.0,
        investment=10000.0,
        include_funding=False,
        force_close_end=False,
    )

    markers = sim_res["markers"]
    open_pos: Optional[MacroCyclePosition] = sim_res["open_position"]

    zones = [
        {
            "time": int(row["time"]),
            "zone": _classify_zone(row) if idx >= warmup_bars else "neutral",
            "mayer": _clean_float(row.get("mayer"), 3),
            "dd_180_pct": _clean_float(row.get("dd_180_pct"), 4),
            "dd_90_pct": _clean_float(row.get("dd_90_pct"), 4),
        }
        for idx, (_, row) in enumerate(df_feat.iterrows())
    ]

    last_idx = len(df_feat) - 1
    last_row = df_feat.iloc[last_idx]
    last_close = float(last_row["close"])
    last_time = int(last_row["time"])
    stage, stage_label, stage_desc = _resolve_macro_stage(last_row, open_pos)

    dd180_val = _clean_float(last_row.get("dd_180_pct"))
    dd180_thresh = _clean_float(last_row.get("dyn_dd_180_thresh"))
    dd90_val = _clean_float(last_row.get("dd_90_pct"))

    active_pos_dict: Optional[Dict[str, Any]] = None
    if open_pos is not None:
        curr_pnl_pct = ((last_close - open_pos.entry_price) / open_pos.entry_price * 100.0) if open_pos.entry_price > 0 else 0.0
        hold_days = max(0, int((last_time - open_pos.entry_time) // DAY_SEC))
        active_pos_dict = {
            "id": open_pos.id,
            "entry_type": open_pos.entry_type,
            "entry_time": int(open_pos.entry_time),
            "entry_price": round(float(open_pos.entry_price), 6),
            "current_price": round(float(last_close), 6),
            "pnl_pct": round(float(curr_pnl_pct), 2),
            "peak_mfe_pct": round(float(open_pos.peak_mfe_pct()), 2),
            "hold_days": hold_days,
            "base_stop": round(float(open_pos.base_stop), 6),
            "base_stop_disabled": bool(open_pos.base_stop_disabled),
            "euphoria_armed": bool(open_pos.highest_since_entry >= open_pos.entry_price * 1.45),
        }

    latest_event = markers[-1] if markers else None

    macro_cycle_state = {
        "mode": "macro_cycle",
        "version": "v1.6",
        "timeframe": timeframe,
        "timeframe_warning": timeframe_warning,
        "position_state": "LONG" if open_pos is not None else "FLAT",
        "stage": stage,
        "stage_label": stage_label,
        "stage_description": stage_desc,
        "mayer_multiple": _clean_float(last_row.get("mayer"), 2),
        "euphoria_mayer_threshold": _clean_float(last_row.get("euphoria_mayer_thresh"), 2),
        "dd_180_pct": round(dd180_val * 100.0, 1) if dd180_val is not None else None,
        "dd_180_threshold_pct": round(dd180_thresh * 100.0, 1) if dd180_thresh is not None else None,
        "dd_90_pct": round(dd90_val * 100.0, 1) if dd90_val is not None else None,
        "rsi_14": _clean_float(last_row.get("rsi14"), 1),
        "ema20": _clean_float(last_row.get("ema20"), 4),
        "ema50": _clean_float(last_row.get("ema50"), 4),
        "ema200": _clean_float(last_row.get("ema200"), 4),
        "ema50_rising": bool(last_row.get("ema50_rising", False)),
        "ema200_rising": bool(last_row.get("ema200_rising", False)),
        "left_zones": {
            "bear_value_active": bool(last_row.get("bear_left_active_v16", False)),
            "regional_value_active": bool(last_row.get("reg_left_active_v16", False)) and bool(last_row.get("reg_context_ok_v16", False)),
            "euphoria_overheated_active": bool(last_row.get("euphoria_price_30d_v16", False)),
            "bear_regime_active": bool(last_row.get("regime_bear_exit_v16", False)),
        },
        "active_position": active_pos_dict,
        "derivative_context": _extract_row_deriv_context(df_feat, last_idx),
        "latest_event": latest_event,
    }

    return {
        "markers": markers,
        "macro_cycle_zones": zones,
        "ema_20": ema_20,
        "macro_cycle_state": macro_cycle_state,
    }
