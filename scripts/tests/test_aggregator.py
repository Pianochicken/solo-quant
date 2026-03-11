from api.core.fetcher import DataFetcher
import json

df = DataFetcher()
print("Fetching Aggregated Taker Volume...")
tv = df.fetch_taker_volume('BTC-USDT', '1h', 2)
print(json.dumps(tv, indent=2))

print("Fetching Aggregated Open Interest...")
oi = df.fetch_open_interest('BTC-USDT', 2, '1h')
print(json.dumps(oi, indent=2))

print("Fetching Aggregated LSUR...")
lsr = df.fetch_long_short_ratio('BTC-USDT', '1h', 2)
print(json.dumps(lsr, indent=2))
