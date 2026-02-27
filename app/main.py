from fastapi import FastAPI

from app.api.routes import router
from app.db import ensure_schema_and_seed, get_engine

app = FastAPI(title="Institutional Flow Tracker API", version="0.1.0")
app.include_router(router)


@app.on_event("startup")
def _startup_init_db() -> None:
    # Ensure schema exists for whichever DB URL the process is using.
    ensure_schema_and_seed(get_engine())
