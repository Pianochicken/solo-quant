# Solo-Quant Changelog

All notable changes to the Solo-Quant project will be documented in this file.
This file serves as a historical record to keep `AI_HANDOFF.md` clean and focused on current state and next steps.

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
