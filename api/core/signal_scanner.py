"""
Signal Scanner Module.

Periodically scans all monitored symbols for new confluence signals,
then dispatches Telegram notifications for any newly detected signals.

Strictly reuses the existing get_market_data() pipeline to guarantee
Indicator Warmup Parity (1000-candle warmup).
"""
import asyncio
import logging
import time
from typing import Dict, List, Optional

from api.core.notifier import format_signal_message, send_signal_with_chart

logger = logging.getLogger(__name__)

# --- In-Memory State ---
# Tracks the latest notified signal timestamp per (symbol, timeframe) pair.
# This prevents re-sending old signals on every scan cycle.
_last_notified: Dict[str, float] = {}

# Default list of symbols to monitor (matches frontend options).
DEFAULT_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "HYPE/USDT", "CC/USDT"]

# Default scan timeframe
DEFAULT_TIMEFRAME = "1h"

# Global toggle — can be flipped via API
_notifications_enabled = True
_monitored_symbols: List[str] = list(DEFAULT_SYMBOLS)
_enable_mtf_filter: bool = True
_enable_protection: bool = False
_notified_signal_keys: Dict[str, set] = {}


def get_notification_config() -> dict:
    """Return the current notification configuration."""
    return {
        "enabled": _notifications_enabled,
        "monitored_symbols": _monitored_symbols,
        "scan_schedule": "every hour at :00, :15, :30, :45",
        "timeframe": DEFAULT_TIMEFRAME,
        "enable_mtf_filter": _enable_mtf_filter,
        "enable_protection": _enable_protection,
    }


def update_notification_config(
    enabled: Optional[bool] = None,
    monitored_symbols: Optional[List[str]] = None,
    enable_mtf_filter: Optional[bool] = None,
    enable_protection: Optional[bool] = None,
) -> dict:
    """Update notification settings."""
    global _notifications_enabled, _monitored_symbols, _enable_mtf_filter, _enable_protection

    if enabled is not None:
        _notifications_enabled = enabled
    if monitored_symbols is not None:
        _monitored_symbols = monitored_symbols
    if enable_mtf_filter is not None:
        _enable_mtf_filter = enable_mtf_filter
    if enable_protection is not None:
        _enable_protection = enable_protection

    logger.info(
        f"Notification config updated: enabled={_notifications_enabled}, symbols={_monitored_symbols}, "
        f"mtf={_enable_mtf_filter}, protection={_enable_protection}"
    )
    return get_notification_config()


async def scan_and_notify():
    """
    Core scan loop. Called by APScheduler every N minutes.
    
    For each monitored symbol:
        1. Prioritizes BTC/USDT first to extract and pass BTC macro regime to altcoins.
        2. Calls get_market_data() via asyncio.to_thread to prevent blocking event loop.
        3. Filters unclosed bar signals unless high score (>=5.0) or CAP/DIV structural inflection.
        4. Dedups with (timestamp, strategy_type) to avoid suppressing signals.
        5. Formats and sends Telegram messages with charts.
    """
    if not _notifications_enabled:
        logger.info("Notifications disabled, skipping scan.")
        return

    logger.info(f"=== Signal scan starting for {len(_monitored_symbols)} symbols ===")

    from api.main import get_market_data

    # Sort so BTC is scanned first, allowing altcoins to receive BTC macro regime
    symbols_to_scan = sorted(_monitored_symbols, key=lambda s: 0 if 'BTC' in s.upper() else 1)
    btc_macro_regime: Optional[Dict] = None

    for idx, symbol in enumerate(symbols_to_scan):
        try:
            api_symbol = symbol.replace("/", "-")
            cache_key = f"{symbol}:{DEFAULT_TIMEFRAME}"

            logger.info(f"Scanning [{idx+1}/{len(symbols_to_scan)}] {symbol}...")

            # 1. Fetch data using asyncio.to_thread to keep event loop unblocked
            result = await asyncio.to_thread(
                get_market_data,
                symbol=api_symbol,
                timeframe=DEFAULT_TIMEFRAME,
                limit=1000,
                ranging_threshold=3,
                trending_threshold=3,
                enable_protection=_enable_protection,
                use_dynamic_profiles=True,
                enable_mtf_filter=_enable_mtf_filter,
                btc_macro_regime=btc_macro_regime if 'BTC' not in symbol.upper() else None,
            )

            # Save BTC macro regime if we just scanned BTC
            if 'BTC' in symbol.upper():
                regime_info = result.get("indicators", {}).get("market_regime", {})
                composite_score = result.get("indicators", {}).get("composite_score", 50.0)
                btc_macro_regime = {
                    'regime': regime_info.get('regime', 'ranging'),
                    'direction': regime_info.get('direction', 'neutral'),
                    'pulse': composite_score,
                }
                logger.info(f"  BTC Macro Regime saved: {btc_macro_regime}")

            markers = result.get("indicators", {}).get("lsur_markers", [])
            price_data = result.get("data", {}).get("price", [])

            if not markers:
                logger.info(f"  {symbol}: no markers found, skipping.")
                continue

            latest_candle_time = price_data[-1]["time"] if price_data else 0

            # 2. Recency filter: signals within the last 2 hours
            now_sec = time.time()
            RECENCY_WINDOW_SEC = 7200  # 2 hours
            recent_markers = [m for m in markers if m["time"] >= (now_sec - RECENCY_WINDOW_SEC)]

            if not recent_markers:
                logger.info(f"  {symbol}: {len(markers)} total markers, 0 within recency window.")
                continue

            if cache_key not in _notified_signal_keys:
                _notified_signal_keys[cache_key] = set()
            notified_set = _notified_signal_keys[cache_key]

            # 3. Unclosed candle & (time, strategy_type) dedup check
            new_signals = []
            for sig in recent_markers:
                sig_key = (sig["time"], sig.get("strategy_type", "reversion"))
                if sig_key in notified_set:
                    continue

                # Check if this signal belongs to the currently forming (unclosed) candle
                if sig["time"] == latest_candle_time:
                    sig_text = sig.get("text", "")
                    has_structure = ("CAP" in sig_text) or ("DIV" in sig_text)
                    is_high_conviction = (sig.get("score", 0) >= 5.0) or has_structure
                    if not is_high_conviction:
                        # Skip intra-bar alert; wait for candle to close
                        continue

                new_signals.append(sig)

            if not new_signals:
                logger.info(f"  {symbol}: {len(recent_markers)} recent markers, no new qualifying signals to notify.")
                continue

            price_by_time = {p["time"]: p["close"] for p in price_data} if price_data else {}

            logger.info(f"  {symbol}: {len(new_signals)} NEW signal(s) to notify!")
            for sig in new_signals:
                sig_price = price_by_time.get(sig["time"], 0)
                message = format_signal_message(sig, symbol, sig_price)
                await send_signal_with_chart(
                    text=message,
                    price_data=price_data,
                    all_markers=markers,
                    symbol=symbol,
                )
                logger.info(f"  → Sent with chart: {message}")
                notified_set.add((sig["time"], sig.get("strategy_type", "reversion")))

            _last_notified[cache_key] = max(s["time"] for s in new_signals)

        except Exception as e:
            logger.error(f"Error scanning {symbol}: {e}", exc_info=True)
            continue

        if idx < len(symbols_to_scan) - 1:
            await asyncio.sleep(5)

    logger.info(f"=== Signal scan completed for {len(symbols_to_scan)} symbols ===")
