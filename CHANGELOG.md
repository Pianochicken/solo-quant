# Solo-Quant Changelog

All notable changes to the Solo-Quant project will be documented in this file.
This file serves as a historical record to keep `AI_HANDOFF.md` clean and focused on current state and next steps.

## [2026-10-28] v0.5.0 - Frontend Signal Terminal Refactoring & Macro Alignment
- **Dual-Exchange Open Interest & Liquidity Breakdown Fix (`api/core/fetcher.py` & `api/main.py`)**:
  - Implemented lightweight `get_exchange_breakdown()` with 60s in-memory cache, accurately parsing Binance USD values (`openInterestValue`, `sumOpenInterestValue`, or `amount * price`) and OKX USD values (`oiUsd`, `openInterestValue`, or `oiCcy * price`).
  - Fixed OKX daily OI fetching bug where `(ts // 1000) % 86400 != 0` (57600 at 16:00 UTC) dropped 100% of OKX daily records.
  - Enforced `limit=min(per_page, 100)` for OKX Rubik API calls with graceful fallback (`okx: 0.0`) for unlisted swap contracts.
  - Normalized DB query logic for `1d` to search both `'1d'` and `'1D'`, resolving empty DB cache hits.
  - Upgraded smooth past/future boundary scaling between Binance and OKX to guarantee zero cliff jump at the 100-bar boundary, completely eliminating false `CAP` signals.
  - Verified across `BTC-USDT`, `ETH-USDT`, and `SOL-USDT` on `1h`, `4h`, `1d` (Binance ~74-79%, OKX ~21-26%).
- **Frontend Terminal Pure Refactoring (`web/app/page.tsx`)**:
  - Updated header subtitle to `CRYPTO MACRO & SIGNAL TERMINAL`.
  - Removed legacy `GridPanel` and `HistoryPanel` along with simulated local matching engine states, eliminating unused black space beneath the chart.
  - Added **Recent Signals Radar** in the right column beneath `SentimentPanel`: lists latest 10 signals with formatted UTC timestamps (`MM/DD HH:mm`), strategy type badges (`🚀 BREAKOUT / BREAKDOWN`, `⚡ STRUCTURE ▲/▼`, `🟢 BUY / 🔴 SELL`), asset-precision trigger prices (`getPricePrecision`), and monospace indicator reason pills.
  - **Unified Terminal Loader**: Replaced fragmented multi-block loaders and artificial 600ms delays with a single full-workspace dark loading screen (radar pulse animation & asset/timeframe pill). On data arrival, Chart, SentimentPanel, and Recent Signals hydrate atomically without flickering or empty states.
- **4H MTF Confluence & Sentiment Panel (`web/components/SentimentPanel.tsx`)**:
  - Integrated 4H MTF regime status badge (`mtf_4h_regime`) into the `Market Regime` header right side (`4H: Trending ↑` emerald, `4H: Trending ↓` red, `4H: Ranging` amber), providing instant macro trend awareness.
  - Gracefully formatted single-source exchange liquidity when OKX or Binance has 0 volume (`—` instead of `0.0%`).
- **Advanced Chart Polish (`web/components/AdvancedChart.tsx`)**:
  - Added `attributionLogo: false` in `commonOptions.layout` to eliminate TradingView logo overlap with the 7th subchart (`Market Regime`).
  - Expanded main price chart height from 400px to 460px (`h-[460px]`).
- **Multi-Year Rolling Evaluation & IndicatorEngine v8**:
  - `scripts/debug/evaluate_signal_quality.py`: Evaluated multi-year rolling windows across Bull, Bear, and Ranging regimes for BTC/ETH, confirming Full Macro E-Ratio > 1.15 across all horizons (1h: 1.18, 4h: 1.83, 1d: 1.15).
  - Maintained Full Macro defaults (`enableProtection: true`, `enableMtfFilter: true`) across both dashboard and backtester.

## [2026-10-26] v0.4.0 - Full Macro Cross-Regime Architecture & Precision Tuning
- **Signal Quality & Multi-Year Diagnostic Engine**:
  - `scripts/debug/evaluate_signal_quality.py`: Created an event-study rolling-window diagnostic script across multi-year data (1d 1000 bars, 4h 2200 bars, 1h 4320 bars) for core assets (BTC & ETH), producing scientific Tables A through D across Bull, Bear, and Ranging market regimes.
- **Breakout & Structure Precision Tuning (`api/core/indicators.py`)**:
  - **1h Breakout Re-architecture**: Dynamic Donchian period (48 bars for 15m/1h, 20 bars for 4h/1d); candle body expansion confirmation; required OI expansion (`oi_expanding = oi_chg_pct > 0`) for 15m/1h breakouts.
  - **Strict Anti-Trend Iron Laws**:
    - Unconditional `no_short` blocking: Removed `has_bear_structure` exemption from `no_short`, completely preventing counter-trend shorting during bull regimes.
    - 1h/15m Bull Structural Guard: Monitored 24-bar EMA200 slope (`ema200_rising`) and 4h MTF regime to block counter-trend shorts in bull grind.
    - Prohibited counter-trend Breakdowns when `price_close > ema200` or 4h trending up, and counter-trend Breakouts when `price_close < ema200` and 4h trending down.
    - Restricted `has_bull_structure` exemption from `no_long` strictly to `4h` with `'CAP↑'` true capitulation and `bull_score >= bull_threshold + 1.5`, restoring 1d Structure win rate to 73.3% and E-Ratio to 1.59.
- **Risk Management & Dynamic TP/SL (`api/quant/position.py` & `api/quant/signal_backtester.py`)**:
  - **Breakeven Floor**: Added guaranteed floor to `Position.update()` when trailing stop activates (Long `new_trail >= entry_price * 1.002`, Short `new_trail <= entry_price * 0.998`), eliminating loss-making exits after profit activation.
  - **ATR(14) Precomputation**: Precalculated 14-period Wilder's ATR across all bars.
  - **Structure & Breakout TP Expansion**: Dynamic 1.35x multiplier applied to `take_profit_pct` for Structure and Breakout trades.
- **Multi-Timeframe Telegram Scanner (`api/core/signal_scanner.py` & `api/core/notifier.py`)**:
  - Upgraded scanner to monitor `MONITORED_TIMEFRAMES = ["1h", "4h"]`, scanning 4h at `:00` UTC when `hour % 4 == 0` with 8-hour tracking window.
  - Defaulted to Full Macro mode (`enable_protection=True`, `enable_mtf_filter=True`).
  - Added timeframe identifier to Telegram alerts (e.g. `[BTC/USDT 4h]`).
- **Frontend Defaults & Presets Alignment**:
  - `web/app/page.tsx`: Initialized `signalConfig` with `enableProtection: true` and `enableMtfFilter: true`.
  - `web/app/backtest/page.tsx`: Defaulted `enableProtection` and `enableMtfFilter` to `true`. Updated quick presets to match Table D empirical metrics: 保守回歸 (`SL: 1.8%`, `TP: 2.8%`, `Trail: 0.8%`, `Act: 1.2%`) and 順勢突破 (4h/1d) (`SL: 3.0%`, `TP: 6.0%`, `Trail: 1.5%`, `Act: 2.0%`).
- **Golden Balance Calibration & Native Trend Pullback (`api/core/indicators.py` & `api/main.py`)**:
  - **Dynamic Donchian Period**: Enforced `period = 48` for `15m/1h` and `period = 20` for `4h/1d` in `api/main.py`.
  - **Native EMA50 Trend Pullback**: Replaced external pullback track with native `EMA支撐↑` (uptrend pullback to EMA50 within `-1.2% ~ +0.35%` holding above EMA200) and `EMA壓力↓` (downtrend bounce to EMA50 within `-0.35% ~ +1.2%` under EMA200), driving 4h Pure Reversion to 71.4% win rate and 3.49 E-Ratio.
  - **Restored Version 3 Strict Breakout (🚀)**: Required `regime == 'trending'`, strict first-bar Donchian cross, volume & momentum confirmation, OI expansion for 15m/1h, and `COOLDOWN * 2`, bringing 1h Breakout back to high-conviction quality.
  - **Tightened Extreme Inflection Exemption**: Exemptions to `no_long / no_short` strictly require 4-fold extreme resonance (`Structure` + `RSI < 28 / > 72` + `BB < 0.05 / > 0.95` + `score >= threshold + 1.5`).
  - **All-Timeframe Golden Balance**: Full Macro E-Ratio > 1.15 across all horizons (1h: 1.18, 4h: 1.83, 1d: 1.15) with balanced signal density (1h: 164, 4h: 72, 1d: 76).
- **Tests**: 33/33 unit tests passing (`api/tests/test_signal_strategy.py`).

## [2026-10-25] v0.3.0 - IndicatorEngine v8 (Macro & Inflection Precision Upgrade)
- **Data Ingestion & Aggregation (Phase A)**:
  - `scripts/data/ingest_cvd.py`: Standardized timeframe to `'1d'` (was uppercase `'1D'`).
  - `api/core/fetcher.py`:
    - Fixed 4h Taker Volume collapse: dynamically scaled `query_limit = limit * tf_ratio` based on timeframe duration, ensuring 4h queries return a full 1000 warmup candles.
    - Fixed cross-exchange Open Interest aggregation: merged OKX and Binance OI on timestamp with `ffill(limit=2)` and smooth ratio scaling across boundaries, eliminating false OI crashes/CAP signals caused by Binance 30-day history cutoffs.
    - Standardized long/short account ratio fetching to align retail contract accounts across exchanges.
- **Backtest Precision & Look-Ahead Removal (Phase A)**:
  - `api/quant/signal_backtester.py`:
    - Fixed intra-bar trailing stop look-ahead bias: `_process_exits()` now evaluates `pos.check_exit()` strictly *before* `pos.update()`, evaluating trailing stops against previous-bar ratchets.
    - Fixed position sizing: `max_affordable` divides by `max_positions` (`current_equity * 0.95 / max_positions`), preventing the first trade from locking 95% equity.
    - Dynamic annualization factor for Sharpe ratio using detected candle interval.
    - Added Forward Return MFE/MAE tracking (`avg_mfe_pct`, `avg_mae_pct` in backtest metrics).
- **IndicatorEngine v8 Upgrade (Phase B)**:
  - Converted `cvd_slope_extreme` to rolling causal 20-bar lookback inside loop, removing future look-ahead bias.
  - Added rolling `oi_percentile_series` leverage multipliers: `curr_oi_pct >= 80` + extreme funding raises CAP/DIV structural weights to 2.0; `curr_oi_pct <= 20` lowers CAP weight to 1.0.
  - Upgraded Layer 1 Capitulation Detector (`CAP↑`/`CAP↓`): Dynamic `cap_oi_drop_pct` by coin tier (BTC -4.5%, Midcaps -7%, Alts -10%), replaced flawed 3-bar price stab with true absorption price action (`price_chg_pct` + `is_bull_pa`/`is_bear_pa`).
  - Upgraded Layer 2 CVD Divergence (`DIV↑`/`DIV↓`): Added recency condition (`min(div_price_lows[-2:]) == second_price_low` with `is_bull_pa` / max with `is_bear_pa`), eliminating repetitive continuous signals.
  - Breakout Engine MTF & logic fix: Resolved `if/elif` mutual blocking bug via decoupled flags; required `'Structure'` group confirmation for 1h breakouts counter to 4h MTF trends.
  - Layer 4 BTC Macro Regime Filter: `btc_macro_regime` parameter adjusts altcoin bull/bear thresholds (+1.0) when BTC is in an adverse macro regime.
- **Scanner, API & Frontend Alignment (Phase C)**:
  - `api/core/notifier.py`: Replaced hardcoded local file path with `ARTIFACTS_DIR` env var fallback.
  - `api/core/signal_scanner.py`: Added MTF filter and regime protection support; offloaded I/O to worker threads; added unclosed candle broadcast filter (`score >= 5.0` or structural signals only for intra-bar); deduplicates on `(time, strategy_type)`; scans BTC first to propagate `btc_macro_regime` to altcoins.
  - `api/main.py`: Propagates and caches `_btc_macro_cache`; clears cache and resets fetcher instance on `/clear-cache`.
  - `web/app/backtest/page.tsx`: Fixed double timezone offset (+16h) in trade history table by adding `{ timeZone: 'UTC' }` to pre-shifted timestamps.
  - `web/components/AdvancedChart.tsx`: Aligned `fundingData` via `alignData` with null/undefined filtering; corrected inverted `Market Pulse` tooltip description.
- **Tests**: Added comprehensive unit tests in `api/tests/test_signal_strategy.py` for MFE/MAE metrics, causal trailing stop sequence, and BTC macro regime filtering (all 27 tests passing).

---

## [2026-06-16] v0.2.0 - TradingView-Style Chart in Telegram Signal Notifications
- **Backend**: Created `api/core/utils/chart.py` — pure-`matplotlib` candlestick chart generator.
  - TradingView dark-theme layout (`#131722` background), no candlestick edge lines.
  - EMA50 (orange, `#FF9800`) and EMA200 (purple, `#9C27B0`) overlay lines (0.9px).
  - Per-type signal markers: Reversion BUY (green `▲`), Reversion SELL (red `▼`), MACD Breakout UP (sky-blue `▲`), MACD Breakout DOWN (orange `▼`) — colours read directly from `lsur_markers[].color` to stay in sync with the frontend.
  - Latest price tag on right Y-axis (round-corner bbox, 1.2px dashed reference line).
  - Dual Y-axes (left + right), `MM/DD\n HH:MM` X-axis labels (horizontal, no rotation).
  - Signal markers strictly clamped to the 168-bar visible window to prevent out-of-range signals from snapping to edge candles.
  - UTC-naive timestamp handling ensures chart signal positions match the frontend exactly (no ±1h timezone drift).
- **Backend**: Refactored `api/core/notifier.py` — `send_signal_with_chart()` now accepts `price_data` (raw `get_market_data()` OHLCV list) and `all_markers` (raw `lsur_markers` list), converts them internally. Telegram message is sent as `sendPhoto` with chart PNG + caption (text signal message).
- **Backend**: Updated `api/core/signal_scanner.py` — replaced bare `send_telegram_message()` call with `send_signal_with_chart()`, passing the DB-derived `price_data` and `markers` already in scope. Chart data is always consistent with the frontend because it comes from the same `get_market_data()` call.
- **Infra**: Added `matplotlib>=3.8.0` to `requirements.txt`. Verified Docker build succeeds and container starts cleanly.

---

## [2026-05-29] - Multi-Timeframe Confirmation (Phase 5 Layer 3)
- **Backend**: Upgraded `IndicatorEngine.calculate_confluence_signals()` from v6 to **v7** — added Layer 3 MTF (Multi-Timeframe) Confirmation.
  - New param `higher_tf_regime_history: List[Dict] = None`. When provided, Reversion signals are filtered by the higher TF regime direction.
  - **Loose mode**: 4h `trending+down` → blocks bullish Reversion BUY; 4h `trending+up` → blocks bearish Reversion SELL; Neutral/ranging 4h regimes pass through unconditionally. Breakout signals are **exempt** (already regime-aligned).
  - Bisect-based O(log n) backward-fill lookup per bar (no look-ahead bias). `import bisect` moved to module top level.
  - When MTF is active, passing Reversion signals show `[4h✓]` tag in signal text (e.g. `⚡(2G) 3.5/10 [R][4h✓] RSI30+CVD↑`).
- **Backend**: `GET /market/{symbol}` — new `enable_mtf_filter: bool = False` query param (default off for full backward compatibility). When enabled and timeframe ≠ 4h/1d, concurrently fetches 4h OHLCV + 4h taker volume (within existing `ThreadPoolExecutor(max_workers=10)`), computes 4h CVD and `calculate_market_regime_history()`, then passes into confluence engine. Response includes `indicators.mtf_4h_regime` (latest 4h regime dict, or `null` when disabled).
- **Frontend**: `lib/api.ts` — `SignalConfig` extended with `enableMtfFilter: boolean`; `IndicatorData` extended with `mtf_4h_regime?: {...} | null`; `getMarketData()` URL builder appends `enable_mtf_filter` param.
- **Frontend**: `SignalSettingsModal.tsx` — new MTF Confirmation toggle (indigo accent, `[Layer 3]` badge) with description text explaining loose-mode semantics.
- **Frontend**: `app/page.tsx` — `signalConfig` default includes `enableMtfFilter: false`.
- **Validation**: Unit tests confirm correct blocking/passing for all 3 HTF regime states (downtrend/uptrend/neutral). API smoke test confirms: disabled → `mtf_4h_regime: null`; enabled → returns current 4h regime dict and correctly handles neutral 4h (no signals blocked).

---

## [2026-05-20] - Structural Inflection Point Indicators (Phase 4)
- **Backend**: Upgraded `IndicatorEngine.calculate_confluence_signals()` from v5 to v6 — added two new structural indicators for detecting major trend turning points.
- **Layer 1 — Capitulation Detector (`CAP↑`/`CAP↓`)**: Detects OI crash from recent peak (≥10% drop) combined with CVD accumulation and price stabilization. Identifies liquidation cascade exhaustion (bottoms) and blow-off tops. Weight: 1.5pts, `Structure` group. Timeframe-adaptive parameters (e.g., 1h: OI window=6 bars, drop threshold=-10%, CVD window=4 bars, price stability=0.5%).
- **Layer 2 — CVD Divergence (`DIV↑`/`DIV↓`)**: Detects volume-price structural divergence — price making Lower Low while CVD makes Higher Low (bullish selling exhaustion) or price Higher High while CVD Lower High (bearish buying exhaustion). Weight: 1.5pts, `Structure` group. Window: timeframe-adaptive (1h=10, 4h=8, 1d=7 bars).
- **Scoring**: Signal score denominator updated from `/7` to `/10` to reflect expanded indicator suite.
- **Frontend**: Updated `IndicatorsInfoModal.tsx` to reflect v6 scoring logic, adding the `Structure` dimension and detailed descriptions for the two new structural indicators.
- **Frontend**: Updated `SignalSettingsModal.tsx` threshold input maximums to `/10` and fixed Market Pulse tooltip descriptions across `AdvancedChart.tsx` and `SentimentPanel.tsx`.
- **Validation**: API verified with 34 signals on BTC 1h (1000 bars). 4 DIV signals detected (avg score 3.9 vs non-structural avg 3.4). 0 CAP signals (no recent capitulation events — expected). Frontend dashboard confirmed loading with no errors.

---

## [2026-05-15] - Frontend Notification Panel & Backtest Presets (Phase 3)
- **Frontend**: Created `NotificationSettingsModal.tsx` — modal UI for managing Telegram notification settings (toggle on/off, select monitored symbols, send test notification). Integrated with `GET/POST /notifications/config` and `POST /notifications/test` APIs.
- **Frontend**: Added 🔔 "通知設定" button to main page header, opening the notification settings modal.
- **Frontend**: Updated backtest "Quick Presets" — renamed "擁抱順勢" → "順勢突破" with relaxed Breakout-friendly parameters (SL 4%, TP 10%, Trail 3%, Activation 2%).
- **Bugfix**: Fixed `Cannot read properties of undefined (reading 'includes')` crash in NotificationSettingsModal caused by frontend `NotificationConfig` interface using `symbols` while backend returns `monitored_symbols`. Root cause: API contract was not validated before deployment.
- **Process**: Added "API Contract Validation" rule to `AI_HANDOFF.md` Section 3 to prevent similar frontend/backend field name mismatches in the future.

---

## [2026-05-05] - Event-Driven Signal Notification System (Telegram)
- **Backend**: Implemented `api/core/notifier.py` — async Telegram Bot API wrapper with `httpx`, message formatting with direction emoji (🟢⬆/🔴⬇), signal timestamp, strategy type (Reversion/Breakout), and indicator reasons.
- **Backend**: Implemented `api/core/signal_scanner.py` — periodic signal scanner that reuses the exact `get_market_data(limit=1000)` pipeline, with 1-hour recency window filter and in-memory deduplication to prevent notification floods.
- **Backend**: Integrated `APScheduler` into FastAPI `lifespan` with `CronTrigger(minute="0,15,30,45")` for fixed-clock scan schedule. Added 5-second delay between symbol scans to avoid OKX rate limiting.
- **Backend**: Added 4 new API endpoints: `GET/POST /notifications/config`, `POST /notifications/test`, `POST /notifications/scan-now`.
- **Infra**: Added `httpx` and `apscheduler` to `requirements.txt`. Added `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` env vars to `docker-compose.yml`.
- **Infra**: Configured Python root logger (`logging.basicConfig`) to ensure scanner/notifier INFO logs are visible in Docker container output.

---

## [2026-04-30] - Data Alignment & Early Indicator Fixes
- **Backend**: Fixed false positive `FR+` (Funding Rate) and `OI` signals by replacing zero-filling (`fillna(0)`) with proper `None` handling for missing early historical data.
- **Backend**: Enhanced `LSUR Z-Score` initialization by dynamically adapting `min_periods`, unlocking technical indicators (MACD, RSI, PA) to trigger signals much earlier during the warmup phase.

## [2026-04-29] - Risk Presets UI & Position Lifecycle Validation
- **Frontend**: Added "Conservative" and "Trend Following" risk preset toggle buttons to the Signal Backtester UI with dynamic active-state styling.
- **Backend**: Verified and cemented Position exit evaluation priority: Stop Loss strictly triggers before Take Profit and Trailing Stop in the backtest engine context.

## [2026-04-28] - Dual-Engine Strategy & Breakout Indicators
- **Backend**: Implemented look-ahead-bias-free Donchian Channel and MACD calculations in `api/core/indicators.py`.
- **Backend**: Integrated a new "Breakout" logic into the confluence signal engine to catch strong trend continuations (Dual-Engine architecture).
- **Frontend**: Updated `AdvancedChart.tsx` to visually distinguish Breakout signals (using a 🚀 icon and unique blue/orange colors) from Reversion signals.
- **Docs**: Updated `AI_HANDOFF.md` to reflect the completed Dual-Engine architecture and refocused the next goal on Risk Management and Backtest Parameter Tuning.

## [2026-04-28] - Regime Chart & Adaptive Thresholds
- **Backend**: Modified `api/core/indicators.py` to automatically relax bullish conditions (RSI threshold from 30 to 45, EMA distance requirement shrunk to 1/5, etc.) when the market is in `trending up` regime. This captures shallow pullbacks in strong uptrends.
- **Frontend**: Added a `Regime Chart (Histogram)` at the bottom of `AdvancedChart.tsx`. It displays constant-height bars colored Emerald (Uptrend), Red (Downtrend), and Amber (Ranging) to make regime-protection visually explicit.

## [2026-04-27] - Backtest Signal Alignment & Timezone Sync
- **Backend**: Refactored `/quant/signal-backtest` API. Forced the backtester to call the exact same `get_market_data(limit=1000)` function as the Dashboard endpoint, completely resolving indicator path-dependence issues (warm-up periods).
- **Frontend**: Added a `Regime Filter` toggle to the Backtester parameter panel.
- **Frontend**: Unified trade history timezone to Local Time and updated to a 24-hour format, resolving a 1-hour discrepancy with Lightweight Charts (UTC).

## [2026-04-26] - v2 Signal Strategy Engine
- **Backend**: Added signal-driven strategy core modules (`Position`, `SignalStrategy`, `SignalBacktester`).
- **Backend**: Added `POST /quant/signal-backtest` endpoint.
- **Backend**: Implemented 24 unit & integration tests.
- **Frontend**: Added Signal Strategy backtest UI with trade markers embedded in the Equity Curve.

## [2026-04-10 to 2026-04-22] - Backtest UI & Data Pipeline Enhancements
- **Frontend**: Stabilized backtester layout with fixed min-heights for metric cards and chart.
- **Frontend**: Implemented trading fee deduction and dynamic decimal precision in UI.
- **Frontend**: Added dynamic asset profile tooltip to toggle label.
- **Backend**: Fixed AI price boundaries and enabled regime protection logic.
- **Backend**: Refactored OHLCV to perpetual swaps for full history and standardized CVD on Binance base asset volume.
- **Backend**: Added multi-threaded CVD backfill script and DB ingestion.
- **Backend**: Healed historical data gaps dynamically by detecting discontinuities and filtered null metrics from DB cache.

## [2026-03-27] - PostgreSQL Migration & Dockerization
- **Backend**: Migrated persistence layer from JSON to PostgreSQL.
- **Infra**: Exposed Dockerization and prepared full-stack deployment (`docker-compose`).
- **Backend**: Fixed indicator timeframe alignment.

## [2026-03-16 to 2026-03-20] - Dynamic Profiles & Regime Upgrades
- **Backend**: Added support for HYPE & CC symbols with dynamic asset profile indicator engine.
- **Backend**: Displayed detailed market regime factors (ADX, BB Width, CVD) on Sentiment Panel.
- **Backend**: Resolved regime look-ahead bias and state machine repainting bugs.
- **Frontend**: Added category tags (Price/Momentum/Sentiment) to indicator info modal.

## [2026-03-03 to 2026-03-11] - Signal System v4/v5 & Caching
- **Backend**: Upgraded to Signal System v5 with Market Regime and "no-short" filter.
- **Backend**: Added Market Pulse composite score (0-100).
- **Backend**: Implemented data caching and parallel fetching to accelerate timeframe switching.
- **Backend**: Upgraded to Signal system v4 (Timeframe-adaptive thresholds, OI×Price divergence).
- **Frontend**: Extended historical indicator signals via daily data and added SWR frontend caching for instant UI responses.
- **Frontend**: Added Binance liquidity sources visualization breakdown chart.

## [2026-02-12 to 2026-02-13] - Initial Indicators & UI Foundation
- **Frontend**: Modified UI and added core visualization layouts.
- **Backend**: Implemented core indicators: LSUR Z-Score, CVD, Open Interest, Funding Rate, RSI, EMA Zone, Bollinger Bands.
