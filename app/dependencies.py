from fastapi import Depends
from sqlalchemy.orm import Session

from app.clients.rate_limit import ProviderRateLimiter
from app.clients.sec_client import SecClient, build_sec_http_session
from app.config import get_settings
from app.db import get_db_session

_limiter: ProviderRateLimiter | None = None
_http_session = None


def get_limiter() -> ProviderRateLimiter:
    global _limiter
    if _limiter is None:
        settings = get_settings()
        _limiter = ProviderRateLimiter()
        _limiter.register(provider="SEC", rate_per_sec=float(settings.sec_burst_per_second))
    return _limiter


def get_db() -> Session:
    yield from get_db_session()


def get_sec_client(db: Session = Depends(get_db)) -> SecClient:
    global _http_session
    if _http_session is None:
        _http_session = build_sec_http_session()
    return SecClient(
        session=_http_session,
        limiter=get_limiter(),
        db=db,
    )
