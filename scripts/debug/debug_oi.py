import ccxt
import time

def debug_oi():
    exchange = ccxt.okx()
    
    symbols_to_test = [
        "BTC/USDT:USDT",
        "BTC-USDT-SWAP",
        "BTC/USDT"
    ]
    
    print("Testing Open Interest Fetching...")
    
    for sym in symbols_to_test:
        print(f"\n--- Testing Symbol: {sym} ---")
        try:
            # Try fetching explicit Swap Open Interest
            # fetch_open_interest_history(symbol, timeframe, since, limit)
            oi = exchange.fetch_open_interest_history(sym, timeframe='1h', limit=5)
            print(f"Success! Records found: {len(oi)}")
            if oi:
                print("Sample Data:", oi[0])
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    debug_oi()
