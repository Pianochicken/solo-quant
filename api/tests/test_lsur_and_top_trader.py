"""
Unit tests for LSUR/CVD lowercase normalization, Z-score min_periods,
and Binance Top Trader Position L/S Ratio fetcher.
"""

from datetime import datetime, timezone
from contextlib import contextmanager
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.db.database import Base
from api.db.models import MarketDataPoint
from api.db import crud
from api.core.indicators import IndicatorEngine
from api.core.fetcher import DataFetcher


def test_lsur_z_score_min_periods_and_constant():
    # Below default window=90 returns 0.0
    short_series = [{"time": i * 86400, "value": 1.0 + i * 0.02} for i in range(30)]
    assert IndicatorEngine.calculate_lsur_z_score(short_series) == 0.0

    # With min_periods=14 (for 1d Top Trader 30-day history), returns finite positive Z-score
    z_daily = IndicatorEngine.calculate_lsur_z_score(short_series, window=90, min_periods=14)
    assert z_daily > 1.0

    # Constant series (zero std) must safely return 0.0
    const_series = [{"time": i * 3600, "value": 1.5} for i in range(100)]
    assert IndicatorEngine.calculate_lsur_z_score(const_series) == 0.0
    assert IndicatorEngine.calculate_lsur_z_score(const_series, window=90, min_periods=14) == 0.0


def test_crud_get_market_data_normalizes_timeframe_and_require_column():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        t1 = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 11, 20, 13, 0, tzinfo=timezone.utc)
        # Row 1 has OI but no long_short_ratio
        db.add(MarketDataPoint(
            exchange="okx",
            symbol="BTC/USDT",
            timeframe="1h",
            timestamp=t1,
            open_interest=5e9,
            long_short_ratio=None,
        ))
        # Row 2 has long_short_ratio and top_ls_position_ratio
        db.add(MarketDataPoint(
            exchange="okx",
            symbol="BTC/USDT",
            timeframe="1h",
            timestamp=t2,
            long_short_ratio=2.05,
        ))
        db.add(MarketDataPoint(
            exchange="binance",
            symbol="BTC/USDT",
            timeframe="1h",
            timestamp=t2,
            top_ls_position_ratio=1.83,
        ))
        db.commit()

        # Passing uppercase '1H' must normalize to '1h' and find records
        rows_ls = crud.get_market_data(
            db,
            symbol="BTC/USDT",
            timeframe="1H",
            exchange="okx",
            limit=10,
            require_column="long_short_ratio",
        )
        assert len(rows_ls) == 1
        assert rows_ls[0].long_short_ratio == 2.05

        rows_top = crud.get_market_data(
            db,
            symbol="BTC/USDT",
            timeframe="1H",
            exchange="binance",
            limit=10,
            require_column="top_ls_position_ratio",
        )
        assert len(rows_top) == 1
        assert rows_top[0].top_ls_position_ratio == 1.83


def test_fetch_top_trader_position_ratio_binance_only_and_lowercase():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    @contextmanager
    def fake_session_local():
        sess = TestSession()
        try:
            yield sess
        finally:
            sess.close()

    def fake_upsert(db, records):
        for r in records:
            r["timeframe"] = str(r.get("timeframe", "")).lower()
            existing = db.query(MarketDataPoint).filter_by(
                exchange=r["exchange"],
                symbol=r["symbol"],
                timeframe=r["timeframe"],
                timestamp=r["timestamp"],
            ).first()
            if existing:
                existing.top_ls_position_ratio = r["top_ls_position_ratio"]
            else:
                db.add(MarketDataPoint(**r))
        db.commit()

    sample_api_rows = [
        {"symbol": "BTCUSDT", "longAccount": "0.6200", "longShortRatio": "1.6316", "shortAccount": "0.3800", "timestamp": 1795269600000},
        {"symbol": "BTCUSDT", "longAccount": "0.6462", "longShortRatio": "1.8267", "shortAccount": "0.3538", "timestamp": 1795273200000},
    ]

    with patch("api.core.fetcher.SessionLocal", fake_session_local), \
         patch("api.core.fetcher.crud.upsert_market_data", side_effect=fake_upsert):
        fetcher = DataFetcher()
        fetcher.binance.fapidataGetToplongshortpositionratio = MagicMock(return_value=sample_api_rows)

        res = fetcher.fetch_top_trader_position_ratio("BTC/USDT", period="1H", limit=100)

        assert len(res) == 2
        assert res[0]["time"] == 1795269600
        assert res[0]["value"] == 1.6316
        assert res[1]["time"] == 1795273200
        assert res[1]["value"] == 1.8267

        # Verify stored with exchange='binance' and lowercase timeframe='1h'
        with TestSession() as db:
            stored = crud.get_market_data(
                db, symbol="BTC/USDT", timeframe="1h", exchange="binance", limit=10, require_column="top_ls_position_ratio"
            )
            assert len(stored) == 2
            assert stored[-1].timeframe == "1h"
