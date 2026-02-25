from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def _ensure_sqlite_parent_exists(db_url: str) -> None:
    if not db_url.startswith("sqlite:///"):
        return
    db_path = db_url.replace("sqlite:///", "", 1)
    path = Path(db_path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)


def get_engine() -> Engine:
    settings = get_settings()
    _ensure_sqlite_parent_exists(settings.api_db_url)
    return create_engine(settings.api_db_url, future=True)


SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, class_=Session)


def get_db_session() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def ensure_schema_and_seed(engine: Engine) -> None:
    root = Path(__file__).resolve().parent.parent
    schema_sql = (root / "db" / "schema.sql").read_text(encoding="utf-8")
    seed_sql = (root / "db" / "seed_api_budgets.sql").read_text(encoding="utf-8")
    with engine.begin() as conn:
        raw = conn.connection
        raw.executescript(schema_sql)
        raw.executescript(seed_sql)
