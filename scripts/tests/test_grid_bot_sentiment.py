from api.quant.grid_bot import GridBot


def test_grid_bot_sentiment_guard_high_z_score():
    # Setup: Price 100. Grid 90-110. Current Price 100.
    # Grids: 90, 95, 100, 105, 110 (roughly)
    bot = GridBot("BTC/USDT", 90, 110, 5, 1000)
    
    # Normal Case (Z=0): Should have Buys (90, 95) and Sells (105, 110)
    orders = bot.get_orders_for_price(100, sentiment_score=0.0)
    buys = [o for o in orders if o['side'] == 'buy']
    sells = [o for o in orders if o['side'] == 'sell']
    
    assert len(buys) > 0, "Should have buy orders normally"
    assert len(sells) > 0, "Should have sell orders normally"
    
    # High Z-Score (Crowd Long > 2.0) -> Expect NO BUYS (Don't catch knife)
    orders_bearish = bot.get_orders_for_price(100, sentiment_score=2.5)
    buys_bearish = [o for o in orders_bearish if o['side'] == 'buy']
    sells_bearish = [o for o in orders_bearish if o['side'] == 'sell']
    
    assert len(buys_bearish) == 0, "Should NOT buy when crowd is too long (Z > 2)"
    assert len(sells_bearish) > 0, "Should still sell when crowd is long"

def test_grid_bot_sentiment_guard_low_z_score():
    bot = GridBot("BTC/USDT", 90, 110, 5, 1000)
    
    # Low Z-Score (Crowd Short < -2.0) -> Expect NO SELLS (Don't sell bottom)
    orders_bullish = bot.get_orders_for_price(100, sentiment_score=-2.5)
    buys_bullish = [o for o in orders_bullish if o['side'] == 'buy']
    sells_bullish = [o for o in orders_bullish if o['side'] == 'sell']
    
    assert len(sells_bullish) == 0, "Should NOT sell when crowd is panic selling (Z < -2)"
    assert len(buys_bullish) > 0, "Should still buy when crowd is panic selling"

if __name__ == "__main__":
    print("Running Manual Tests...")
    try:
        test_grid_bot_sentiment_guard_high_z_score()
        print("✅ High Z-Score Test Passed (Buys Blocked)")
        test_grid_bot_sentiment_guard_low_z_score()
        print("✅ Low Z-Score Test Passed (Sells Blocked)")
    except AssertionError as e:
        print(f"❌ Test Failed: {e}")
