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


def get_notification_config() -> dict:
    """Return the current notification configuration."""
    return {
        "enabled": _notifications_enabled,
        "monitored_symbols": _monitored_symbols,
        "scan_schedule": "every hour at :00, :15, :30, :45",
        "timeframe": DEFAULT_TIMEFRAME,
    }


def update_notification_config(
    enabled: Optional[bool] = None,
    monitored_symbols: Optional[List[str]] = None,
) -> dict:
    """Update notification settings."""
    global _notifications_enabled, _monitored_symbols

    if enabled is not None:
        _notifications_enabled = enabled
    if monitored_symbols is not None:
        _monitored_symbols = monitored_symbols

    logger.info(f"Notification config updated: enabled={_notifications_enabled}, symbols={_monitored_symbols}")
    return get_notification_config()


async def scan_and_notify():
    """
    Core scan loop. Called by APScheduler every N minutes.
    
    For each monitored symbol:
        1. Calls the SAME get_market_data() endpoint logic used by the Dashboard
           (limit=1000, ensuring indicator warmup parity).
        2. Extracts confluence markers from the response.
        3. Filters for signals newer than the last notified timestamp.
        4. Formats and sends Telegram messages for each new signal.
    """
    if not _notifications_enabled:
        logger.info("Notifications disabled, skipping scan.")
        return

    logger.info(f"=== Signal scan starting for {len(_monitored_symbols)} symbols ===")

    # Import here to avoid circular imports — get_market_data is defined in main.py
    from api.main import get_market_data

    for idx, symbol in enumerate(_monitored_symbols):
        try:
            # Convert symbol format for the API (BTC/USDT -> BTC-USDT)
            api_symbol = symbol.replace("/", "-")
            cache_key = f"{symbol}:{DEFAULT_TIMEFRAME}"

            logger.info(f"Scanning [{idx+1}/{len(_monitored_symbols)}] {symbol}...")

            # 1. Fetch data using the exact same pipeline as the Dashboard
            result = get_market_data(
                symbol=api_symbol,
                timeframe=DEFAULT_TIMEFRAME,
                limit=1000,
                ranging_threshold=3,
                trending_threshold=3,
                enable_protection=False,
                use_dynamic_profiles=True,
            )

            markers = result.get("indicators", {}).get("lsur_markers", [])
            price_data = result.get("data", {}).get("price", [])

            if not markers:
                logger.info(f"  {symbol}: no markers found, skipping.")
                continue

            # 2. Recency filter: only consider signals from the last 2 hour.
            #    This prevents a flood of historical notifications on first startup
            #    or after a container restart (when _last_notified is empty).
            now_sec = time.time()
            RECENCY_WINDOW_SEC = 7200  # 2 hours
            recent_markers = [m for m in markers if m["time"] >= (now_sec - RECENCY_WINDOW_SEC)]

            if not recent_markers:
                logger.info(f"  {symbol}: {len(markers)} total markers, 0 within recency window.")
                continue

            # 3. Dedup: only send signals newer than the last notified timestamp
            last_ts = _last_notified.get(cache_key, 0)
            new_signals = [m for m in recent_markers if m["time"] > last_ts]

            if not new_signals:
                logger.info(f"  {symbol}: {len(recent_markers)} recent markers, all already notified.")
                continue

            # 4. Build a price lookup for formatting
            price_by_time = {p["time"]: p["close"] for p in price_data} if price_data else {}

            # 5. Send notifications for each new signal
            logger.info(f"  {symbol}: {len(new_signals)} NEW signal(s) to notify!")
            for sig in new_signals:
                sig_price = price_by_time.get(sig["time"], 0)
                message = format_signal_message(sig, symbol, sig_price)
                # Send chart image (168h OHLCV from DB + all markers) + text caption
                await send_signal_with_chart(
                    text=message,
                    price_data=price_data,
                    all_markers=markers,
                    symbol=symbol,
                )
                logger.info(f"  → Sent with chart: {message}")

            # 6. Update last notified timestamp to the most recent signal
            _last_notified[cache_key] = max(s["time"] for s in new_signals)

        except Exception as e:
            logger.error(f"Error scanning {symbol}: {e}", exc_info=True)
            continue

        # Delay between symbols to avoid OKX rate limiting (Too Many Requests)
        if idx < len(_monitored_symbols) - 1:
            await asyncio.sleep(5)

    logger.info(f"=== Signal scan completed for {len(_monitored_symbols)} symbols ===")
