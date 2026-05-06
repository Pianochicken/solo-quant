"""
Telegram Bot Notification Module.

Sends formatted trading signal alerts to the user's Telegram chat.
Tokens are read from environment variables — never hardcode them.
"""
import os
import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

# --- Configuration from Environment ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API_BASE = "https://api.telegram.org"


async def send_telegram_message(text: str, parse_mode: str = "HTML") -> bool:
    """
    Send a message to the configured Telegram chat via Bot API.
    
    Args:
        text: The message body (supports HTML formatting).
        parse_mode: 'HTML' or 'MarkdownV2'.
    
    Returns:
        True if the message was sent successfully, False otherwise.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning(
            "Telegram credentials not configured. "
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables."
        )
        return False

    url = f"{TELEGRAM_API_BASE}/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code == 200:
                logger.info("Telegram notification sent successfully.")
                return True
            else:
                logger.error(
                    f"Telegram API error {response.status_code}: {response.text}"
                )
                return False
    except httpx.TimeoutException:
        logger.error("Telegram API request timed out.")
        return False
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False


def format_signal_message(signal: dict, symbol: str, price: float) -> str:
    """
    Format a confluence signal marker dict into a human-readable Telegram message.
    
    Message format examples:
        🟢⬆ 2026/05/05 17:00 [BTC/USDT] Reversion BUY @ $94,500 | 3/7 CVD↑+FR-(OI↑)+BB↑
        🔴⬇ 2026/05/05 18:00 [BTC/USDT] Breakdown SELL @ $96,100 | 🚀 MACD↓+CVD↓
    """
    direction = signal.get("direction", "bullish")
    strategy_type = signal.get("strategy_type", "reversion")
    score = signal.get("score", 0)
    text_raw = signal.get("text", "")
    signal_time = signal.get("time", 0)

    # Timezone Offset from environment (e.g. 8 for UTC+8)
    tz_offset = float(os.getenv("NEXT_PUBLIC_TIMEZONE_OFFSET", "0"))

    # Format signal timestamp (UTC -> custom offset)
    if signal_time:
        import datetime as dt_module
        dt = datetime.fromtimestamp(signal_time, tz=timezone.utc)
        dt = dt + dt_module.timedelta(hours=tz_offset)
        time_str = dt.strftime("%Y/%m/%d %H:%M")
    else:
        time_str = "----/--/-- --:--"

    # Direction emoji
    if direction == "bullish":
        emoji = "🟢⬆"
        action = "BUY"
    else:
        emoji = "🔴⬇"
        action = "SELL"

    # Strategy label
    if strategy_type == "breakout":
        strategy_label = "Breakout" if direction == "bullish" else "Breakdown"
    else:
        strategy_label = "Reversion"

    # Price formatting
    price_str = f"${price:,.2f}" if price >= 1 else f"${price:.6f}"

    # Build the reason string
    if strategy_type == "breakout":
        # Extract reasons from text like "🚀 [BREAKOUT] MACD_UP+CVD↑"
        reasons_raw = text_raw.split("] ")[-1] if "] " in text_raw else text_raw
        reason_str = f"🚀 {reasons_raw}"
    else:
        # Extract reasons from text like "⚡(2G) 3/7 [T] CVD↑+FR-+BB↑"
        # We want to show "3/7 CVD↑+FR-+BB↑"
        reason_str = f"{score}/7 {text_raw.split('] ')[-1]}" if "] " in text_raw else f"{score}/7"

    return f"{emoji} {time_str} [{symbol}] {strategy_label} {action} @ {price_str} | {reason_str}"

