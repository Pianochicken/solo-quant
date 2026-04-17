import requests
import zipfile
import io
import pandas as pd
import os
import concurrent.futures

from datetime import datetime, timedelta

def process_daily_agg_trades(symbol: str, date_str: str, output_csv: str):
    """
    Download aggTrades from Binance Vision for a specific date, aggregate in memory, and append to the summary file.
    """
    url = f"https://data.binance.vision/data/futures/um/daily/aggTrades/{symbol}/{symbol}-aggTrades-{date_str}.zip"
    print(f"[{date_str}][{symbol}] Downloading: {url}")
    
    response = requests.get(url)
    if response.status_code != 200:
        print(f"[{date_str}][{symbol}] Data not found or download failed (Status: {response.status_code})")
        return False
        
    try:
        # Put downloaded bytes into memory buffer and read using the zipfile module
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            # Get the first file name within the ZIP (usually the CSV)
            csv_filename = z.namelist()[0]
            with z.open(csv_filename) as f:
                # aggTrades format usually has headers: 
                # [agg_trade_id, price, qty, first_id, last_id, timestamp, is_buyer_maker]
                # We only need 'quantity' and 'is_buyer_maker'
                df = pd.read_csv(
                    f, 
                    header=0, # First row is usually the header
                    usecols=['quantity', 'is_buyer_maker'], 
                    dtype={'quantity': float, 'is_buyer_maker': bool}
                )
                
                # is_buyer_maker = True means maker is buyer, implying taker sell
                taker_sell_vol = df[df['is_buyer_maker'] == True]['quantity'].sum()
                # is_buyer_maker = False means maker is seller, implying taker buy
                taker_buy_vol = df[df['is_buyer_maker'] == False]['quantity'].sum()
                
                # Rounding to 3 decimal places is usually precise enough for volume and keeps it clean
                taker_sell_vol = round(taker_sell_vol, 3)
                taker_buy_vol = round(taker_buy_vol, 3)
                
                file_exists = os.path.isfile(output_csv)
                with open(output_csv, 'a') as out_f:
                    if not file_exists:
                        out_f.write("date,symbol,taker_buy_vol,taker_sell_vol\n")
                    out_f.write(f"{date_str},{symbol},{taker_buy_vol:.3f},{taker_sell_vol:.3f}\n")
                
                print(f"[{date_str}][{symbol}] Aggregation complete! Taker Buy: {taker_buy_vol:.3f} | Taker Sell: {taker_sell_vol:.3f}")
                return True
                
    except Exception as e:
        print(f"[{date_str}][{symbol}] Processing error: {e}")
        return False

def process_symbol_history(symbol: str, dates: dict):
    """
    Process the entire date range for a single symbol.
    """
    output_file = f"scripts/data/{symbol}_cvd_history.csv"
    
    start_dt = datetime.strptime(dates["start"], "%Y-%m-%d")
    end_dt = datetime.strptime(dates["end"], "%Y-%m-%d")
    
    # Read existing dates to avoid redundant downloads
    existing_dates = set()
    if os.path.isfile(output_file):
        try:
            df_existing = pd.read_csv(output_file)
            existing_dates = set(df_existing['date'].astype(str).tolist())
        except Exception as e:
            print(f"[{symbol}] Failed to read existing records: {e}")
    
    print(f"\n🚀 Starting CVD historical data fetch for {symbol} ({dates['start']} ~ {dates['end']})")
    
    current_dt = start_dt
    while current_dt <= end_dt:
        d_str = current_dt.strftime("%Y-%m-%d")
        
        # Skip if date is already processed to support perfect resumption
        if d_str not in existing_dates:
            process_daily_agg_trades(symbol, d_str, output_file)
        
        current_dt += timedelta(days=1)
    
    # Re-sort the file chronologically by date to handle out-of-order backfills
    if os.path.isfile(output_file):
        try:
            df_sort = pd.read_csv(output_file)
            df_sort.sort_values('date', inplace=True)
            df_sort.to_csv(output_file, index=False)
            print(f"[{symbol}] Re-sorted {output_file} chronologically")
        except Exception as e:
            pass

if __name__ == "__main__":
    # Ensure directories exist
    os.makedirs("scripts/data", exist_ok=True)
    
    # Define symbols and their corresponding start/end dates
    # Start dates align with the listing dates of the perpetual contracts to ensure CVD alignment with price history
    tasks = {
        "BTCUSDT": {"start": "2023-07-23", "end": "2026-04-15"},
        "ETHUSDT": {"start": "2023-07-23", "end": "2026-04-14"},
        "SOLUSDT": {"start": "2023-07-23", "end": "2026-04-14"},
        "HYPEUSDT": {"start": "2025-05-30", "end": "2026-04-14"},
        "CCUSDT": {"start": "2025-10-31", "end": "2026-04-14"}
    }
    
    # Run all symbols concurrently
    print(f"Launching {len(tasks)} parallel workers...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as executor:
        futures = [executor.submit(process_symbol_history, sym, dates) for sym, dates in tasks.items()]
        concurrent.futures.wait(futures)
            
    print(f"\n--- All parallel backfill tasks completed ---")
