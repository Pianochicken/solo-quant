# Solo-Quant Project Context & AI Handoff

This document is the **Context Buffer** for AI Agents. It defines how the system works *right now*, the critical rules to avoid regressions, and the immediate next goal.
*Note: For historical updates, please refer to `CHANGELOG.md`.*
*Note: For general domain knowledge, trading philosophy, and coding standards, ALWAYS review `@[.github/skills/skill-quant-trading/SKILL.md]`.*

---

## 1. Project Overview & Tech Stack
**Solo-Quant** is a cryptocurrency algorithmic trading platform focused on Multi-indicator Confluence Analysis and Signal-Driven Backtesting.
- **Backend**: Python 3.11, FastAPI, Pandas, NumPy, CCXT. (Run via `docker compose up api`)
- **Frontend**: Next.js 16 (App Router), TypeScript, Tailwind CSS, Lightweight Charts. (Run via `docker compose up web`)
- **Architecture**: Crypto Macro & Signal Terminal (Signal-Driven Quantitative Intelligence & Backtesting; legacy grid bot UI removed).

---

## 2. Current Architecture (The "Now")

### 2.1 The Signal-Driven Engine (v8 - Macro & Inflection Precision)
The core of the system generates `Bullish` and `Bearish` markers from `IndicatorEngine` v8, which are parsed by the `SignalBacktester` to execute trades and visualized on the dashboard.

- **Data Flow**: `get_market_data(limit=1000)` fetches OHLCV from DB -> `IndicatorEngine` calculates arrays -> UI renders `AdvancedChart` / Backend runs `SignalBacktester`.
- **Multi-Layer Confluence Logic**:
  - **Reversion & Trend Pullback Engine**: RSI, BB, EMA, Funding for ranging regimes; native EMA50 support/resistance (`EMA支撐↑` / `EMA壓力↓`) with EMA200 trend alignment during trending regimes (driving 4h Pure Reversion to 71.4% win rate and 3.49 E-Ratio).
  - **Breakout Engine**: Dynamic Donchian Channels (48 bars for 1h/15m, 20 bars for 4h/1d), strict first-bar cross, volume & momentum confirmation, required OI expansion (`oi_expanding = oi_chg_pct > 0` for 1h/15m). Counter-trend breakouts strictly forbidden.
  - **Trend Protection Iron Laws**:
    - **Uptrend Strict Anti-Shorting**: Unconditional `no_short` blocking (no exemptions allowed).
    - **1h Bull Structure Guard**: 24-bar rising EMA200 (`ema200_rising`) and 4h MTF direction strictly block counter-trend shorts in bull grind.
    - **Extreme Inflection Exemption**: Exemptions to `no_long / no_short` strictly require 4-fold extreme resonance (`Structure` + `RSI < 28 / > 72` + `BB < 0.05 / > 0.95` + `score >= threshold + 1.5`). All timeframes achieve Full Macro E-Ratio > 1.15.
  - **Layer 1 Capitulation Detector (`CAP↑`/`CAP↓`)**: Dynamic OI drop thresholds (BTC -4.5%, Midcaps -7%, Alts -10%) + CVD accumulation + absorption price action (wick / candle body direction).
  - **Layer 2 CVD Divergence (`DIV↑`/`DIV↓`)**: Volume-price structural divergence with recency constraint (`min`/`max` within last 2 bars) and price action confirmation.
  - **Layer 3 MTF Confirmation (`[4h✓]`)**: Causal 4h regime confirmation. Enforces $t_{\text{htf}} + \text{htf\_sec} \le t + \text{tf\_sec}$ so 1h candles only read closed 4h bars, completely eliminating look-ahead bias.
  - **Layer 4 BTC Macro Regime Filter**: BTC trending down or overbought (pulse ≥ 80) increases altcoin long threshold (+1.0); BTC trending up or oversold (pulse ≤ 20) increases altcoin short threshold (+1.0).
  - **Macro Leverage Multiplier**: Rolling OI percentile (90 bars) dynamically scales `CAP`/`DIV` structural weights (2.0x when OI pct ≥ 80 with extreme funding; 1.0x when OI pct ≤ 20).
- **Position Lifecycle & Zero Look-Ahead Bias**: In `api/quant/signal_backtester.py`, `_process_exits()` strictly calls `pos.check_exit()` *before* `pos.update()`. Stop Loss -> Take Profit -> Trailing Stop (evaluated using previous-bar ratchet). Entry fees are single-counted (deducted from balance at entry and aggregated at exit via `pos.fees_paid`, eliminating 1.5x fee inflation).
- **Physical Execution Bounds & Gap Slippage**: In `Position.get_exit_price_for_reason()`, stop execution prices are physically bounded: Long SL/trailing stop cannot exceed `min(level, high)`; Short SL/trailing stop cannot breach `max(level, low)`. Opening gap-downs through stop levels fill at `open_price`. In `Position.update()`, ratcheted trailing stops are clamped to current `close` if price already retraced past the stop level.
- **Trailing Stop Breakeven Floor**: In `Position.update()`, once trailing stop is active, enforces `new_trail >= entry_price * 1.002` (Long) and `new_trail <= entry_price * 0.998` (Short), completely eliminating loss exits after profit activation.
- **Dynamic TP & Risk-Based Sizing**: Precomputed 14-period Wilder's ATR; 1.35x `take_profit_pct` multiplier applied to Structure and Breakout trades. Capital allocation safely divided by `max_positions` (`current_equity * 0.95 / max_positions`).
- **Signal Quality Metrics**: Backtester computes Forward Return MFE/MAE (`avg_mfe_pct`, `avg_mae_pct`).

### 2.2 Signal Notification System (Telegram v8)
An event-driven notification pipeline embedded within the FastAPI container.

- **Modules**: `api/core/notifier.py` + `api/core/signal_scanner.py`.
- **Schedule & Multi-Timeframe**: `APScheduler` with `CronTrigger(minute="0,15,30,45")`. Monitors `MONITORED_TIMEFRAMES = ["1h", "4h"]` (4h scanned at `:00` UTC when `hour % 4 == 0` with 8-hour tracking window; 1h scanned hourly).
- **Full Macro Defaults**: Scans default to `enable_protection=True` and `enable_mtf_filter=True`.
- **Candle Close Confirmation**: Intra-bar 1h signals broadcast only if high conviction (`score >= 5.0` or structural `CAP`/`DIV`). Otherwise, alerts are broadcast only after the candle closes.
- **Dedup**: Tracks `(signal_time, strategy_type)` to avoid intra-bar alerts cannibalizing final closed candle signals.
- **BTC Macro Scanning Sequence**: Scans BTC first to cache and propagate `btc_macro_regime` to monitored altcoins.
- **Message Format**: `sendPhoto` with TradingView-style 168-hour candlestick chart + detailed caption indicating timeframe and timezone badge (e.g. `[BTC/USDT 4h]`, `(UTC+8)`). Notification timestamps and chart X-axis ticks align dynamically to `NEXT_PUBLIC_TIMEZONE_OFFSET` (defaulting to 0 / UTC, configurable via `.env`).
- **Config API**: `GET/POST /notifications/config` (exposes `enable_mtf_filter`, `enable_protection`, `monitored_symbols`).

### 2.3 Frontend Terminal Architecture (Crypto Macro & Signal Terminal)
The frontend (`web/`) is streamlined into a high-conviction decision cockpit for market intelligence:
- **Main Terminal (`web/app/page.tsx`)**: Pure signal & macro dashboard. Legacy `GridPanel` and `HistoryPanel` removed, eliminating empty black voids.
- **Recent Signals Radar**: Right-column card displaying the latest 10 signals from `lsur_markers` with UTC timestamps (`MM/DD HH:mm`), strategy type badges (`🚀 BREAKOUT`, `⚡ STRUCTURE`, `🟢 BUY / 🔴 SELL`), asset-precision trigger prices (`getPricePrecision`), and monospace indicator reason pills.
- **Five-Coin Macro & Quadrant Strip (`web/app/page.tsx` & `/api/market_overview`)**: Top horizontal radar bar rendering 5 micro-cards (BTC, ETH, SOL, HYPE, CC) displaying 24h price change %, 4h RSI, relative strength vs BTC (`rs_vs_btc`), 24h coin-denominated open interest change % (`oi_coin_change_24h_pct`), 4-quadrant state badges (`🔥 強勢加倉` / `🩸 弱勢加倉` / `⚡ 強勢減倉` / `🧊 弱勢減倉` / `⚪ 中性盤整`), 4H regime, and latest signal. Clicking any card switches the active symbol. Equipped with rich, non-intrusive `InfoTooltip` explainers on every metric (24h Price Change, Quadrant triggers, RS vs BTC, 24h Coin OI %, 4H Regime, and Latest Signal with elapsed hours).
- **Background Pre-warmer & Ultra-Low Latency Overview (`api/main.py`)**: APScheduler runs `_background_refresh_market_overview` every 30s in the background, keeping memory cache warm. User page reloads hit cache in **< 6ms** (reduced from 5–8 seconds). Cold cache misses execute concurrently using a 5-worker thread pool with lean data fetching (`include_orderbook=False`, `include_breakdown=False`, and `limit=50`).
- **Structural Overlays (`AdvancedChart.tsx`)**: Main price chart legend bar includes one-click toggles for `Donchian 通道` (cyan dashed bands) and `VP POC 籌碼峰` (40-bin volume-weighted Point of Control horizontal amber line `#f59e0b`).
- **Signal Archetype & Minimum Score Filters (`web/components/SignalSettingsModal.tsx` & `web/app/backtest/page.tsx`)**: Checkboxes for `Structure (CAP/DIV)`, `Reversion / Pullback`, `Breakout`, and dropdown for `Min Confluence Score` (Default, 3.5, 4.0, 4.5, 5.0) wired through both the live terminal and backtester.
- **4H MTF Status Badge (`SentimentPanel.tsx`)**: Surfaces `mtf_4h_regime` in the `Market Regime` card header right side (`4H: Trending ↑` emerald, `4H: Trending ↓` red, `4H: Ranging` amber) to maintain macro direction awareness.
- **Unified Terminal Loader**: Replaced fragmented multi-block loaders and artificial 600ms delays with a single full-workspace dark loading screen (radar pulse & asset/timeframe pill). On data arrival, all 3 panels (Chart, SentimentPanel, Recent Signals) hydrate atomically in the exact same render frame.
- **Chart Polish (`AdvancedChart.tsx`)**: Removed TradingView attribution logo (`attributionLogo: false`) to prevent overlap with the 7th subchart (`Market Regime`), and expanded main price chart height to 460px (`h-[460px]`).
- **Full Macro Defaults**: Frontend initializes with `enableProtection: true` and `enableMtfFilter: true`.
- **Strategy Backtester (`web/app/backtest/page.tsx`)**: Upgraded to a pure Signal Strategy Terminal. Removed legacy Grid tabs. Added multi-timeframe selector (`1h`, `4h`, `1d`) linked to adaptive durations, integrated empirical `OPTIMAL_RISK_PROFILES` (Auto Risk Profile toggle), dynamic relative multiplier buttons (🎯 實證最佳基準 / 🚀 波段放大 1.4x), and unified default position limit (max 1) and fee rate (0.05%).

---

## 3. Crucial Principles & Gotchas (READ BEFORE CODING)
To prevent regressions, **ALL future AI Agents MUST adhere to these rules**:

1. **Indicator Path-Dependence Parity (1000-candle Warmup)**:
   - *Rule*: **ALWAYS** fetch `limit=1000` candles for indicator calculation. When aggregating higher timeframes (e.g. 4h), query `limit * tf_ratio` raw points to guarantee a full 1000 aggregated bars.
2. **Strict Time Alignment & Zero Look-Ahead Bias**:
   - *Rule*: Indicators must be strictly causal (rolling windows `<= current_bar`). Donchian warmup uses expanding windows shifted by 1 (no `bfill`). MTF alignment strictly enforces $t_{\text{htf}} + \text{htf\_sec} \le t + \text{tf\_sec}$ so 1h candles never observe unclosed 4h candles. Trailing stops in backtesting must be evaluated against the previous bar's ratcheted price before applying current-bar highs/lows.
3. **Cross-Exchange OI Merging & Liquidity Sources**:
   - *Gotcha*: Binance and OKX have different historical depth limits. Directly summing or averaging unaligned series causes artificial jumps at boundary points (e.g. OKX 100-bar limit). Furthermore, OKX daily candles close at 16:00 UTC (modulo 86400 == 57600), so filtering by `ts % 86400 == 0` drops all daily data.
   - *Rule*: For live breakdown, use `get_exchange_breakdown()` with in-memory caching. For historical OI and Long/Short series, outer-merge on timestamp, apply `ffill(limit=2)`, and apply causal overlap ratio scaling (`ffill().bfill().fillna(1.0)`) across overlapping ranges to guarantee zero artificial cliff jumps.
4. **Local Time vs UTC Formatting**:
   - *Gotcha*: If timestamps have already been shifted for local timezone display (e.g., in `runSignalBacktest()`), frontend formatters must specify `{ timeZone: 'UTC' }` to avoid double-offset (+16h).
5. **API Contract Validation (Frontend ↔ Backend)**:
   - *Rule*: Always verify that TypeScript interfaces mirror the exact field names returned by FastAPI before deploying UI changes.
6. **PostgreSQL Concurrent Upsert Deadlock & Cardinality Prevention**:
   - *Gotcha*: Bulk `INSERT ... ON CONFLICT DO UPDATE` across concurrent asynchronous transactions causes PostgreSQL deadlocks on index tuples if rows are inserted in varying order. Furthermore, passing duplicate primary keys in the same batch triggers PostgreSQL `CardinalityViolation` (`ON CONFLICT DO UPDATE command cannot affect row a second time`).
   - *Rule*: Always deduplicate records in memory by `(exchange, symbol, timeframe, timestamp)` and sort deterministically by primary index elements before executing `stmt.on_conflict_do_update()`. Normalize `timeframe` to lowercase.
7. **Database Connection Pool Sizing**:
   - *Rule*: With parallel thread pools inside `get_market_data()` (10 worker threads) and background scanners, maintain `pool_size >= 20` and `max_overflow >= 30` (up to 50 concurrent DB connections) with `pool_pre_ping=True` in `api/db/database.py` to prevent `QueuePool limit reached` timeouts.
8. **Physical Execution Bounds & Gap Slippage in Backtester**:
   - *Rule*: Backtester exit execution must respect market physics: Long stops fill at `min(level, high)` and Short stops fill at `max(level, low)`. Opening gap-throughs fill at `open_price`. Trailing stops must clamp to candle close if intra-bar reversals breach the ratcheted level. Entry fees must only be aggregated upon position closing to prevent double-counting.

---

## 4. Current Development Focus (The "Next")
### Goal: Macro Precision & Live Execution Optimization

**Context**: Solo-Quant v8 (Macro & Inflection Precision Upgrade) is **complete and validated**:
- Data ingestion and cross-exchange aggregation fixed (no false OI crashes, 4h warmup aligned).
- Backtest engine look-ahead bias eliminated; MFE/MAE signal quality tracking added.
- IndicatorEngine upgraded to v8 with dynamic leverage multipliers, absorption-based capitulation, recency-constrained divergence, and BTC macro regime filtering.
- Signal scanner upgraded with closed-bar confirmation, MTF filter support, and BTC-first macro propagation.
- Frontend timezone display and chart tooltip alignment complete.

### 4.1 Completed Phases ✅
- Phase A: Data Ingestion & Backtest Engine Accuracy
- Phase B: IndicatorEngine v8 Upgrade
- Phase C: Telegram Signal Scanner & Frontend Alignment
- Phase D: Multi-Year Cross-Regime Validation & Execution Tuning (1d/4h/1h Full Macro E-Ratio > 1.10, 1d Structure win rate 73.3% / E-Ratio 1.59, 4h Breakout 62.5% / E-Ratio 1.61)

### 4.2 Next Goals (Phase 6)
1. **Live Paper Trading / Execution Engine**: Connect signals to paper-trading accounts (e.g., OKX / Binance Demo API) to measure real slippage vs backtest MFE/MAE.
2. **Orderbook Liquidity Imbalance (Layer 5)**: Periodic depth/orderbook snapshot ingestion into DB for institutional orderflow absorption scoring.
3. **Parameter Optimization**: Fine-tune per-asset profile thresholds using the new forward-return MFE/MAE metrics.

---

## 5. AI Agent Prompt (Copy-Paste to start next session)
*Copy the prompt below to hand off this exact context to the next AI session:*

「請扮演一位資深的全端工程師及加密貨幣分析師。請先閱讀 `SKILL.md` 與 `AI_HANDOFF.md` 以了解專案架構、核心理念與避坑規則。

目前系統已升級至 **Solo-Quant v8 (Macro & Inflection Precision)**，包含零未來函數回測、1000 根 K 線暖機對齊、動態槓桿脆弱度乘數、真吸收 K 線投降指標與 BTC 宏觀狀態過濾。

**任務：實戰驗證與訊號品質調優 (Phase 6)**
1. 使用 Backtester 分析不同幣種在開啟 MTF 與 BTC 宏觀過濾下的勝率與 MFE/MAE 表現。
2. 監控 Telegram Scanner 推播訊號的收線確認機制與圖表清晰度。
3. 遵循三大鐵則：零未來函數、1000 根暖機對齊、前後端 API 型別一致。」


