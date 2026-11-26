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

Solo-Quant now runs as a **Dual-Mode Terminal** supporting both **Short/Swing Confluence (`legacy_v8`, default on load)** and **Macro Cycle Hold-to-Top (`macro_cycle` v1.6, 1D daily engine)** side-by-side without breaking backward compatibility.

### 2.1 The Signal-Driven Engine (v8 - Macro & Inflection Precision)
The core of the system generates `Bullish` and `Bearish` markers from `IndicatorEngine` v8, which are parsed by the `SignalBacktester` to execute trades and visualized on the dashboard.

- **Data Flow**: `get_market_data(limit=1000)` fetches OHLCV + Top Trader Position Ratio (`top_ls_position_ratio`, Binance Top 20% notional) + Global Account LSUR from DB (strictly normalized lowercase `timeframe`) -> `IndicatorEngine` calculates arrays using `lsur` as primary confluence input (`lsur_source="lsur"`; `top_ls` retained for UI divergence & optional diagnostic override) -> UI renders `AdvancedChart` / Backend runs `SignalBacktester`.
- **Multi-Layer Confluence Logic**:
  - **Unified Coin-Denominated OI & Uniform ATR Bounds (`api/core/indicators.py`)**: Computes coin-denominated OI change (`use_coin_oi_all=True`) and applies ATR-scaled dynamic bounds for EMA50 pullbacks/bounces (`-max(1.2, atr_pct * 1.1) <= low_ema_dist <= max(0.35, atr_pct * 0.3)` and mirrored short bounds) **uniformly across all symbols** (`BTC`, `ETH`, `SOL`, `HYPE`, `CC`). All 5 legacy `is_hype` bespoke rules and `use_legacy_hype_rules` toggle were formally deleted after Phase 2 Walk-Forward OOS pruning (`Variant B` improved Mean OOS Exp `+0.001% -> +0.046%` and `HYPE 4h` OOS `-0.872% -> +0.166%`), unifying `is_alt` (`HYPE`, `CC`) under shared `-10/+10` RSI offsets and standard breakout/reversion gates. Optional `price_group_cap` (`None` = standard additive cap `3.0`) and `single_trend_guard` (`False` = keep multi-layer EMA guards) remain available solely as ablation kwargs for `scripts/run_audit_experiments.py`.
  - **Symmetric `SETUP_WINDOW` State Machine (`setup_symmetry=True`) & CVD Degradation**: Tracks Bull/Bear setups independently with peak score retention across `SETUP_WINDOW` (tightened to 1 bar in 1h ranging markets), canceling an active setup only when the opposing bar is strictly stronger (and carries Structure or `>= 2.0` pts when opposing a Structure setup). When taker CVD is missing/stagnant, Breakout and CAP degrade gracefully to `VOL↑`/`VOL↓` + candle-body absorption checks.
  - **Reversion & Trend Pullback Engine**: RSI, BB, EMA, Funding for ranging regimes; native EMA50 support/resistance (`EMA支撐↑` / `EMA壓力↓`) with EMA200 trend alignment during trending regimes.
  - **Breakout Engine**: Dynamic Donchian Channels (48 bars for 1h/15m, 20 bars for 4h/1d), strict first-bar cross, volume & momentum confirmation, required OI expansion (`eff_oi_chg_pct > 0` for 1h/15m). Counter-trend breakouts strictly forbidden.
  - **Trend Protection Iron Laws**:
    - **Uptrend Strict Anti-Shorting**: Unconditional `no_short` blocking (no exemptions allowed).
    - **Multi-Layer Macro & 1h Bull Structure Guards**: `is_bull_macro_trend`/`is_bear_macro_trend` (`APPLY_DIRECTIONAL_PROTECTION=True`, `single_trend_guard=False`), plus 24-bar rising EMA200 (`ema200_rising`) and 4h MTF direction blocking counter-trend shorts in 1h/15m bull grind.
    - **Extreme Inflection Exemption**: Exemptions to `no_long / no_short` strictly require 4-fold extreme resonance (`Structure` + `RSI < 28 / > 72` + `BB < 0.05 / > 0.95` + `score >= threshold + 1.5`).
  - **Layer 1 Capitulation Detector (`CAP↑`/`CAP↓`)**: Dynamic OI drop thresholds (BTC -4.5%, Midcaps -7%, Alts -10%) + CVD accumulation (or candle body fallback) + absorption price action (wick / candle body direction).
  - **Layer 2 CVD Divergence (`DIV↑`/`DIV↓`)**: Volume-price structural divergence with recency constraint (`min`/`max` within last 2 bars) and price action confirmation.
  - **Layer 3 MTF Confirmation (`[4h✓]`)**: Strictly causal candle-close aligned 4h regime lookup (`htf_cutoff = t + tf_sec - htf_sec` when `mtf_close_aligned=True`), ensuring 1h candles never observe unclosed 4h bars.
  - **Layer 4 BTC Macro Regime Filter**: Strictly causal per-bar `btc_macro_history` lookup (`cutoff_btc = t + tf_sec - btc_tf_sec`; single-bar `_btc_macro_cache` fallback only for live requests when history is unavailable): BTC trending down or overbought (pulse ≥ 80) raises altcoin long threshold (+1.0); BTC trending up or oversold (pulse ≤ 20) raises altcoin short threshold (+1.0).
  - **Macro Leverage Multiplier**: Rolling OI percentile (90 bars) dynamically scales `CAP`/`DIV` structural weights (2.0x when OI pct ≥ 80 with extreme funding; 1.0x when OI pct ≤ 20).
- **Execution Architecture: Single Full TP, OHLC/Conservative Trailing & Realistic Friction (`Position` & `SignalBacktester`)**:
  - **Single Full TP as Default (`enable_partial_tp = False`)**: Validated in Exit Architecture stress testing (`SingleFullTP_Narrow` dominated `PartialTP+1.0xATR/1.5xATR/WidePct` under 5/15 bps + funding). Two-stage partial TP remains available via config flag (with sequential `tp1_partial -> tp2` ordering on continuous breakout bars).
  - **No-Clamp Trailing Stop & Intra-Bar Path Check**: Removed artificial `close * 0.999` / `close * 1.001` clamps in `Position.update()` so `trailing_stop_price` ratchets strictly monotonically using `candidate_trail` (with breakeven floor `entry * 1.002` / `0.998`). After `Position.update()`, `Position.check_intraday_trailing_exit()` evaluates same-candle trailing breaches under `'ohlc'` (production default: close cross or directional reversal extreme breach) or `'conservative'` (audit stress mode: any intra-bar low/high breach).
  - **Physical Execution & Transaction Friction**:
    - Step A: `pos.check_exit()` evaluates existing levels from prior bars or opening gap (`open_price` fill on gap-through; physical bounds `min(level, high)` / `max(level, low)` otherwise).
    - Step B: If not exited in Step A, evaluates optional TP1 partial fill, ratchets trailing stops via `pos.update()`, and checks `pos.check_intraday_trailing_exit()`.
    - **Slippage & Funding PnL**: Applies one-way adverse `slippage_bps` (`5.0` bps default) on market/stop fills (`open`, `sl`, `trailing`, `signal_reverse`; exempt on limit `tp`/`tp1_partial`) and settles historical `FundingRate` PnL (`include_funding=True` default) on open positions across crossed settlement timestamps.
- **Unified Capital Return Formula**: Standardized capital return across `execute_partial_tp` and `_close_position` to `returned_cash = closed_cost + raw_pnl - exit_fee` for both Long and Short, completely preventing balance drift.
- **Dynamic TP & Risk-Based Sizing**: Precomputed 14-period Wilder's ATR; 1.15x `take_profit_pct` multiplier applied to Structure and Breakout trades. Capital allocation safely divided by `max_positions` (`current_equity * 0.95 / max_positions`).
- **Signal Quality Metrics & Empirical Risk Calibration**: Backtester computes Forward Return MFE/MAE (`avg_mfe_pct`, `avg_mae_pct`). Risk profiles are empirically calibrated:
  - **BTC 1h**: SL 1.2%, TP 1.80%, Trail Act 0.60%, Trail Stop 0.25% (68.8% WR)
  - **BTC 4h**: SL 2.0%, TP 3.80%, Trail Act 1.50%, Trail Stop 0.40% (55.6% WR, PF 1.19)
  - **ETH 4h**: SL 2.8%, TP 3.80%, Trail Act 1.60%, Trail Stop 0.65% (66.7% WR, PF 1.54)
  - **SOL 4h**: SL 3.5%, TP 3.80%, Trail Act 1.65%, Trail Stop 0.65% (60.0% WR, PF 1.20)
  - **HYPE 4h**: SL 5.5%, TP 5.20%, Trail Act 2.20%, Trail Stop 0.50% (83.3% WR, PF 1.65)
  - **HYPE 1h**: SL 2.4%, TP 2.80%, Trail Act 1.20%, Trail Stop 0.35% (83.3% WR, PF 2.04)

### 2.1.2 Dual-Mode Macro Cycle Engine (`macro_cycle` v1.6 — `Cycle_P_v16_1d`)
Self-contained, strictly causal 1D secular cycle engine (`api/core/macro_cycle.py` + `api/quant/macro_cycle_backtester.py`), promoted into production after passing Phase 1.6 (`4/5 PASS` / `VALIDATED_PRICE_CYCLE`; `15 bps` Pooled `PF = 2.00`, EW `+213.63%`, EW `MAR = 0.77` vs Buy & Hold `0.70`, OOS bear MaxDD `21.44%` vs `56.95%`).
- **API Mode Selection**: `strategy_mode` query/body param on `GET /market/{symbol}`, `_get_market_data_impl()`, and `POST /quant/signal-backtest` (`"legacy_v8"` default | `"macro_cycle"`, HTTP `400` on invalid value).
- **Pure-Price Asymmetric Cycle Rules (Long-Flat)**:
  - **Entries** (10-bar post-exit cooldown, `0.95x` notional): `BEAR_BOTTOM_V16` (180d adaptive DD `0.30..0.52` or `<= 0.78*EMA200` + `RSI10d <= 33` -> `EMA20 > EMA50`, rising `EMA50`, breakout), `REGIONAL_BOTTOM_V16` (`EMA50 > EMA200`, rising `EMA200`, 90d dip -> reclaim `EMA50` & 20d high), `STAGE2_IGNITION_V16` (`EMA20 > EMA50 > EMA200` aligned + 60d breakout below `1.40x EMA200`).
  - **Exits**: Early-only pre-close `BASE_INVALIDATION_V16` (`max(entry - 3*ATR14, low20 * 0.98)`, automatically disabled forever once trade gain reaches `+25%`), adaptive Mayer-Multiple euphoria exit `EUPHORIA_TOP_V16` (peak gain `>= +45%`, `mayer_10d >= clip(1 + 12*atr_pct_med60, 1.55, 2.20)`, ext ATR `>= 5.5`, `RSI >= 76` within 30d -> close `< EMA20` & `< 20d low`), and `REGIME_BEAR_EXIT_V16` (`close < EMA50`, `EMA20 < EMA50`, `< 30d low`, and `< EMA200` or falling `EMA50`).
- **UI-Only Left-Side Derivative Context**: Because Phase 1.6 `H4` proved adding hard derivative gates produced identical `28` trades (`p = 1.0000`), `coin_oi_dd_60d`, `coin_oi_pct_180d`, `fr_7d_mean_pct`, and `lsur_z_90d` are computed causally for UI badges and Telegram alert context without blocking price signals.
- **Full-History Fetcher Guard (`api/core/fetcher.py`)**: `_full_history_exhausted` and `_funding_history_exhausted` (6h cooldown) prevent repeated OKX full-history pagination loops when requesting `limit=1800`/`2000` on newer listings (`HYPE`, `CC`).

### 2.2 Signal Notification System (Telegram v8 + Daily 1D Macro Cycle)
Dual event-driven notification pipelines embedded within the FastAPI container (`api/core/notifier.py` + `api/core/signal_scanner.py`):

- **v8 Short/Swing Schedule**: `APScheduler` `CronTrigger(minute="0,15,30,45", second="25")` scans `MONITORED_TIMEFRAMES = ["1h", "4h"]` (4h at `:00:25` UTC on 4-hour multiples; 1h quarterly/hourly).
- **Daily 1D Macro Cycle Schedule**: `APScheduler` `CronTrigger(hour=0, minute=5, second=0, timezone="UTC")` (`08:05 UTC+8`) runs `scan_macro_cycle_and_notify()` (`limit=1800`, `strategy_mode="macro_cycle"`), strictly ignoring unclosed 1D bars (`now < latest_candle_time + 86400`), deduplicating `(time, cycle_event)` over a 48h window, formatting via `format_macro_cycle_message()` (Base Stop + `+25%` auto-disable note, realized PnL / peak MFE / hold days, left-side derivative summary), and rendering custom-color 1D charts (`%y/%m\n%d`). Manual trigger via `POST /notifications/scan-macro-now`.
- **Tactical Execution Orders, Sizing & Macro Positioning (v8)**: Telegram alert messages calculate and display exact SL, TP1 (追蹤啟動 / 可選減半推保本), and TP2 (全倉波段目標) execution order prices aligned with `Single Full TP` default (`enable_partial_tp=False`), notional sizing / effective leverage risk caps (`1%~2%` equity risk, `<= 0.95x`), cross-symbol correlation warning (`>= 3` symbols firing same direction within 4h), and the asset's Macro Quadrant status (`🔥 強勢加倉` / `🩸 弱勢加倉` / `⚡ 強勢減倉` / `🧊 弱勢減倉` / `⚪ 中性盤整`), RS vs BTC, 24h Coin OI %, and 4H regime.
- **Full Macro Defaults**: Scans default to `enable_protection=True`, `enable_mtf_filter=True`, and `enable_macro_cycle_alerts=True` (`allow_live_btc_cache=False`, computing causal BTC macro history per scan).
- **Candle Close Confirmation**: Closed-candle confirmation is enforced by default (`_allow_intraday_prealert = False`, anti-repainting for v8; always strict closed-candle for 1D Macro Cycle); unclosed latest v8 candles are suppressed unless `allow_intraday_prealert=True` is enabled via `/notifications/config` (in which case only high-conviction `score >= 5.0` or `CAP`/`DIV` emit `[盤中未收線預警]`).
- **Dedup & Reliability**: Tracks `(signal_time, strategy_type)` (and `("prealert", time, strategy_type)` for v8 pre-alerts) / `(time, cycle_event)` for Macro Cycle only after successful dispatch (`sent_ok is True`); failed alerts are retained for retry.
- **BTC Macro Scanning Sequence**: Scans BTC first so DB history is fresh before altcoins compute causal `btc_macro_history`.
- **Resilient Message Dispatch & Thread Safety**: Chart generation is thread-safe (`_chart_lock = threading.Lock()`) and non-blocking (`asyncio.to_thread`). Output files include timeframe (`{symbol}_{timeframe}_168h.png`) to prevent 1h/4h/1d overwrite races. If chart rendering or photo upload fails, automatically degrades to plain-text notification, guaranteeing 100% alert delivery.
- **Timezone Default**: Timezone defaults to `8.0` (UTC+8 / Asia/Taipei), configurable via `NEXT_PUBLIC_TIMEZONE_OFFSET`.
- **Config API**: `GET/POST /notifications/config` (exposes `enable_macro_cycle_alerts`, `macro_cycle_schedule`, `enable_mtf_filter`, `enable_protection`, `allow_intraday_prealert`, `monitored_symbols`), plus `POST /notifications/scan-now` and `POST /notifications/scan-macro-now`.

### 2.3 Frontend Terminal Architecture (Crypto Macro & Signal Terminal)
The frontend (`web/`) is streamlined into a dual-mode decision cockpit for market intelligence:
- **Main Terminal (`web/app/page.tsx`)**: Defaults to `strategyMode = 'legacy_v8'` + `'4h'` K-lines on load (`1000` bars, 15s poll) with a header segmented switcher (`⚡ v8 短波段` ↔ `🌊 大週期 (1D)`) that seamlessly switches to `macro_cycle` (`1d`, `limit=1800`, 60s poll) and restores the prior short-term timeframe when toggling back. Employs `AbortController` in `fetchData` effect so fast switching immediately aborts stale pending requests.
- **Recent Signals Radar**: Right-column card displaying the latest 10 signals/cycle events from `lsur_markers` with mode-aware dates (`MM/DD HH:mm` for v8, `YYYY/MM/DD` for Macro Cycle), rich badges (`🐻 熊市大底`, `💎 回調大底`, `🚀 主升浪啟動`, `🔥 過熱逃頂`, `🛡️ 轉熊防線`, `⚠️ 結構止損`, plus v8 `🚀 BREAKOUT`, `⚡ STRUCTURE`, `🟢 BUY / 🔴 SELL`), asset-precision trigger prices, and indicator details.
- **Macro Cycle Visuals (`AdvancedChart.tsx` & `SentimentPanel.tsx` & `NotificationSettingsModal.tsx`)**: In `macro_cycle` mode, `AdvancedChart.tsx` overlays `EMA20` (`#22d3ee`), translucent background risk bands (`✓ 左側警戒帶` on isolated hidden `cycle-zones` scale so candlestick pricing and 7-chart crosshair sync stay undistorted), enlarged arrows with short labels, and hover Mayer/zone readouts; `SentimentPanel.tsx` surfaces the top **`🌊 宏觀大週期位階 (Macro Cycle v1.6)`** status card (live position PnL/MFE/Base Stop, Mayer vs threshold, 180d DD, EMA alignment) plus auxiliary derivative context; `NotificationSettingsModal.tsx` exposes the daily 1D Macro Cycle push toggle.
- **Five-Coin Macro & Quadrant Strip (`web/app/page.tsx` & `/api/market_overview`)**: Top horizontal radar bar rendering 5 micro-cards (BTC, ETH, SOL, HYPE, CC) displaying 24h price change %, 4h RSI, relative strength vs BTC (`rs_vs_btc`), 24h coin-denominated open interest change % (`oi_coin_change_24h_pct`), 4-quadrant state badges (`🔥 強勢加倉` / `🩸 弱勢加倉` / `⚡ 強勢減倉` / `🧊 弱勢減倉` / `⚪ 中性盤整`), 4H regime, and latest signal. Built with semantic `<div role="button" tabIndex={0}>` avoiding HTML5 nested button violations with inner `InfoTooltip` instances. Equipped with rich, non-intrusive `InfoTooltip` explainers on every metric (24h Price Change, Quadrant triggers, RS vs BTC, 24h Coin OI %, 4H Regime, and Latest Signal with elapsed hours).
- **Background Pre-warmer & Ultra-Low Latency Overview (`api/main.py`)**: APScheduler runs `_background_refresh_market_overview` every 30s in the background with `_overview_lock` concurrency protection, keeping memory cache warm. User page reloads hit cache in **< 6ms** (reduced from 5–8 seconds). Calls `get_market_data` with `limit=300` (`fetch_limit=1000`) guaranteeing complete warmup for EMA200 and rolling indicators, and truncates memory payloads to lean summary metrics.
- **Timeframe-Isolated BTC Macro Cache**: `_btc_macro_cache` is isolated by timeframe (`Dict[str, Dict]`) with fallback resolution (`tf` -> `4h` -> `1h`). Only updates if data length $\ge 250$ bars, eliminating under-warmed cache pollution.
- **High-Performance 7-Chart Crosshair Sync (`AdvancedChart.tsx`)**:
  - Replaced $O(N)$ linear `Array.find()` lookups with precomputed `Map<number, any>` indices (`priceMap`, `rsiMap`, `cvdMap`, `oiMap`, etc.), achieving $O(1)$ constant-time point lookup across all 7 charts on every mouse movement.
  - Added `isSyncingRef` mutex to `timeScale.subscribeVisibleLogicalRangeChange()` with `setTimeout` unlock, completely breaking recursive range synchronization loops.
  - Wrapped `AdvancedChart` with `React.memo` to eliminate unnecessary full-canvas redraws during 15s/60s background polling.
- **Structural Overlays (`AdvancedChart.tsx`)**: Main price chart legend bar includes one-click toggles for `Donchian 通道` (cyan dashed bands) and `VP POC 籌碼峰` (40-bin volume-weighted Point of Control horizontal amber line `#f59e0b`).
- **Signal Archetype & Minimum Score Filters (`web/components/SignalSettingsModal.tsx` & `web/app/backtest/page.tsx`)**: Checkboxes for `Structure (CAP/DIV)`, `Reversion / Pullback`, `Breakout`, and dropdown for `Min Confluence Score` (Default, 3.5, 4.0, 4.5, 5.0) wired through both the live terminal and backtester. When all types are deselected in backtesting, sends `'none'` to respect strict zero-selection instead of defaulting to all signals.
- **4H MTF & Long/Short Positioning (`SentimentPanel.tsx`, `AdvancedChart.tsx`)**: Surfaces `mtf_4h_regime` in the `Market Regime` card header right side (`4H: Trending ↑` emerald, `4H: Trending ↓` red, `4H: Ranging` amber). Displays a unified **Positioning** card contrasting **Binance Top 20% Trader Position Ratio** (`top_ls_ratio`, Z-score, Long/Short % bar) vs **Global Account LSUR** (`lsur_ratio`, `lsur_z_score`) with Smart Money Divergence detection. In `AdvancedChart.tsx`, overlays Whale Position Ratio (`#38bdf8`) and Retail LSUR (`#e879f9`) on the `Open Interest` subchart via a hidden independent `leftPriceScale` (`scaleMargins: { top: 0.1, bottom: 0.15 }`, keeping plot widths identical across all 7 charts), plus `1.0` equilibrium dotted line, toggle buttons, and O(1) legend tracking. Defends liquidity total calculations against `NaN` (`const safeTotal = total || (binance + okx) || 0`).
- **Unified Terminal Loader**: Replaced fragmented multi-block loaders and artificial 600ms delays with a single full-workspace dark loading screen (radar pulse & asset/timeframe pill). On data arrival, all 3 panels (Chart, SentimentPanel, Recent Signals) hydrate atomically in the exact same render frame.
- **Chart Polish (`AdvancedChart.tsx`)**: Removed TradingView attribution logo (`attributionLogo: false`) to prevent overlap with the 7th subchart (`Market Regime`), and expanded main price chart height to 460px (`h-[460px]`).
- **Full Macro Defaults**: Frontend initializes with `enableProtection: true` and `enableMtfFilter: true`.
- **Strategy Backtester (`web/app/backtest/page.tsx`)**: Upgraded to a Dual-Mode Signal Strategy Terminal (`⚡ v8 短波段策略` vs `🌊 大週期策略 (1D)`). Preserves v8 multi-timeframe (`1h`, `4h`, `1d`) + empirical `OPTIMAL_RISK_PROFILES` + dynamic relative multiplier buttons, while `macro_cycle` locks 1D (`180d..1600d Full Cycle`), surfaces fixed v1.6 rules, and adds a benchmark card strip (`CAGR`, `MAR Ratio`, `Avg Hold Days`, `Time in Market %`, `Buy & Hold Return / MaxDD`).

---

## 3. Crucial Principles & Gotchas (READ BEFORE CODING)
To prevent regressions, **ALL future AI Agents MUST adhere to these rules**:

1. **Indicator Path-Dependence Parity (1000-candle Warmup)**:
   - *Rule*: **ALWAYS** fetch `limit=1000` candles for indicator calculation. When aggregating higher timeframes (e.g. 4h), query `limit * tf_ratio` raw points to guarantee a full 1000 aggregated bars.
2. **Strict Time Alignment & Zero Look-Ahead Bias**:
   - *Rule*: Indicators must be strictly causal (rolling windows `<= current_bar`). Donchian warmup uses expanding windows shifted by 1 (no `bfill`). MTF alignment strictly enforces $t_{\text{htf}} + \text{htf\_sec} \le t + \text{tf\_sec}$ so 1h candles never observe unclosed 4h candles. Trailing stops in backtesting must be evaluated against the previous bar's ratcheted price before applying current-bar highs/lows.
3. **Cross-Exchange OI Merging & Liquidity Sources**:
   - *Gotcha*: Binance and OKX have different historical depth limits. Directly summing or averaging unaligned series causes artificial jumps at boundary points (e.g. OKX 100-bar limit). Furthermore, OKX daily candles close at 16:00 UTC (modulo 86400 == 57600), so filtering by `ts % 86400 == 0` drops all daily data.
   - *Rule*: For live breakdown, use `get_exchange_breakdown()` with in-memory caching. For historical OI and Long/Short series, outer-merge on timestamp, apply `ffill(limit=2)`, and apply strictly causal forward overlap ratio scaling (`ffill().fillna(1.0)`, NEVER `.bfill()`) to guarantee zero future scaling leakage and zero artificial cliff jumps.
4. **Local Time vs UTC Formatting**:
   - *Gotcha*: If timestamps have already been shifted for local timezone display (e.g., in `runSignalBacktest()`), frontend formatters must specify `{ timeZone: 'UTC' }` to avoid double-offset (+16h).
5. **API Contract Validation (Frontend ↔ Backend)**:
   - *Rule*: Always verify that TypeScript interfaces mirror the exact field names returned by FastAPI before deploying UI changes.
6. **PostgreSQL Concurrent Upsert, Lowercase Timeframe Parity & Cardinality Prevention**:
   - *Gotcha*: Bulk `INSERT ... ON CONFLICT DO UPDATE` across concurrent asynchronous transactions causes PostgreSQL deadlocks on index tuples if rows are inserted in varying order. Furthermore, passing duplicate primary keys in the same batch triggers PostgreSQL `CardinalityViolation` (`ON CONFLICT DO UPDATE command cannot affect row a second time`). And querying uppercase `'1H'`/`'1D'` when upserts write lowercase `'1h'`/`'1d'` silently returns stale frozen data (`LSUR Z-Score = 0.00`).
   - *Rule*: Always deduplicate records in memory by `(exchange, symbol, timeframe, timestamp)` and sort deterministically by primary index elements before executing `stmt.on_conflict_do_update()`. Normalize `timeframe` to lowercase on **both** upserts and reads (`crud.get_market_data`), and keep `top_ls_position_ratio` strictly Binance-exclusive (incompatible with OKX margin usage ratio; keep `lsur` as primary `lsur_source` default and retain `top_ls` for diagnostics).
7. **Database Connection Pool Sizing**:
   - *Rule*: With parallel thread pools inside `get_market_data()` (10 worker threads) and background scanners, maintain `pool_size >= 20` and `max_overflow >= 30` (up to 50 concurrent DB connections) with `pool_pre_ping=True` in `api/db/database.py` to prevent `QueuePool limit reached` timeouts.
8. **Physical Execution Bounds, No-Clamp Trailing & Slippage/Funding in Backtester**:
   - *Rule*: Backtester exit execution must respect market physics: Long stops fill at `min(level, high)` and Short stops fill at `max(level, low)`. Opening gap-throughs fill at `open_price`. `Position.update()` must NOT clamp trailing stops to `close * 0.999` / `close * 1.001`; same-bar trailing exits are evaluated physically via `check_intraday_trailing_exit()` (`ohlc` or `conservative`). Market/stop executions (`open`, `sl`, `trailing`, `signal_reverse`) apply adverse `slippage_bps` (`tp` limit fills do not), and entry fees must only be aggregated upon position closing to prevent double-counting.
9. **Short-Lived Database Sessions (Zero Connection Leaks)**:
   - *Rule*: Never hold a SQLAlchemy `SessionLocal()` across external network calls (CCXT / REST) or child thread pools. Follow the 3-step lifecycle: 1. Check cache gap in short session -> 2. Network I/O outside DB -> 3. Upsert batch in short session -> 4. Read final series in short session -> 5. Process in memory.
10. **Telegram Push Resiliency & Graceful Degradation**:
    - *Rule*: Protect matplotlib with thread locks (`_chart_lock`), dispatch via `asyncio.to_thread`, tag chart filenames with timeframe (`{symbol}_{tf}_168h.png`), and always fallback to plain-text messages if rendering or photo delivery fails. Only mark signals as notified (`notified_set.add`) upon verified successful dispatch.
11. **Dual-Mode Contracts, AST Parity & Timestamp Shifting (`api/main.py`, `web/lib/api.ts`)**:
    - *Rule*: Keep `strategy_mode="legacy_v8"` and `lsur_source="lsur"` as backward-compatible defaults on `SignalBacktestParams`, `get_market_data()`, and `_get_market_data_impl()`. Maintain **exactly one** `get_market_data(...)` call inside `run_signal_backtest()` passing `lsur_source=params.lsur_source` (guarded by `test_api_main_lsur_source_default_ast`), initialize `macro_cycle_state`, `macro_cycle_zones`, and `ema_20` before the `if price_data:` branch for empty-price JSON safety (`allow_nan=False`), and note that frontend `shiftTimes()` only shifts fields named `time` (`active_position.entry_time` requires explicit `getTimezoneOffsetSec()` before UTC formatting).
12. **Fetcher History Limit Guard & Next.js Container Rebuilds**:
    - *Gotcha*: Requesting `limit=1800` for `macro_cycle` on coins with shorter DB history triggers full OKX pagination loops on every poll unless guarded; additionally, `docker-compose.yml` only bind-mounts `.:/app` onto `fastapi`, NOT `nextjs`.
    - *Rule*: Preserve `_full_history_exhausted` / `_funding_history_exhausted` cooldowns in `api/core/fetcher.py`, and always rebuild the frontend container (`docker compose up -d --build nextjs`) after `web/` edits so `localhost:3000` serves updated bundles.

---

## 4. Current Development Focus (The "Next")
### Goal: Dual-Mode Stabilization, Live Paper Trading & Macro Monitoring

**Context**: Solo-Quant now ships **v0.8.0 (Dual-Mode Terminal: `legacy_v8` 1h/4h + `macro_cycle` v1.6 1D)**:
- Data ingestion and cross-exchange aggregation fixed (no `.bfill()`, 4h warmup aligned, full-history exhaustion guarded).
- Backtest engine look-ahead bias eliminated; MFE/MAE, slippage, and `FundingRate` PnL integrated across both v8 and Macro Cycle modes.
- IndicatorEngine v8 pruned via Walk-Forward OOS (`is_hype` hacks deleted, `lsur` retained) alongside self-contained pure-price `Cycle_P_v16_1d` (`4/5 PASS` / `VALIDATED_PRICE_CYCLE`).
- Dual Telegram scanners active (15-min `1h/4h` v8 + daily `00:05 UTC` `1d` Macro Cycle, both strictly closed-candle confirmed).
- Frontend defaults to `4h` `legacy_v8` with top segmented switcher into `🌊 大週期 (1D)` and `/backtest` full-cycle simulation (`113 passed` tests).

### 4.1 Completed Phases ✅
- Phase A: Data Ingestion & Backtest Engine Accuracy
- Phase B: IndicatorEngine v8 Upgrade
- Phase C: Telegram Signal Scanner & Frontend Alignment
- Phase D: Multi-Year Cross-Regime Validation & Execution Tuning
- Phase E: Empirical Risk Profile Calibration & Red-Team Audit / OOS Pruning (`v0.7.0`)
- Phase F: Macro Cycle Research (`Phase 1 -> 1.5 -> 1.6 Cycle_P_v16_1d`) & Dual-Mode Production Integration (`v0.8.0`)

### 4.2 Next Goals (Phase 6+)
1. **Monitor Daily `00:05 UTC` Macro Cycle Alerts & Live Slippage**: Track closed 1D signals across BTC/ETH/SOL/HYPE/CC in production and optionally connect dry-run/demo execution to compare realized slippage vs backtest assumptions (`5–15 bps`).
2. **Orderbook Liquidity Imbalance (Layer 5)**: Periodic depth/orderbook snapshot ingestion into DB for institutional orderflow absorption scoring.
3. **Portfolio-Level Multi-Asset Allocation**: Explore cross-asset equal-weight / volatility-targeted sizing on top of validated `Cycle_P_v16_1d` signals.

---

## 5. AI Agent Prompt (Copy-Paste to start next session)
*Copy the prompt below to hand off this exact context to the next AI session:*

「請扮演一位資深的全端工程師及加密貨幣分析師。請先閱讀 `SKILL.md` 與 `AI_HANDOFF.md` 以了解專案架構、核心理念與避坑規則。

目前系統已升級至 **Solo-Quant v0.8.0 (Dual-Mode: `legacy_v8` 短波段 + `macro_cycle` v1.6 大週期)**，前後端與 Telegram 雙排程均已驗證上線（`113 passed`）。

**任務：雙模式實盤追蹤與下一階段演化 (Phase 6+)**
1. 監控 Telegram 每日 `00:05 UTC`（`08:05 UTC+8`）`macro_cycle (1d)` 收盤訊號與既有 `1h/4h` v8 推播品質。
2. 遵循開發鐵則：零未來函數、嚴守 `strategy_mode="legacy_v8"` 與 `lsur_source="lsur"` 向後相容、確保前後端 API 型別一致，修改 `web/` 後務必重建 `nextjs` 容器。」


