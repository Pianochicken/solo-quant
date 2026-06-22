"""
chart.py — Candlestick chart generator for Telegram notifications.

Produces a TradingView-style 168-hour (1-week) candlestick PNG with:
  • EMA50 (orange) & EMA200 (purple) overlay lines
  • Latest-price label on the right Y-axis (arrow tag style)
  • Buy ▲ / Sell ▼ signal markers
  • Dual Y-axes (left & right)
  • "06/10\n12:00" style X-axis ticks (not rotated)
  • No candlestick edge lines, no legend, no volume panel
"""

import os
import warnings
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from matplotlib.collections import PatchCollection
from matplotlib.patches import FancyArrow
from pathlib import Path

warnings.filterwarnings("ignore")

# ── Colour palette ────────────────────────────────────────────────────────────
BG          = "#131722"
PANEL_BG    = "#131722"
GRID        = "#363a45"
TEXT        = "#d1d4dc"
UP_CANDLE   = "#26a69a"   # bullish body
DOWN_CANDLE = "#ef5350"   # bearish body
EMA50_COL   = "#FF9800"   # orange  (TradingView default)
EMA200_COL  = "#9C27B0"   # purple  (TradingView default)
# Signal colours — match exactly what the frontend sends in marker['color']
REVERSION_BUY_COL  = "#22c55e"   # green  ▲
REVERSION_SELL_COL = "#ef4444"   # red    ▼
BREAKOUT_UP_COL    = "#0ea5e9"   # sky-blue ▲
BREAKOUT_DN_COL    = "#f97316"   # orange   ▼


def _draw_candles(ax: plt.Axes, df: pd.DataFrame) -> None:
    """Draw candlestick bodies and wicks with no edge lines."""
    for i, (ts, row) in enumerate(df.iterrows()):
        o, h, l, c = row["Open"], row["High"], row["Low"], row["Close"]
        color = UP_CANDLE if c >= o else DOWN_CANDLE
        # Wick
        ax.plot([i, i], [l, h], color=color, linewidth=0.8, zorder=1)
        # Body (no edge → linewidth=0)
        body_bottom = min(o, c)
        body_height = abs(c - o) if abs(c - o) > 0 else 0.1
        rect = plt.Rectangle(
            (i - 0.35, body_bottom), 0.7, body_height,
            color=color, linewidth=0, zorder=2,
        )
        ax.add_patch(rect)


def _format_price(v: float, _=None) -> str:
    """Format price dynamically based on magnitude."""
    abs_v = abs(v)
    if abs_v >= 1000:
        return f"{v:,.0f}"
    elif abs_v >= 1:
        return f"{v:,.2f}"
    elif abs_v >= 0.001:
        return f"{v:.4f}"
    else:
        return f"{v:.6f}"

def _price_label(ax: plt.Axes, price: float, color: str) -> None:
    """Draw a TradingView-style price tag on the right spine."""
    price_str = _format_price(price)
    ax.axhline(price, color=color, linewidth=1.2, linestyle="--", alpha=0.7, zorder=1)
    ax.annotate(
        price_str,
        xy=(1, price), xycoords=("axes fraction", "data"),
        xytext=(6, 0), textcoords="offset points",
        ha="left", va="center",
        fontsize=8, fontweight="bold", color=BG,
        bbox=dict(boxstyle="round,pad=0.25", fc=color, ec="none"),
        annotation_clip=False,
    )


def _format_xticks(df: pd.DataFrame, ax: plt.Axes) -> None:
    """Show ticks in "10日\\n12:00" style without rotation."""
    n = len(df)
    # target roughly one tick every 12 bars (= 12 h)
    step = max(1, n // 14)
    tick_positions = list(range(0, n, step))
    tick_labels = []
    for i in tick_positions:
        ts = df.index[i]
        date_str = ts.strftime("%m/%d")
        hour_str = ts.strftime("%H:%M")
        tick_labels.append(f"{date_str}\n{hour_str}")
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(tick_labels, fontsize=7.5, color=TEXT)


def generate_candlestick_chart(
    symbol: str,
    df: pd.DataFrame,
    signals: list[dict],
    output_path: str,
) -> str:
    """Generate a 168-hour candlestick chart and save it to *output_path*.

    Args:
        symbol:      e.g. "BTC/USDT"
        df:          DataFrame with columns Date, Open, High, Low, Close.
                     Volume is optional and is not plotted.
        signals:     List of {"time": datetime, "direction": "buy"|"sell"}.
        output_path: Absolute path for the output PNG.

    Returns:
        Absolute path of the saved PNG.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # ── Prepare DataFrame ─────────────────────────────────────────────────────
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    df.set_index("Date", inplace=True)

    # ── EMA calculations ──────────────────────────────────────────────────────
    df["EMA50"]  = df["Close"].ewm(span=50,  adjust=False).mean()
    df["EMA200"] = df["Close"].ewm(span=200, adjust=False).mean()

    x = np.arange(len(df))          # integer x-axis positions

    # ── Map signal datetimes → integer indices ────────────────────────────────
    # Group signals by colour so each can be scattered independently.
    # Each key is a hex colour string; value is (x_positions, y_positions, marker_char)
    color_map: dict[str, tuple[list, list, str]] = {}

    idx_arr  = df.index
    t_start  = idx_arr[0]
    t_end    = idx_arr[-1]

    for sig in signals:
        t = pd.Timestamp(sig["time"])  # treat as UTC-naive (matches OHLCV Date index)
        # Normalise to tz-naive so it is comparable with the tz-naive DatetimeIndex
        if t.tzinfo is not None:
            t = t.tz_convert(None)

        # Skip signals outside the visible window — prevents old signals
        # from snapping to the first/last candle via nearest-neighbour lookup.
        if t < t_start or t > t_end:
            continue

        iloc = idx_arr.get_indexer([t], method="nearest")[0]
        if iloc < 0:
            continue
        row = df.iloc[iloc]

        # Determine colour & marker from signal metadata
        sig_color  = sig.get("color", "")
        direction  = sig.get("direction", "buy")   # "buy"/"sell"
        is_buy     = direction == "buy"

        if sig_color in (BREAKOUT_UP_COL, BREAKOUT_DN_COL):
            color  = sig_color
        elif is_buy:
            color  = REVERSION_BUY_COL
        else:
            color  = REVERSION_SELL_COL

        marker_char = "^" if is_buy else "v"
        y_pos = row["Low"] * 0.997 if is_buy else row["High"] * 1.003

        if color not in color_map:
            color_map[color] = ([], [], marker_char)
        color_map[color][0].append(iloc)
        color_map[color][1].append(y_pos)

    # ── Figure setup ──────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(14, 6))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(PANEL_BG)

    # ── Draw candlesticks ─────────────────────────────────────────────────────
    _draw_candles(ax, df)

    # ── EMA lines ─────────────────────────────────────────────────────────────
    ax.plot(x, df["EMA50"].values,  color=EMA50_COL,  linewidth=0.9,
            label="EMA50", zorder=3)
    ax.plot(x, df["EMA200"].values, color=EMA200_COL, linewidth=0.9,
            label="EMA200", zorder=3)

    # ── Signal markers (one scatter call per colour group) ───────────────────
    for color, (xs, ys, mchar) in color_map.items():
        ax.scatter(xs, ys, marker=mchar, color=color,
                   s=80, zorder=5, linewidths=0)

    # ── Latest price tag ──────────────────────────────────────────────────────
    latest_close = df["Close"].iloc[-1]
    last_color = UP_CANDLE if df["Close"].iloc[-1] >= df["Open"].iloc[-1] else DOWN_CANDLE
    _price_label(ax, latest_close, last_color)

    # ── Axes styling ──────────────────────────────────────────────────────────
    ax.set_xlim(-1, len(df))
    ax.tick_params(colors=TEXT, labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID)

    # Left Y-axis
    ax.yaxis.set_label_position("left")
    ax.yaxis.tick_left()
    ax.tick_params(axis="y", left=True, right=False, labelright=False, colors=TEXT)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_format_price))

    # Right Y-axis (twin)
    ax2 = ax.twinx()
    ax2.set_facecolor(PANEL_BG)
    ax2.set_ylim(ax.get_ylim())
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(_format_price))
    ax2.tick_params(colors=TEXT, labelsize=8)
    for spine in ax2.spines.values():
        spine.set_edgecolor(GRID)

    # Grid
    ax.grid(axis="both", color=GRID, linestyle="--", linewidth=0.4, zorder=0)

    # X-axis ticks
    _format_xticks(df, ax)

    # Title (top-left, subtle)
    ax.set_title(
        f"{symbol}  ·  1H  ·  168 candles  ·  EMA50 / EMA200",
        loc="left", color=TEXT, fontsize=9, pad=8,
    )

    # ── Save ──────────────────────────────────────────────────────────────────
    plt.tight_layout(pad=1.0)
    fig.savefig(output_path, dpi=150, bbox_inches="tight",
                facecolor=BG, edgecolor="none")
    plt.close(fig)
    return os.path.abspath(output_path)
