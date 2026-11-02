import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from api.main import run_signal_backtest, SignalBacktestParams

BENCHMARKS = [
    {"name": "BTC 1h (30d)", "symbol": "BTC/USDT", "tf": "1h", "days": 30, "sl": 1.2, "tp": 1.80, "act": 0.60, "trail": 0.25},
    {"name": "ETH 4h (90d)", "symbol": "ETH/USDT", "tf": "4h", "days": 90, "sl": 2.8, "tp": 3.80, "act": 1.60, "trail": 0.65},
    {"name": "SOL 4h (90d)", "symbol": "SOL/USDT", "tf": "4h", "days": 90, "sl": 3.5, "tp": 3.80, "act": 1.65, "trail": 0.65},
    {"name": "HYPE 4h (90d)", "symbol": "HYPE/USDT", "tf": "4h", "days": 90, "sl": 5.5, "tp": 5.20, "act": 2.20, "trail": 0.50},
    {"name": "BTC 4h (90d)", "symbol": "BTC/USDT", "tf": "4h", "days": 90, "sl": 2.0, "tp": 3.80, "act": 1.50, "trail": 0.40},
    {"name": "HYPE 1h (30d)", "symbol": "HYPE/USDT", "tf": "1h", "days": 30, "sl": 2.4, "tp": 2.80, "act": 1.20, "trail": 0.35},
]

print(f"{'Target':<16} | {'Trades':<7} | {'WinRate':<8} | {'PnL ($)':<11} | {'PnL (%)':<9} | {'ProfitFactor':<13} | {'MaxDD (%)':<9}")
print("-" * 95)

for b in BENCHMARKS:
    params = SignalBacktestParams(
        symbol=b["symbol"],
        timeframe=b["tf"],
        duration_days=b["days"],
        stop_loss_pct=b["sl"],
        take_profit_pct=b["tp"],
        trailing_activation_pct=b["act"],
        trailing_stop_pct=b["trail"],
        min_score=0.0,
        enable_partial_tp=False,
        enable_protection=True,
        enable_mtf_filter=True,
        use_dynamic_profiles=True,
    )
    res = run_signal_backtest(params)
    m = res["metrics"]
    print(f"{b['name']:<16} | {m['total_trades']:<7} | {m['win_rate']:<8.1f}% | {m['pnl']:<+11.2f} | {m['pnl_percent']:<+9.2f}% | {m['profit_factor']:<13.2f} | {m['max_drawdown_pct']:<9.2f}%")
