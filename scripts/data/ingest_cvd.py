import sys
import os
import pandas as pd
from datetime import datetime, timezone

# Ensure the root structure is included so we can import smoothly 
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from api.db.database import SessionLocal
from api.db import crud

def ingest_cvd_csv(filepath: str, db_symbol: str):
    print(f"Reading {filepath} aiming to ingest to DB symbol: {db_symbol} ...")
    if not os.path.exists(filepath):
        print(f"File {filepath} not found. Skipping.")
        return

    df = pd.read_csv(filepath)
    if df.empty:
        print("Data is empty.")
        return

    records = []
    for _, row in df.iterrows():
        # Parsing the '2023-07-23' format into a proper timezone-aware Python datetime
        dt = datetime.strptime(str(row['date']), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        
        # Mapping to match PostgreSQL MarketDataPoint Schema
        record = {
            'timestamp': dt,
            'exchange': 'binance',
            'symbol': db_symbol,
            'timeframe': '1D',
            'taker_buy_vol': float(row['taker_buy_vol']),
            'taker_sell_vol': float(row['taker_sell_vol'])
        }
        records.append(record)

    # Utilizing Batch Upsert to prevent flooding memory while avoiding deadlocks
    batch_size = 500
    with SessionLocal() as db:
        for i in range(0, len(records), batch_size):
            batch = records[i:i+batch_size]
            try:
                # `upsert_market_data` internally runs PostgreSQL ON CONFLICT DO UPDATE
                crud.upsert_market_data(db, batch)
                print(f"[{db_symbol}] Upserted batch {i//batch_size + 1} ...")
            except Exception as e:
                print(f"[{db_symbol}] Error on batch upsert: {e}")
                db.rollback()
    print(f"[{db_symbol}] Successfully ingested total {len(records)} daily records into PostgreSQL.")

if __name__ == "__main__":
    # Symbol mapping from CSV format ("BTCUSDT") to Database format ("BTC/USDT")
    tokens = ["BTC", "ETH", "SOL", "HYPE", "CC"]
    
    for token in tokens:
        csv_path = f"scripts/data/{token}USDT_cvd_history.csv"
        db_symbol = f"{token}/USDT"
        ingest_cvd_csv(csv_path, db_symbol)

    print("\n--- Data Integration via Upsert Complete ---")
