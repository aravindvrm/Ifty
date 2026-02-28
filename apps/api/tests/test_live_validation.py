from __future__ import annotations

from sqlalchemy.orm import Session


def test_live_validation_internal(seed_route_data, test_engine):
    from app.validation.live_validation import run_live_validation

    with Session(bind=test_engine) as db:
        report = run_live_validation(
            db=db,
            manager_keys=["1"],
            tickers=["AAPL"],
            sample_managers=0,
            sample_tickers=0,
            tolerance_pct=0.01,
            external_provider="none",
        )

    assert report["error_count"] == 0
    assert report["warn_count"] == 0
    assert report["checked"]["managers"] == ["1"]
    assert report["checked"]["tickers"] == ["AAPL"]
