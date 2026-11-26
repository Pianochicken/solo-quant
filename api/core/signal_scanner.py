"""
Signal Scanner Module.

Periodically scans all monitored symbols for new confluence signals across
multiple timeframes (1h + 4h), then dispatches Telegram notifications.

Strictly reuses the existing get_market_data() pipeline to guarantee
Indicator Warmup Parity (1000-candle warmup).
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from api.core.notifier import format_macro_cycle_message, format_signal_message, send_signal_with_chart

logger = logging.getLogger(__name__)

# --- In-Memory State ---
# Tracks the latest notified signal timestamp per (symbol, timeframe) pair.
_last_notified: Dict[str, float] = {}

# Default list of symbols to monitor (matches frontend options).
DEFAULT_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "HYPE/USDT", "CC/USDT"]

# Multi-timeframe monitoring
DEFAULT_TIMEFRAME = "1h"
MONITORED_TIMEFRAMES = ["1h", "4h"]

# Global toggle — can be flipped via API
_notifications_enabled = True
_monitored_symbols: List[str] = list(DEFAULT_SYMBOLS)
_enable_mtf_filter: bool = True
_enable_protection: bool = True  # Full Macro default
_allow_intraday_prealert: bool = False  # Closed-candle confirmation default (anti-repainting)
_enable_macro_cycle_alerts: bool = True
_notified_signal_keys: Dict[str, set] = {}
_notified_macro_cycle_keys: Dict[str, set] = {}
_recent_directional_signals: List[Dict] = []


def get_notification_config() -> dict:
    """Return the current notification configuration."""
    return {
        "enabled": _notifications_enabled,
        "monitored_symbols": _monitored_symbols,
        "scan_schedule": "every hour at :00:25, :15:25, :30:25, :45:25 (4h scanned at :00:25 on 4-hour multiples)",
        "macro_cycle_schedule": "daily at 00:05 UTC (08:05 UTC+8) after 1D candle close",
        "timeframe": DEFAULT_TIMEFRAME,
        "monitored_timeframes": MONITORED_TIMEFRAMES,
        "enable_mtf_filter": _enable_mtf_filter,
        "enable_protection": _enable_protection,
        "allow_intraday_prealert": _allow_intraday_prealert,
        "enable_macro_cycle_alerts": _enable_macro_cycle_alerts,
    }


def update_notification_config(
    enabled: Optional[bool] = None,
    monitored_symbols: Optional[List[str]] = None,
    enable_mtf_filter: Optional[bool] = None,
    enable_protection: Optional[bool] = None,
    allow_intraday_prealert: Optional[bool] = None,
    enable_macro_cycle_alerts: Optional[bool] = None,
) -> dict:
    """Update notification settings."""
    global _notifications_enabled, _monitored_symbols, _enable_mtf_filter, _enable_protection, _allow_intraday_prealert, _enable_macro_cycle_alerts

    if enabled is not None:
        _notifications_enabled = enabled
    if monitored_symbols is not None:
        _monitored_symbols = monitored_symbols
    if enable_mtf_filter is not None:
        _enable_mtf_filter = enable_mtf_filter
    if enable_protection is not None:
        _enable_protection = enable_protection
    if allow_intraday_prealert is not None:
        _allow_intraday_prealert = allow_intraday_prealert
    if enable_macro_cycle_alerts is not None:
        _enable_macro_cycle_alerts = enable_macro_cycle_alerts

    logger.info(
        f"Notification config updated: enabled={_notifications_enabled}, symbols={_monitored_symbols}, "
        f"mtf={_enable_mtf_filter}, protection={_enable_protection}, prealert={_allow_intraday_prealert}, "
        f"macro_cycle={_enable_macro_cycle_alerts}"
    )
    return get_notification_config()


def _prune_and_check_correlation(
    pending_signals: List[Dict],
    now_sec: float,
    window_sec: float = 14400.0,
) -> Dict[str, int]:
    """
    Record recent directional signals within the last 4 hours (plus current cycle)
    and return distinct symbol counts per direction ('bullish' / 'bearish').
    """
    global _recent_directional_signals
    cutoff = now_sec - window_sec
    _recent_directional_signals = [
        item for item in _recent_directional_signals if item.get("time", 0) >= cutoff
    ]

    existing_keys = {
        (item["symbol"], item["direction"], item["time"])
        for item in _recent_directional_signals
    }
    cycle_extra: Dict[str, set] = {"bullish": set(), "bearish": set()}
    for p in pending_signals:
        sig_time = float(p["signal"].get("time", now_sec))
        direction = p["signal"].get("direction", "")
        sym = p["symbol"]
        if direction in ("bullish", "bearish") and sig_time >= cutoff:
            if p.get("is_prealert"):
                cycle_extra[direction].add(sym)
                continue
            key = (sym, direction, sig_time)
            if key not in existing_keys:
                _recent_directional_signals.append({
                    "time": sig_time,
                    "symbol": sym,
                    "direction": direction,
                })
                existing_keys.add(key)

    dir_symbols: Dict[str, set] = {
        "bullish": set(cycle_extra["bullish"]),
        "bearish": set(cycle_extra["bearish"]),
    }
    for item in _recent_directional_signals:
        d = item.get("direction")
        if d in dir_symbols:
            dir_symbols[d].add(item["symbol"])

    return {d: len(syms) for d, syms in dir_symbols.items()}


async def scan_and_notify(
    timeframes: Optional[List[str]] = None,
    market_data_fn: Optional[Callable[..., Dict[str, Any]]] = None,
):
    """
    Core scan loop. Called by APScheduler at :00:25, :15:25, :30:25, :45:25.

    In :00 when hour % 4 == 0, scans both 1h and 4h.
    Otherwise scans 1h.

    For each monitored symbol:
        1. Scans BTC first to warm DB BTC history; altcoins compute causal btc_macro_history.
        2. Calls get_market_data(..., include_orderbook=False, include_breakdown=False) via asyncio.to_thread.
        3. Enforces closed-candle confirmation by default (anti-repainting).
        4. Evaluates cross-symbol correlation (>= 3 symbols same direction in cycle / 4h).
        5. Dedups and formats/sends Telegram messages with charts.
    """
    if not _notifications_enabled:
        logger.info("Notifications disabled, skipping scan.")
        return

    now_utc = datetime.now(timezone.utc)
    if timeframes is None:
        is_4h_interval = (now_utc.hour % 4 == 0 and now_utc.minute < 5)
        active_tfs = ["1h", "4h"] if is_4h_interval else ["1h"]
    else:
        active_tfs = timeframes

    logger.info(f"=== Signal scan starting for {len(_monitored_symbols)} symbols across timeframes {active_tfs} ===")

    if market_data_fn is None:
        from api.main import get_market_data
        market_data_fn = get_market_data

    # Sort so BTC is scanned first to keep DB BTC data fresh for altcoins
    symbols_to_scan = sorted(_monitored_symbols, key=lambda s: 0 if 'BTC' in s.upper() else 1)

    for tf in active_tfs:
        logger.info(f"--- Scanning timeframe: {tf} ---")
        tf_sec = 14400 if tf == "4h" else (86400 if tf == "1d" else 3600)
        pending_dispatches: List[Dict] = []

        for idx, symbol in enumerate(symbols_to_scan):
            try:
                api_symbol = symbol.replace("/", "-")
                cache_key = f"{symbol}:{tf}"

                logger.info(f"Scanning [{idx+1}/{len(symbols_to_scan)}] {symbol} ({tf})...")

                # 1. Fetch data cleanly without orderbook/breakdown overhead
                result = await asyncio.to_thread(
                    market_data_fn,
                    symbol=api_symbol,
                    timeframe=tf,
                    limit=1000,
                    ranging_threshold=3,
                    trending_threshold=3,
                    enable_protection=_enable_protection,
                    use_dynamic_profiles=True,
                    enable_mtf_filter=_enable_mtf_filter,
                    include_orderbook=False,
                    include_breakdown=False,
                    allow_live_btc_cache=False,
                )

                markers = result.get("indicators", {}).get("lsur_markers", [])
                price_data = result.get("data", {}).get("price", [])

                if not markers or not price_data:
                    logger.info(f"  {symbol} ({tf}): no markers or price data found, skipping.")
                    continue

                latest_candle_time = price_data[-1]["time"]
                now_sec = time.time()
                is_last_unclosed = (now_sec < latest_candle_time + tf_sec)

                # 2. Recency filter: signals within the last 2 bars (7200s for 1h, 28800s for 4h)
                recency_window_sec = 28800 if tf == "4h" else 7200
                recent_markers = [m for m in markers if m["time"] >= (now_sec - recency_window_sec)]

                if not recent_markers:
                    logger.info(f"  {symbol} ({tf}): {len(markers)} total markers, 0 within recency window.")
                    continue

                if cache_key not in _notified_signal_keys:
                    _notified_signal_keys[cache_key] = set()
                notified_set = _notified_signal_keys[cache_key]

                # 3. Closed-candle confirmation & dedup check
                new_signals = []
                for sig in recent_markers:
                    strat_type = sig.get("strategy_type", "reversion")
                    is_unclosed_sig = (sig["time"] == latest_candle_time and is_last_unclosed)

                    if is_unclosed_sig:
                        if not _allow_intraday_prealert:
                            # Closed-candle default: ignore unclosed intra-bar signals to eliminate repainting
                            continue
                        sig_text = sig.get("text", "")
                        has_structure = ("CAP" in sig_text) or ("DIV" in sig_text)
                        is_high_conviction = (sig.get("score", 0) >= 5.0) or has_structure
                        if not is_high_conviction:
                            continue
                        sig_key = ("prealert", sig["time"], strat_type)
                    else:
                        sig_key = (sig["time"], strat_type)

                    if sig_key in notified_set:
                        continue

                    new_signals.append((sig, sig_key, is_unclosed_sig))

                if not new_signals:
                    logger.info(f"  {symbol} ({tf}): {len(recent_markers)} recent markers, no new qualifying signals to notify.")
                    continue

                price_by_time = {p["time"]: p["close"] for p in price_data}

                # Retrieve macro info from market overview cache if available
                macro_info = None
                try:
                    from api.main import _market_overview_cache
                    cached_data = _market_overview_cache.get("data", [])
                    for item in cached_data:
                        if item.get("symbol") == symbol or item.get("symbol_slug") == symbol.replace('/', '-'):
                            macro_info = item
                            break
                except Exception:
                    pass

                for sig, sig_key, is_prealert in new_signals:
                    pending_dispatches.append({
                        "cache_key": cache_key,
                        "symbol": symbol,
                        "timeframe": tf,
                        "signal": sig,
                        "sig_key": sig_key,
                        "is_prealert": is_prealert,
                        "price": price_by_time.get(sig["time"], 0),
                        "price_data": price_data,
                        "all_markers": markers,
                        "macro_info": macro_info,
                    })

            except Exception as e:
                logger.error(f"Error scanning {symbol} ({tf}): {e}", exc_info=True)
                continue

            if idx < len(symbols_to_scan) - 1:
                await asyncio.sleep(3)

        if not pending_dispatches:
            continue

        # 4. Cross-symbol correlation check (>= 3 symbols firing same direction in cycle / past 4h)
        dir_counts = _prune_and_check_correlation(pending_dispatches, now_sec=time.time())

        # 5. Dispatch collected alerts
        by_cache_key: Dict[str, List[int]] = {}
        for item in pending_dispatches:
            sig = item["signal"]
            direction = sig.get("direction", "")
            corr_warn = dir_counts.get(direction, 0) >= 3
            message = format_signal_message(
                sig,
                item["symbol"],
                item["price"],
                timeframe=item["timeframe"],
                macro_info=item["macro_info"],
                correlation_warning=corr_warn,
                is_intraday_prealert=item["is_prealert"],
            )
            sent_ok = await send_signal_with_chart(
                text=message,
                price_data=item["price_data"],
                all_markers=item["all_markers"],
                symbol=item["symbol"],
                timeframe=item["timeframe"],
            )
            c_key = item["cache_key"]
            if sent_ok:
                logger.info(f"  → Sent successfully for {item['symbol']} ({item['timeframe']}): {sig.get('time')}")
                _notified_signal_keys[c_key].add(item["sig_key"])
                by_cache_key.setdefault(c_key, []).append(sig["time"])
            else:
                logger.warning(f"  ❌ Failed to send Telegram alert for {item['symbol']} ({item['timeframe']}) at {sig['time']}. Will retry on next scan.")

        for c_key, times_sent in by_cache_key.items():
            if times_sent:
                _last_notified[c_key] = max(times_sent)

    logger.info(f"=== Signal scan completed for {len(symbols_to_scan)} symbols across {active_tfs} ===")


async def scan_macro_cycle_and_notify(
    market_data_fn: Optional[Callable[..., Dict[str, Any]]] = None,
):
    """
    Daily 1D Macro Cycle scan (scheduled at 00:05 UTC / 08:05 UTC+8).
    Enforces strict closed-candle confirmation (never alerts on an unclosed 1D bar).
    """
    if not _notifications_enabled or not _enable_macro_cycle_alerts:
        logger.info("Macro cycle notifications disabled, skipping daily 1D scan.")
        return

    logger.info(f"=== Macro Cycle 1D scan starting for {len(_monitored_symbols)} symbols ===")
    if market_data_fn is None:
        from api.main import get_market_data
        market_data_fn = get_market_data

    symbols_to_scan = sorted(_monitored_symbols, key=lambda s: 0 if "BTC" in s.upper() else 1)
    recency_window_sec = 172800  # Last 2 days

    for idx, symbol in enumerate(symbols_to_scan):
        try:
            api_symbol = symbol.replace("/", "-")
            cache_key = f"{symbol}:1d:macro_cycle"

            result = await asyncio.to_thread(
                market_data_fn,
                symbol=api_symbol,
                timeframe="1d",
                limit=1800,
                strategy_mode="macro_cycle",
                include_orderbook=False,
                include_breakdown=False,
                allow_live_btc_cache=False,
            )

            indicators = result.get("indicators", {})
            markers = indicators.get("lsur_markers", [])
            price_data = result.get("data", {}).get("price", [])
            macro_state = indicators.get("macro_cycle_state")

            if not markers or not price_data:
                logger.info(f"  {symbol} (1d macro_cycle): no markers or price data found, skipping.")
                continue

            latest_candle_time = int(price_data[-1]["time"])
            now_sec = time.time()
            is_last_unclosed = (now_sec < latest_candle_time + 86400)
            recent_markers = [m for m in markers if int(m["time"]) >= (now_sec - recency_window_sec)]

            if not recent_markers:
                logger.info(f"  {symbol} (1d macro_cycle): {len(markers)} total markers, 0 within 48h window.")
                continue

            if cache_key not in _notified_macro_cycle_keys:
                _notified_macro_cycle_keys[cache_key] = set()
            notified_set = _notified_macro_cycle_keys[cache_key]

            price_by_time = {int(p["time"]): float(p["close"]) for p in price_data}

            for sig in recent_markers:
                sig_t = int(sig["time"])
                if sig_t == latest_candle_time and is_last_unclosed:
                    continue

                sig_key = (sig_t, sig.get("cycle_event", sig.get("direction", "")))
                if sig_key in notified_set:
                    continue

                trigger_price = float(sig.get("price") or price_by_time.get(sig_t, 0.0))
                message = format_macro_cycle_message(
                    sig,
                    symbol,
                    trigger_price,
                    macro_state=macro_state,
                )
                sent_ok = await send_signal_with_chart(
                    text=message,
                    price_data=price_data,
                    all_markers=markers,
                    symbol=symbol,
                    timeframe="1d",
                )
                if sent_ok:
                    logger.info(f"  → Sent Macro Cycle alert for {symbol} (1d): {sig.get('cycle_event')} @ {sig_t}")
                    notified_set.add(sig_key)
                else:
                    logger.warning(f"  ❌ Failed Macro Cycle Telegram alert for {symbol} (1d) @ {sig_t}.")

        except Exception as e:
            logger.error(f"Error scanning Macro Cycle for {symbol} (1d): {e}", exc_info=True)
            continue

        if idx < len(symbols_to_scan) - 1:
            await asyncio.sleep(2)

    logger.info("=== Macro Cycle 1D scan completed ===")
