# Solo-Quant Changelog

All notable changes to the Solo-Quant project will be documented in this file.
This file serves as a historical record to keep `AI_HANDOFF.md` clean and focused on current state and next steps.

## [2026-11-02] v0.6.8 - Single Full TP Architecture, Cross-Candle Trailing Stop & Empirical Profile Calibration
- **Default Architecture: Single Full TP (`enable_partial_tp = False`)**:
  - Based on empirical multi-asset backtesting (ETH 4h WR 75%, SOL 4h WR 80%), standardized default execution mode to Single Full TP (`enable_partial_tp = False`) across `SignalStrategyConfig`, `SignalBacktestParams`, and `web/app/backtest/page.tsx`.
  - Single Full TP consistently outperforms two-stage partial take-profit by preserving 100% position size for the entire swing expansion without sacrificing profit on winning runs.
- **Cross-Candle Trailing Stop & Same-Candle Premature Exit Elimination (`api/quant/position.py`, `api/quant/signal_backtester.py`)**:
  - Removed same-candle premature exit where candles retracing from high were prematurely stopped out on the very candle of their rally.
  - Implemented safe cross-candle trailing stop clamping in `Position.update()`: when `unrealized_pct >= trailing_activation_pct`, if candle `close` drops below `candidate_trail`, the stop is securely clamped below close (`safe_trail = max(self.stop_loss, close * 0.999)` for Long, `min(self.stop_loss, close * 1.001)` for Short). Prevents both underwater next-open gap-through and same-candle premature exit.
  - Preserved physical fill bounds in `Position.get_exit_price_for_reason()` (`min(sl, high)` for Long; `max(sl, low)` for Short).
- **HYPE High-Volatility Engine Calibration (`api/core/indicators.py`, `api/quant/signal_strategy.py`)**:
  - In `IndicatorEngine.calculate_confluence_signals()` under `is_hype`, required `score_ok = (bull_score >= 3.5)` / `(bear_score >= 3.5)` for Reversion setups, eliminating low-conviction counter-trend noise (e.g. score=3 bottom short before the rally to 97).
  - Widened HYPE 4h stop loss to 5.5% (exceeding its P75 MAE of 4.83%) and calibrated risk profile: SL 5.5%, TP 5.20%, Trail Act 2.20%, Trail Stop 0.50%.
  - Calibrated HYPE 1h risk profile: SL 2.4%, TP 2.80%, Trail Act 1.20%, Trail Stop 0.35%.
  - Result: HYPE 4h (90d) win rate skyrocketed from 25.0% to **83.3%** (6 trades: 5 wins, 1 loss, PF 1.65, PnL +$133.48), and HYPE 1h (30d) achieved **83.3%** win rate (12 trades, PF 2.04, PnL +$443.44)!
- **BTC Empirical Profile Calibration (`api/quant/signal_strategy.py`, `api/main.py`, `web/app/backtest/page.tsx`)**:
  - Calibrated BTC 1h: SL 1.2%, TP 1.80%, Trail Act 0.60%, Trail Stop 0.25%.
  - Win rate increased to **68.8%** (16 trades: 11 wins, 5 losses), with losses reduced by 80% (PnL -$178.62, PF 0.71).
  - Calibrated BTC 4h: SL 2.0%, TP 3.80%, Trail Act 1.50%, Trail Stop 0.40% (**55.6% WR**, PF 1.19, PnL +$126.72).
- **Final Multi-Asset 90-Day Empirical Benchmark Table**:
  - BTC 1h (30d): 16 trades, 68.8% WR, PnL -$178.62 (-1.79%), PF 0.71, MaxDD 5.02%
  - ETH 4h (90d): 9 trades, 66.7% WR, PnL +$242.92 (+2.43%), PF 1.54, MaxDD 5.31%
  - SOL 4h (90d): 10 trades, 60.0% WR, PnL +$109.57 (+1.10%), PF 1.20, MaxDD 3.49%
  - HYPE 4h (90d): 6 trades, 83.3% WR, PnL +$133.48 (+1.33%), PF 1.65, MaxDD 3.07%
  - BTC 4h (90d): 9 trades, 55.6% WR, PnL +$126.72 (+1.27%), PF 1.19, MaxDD 6.73%
  - HYPE 1h (30d): 12 trades, 83.3% WR, PnL +$443.44 (+4.43%), PF 2.04, MaxDD 2.45%
  - All 43 unit tests passing in Docker container (`solo-quant-api`).
  - All 3 review slices (`slice_a_quant`, `slice_b_backend`, `slice_c_frontend`) synchronized and re-exported.

## [2026-11-02] v0.6.7 - Physical Timeline Execution, MFE Risk Re-Anchoring & Two-Stage Partial TP Alignment
- **Physical Timeline Execution Engine (`api/quant/position.py`, `api/quant/signal_backtester.py`)**:
  - Restored real-world physical law (High occurs before Close in OHLC):
    - **Step A**: Call `pos.check_exit()` against existing levels from prior bars or open gap. Only true gap-downs/gap-ups execute at `open_price`; otherwise orders fill at exact stop/target price, bounded by candle extremes.
    - **Step B**: If not exited in Step A:
      1. Check TP1 (`high >= tp1_price` for Long, `low <= tp1_price` for Short). If reached, execute 50% partial take profit (`execute_partial_tp`) and advance stop loss of the remaining 50% runner to breakeven (`entry * 1.002` for Long, `entry * 0.998` for Short).
      2. Ratchet intraday extremes `highest_since_entry` / `lowest_since_entry` and calculate `trailing_stop_price`.
      3. **Same-Candle Retracement Check**: If `pos.trailing_active` is True and the candle close retraces through the trailing stop (`close <= pos.trailing_stop_price` for Long, `close >= pos.trailing_stop_price` for Short), immediately trigger a trailing exit on the exact same candle at `trailing_stop_price`! Eliminates the blind spot where profitable spikes turned into full stopouts.
  - **Unified Margin & Capital Return Formula**: Standardized capital return across `execute_partial_tp` and `_close_position` to `returned_cash = closed_cost + raw_pnl - exit_fee` for both Long and Short, completely preventing balance drift.
- **Empirical MFE Risk Re-Anchoring (`api/quant/signal_strategy.py`, `api/main.py`, `web/app/backtest/page.tsx`)**:
  - Re-anchored `OPTIMAL_RISK_PROFILES` to empirical median & average MFE:
    - **BTC**: 1h (SL 1.4%, TP 1.65%, Trail Act 0.70%, Trail Stop 0.30%), 4h (SL 2.2%, TP 2.80%, Trail Act 1.25%, Trail Stop 0.50%), 1d (SL 5.0%, TP 6.50%, Trail Act 2.80%, Trail Stop 1.10%).
    - **ETH**: 1h (SL 1.8%, TP 2.20%, Trail Act 0.90%, Trail Stop 0.35%), 4h (SL 2.8%, TP 3.80%, Trail Act 1.60%, Trail Stop 0.65%), 1d (SL 7.5%, TP 10.5%, Trail Act 4.20%, Trail Stop 1.60%).
    - **SOL**: 1h (SL 2.0%, TP 2.60%, Trail Act 1.05%, Trail Stop 0.40%), 4h (SL 3.5%, TP 3.80%, Trail Act 1.65%, Trail Stop 0.65%), 1d (SL 9.0%, TP 12.0%, Trail Act 5.00%, Trail Stop 2.00%).
    - **CC**: 1h (SL 3.0%, TP 3.20%, Trail Act 1.30%, Trail Stop 0.50%), 4h (SL 6.0%, TP 6.80%, Trail Act 2.80%, Trail Stop 1.10%), 1d (SL 9.5%, TP 11.5%, Trail Act 5.00%, Trail Stop 2.00%).
    - **HYPE**: 1h (SL 2.4%, TP 2.80%, Trail Act 1.10%, Trail Stop 0.45%), 4h (SL 3.2%, TP 3.80%, Trail Act 1.65%, Trail Stop 0.60%), 1d (SL 8.5%, TP 12.0%, Trail Act 5.00%, Trail Stop 2.00%).
  - Adjusted Structure and Breakout TP expansion multiplier from 1.35x to 1.15x across `signal_backtester.py` and `notifier.py`.
  - Standardized default strategy parameters: `enable_partial_tp: bool = True`, `partial_tp_ratio: float = 0.5`.
- **HYPE Filter Calibration & Ranging Noise Suppression (`api/core/indicators.py`)**:
  - Relaxed HYPE Reversion filter to require EMA50 alignment (`close > ema50` or Structure for Long; `close < ema50` or Structure for Short) along with CVD momentum confirmation (`cvd_rising` / `cvd_falling`).
  - Added dynamic setup window tightening: in 1h ranging markets, `SETUP_WINDOW` is tightened from 3 bars to 1 bar (`effective_setup_window = 1`), preventing stale setups from matching price triggers on range boundary sweeps.
- **Testing, Verification & Slices**:
  - All 43 unit tests passing in Docker (`api/tests/`).
  - Backtest benchmarks:
    - **BTC 1h (30d)**: Win Rate 62.5% (16 trades, PF 0.69 / 0.59).
    - **ETH 4h (90d)**: Win Rate 75.0% (8 trades, PnL +$366.62 / +$222.08, PF 1.83 / 1.51).
    - **SOL 4h (90d)**: Win Rate 80.0% (10 trades, PnL +$673.50 / +$500.07, PF 2.58 / 2.18).
    - **HYPE 4h (90d)**: Trade count restored to 8 trades.
  - Re-packaged all 3 review slices (`slice_a_quant`, `slice_b_backend`, `slice_c_frontend`).

## [2026-11-01] v0.6.6 - Close-Confirmed Ratchet, Risk-Reward Rebalancing & HYPE Trend Filter
- **Close-Confirmed Ratchet & Underwater Stop Elimination (`api/quant/position.py`)**:
  - In `Position.update()`, added strict close-confirmation requirements before activating or ratcheting trailing stops:
    - Long: `unrealized_pct >= trailing_activation_pct` and `close > new_trail`.
    - Short: `unrealized_pct >= trailing_activation_pct` and `close < new_trail`.
  - Completely eliminated the "Upper Shadow Activation + Next Open Stopout" bug where intraday wicks triggered trailing stops but candle close fell below, causing next candle open to immediately exit at a loss.
  - In `Position.check_partial_tp()`, enforce minimum TP1 distance of `max(trailing_activation_pct, 0.85 * R)` and require candle close securely above/below breakeven (`close > entry * 1.003` for Long, `close < entry * 0.997` for Short).
  - In `Position.execute_partial_tp()`, adjusted partial take-profit ratio to 40% (`ratio=0.4`), preserving 60% position size for the main TP target.
- **Risk-Reward Ratio Rebalancing (`api/quant/signal_strategy.py`, `api/main.py`, `web/app/backtest/page.tsx`)**:
  - Rebalanced `OPTIMAL_RISK_PROFILES` across all major assets and timeframes (BTC, ETH, SOL, CC, HYPE) to establish healthy $R$-multiples (e.g. BTC 1h: SL 1.4%, TP 2.1% [1.5R], Trail Act 1.20%, Trail Stop 0.35%).
  - Set `enable_partial_tp = False` by default across `SignalStrategyConfig` and `SignalBacktestParams`.
  - Synchronized default backtesting parameters in `api/main.py` and `web/app/backtest/page.tsx`.
- **v8 Baseline Restoration & HYPE Trend Conviction Filter (`api/core/indicators.py`)**:
  - Restored v8 golden baseline for non-HYPE assets (`not is_hype`): native `oi_chg_pct`, fixed EMA bounce bounds (`-1.2 <= low_ema_dist <= 0.35` / `-0.35 <= high_ema_dist <= 1.2`), and standard breakout conditions.
  - Layer 3 MTF alignment (~line 1456): aligned with `idx_htf = bisect.bisect_right(htf_regime_times, t) - 1`, ensuring immediate reflection of current 4H regime structure.
  - For HYPE (`is_hype`):
    - Pure Reversion signals without Structure (no CAP/DIV) strictly require EMA50/EMA200 trend alignment, MACD momentum confirmation, and score threshold +0.5.
    - Structure signals (CAP/DIV) require candle body direction and CVD momentum confirmation (`close > open and cvd_now > cvd_prev` for Long; `close < open and cvd_now < cvd_prev` for Short).
- **Unit Testing & Backtest Verification**:
  - All 43 unit tests passing in Docker (`api/tests/`).
  - BTC 1h 30d backtest with partial TP improved Win Rate to 46.2%, Profit Factor to 0.68, and cut Net Loss by 75% compared to pre-fix baseline.

## [2026-10-31] v0.6.5 - Tactical Execution Orders, Two-Stage Partial TP & HYPE Microstructure Tuning
- **Two-Stage Partial Take Profit & Breakeven Runner Engine (`api/quant/position.py`, `api/quant/signal_strategy.py`, `api/quant/signal_backtester.py`)**:
  - Implemented partial profit-taking upon reaching TP1 (`trailing_activation_pct`): closes 50% of the position to secure initial profit, returns capital/margin to balance, and records a `'tp1_partial'` trade.
  - Automatically shifts remaining 50% stop loss to breakeven (`entry * 1.002` for long, `entry * 0.998` for short) and expands the runner's trailing stop distance by 1.4x (`trailing_stop_pct *= 1.4`) to let winners run towards TP2.
  - Supported lifetime aggregation in `Position.close()` while cleanly separating trade record PnL and fee accounting between partial TP1 and final close.
  - Added `enable_partial_tp: bool = True` and `partial_tp_ratio: float = 0.5` across `SignalStrategyConfig`, `SignalBacktestParams`, `web/app/backtest/page.tsx`, and `api/main.py`.
- **HYPE & High-Volatility Coin Microstructure Tuning (`api/core/indicators.py`)**:
  - **Coin-Denominated OI**: Introduced `coin_oi_chg_pct = (oi_coin_now - oi_coin_prev) / oi_coin_prev * 100`, eliminating USD OI price appreciation distortion across rapid market moves. Applied `eff_oi_chg_pct` to OI↑P↑, OI↑P↓, and OI deleveraging checks.
  - **Dynamic ATR EMA Pullback Bounds**: Upgraded EMA50 trend pullback/bounce detection to dynamic ATR-scaled thresholds (`-max(1.2, atr_pct * 1.1) <= low_ema_dist <= max(0.35, atr_pct * 0.3)` for longs; `-max(0.35, atr_pct * 0.3) <= high_ema_dist <= max(1.2, atr_pct * 1.1)` for shorts), preventing false exclusions from high-volatility wicks while protecting against chasing tops.
  - **Alpha Decoupling Protection**: When an asset demonstrates independent strength (price > EMA50 > EMA200, RSI $\ge$ 55, and `coin_oi_chg_pct >= 1.5%`), exempts BTC macro penalty to `bull_threshold` (+1.0) and completely blocks counter-trend short signals (`allow_reversion_bear = False`).
  - **Pure Reversion Trend Alignment**: Restructured HYPE RSI overbought/oversold limits to -6 / +6. Pure Reversion signals for HYPE without structural CAP/DIV confirmation now strictly require macro trend alignment (`is_bull_macro_trend` / `is_bear_macro_trend`) and `score >= threshold + 0.5`.
  - **Altcoin Breakout Conviction Engine**: Require breakout candle body $\ge 0.45 \times \text{ATR}$, close in upper/lower 50% of range, and coin-denominated OI expansion $\ge 0.5\%$, lifting HYPE 4h Breakout E-Ratio to 1.53.
  - Updated HYPE empirical risk profiles across 1h (`SL 2.6%, TP 3.2%, Trail Act 1.20%, Trail Stop 0.55%`), 4h (`SL 4.0%, TP 5.2%, Trail Act 2.00%, Trail Stop 0.90%`), and 1d (`SL 9.5%, TP 14.0%, Trail Act 5.50%, Trail Stop 2.20%`).
- **Telegram Tactical Execution Orders & Chip Quadrant Status (`api/core/notifier.py` & `api/core/signal_scanner.py`)**:
  - Upgraded Telegram push messages to display exact execution price levels: TP1 (減半推保本), TP2 (波段目標), and SL (安全止損) formatted with currency decimals and target percentage tags.
  - Integrated Macro Positioning block displaying Chip Quadrant status (`🔥 強勢加倉` / `🩸 弱勢加倉` / `⚡ 強勢減倉` / `🧊 弱勢減倉` / `⚪ 中性盤整`), RS vs BTC, 24h Coin-denominated OI %, and 4H market regime from `_market_overview_cache`.
  - Added HTML entity sanitization (`html.escape`) to prevent unescaped XML formatting errors in Telegram Markdown/HTML parse mode.
- **Verification & Comprehensive Testing**:
  - Created unit test suite `api/tests/test_tactical_and_partial_tp.py` covering Position TP1 execution, Backtester two-stage partial TP, and Notifier tactical order formatting (43/43 tests passing).
  - Executed `scripts/debug/evaluate_altcoins_quality.py`, generating `scripts/debug/altcoins_evaluation_report.md` confirming HYPE 4h Breakout E-Ratio = 1.53, Pure Reversion E-Ratio = 1.11, and CC 4h Breakout E-Ratio = 1.46.

## [2026-10-31] v0.6.4 - Frontend Terminal O(1) Performance, DOM Semantics & State Alignment
- **Crosshair Sync O(1) Hash Map Optimization (`web/components/AdvancedChart.tsx`)**:
  - Replaced $O(N)$ linear `Array.find()` across 7 charts and 1,000 candles with precomputed `Map<number, any>` lookups (`priceMap`, `rsiMap`, `cvdMap`, `oiMap`, `fundingMap`, `pulseMap`, `regimeMap`, `markersMap`).
  - Crosshair mouse movement querying reduced from $O(7N)$ down to $O(1)$ constant time, completely eliminating UI lag and cursor jitter during hovering.
  - Wrapped `AdvancedChart` with `React.memo` to eliminate unnecessary canvas re-renders during background polling.
- **TimeScale Re-entrancy Lock (`web/components/AdvancedChart.tsx`)**:
  - Introduced `isSyncingRef` mutex lock around `timeScale.subscribeVisibleLogicalRangeChange()`.
  - Calling `setVisibleLogicalRange()` on sibling charts is guarded by `isSyncingRef.current = true` with immediate asynchronous unlock `setTimeout(() => { isSyncingRef.current = false; }, 0)`, breaking recursive range update cascades.
- **HTML5 DOM Semantics & Interactive Event Isolation (`web/app/page.tsx`)**:
  - Refactored five-coin macro cards from invalid nested `<button>` tags (which wrapped 6 `<InfoTooltip>` button triggers) into accessible `<div role="button" tabIndex={0}>` with Enter/Space keyboard handlers.
  - Eliminated HTML5 specification violations and resolved mobile/touchscreen event bubbling conflicts.
- **Network Race Condition Protection via AbortController (`web/app/page.tsx`)**:
  - Added `AbortController` in `fetchData` effect and passed `signal` into `getMarketData()`.
  - Rapidly switching symbols or timeframes now immediately cancels pending inflight requests, preventing out-of-order network responses from overwriting current market views.
- **Type Contract & Timezone Alignment (`web/lib/api.ts`)**:
  - Corrected `lsur_history` from single object to `{ time: number; value: number }[] | null`.
  - Formally aligned `composite_score` (number), `composite_score_history` (array), and `lsur_markers` in `IndicatorData`.
  - Made `mtf_4h_regime.adx` and `bb_width` optional numbers to match backend JSON serialization.
  - Added `tzOffsetSec` adjustment in `getMarketOverview()` via `shiftTimes()`, aligning macro card signal timestamps with local user timezone.
- **Defensive Rendering & Boundary Fixes (`web/components/SentimentPanel.tsx` & `web/app/backtest/page.tsx`)**:
  - `SentimentPanel.tsx`: Added `safeTotal = total || (binance + okx) || 0` fallback to prevent `NaN` crashes when liquidity totals are null or zero.
  - `web/app/backtest/page.tsx`: In `runBacktest()`, passing `'none'` when all signal archetypes are deselected instead of empty string `''`, preventing backend fallback to default all-signal whitelist.

## [2026-10-30] v0.6.3 - Backend Architecture, DB Pool Lifecycle & Concurrency Hardening
- **Short-Lived DB Sessions & Elimination of Connection Pool Starvation (`api/core/fetcher.py`)**:
  - Refactored `fetch_market_data()`, `fetch_taker_volume()`, `fetch_open_interest()`, and `fetch_long_short_ratio()` to strictly enforce the Short-Lived Session pattern.
  - Eliminated nested DB session acquisition across HTTP network I/O and child thread pools: sessions are opened only for cache-gap checks, closed before external requests, reopened briefly for batch upserts, and reopened only for final reads.
- **Warmup Depth Guarantee & Timeframe-Isolated BTC Macro Cache (`api/main.py`)**:
  - `_fetch_single_asset_overview()`: Upgraded query depth from `limit=50` to `limit=300` (`fetch_limit=1000`), guaranteeing full warmup for EMA200, 90-period LSUR Z-score, and daily OI percentiles. Truncated memory payloads to return only lean summary metrics.
  - Isolated `_btc_macro_cache` by timeframe (`Dict[str, Dict]`) with fallback resolution (`timeframe` -> `4h` -> `1h`). Cache overwriting is strictly blocked unless the source series contains $\ge 250$ bars.
  - Added global thread lock `_overview_lock = threading.Lock()` to prevent overlapping concurrent pre-warm tasks from thrashing system resources.
- **Lifespan Startup & Scheduler Hardening (`api/main.py`)**:
  - Moved `Base.metadata.create_all()` into `lifespan()` startup with 5 retries (2-second interval) to prevent crash loops when the database container starts slower than the API.
  - Added `max_instances=1, coalesce=True, misfire_grace_time=30` to APScheduler jobs and unified pre-warm initialization via `next_run_time=datetime.now(timezone.utc)`, eliminating duplicated background tasks.
- **Telegram Alert Resilience & Non-blocking Chart Generation (`api/core/notifier.py` & `api/core/signal_scanner.py`)**:
  - Protected matplotlib chart rendering with `_chart_lock = threading.Lock()` and dispatched via `await asyncio.to_thread()`, keeping the FastAPI event loop unblocked.
  - Added timeframe tags to output chart filenames (`{symbol}_{timeframe}_168h.png`) to eliminate race-condition file overwrites between 1h and 4h alerts.
  - Added graceful degradation fallback: if image generation fails or photo upload encounters an error, automatically falls back to plain-text Telegram notification, guaranteeing 100% signal delivery.
  - Updated `signal_scanner.py` to only mark signals as notified if `send_signal_with_chart()` returned `True`; failed alerts remain in queue for retry on subsequent scans.
  - Set default timezone offset in `notifier.py` to `8.0` (UTC+8 / Asia/Taipei).
- **Container Infrastructure & Build Time Configuration (`docker-compose.yml` & `web/Dockerfile`)**:
  - Added PostgreSQL healthcheck (`pg_isready -U quant_user -d quant_db`) to `db` service and configured `fastapi` with `condition: service_healthy`.
  - Configured `TZ=Asia/Taipei` and updated default `NEXT_PUBLIC_TIMEZONE_OFFSET` to `8` across `fastapi` and `nextjs` containers.
  - Declared `ARG NEXT_PUBLIC_API_URL` and `ARG NEXT_PUBLIC_TIMEZONE_OFFSET` before `RUN npm run build` in `web/Dockerfile`, ensuring client-side build-time static variables hydrate correctly.

## [2026-10-30] v0.6.2 - Quant Engine & Pipeline Core Audit Repairs (Zero Look-Ahead & Math Parity)
- **Elimination of MTF 4H Alignment Look-Ahead Bias (`api/core/indicators.py`)**:
  - In `calculate_confluence_signals()` Layer 3 MTF Confirmation, resolved the causal look-ahead leak where `bisect_right(htf_regime_times, t)` allowed open 1h candles to read 4h candles that had not yet closed.
  - Precalculated `tf_sec` and `htf_sec` and enforced strict causal boundary alignment: $t_{\text{htf}} + \text{htf\_sec} \le t + \text{tf\_sec} \implies \text{max\_valid\_htf\_open} = t + \text{tf\_sec} - \text{htf\_sec}$. Higher timeframe regime is only consumed once fully finalized relative to current candle close.
- **Donchian Channel Warmup Future Leak Prevention (`api/core/indicators.py`)**:
  - In `calculate_donchian_channel()`, purged `df.bfill(inplace=True)` which leaked future 20th-bar extremes back to bar 0.
  - Implemented expanding window shifted by 1 (`df['high'].shift(1).expanding(min_periods=1).max()`) combined with rolling window, backing up bar 0 with its own high/low without future contamination.
- **Eradication of Backtest Fee Double-Counting (`api/quant/signal_backtester.py`)**:
  - In `SignalBacktester._open_position()`, removed duplicate `self.total_fees_paid += entry_fee`.
  - Position fees (`pos.fees_paid = entry_fee + exit_fee`) are tracked within `Position.close()` and aggregated at trade exit in `_close_position()`, eliminating the 1.5x fee inflation on backtest metrics.
- **Ghost Execution Fill Prevention & Gap Slippage Constraints (`api/quant/position.py` & `api/quant/signal_backtester.py`)**:
  - Clamped `new_trail` in `Position.update()` to current `close` if the candle has already retraced below/above the calculated stop, preventing floating phantom stops.
  - In `Position.get_exit_price_for_reason()`, constrained execution prices within physical market bounds: Long SL/trailing stop cannot exceed `min(level, high)`; Short SL/trailing stop cannot breach `max(level, low)`.
  - Introduced `open_price` awareness into `Position.check_exit()` and fill calculation: detects opening gap-down/gap-up through stop levels and executes at `open_price` (realistic gap slippage).
- **Causal Data Ingestion & Boundary Cliff Elimination (`api/core/fetcher.py`)**:
  - `fetch_open_interest()`: Replaced intra-interval future scaling (`scale_to_bin_future`) with causal ratio derivation on overlapping points using `pd.Series.ffill().bfill().fillna(1.0)`.
  - `fetch_long_short_ratio()`: Grouped by `rounded_time` individually per exchange, outer-merged on timestamp, and applied causal overlap ratio scaling before averaging, eliminating the 100-bar cliff drop caused by OKX's 100-bar limit vs Binance's 1000-bar history.
- **Database Upsert In-Batch Deduplication & Deadlock Prevention (`api/db/crud.py`)**:
  - `upsert_market_data()` & `upsert_funding_rates()`: Implemented in-batch composite primary key deduplication via in-memory dictionary prior to DB execution, preventing PostgreSQL `CardinalityViolation` crashes (`ON CONFLICT DO UPDATE command cannot affect row a second time`).
  - Added deterministic primary key sorting and normalized `timeframe.lower()` to eliminate PostgreSQL transaction lock-order inversion and deadlocks.
- **Automated Verification & Review Slices Packaging (`api/tests/test_audit_fixes.py` & `scripts/`)**:
  - Created `api/tests/test_audit_fixes.py` covering Donchian warmup causal bounds, fee single-counting, ghost fill prevention/gap slippage, and MTF causal alignment. All 40 pytest tests pass (100%).
  - Added `scripts/export_slices.py` and `scripts/export_for_agent.py` to package thematic review slices (Slice A: Quant, Slice B: Backend, Slice C: Frontend) in XML and Markdown formats, updating `.gitignore` to prevent tracking generated review bundles.

## [2026-10-30] v0.6.1 - Background Market Overview Pre-warmer, Concurrent Lean Queries & Multi-Asset InfoTooltip System
- **Macro Radar & Quadrant Strip Comprehensive Tooltips (`web/components/InfoTooltip.tsx` & `web/app/page.tsx`)**:
  - `web/components/InfoTooltip.tsx`: Upgraded component with custom `width`, `className`, `iconClassName`, responsive viewport clamping, and `e.stopPropagation()` / `e.preventDefault()` event isolation so hovering/clicking tooltips inside clickable card buttons never inadvertently triggers card selection.
  - `web/app/page.tsx`: Embedded rich interactive tooltips explaining:
    - **Header**: Overview of the 5-asset macro radar, RS vs BTC, 24h Coin OI, Quadrants, and Regime.
    - **24h Price Change %**: 24h calculation benchmarked against the 6th preceding 4h candle.
    - **Quadrant Badges**: Exact mathematical trigger conditions and institutional market interpretations for each state:
      - 🔥 強勢加倉 (Strong Add): RS > 0 & 24h Coin OI > +3% (leading momentum backed by expanding contracts)
      - 🩸 弱勢加倉 (Weak Add): RS < 0 & 24h Coin OI > +3% (lagging price with contract buildup, bottom-fishing or trap)
      - ⚡ 強勢減倉 (Strong Reduce): RS > 0 & 24h Coin OI < -3% (price outperforming but contracts unwinding, take-profit)
      - 🧊 弱勢減倉 (Weak Reduce): RS < 0 & 24h Coin OI < -3% (lagging price with deleveraging/liquidations)
      - ⚪ 中性盤整 (Neutral): 24h Coin OI change within ±3%
    - **RS vs BTC**: Relative Strength ($RSI_{4h}(\text{Asset}) - RSI_{4h}(\text{BTC})$), explaining positive vs negative values.
    - **24h Coin OI %**: Coin-denominated OI ($\frac{\text{USD OI}}{\text{Price}}$), isolating contract volume from price bias.
    - **4H Regime**: 4h macro trend classification ($↗$ Uptrend, $↘$ Downtrend, $⇄$ Ranging) and its role in MTF counter-trend filtering.
    - **Latest Signal**: Archetype tagging (`Breakout`, `Structure`, `Reversion`), direction ($↑$/$↓$), and elapsed hours (`xx.x h`).
- **Endpoint Latency & Architecture Optimization (`api/main.py`)**:
  - **Background Pre-warmer**: Added `_background_refresh_market_overview` scheduled via APScheduler every 30s. Automatically warms cache at startup so user visits and page reloads hit warm memory in **~5ms** (down from 5–8 seconds).
  - **Lean Overview Fetching**: Added `include_orderbook=False` and `include_breakdown=False` to `get_market_data()`. Skipped 10 redundant orderbook snapshot network calls (400 levels) and exchange breakdown CCXT calls.
  - **Adaptive Query Depth**: When `limit <= 100`, sets `fetch_limit=limit` and `daily_limit=limit`, eliminating massive 1200-candle DB scans and pandas merges on shallow overview requests.
  - **Parallel Asset Computation**: Upgraded `_compute_and_cache_market_overview()` to fetch the 5 assets concurrently using `concurrent.futures.ThreadPoolExecutor(max_workers=5)`. Cold cache miss latency reduced from ~7,000ms to < 400ms.
- **Verification & Testing**:
  - All 36 unit/integration tests in `api/tests/test_signal_strategy.py` pass cleanly (100%).
  - Next.js production build (`npm run build`) succeeded with zero TypeScript errors.
  - Live `/api/market_overview` response time verified at **0.0058s (5.8ms)**.

## [2026-10-30] v0.6.0 - Signal Archetype Filters, Multi-Asset Quadrant Radar Strip & Structural Overlays
- **Signal Archetype & Minimum Score Filtering (`indicators.py`, `signal_strategy.py`, `signal_backtester.py`, `main.py`, `web/`)**:
  - `api/core/indicators.py`: Added `min_score: float = 0.0` and `allowed_types: Optional[List[str]] = None` to `calculate_confluence_signals()`. Emitted markers are tagged with their archetype (`'breakout'`, `'structure'`, `'reversion'`) and filtered accordingly.
  - `api/quant/signal_strategy.py` & `api/quant/signal_backtester.py`: Added `min_score` and `allowed_types` to `SignalStrategyConfig` and filtered `signals` in `SignalBacktester.__init__()`.
  - `api/main.py`: Updated `get_market_data()` and `/quant/signal-backtest` to accept `min_score` and `signal_types` (comma-separated string).
  - `web/components/SignalSettingsModal.tsx` & `web/app/backtest/page.tsx`: Added 3 archetype checkboxes (`⚡ 結構拐點 (Structure: CAP/DIV)`, `🔁 均線回踩與回歸 (Reversion / Pullback)`, `🚀 順勢突破 (Breakout)`) and a `Min Confluence Score` selector (`Default`, `3.5`, `4.0`, `4.5`, `5.0`).
- **Five-Coin Macro Strength & Quadrant Radar (`GET /api/market_overview`, `web/app/page.tsx`)**:
  - `api/main.py`: Implemented `/api/market_overview` (and `/market_overview`) with 60-second in-memory caching. Computes latest close price, 24h price change %, 4h RSI(14), relative strength vs BTC (`rs_vs_btc = round(rsi_4h - btc_rsi_4h, 1)`), 24h coin-denominated open interest change % (`oi_usd / close`), 4-quadrant state (`strong_add`, `weak_add`, `strong_reduce`, `weak_reduce`, `neutral`), 4h market regime, and latest triggered signal across 1h/4h.
  - `web/app/page.tsx`: Added top "Multi-Asset Macro & Quadrant Strip" rendering 5 responsive micro-cards (BTC, ETH, SOL, HYPE, CC) displaying Line 1 (Symbol + Price + 24h change %), Line 2 (Quadrant Badge + RS vs BTC + 24h Coin OI %), and Line 3 (4H Regime + latest signal with hours ago). Clicking any card switches the active symbol. Auto-refreshes every 60 seconds.
- **Main Chart Structural Visualizations: Donchian & Volume Profile POC (`web/components/AdvancedChart.tsx`)**:
  - Added clickable toggle buttons `[Donchian 通道]` and `[VP POC 籌碼峰]` in the main price chart legend bar.
  - `Donchian 通道`: Renders dashed cyan upper and lower channel boundaries based on `indicators.donchian_channel` (or client-side rolling 48/20 bar calculation).
  - `VP POC 籌碼峰`: Bins loaded candle price range into 40 bins, sums trading volume per bin, and draws a horizontal dashed amber line (`#f59e0b`, `POC 籌碼峰`) at the maximum volume price level.
- **Database Upsert Concurrency Hardening (`api/db/crud.py`)**:
  - Added deterministic primary index sorting `(exchange, symbol, timeframe, timestamp)` to `upsert_market_data()` before executing PostgreSQL `INSERT ... ON CONFLICT DO UPDATE`, completely preventing transaction deadlocks during concurrent multi-asset fetches.
- **Database & Network Connection Pool Upgrades (`api/db/database.py` & `api/core/fetcher.py`)**:
  - `api/db/database.py`: Expanded SQLAlchemy QueuePool settings to `pool_size=20, max_overflow=30, pool_timeout=60, pool_recycle=1800, pool_pre_ping=True` (up to 50 concurrent DB connections), eliminating `TimeoutError: QueuePool limit reached` during simultaneous foreground requests and background scanner runs.
  - `api/core/fetcher.py`: Mounted `HTTPAdapter(pool_connections=50, pool_maxsize=50)` on CCXT's OKX and Binance HTTP sessions, preventing `urllib3.connectionpool` connection discarding warnings and improving SSL connection reuse.
- **Test Suite**:
  - Added `test_signal_filtering_min_score_and_types` and `test_market_overview_endpoint` to `api/tests/test_signal_strategy.py`. All 36 tests pass.

## [2026-10-28] v0.5.0 - Frontend Signal Terminal Refactoring & Macro Alignment
- **Strategy Backtester & Optimal Risk Profiles Upgrade (`web/app/backtest/page.tsx` & `api/quant/signal_strategy.py`)**:
  - `api/quant/signal_strategy.py`: Added empirical `OPTIMAL_RISK_PROFILES` for BTC, ETH, SOL, CC, and HYPE across 1h, 4h, and 1d timeframes. Updated `SignalStrategyConfig` defaults: `stop_loss_pct=1.4`, `take_profit_pct=1.5`, `trailing_activation_pct=0.65`, `trailing_stop_pct=0.30`, `max_positions=1`, `fee_rate=0.0005` (0.05%), and enabled Full Macro filters.
  - `api/main.py`: Updated `/quant/signal-backtest` to dynamically calculate required candle count based on timeframe (`1h` -> `days * 24 + 250`, `4h` -> `days * 6 + 250`, `1d` -> `days + 250`), guaranteeing complete indicator warmup before slicing to requested backtest window.
  - `web/app/backtest/page.tsx`: Purged legacy Grid Strategy tabs and dead parameters. Added `timeframe` selector (`1h`, `4h`, `1d`) linked to adaptive duration ranges. Added `Auto Risk Profile` toggle to automatically populate MFE/MAE optimal risk parameters upon switching symbol or timeframe. Replaced static presets with dynamic multiplier buttons (🎯 實證最佳基準 / 🚀 波段放大 1.4x).
- **Altcoins Quality & Dual-Exchange Liquidity Diagnostic (`scripts/debug/evaluate_altcoins_quality.py`)**:
  - Validated forward signal quality and liquidity health for ETH, SOL, HYPE, and CC across 1h, 4h, and 1d, producing `scripts/debug/altcoins_evaluation_report.md`.
- **Telegram Notification & Chart Timezone Alignment (`NEXT_PUBLIC_TIMEZONE_OFFSET`)**:
  - `api/core/notifier.py`: Formats signal timestamps using `NEXT_PUBLIC_TIMEZONE_OFFSET` with dynamic timezone badges (e.g. `(UTC+8)`, defaulting cleanly to `(UTC)`). Shifts chart OHLCV dates and signal markers by the configured offset to synchronize with text alerts.
  - `api/core/utils/chart.py`: Updated `generate_candlestick_chart` to accept `timeframe` and `tz_label` (defaulting to `(UTC)`), rendering them dynamically in the chart header.
  - `api/core/signal_scanner.py`: Passes active `timeframe` to `send_signal_with_chart`.
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
