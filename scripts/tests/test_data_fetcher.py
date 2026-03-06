from api.core.fetcher import DataFetcher
import json

def test_data_fetcher():
    fetcher = DataFetcher()
    symbol = "BTC/USDT"
    
    print(f"--- Testing Data Fetcher for {symbol} ---")
    
    # 1. Test Order Book Depth
    print("\n1. Fetching Order Book Depth...")
    depth = fetcher.fetch_order_book_depth(symbol, limit=5)
    print(f"Bids: {len(depth['bids'])}, Asks: {len(depth['asks'])}")
    if depth['bids']:
        print(f"Top Bid: {depth['bids'][0]}")
    if depth['asks']:
        print(f"Top Ask: {depth['asks'][0]}")
        
    # 2. Test Long/Short Ratio
    print("\n2. Fetching Long/Short Account Ratio (Implicit API)...")
    ls_ratio = fetcher.fetch_long_short_ratio(symbol)
    print(f"Received {len(ls_ratio)} data points.")
    if ls_ratio:
        print(f"Latest L/S Ratio: {ls_ratio[-1]}")
        
    # 3. Test USDC/USDT Ticker (Premium)
    print("\n3. Fetching USDC/USDT Ticker...")
    try:
        ticker = fetcher.exchange.fetch_ticker("USDC/USDT")
        print(f"USDC/USDT Price: {ticker['last']}")
    except Exception as e:
        print(f"Failed to fetch USDC/USDT: {e}")

if __name__ == "__main__":
    test_data_fetcher()
