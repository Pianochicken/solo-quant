import ccxt
import time

def check_limit():
    exchange = ccxt.okx()
    symbol = 'BTC/USDT:USDT'
    
    print("Requesting 100 candles...")
    ohlcv_100 = exchange.fetch_ohlcv(symbol, '1h', limit=100)
    print(f"Received: {len(ohlcv_100)}")
    
    print("\nRequesting 500 candles...")
    ohlcv_500 = exchange.fetch_ohlcv(symbol, '1h', limit=500)
    print(f"Received: {len(ohlcv_500)}")
    
    print("\nRequesting 1000 candles...")
    ohlcv_1000 = exchange.fetch_ohlcv(symbol, '1h', limit=1000)
    print(f"Received: {len(ohlcv_1000)}")

if __name__ == "__main__":
    check_limit()
