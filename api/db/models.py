from sqlalchemy import Column, String, Float, DateTime, PrimaryKeyConstraint
from .database import Base

class MarketDataPoint(Base):
    """
    Unified table for storing OHLCV + Metric data for signals.
    Composite primary key: (exchange, symbol, timeframe, timestamp)
    """
    __tablename__ = "market_data_points"

    timestamp = Column(DateTime(timezone=True), nullable=False)
    exchange = Column(String(20), nullable=False)     # e.g., 'binance', 'okx'
    symbol = Column(String(20), nullable=False)       # e.g., 'BTC/USDT'
    timeframe = Column(String(10), nullable=False)    # e.g., '15m', '1h', '4h', '1d'

    # OHLCV data
    open = Column(Float, nullable=True)
    high = Column(Float, nullable=True)
    low = Column(Float, nullable=True)
    close = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)

    # Core indicator metrics
    open_interest = Column(Float, nullable=True)      # Absolute OI
    long_short_ratio = Column(Float, nullable=True)   # LS ratio (accounts/volume based)
    taker_buy_vol = Column(Float, nullable=True)      # For CVD calculation
    taker_sell_vol = Column(Float, nullable=True)     # For CVD calculation

    __table_args__ = (
        PrimaryKeyConstraint('exchange', 'symbol', 'timeframe', 'timestamp'),
    )


class FundingRate(Base):
    """
    Funding rates are updated generally every 8 hours, independently of our main OHLCV timeframes.
    """
    __tablename__ = "funding_rates"

    timestamp = Column(DateTime(timezone=True), nullable=False)
    exchange = Column(String(20), nullable=False)
    symbol = Column(String(20), nullable=False)

    funding_rate = Column(Float, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint('exchange', 'symbol', 'timestamp'),
    )
