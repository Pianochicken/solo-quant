"""
Phase 2 Production Integration & Regression Tests for Dual-Mode Macro Cycle Engine:
  1. Exact parity between api/core/macro_cycle.py + api/quant/macro_cycle_backtester.py
     and scripts/run_macro_cycle_v16_experiments.py (Cycle_P_v16_1d).
  2. Strict causal prefix invariance (0..k == 0..N at indices 0..k-1) + Pandas CoW safety AST check.
  3. _get_market_data_impl & run_signal_backtest dual-mode branching, empty history, invalid strategy_mode.
  4. scan_macro_cycle_and_notify closed-1d gating, deduplication, toggle checks & format_macro_cycle_message.
  5. DataFetcher full-history exhaustion guard (prevents pagination storm on limit=1800).
  6. Daily candlestick PNG chart generation with custom hex colors & daily X-axis ticks.
"""

from __future__ import annotations

import ast
import asyncio
import json
import math
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import scripts.run_macro_cycle_v16_experiments as v16
from api.core.fetcher import DataFetcher
from api.core.macro_cycle import (
    analyze_macro_cycle,
    deduplicate_1d_candles,
    evaluate_macro_cycle_features_1d,
    simulate_macro_cycle_v16,
)
from api.core.notifier import format_macro_cycle_message
from api.core import signal_scanner
from api.core.utils.chart import generate_candlestick_chart
from api.db.database import Base
from api.db.models import MarketDataPoint
from api.quant.macro_cycle_backtester import run_macro_cycle_backtest


def _make_synthetic_multi_cycle_candles(start_ts: int = 1653177600) -> list[dict]:
    """
    Build a deterministic 520-day multi-cycle 1D OHLCV sequence with:
      - Bear bottom (-50% crash + RSI <= 30) -> EMA20 > EMA50 breakout (Path A)
      - Strong bull euphoria (+80% above EMA200, RSI >= 76) -> distribution break (EUPHORIA_TOP_V16)
      - Bear rollover below EMA50 & 30d low (REGIME_BEAR_EXIT_V16)
    """
    closes: list[float] = []
    # Phase 0: Downtrend into deep bear bottom (days 0..179)
    for i in range(180):
        c = 120.0 * (0.9945 ** i)
        closes.append(c)
    # Flush dip for RSI <= 30 (days 180..194)
    c_floor = closes[-1]
    for i in range(15):
        closes.append(c_floor * (0.978 ** (i + 1)))
    # Base & secular Stage-2 trend reclaim (days 195..319)
    c_base = closes[-1]
    for i in range(125):
        c_base *= 1.0075
        closes.append(c_base)
    # Euphoria spike well past 1.6x EMA200 & RSI > 78 (days 320..354)
    for i in range(35):
        c_base *= 1.022
        closes.append(c_base)
    # Distribution breakdown below EMA20 & 20d/30d low (days 355..519)
    for i in range(165):
        c_base *= 0.991
        closes.append(c_base)

    candles = []
    prev_c = closes[0]
    for i, c in enumerate(closes):
        o = prev_c if i > 0 else c
        h = max(o, c) * 1.018
        l = min(o, c) * 0.982
        candles.append({
            "time": start_ts + i * 86400,
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": 5000.0 + (i % 17) * 200.0,
        })
        prev_c = c
    return candles


# ─── 1. Exact Parity Against Phase 1.6 Research Script ────────────────────────

def test_macro_cycle_parity_with_phase16_prototype():
    candles = _make_synthetic_multi_cycle_candles()
    df_proto_in = pd.DataFrame([
        {
            **c,
            "known_ts": c["time"] + 86400,
            "oi_usd": float("nan"),
            "coin_oi": float("nan"),
            "taker_ratio": float("nan"),
            "lsur_z_90d": float("nan"),
            "funding_daily": float("nan"),
            "has_deriv": False,
        }
        for c in candles
    ])
    df_proto_feat = v16.evaluate_cycle_v16_features_1d(df_proto_in)
    warmup = min(60, max(40, len(df_proto_feat) // 6))
    proto_res = v16.simulate_cycle_v16_strategy(
        "BTC/USDT",
        df_proto_feat,
        "Cycle_P_v16_1d",
        start_idx=warmup,
        slippage_bps=5.0,
        fee_rate=0.0005,
        investment=10000.0,
        include_funding=False,
    )

    df_prod_feat = evaluate_macro_cycle_features_1d(candles)
    prod_res = simulate_macro_cycle_v16(
        "BTC/USDT",
        df_prod_feat,
        start_idx=warmup,
        slippage_bps=5.0,
        fee_rate=0.0005,
        investment=10000.0,
        include_funding=False,
        force_close_end=True,
    )

    proto_pos = proto_res["closed_positions"]
    prod_pos = prod_res["closed_positions"]
    assert len(prod_pos) == len(proto_pos) and len(prod_pos) >= 1

    for p_exp, p_act in zip(proto_pos, prod_pos):
        assert p_act.entry_time == p_exp.entry_time
        assert p_act.exit_time == p_exp.exit_time
        assert p_act.entry_type == p_exp.entry_type
        exp_reason = "backtest_end" if p_exp.exit_reason == "BACKTEST_END" else p_exp.exit_reason
        assert p_act.exit_reason == exp_reason
        assert p_act.realized_pnl == pytest.approx(p_exp.realized_pnl, rel=1e-6, abs=1e-4)

    assert prod_res["metrics"]["final_balance"] == pytest.approx(
        proto_res["metrics"]["final_balance"], rel=1e-6, abs=1e-3
    )

    bt_res = run_macro_cycle_backtest(
        "BTC/USDT",
        candles,
        duration_days=1600,
        investment=10000.0,
        fee_rate=0.0005,
        slippage_bps=5.0,
        include_funding=False,
    )
    assert bt_res["strategy_mode"] == "macro_cycle"
    assert bt_res["metrics"]["final_balance"] == pytest.approx(prod_res["metrics"]["final_balance"], abs=0.05)
    assert "buy_and_hold_return_pct" in bt_res["metrics"]
    assert "cagr_pct" in bt_res["metrics"]
    assert "mar_ratio" in bt_res["metrics"]
    assert len(bt_res["positions"]) == len(prod_pos)


# ─── 2. Strict Causal Prefix Invariance & AST Hygiene ─────────────────────────

def test_macro_cycle_zero_lookahead_prefix_invariance():
    candles = _make_synthetic_multi_cycle_candles()
    df_full = evaluate_macro_cycle_features_1d(candles)
    df_pref = evaluate_macro_cycle_features_1d(candles[:320])
    for col in ("ema20", "ema50", "ema200", "mayer", "path_a_v16_ok", "path_b_v16_ok", "path_c_v16_ok", "euphoria_price_30d_v16", "regime_bear_exit_v16"):
        pd.testing.assert_series_equal(
            df_full[col].iloc[:320].reset_index(drop=True),
            df_pref[col].reset_index(drop=True),
            check_names=False,
        )

    full = analyze_macro_cycle("BTC/USDT", candles, timeframe="1d")
    cut = 380  # >= 360 so warmup_bars == 60 identically on both slices
    cutoff_ts = candles[cut - 1]["time"]
    pref = analyze_macro_cycle("BTC/USDT", candles[:cut], timeframe="1d")

    assert [m for m in full["markers"] if m["time"] <= cutoff_ts] == [
        m for m in pref["markers"] if m["time"] <= cutoff_ts
    ]
    assert [z for z in full["macro_cycle_zones"] if z["time"] <= cutoff_ts] == [
        z for z in pref["macro_cycle_zones"] if z["time"] <= cutoff_ts
    ]


def test_production_macro_modules_no_bfill_or_inplace():
    root = Path(__file__).resolve().parent.parent
    for rel in ("core/macro_cycle.py", "quant/macro_cycle_backtester.py"):
        src = (root / rel).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr != "bfill", f"Forbidden .bfill() in {rel}"
                for kw in node.keywords:
                    if kw.arg == "inplace" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        raise AssertionError(f"Forbidden inplace=True in {rel}")


# ─── 3. FastAPI Dual-Mode /market & /quant/signal-backtest ────────────────────

def test_api_dual_mode_market_and_backtest():
    fastapi = pytest.importorskip("fastapi")
    import api.main as api_main

    candles = _make_synthetic_multi_cycle_candles()
    oi_rows = [{"time": c["time"], "value": 1e8 * (1.0 + 0.001 * i)} for i, c in enumerate(candles)]
    mock_fetcher = MagicMock()
    mock_fetcher.fetch_market_data.return_value = {
        "price": candles,
        "funding": [{"time": c["time"], "value": 0.01} for c in candles],
        "funding_settlements": [{"time": c["time"] + 28800, "funding_rate": 0.0001} for c in candles],
    }
    mock_fetcher.fetch_open_interest.return_value = oi_rows
    mock_fetcher.fetch_long_short_ratio.return_value = [{"time": c["time"], "value": 1.4} for c in candles]
    mock_fetcher.fetch_top_trader_position_ratio.return_value = [{"time": c["time"], "value": 1.8} for c in candles]
    mock_fetcher.fetch_taker_volume.return_value = [
        {"time": c["time"], "buy_vol": 600.0, "sell_vol": 400.0} for c in candles
    ]
    mock_fetcher.fetch_order_book_depth.return_value = {"bids": [], "asks": [], "timestamp": 0}
    mock_fetcher.get_exchange_breakdown.return_value = {"binance": 50.0, "okx": 50.0, "total": 100.0}

    with patch.object(api_main, "get_fetcher", return_value=mock_fetcher):
        # 1. Macro Cycle mode via _get_market_data_impl
        res_mc = api_main._get_market_data_impl(
            "SOL-USDT",
            timeframe="1d",
            limit=1800,
            include_orderbook=False,
            include_breakdown=False,
            strategy_mode="macro_cycle",
        )
        json.dumps(res_mc, allow_nan=False)
        ind_mc = res_mc["indicators"]
        assert ind_mc["strategy_mode"] == "macro_cycle"
        assert isinstance(ind_mc["macro_cycle_state"], dict)
        assert ind_mc["macro_cycle_state"]["version"] == "v1.6"
        assert ind_mc["macro_cycle_state"]["timeframe_warning"] is None
        assert len(ind_mc["ema_20"]) == len(candles)
        assert len(ind_mc["macro_cycle_zones"]) == len(candles)
        assert len(ind_mc["lsur_markers"]) >= 1

        # 2. Invalid strategy_mode rejected cleanly
        with pytest.raises(fastapi.HTTPException) as exc_bad:
            api_main._get_market_data_impl("BTC-USDT", timeframe="1d", strategy_mode="invalid_mode")
        assert exc_bad.value.status_code == 400

        # 3. Backtest endpoint in macro_cycle mode
        bt_out = api_main.run_signal_backtest(
            api_main.SignalBacktestParams(
                symbol="SOL/USDT",
                timeframe="1d",
                duration_days=1600,
                strategy_mode="macro_cycle",
            )
        )
        json.dumps(bt_out, allow_nan=False)
        assert bt_out["strategy_mode"] == "macro_cycle"
        assert bt_out["metrics"]["total_trades"] >= 1
        assert "buy_and_hold_return_pct" in bt_out["metrics"]

        # 4. Empty price history still returns clean JSON & 404 in backtest
        mock_fetcher.fetch_market_data.return_value = {"price": [], "funding": [], "funding_settlements": []}
        res_empty = api_main._get_market_data_impl(
            "BTC-USDT", timeframe="1d", limit=1800, strategy_mode="macro_cycle"
        )
        json.dumps(res_empty, allow_nan=False)
        assert res_empty["indicators"]["strategy_mode"] == "macro_cycle"
        assert res_empty["indicators"]["macro_cycle_state"] is None
        assert res_empty["indicators"]["macro_cycle_zones"] == []
        assert res_empty["indicators"]["ema_20"] == []


# ─── 4. Daily Macro Scanner & Telegram Formatter ──────────────────────────────

def test_scan_macro_cycle_closed_candle_gating_and_dedup():
    closed_bar_t = 1_760_000_000
    unclosed_bar_t = closed_bar_t + 86400
    now_sec = unclosed_bar_t + 3600  # 1 hour into current open 1D candle

    price_bars = [
        {"time": closed_bar_t - 86400, "open": 95.0, "high": 98.0, "low": 94.0, "close": 96.0, "volume": 100.0},
        {"time": closed_bar_t, "open": 96.0, "high": 106.0, "low": 95.0, "close": 105.0, "volume": 200.0},
        {"time": unclosed_bar_t, "open": 105.0, "high": 115.0, "low": 104.0, "close": 112.0, "volume": 150.0},
    ]

    def fake_market_data(symbol, timeframe="1d", **kwargs):
        assert timeframe == "1d"
        assert kwargs.get("strategy_mode") == "macro_cycle"
        assert kwargs.get("include_orderbook") is False
        assert kwargs.get("include_breakdown") is False
        assert kwargs.get("allow_live_btc_cache") is False
        markers = [
            {
                "time": closed_bar_t,
                "direction": "bullish",
                "cycle_event": "BEAR_BOTTOM_V16",
                "price": 105.0,
                "base_stop": 92.5,
                "mayer": 1.05,
                "deriv_context": {
                    "has_deriv": True,
                    "coin_oi_dd_60d": -25.4,
                    "coin_oi_pct_180d": 15.0,
                    "fr_7d_mean_pct": -0.0085,
                    "lsur_z_90d": -1.42,
                    "summary": "洗盤充分",
                },
            },
            {
                "time": unclosed_bar_t,
                "direction": "bearish",
                "cycle_event": "EUPHORIA_TOP_V16",
                "price": 112.0,
                "mayer": 1.95,
            },
        ]
        return {
            "data": {"price": price_bars},
            "indicators": {
                "lsur_markers": markers,
                "macro_cycle_state": {
                    "mayer_multiple": 1.05,
                    "dd_180_pct": 42.3,
                    "ema20": 102.0,
                    "ema50": 98.0,
                    "ema200": 95.0,
                },
            },
        }

    sent_payloads = []

    async def fake_send_chart(text, **kwargs):
        sent_payloads.append((text, kwargs.get("timeframe")))
        return True

    signal_scanner._notifications_enabled = True
    signal_scanner._enable_macro_cycle_alerts = True
    signal_scanner._monitored_symbols = ["BTC/USDT", "SOL/USDT"]
    signal_scanner._notified_macro_cycle_keys.clear()

    with patch("api.core.signal_scanner.send_signal_with_chart", side_effect=fake_send_chart), \
         patch("api.core.signal_scanner.time.time", return_value=float(now_sec)), \
         patch("api.core.signal_scanner.asyncio.sleep", return_value=None):
        asyncio.run(signal_scanner.scan_macro_cycle_and_notify(market_data_fn=fake_market_data))
        # Second run on same closed candle must deduplicate cleanly (0 extra alerts)
        asyncio.run(signal_scanner.scan_macro_cycle_and_notify(market_data_fn=fake_market_data))

        # Disable toggle -> 0 extra alerts
        signal_scanner._notified_macro_cycle_keys.clear()
        signal_scanner._enable_macro_cycle_alerts = False
        asyncio.run(signal_scanner.scan_macro_cycle_and_notify(market_data_fn=fake_market_data))

    assert len(sent_payloads) == 2
    for msg, tf in sent_payloads:
        assert tf == "1d"
        assert "BEAR_BOTTOM_V16" in msg
        assert "EUPHORIA_TOP_V16" not in msg
        assert "+25%" in msg
        assert "Base Stop" in msg
        assert "左側衍生品輔助佐證" in msg


def test_format_macro_cycle_message_exit_details():
    exit_msg = format_macro_cycle_message(
        {
            "time": 1_760_000_000,
            "direction": "bearish",
            "cycle_event": "EUPHORIA_TOP_V16",
            "mayer": 1.88,
            "realized_pnl_pct": 142.5,
            "peak_mfe_pct": 185.0,
            "hold_days": 165.0,
            "deriv_context": {
                "has_deriv": True,
                "coin_oi_dd_60d": -2.0,
                "coin_oi_pct_180d": 91.0,
                "fr_7d_mean_pct": 0.032,
                "lsur_z_90d": 1.55,
                "summary": "過熱派發",
            },
        },
        "SOL/USDT",
        153.0334,
        macro_state={"dd_180_pct": 12.0, "ema20": 160.0, "ema50": 140.0, "ema200": 81.4},
    )
    assert "EUPHORIA_TOP_V16" in exit_msg
    assert "+142.50%" in exit_msg
    assert "+185.00%" in exit_msg
    assert "165 天" in exit_msg
    assert "過熱逃頂" in exit_msg


# ─── 5. Fetcher Full-History Exhaustion Guard ─────────────────────────────────

def test_fetcher_full_history_exhaustion_guard_skips_repeat_pagination():
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

        now_utc = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        base_ts = int(now_utc.timestamp()) - 201 * 86400
        with TestSession() as db:
            for i in range(200):
                db.add(MarketDataPoint(
                    exchange="okx",
                    symbol="HYPE/USDT",
                    timeframe="1d",
                    timestamp=datetime.fromtimestamp(base_ts + i * 86400, tz=timezone.utc),
                    open=20.0, high=21.0, low=19.0, close=20.5, volume=1000.0,
                ))
            db.commit()

        with patch("api.core.fetcher.SessionLocal", fake_session):
            fetcher = DataFetcher()
            fetcher.exchange.markets = {"HYPE/USDT:USDT": {}}
            ohlcv_calls = []

            def fake_fetch_ohlcv(sym, timeframe="1d", limit=300, params=None):
                ohlcv_calls.append(limit)
                return []  # Exchange has no older listing history beyond 200 DB bars

            fetcher.exchange.fetch_ohlcv = fake_fetch_ohlcv
            fetcher.exchange.fetch_funding_rate_history = MagicMock(return_value=[])

            # 1st call: tries full history fetch (limit=300 per page capped) because 200 < 1800
            fetcher.fetch_market_data("HYPE/USDT", "1d", limit=1800)
            # 2nd call: history already exhausted -> falls back to incremental missed_candles (= 10 << 300)
            fetcher.fetch_market_data("HYPE/USDT", "1d", limit=1800)

        assert len(ohlcv_calls) == 2
        assert ohlcv_calls[0] == 300
        assert ohlcv_calls[1] == 10
    finally:
        engine.dispose()


# ─── 6. Chart PNG Generation for 1D Daily Mode & Custom Hex Colors ────────────

def test_generate_candlestick_chart_daily_custom_hex(tmp_path):
    base_ts = 1_750_000_000
    rows = []
    for i in range(60):
        t = datetime.fromtimestamp(base_ts + i * 86400, tz=timezone.utc)
        rows.append({"Date": t, "Open": 100.0 + i, "High": 102.0 + i, "Low": 99.0 + i, "Close": 101.0 + i})
    df = pd.DataFrame(rows)
    out_file = tmp_path / "macro_1d.png"
    res_path = generate_candlestick_chart(
        "BTC/USDT",
        df,
        [
            {"time": rows[20]["Date"], "direction": "buy", "color": "#10b981"},
            {"time": rows[50]["Date"], "direction": "sell", "color": "#f59e0b"},
        ],
        str(out_file),
        timeframe="1d",
        tz_label="(UTC+8)",
    )
    assert Path(res_path).exists()
    assert Path(res_path).stat().st_size > 1024
