import requests
import json
import time

def test_backtest_with_sentiment():
    url = "http://localhost:8000/quant/backtest"
    payload = {
        "symbol": "BTC/USDT",
        "lower_price": 60000,
        "upper_price": 75000,
        "grid_count": 20,
        "investment": 1000,
        "duration_days": 7
    }
    
    print(f"Running Backtest for 7 days on BTC/USDT...")
    try:
        start = time.time()
        res = requests.post(url, json=payload)
        print(f"Status Code: {res.status_code}")
        print(f"Time Taken: {time.time() - start:.2f}s")
        
        if res.status_code == 200:
            data = res.json()
            metrics = data['metrics']
            print("\n--- Backtest Results ---")
            print(f"Initial Balance: ${metrics['initial_balance']:.2f}")
            print(f"Final Balance:   ${metrics['final_balance']:.2f}")
            print(f"PnL:             ${metrics['pnl']:.2f} ({metrics['pnl_percent']:.2f}%)")
            print(f"Total Trades:    {metrics['total_trades']}")
            
            if metrics['total_trades'] > 0:
                print("✅ SUCCESS: Backtest executed trades.")
            else:
                print("⚠️ WARNING: No trades executed (Range might be wide or market stale).")
        else:
            print(f"❌ Error: {res.text}")
            
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    test_backtest_with_sentiment()
