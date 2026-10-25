# Solo-Quant Project Context & AI Handoff

This document is the **Context Buffer** for AI Agents. It defines how the system works *right now*, the critical rules to avoid regressions, and the immediate next goal.
*Note: For historical updates, please refer to `CHANGELOG.md`.*
*Note: For general domain knowledge, trading philosophy, and coding standards, ALWAYS review `@[.github/skills/skill-quant-trading/SKILL.md]`.*

---

## 1. Project Overview & Tech Stack
**Solo-Quant** is a cryptocurrency algorithmic trading platform focused on Multi-indicator Confluence Analysis and Signal-Driven Backtesting.
- **Backend**: Python 3.11, FastAPI, Pandas, NumPy, CCXT. (Run via `docker compose up api`)
- **Frontend**: Next.js 16 (App Router), TypeScript, Tailwind CSS, Lightweight Charts. (Run via `docker compose up web`)
- **Architecture**: Dual-mode (Grid-based Legacy vs. Signal-Driven Modern).

---

## 2. Current Architecture (The "Now")

### 2.1 The Signal-Driven Engine (v8 - Macro & Inflection Precision)
The core of the system generates `Bullish` and `Bearish` markers from `IndicatorEngine` v8, which are parsed by the `SignalBacktester` to execute trades and visualized on the dashboard.

- **Data Flow**: `get_market_data(limit=1000)` fetches OHLCV from DB -> `IndicatorEngine` calculates arrays -> UI renders `AdvancedChart` / Backend runs `SignalBacktester`.
- **Multi-Layer Confluence Logic**:
  - **Reversion Engine**: RSI, BB, EMA, Funding for ranging regimes.
  - **Breakout Engine**: Donchian Channels, MACD, CVD for trend continuations (requires `'Structure'` confirmation when counter to 4h MTF trend).
  - **Layer 1 Capitulation Detector (`CAP↑`/`CAP↓`)**: Dynamic OI drop thresholds (BTC -4.5%, Midcaps -7%, Alts -10%) + CVD accumulation + absorption price action (wick / candle body direction).
  - **Layer 2 CVD Divergence (`DIV↑`/`DIV↓`)**: Volume-price structural divergence with recency constraint (`min`/`max` within last 2 bars) and price action confirmation.
  - **Layer 3 MTF Confirmation (`[4h✓]`)**: 4h regime direction blocks counter-trend 1h reversion signals.
  - **Layer 4 BTC Macro Regime Filter**: BTC trending down or overbought (pulse ≥ 80) increases altcoin long threshold (+1.0); BTC trending up or oversold (pulse ≤ 20) increases altcoin short threshold (+1.0).
  - **Macro Leverage Multiplier**: Rolling OI percentile (90 bars) dynamically scales `CAP`/`DIV` structural weights (2.0x when OI pct ≥ 80 with extreme funding; 1.0x when OI pct ≤ 20).
- **Position Lifecycle & Zero Look-Ahead Bias**: In `api/quant/signal_backtester.py`, `_process_exits()` strictly calls `pos.check_exit()` *before* `pos.update()`. Stop Loss -> Take Profit -> Trailing Stop (evaluated using previous-bar ratchet).
- **Capital Allocation**: Position size safely divided by `max_positions` (`current_equity * 0.95 / max_positions`).
- **Signal Quality Metrics**: Backtester computes Forward Return MFE/MAE (`avg_mfe_pct`, `avg_mae_pct`).

### 2.2 Signal Notification System (Telegram v8)
An event-driven notification pipeline embedded within the FastAPI container.

- **Modules**: `api/core/notifier.py` + `api/core/signal_scanner.py`.
- **Schedule**: `APScheduler` with `CronTrigger(minute="0,15,30,45")`. Worker I/O offloaded to thread pool (`asyncio.to_thread`).
- **Candle Close Confirmation**: Intra-bar 1h signals broadcast only if high conviction (`score >= 5.0` or structural `CAP`/`DIV`). Otherwise, alerts are broadcast only after the candle closes.
- **Dedup**: Tracks `(signal_time, strategy_type)` to avoid intra-bar alerts cannibalizing final closed candle signals.
- **BTC Macro Scanning Sequence**: Scans BTC first to cache and propagate `btc_macro_regime` to monitored altcoins.
- **Message Format**: `sendPhoto` with TradingView-style 168-hour candlestick chart (custom symbol decimal tick format, EMA lines, exact signal markers) + detailed caption.
- **Config API**: `GET/POST /notifications/config` (exposes `enable_mtf_filter`, `enable_protection`, `monitored_symbols`).

---

## 3. Crucial Principles & Gotchas (READ BEFORE CODING)
To prevent regressions, **ALL future AI Agents MUST adhere to these rules**:

1. **Indicator Path-Dependence Parity (1000-candle Warmup)**:
   - *Rule*: **ALWAYS** fetch `limit=1000` candles for indicator calculation. When aggregating higher timeframes (e.g. 4h), query `limit * tf_ratio` raw points to guarantee a full 1000 aggregated bars.
2. **Strict Time Alignment & Zero Look-Ahead Bias**:
   - *Rule*: Indicators must be strictly causal (rolling windows `<= current_bar`). Trailing stops in backtesting must be evaluated against the previous bar's ratcheted price before applying current-bar highs/lows.
3. **Cross-Exchange OI Merging**:
   - *Gotcha*: Binance OI history is limited to ~30 days. Directly summing unaligned series causes 60%+ artificial drops at boundary points.
   - *Rule*: Always outer-merge on timestamp, apply `ffill(limit=2)`, and smooth boundary scale before computing delta/percentiles.
4. **Local Time vs UTC Formatting**:
   - *Gotcha*: If timestamps have already been shifted for local timezone display (e.g., in `runSignalBacktest()`), frontend formatters must specify `{ timeZone: 'UTC' }` to avoid double-offset (+16h).
5. **API Contract Validation (Frontend ↔ Backend)**:
   - *Rule*: Always verify that TypeScript interfaces mirror the exact field names returned by FastAPI before deploying UI changes.

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


