
from api.core.fetcher import DataFetcher
from api.core.indicators import IndicatorEngine

def verify():
    fetcher = DataFetcher()
    symbol = "BTC/USDT"
    
    print("1. Fetching Taker Volume...")
    taker_volume = fetcher.fetch_taker_volume(symbol, period="1H", limit=100)
    print(f"   Count: {len(taker_volume)}")
    
    if taker_volume:
        print(f"   Sample: {taker_volume[0]}")
        
        print("\n2. Calculating CVD...")
        cvd_history = IndicatorEngine.calculate_cvd_history(taker_volume)
        print(f"   CVD Count: {len(cvd_history)}")
        if cvd_history:
            print(f"   First CVD: {cvd_history[0]}")
            print(f"   Last CVD:  {cvd_history[-1]}")
            print(f"   Min Value: {min(c['value'] for c in cvd_history):.2f}")
            print(f"   Max Value: {max(c['value'] for c in cvd_history):.2f}")
    else:
        print("   STILL EMPTY - Fix did not work!")

if __name__ == "__main__":
    verify()
