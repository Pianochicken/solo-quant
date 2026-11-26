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
from api.quant.signal_strategy import OPTIMAL_RISK_PROFILES, SignalStrategyConfig, get_risk_profile

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
    enable_partial_tp: Optional[bool] = None,
    correlation_warning: bool = False,
    is_intraday_prealert: bool = False,
) -> str:
    """Format a confluence signal into an actionable Telegram message with TP1/TP2/SL, position sizing, and quadrant status."""
    direction = signal.get("direction", "bullish")
    strategy_type = signal.get("strategy_type", "reversion")
    score = signal.get("score", 0)
    text_raw = signal.get("text", "")
    signal_time = signal.get("time", 0)
    if enable_partial_tp is None:
        enable_partial_tp = SignalStrategyConfig().enable_partial_tp

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
    p_cfg = get_risk_profile(symbol, timeframe)
    sl_pct = p_cfg['stop_loss_pct']
    tp_pct = p_cfg['take_profit_pct']
    act_pct = p_cfg['trailing_activation_pct']
    trail_pct = p_cfg['trailing_stop_pct']

    # Breakout & Structure signals get 1.15x TP expansion
    is_breakout = (strategy_type == "breakout") or ("BREAKOUT" in text_raw) or ("🚀" in text_raw)
    is_structure = ("CAP" in text_raw) or ("DIV" in text_raw)
    if is_breakout or is_structure:
        tp_pct *= 1.15

    # Position Sizing & Effective Leverage Cap (1%~2% equity risk, capped at 0.95x notional)
    risk_1_notional_pct = min(95.0, (1.0 / sl_pct) * 100.0) if sl_pct > 0 else 95.0
    risk_2_notional_pct = min(95.0, (2.0 / sl_pct) * 100.0) if sl_pct > 0 else 95.0
    eff_lev_1 = risk_1_notional_pct / 100.0
    eff_lev_2 = risk_2_notional_pct / 100.0
    sizing_block = (
        f"⚖️ <b>倉位與槓桿風控</b> (單筆風險 1%~2%):\n"
        f"• 建議名目倉位: 權益 {risk_1_notional_pct:.0f}%~{risk_2_notional_pct:.0f}% "
        f"(有效槓桿 {eff_lev_1:.2f}x~上限 {eff_lev_2:.2f}x，嚴控 &lt;= 0.95x)"
    )

    if price > 0:
        if direction == "bullish":
            tp1_price = price * (1 + act_pct / 100)
            tp2_price = price * (1 + tp_pct / 100)
            sl_price = price * (1 - sl_pct / 100)
            sign_tp, sign_sl = "+", "-"
        else:
            tp1_price = price * (1 - act_pct / 100)
            tp2_price = price * (1 - tp_pct / 100)
            sl_price = price * (1 + sl_pct / 100)
            sign_tp, sign_sl = "-", "+"

        if enable_partial_tp:
            points_block = (
                f"🎯 <b>戰術掛單點位</b> (兩段式減半保本):\n"
                f"• TP1 (減半推保本): {fmt_price(tp1_price)} ({sign_tp}{act_pct:.2f}%)\n"
                f"• TP2 (波段目標): {fmt_price(tp2_price)} ({sign_tp}{tp_pct:.2f}%)\n"
                f"• SL (安全止損): {fmt_price(sl_price)} ({sign_sl}{sl_pct:.2f}%)"
            )
        else:
            points_block = (
                f"🎯 <b>戰術掛單點位</b> (單段全倉追蹤 | 參考 TP1/TP2):\n"
                f"• 追蹤啟動 / 可選 TP1 (減半推保本): {fmt_price(tp1_price)} ({sign_tp}{act_pct:.2f}% | 回撤 {trail_pct:.2f}%)\n"
                f"• 全倉目標 / 可選 TP2 (波段目標): {fmt_price(tp2_price)} ({sign_tp}{tp_pct:.2f}%)\n"
                f"• SL (安全止損): {fmt_price(sl_price)} ({sign_sl}{sl_pct:.2f}%)"
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

    prealert_prefix = "[盤中未收線預警] " if is_intraday_prealert else ""
    lines = [
        f"{prealert_prefix}{emoji} <b>[{symbol} {timeframe}] {strategy_label} {action}</b> @ {price_str}",
        f"⏰ 時間: {time_str} {tz_label}",
        f"⚡ 訊號: {safe_reason_str}",
    ]
    if points_block:
        lines.append(f"\n{points_block}")
    lines.append(f"\n{sizing_block}")
    if macro_block:
        lines.append(f"\n{macro_block}")
    if correlation_warning:
        lines.append("\n⚠️ 跨幣種高度共線警示：請控管帳戶總風險敞口（建議總風險 &lt;= 4%～6%）")

    return "\n".join(lines)


def format_macro_cycle_message(
    signal: dict,
    symbol: str,
    price: float,
    macro_state: Optional[dict] = None,
) -> str:
    """Format a Phase 1.6 1D Macro Cycle inflection alert for Telegram."""
    cycle_event = str(signal.get("cycle_event", "")).upper()
    direction = signal.get("direction", "bullish")
    signal_time = signal.get("time", 0)

    offset = get_timezone_offset()
    tz = timezone(timedelta(hours=offset))
    tz_label = get_timezone_label(offset)
    if signal_time:
        dt = datetime.fromtimestamp(signal_time, tz=tz)
        date_str = dt.strftime("%Y/%m/%d (%H:%M)")
    else:
        date_str = "----/--/-- (--:--)"

    def fmt_price(p: Optional[float]) -> str:
        if p is None or p <= 0:
            return "—"
        if p >= 100:
            return f"${p:,.2f}"
        if p >= 1:
            return f"${p:,.3f}"
        return f"${p:,.6f}"

    header_map = {
        "BEAR_BOTTOM_V16": ("🐻🟢", "熊市反轉大底建倉"),
        "REGIONAL_BOTTOM_V16": ("💎🟢", "牛市回調底部接回"),
        "STAGE2_IGNITION_V16": ("🚀🟢", "Stage-2 主升浪啟動"),
        "EUPHORIA_TOP_V16": ("🔥🟠", "牛市高檔過熱逃頂"),
        "REGIME_BEAR_EXIT_V16": ("🛡️🔴", "趨勢破位轉熊離場"),
        "BASE_INVALIDATION_V16": ("⚠️🔴", "建倉初期結構止損"),
    }
    emoji, event_title = header_map.get(
        cycle_event,
        ("🟢⬆", "大週期多頭進場") if direction == "bullish" else ("🔴⬇", "大週期空手離場"),
    )

    mayer = signal.get("mayer")
    if mayer is None and macro_state:
        mayer = macro_state.get("mayer_multiple")
    mayer_str = f"{mayer:.2f}x" if isinstance(mayer, (int, float)) else "—"

    dd180_pct = macro_state.get("dd_180_pct") if macro_state else None
    dd180_str = f"{dd180_pct:.1f}%" if isinstance(dd180_pct, (int, float)) else "—"

    ema_align = "—"
    if macro_state:
        e20 = macro_state.get("ema20")
        e50 = macro_state.get("ema50")
        e200 = macro_state.get("ema200")
        if all(isinstance(v, (int, float)) for v in (e20, e50, e200)):
            if e20 > e50 > e200:
                ema_align = "EMA20 > EMA50 > EMA200 (多頭全排列)"
            elif e20 > e50:
                ema_align = "EMA20 > EMA50 (短中期轉強)"
            elif e20 < e50 < e200:
                ema_align = "EMA20 < EMA50 < EMA200 (空頭排列)"
            else:
                ema_align = "均線糾結轉折中"

    safe_event_title = html.escape(event_title)
    safe_event_code = html.escape(cycle_event or "MACRO_CYCLE")
    lines = [
        f"{emoji} <b>[{html.escape(symbol)} 1D 大週期] {safe_event_title}</b> @ {fmt_price(price)}",
        f"📅 1D 收盤K棒: {date_str} {tz_label} | 代碼: <code>{safe_event_code}</code>",
        f"📐 估值與結構: Mayer <b>{mayer_str}</b> | 180日高點回撤 {dd180_str} | {html.escape(ema_align)}",
    ]

    if direction == "bullish":
        base_stop = signal.get("base_stop")
        if base_stop is None and macro_state and isinstance(macro_state.get("active_position"), dict):
            base_stop = macro_state["active_position"].get("base_stop")
        if isinstance(base_stop, (int, float)) and price > 0:
            stop_dist_pct = abs((price - base_stop) / price) * 100.0
            stop_line = f"• 初期防禦止損 (Base Stop): {fmt_price(base_stop)} (-{stop_dist_pct:.2f}%)"
        else:
            stop_line = "• 初期防禦止損: 依開倉價下方 3×ATR 與 20日低點動態設定"

        lines.append(
            "\n⚖️ <b>週期配置與抱單規則 (Phase 1.6)</b>:\n"
            "• 建議現貨 / 低槓桿名目配置: 0.95x（僅做多・無短線窄停利）\n"
            f"{stop_line}\n"
            "• 抱單防護: 只要波段浮盈達 <b>+25%</b> 即自動解除 Base Stop，改為全程抱單至「過熱逃頂」或「轉熊防禦」離場。"
        )
    else:
        pnl_pct = signal.get("realized_pnl_pct")
        mfe_pct = signal.get("peak_mfe_pct")
        hold_days = signal.get("hold_days")
        pnl_str = f"{pnl_pct:+.2f}%" if isinstance(pnl_pct, (int, float)) else "—"
        mfe_str = f"+{mfe_pct:.2f}%" if isinstance(mfe_pct, (int, float)) else "—"
        hold_str = f"{hold_days:.0f} 天" if isinstance(hold_days, (int, float)) else "—"
        lines.append(
            "\n🏁 <b>本輪大週期結算摘要</b>:\n"
            f"• 實現波段報酬: <b>{pnl_str}</b> | 期間峰值浮盈 (MFE): {mfe_str} | 持倉天數: {hold_str}"
        )

    deriv = signal.get("deriv_context") or (macro_state.get("derivative_context") if macro_state else None)
    if isinstance(deriv, dict):
        oi_dd = deriv.get("coin_oi_dd_60d")
        oi_pct = deriv.get("coin_oi_pct_180d")
        fr_7d = deriv.get("fr_7d_mean_pct")
        lsur_z = deriv.get("lsur_z_90d")
        summary = html.escape(str(deriv.get("summary") or ""))

        oi_dd_s = f"{oi_dd:+.1f}%" if isinstance(oi_dd, (int, float)) else "N/A"
        oi_pct_s = f"{oi_pct:.0f}%" if isinstance(oi_pct, (int, float)) else "N/A"
        fr_s = f"{fr_7d:+.4f}%" if isinstance(fr_7d, (int, float)) else "N/A"
        z_s = f"{lsur_z:+.2f}" if isinstance(lsur_z, (int, float)) else "N/A"

        lines.append(
            "\n🧭 <b>左側衍生品輔助佐證</b>（純價格決策・非硬性閘門）:\n"
            f"• 幣本位 OI 60D回撤: {oi_dd_s} (180D分位 {oi_pct_s}) | 7D均費率: {fr_s} | LSUR Z: {z_s}\n"
            f"• {summary}"
        )

    return "\n".join(lines)
