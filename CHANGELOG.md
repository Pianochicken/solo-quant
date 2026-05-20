# Solo-Quant Changelog

All notable changes to the Solo-Quant project will be documented in this file.
This file serves as a historical record to keep `AI_HANDOFF.md` clean and focused on current state and next steps.

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
