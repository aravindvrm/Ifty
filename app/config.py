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


@lru_cache
def get_settings() -> Settings:
    return Settings()
