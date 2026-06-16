import os
import re
import logging
from datetime import datetime, timezone
import httpx
import pandas as pd
from pathlib import Path

# Local import for chart generation
from .utils.chart import generate_candlestick_chart

logger = logging.getLogger(__name__)

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
        caption:     Optional override for the caption; defaults to *text*.

    Returns:
        True if the Telegram API call succeeded.
    """
    from .utils.chart import generate_candlestick_chart

    # -- Convert price_data (last 168 candles) to DataFrame --
    df = pd.DataFrame(price_data)
    df["Date"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.tz_localize(None)
    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"})
    df = df[["Date", "Open", "High", "Low", "Close"]].sort_values("Date").tail(168).reset_index(drop=True)

    # -- Convert lsur_markers to signals list (preserve color + direction for chart) --
    signals = [
        {
            # Use unit="s" so the Timestamp is UTC-naive, matching the OHLCV Date index
            "time":      pd.Timestamp(m["time"], unit="s"),
            "direction": "buy" if m.get("direction", "") == "bullish" else "sell",
            "color":     m.get("color", ""),          # hex colour from frontend (e.g. #0ea5e9)
        }
        for m in all_markers
    ]

    artifacts_dir = Path(
        "/Users/huangjunyou/.gemini/antigravity-ide/brain/bb3e634d-9790-427f-ac57-6fa3f7dd5dd0/artifacts"
    )
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    output_path = artifacts_dir / f"{symbol.replace('/', '_')}_168h.png"

    generate_candlestick_chart(symbol, df, signals, str(output_path))

    return await send_telegram_message(
        text="",
        photo_path=str(output_path),
        caption=caption or text,
    )

# ---------------------------------------------------------------------------
# Existing plain‑text formatter (unchanged apart from imports)
# ---------------------------------------------------------------------------
def format_signal_message(signal: dict, symbol: str, price: float) -> str:
    """Format a confluence signal into a human‑readable Telegram message.

    Example output::
        🟢⬆ 2026/05/05 17:00 [BTC/USDT] Reversion BUY @ $94,500 | 3/7 CVD↑+FR-(OI↑)+BB↑
    """
    direction = signal.get("direction", "bullish")
    strategy_type = signal.get("strategy_type", "reversion")
    score = signal.get("score", 0)
    text_raw = signal.get("text", "")
    signal_time = signal.get("time", 0)

    # Timezone handling
    tz_offset = float(os.getenv("NEXT_PUBLIC_TIMEZONE_OFFSET", "0"))
    if signal_time:
        import datetime as dt_module
        dt = datetime.fromtimestamp(signal_time, tz=timezone.utc)
        dt = dt + dt_module.timedelta(hours=tz_offset)
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

    return f"{emoji} {time_str} [{symbol}] {strategy_label} {action} @ {price_str} | {reason_str}"
