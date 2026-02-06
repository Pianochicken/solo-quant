import ccxt

def debug_okx_symbols():
    exchange = ccxt.okx()
    exchange.load_markets()
    
    # Check for BTC/USDT variations
    target_base = 'BTC'
    target_quote = 'USDT'
    
    print(f"Checking for {target_base}/{target_quote} symbols on OKX...")
    
    matches = [s for s in exchange.symbols if target_base in s and target_quote in s]
    
    for s in matches[:10]: # Print first 10 matches
        market = exchange.market(s)
        if market['spot']:
            print(f"SPOT: {s} -> id: {market['id']}")
        if market['swap']:
            print(f"SWAP: {s} -> id: {market['id']}")
        if market['future']:
            print(f"FUTURE: {s} -> id: {market['id']}")
            
    # Try fetching funding rate for the most likely swap candidate
    swap_symbol = "BTC/USDT:USDT" 
    print(f"\nTesting fetch_funding_rate_history for {swap_symbol}...")
    try:
        funding = exchange.fetch_funding_rate_history(swap_symbol, limit=5)
        print("Success! First funding record:", funding[0])
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    debug_okx_symbols()
