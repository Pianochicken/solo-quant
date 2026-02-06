import ccxt
import sys

def check_exchange_capabilities():
    exchanges = ['binance', 'okx', 'bybit']
    capabilities = {}

    print(f"CCXT Version: {ccxt.__version__}")

    for exchange_id in exchanges:
        try:
            exchange_class = getattr(ccxt, exchange_id)
            exchange = exchange_class()
            
            # Check for specific methods
            has_funding_history = exchange.has.get('fetchFundingRateHistory', False)
            has_ohlcv = exchange.has.get('fetchOHLCV', False)
            has_open_interest = exchange.has.get('fetchOpenInterest', False)
            has_open_interest_history = exchange.has.get('fetchOpenInterestHistory', False)
            # Long/Short ratio is often custom or not unified
            has_long_short = 'fetchLongShortRatio' in dir(exchange) or 'fetchGlobalLongShortRatio' in dir(exchange) # checking method existence safely

            capabilities[exchange_id] = {
                'fetchOHLCV': has_ohlcv,
                'fetchFundingRateHistory': has_funding_history,
                'fetchOpenInterest': has_open_interest,
                'fetchOpenInterestHistory': has_open_interest_history,
                'Approx_LS_Ratio_Support': has_long_short
            }
        except Exception as e:
            capabilities[exchange_id] = str(e)

    print("\n--- Capabilities Report ---")
    for ex, caps in capabilities.items():
        print(f"[{ex.upper()}]")
        if isinstance(caps, dict):
            for feature, supported in caps.items():
                print(f"  - {feature}: {supported}")
        else:
            print(f"  Error: {caps}")

if __name__ == "__main__":
    check_exchange_capabilities()
