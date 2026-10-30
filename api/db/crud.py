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

    # 1. Lowercase timeframe and deduplicate within batch by primary key
    dedup_dict = {}
    for r in records:
        r['timeframe'] = str(r.get('timeframe', '')).lower()
        pk = (
            str(r.get('exchange', '')),
            str(r.get('symbol', '')),
            str(r.get('timeframe', '')),
            r.get('timestamp')
        )
        if pk in dedup_dict:
            # Merge fields: non-None fields overwrite earlier fields
            for k, v in r.items():
                if v is not None:
                    dedup_dict[pk][k] = v
        else:
            dedup_dict[pk] = dict(r)

    # 2. Sort records by primary index elements to prevent PostgreSQL deadlocks during concurrent upserts
    def get_sort_key(r):
        ts = r.get('timestamp')
        ts_sec = ts.timestamp() if hasattr(ts, 'timestamp') else float(ts or 0)
        return (
            str(r.get('exchange', '')),
            str(r.get('symbol', '')),
            str(r.get('timeframe', '')),
            ts_sec
        )

    sorted_records = sorted(dedup_dict.values(), key=get_sort_key)

    # Keep track of all keys present across all records
    record_keys = set()
    for r in sorted_records:
        record_keys.update(r.keys())

    # Create the insert statement
    stmt = insert(MarketDataPoint).values(sorted_records)

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
    end_time: Optional[datetime] = None,
    require_ohlcv: bool = False
) -> List[MarketDataPoint]:
    """
    Retrieve market data points. Order is chronological (ascending timestamp).
    """
    query = db.query(MarketDataPoint).filter(
        MarketDataPoint.symbol == symbol,
        MarketDataPoint.timeframe == timeframe,
        MarketDataPoint.exchange == exchange
    )

    if require_ohlcv:
        query = query.filter(MarketDataPoint.open.isnot(None))

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
    Upsert funding rate data with batch deduplication and deterministic primary key sorting.
    """
    if not records:
        return

    # 1. Deduplicate within batch by primary key (exchange, symbol, timestamp)
    dedup_dict = {}
    for r in records:
        pk = (
            str(r.get('exchange', '')),
            str(r.get('symbol', '')),
            r.get('timestamp')
        )
        if pk in dedup_dict:
            for k, v in r.items():
                if v is not None:
                    dedup_dict[pk][k] = v
        else:
            dedup_dict[pk] = dict(r)

    # 2. Sort deterministically by primary index elements
    def get_sort_key(r):
        ts = r.get('timestamp')
        ts_sec = ts.timestamp() if hasattr(ts, 'timestamp') else float(ts or 0)
        return (
            str(r.get('exchange', '')),
            str(r.get('symbol', '')),
            ts_sec
        )

    sorted_records = sorted(dedup_dict.values(), key=get_sort_key)

    stmt = insert(FundingRate).values(sorted_records)
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
