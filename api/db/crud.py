from typing import List, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import desc, asc
from .models import MarketDataPoint, FundingRate

def upsert_market_data(db: Session, records: List[dict]):
    """
    Upsert (Insert or Update) market data points into the database.
    Expects records to be a list of dictionaries matching MarketDataPoint columns.
    Uses PostgreSQL ON CONFLICT DO UPDATE to avoid duplicates and update missing metrics.
    """
    if not records:
        return

    # Keep track of all keys present across all records
    record_keys = set()
    for r in records:
        record_keys.update(r.keys())

    # Create the insert statement
    stmt = insert(MarketDataPoint).values(records)

    # Define the fields to update on conflict (only update if explicitly provided)
    update_dict = {
        c.name: c
        for c in stmt.excluded
        if not c.primary_key and c.name in record_keys
    }

    # If no non-primary fields to update, just do nothing
    if not update_dict:
        return

    # Build the UPSERT statement
    # We use COALESCE/GREATEST/LEAST or just simple overwrite.
    # Here we overwrite with the newest API data, which is standard for CCXT backfilling.
    upsert_stmt = stmt.on_conflict_do_update(
        index_elements=['exchange', 'symbol', 'timeframe', 'timestamp'],
        set_=update_dict
    )

    db.execute(upsert_stmt)
    db.commit()

def get_market_data(
    db: Session, 
    symbol: str, 
    timeframe: str, 
    exchange: str = "okx", 
    limit: int = 100,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None
) -> List[MarketDataPoint]:
    """
    Retrieve market data points. Order is chronological (ascending timestamp).
    """
    query = db.query(MarketDataPoint).filter(
        MarketDataPoint.symbol == symbol,
        MarketDataPoint.timeframe == timeframe,
        MarketDataPoint.exchange == exchange
    )

    if start_time:
        query = query.filter(MarketDataPoint.timestamp >= start_time)
    if end_time:
        query = query.filter(MarketDataPoint.timestamp <= end_time)

    # If no specific time range but limit is requested, we want the *latest* N records, 
    # but returned in chronological order.
    if limit and not start_time and not end_time:
        # Subquery to get the latest N
        latest_records = query.order_by(desc(MarketDataPoint.timestamp)).limit(limit).all()
        # Sort back to chronological
        return sorted(latest_records, key=lambda x: x.timestamp)
    
    # Otherwise return normal query
    if limit:
        query = query.limit(limit)
        
    return query.order_by(asc(MarketDataPoint.timestamp)).all()

def upsert_funding_rates(db: Session, records: List[dict]):
    """
    Upsert funding rate data.
    """
    if not records:
        return

    stmt = insert(FundingRate).values(records)
    update_dict = {"funding_rate": stmt.excluded.funding_rate}

    upsert_stmt = stmt.on_conflict_do_update(
        index_elements=['exchange', 'symbol', 'timestamp'],
        set_=update_dict
    )

    db.execute(upsert_stmt)
    db.commit()

def get_latest_funding_rate(db: Session, symbol: str, exchange: str = "okx") -> Optional[FundingRate]:
    """
    Get the most recent funding rate.
    """
    return db.query(FundingRate).filter(
        FundingRate.symbol == symbol,
        FundingRate.exchange == exchange
    ).order_by(desc(FundingRate.timestamp)).first()
