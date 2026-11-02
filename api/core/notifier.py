import os
import re
import html
import logging
import asyncio
import threading
from typing import Optional
from datetime import datetime, timezone, timedelta
import httpx
import pandas as pd
from pathlib import Path

# Local import for chart generation
from .utils.chart import generate_candlestick_chart
from api.quant.signal_strategy import OPTIMAL_RISK_PROFILES

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
# Tactical signal formatter with TP1/TP2/SL targets and macro quadrant status
# ---------------------------------------------------------------------------
def format_signal_message(
    signal: dict,
    symbol: str,
    price: float,
    timeframe: str = "1h",
    macro_info: Optional[dict] = None,
) -> str:
    """Format a confluence signal into an actionable Telegram message with TP1/TP2/SL and quadrant status."""
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

    def fmt_price(p: float) -> str:
        if p >= 100:
            return f"${p:,.2f}"
        elif p >= 1:
            return f"${p:,.3f}"
        else:
            return f"${p:,.6f}"

    price_str = fmt_price(price) if price > 0 else "—"

    # Reason string
    if strategy_type == "breakout":
        reasons_raw = text_raw.split("] ")[-1] if "] " in text_raw else text_raw
        reason_str = f"🚀 {reasons_raw}"
    else:
        match = re.search(r'([\d\.]+/\d+)', text_raw)
        score_str = match.group(1) if match else f"{score:g}"
        reason_str = f"{score_str} {text_raw.split('] ')[-1]}" if "] " in text_raw else score_str

    safe_reason_str = html.escape(reason_str)

    # --- Target SL / TP1 / TP2 Calculation ---
    coin = symbol.split('/')[0].split('-')[0].upper()
    p_cfg = (
        OPTIMAL_RISK_PROFILES.get(coin, {}).get(timeframe)
        or OPTIMAL_RISK_PROFILES.get(coin, {}).get('1h')
        or OPTIMAL_RISK_PROFILES['BTC']['1h']
    )
    sl_pct = p_cfg['stop_loss_pct']
    tp_pct = p_cfg['take_profit_pct']
    act_pct = p_cfg['trailing_activation_pct']

    # Breakout & Structure signals get 1.15x TP expansion
    is_breakout = (strategy_type == "breakout") or ("BREAKOUT" in text_raw) or ("🚀" in text_raw)
    is_structure = ("CAP" in text_raw) or ("DIV" in text_raw)
    if is_breakout or is_structure:
        tp_pct *= 1.15

    if price > 0:
        if direction == "bullish":
            tp1_price = price * (1 + act_pct / 100)
            tp2_price = price * (1 + tp_pct / 100)
            sl_price = price * (1 - sl_pct / 100)
            points_block = (
                f"🎯 <b>戰術掛單點位</b>:\n"
                f"• TP1 (減半推保本): {fmt_price(tp1_price)} (+{act_pct:.2f}%)\n"
                f"• TP2 (波段目標): {fmt_price(tp2_price)} (+{tp_pct:.2f}%)\n"
                f"• SL (安全止損): {fmt_price(sl_price)} (-{sl_pct:.2f}%)"
            )
        else:
            tp1_price = price * (1 - act_pct / 100)
            tp2_price = price * (1 - tp_pct / 100)
            sl_price = price * (1 + sl_pct / 100)
            points_block = (
                f"🎯 <b>戰術掛單點位</b>:\n"
                f"• TP1 (減半推保本): {fmt_price(tp1_price)} (-{act_pct:.2f}%)\n"
                f"• TP2 (波段目標): {fmt_price(tp2_price)} (-{tp_pct:.2f}%)\n"
                f"• SL (安全止損): {fmt_price(sl_price)} (+{sl_pct:.2f}%)"
            )
    else:
        points_block = ""

    # --- Macro Quadrant Status ---
    macro_block = ""
    if macro_info:
        quadrant_map = {
            'strong_add': '🔥 強勢加倉',
            'weak_add': '🩸 弱勢加倉',
            'strong_reduce': '⚡ 強勢減倉',
            'weak_reduce': '🧊 弱勢減倉',
            'neutral': '⚪ 中性盤整',
        }
        quad_badge = quadrant_map.get(macro_info.get('quadrant', 'neutral'), '⚪ 中性盤整')
        rs_val = macro_info.get('rs_vs_btc', 0)
        oi_val = macro_info.get('oi_coin_change_24h_pct', 0)
        rs_str = f"+{rs_val}" if rs_val > 0 else f"{rs_val}"
        oi_str = f"+{oi_val:.1f}%" if oi_val > 0 else f"{oi_val:.1f}%"
        reg_4h = macro_info.get('regime_4h', '')
        reg_str = '4H ↗ 趨勢多' if reg_4h == 'trending_up' else ('4H ↘ 趨勢空' if reg_4h == 'trending_down' else '4H ⇄ 盤整')
        macro_block = (
            f"📊 <b>籌碼四象限定位</b>: {quad_badge}\n"
            f"• 4H 宏觀: {reg_str} | RS vs BTC: {rs_str} | 24h 幣本位OI: {oi_str}"
        )

    lines = [
        f"{emoji} <b>[{symbol} {timeframe}] {strategy_label} {action}</b> @ {price_str}",
        f"⏰ 時間: {time_str} {tz_label}",
        f"⚡ 訊號: {safe_reason_str}",
    ]
    if points_block:
        lines.append(f"\n{points_block}")
    if macro_block:
        lines.append(f"\n{macro_block}")

    return "\n".join(lines)
