from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_db_url: str = "sqlite:///./data/app.db"
    sec_user_agent: str = ""
    sec_base_url: str = "https://data.sec.gov"
    sec_archives_base_url: str = "https://www.sec.gov/Archives"
    sec_www_base_url: str = "https://www.sec.gov"
    sec_burst_per_second: int = 8
    request_timeout_seconds: float = 20.0
    poly_key: str = ""
    av_key: str = ""
    openfigi_api_key: str = ""
    openfigi_base_url: str = "https://api.openfigi.com/v3/mapping"
    openfigi_requests_per_minute: int = 20
    openfigi_batch_size: int = 50
    nasdaq_burst_per_second: float = 0.5
    polygon_burst_per_second: float = 0.2
    alphavantage_burst_per_second: float = 0.08
    db_pool_size: int = 20
    db_max_overflow: int = 40
    db_pool_timeout_seconds: int = 30
    db_pool_recycle_seconds: int = 1800
    db_statement_timeout_ms: int = 20000
    api_verbose_logs: int = 0
    api_slow_request_ms: int = 1500
    aum_top_n_default: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()
