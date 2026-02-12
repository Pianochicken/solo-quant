import requests
import json
import time

def test_smart_params():
    symbol = "BTC/USDT"
    url = f"http://127.0.0.1:8000/quant/smart-params/{symbol.replace('/', '-')}"
    
    print(f"Requesting Smart Params from {url}...")
    try:
        start = time.time()
        res = requests.get(url)
        print(f"Status Code: {res.status_code}")
        print(f"Time Taken: {time.time() - start:.2f}s")
        
        if res.status_code == 200:
            data = res.json()
            print("\n--- Smart Params Received ---")
            print(json.dumps(data, indent=2))
            
            # Validation
            required = ["lower_price", "upper_price", "sentiment_score"]
            if all(k in data for k in required):
                print("\n✅ SUCCESS: Smart Params valid.")
                print(f"Range: {data['lower_price']} - {data['upper_price']}")
                print(f"Sentiment: {data['sentiment_score']:.2f} ({data['signal']})")
            else:
                print("\n❌ FAILURE: Missing keys.")
        else:
            print(f"Error: {res.text}")
            
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    test_smart_params()
