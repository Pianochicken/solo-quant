import requests
import json
import time

def test_endpoint():
    symbol = "BTC/USDT"
    url = f"http://127.0.0.1:8000/market/{symbol.replace('/', '-')}"
    
    print(f"Connecting to {url}...")
    try:
        start = time.time()
        res = requests.get(url)
        print(f"Status Code: {res.status_code}")
        print(f"Time Taken: {time.time() - start:.2f}s")
        
        if res.status_code == 200:
            data = res.json()
            print("\n--- Response Keys ---")
            print(data.keys())
            
            if "indicators" in data:
                print("\n--- Indicators Found ---")
                indicators = data["indicators"]
                print(json.dumps(indicators, indent=2))
                
                # Validation
                if "liquidity_walls" in indicators and "lsur_z_score" in indicators:
                    print("\n✅ SUCCESS: Indicators present.")
                else:
                    print("\n❌ FAILURE: Missing indicator keys.")
            else:
                print("\n❌ FAILURE: 'indicators' key missing.")
        else:
            print(f"Error: {res.text}")
            
    except Exception as e:
        print(f"Connection failed: {e}")
        print("Is the server running?")

if __name__ == "__main__":
    test_endpoint()
