"""
Macro Cycle Strategy Backtester Adapter (Phase 2).

Executes the Phase 1.6 Cycle_P_v16_1d full-cycle engine over deduplicated 1D candles
and returns a SignalBacktestResult-compatible payload alongside Buy & Hold benchmarks.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from api.core.macro_cycle import (
    DAY_SEC,
    DEFAULT_FEE_RATE,
    LONG_NOTIONAL_PCT,
    MacroCyclePosition,
    _apply_slippage,
    _classify_zone,
    _clean_float,
    _prep_funding_events,
    compute_cycle_portfolio_metrics,
    deduplicate_1d_candles,
    evaluate_macro_cycle_features_1d,
    simulate_macro_cycle_v16,
)


def _simulate_buy_and_hold_benchmark(
    symbol: str,
    candles: Sequence[Dict[str, Any]],
    *,
    funding_rates: Optional[Sequence[Dict[str, Any]]] = None,
    slippage_bps: float = 5.0,
    fee_rate: float = DEFAULT_FEE_RATE,
    investment: float = 10000.0,
    include_funding: bool = True,
) -> Dict[str, Any]:
    """Benchmark: 0.95x notional buy & hold over the exact same window with fees + funding."""
    if not candles:
        return {"total_return_pct": 0.0, "max_drawdown_pct": 0.0}

    funding_events = _prep_funding_events(funding_rates)
    balance = float(investment)
    c0 = candles[0]
    t0 = int(c0["time"])
    close0 = float(c0["close"])
    entry_price = _apply_slippage(close0, "long", is_entry=True, slippage_bps=slippage_bps)
    notional = balance * LONG_NOTIONAL_PCT
    size = notional / entry_price if entry_price > 0 else 0.0
    cost = size * entry_price
    entry_fee = cost * fee_rate
    balance -= (cost + entry_fee)

    pos = MacroCyclePosition(
        symbol=symbol,
        side="long",
        entry_price=entry_price,
        entry_time=t0,
        entry_idx=0,
        entry_type="BUY_AND_HOLD",
        size=size,
        atr_entry=0.0,
        base_stop=0.0,
    )
    pos.fees_paid = entry_fee

    f_idx = 0
    while f_idx < len(funding_events) and funding_events[f_idx]["time"] <= t0:
        f_idx += 1

    equity_curve: List[Dict[str, Any]] = [{"time": t0, "value": balance + pos.size * close0}]
    n = len(candles)

    for i in range(1, n):
        c = candles[i]
        ti = int(c["time"])
        hi = float(c["high"])
        lo = float(c["low"])
        ci = float(c["close"])
        next_t = int(candles[i + 1]["time"]) if i + 1 < n else (ti + DAY_SEC)

        if hi > pos.highest_since_entry:
            pos.highest_since_entry = hi
        if lo < pos.lowest_since_entry:
            pos.lowest_since_entry = lo

        while f_idx < len(funding_events) and funding_events[f_idx]["time"] <= next_t:
            fs = funding_events[f_idx]
            if include_funding and fs["time"] > ti:
                f_pnl = -(pos.size * ci) * fs["funding_rate"]
                balance += f_pnl
                pos.funding_pnl += f_pnl
            f_idx += 1

        equity_curve.append({"time": ti, "value": balance + pos.size * ci})

    last = candles[-1]
    last_close = float(last["close"])
    raw_pnl = (last_close - pos.entry_price) * pos.size
    exit_fee = last_close * pos.size * fee_rate
    balance += pos.cost + raw_pnl - exit_fee
    if equity_curve:
        equity_curve[-1]["value"] = balance

    metrics = compute_cycle_portfolio_metrics(
        equity_curve,
        [pos],
        investment=investment,
        final_balance=balance,
    )
    return {
        "total_return_pct": metrics["pnl_percent"],
        "max_drawdown_pct": metrics["max_drawdown_pct"],
    }


def run_macro_cycle_backtest(
    symbol: str,
    price_history: Sequence[Dict[str, Any]],
    *,
    duration_days: int = 1600,
    investment: float = 10000.0,
    fee_rate: float = DEFAULT_FEE_RATE,
    slippage_bps: float = 5.0,
    include_funding: bool = True,
    funding_settlements: Optional[Sequence[Dict[str, Any]]] = None,
    oi_aligned: Optional[Sequence[Dict[str, Any]]] = None,
    funding_aligned: Optional[Sequence[Dict[str, Any]]] = None,
    lsur_z_aligned: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Run the Phase 1.6 Macro Cycle backtest over 1D OHLCV history and return a
    SignalBacktestResult-compatible dictionary.
    """
    dedup = deduplicate_1d_candles(price_history)
    if len(dedup) < 80:
        raise ValueError(f"Insufficient 1D candles for Macro Cycle backtest ({len(dedup)} < 80)")

    df_feat = evaluate_macro_cycle_features_1d(
        dedup,
        oi_aligned=oi_aligned,
        funding_settlements=funding_settlements,
        funding_aligned=funding_aligned,
        lsur_z_aligned=lsur_z_aligned,
    )

    warmup_bars = min(60, max(40, len(df_feat) // 6))
    times = df_feat["time"].to_numpy(dtype=int)
    end_ts = int(times[-1])
    if duration_days >= 1500:
        start_idx = warmup_bars
    else:
        target_start = end_ts - int(duration_days) * DAY_SEC
        if target_start <= int(times[warmup_bars]):
            start_idx = warmup_bars
        else:
            start_idx = next(
                (i for i in range(warmup_bars, len(times)) if int(times[i]) >= target_start),
                len(times) - 1,
            )

    eval_start_sec = int(times[start_idx])
    slice_funding = [
        f for f in _prep_funding_events(funding_settlements)
        if eval_start_sec - 8 * 3600 <= int(f["time"]) <= (end_ts + DAY_SEC)
    ]

    sim_res = simulate_macro_cycle_v16(
        symbol=symbol,
        df_feat=df_feat,
        start_idx=start_idx,
        funding_rates=slice_funding,
        slippage_bps=slippage_bps,
        fee_rate=fee_rate,
        investment=investment,
        include_funding=include_funding,
        force_close_end=True,
    )

    eval_price = [
        {
            "time": int(row["time"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        }
        for _, row in df_feat.iloc[start_idx:].iterrows()
    ]

    bh = _simulate_buy_and_hold_benchmark(
        symbol,
        eval_price,
        funding_rates=slice_funding,
        slippage_bps=slippage_bps,
        fee_rate=fee_rate,
        investment=investment,
        include_funding=include_funding,
    )

    metrics = dict(sim_res["metrics"])
    metrics["buy_and_hold_return_pct"] = bh["total_return_pct"]
    metrics["buy_and_hold_max_dd_pct"] = bh["max_drawdown_pct"]

    zones = [
        {
            "time": int(row["time"]),
            "zone": _classify_zone(row),
            "mayer": _clean_float(row.get("mayer"), 3),
            "dd_180_pct": _clean_float(row.get("dd_180_pct"), 4),
            "dd_90_pct": _clean_float(row.get("dd_90_pct"), 4),
        }
        for _, row in df_feat.iloc[start_idx:].iterrows()
    ]

    markers = [m for m in sim_res["markers"] if m["time"] >= eval_start_sec]

    return {
        "strategy_mode": "macro_cycle",
        "metrics": metrics,
        "equity_curve": sim_res["equity_curve"],
        "trades": sim_res["trades"],
        "signals_used": markers,
        "positions": [p.to_dict() for p in sim_res["closed_positions"]],
        "price_data": eval_price,
        "macro_cycle_zones": zones,
        "debug_history_len": len(df_feat),
        "debug_markers_len": len(markers),
    }
