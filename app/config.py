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
    api_cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    retention_13dg_days: int = 120
    ai_enabled: bool = False
    ai_base_url: str = "http://127.0.0.1:1234/v1"
    ai_api_key: str = ""
    ai_model: str = "gpt-4o-mini"
    ai_temperature: float = 0.1
    ai_request_timeout_seconds: float = 45.0
    ai_max_steps: int = 6
    ai_sql_fallback_enabled: bool = False
    ai_max_output_tokens: int = 700
    ai_max_history_messages: int = 12
    ai_max_message_chars: int = 2000
    ai_tool_result_max_chars: int = 1800


@lru_cache
def get_settings() -> Settings:
    return Settings()
