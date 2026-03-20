import pandas as pd
import numpy as np
from api.core.fetcher import DataFetcher

def analyze_thresholds():
    fetcher = DataFetcher()
    symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'HYPE/USDT', 'CC/USDT']
    limit = 300
    timeframe = '4h'

    print(f"Fetching historical data for {len(symbols)} symbols. Limit: {limit}, Timeframe: {timeframe}...\n")

    for symbol in symbols:
        print(f"--- Analyzing {symbol} ---")
        try:
            # 1. Fetch Market Data (Funding Rate)
            # fetch_market_data will route through OKX/Binance wrappers
            market_data = fetcher.fetch_market_data(symbol, timeframe=timeframe, limit=limit)
            funding_data = market_data.get('funding', [])
            
            # 2. Fetch LSUR (Long/Short Account Ratio)
            lsur_data = fetcher.fetch_long_short_ratio(symbol, period=timeframe, limit=limit)

            # Analyze Funding
            if funding_data:
                df_fund = pd.DataFrame(funding_data)
                vals = df_fund['value'].astype(float)
                mean_f = vals.mean()
                std_f = vals.std()
                p05_f = np.percentile(vals.dropna(), 5)
                p95_f = np.percentile(vals.dropna(), 95)
                
                print(f"[Funding Rate]")
                print(f"  Count: {len(vals)}")
                print(f"  Mean:  {mean_f:.6f}%")
                print(f"  Std:   {std_f:.6f}%")
                print(f"  5th:   {p05_f:.6f}%")
                print(f"  95th:  {p95_f:.6f}%")
            else:
                print(f"[Funding Rate] No data found.")

            # Analyze LSUR
            if lsur_data:
                df_lsur = pd.DataFrame(lsur_data)
                vals_l = df_lsur['value'].astype(float)
                mean_l = vals_l.mean()
                std_l = vals_l.std()
                p05_l = np.percentile(vals_l.dropna(), 5)
                p95_l = np.percentile(vals_l.dropna(), 95)
                
                print(f"[Long/Short Ratio]")
                print(f"  Count: {len(vals_l)}")
                print(f"  Mean:  {mean_l:.4f}")
                print(f"  Std:   {std_l:.4f}")
                print(f"  5th:   {p05_l:.4f}")
                print(f"  95th:  {p95_l:.4f}\n")
            else:
                print(f"[Long/Short Ratio] No data found.\n")

        except Exception as e:
            print(f"Error fetching {symbol}: {e}\n")

if __name__ == "__main__":
    analyze_thresholds()