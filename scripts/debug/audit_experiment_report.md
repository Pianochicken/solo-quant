# Solo-Quant Red-Team Audit & Falsification Experiments Report
**Generated at**: 2026-11-25T21:01:17.236980+00:00 | **Mode**: `db` | **Synthetic**: False
> **Signal Engine Metadata (`api/core/indicators.py`)**: `is_hype_hacks_deleted=True` (`use_legacy_hype_rules` & all 5 `is_hype` special cases removed; unified `is_alt` `-10/+10` RSI & uniform ATR EMA50 bounds). Phase 1/2 causal defaults enforced: `mtf_close_aligned=True`, `use_btc_history=True`, `setup_symmetry=True`, `use_coin_oi_all=True`, `price_group_cap=None`, `single_trend_guard=False`.

## 0. Phase 0 — Stage 0 (Raw Baseline Snapshot)
| Symbol | Timeframe | Clean Window Days | Trades | Win Rate (%) | Profit Factor | Expectancy per Trade (%) | Max Drawdown (%) | MAR Ratio | Sharpe | Avg MFE (%) | Avg MAE (%) | MFE/MAE Ratio |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| BTC/USDT | 1h | 199.75 | 103 | 54.4 | 0.71 | -0.149 | 16.20 | -1.49 | -2.00 | 1.95 | 1.46 | 1.34 |
| BTC/USDT | 4h | 205.0 | 45 | 40.0 | 0.50 | -0.565 | 26.73 | -1.34 | -2.78 | 3.45 | 3.48 | 0.99 |
| ETH/USDT | 1h | 198.71 | 84 | 63.1 | 0.97 | -0.007 | 8.08 | -0.28 | -0.05 | 2.41 | 2.01 | 1.20 |
| ETH/USDT | 4h | 196.83 | 36 | 66.7 | 1.33 | +0.339 | 7.57 | 2.15 | 1.14 | 5.79 | 3.52 | 1.64 |
| SOL/USDT | 1h | 198.71 | 90 | 58.9 | 0.85 | -0.097 | 14.75 | -1.08 | -0.78 | 2.60 | 2.35 | 1.11 |
| SOL/USDT | 4h | 196.83 | 35 | 62.9 | 0.94 | -0.059 | 10.47 | -0.29 | -0.19 | 5.44 | 4.35 | 1.25 |
| HYPE/USDT | 1h | 198.5 | 112 | 56.2 | 0.60 | -0.372 | 32.47 | -1.49 | -2.95 | 3.31 | 3.35 | 0.99 |
| HYPE/USDT | 4h | 196.67 | 51 | 58.8 | 0.72 | -0.510 | 13.12 | -1.29 | -1.40 | 6.85 | 6.42 | 1.07 |
| CC/USDT | 1h | 195.79 | 82 | 62.2 | 0.84 | -0.151 | 16.03 | -0.98 | -0.84 | 3.20 | 3.24 | 0.99 |
| CC/USDT | 4h | 194.0 | 33 | 57.6 | 0.69 | -0.591 | 9.90 | -1.21 | -1.07 | 6.04 | 6.11 | 0.99 |

## 1. Stage 0 -> Stage 1C De-hallucinated Baseline & Slippage/Funding Stress Test
| Symbol | TF | Stage | Days | Trades | WR (%) | PF | Exp/Trade (%) | MaxDD (%) | MAR | Sharpe | Avg MFE (%) | Avg MAE (%) | MFE/MAE | Funding ($) |
| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| BTC/USDT | 1h | Stage 0 (Raw) | 199.75 | 103 | 54.4 | 0.71 | -0.149 | 16.20 | -1.49 | -2.00 | 1.95 | 1.46 | 1.34 | +0.00 |
| BTC/USDT | 1h | Stage 1A (Causality) | 199.75 | 104 | 54.8 | 0.72 | -0.145 | 16.84 | -1.41 | -1.96 | 1.94 | 1.45 | 1.34 | +0.00 |
| BTC/USDT | 1h | Stage 1B (Trail+SM+OI) | 199.75 | 120 | 60.0 | 0.70 | -0.149 | 17.71 | -1.55 | -2.37 | 1.70 | 1.59 | 1.07 | +0.00 |
| BTC/USDT | 1h | Stage 1C (0bps+Fund) | 199.75 | 120 | 60.0 | 0.70 | -0.148 | 17.67 | -1.54 | -2.35 | 1.70 | 1.59 | 1.07 | +12.11 |
| BTC/USDT | 1h | Stage 1C (5bps+Fund) | 199.75 | 119 | 58.0 | 0.54 | -0.262 | 26.82 | -1.58 | -4.02 | 1.70 | 1.59 | 1.07 | +9.83 |
| BTC/USDT | 1h | Stage 1C (15bps+Fund) | 199.75 | 119 | 53.8 | 0.34 | -0.473 | 42.43 | -1.48 | -6.63 | 1.70 | 1.59 | 1.07 | +8.17 |
| BTC/USDT | 4h | Stage 0 (Raw) | 205.0 | 45 | 40.0 | 0.50 | -0.565 | 26.73 | -1.34 | -2.78 | 3.45 | 3.48 | 0.99 | +0.00 |
| BTC/USDT | 4h | Stage 1A (Causality) | 205.0 | 45 | 40.0 | 0.50 | -0.565 | 26.73 | -1.34 | -2.78 | 3.45 | 3.48 | 0.99 | +0.00 |
| BTC/USDT | 4h | Stage 1B (Trail+SM+OI) | 205.0 | 60 | 46.7 | 0.80 | -0.204 | 19.40 | -1.05 | -1.08 | 3.19 | 3.40 | 0.94 | +0.00 |
| BTC/USDT | 4h | Stage 1C (0bps+Fund) | 205.0 | 60 | 46.7 | 0.79 | -0.207 | 19.48 | -1.06 | -1.10 | 3.19 | 3.40 | 0.94 | -13.28 |
| BTC/USDT | 4h | Stage 1C (5bps+Fund) | 205.0 | 60 | 45.0 | 0.68 | -0.355 | 25.55 | -1.24 | -1.87 | 3.19 | 3.40 | 0.94 | -16.27 |
| BTC/USDT | 4h | Stage 1C (15bps+Fund) | 205.0 | 60 | 45.0 | 0.56 | -0.554 | 31.90 | -1.37 | -2.90 | 3.19 | 3.40 | 0.94 | -14.69 |
| ETH/USDT | 1h | Stage 0 (Raw) | 198.71 | 84 | 63.1 | 0.97 | -0.007 | 8.08 | -0.28 | -0.05 | 2.41 | 2.01 | 1.20 | +0.00 |
| ETH/USDT | 1h | Stage 1A (Causality) | 198.71 | 99 | 61.6 | 0.86 | -0.080 | 10.42 | -1.38 | -0.77 | 2.33 | 2.15 | 1.08 | +0.00 |
| ETH/USDT | 1h | Stage 1B (Trail+SM+OI) | 198.71 | 102 | 58.8 | 0.81 | -0.133 | 17.68 | -1.28 | -1.26 | 2.12 | 2.08 | 1.02 | +0.00 |
| ETH/USDT | 1h | Stage 1C (0bps+Fund) | 198.71 | 102 | 58.8 | 0.81 | -0.133 | 17.63 | -1.28 | -1.26 | 2.12 | 2.08 | 1.02 | +4.36 |
| ETH/USDT | 1h | Stage 1C (5bps+Fund) | 198.71 | 100 | 57.0 | 0.70 | -0.248 | 24.91 | -1.47 | -2.30 | 2.12 | 2.08 | 1.02 | +4.67 |
| ETH/USDT | 1h | Stage 1C (15bps+Fund) | 198.71 | 100 | 57.0 | 0.55 | -0.412 | 34.99 | -1.50 | -3.70 | 2.12 | 2.08 | 1.02 | +5.14 |
| ETH/USDT | 4h | Stage 0 (Raw) | 196.83 | 36 | 66.7 | 1.33 | +0.339 | 7.57 | 2.15 | 1.14 | 5.79 | 3.52 | 1.64 | +0.00 |
| ETH/USDT | 4h | Stage 1A (Causality) | 196.83 | 40 | 62.5 | 1.19 | +0.206 | 9.11 | 1.13 | 0.75 | 5.41 | 3.87 | 1.40 | +0.00 |
| ETH/USDT | 4h | Stage 1B (Trail+SM+OI) | 196.83 | 49 | 65.3 | 1.19 | +0.204 | 11.27 | 1.13 | 0.85 | 5.10 | 3.88 | 1.31 | +0.00 |
| ETH/USDT | 4h | Stage 1C (0bps+Fund) | 196.83 | 49 | 65.3 | 1.19 | +0.201 | 11.29 | 1.10 | 0.83 | 5.10 | 3.88 | 1.31 | -12.42 |
| ETH/USDT | 4h | Stage 1C (5bps+Fund) | 196.83 | 49 | 63.3 | 1.05 | +0.069 | 12.25 | 0.26 | 0.28 | 5.10 | 3.88 | 1.31 | -11.51 |
| ETH/USDT | 4h | Stage 1C (15bps+Fund) | 196.83 | 49 | 63.3 | 0.90 | -0.095 | 14.06 | -0.49 | -0.37 | 5.10 | 3.88 | 1.31 | -10.45 |
| SOL/USDT | 1h | Stage 0 (Raw) | 198.71 | 90 | 58.9 | 0.85 | -0.097 | 14.75 | -1.08 | -0.78 | 2.60 | 2.35 | 1.11 | +0.00 |
| SOL/USDT | 1h | Stage 1A (Causality) | 198.71 | 111 | 56.8 | 0.73 | -0.212 | 26.14 | -1.35 | -1.91 | 2.43 | 2.45 | 0.99 | +0.00 |
| SOL/USDT | 1h | Stage 1B (Trail+SM+OI) | 198.71 | 122 | 59.0 | 0.72 | -0.218 | 25.15 | -1.54 | -2.11 | 2.07 | 2.47 | 0.84 | +0.00 |
| SOL/USDT | 1h | Stage 1C (0bps+Fund) | 198.71 | 122 | 59.0 | 0.72 | -0.218 | 25.18 | -1.54 | -2.12 | 2.07 | 2.47 | 0.84 | -5.34 |
| SOL/USDT | 1h | Stage 1C (5bps+Fund) | 198.71 | 122 | 59.0 | 0.67 | -0.276 | 30.34 | -1.52 | -2.64 | 2.07 | 2.47 | 0.84 | -5.92 |
| SOL/USDT | 1h | Stage 1C (15bps+Fund) | 198.71 | 121 | 57.0 | 0.52 | -0.470 | 43.27 | -1.46 | -4.19 | 2.07 | 2.47 | 0.84 | -6.20 |
| SOL/USDT | 4h | Stage 0 (Raw) | 196.83 | 35 | 62.9 | 0.94 | -0.059 | 10.47 | -0.29 | -0.19 | 5.44 | 4.35 | 1.25 | +0.00 |
| SOL/USDT | 4h | Stage 1A (Causality) | 196.83 | 47 | 55.3 | 0.67 | -0.448 | 17.88 | -1.17 | -1.67 | 4.84 | 5.22 | 0.93 | +0.00 |
| SOL/USDT | 4h | Stage 1B (Trail+SM+OI) | 196.83 | 59 | 64.4 | 1.06 | +0.095 | 11.81 | 0.40 | 0.38 | 5.10 | 4.63 | 1.10 | +0.00 |
| SOL/USDT | 4h | Stage 1C (0bps+Fund) | 196.83 | 59 | 64.4 | 1.06 | +0.094 | 11.83 | 0.40 | 0.37 | 5.10 | 4.63 | 1.10 | -4.11 |
| SOL/USDT | 4h | Stage 1C (5bps+Fund) | 196.83 | 59 | 64.4 | 0.99 | +0.010 | 13.04 | -0.05 | 0.05 | 5.10 | 4.63 | 1.10 | -3.78 |
| SOL/USDT | 4h | Stage 1C (15bps+Fund) | 196.83 | 58 | 63.8 | 0.86 | -0.162 | 16.11 | -0.63 | -0.62 | 5.10 | 4.63 | 1.10 | -3.94 |
| HYPE/USDT | 1h | Stage 0 (Raw) | 198.5 | 112 | 56.2 | 0.60 | -0.372 | 32.47 | -1.49 | -2.95 | 3.31 | 3.35 | 0.99 | +0.00 |
| HYPE/USDT | 1h | Stage 1A (Causality) | 198.5 | 131 | 57.3 | 0.65 | -0.313 | 33.19 | -1.45 | -2.66 | 3.02 | 3.42 | 0.88 | +0.00 |
| HYPE/USDT | 1h | Stage 1B (Trail+SM+OI) | 198.5 | 136 | 64.0 | 0.93 | -0.046 | 25.74 | -0.46 | -0.40 | 3.09 | 3.33 | 0.93 | +0.00 |
| HYPE/USDT | 1h | Stage 1C (0bps+Fund) | 198.5 | 136 | 64.0 | 0.93 | -0.046 | 25.77 | -0.46 | -0.40 | 3.09 | 3.33 | 0.93 | +1.78 |
| HYPE/USDT | 1h | Stage 1C (5bps+Fund) | 198.5 | 136 | 63.2 | 0.84 | -0.141 | 28.59 | -0.95 | -1.18 | 3.09 | 3.33 | 0.93 | +0.92 |
| HYPE/USDT | 1h | Stage 1C (15bps+Fund) | 198.5 | 136 | 61.8 | 0.68 | -0.336 | 38.03 | -1.31 | -2.75 | 3.09 | 3.33 | 0.93 | +2.03 |
| HYPE/USDT | 4h | Stage 0 (Raw) | 196.67 | 51 | 58.8 | 0.72 | -0.510 | 13.12 | -1.29 | -1.40 | 6.85 | 6.42 | 1.07 | +0.00 |
| HYPE/USDT | 4h | Stage 1A (Causality) | 196.67 | 51 | 62.7 | 0.82 | -0.282 | 12.32 | -0.82 | -0.79 | 6.72 | 6.32 | 1.06 | +0.00 |
| HYPE/USDT | 4h | Stage 1B (Trail+SM+OI) | 196.67 | 56 | 67.9 | 1.07 | +0.136 | 9.09 | 0.46 | 0.37 | 7.01 | 6.54 | 1.07 | +0.00 |
| HYPE/USDT | 4h | Stage 1C (0bps+Fund) | 196.67 | 56 | 67.9 | 1.07 | +0.138 | 9.07 | 0.48 | 0.38 | 7.01 | 6.54 | 1.07 | +4.51 |
| HYPE/USDT | 4h | Stage 1C (5bps+Fund) | 196.67 | 56 | 67.9 | 1.01 | +0.044 | 9.84 | 0.07 | 0.12 | 7.01 | 6.54 | 1.07 | +4.42 |
| HYPE/USDT | 4h | Stage 1C (15bps+Fund) | 196.67 | 56 | 66.1 | 0.85 | -0.252 | 13.90 | -0.70 | -0.70 | 7.01 | 6.54 | 1.07 | +4.62 |
| CC/USDT | 1h | Stage 0 (Raw) | 195.79 | 82 | 62.2 | 0.84 | -0.151 | 16.03 | -0.98 | -0.84 | 3.20 | 3.24 | 0.99 | +0.00 |
| CC/USDT | 1h | Stage 1A (Causality) | 195.79 | 111 | 64.0 | 0.92 | -0.056 | 15.94 | -0.59 | -0.37 | 2.91 | 3.03 | 0.96 | +0.00 |
| CC/USDT | 1h | Stage 1B (Trail+SM+OI) | 195.79 | 120 | 71.7 | 0.96 | -0.018 | 20.46 | -0.22 | -0.13 | 2.75 | 2.94 | 0.94 | +0.00 |
| CC/USDT | 1h | Stage 1C (0bps+Fund) | 195.79 | 120 | 71.7 | 0.96 | -0.019 | 20.50 | -0.22 | -0.13 | 2.75 | 2.94 | 0.94 | -1.99 |
| CC/USDT | 1h | Stage 1C (5bps+Fund) | 195.79 | 117 | 69.2 | 0.79 | -0.179 | 23.99 | -1.01 | -1.24 | 2.75 | 2.94 | 0.94 | -10.49 |
| CC/USDT | 1h | Stage 1C (15bps+Fund) | 195.79 | 113 | 66.4 | 0.68 | -0.339 | 24.64 | -1.53 | -2.15 | 2.75 | 2.94 | 0.94 | -11.90 |
| CC/USDT | 4h | Stage 0 (Raw) | 194.0 | 33 | 57.6 | 0.69 | -0.591 | 9.90 | -1.21 | -1.07 | 6.04 | 6.11 | 0.99 | +0.00 |
| CC/USDT | 4h | Stage 1A (Causality) | 194.0 | 43 | 55.8 | 0.66 | -0.701 | 13.80 | -1.29 | -1.56 | 5.90 | 6.18 | 0.95 | +0.00 |
| CC/USDT | 4h | Stage 1B (Trail+SM+OI) | 194.0 | 49 | 65.3 | 1.12 | +0.220 | 9.60 | 0.64 | 0.54 | 6.06 | 5.86 | 1.03 | +0.00 |
| CC/USDT | 4h | Stage 1C (0bps+Fund) | 194.0 | 49 | 65.3 | 1.12 | +0.224 | 9.63 | 0.65 | 0.55 | 6.06 | 5.86 | 1.03 | +6.51 |
| CC/USDT | 4h | Stage 1C (5bps+Fund) | 194.0 | 49 | 65.3 | 1.06 | +0.126 | 10.11 | 0.31 | 0.31 | 6.06 | 5.86 | 1.03 | +6.39 |
| CC/USDT | 4h | Stage 1C (15bps+Fund) | 194.0 | 49 | 65.3 | 0.97 | -0.020 | 11.03 | -0.13 | -0.05 | 6.06 | 5.86 | 1.03 | +6.32 |

## 2. Exit Architecture Stress Test (Partial TP + Wide Trailing vs Narrow Trailing)
| Symbol | TF | Architecture | Trades | WR (%) | PF | Exp/Trade (%) | MaxDD (%) | MAR |
| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| BTC/USDT | 1h | SingleFullTP_Narrow (5bps) | 119 | 58.0 | 0.54 | -0.262 | 26.82 | -1.58 |
| BTC/USDT | 1h | PartialTP+1.0xATR (5bps) | 120 | 60.0 | 0.36 | -0.348 | 33.52 | -1.55 |
| BTC/USDT | 1h | PartialTP+1.5xATR (5bps) | 120 | 60.0 | 0.34 | -0.361 | 34.40 | -1.55 |
| BTC/USDT | 1h | PartialTP+WidePct (5bps) | 120 | 60.0 | 0.36 | -0.351 | 33.65 | -1.55 |
| BTC/USDT | 1h | SingleFullTP_Narrow (15bps) | 119 | 53.8 | 0.34 | -0.473 | 42.43 | -1.48 |
| BTC/USDT | 1h | PartialTP+1.0xATR (15bps) | 120 | 60.0 | 0.23 | -0.485 | 43.17 | -1.48 |
| BTC/USDT | 1h | PartialTP+1.5xATR (15bps) | 120 | 60.0 | 0.21 | -0.495 | 43.78 | -1.48 |
| BTC/USDT | 1h | PartialTP+WidePct (15bps) | 120 | 60.0 | 0.23 | -0.486 | 43.14 | -1.48 |
| BTC/USDT | 4h | SingleFullTP_Narrow (5bps) | 60 | 45.0 | 0.68 | -0.355 | 25.55 | -1.24 |
| BTC/USDT | 4h | PartialTP+1.0xATR (5bps) | 58 | 46.6 | 0.39 | -0.697 | 35.67 | -1.41 |
| BTC/USDT | 4h | PartialTP+1.5xATR (5bps) | 57 | 47.4 | 0.38 | -0.696 | 35.15 | -1.41 |
| BTC/USDT | 4h | PartialTP+WidePct (5bps) | 59 | 45.8 | 0.42 | -0.669 | 34.39 | -1.44 |
| BTC/USDT | 4h | SingleFullTP_Narrow (15bps) | 60 | 45.0 | 0.56 | -0.554 | 31.90 | -1.37 |
| BTC/USDT | 4h | PartialTP+1.0xATR (15bps) | 58 | 46.6 | 0.28 | -0.895 | 40.15 | -1.45 |
| BTC/USDT | 4h | PartialTP+1.5xATR (15bps) | 57 | 47.4 | 0.28 | -0.884 | 39.30 | -1.46 |
| BTC/USDT | 4h | PartialTP+WidePct (15bps) | 59 | 45.8 | 0.33 | -0.843 | 39.15 | -1.45 |
| ETH/USDT | 1h | SingleFullTP_Narrow (5bps) | 100 | 57.0 | 0.70 | -0.248 | 24.91 | -1.47 |
| ETH/USDT | 1h | PartialTP+1.0xATR (5bps) | 100 | 58.0 | 0.47 | -0.434 | 35.54 | -1.52 |
| ETH/USDT | 1h | PartialTP+1.5xATR (5bps) | 100 | 58.0 | 0.43 | -0.468 | 37.51 | -1.51 |
| ETH/USDT | 1h | PartialTP+WidePct (5bps) | 100 | 58.0 | 0.44 | -0.454 | 36.72 | -1.51 |
| ETH/USDT | 1h | SingleFullTP_Narrow (15bps) | 100 | 57.0 | 0.55 | -0.412 | 34.99 | -1.50 |
| ETH/USDT | 1h | PartialTP+1.0xATR (15bps) | 100 | 58.0 | 0.36 | -0.580 | 43.83 | -1.47 |
| ETH/USDT | 1h | PartialTP+1.5xATR (15bps) | 100 | 58.0 | 0.33 | -0.610 | 45.37 | -1.46 |
| ETH/USDT | 1h | PartialTP+WidePct (15bps) | 100 | 58.0 | 0.34 | -0.599 | 44.81 | -1.46 |
| ETH/USDT | 4h | SingleFullTP_Narrow (5bps) | 49 | 63.3 | 1.05 | +0.069 | 12.25 | 0.26 |
| ETH/USDT | 4h | PartialTP+1.0xATR (5bps) | 49 | 65.3 | 0.74 | -0.247 | 15.98 | -0.96 |
| ETH/USDT | 4h | PartialTP+1.5xATR (5bps) | 49 | 65.3 | 0.69 | -0.297 | 15.33 | -1.18 |
| ETH/USDT | 4h | PartialTP+WidePct (5bps) | 49 | 65.3 | 0.74 | -0.239 | 15.23 | -0.98 |
| ETH/USDT | 4h | SingleFullTP_Narrow (15bps) | 49 | 63.3 | 0.90 | -0.095 | 14.06 | -0.49 |
| ETH/USDT | 4h | PartialTP+1.0xATR (15bps) | 49 | 65.3 | 0.64 | -0.368 | 17.28 | -1.22 |
| ETH/USDT | 4h | PartialTP+1.5xATR (15bps) | 49 | 65.3 | 0.60 | -0.407 | 16.58 | -1.38 |
| ETH/USDT | 4h | PartialTP+WidePct (15bps) | 49 | 65.3 | 0.65 | -0.356 | 16.51 | -1.24 |
| SOL/USDT | 1h | SingleFullTP_Narrow (5bps) | 122 | 59.0 | 0.67 | -0.276 | 30.34 | -1.52 |
| SOL/USDT | 1h | PartialTP+1.0xATR (5bps) | 121 | 58.7 | 0.43 | -0.497 | 45.46 | -1.45 |
| SOL/USDT | 1h | PartialTP+1.5xATR (5bps) | 120 | 58.3 | 0.43 | -0.502 | 45.54 | -1.45 |
| SOL/USDT | 1h | PartialTP+WidePct (5bps) | 120 | 58.3 | 0.43 | -0.503 | 45.59 | -1.45 |
| SOL/USDT | 1h | SingleFullTP_Narrow (15bps) | 121 | 57.0 | 0.52 | -0.470 | 43.27 | -1.46 |
| SOL/USDT | 1h | PartialTP+1.0xATR (15bps) | 122 | 59.0 | 0.36 | -0.613 | 51.77 | -1.41 |
| SOL/USDT | 1h | PartialTP+1.5xATR (15bps) | 121 | 58.7 | 0.34 | -0.635 | 52.66 | -1.40 |
| SOL/USDT | 1h | PartialTP+WidePct (15bps) | 121 | 58.7 | 0.35 | -0.631 | 52.47 | -1.40 |
| SOL/USDT | 4h | SingleFullTP_Narrow (5bps) | 59 | 64.4 | 0.99 | +0.010 | 13.04 | -0.05 |
| SOL/USDT | 4h | PartialTP+1.0xATR (5bps) | 59 | 64.4 | 0.61 | -0.444 | 21.65 | -1.14 |
| SOL/USDT | 4h | PartialTP+1.5xATR (5bps) | 59 | 64.4 | 0.60 | -0.463 | 22.16 | -1.15 |
| SOL/USDT | 4h | PartialTP+WidePct (5bps) | 59 | 64.4 | 0.61 | -0.442 | 21.87 | -1.12 |
| SOL/USDT | 4h | SingleFullTP_Narrow (15bps) | 58 | 63.8 | 0.86 | -0.162 | 16.11 | -0.63 |
| SOL/USDT | 4h | PartialTP+1.0xATR (15bps) | 59 | 64.4 | 0.53 | -0.572 | 23.91 | -1.24 |
| SOL/USDT | 4h | PartialTP+1.5xATR (15bps) | 59 | 64.4 | 0.52 | -0.587 | 24.29 | -1.25 |
| SOL/USDT | 4h | PartialTP+WidePct (15bps) | 59 | 64.4 | 0.53 | -0.574 | 24.17 | -1.23 |
| HYPE/USDT | 1h | SingleFullTP_Narrow (5bps) | 136 | 63.2 | 0.84 | -0.141 | 28.59 | -0.95 |
| HYPE/USDT | 1h | PartialTP+1.0xATR (5bps) | 135 | 63.7 | 0.53 | -0.446 | 44.09 | -1.37 |
| HYPE/USDT | 1h | PartialTP+1.5xATR (5bps) | 134 | 63.4 | 0.53 | -0.444 | 43.60 | -1.38 |
| HYPE/USDT | 1h | PartialTP+WidePct (5bps) | 134 | 63.4 | 0.55 | -0.426 | 42.66 | -1.37 |
| HYPE/USDT | 1h | SingleFullTP_Narrow (15bps) | 136 | 61.8 | 0.68 | -0.336 | 38.03 | -1.31 |
| HYPE/USDT | 1h | PartialTP+1.0xATR (15bps) | 136 | 63.2 | 0.44 | -0.567 | 50.14 | -1.35 |
| HYPE/USDT | 1h | PartialTP+1.5xATR (15bps) | 135 | 63.0 | 0.45 | -0.561 | 49.55 | -1.36 |
| HYPE/USDT | 1h | PartialTP+WidePct (15bps) | 135 | 63.0 | 0.46 | -0.547 | 48.89 | -1.36 |
| HYPE/USDT | 4h | SingleFullTP_Narrow (5bps) | 56 | 67.9 | 1.01 | +0.044 | 9.84 | 0.07 |
| HYPE/USDT | 4h | PartialTP+1.0xATR (5bps) | 55 | 69.1 | 0.55 | -0.707 | 18.05 | -1.30 |
| HYPE/USDT | 4h | PartialTP+1.5xATR (5bps) | 55 | 69.1 | 0.52 | -0.755 | 18.48 | -1.34 |
| HYPE/USDT | 4h | PartialTP+WidePct (5bps) | 55 | 69.1 | 0.53 | -0.734 | 18.11 | -1.34 |
| HYPE/USDT | 4h | SingleFullTP_Narrow (15bps) | 56 | 66.1 | 0.85 | -0.252 | 13.90 | -0.70 |
| HYPE/USDT | 4h | PartialTP+1.0xATR (15bps) | 56 | 67.9 | 0.45 | -0.934 | 21.16 | -1.40 |
| HYPE/USDT | 4h | PartialTP+1.5xATR (15bps) | 56 | 67.9 | 0.43 | -0.977 | 21.52 | -1.43 |
| HYPE/USDT | 4h | PartialTP+WidePct (15bps) | 56 | 67.9 | 0.44 | -0.961 | 21.23 | -1.43 |
| CC/USDT | 1h | SingleFullTP_Narrow (5bps) | 117 | 69.2 | 0.79 | -0.179 | 23.99 | -1.01 |
| CC/USDT | 1h | PartialTP+1.0xATR (5bps) | 119 | 71.4 | 0.70 | -0.253 | 22.95 | -1.39 |
| CC/USDT | 1h | PartialTP+1.5xATR (5bps) | 119 | 71.4 | 0.70 | -0.256 | 23.42 | -1.38 |
| CC/USDT | 1h | PartialTP+WidePct (5bps) | 119 | 71.4 | 0.68 | -0.266 | 23.38 | -1.42 |
| CC/USDT | 1h | SingleFullTP_Narrow (15bps) | 113 | 66.4 | 0.68 | -0.339 | 24.64 | -1.53 |
| CC/USDT | 1h | PartialTP+1.0xATR (15bps) | 119 | 71.4 | 0.63 | -0.335 | 25.04 | -1.55 |
| CC/USDT | 1h | PartialTP+1.5xATR (15bps) | 119 | 71.4 | 0.61 | -0.354 | 25.44 | -1.58 |
| CC/USDT | 1h | PartialTP+WidePct (15bps) | 119 | 71.4 | 0.61 | -0.358 | 25.69 | -1.58 |
| CC/USDT | 4h | SingleFullTP_Narrow (5bps) | 49 | 65.3 | 1.06 | +0.126 | 10.11 | 0.31 |
| CC/USDT | 4h | PartialTP+1.0xATR (5bps) | 49 | 65.3 | 0.75 | -0.393 | 11.93 | -0.99 |
| CC/USDT | 4h | PartialTP+1.5xATR (5bps) | 46 | 63.0 | 0.71 | -0.502 | 11.76 | -1.19 |
| CC/USDT | 4h | PartialTP+WidePct (5bps) | 46 | 63.0 | 0.72 | -0.475 | 11.59 | -1.15 |
| CC/USDT | 4h | SingleFullTP_Narrow (15bps) | 49 | 65.3 | 0.97 | -0.020 | 11.03 | -0.13 |
| CC/USDT | 4h | PartialTP+1.0xATR (15bps) | 49 | 65.3 | 0.69 | -0.523 | 12.68 | -1.19 |
| CC/USDT | 4h | PartialTP+1.5xATR (15bps) | 46 | 63.0 | 0.66 | -0.615 | 12.50 | -1.32 |
| CC/USDT | 4h | PartialTP+WidePct (15bps) | 46 | 63.0 | 0.67 | -0.589 | 12.35 | -1.28 |

## 3. Walk-Forward (60% IS vs 40% OOS) Ablation Study
| Symbol | TF | Variant | IS Trades | IS Exp (%) | IS MAR | OOS Trades | OOS WR (%) | OOS PF | OOS Exp (%) | OOS DD (%) | OOS MAR |
| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| BTC/USDT | 1h | Variant B (Pruned Production) | 84 | -0.248 | -2.29 | 35 | 57.1 | 0.48 | -0.295 | 11.39 | -3.21 |
| BTC/USDT | 1h | Variant C (Price Cap 1.5) | 73 | -0.186 | -1.91 | 27 | 59.3 | 0.51 | -0.259 | 7.26 | -3.66 |
| BTC/USDT | 1h | Variant D (Single Guard) | 81 | -0.188 | -2.06 | 32 | 53.1 | 0.44 | -0.307 | 10.52 | -3.34 |
| BTC/USDT | 4h | Variant B (Pruned Production) | 39 | -0.315 | -1.57 | 21 | 42.9 | 0.62 | -0.431 | 14.28 | -2.32 |
| BTC/USDT | 4h | Variant C (Price Cap 1.5) | 37 | -0.212 | -1.20 | 20 | 40.0 | 0.57 | -0.522 | 14.28 | -2.58 |
| BTC/USDT | 4h | Variant D (Single Guard) | 39 | -0.164 | -1.10 | 20 | 40.0 | 0.57 | -0.522 | 14.28 | -2.58 |
| ETH/USDT | 1h | Variant B (Pruned Production) | 65 | -0.311 | -2.24 | 35 | 62.9 | 0.81 | -0.131 | 8.45 | -2.30 |
| ETH/USDT | 1h | Variant C (Price Cap 1.5) | 57 | -0.469 | -2.19 | 25 | 60.0 | 0.70 | -0.228 | 9.29 | -2.47 |
| ETH/USDT | 1h | Variant D (Single Guard) | 66 | -0.407 | -2.19 | 27 | 55.6 | 0.58 | -0.359 | 12.69 | -2.79 |
| ETH/USDT | 4h | Variant B (Pruned Production) | 35 | -0.036 | -0.35 | 14 | 71.4 | 1.37 | +0.347 | 2.97 | 5.43 |
| ETH/USDT | 4h | Variant C (Price Cap 1.5) | 32 | +0.123 | 0.70 | 11 | 63.6 | 0.97 | -0.012 | 4.25 | -0.27 |
| ETH/USDT | 4h | Variant D (Single Guard) | 34 | +0.054 | 0.21 | 12 | 58.3 | 0.78 | -0.260 | 5.80 | -1.80 |
| SOL/USDT | 1h | Variant B (Pruned Production) | 84 | -0.289 | -2.18 | 38 | 63.2 | 0.69 | -0.249 | 13.47 | -2.60 |
| SOL/USDT | 1h | Variant C (Price Cap 1.5) | 78 | -0.248 | -2.13 | 28 | 67.9 | 0.87 | -0.079 | 8.99 | -1.17 |
| SOL/USDT | 1h | Variant D (Single Guard) | 95 | -0.254 | -2.11 | 31 | 61.3 | 0.76 | -0.173 | 10.10 | -2.19 |
| SOL/USDT | 4h | Variant B (Pruned Production) | 42 | -0.229 | -1.72 | 17 | 70.6 | 1.72 | +0.602 | 7.25 | 4.09 |
| SOL/USDT | 4h | Variant C (Price Cap 1.5) | 40 | -0.196 | -1.76 | 17 | 58.8 | 0.89 | -0.113 | 9.74 | -0.59 |
| SOL/USDT | 4h | Variant D (Single Guard) | 42 | -0.063 | -0.74 | 19 | 63.2 | 0.99 | +0.008 | 9.76 | -0.05 |
| HYPE/USDT | 1h | Variant B (Pruned Production) | 87 | -0.045 | -1.01 | 49 | 61.2 | 0.66 | -0.310 | 19.44 | -2.31 |
| HYPE/USDT | 1h | Variant C (Price Cap 1.5) | 69 | -0.087 | -1.10 | 38 | 65.8 | 0.80 | -0.162 | 13.69 | -1.61 |
| HYPE/USDT | 1h | Variant D (Single Guard) | 72 | -0.096 | -1.10 | 40 | 62.5 | 0.71 | -0.244 | 16.22 | -1.98 |
| HYPE/USDT | 4h | Variant B (Pruned Production) | 40 | -0.141 | -0.73 | 16 | 68.8 | 1.09 | +0.166 | 6.30 | 0.61 |
| HYPE/USDT | 4h | Variant C (Price Cap 1.5) | 36 | -0.388 | -1.35 | 13 | 61.5 | 0.91 | -0.145 | 6.30 | -0.59 |
| HYPE/USDT | 4h | Variant D (Single Guard) | 36 | -0.388 | -1.35 | 13 | 61.5 | 0.91 | -0.145 | 6.30 | -0.59 |
| CC/USDT | 1h | Variant B (Pruned Production) | 55 | -0.504 | -1.84 | 62 | 75.8 | 1.12 | +0.108 | 9.25 | 2.16 |
| CC/USDT | 1h | Variant C (Price Cap 1.5) | 47 | -0.529 | -1.70 | 54 | 77.8 | 1.24 | +0.192 | 6.92 | 5.02 |
| CC/USDT | 1h | Variant D (Single Guard) | 53 | -0.561 | -1.76 | 56 | 76.8 | 1.17 | +0.147 | 6.92 | 3.76 |
| CC/USDT | 4h | Variant B (Pruned Production) | 27 | -0.341 | -0.97 | 22 | 72.7 | 1.43 | +0.655 | 3.42 | 7.05 |
| CC/USDT | 4h | Variant C (Price Cap 1.5) | 25 | -0.295 | -0.84 | 20 | 80.0 | 2.01 | +1.124 | 2.82 | 14.52 |
| CC/USDT | 4h | Variant D (Single Guard) | 29 | -0.116 | -0.50 | 20 | 80.0 | 2.01 | +1.124 | 2.82 | 14.52 |

### Automated Walk-Forward OOS Variant Ranking
- **Variant B (Pruned Production)**: Mean IS Exp=-0.246% | Mean OOS Exp=+0.046% | Mean OOS MAR=0.66
- **Variant C (Price Cap 1.5)**: Mean IS Exp=-0.249% | Mean OOS Exp=-0.020% | Mean OOS MAR=0.66
- **Variant D (Single Guard)**: Mean IS Exp=-0.218% | Mean OOS Exp=-0.073% | Mean OOS MAR=0.30

### Pre-Pruning Variant A Reference Baseline (Frozen Empirical Observation before Deletion)
> **Why Variant A is no longer executed live**: `use_legacy_hype_rules` and all 5 `is_hype` bespoke rules were formally deleted from `api/core/indicators.py` following Window A Walk-Forward OOS falsification (`2026-11-25`, 194–205d, 10 targets, `5 bps` + funding + `conservative` trailing).
- **Variant A (Legacy Rules — Frozen Pre-Pruning Reference)**: Mean IS Exp=`-0.249%` | Mean OOS Exp=`+0.001%` | Mean OOS MAR=`1.06`
  - `HYPE/USDT 4h` (Variant A): IS `19` trades (`-0.389%`, MAR `-1.42`) -> OOS `8` trades, WR `62.5%`, PF `0.59`, Exp **`-0.872%`**, DD `5.44%`, MAR `-2.08`.
  - `HYPE/USDT 1h` (Variant A): IS `38` trades (`-0.223%`, MAR `-1.46`) -> OOS `32` trades, WR `68.8%`, PF `0.92`, Exp `-0.048%`, DD `9.83%`, MAR `-0.71`.
- **Contrasted with Variant B (No Coin Hacks -> Pruned Production)**: Mean IS Exp=`-0.246%` | Mean OOS Exp=**`+0.046%`** | Mean OOS MAR=`0.66`; `HYPE/USDT 4h` OOS rose from `-0.872% (PF 0.59)` to **`+0.166%` (PF `1.09`, WR `68.8%`, `16` trades)**.

### Phase 2 OOS Module Keep/Prune Verdict Table (模組去留判決表)
| Module / Parameter | Decision (決策) | Window A / Window B Empirical OOS Evidence |
| :--- | :---: | :--- |
| `5x is_hype` bespoke rules & `use_legacy_hype_rules` | **PRUNE / DELETED (刪除)** | Window A 60/40 OOS: `Variant B` achieved best Mean OOS Exp **`+0.046%`** vs `Variant A` `+0.001%`; `HYPE 4h` OOS jumped `-0.872% (PF 0.59)` -> **`+0.166%` (PF `1.09`, WR `68.8%`)**. Eliminated coin-specific curve fitting; unified `is_alt` `-10/+10` RSI & ATR EMA50 bounds across all assets. |
| `Price Group Cap 3.0` (`price_group_cap=None`) | **KEEP (保留)** | Lowering Price Cap to `1.5` (`Variant C`) degraded Mean OOS Exp `+0.046%` -> **`-0.020%`** (e.g., `ETH 4h` OOS `+0.347%` -> `-0.012%`, `SOL 4h` OOS `+0.602%` -> `-0.113%`, `HYPE 4h` OOS `+0.166%` -> `-0.145%`). |
| `Multi-Layer EMA Guards` (`single_trend_guard=False`) | **KEEP (保留)** | Collapsing to Single Trend Guard (`Variant D`) further degraded Mean OOS Exp to **`-0.073%`** and halved Mean OOS MAR `0.66` -> **`0.30`** (`ETH 1h` OOS `-0.131%` -> `-0.359%`, `ETH 4h` OOS `+0.347%` -> `-0.260%`). |
| `SingleFullTP_Narrow` (`enable_partial_tp=False`) | **KEEP (保留)** | Window A Section 2 Exit Stress (`5` & `15 bps` + funding): `SingleFullTP_Narrow` outperformed all `PartialTP` variants (`+1.0xATR`, `+1.5xATR`, `+WidePct`) across 4h swing targets (`ETH 4h 5bps`: `+0.057% PF 1.03` vs `-0.242%~-0.297%`; `SOL 4h 5bps`: `+0.064% PF 1.04` vs `-0.371%~-0.390%`; `CC 4h 5bps`: `+0.441% PF 1.29` vs `-0.214%~+0.031%`). |
| `top_ls_position_ratio` as primary `lsur_source` | **DO NOT PROMOTE (不升格，維持診斷)** | Clean Window B (`34.46d 1h / 32.67d 4h`, 10/10 targets): `Group D2 (top_ls, N=194)` Pooled Ret+12 = `+0.656%` failed Bootstrap significance vs `Group P` (`p=0.6790`) and vs `Group D1 lsur` (`p=0.5940`, Pooled Ret+12 = `+0.809%`), 0/10 targets hit `p < 0.10`; Stage 1C `lsur` outperformed `top_ls` (Mean Exp `+0.877% / Sharpe 3.25` vs `+0.715% / 2.68`). |

## 4. Fixed-Horizon Forward Return (+4/+12/+24) & Top Trader Bootstrap Test (Window A)
> Causal config: `mtf_close_aligned=True`, `use_btc_history=True`, `setup_symmetry=True`, `use_coin_oi_all=True`, `is_hype_hacks_deleted=True`.
| Symbol | TF | Group | N | Ret+4 (%) | Ret+12 (%) | Ret+24 (%) | E-Ratio+12 | p(vs P @12) | p(vs D1 @12) |
| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| BTC/USDT | 1h | Group P | 115 | -0.024 | -0.077 | +0.102 | 0.77 | 1.0000 | 1.0000 |
| BTC/USDT | 1h | Group D1 | 127 | -0.055 | -0.112 | +0.031 | 0.65 | 0.8470 | 1.0000 |
| BTC/USDT | 1h | Group D2 | 0 | +0.000 | +0.000 | +0.000 | 0.00 | 1.0000 | 1.0000 |
| BTC/USDT | 4h | Group P | 56 | -0.236 | -0.047 | +0.423 | 0.74 | 1.0000 | 1.0000 |
| BTC/USDT | 4h | Group D1 | 62 | -0.450 | +0.084 | -0.542 | 0.68 | 0.8530 | 1.0000 |
| BTC/USDT | 4h | Group D2 | 0 | +0.000 | +0.000 | +0.000 | 0.00 | 1.0000 | 1.0000 |
| ETH/USDT | 1h | Group P | 134 | -0.075 | -0.077 | +0.060 | 0.87 | 1.0000 | 1.0000 |
| ETH/USDT | 1h | Group D1 | 114 | -0.104 | -0.225 | -0.147 | 0.95 | 0.5800 | 1.0000 |
| ETH/USDT | 1h | Group D2 | 0 | +0.000 | +0.000 | +0.000 | 0.00 | 1.0000 | 1.0000 |
| ETH/USDT | 4h | Group P | 44 | +0.584 | +0.985 | +0.987 | 1.47 | 1.0000 | 1.0000 |
| ETH/USDT | 4h | Group D1 | 50 | +0.093 | +0.688 | +0.607 | 0.95 | 0.7450 | 1.0000 |
| ETH/USDT | 4h | Group D2 | 0 | +0.000 | +0.000 | +0.000 | 0.00 | 1.0000 | 1.0000 |
| SOL/USDT | 1h | Group P | 119 | -0.110 | -0.139 | -0.224 | 0.99 | 1.0000 | 1.0000 |
| SOL/USDT | 1h | Group D1 | 128 | -0.146 | -0.411 | -0.465 | 0.80 | 0.2880 | 1.0000 |
| SOL/USDT | 1h | Group D2 | 0 | +0.000 | +0.000 | +0.000 | 0.00 | 1.0000 | 1.0000 |
| SOL/USDT | 4h | Group P | 36 | -0.118 | +0.439 | +1.622 | 1.19 | 1.0000 | 1.0000 |
| SOL/USDT | 4h | Group D1 | 59 | -0.038 | +0.212 | +0.372 | 1.00 | 0.8100 | 1.0000 |
| SOL/USDT | 4h | Group D2 | 0 | +0.000 | +0.000 | +0.000 | 0.00 | 1.0000 | 1.0000 |
| HYPE/USDT | 1h | Group P | 137 | +0.242 | +0.157 | +0.626 | 0.88 | 1.0000 | 1.0000 |
| HYPE/USDT | 1h | Group D1 | 144 | -0.055 | -0.117 | -0.248 | 0.95 | 0.4150 | 1.0000 |
| HYPE/USDT | 1h | Group D2 | 0 | +0.000 | +0.000 | +0.000 | 0.00 | 1.0000 | 1.0000 |
| HYPE/USDT | 4h | Group P | 48 | -0.095 | +0.067 | +0.003 | 1.04 | 1.0000 | 1.0000 |
| HYPE/USDT | 4h | Group D1 | 59 | -0.239 | +0.565 | +1.058 | 1.06 | 0.6990 | 1.0000 |
| HYPE/USDT | 4h | Group D2 | 0 | +0.000 | +0.000 | +0.000 | 0.00 | 1.0000 | 1.0000 |
| CC/USDT | 1h | Group P | 114 | -0.266 | -0.319 | -0.252 | 0.81 | 1.0000 | 1.0000 |
| CC/USDT | 1h | Group D1 | 134 | -0.039 | -0.075 | -0.231 | 1.12 | 0.5410 | 1.0000 |
| CC/USDT | 1h | Group D2 | 0 | +0.000 | +0.000 | +0.000 | 0.00 | 1.0000 | 1.0000 |
| CC/USDT | 4h | Group P | 32 | +0.113 | -0.743 | -0.396 | 0.91 | 1.0000 | 1.0000 |
| CC/USDT | 4h | Group D1 | 56 | +0.136 | +0.438 | +0.975 | 0.81 | 0.4240 | 1.0000 |
| CC/USDT | 4h | Group D2 | 0 | +0.000 | +0.000 | +0.000 | 0.00 | 1.0000 | 1.0000 |

### Automated Experiment 3 Statistical Flags (alpha = 0.10)
- ⚠️ **BTC/USDT 1h Group D1**: Not statistically significant vs Group P (p=0.8470 > 0.10, Ret+12=-0.112%).
- ⚠️ **BTC/USDT 1h Group D2**: 0 signals / insufficient data.
- ⚠️ **BTC/USDT 4h Group D1**: Not statistically significant vs Group P (p=0.8530 > 0.10, Ret+12=+0.084%).
- ⚠️ **BTC/USDT 4h Group D2**: 0 signals / insufficient data.
- ⚠️ **ETH/USDT 1h Group D1**: Not statistically significant vs Group P (p=0.5800 > 0.10, Ret+12=-0.225%).
- ⚠️ **ETH/USDT 1h Group D2**: 0 signals / insufficient data.
- ⚠️ **ETH/USDT 4h Group D1**: Not statistically significant vs Group P (p=0.7450 > 0.10, Ret+12=+0.688%).
- ⚠️ **ETH/USDT 4h Group D2**: 0 signals / insufficient data.
- ⚠️ **SOL/USDT 1h Group D1**: Not statistically significant vs Group P (p=0.2880 > 0.10, Ret+12=-0.411%).
- ⚠️ **SOL/USDT 1h Group D2**: 0 signals / insufficient data.
- ⚠️ **SOL/USDT 4h Group D1**: Not statistically significant vs Group P (p=0.8100 > 0.10, Ret+12=+0.212%).
- ⚠️ **SOL/USDT 4h Group D2**: 0 signals / insufficient data.
- ⚠️ **HYPE/USDT 1h Group D1**: Not statistically significant vs Group P (p=0.4150 > 0.10, Ret+12=-0.117%).
- ⚠️ **HYPE/USDT 1h Group D2**: 0 signals / insufficient data.
- ⚠️ **HYPE/USDT 4h Group D1**: Not statistically significant vs Group P (p=0.6990 > 0.10, Ret+12=+0.565%).
- ⚠️ **HYPE/USDT 4h Group D2**: 0 signals / insufficient data.
- ⚠️ **CC/USDT 1h Group D1**: Not statistically significant vs Group P (p=0.5410 > 0.10, Ret+12=-0.075%).
- ⚠️ **CC/USDT 1h Group D2**: 0 signals / insufficient data.
- ⚠️ **CC/USDT 4h Group D1**: Not statistically significant vs Group P (p=0.4240 > 0.10, Ret+12=+0.438%).
- ⚠️ **CC/USDT 4h Group D2**: 0 signals / insufficient data.

## 5. Experiment 3B: Window B Clean `top_ls_position_ratio` Head-to-Head (`Group P` vs `Group D1 lsur` vs `Group D2 top_ls`)
> Shared Window B `eval_price` slice (`require_top_ls=True`). Causal config: `mtf_close_aligned=True`, `use_btc_history=True`, `setup_symmetry=True`, `use_coin_oi_all=True`, `is_hype_hacks_deleted=True`.

### 5.1 Clean Window B Inventory
| Symbol | TF | Valid | Clean Start (UTC) | Eval Start (UTC) | Clean End (UTC) | Clean Days | Eval Bars | top_ls_count | top_ls_eval_bars | Taker | Funding |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| BTC/USDT | 1h | ✅ | 2026-10-21 18:00 | 2026-10-22 08:00 | 2026-11-25 19:00 | 34.46 | 828 | 842 | 828 | True | 106 |
| BTC/USDT | 4h | ✅ | 2026-10-21 16:00 | 2026-10-24 00:00 | 2026-11-25 16:00 | 32.67 | 197 | 211 | 197 | True | 107 |
| ETH/USDT | 1h | ✅ | 2026-10-21 18:00 | 2026-10-22 08:00 | 2026-11-25 19:00 | 34.46 | 828 | 842 | 828 | True | 106 |
| ETH/USDT | 4h | ✅ | 2026-10-21 16:00 | 2026-10-24 00:00 | 2026-11-25 16:00 | 32.67 | 197 | 211 | 197 | True | 107 |
| SOL/USDT | 1h | ✅ | 2026-10-21 18:00 | 2026-10-22 08:00 | 2026-11-25 19:00 | 34.46 | 828 | 842 | 828 | True | 106 |
| SOL/USDT | 4h | ✅ | 2026-10-21 16:00 | 2026-10-24 00:00 | 2026-11-25 16:00 | 32.67 | 197 | 211 | 197 | True | 107 |
| HYPE/USDT | 1h | ✅ | 2026-10-21 18:00 | 2026-10-22 08:00 | 2026-11-25 19:00 | 34.46 | 828 | 842 | 828 | True | 106 |
| HYPE/USDT | 4h | ✅ | 2026-10-21 16:00 | 2026-10-24 00:00 | 2026-11-25 16:00 | 32.67 | 197 | 211 | 197 | True | 107 |
| CC/USDT | 1h | ✅ | 2026-10-21 18:00 | 2026-10-22 08:00 | 2026-11-25 19:00 | 34.46 | 828 | 842 | 828 | True | 213 |
| CC/USDT | 4h | ✅ | 2026-10-21 16:00 | 2026-10-24 00:00 | 2026-11-25 16:00 | 32.67 | 197 | 211 | 197 | True | 214 |

### 5.2 Window B Head-to-Head Forward Return (+4 / +12 / +24), E-Ratio & Return Bootstrap p-values (1,000x)
| Symbol | TF | Group | N | Ret+4 (%) | Ret+12 (%) | Ret+24 (%) | E-Ratio+4 | E-Ratio+12 | E-Ratio+24 | pRet(vs P @4) | pRet(vs P @12) | pRet(vs P @24) | pRet(vs D1 @4) | pRet(vs D1 @12) | pRet(vs D1 @24) |
| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| BTC/USDT | 1h | Group P | 18 | -0.002 | +0.506 | +0.902 | 1.19 | 1.76 | 2.52 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| BTC/USDT | 1h | Group D1 | 36 | +0.181 | +0.231 | +0.327 | 1.34 | 0.89 | 1.36 | 0.5680 | 0.6960 | 0.4270 | 1.0000 | 1.0000 | 1.0000 |
| BTC/USDT | 1h | Group D2 | 36 | +0.222 | +0.332 | +0.432 | 1.54 | 1.07 | 1.68 | 0.5030 | 0.8020 | 0.5260 | 0.8750 | 0.8460 | 0.8730 |
| BTC/USDT | 4h | Group P | 9 | +0.876 | +2.598 | +4.041 | 2.36 | 5.17 | 6.70 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| BTC/USDT | 4h | Group D1 | 8 | +1.209 | +1.837 | +3.727 | 2.13 | 4.39 | 5.89 | 0.8370 | 0.7350 | 0.8970 | 1.0000 | 1.0000 | 1.0000 |
| BTC/USDT | 4h | Group D2 | 9 | +1.737 | +2.246 | +4.144 | 2.58 | 6.06 | 6.37 | 0.5790 | 0.8420 | 0.9620 | 0.6810 | 0.8330 | 0.8690 |
| ETH/USDT | 1h | Group P | 21 | +0.224 | -0.052 | -0.340 | 2.30 | 1.64 | 1.43 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| ETH/USDT | 1h | Group D1 | 29 | +0.223 | -0.109 | +0.119 | 2.06 | 1.13 | 1.13 | 0.9940 | 0.9290 | 0.4880 | 1.0000 | 1.0000 | 1.0000 |
| ETH/USDT | 1h | Group D2 | 32 | +0.207 | -0.169 | -0.018 | 2.04 | 1.13 | 1.16 | 0.9550 | 0.8780 | 0.6510 | 0.9540 | 0.9120 | 0.7860 |
| ETH/USDT | 4h | Group P | 10 | -0.212 | +2.478 | +3.813 | 1.32 | 4.29 | 3.36 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| ETH/USDT | 4h | Group D1 | 12 | +0.143 | +2.648 | +3.852 | 0.89 | 2.43 | 2.38 | 0.7370 | 0.9090 | 0.9850 | 1.0000 | 1.0000 | 1.0000 |
| ETH/USDT | 4h | Group D2 | 12 | +0.143 | +2.648 | +3.852 | 0.89 | 2.43 | 2.38 | 0.7370 | 0.9090 | 0.9850 | 1.0000 | 1.0000 | 1.0000 |
| SOL/USDT | 1h | Group P | 25 | -0.327 | -0.267 | +0.897 | 1.22 | 1.16 | 1.33 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| SOL/USDT | 1h | Group D1 | 29 | -0.131 | +0.466 | +1.044 | 1.09 | 1.89 | 2.80 | 0.6900 | 0.2930 | 0.8320 | 1.0000 | 1.0000 | 1.0000 |
| SOL/USDT | 1h | Group D2 | 30 | -0.071 | +0.366 | +1.194 | 1.26 | 1.38 | 2.24 | 0.5980 | 0.3610 | 0.7230 | 0.8780 | 0.8580 | 0.8280 |
| SOL/USDT | 4h | Group P | 10 | +1.291 | +3.263 | +4.929 | 2.49 | 2.94 | 5.64 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| SOL/USDT | 4h | Group D1 | 11 | +0.809 | +2.398 | +4.536 | 2.26 | 2.31 | 3.15 | 0.6660 | 0.6080 | 0.8310 | 1.0000 | 1.0000 | 1.0000 |
| SOL/USDT | 4h | Group D2 | 11 | +0.809 | +2.398 | +4.536 | 2.26 | 2.31 | 3.15 | 0.6660 | 0.6080 | 0.8310 | 1.0000 | 1.0000 | 1.0000 |
| HYPE/USDT | 1h | Group P | 25 | +0.007 | +0.379 | +1.186 | 0.61 | 0.97 | 0.80 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| HYPE/USDT | 1h | Group D1 | 34 | -0.000 | -0.130 | +1.043 | 1.07 | 1.25 | 1.11 | 0.9890 | 0.5180 | 0.8990 | 1.0000 | 1.0000 | 1.0000 |
| HYPE/USDT | 1h | Group D2 | 34 | +0.024 | -0.113 | +0.870 | 0.96 | 1.22 | 0.98 | 0.9700 | 0.5230 | 0.8040 | 0.9500 | 0.9770 | 0.8520 |
| HYPE/USDT | 4h | Group P | 8 | -0.638 | -1.123 | +1.008 | 1.67 | 1.43 | 1.21 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| HYPE/USDT | 4h | Group D1 | 8 | -2.360 | -0.269 | +0.191 | 0.71 | 0.95 | 1.02 | 0.3280 | 0.7560 | 0.8460 | 1.0000 | 1.0000 | 1.0000 |
| HYPE/USDT | 4h | Group D2 | 8 | -1.976 | +0.044 | -0.291 | 0.71 | 0.95 | 1.02 | 0.4720 | 0.6750 | 0.7470 | 0.8430 | 0.8870 | 0.9250 |
| CC/USDT | 1h | Group P | 21 | +0.026 | +0.560 | +0.536 | 1.35 | 1.35 | 1.24 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| CC/USDT | 1h | Group D1 | 31 | +0.555 | +1.716 | +2.333 | 1.55 | 2.04 | 2.32 | 0.2080 | 0.2480 | 0.0520 | 1.0000 | 1.0000 | 1.0000 |
| CC/USDT | 1h | Group D2 | 31 | +0.370 | +1.141 | +1.890 | 1.34 | 1.88 | 1.67 | 0.4470 | 0.5540 | 0.1330 | 0.6570 | 0.4900 | 0.6060 |
| CC/USDT | 4h | Group P | 3 | +1.783 | +0.997 | +3.465 | 3.16 | 3.67 | 4.04 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| CC/USDT | 4h | Group D1 | 5 | +2.101 | +3.242 | +4.575 | 3.16 | 2.64 | 1.48 | 0.9270 | 0.4500 | 0.8150 | 1.0000 | 1.0000 | 1.0000 |
| CC/USDT | 4h | Group D2 | 5 | -1.333 | +1.412 | +2.174 | 1.52 | 1.72 | 0.93 | 0.4850 | 0.8790 | 0.6750 | 0.3220 | 0.2510 | 0.2850 |

### 5.3 Window B E-Ratio 1,000x Bootstrap p-values (+4 / +12 / +24)
| Symbol | TF | Group | N | E-Ratio+4 | E-Ratio+12 | E-Ratio+24 | pER(vs P @4) | pER(vs P @12) | pER(vs P @24) | pER(vs D1 @4) | pER(vs D1 @12) | pER(vs D1 @24) |
| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| BTC/USDT | 1h | Group P | 18 | 1.19 | 1.76 | 2.52 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| BTC/USDT | 1h | Group D1 | 36 | 1.34 | 0.89 | 1.36 | 0.8260 | 0.3990 | 0.3000 | 1.0000 | 1.0000 | 1.0000 |
| BTC/USDT | 1h | Group D2 | 36 | 1.54 | 1.07 | 1.68 | 0.6420 | 0.5340 | 0.4830 | 0.7130 | 0.7890 | 0.7540 |
| BTC/USDT | 4h | Group P | 9 | 2.36 | 5.17 | 6.70 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| BTC/USDT | 4h | Group D1 | 8 | 2.13 | 4.39 | 5.89 | 0.8510 | 0.7800 | 0.7830 | 1.0000 | 1.0000 | 1.0000 |
| BTC/USDT | 4h | Group D2 | 9 | 2.58 | 6.06 | 6.37 | 0.8190 | 0.7330 | 0.9000 | 0.8200 | 0.6060 | 0.8580 |
| ETH/USDT | 1h | Group P | 21 | 2.30 | 1.64 | 1.43 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| ETH/USDT | 1h | Group D1 | 29 | 2.06 | 1.13 | 1.13 | 0.8240 | 0.5560 | 0.6440 | 1.0000 | 1.0000 | 1.0000 |
| ETH/USDT | 1h | Group D2 | 32 | 2.04 | 1.13 | 1.16 | 0.8450 | 0.5250 | 0.6370 | 0.9890 | 0.9850 | 0.9640 |
| ETH/USDT | 4h | Group P | 10 | 1.32 | 4.29 | 3.36 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| ETH/USDT | 4h | Group D1 | 12 | 0.89 | 2.43 | 2.38 | 0.5400 | 0.2480 | 0.4730 | 1.0000 | 1.0000 | 1.0000 |
| ETH/USDT | 4h | Group D2 | 12 | 0.89 | 2.43 | 2.38 | 0.5400 | 0.2480 | 0.4730 | 1.0000 | 1.0000 | 1.0000 |
| SOL/USDT | 1h | Group P | 25 | 1.22 | 1.16 | 1.33 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| SOL/USDT | 1h | Group D1 | 29 | 1.09 | 1.89 | 2.80 | 0.8240 | 0.4410 | 0.2590 | 1.0000 | 1.0000 | 1.0000 |
| SOL/USDT | 1h | Group D2 | 30 | 1.26 | 1.38 | 2.24 | 0.9330 | 0.7700 | 0.4620 | 0.7100 | 0.6210 | 0.7040 |
| SOL/USDT | 4h | Group P | 10 | 2.49 | 2.94 | 5.64 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| SOL/USDT | 4h | Group D1 | 11 | 2.26 | 2.31 | 3.15 | 0.8520 | 0.6700 | 0.4200 | 1.0000 | 1.0000 | 1.0000 |
| SOL/USDT | 4h | Group D2 | 11 | 2.26 | 2.31 | 3.15 | 0.8520 | 0.6700 | 0.4200 | 1.0000 | 1.0000 | 1.0000 |
| HYPE/USDT | 1h | Group P | 25 | 0.61 | 0.97 | 0.80 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| HYPE/USDT | 1h | Group D1 | 34 | 1.07 | 1.25 | 1.11 | 0.5330 | 0.4670 | 0.4960 | 1.0000 | 1.0000 | 1.0000 |
| HYPE/USDT | 1h | Group D2 | 34 | 0.96 | 1.22 | 0.98 | 0.5950 | 0.5620 | 0.6480 | 0.8560 | 0.9330 | 0.8100 |
| HYPE/USDT | 4h | Group P | 8 | 1.67 | 1.43 | 1.21 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| HYPE/USDT | 4h | Group D1 | 8 | 0.71 | 0.95 | 1.02 | 0.2920 | 0.6150 | 0.8760 | 1.0000 | 1.0000 | 1.0000 |
| HYPE/USDT | 4h | Group D2 | 8 | 0.71 | 0.95 | 1.02 | 0.3050 | 0.6200 | 0.8720 | 1.0000 | 1.0000 | 1.0000 |
| CC/USDT | 1h | Group P | 21 | 1.35 | 1.35 | 1.24 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| CC/USDT | 1h | Group D1 | 31 | 1.55 | 2.04 | 2.32 | 0.8110 | 0.4880 | 0.3690 | 1.0000 | 1.0000 | 1.0000 |
| CC/USDT | 1h | Group D2 | 31 | 1.34 | 1.88 | 1.67 | 0.9560 | 0.5630 | 0.6000 | 0.7650 | 0.8490 | 0.5250 |
| CC/USDT | 4h | Group P | 3 | 3.16 | 3.67 | 4.04 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| CC/USDT | 4h | Group D1 | 5 | 3.16 | 2.64 | 1.48 | 1.0000 | 0.6510 | 0.6170 | 1.0000 | 1.0000 | 1.0000 |
| CC/USDT | 4h | Group D2 | 5 | 1.52 | 1.72 | 0.93 | 0.5470 | 0.4010 | 0.2440 | 0.5840 | 0.6450 | 0.3970 |

### 5.4 Window B Aggregate Summary (`All` / `1h` / `4h`): `Group P` vs `Group D1` vs `Group D2`
| Scope | Group | Targets (N>0/Total) | Total N | Target-Mean Ret+4 (%) | Target-Mean Ret+12 (%) | Target-Mean Ret+24 (%) | Target-Mean ER+4 | Target-Mean ER+12 | Target-Mean ER+24 | Pooled Ret+4 (%) | Pooled Ret+12 (%) | Pooled Ret+24 (%) | Pooled ER+4 | Pooled ER+12 | Pooled ER+24 | Pooled pRet(vs P @12) | Pooled pRet(vs D1 @12) | Pooled pER(vs P @12) | Pooled pER(vs D1 @12) |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| All | Group P | 10/10 | 150 | +0.303 | +0.934 | +2.044 | 1.77 | 2.44 | 2.83 | +0.108 | +0.649 | +1.431 | 1.31 | 1.49 | 1.56 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| All | Group D1 | 10/10 | 203 | +0.273 | +1.203 | +2.175 | 1.63 | 1.99 | 2.26 | +0.189 | +0.760 | +1.496 | 1.31 | 1.49 | 1.83 | 0.7690 | 1.0000 | 0.9980 | 1.0000 |
| All | Group D2 | 10/10 | 208 | +0.013 | +1.030 | +1.878 | 1.51 | 2.01 | 2.16 | +0.137 | +0.648 | +1.351 | 1.32 | 1.44 | 1.76 | 0.9980 | 0.7250 | 0.8310 | 0.8250 |
| 1h | Group P | 5/5 | 110 | -0.014 | +0.225 | +0.636 | 1.33 | 1.38 | 1.46 | -0.025 | +0.205 | +0.659 | 1.27 | 1.42 | 1.32 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| 1h | Group D1 | 5/5 | 159 | +0.166 | +0.435 | +0.973 | 1.42 | 1.44 | 1.74 | +0.166 | +0.424 | +0.964 | 1.63 | 1.29 | 1.66 | 0.5340 | 1.0000 | 0.7280 | 1.0000 |
| 1h | Group D2 | 5/5 | 163 | +0.150 | +0.311 | +0.874 | 1.43 | 1.34 | 1.55 | +0.152 | +0.301 | +0.853 | 1.55 | 1.20 | 1.50 | 0.7640 | 0.6770 | 0.5530 | 0.8060 |
| 4h | Group P | 5/5 | 40 | +0.620 | +1.643 | +3.451 | 2.20 | 3.50 | 4.19 | +0.473 | +1.870 | +3.556 | 1.83 | 3.42 | 3.64 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| 4h | Group D1 | 5/5 | 44 | +0.380 | +1.971 | +3.376 | 1.83 | 2.54 | 2.78 | +0.271 | +1.975 | +3.417 | 1.42 | 2.35 | 2.51 | 0.8970 | 1.0000 | 0.3660 | 1.0000 |
| 4h | Group D2 | 5/5 | 45 | -0.124 | +1.750 | +2.883 | 1.59 | 2.69 | 2.77 | +0.084 | +1.906 | +3.155 | 1.31 | 2.28 | 2.47 | 0.9630 | 0.9400 | 0.3740 | 0.9400 |

### 5.5 Automated Experiment 3B Statistical Flags (alpha = 0.10)
- ⚠️ **BTC/USDT 1h Group D1**: Not statistically significant vs Group P (pRet@12=0.6960 > 0.10, Ret+12=+0.231%, pER@12=0.3990).
- ⚠️ **BTC/USDT 1h Group D2**: Not statistically significant vs Group P (pRet@12=0.8020 > 0.10, Ret+12=+0.332%, pER@12=0.5340).
- ⚠️ **BTC/USDT 4h Group D1**: Not statistically significant vs Group P (pRet@12=0.7350 > 0.10, Ret+12=+1.837%, pER@12=0.7800).
- ⚠️ **BTC/USDT 4h Group D2**: Not statistically significant vs Group P (pRet@12=0.8420 > 0.10, Ret+12=+2.246%, pER@12=0.7330).
- ⚠️ **ETH/USDT 1h Group D1**: Not statistically significant vs Group P (pRet@12=0.9290 > 0.10, Ret+12=-0.109%, pER@12=0.5560).
- ⚠️ **ETH/USDT 1h Group D2**: Not statistically significant vs Group P (pRet@12=0.8780 > 0.10, Ret+12=-0.169%, pER@12=0.5250).
- ⚠️ **ETH/USDT 4h Group D1**: Not statistically significant vs Group P (pRet@12=0.9090 > 0.10, Ret+12=+2.648%, pER@12=0.2480).
- ⚠️ **ETH/USDT 4h Group D2**: Not statistically significant vs Group P (pRet@12=0.9090 > 0.10, Ret+12=+2.648%, pER@12=0.2480).
- ⚠️ **SOL/USDT 1h Group D1**: Not statistically significant vs Group P (pRet@12=0.2930 > 0.10, Ret+12=+0.466%, pER@12=0.4410).
- ⚠️ **SOL/USDT 1h Group D2**: Not statistically significant vs Group P (pRet@12=0.3610 > 0.10, Ret+12=+0.366%, pER@12=0.7700).
- ⚠️ **SOL/USDT 4h Group D1**: Not statistically significant vs Group P (pRet@12=0.6080 > 0.10, Ret+12=+2.398%, pER@12=0.6700).
- ⚠️ **SOL/USDT 4h Group D2**: Not statistically significant vs Group P (pRet@12=0.6080 > 0.10, Ret+12=+2.398%, pER@12=0.6700).
- ⚠️ **HYPE/USDT 1h Group D1**: Not statistically significant vs Group P (pRet@12=0.5180 > 0.10, Ret+12=-0.130%, pER@12=0.4670).
- ⚠️ **HYPE/USDT 1h Group D2**: Not statistically significant vs Group P (pRet@12=0.5230 > 0.10, Ret+12=-0.113%, pER@12=0.5620).
- ⚠️ **HYPE/USDT 4h Group D1**: Not statistically significant vs Group P (pRet@12=0.7560 > 0.10, Ret+12=-0.269%, pER@12=0.6150).
- ⚠️ **HYPE/USDT 4h Group D2**: Not statistically significant vs Group P (pRet@12=0.6750 > 0.10, Ret+12=+0.044%, pER@12=0.6200).
- ⚠️ **CC/USDT 1h Group D1**: Not statistically significant vs Group P (pRet@12=0.2480 > 0.10, Ret+12=+1.716%, pER@12=0.4880).
- ⚠️ **CC/USDT 1h Group D2**: Not statistically significant vs Group P (pRet@12=0.5540 > 0.10, Ret+12=+1.141%, pER@12=0.5630).
- ⚠️ **CC/USDT 4h Group D1**: Not statistically significant vs Group P (pRet@12=0.4500 > 0.10, Ret+12=+3.242%, pER@12=0.6510).
- ⚠️ **CC/USDT 4h Group D2**: Not statistically significant vs Group P (pRet@12=0.8790 > 0.10, Ret+12=+1.412%, pER@12=0.4010).

## 6. Window B Stage 1C Backtest Check (`5 bps`, `include_funding=True`, `trailing_path_mode='conservative'`): `lsur` vs `top_ls`
### 6.1 Per-Target Stage 1C Results
| Symbol | TF | lsur_source | Days | Trades | WR (%) | PF | Exp/Trade (%) | MaxDD (%) | Sharpe | Total Ret (%) | Funding ($) |
| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| BTC/USDT | 1h | lsur | 34.46 | 31 | 61.3 | 0.88 | -0.061 | 7.22 | -0.98 | -1.96 | +13.09 |
| BTC/USDT | 1h | top_ls | 34.46 | 32 | 65.6 | 1.00 | +0.005 | 6.36 | 0.09 | -0.01 | +14.11 |
| BTC/USDT | 4h | lsur | 32.67 | 8 | 75.0 | 3.67 | +1.538 | 2.92 | 4.91 | +12.09 | +7.75 |
| BTC/USDT | 4h | top_ls | 32.67 | 8 | 75.0 | 3.67 | +1.538 | 2.92 | 4.90 | +12.09 | +7.75 |
| ETH/USDT | 1h | lsur | 34.46 | 27 | 74.1 | 1.78 | +0.407 | 7.64 | 4.50 | +10.66 | -0.71 |
| ETH/USDT | 1h | top_ls | 34.46 | 30 | 73.3 | 1.55 | +0.305 | 9.14 | 3.66 | +8.74 | -2.70 |
| ETH/USDT | 4h | lsur | 32.67 | 11 | 63.6 | 1.33 | +0.375 | 4.05 | 1.51 | +2.73 | +3.86 |
| ETH/USDT | 4h | top_ls | 32.67 | 11 | 63.6 | 1.33 | +0.375 | 4.05 | 1.51 | +2.73 | +3.86 |
| SOL/USDT | 1h | lsur | 34.46 | 28 | 64.3 | 0.89 | -0.073 | 7.48 | -0.76 | -2.28 | +4.14 |
| SOL/USDT | 1h | top_ls | 34.46 | 27 | 63.0 | 0.95 | -0.024 | 6.79 | -0.22 | -0.98 | +5.68 |
| SOL/USDT | 4h | lsur | 32.67 | 10 | 90.0 | 4.87 | +1.512 | 2.79 | 5.01 | +8.78 | +1.88 |
| SOL/USDT | 4h | top_ls | 32.67 | 11 | 81.8 | 2.43 | +1.037 | 2.79 | 3.56 | +6.51 | +1.88 |
| HYPE/USDT | 1h | lsur | 34.46 | 32 | 68.8 | 1.06 | +0.057 | 8.81 | 0.57 | +1.15 | +0.90 |
| HYPE/USDT | 1h | top_ls | 34.46 | 34 | 67.6 | 1.01 | +0.018 | 8.81 | 0.20 | +0.14 | +1.67 |
| HYPE/USDT | 4h | lsur | 32.67 | 11 | 72.7 | 1.41 | +0.589 | 3.36 | 1.95 | +2.26 | +2.03 |
| HYPE/USDT | 4h | top_ls | 32.67 | 11 | 72.7 | 1.44 | +0.634 | 3.36 | 2.08 | +2.44 | +2.12 |
| CC/USDT | 1h | lsur | 34.46 | 29 | 86.2 | 2.35 | +0.630 | 4.25 | 5.51 | +12.49 | -19.96 |
| CC/USDT | 1h | top_ls | 34.46 | 30 | 80.0 | 1.50 | +0.343 | 6.29 | 2.97 | +6.72 | -26.06 |
| CC/USDT | 4h | lsur | 32.67 | 6 | 83.3 | 2.77 | +1.831 | 2.08 | 4.10 | +3.63 | -5.78 |
| CC/USDT | 4h | top_ls | 32.67 | 6 | 66.7 | 0.83 | -0.311 | 4.18 | -0.64 | -0.67 | -5.25 |

### 6.2 Window B Stage 1C Aggregate Comparison (`All` / `1h` / `4h`)
| Scope | lsur_source | Targets | Total Trades | Mean WR (%) | Mean PF | Mean Exp (%) | Mean MaxDD (%) | Mean Sharpe |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| All | lsur | 10 | 193 | 73.9 | 2.10 | +0.680 | 5.06 | 2.63 |
| All | top_ls | 10 | 200 | 70.9 | 1.57 | +0.392 | 5.47 | 1.81 |
| 1h | lsur | 5 | 147 | 70.9 | 1.39 | +0.192 | 7.08 | 1.77 |
| 1h | top_ls | 5 | 153 | 69.9 | 1.20 | +0.129 | 7.48 | 1.34 |
| 4h | lsur | 5 | 46 | 76.9 | 2.81 | +1.169 | 3.04 | 3.50 |
| 4h | top_ls | 5 | 47 | 72.0 | 1.94 | +0.655 | 3.46 | 2.28 |
