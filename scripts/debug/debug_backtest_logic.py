from api.core.fetcher import DataFetcher
from api.quant.grid_bot import GridBot
from api.quant.backtester import Backtester
from api.core.indicators import IndicatorEngine
import time
import pandas as pd
import traceback

def debug_backtest():
    print("Initializing Fetcher...")
    fetcher = DataFetcher()
    symbol = "BTC/USDT"
    formatted_symbol = "BTC/USDT"
    
    try:
        # 1. Fetch History
        print("Fetching Price History...")
        end_time = int(time.time() * 1000)
        start_time = end_time - (7 * 24 * 60 * 60 * 1000)
        history = fetcher.fetch_history(formatted_symbol, start_time, end_time, '1h')
        print(f"Price History: {len(history)} candles")
        
        # 2. Fetch Sentiment
        print("Fetching Sentiment...")
        hours_needed = 7 * 24
        lsur_raw = fetcher.fetch_long_short_ratio(formatted_symbol, period='1H', limit=hours_needed + 50)
        print(f"Sentiment Raw: {len(lsur_raw) if lsur_raw else 'None'}")
        
        # 3. Process Sentiment
        if lsur_raw:
            lsur_df = pd.DataFrame(lsur_raw)
            print("DataFrame Created")
            print(lsur_df.head())
            
            lsur_df['value'] = lsur_df['value'].astype(float)
            lsur_df = lsur_df.sort_values('time')
            
            window = 20
            lsur_df['mean'] = lsur_df['value'].rolling(window=window).mean()
            lsur_df['std'] = lsur_df['value'].rolling(window=window).std()
            lsur_df['z_score'] = (lsur_df['value'] - lsur_df['mean']) / lsur_df['std']
            
            sentiment_data = lsur_df[['time', 'z_score']].dropna().rename(columns={'z_score': 'value'}).to_dict('records')
            print(f"Sentiment Processed: {len(sentiment_data)} points")
        else:
            sentiment_data = []
            
        # 4. Init Bot
        bot = GridBot(formatted_symbol, 60000, 75000, 20, 1000)
        
        # 5. Run Backtest
        print("Running Backtester...")
        tester = Backtester(bot, history, sentiment_data=sentiment_data)
        result = tester.run()
        
        print("Backtest Complete!")
        print(f"Final Balance: {result['final_balance']}")
        
    except Exception as e:
        print("CRASHED:")
        traceback.print_exc()

if __name__ == "__main__":
    debug_backtest()
