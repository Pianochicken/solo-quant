import os
import re
import logging
import asyncio
import threading
from datetime import datetime, timezone, timedelta
import httpx
import pandas as pd
from pathlib import Path

# Local import for chart generation
from .utils.chart import generate_candlestick_chart

logger = logging.getLogger(__name__)
_chart_lock = threading.Lock()

def get_timezone_offset() -> float:
    """Return timezone offset in hours from environment (defaults to 8.0 for UTC+8 / Taipei)."""
    val = os.getenv("NEXT_PUBLIC_TIMEZONE_OFFSET", "8")
    try:
        return float(val)
    except ValueError:
        return 8.0

def get_timezone_label(offset: float) -> str:
    """Return a label like '(UTC+8)' or '(UTC)'."""
    if offset == 0:
        return "(UTC)"
    sign = "+" if offset > 0 else ""
    formatted_offset = int(offset) if offset.is_integer() else offset
    return f"(UTC{sign}{formatted_offset})"

# --- Environment configuration ------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API_BASE = "https://api.telegram.org"

# ---------------------------------------------------------------------------
# Telegram sending utilities
# ---------------------------------------------------------------------------
async def send_telegram_message(
    text: str = "",
    parse_mode: str = "HTML",
    *,
    photo_path: str | None = None,
    caption: str | None = None,
) -> bool:
    """Send a Telegram message.

    If *photo_path* is supplied the image is sent via ``sendPhoto`` and the
    *caption* (or *text* as fallback) is attached. Otherwise a plain text message
    is sent using ``sendMessage``.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning(
            "Telegram credentials not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables."
        )
        return False

    if photo_path:
        url = f"{TELEGRAM_API_BASE}/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption or text, "parse_mode": parse_mode}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                with open(photo_path, "rb") as f:
                    files = {"photo": f}
                    response = await client.post(url, data=data, files=files)
        except Exception as exc:  # pragma: no cover
            logger.error(f"Telegram photo send error: {exc}")
            return False
    else:
        url = f"{TELEGRAM_API_BASE}/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": parse_mode}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
        except Exception as exc:  # pragma: no cover
            logger.error(f"Telegram send error: {exc}")
            return False

    if response.status_code == 200:
        logger.info("Telegram notification sent successfully.")
        return True
    else:
        logger.error(f"Telegram API error {response.status_code}: {response.text}")
        return False

# ---------------------------------------------------------------------------
# Helper to generate a 168‑hour candlestick chart with buy/sell arrows and send it
# ---------------------------------------------------------------------------
async def send_signal_with_chart(
    text: str,
    price_data: list[dict],
    all_markers: list[dict],
    symbol: str,
    timeframe: str = "1h",
    *,
    caption: str | None = None,
) -> bool:
    """Generate a 168-hour candlestick chart from DB-derived data and send it with *text* as caption.

    Args:
        text:        Formatted signal message (used as Telegram caption).
        price_data:  List of OHLCV dicts from get_market_data() — each dict has keys
                     ``time`` (unix seconds), ``open``, ``high``, ``low``, ``close``.
        all_markers: Full list of signal marker dicts from ``lsur_markers`` — each has
                     ``time`` (unix seconds), ``direction`` ("bullish"/"bearish").
        symbol:      Trading pair identifier (e.g. "BTC/USDT").
        timeframe:   Candle timeframe (e.g. "1h", "4h").
        caption:     Optional override for the caption; defaults to *text*.

    Returns:
        True if the Telegram API call succeeded.
    """
    from .utils.chart import generate_candlestick_chart

    # -- Convert price_data (last 168 candles) to DataFrame with configured timezone offset --
    offset = get_timezone_offset()
    tz_label = get_timezone_label(offset)

    df = pd.DataFrame(price_data)
    df["Date"] = pd.to_datetime(df["time"] + int(offset * 3600), unit="s")
    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"})
    df = df[["Date", "Open", "High", "Low", "Close"]].sort_values("Date").tail(168).reset_index(drop=True)

    # -- Convert lsur_markers to signals list (shifted by offset matching Date index) --
    signals = [
        {
            "time":      pd.to_datetime(m["time"] + int(offset * 3600), unit="s"),
            "direction": "buy" if m.get("direction", "") == "bullish" else "sell",
            "color":     m.get("color", ""),          # hex colour from frontend (e.g. #0ea5e9)
        }
        for m in all_markers
    ]

    artifacts_dir = Path(os.getenv("ARTIFACTS_DIR", "/tmp/solo_quant_charts"))
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    output_path = artifacts_dir / f"{symbol.replace('/', '_')}_{timeframe}_168h.png"

    def _render_chart():
        with _chart_lock:
            generate_candlestick_chart(symbol, df, signals, str(output_path), timeframe=timeframe, tz_label=tz_label)

    photo_sent = False
    try:
        await asyncio.to_thread(_render_chart)
        photo_sent = await send_telegram_message(
            text="",
            photo_path=str(output_path),
            caption=caption or text,
        )
    except Exception as chart_err:
        logger.error(f"Chart generation or photo delivery failed for {symbol} ({timeframe}): {chart_err}")
        photo_sent = False

    # Fallback to plain-text notification if chart generation or photo delivery fails
    if not photo_sent:
        logger.warning(f"Falling back to plain-text Telegram alert for {symbol} ({timeframe})")
        return await send_telegram_message(text=caption or text)

    return True

# ---------------------------------------------------------------------------
# Existing plain‑text formatter (dynamically aligned to timezone offset)
# ---------------------------------------------------------------------------
def format_signal_message(signal: dict, symbol: str, price: float, timeframe: str = "1h") -> str:
    """Format a confluence signal into a human-readable Telegram message."""
    direction = signal.get("direction", "bullish")
    strategy_type = signal.get("strategy_type", "reversion")
    score = signal.get("score", 0)
    text_raw = signal.get("text", "")
    signal_time = signal.get("time", 0)

    # Timezone handling: dynamically derived from environment offset
    offset = get_timezone_offset()
    tz = timezone(timedelta(hours=offset))
    tz_label = get_timezone_label(offset)
    if signal_time:
        dt = datetime.fromtimestamp(signal_time, tz=tz)
        time_str = dt.strftime("%Y/%m/%d %H:%M")
    else:
        time_str = "----/--/-- --:--"

    # Emoji & action
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

    # Reason string
    if strategy_type == "breakout":
        reasons_raw = text_raw.split("] ")[-1] if "] " in text_raw else text_raw
        reason_str = f"🚀 {reasons_raw}"
    else:
        match = re.search(r'([\d\.]+/\d+)', text_raw)
        score_str = match.group(1) if match else f"{score:g}"
        reason_str = f"{score_str} {text_raw.split('] ')[-1]}" if "] " in text_raw else score_str

    return f"{emoji} {time_str} {tz_label} [{symbol} {timeframe}] {strategy_label} {action} @ {price_str} | {reason_str}"
