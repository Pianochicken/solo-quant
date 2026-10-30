#!/usr/bin/env python3
"""
evaluate_altcoins_quality.py - Comprehensive Altcoin Quality & Liquidity Evaluation Script

Evaluates ETH/USDT, SOL/USDT, HYPE/USDT, CC/USDT across 1h, 4h, and 1d timeframes:
  Table 1: Frontend 1000-candle signal density & dual-exchange liquidity health
  Table 2: Multi-timeframe Full Macro signal quality & risk benchmark
  Table 3: Signal category ablation (Structure vs Breakout vs Pure Reversion) for altcoins
"""

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
import numpy as np

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from api.main import get_market_data

SYMBOLS = ['ETH-USDT', 'SOL-USDT', 'HYPE-USDT', 'CC-USDT']

TF_CONFIGS = {
    '1d': {
        'limit': 1000,
        'horizons': [3, 7, 14],
        'primary_horizon': 7,
        'horizon_labels': ['3d', '7d', '14d'],
        'primary_label': '7d (7根)',
    },
    '4h': {
        'limit': 2200,
        'horizons': [3, 6, 12],
        'primary_horizon': 6,
        'horizon_labels': ['12h', '24h', '48h'],
        'primary_label': '24h (6根)',
    },
    '1h': {
        'limit': 4320,
        'horizons': [4, 12, 24],
        'primary_horizon': 12,
        'horizon_labels': ['4h', '12h', '24h'],
        'primary_label': '12h (12根)',
    },
}


def calculate_atr_pct(price_data: List[Dict], period: int = 14) -> List[float]:
    """Computes 14-period Wilder's ATR as percentage of close price for each bar."""
    n = len(price_data)
    if n == 0:
        return []

    tr = [0.0] * n
    tr[0] = price_data[0]['high'] - price_data[0]['low']

    for i in range(1, n):
        h = price_data[i]['high']
        l = price_data[i]['low']
        prev_c = price_data[i - 1]['close']
        tr[i] = max(h - l, abs(h - prev_c), abs(l - prev_c))

    atr = [0.0] * n
    initial_atr = sum(tr[:period]) / max(1, period)
    for i in range(min(period, n)):
        atr[i] = initial_atr

    curr_atr = initial_atr
    for i in range(period, n):
        curr_atr = (curr_atr * (period - 1) + tr[i]) / period
        atr[i] = curr_atr

    atr_pct = [
        (atr[i] / max(price_data[i]['close'], 1e-8)) * 100.0
        for i in range(n)
    ]
    return atr_pct


def classify_signal(sig: Dict) -> str:
    """Classifies a marker into Structure, Breakout, or Pure Reversion."""
    text = sig.get('text', '')
    strategy_type = sig.get('strategy_type', '')
    if 'CAP' in text or 'DIV' in text:
        return 'Structure (CAP / DIV)'
    elif strategy_type == 'breakout' or '🚀' in text:
        return 'Breakout (🚀)'
    else:
        return 'Pure Reversion'


def evaluate_markers(
    price_data: List[Dict],
    markers: List[Dict],
    atr_pct: List[float],
    symbol: str,
    timeframe: str,
    horizons: List[int],
    warmup_bars: int = 200,
) -> List[Dict]:
    """Computes forward returns and uninterrupted MFE/MAE for each marker."""
    if not price_data or not markers:
        return []

    time_to_idx = {p['time']: i for i, p in enumerate(price_data)}
    max_h = max(horizons)
    n_bars = len(price_data)

    evaluated = []

    for sig in markers:
        t = sig['time']
        idx = time_to_idx.get(t)
        if idx is None:
            continue

        # Warmup filter
        if idx < warmup_bars:
            continue

        # Forward horizon availability
        if idx + max_h >= n_bars:
            continue

        entry = price_data[idx]['close']
        direction = sig.get('direction', 'bullish')
        if not direction:
            direction = 'bullish' if sig.get('position') == 'belowBar' else 'bearish'

        sig_class = classify_signal(sig)

        res = {
            'time': t,
            'idx': idx,
            'symbol': symbol,
            'timeframe': timeframe,
            'entry': entry,
            'direction': direction,
            'strategy_type': sig.get('strategy_type', 'reversion'),
            'class': sig_class,
            'score': sig.get('score', 0),
            'text': sig.get('text', ''),
            'atr_pct': atr_pct[idx] if idx < len(atr_pct) else 1.0,
            'horizons': {}
        }

        for h in horizons:
            window = price_data[idx + 1: idx + h + 1]
            highs = [p['high'] for p in window]
            lows = [p['low'] for p in window]
            close_h = price_data[idx + h]['close']

            if direction == 'bullish':
                forward_ret = (close_h - entry) / entry * 100.0
                mfe_pct = max(0.0, (max(highs) - entry) / entry * 100.0)
                mae_pct = max(0.0, (entry - min(lows)) / entry * 100.0)
            else:
                forward_ret = (entry - close_h) / entry * 100.0
                mfe_pct = max(0.0, (entry - min(lows)) / entry * 100.0)
                mae_pct = max(0.0, (max(highs) - entry) / entry * 100.0)

            cur_atr = max(atr_pct[idx], 1e-4) if idx < len(atr_pct) else 1.0
            mfe_atr = mfe_pct / cur_atr
            mae_atr = mae_pct / cur_atr
            is_win = (forward_ret > 0.0)

            res['horizons'][h] = {
                'forward_ret_pct': forward_ret,
                'mfe_pct': mfe_pct,
                'mae_pct': mae_pct,
                'mfe_atr': mfe_atr,
                'mae_atr': mae_atr,
                'is_win': is_win,
            }

        evaluated.append(res)

    return evaluated


def aggregate_metrics(evaluated_signals: List[Dict], horizons: List[int], primary_h: int) -> Dict:
    """Computes statistical aggregate metrics for evaluated signals."""
    n = len(evaluated_signals)
    if n == 0:
        return {
            'n': 0,
            'win_rates': {h: 0.0 for h in horizons},
            'median_mfe': 0.0,
            'p75_mfe': 0.0,
            'median_mae': 0.0,
            'p75_mae': 0.0,
            'median_mfe_atr': 0.0,
            'median_mae_atr': 0.0,
            'e_ratio': 0.0,
        }

    win_rates = {}
    for h in horizons:
        wins = sum(1 for s in evaluated_signals if s['horizons'][h]['is_win'])
        win_rates[h] = round(wins / n * 100.0, 1)

    mfe_list = [s['horizons'][primary_h]['mfe_pct'] for s in evaluated_signals]
    mae_list = [s['horizons'][primary_h]['mae_pct'] for s in evaluated_signals]
    mfe_atr_list = [s['horizons'][primary_h]['mfe_atr'] for s in evaluated_signals]
    mae_atr_list = [s['horizons'][primary_h]['mae_atr'] for s in evaluated_signals]

    med_mfe = float(np.median(mfe_list))
    p75_mfe = float(np.percentile(mfe_list, 75))
    med_mae = float(np.median(mae_list))
    p75_mae = float(np.percentile(mae_list, 75))

    med_mfe_atr = float(np.median(mfe_atr_list))
    med_mae_atr = float(np.median(mae_atr_list))

    e_ratio = med_mfe / max(med_mae, 0.0001)

    return {
        'n': n,
        'win_rates': win_rates,
        'median_mfe': round(med_mfe, 2),
        'p75_mfe': round(p75_mfe, 2),
        'median_mae': round(med_mae, 2),
        'p75_mae': round(p75_mae, 2),
        'median_mfe_atr': round(med_mfe_atr, 2),
        'median_mae_atr': round(med_mae_atr, 2),
        'e_ratio': round(e_ratio, 2),
    }


def format_oi(usd_val: float) -> str:
    """Formats USD amount into human readable string."""
    if usd_val >= 1e9:
        return f"${usd_val / 1e9:.2f}B"
    elif usd_val >= 1e6:
        return f"${usd_val / 1e6:.1f}M"
    elif usd_val > 0:
        return f"${usd_val:,.0f}"
    return "$0.0"


def main():
    print("=" * 80)
    print("🚀 Running Altcoins (ETH, SOL, HYPE, CC) Quality & Liquidity Diagnostic")
    print(f"Symbols: {SYMBOLS}")
    print(f"Timeframes: {list(TF_CONFIGS.keys())}")
    print("=" * 80)

    # -------------------------------------------------------------------------
    # PART 1: 1000-candle Frontend View Diagnostic (Table 1)
    # -------------------------------------------------------------------------
    print("\n>>> Collecting Table 1 Data (Frontend 1000-candle view)...")
    table1_rows = []

    for sym in SYMBOLS:
        formatted_sym = sym.replace('-', '/')
        for tf in ['1h', '4h', '1d']:
            print(f"  Fetching 1000-bar view for {sym} [{tf}]...")
            try:
                res = get_market_data(
                    symbol=sym,
                    timeframe=tf,
                    limit=1000,
                    enable_protection=True,
                    enable_mtf_filter=True,
                )
                prices = res.get('data', {}).get('price', [])
                markers = res.get('indicators', {}).get('lsur_markers', [])
                eb = res.get('indicators', {}).get('exchange_breakdown', {})

                total_markers = len(markers)
                bull_cnt = sum(1 for m in markers if m.get('direction') == 'bullish' or m.get('position') == 'belowBar')
                bear_cnt = sum(1 for m in markers if m.get('direction') == 'bearish' or m.get('position') == 'aboveBar')

                struct_cnt = sum(1 for m in markers if 'CAP' in m.get('text', '') or 'DIV' in m.get('text', ''))
                breakout_cnt = sum(1 for m in markers if m.get('strategy_type') == 'breakout' or '🚀' in m.get('text', ''))
                reversion_cnt = total_markers - struct_cnt - breakout_cnt

                total_oi = eb.get('total', 0.0)
                binance_oi = eb.get('binance', 0.0)
                okx_oi = eb.get('okx', 0.0)

                binance_pct = (binance_oi / total_oi * 100.0) if total_oi > 0 else 0.0
                okx_pct = (okx_oi / total_oi * 100.0) if total_oi > 0 else 0.0

                table1_rows.append({
                    'symbol': formatted_sym,
                    'timeframe': tf,
                    'total_str': f"{total_markers} ({bull_cnt}↑ / {bear_cnt}↓)",
                    'struct_cnt': struct_cnt,
                    'breakout_cnt': breakout_cnt,
                    'reversion_cnt': reversion_cnt,
                    'total_oi_str': format_oi(total_oi),
                    'binance_pct_str': f"{binance_pct:.1f}%",
                    'okx_pct_str': f"{okx_pct:.1f}%",
                })
            except Exception as e:
                print(f"  ❌ Error fetching 1000-bar {sym} [{tf}]: {e}")
                table1_rows.append({
                    'symbol': formatted_sym,
                    'timeframe': tf,
                    'total_str': f"ERROR",
                    'struct_cnt': 0,
                    'breakout_cnt': 0,
                    'reversion_cnt': 0,
                    'total_oi_str': "ERROR",
                    'binance_pct_str': "N/A",
                    'okx_pct_str': "N/A",
                })

    # -------------------------------------------------------------------------
    # PART 2: Deep History Multi-Horizon Forward Evaluation (Table 2 & Table 3)
    # -------------------------------------------------------------------------
    print("\n>>> Collecting Deep History Data (Table 2 & Table 3)...")

    # Data structure: [symbol][tf] -> evaluated signals list
    evaluated_by_symbol_tf: Dict[str, Dict[str, List[Dict]]] = {
        sym: {'1h': [], '4h': [], '1d': []} for sym in SYMBOLS
    }
    # Store price length and warmup used: [symbol][tf] -> (len_bars, warmup_bars)
    series_info: Dict[str, Dict[str, Tuple[int, int]]] = {
        sym: {} for sym in SYMBOLS
    }

    for tf in ['1h', '4h', '1d']:
        cfg = TF_CONFIGS[tf]
        limit = cfg['limit']
        horizons = cfg['horizons']
        pri_h = cfg['primary_horizon']

        print(f"\n--- Deep Evaluation Timeframe: {tf.upper()} (limit={limit}, horizons={horizons}) ---")

        for sym in SYMBOLS:
            print(f"  Processing {sym} [{tf}]...")
            try:
                data = get_market_data(
                    symbol=sym,
                    timeframe=tf,
                    limit=limit,
                    enable_protection=True,
                    enable_mtf_filter=True,
                )
                prices = data.get('data', {}).get('price', [])
                markers = data.get('indicators', {}).get('lsur_markers', [])
                atr = calculate_atr_pct(prices, period=14)

                n_bars = len(prices)
                # If series is shorter (< 1000 bars), skip 100 bars warmup; otherwise skip 200 bars
                warmup_bars = 100 if n_bars < 1000 else 200
                series_info[sym][tf] = (n_bars, warmup_bars)

                eval_sigs = evaluate_markers(
                    price_data=prices,
                    markers=markers,
                    atr_pct=atr,
                    symbol=sym,
                    timeframe=tf,
                    horizons=horizons,
                    warmup_bars=warmup_bars,
                )
                evaluated_by_symbol_tf[sym][tf] = eval_sigs
                print(f"    Returned {n_bars} bars, {len(markers)} markers -> {len(eval_sigs)} evaluated (warmup={warmup_bars})")
            except Exception as e:
                print(f"  ❌ Error evaluating {sym} [{tf}]: {e}")
                series_info[sym][tf] = (0, 0)
                evaluated_by_symbol_tf[sym][tf] = []

    # -------------------------------------------------------------------------
    # PART 3: Build Markdown Report
    # -------------------------------------------------------------------------
    print("\n>>> Generating Report Markdown...")
    report_lines = []
    ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    report_lines.append("# Solo-Quant 延伸監控幣種（ETH, SOL, HYPE, CC）訊號品質與雙交易所流動性健康度報告")
    report_lines.append(f"**產出時間**：{ts_str}\n")
    report_lines.append(
        "本報告針對 `ETH/USDT`、`SOL/USDT`、`HYPE/USDT`、`CC/USDT` 四大重點監控幣種進行端到端品質驗證：\n"
        "1. **前端 1000 根 K 線訊號密度與雙交易所 OI 佔比**：檢視目前前端終端畫面呈現之訊號健康度與流動性覆蓋。\n"
        "2. **跨週期 Full Macro 訊號品質與風控基準**：評估長週期滑動視窗下之純訊號前瞻方向勝率、Median/P75 MFE & MAE、ATR 倍數與 E-Ratio。\n"
        "3. **三大訊號類型（Structure vs Breakout vs Reversion）效度拆解**：特別檢視高波動幣種（SOL、HYPE、CC）在 `use_dynamic_profiles=True` 下之表現。\n"
    )
    report_lines.append("---\n")

    # -------------------------------------------------------------------------
    # 表 1
    # -------------------------------------------------------------------------
    report_lines.append("### 表 1【前端 1000 根 K 線圖訊號密度與雙交易所流動性健康度檢查（Full Macro 模式）】")
    report_lines.append("| 幣種 | 時間框架 | 1000根K線訊號總數 (多↑ / 空↓) | Structure 數 | Breakout 🚀 數 | Reversion 數 | 總 OI 規模 ($B / $M) | Binance 佔比 (%) | OKX 佔比 (%) |")
    report_lines.append("| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")

    for row in table1_rows:
        report_lines.append(
            f"| **{row['symbol']}** | {row['timeframe']} | {row['total_str']} | "
            f"{row['struct_cnt']} | {row['breakout_cnt']} | {row['reversion_cnt']} | "
            f"{row['total_oi_str']} | {row['binance_pct_str']} | {row['okx_pct_str']} |"
        )
    report_lines.append("\n*(註：呼叫 `get_market_data(..., limit=1000, enable_protection=True, enable_mtf_filter=True)`，完整模擬使用者在前端圖表所見之訊號與流動性佔比)*\n")
    report_lines.append("---\n")

    # -------------------------------------------------------------------------
    # 表 2
    # -------------------------------------------------------------------------
    report_lines.append("### 表 2【四幣種跨週期（1h / 4h / 1d）Full Macro 訊號品質與風控基準表】")
    report_lines.append("| 幣種 | 時間框架 | 有效K線總數 | 訊號數(N) | 短期勝率(%) | 基準中期勝率(%) | 長期勝率(%) | Median MFE(%) | P75 MFE(%) | Median MAE(%) | P75 MAE(%) | Median MFE(ATR) | Median MAE(ATR) | E-Ratio (MFE/MAE) |")
    report_lines.append("| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")

    for sym in SYMBOLS:
        formatted_sym = sym.replace('-', '/')
        for tf in ['1h', '4h', '1d']:
            cfg = TF_CONFIGS[tf]
            h_list = cfg['horizons']
            pri_h = cfg['primary_horizon']
            labels = cfg['horizon_labels']

            eval_sigs = evaluated_by_symbol_tf[sym][tf]
            m = aggregate_metrics(eval_sigs, h_list, pri_h)

            n_bars, warmup_bars = series_info[sym].get(tf, (0, 0))
            valid_bars = max(0, n_bars - warmup_bars)

            h_wins = [f"{m['win_rates'][h]}% ({labels[i]})" for i, h in enumerate(h_list)]

            report_lines.append(
                f"| **{formatted_sym}** | {tf} | {valid_bars} | {m['n']} | "
                f"{h_wins[0]} | {h_wins[1]} | {h_wins[2]} | "
                f"+{m['median_mfe']}% | +{m['p75_mfe']}% | -{m['median_mae']}% | -{m['p75_mae']}% | "
                f"{m['median_mfe_atr']}x | {m['median_mae_atr']}x | **{m['e_ratio']}** |"
            )
    report_lines.append("\n*(註：基準前瞻視窗：1h 為 12h；4h 為 24h；1d 為 7d。短期與長期分別為：1h 4h/24h；4h 12h/48h；1d 3d/14d。新幣歷史小於常規深度時自動跳過前 100 根暖機期)*\n")
    report_lines.append("---\n")

    # -------------------------------------------------------------------------
    # 表 3
    # -------------------------------------------------------------------------
    report_lines.append("### 表 3【各幣種三大訊號類型（Structure vs Breakout vs Reversion）效度拆解】")
    report_lines.append("| 幣種 | 時間框架 | 訊號類型 | 訊號數(N) | 基準方向勝率(%) | Median MFE(%) | Median MAE(%) | E-Ratio |")
    report_lines.append("| :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: |")

    sig_classes = ['Structure (CAP / DIV)', 'Breakout (🚀)', 'Pure Reversion']
    # Focus symbols for Table 3
    t3_symbols = ['SOL-USDT', 'HYPE-USDT', 'CC-USDT', 'ETH-USDT']

    for sym in t3_symbols:
        formatted_sym = sym.replace('-', '/')
        for tf in ['1h', '4h']:
            cfg = TF_CONFIGS[tf]
            h_list = cfg['horizons']
            pri_h = cfg['primary_horizon']
            all_sigs = evaluated_by_symbol_tf[sym][tf]

            for cls in sig_classes:
                subset = [s for s in all_sigs if s['class'] == cls]
                m = aggregate_metrics(subset, h_list, pri_h)
                win_rate = m['win_rates'][pri_h]
                report_lines.append(
                    f"| **{formatted_sym}** | {tf} | {cls} | {m['n']} | {win_rate}% | "
                    f"+{m['median_mfe']}% | -{m['median_mae']}% | **{m['e_ratio']}** |"
                )

    report_lines.append("\n*(註：檢視高波動性小幣與主流公鏈在 1h 與 4h 級別下，Structure 結構性拐點、Breakout 趨勢突破與 Pure Reversion 均值回歸的獨立勝率與 E-Ratio)*\n")

    report_content = "\n".join(report_lines)

    # Output to markdown file
    output_path = Path(__file__).resolve().parent / "altcoins_evaluation_report.md"
    output_path.write_text(report_content, encoding="utf-8")
    print(f"\n✅ Report written successfully to: {output_path}")

    # Print to stdout
    print("\n" + "=" * 80)
    print(report_content)
    print("=" * 80)


if __name__ == '__main__':
    main()
