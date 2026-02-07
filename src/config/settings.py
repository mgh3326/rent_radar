"""Application settings loaded from environment variables."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for API, workers, and crawlers."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "rent-radar"
    app_env: str = "local"

    database_url: str = (
        "postgresql+asyncpg://rent:rent_password@localhost:5433/rent_finder"
    )
    redis_url: str = "redis://localhost:6380/0"
    taskiq_testing: bool = False

    public_data_api_key: str = ""
    public_data_api_endpoint: str = "http://openapi.molit.go.kr/OpenAPI_ToolInstall498/service/rest/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"
    public_data_request_timeout_seconds: float = 10.0
    public_data_fetch_months: int = Field(default=2, ge=1, le=24)
    target_region_codes: list[str] = Field(default_factory=lambda: ["11110"])

    task_result_ttl_seconds: int = 3600
    crawl_dedup_ttl_seconds: int = 3600
    listing_cache_ttl_seconds: int = 1800
    seen_listing_ttl_seconds: int = 604800

    @field_validator("target_region_codes", mode="before")
    @classmethod
    def _parse_target_region_codes(cls, value: object) -> list[str]:
        if value is None:
            return ["11110"]
        if isinstance(value, str):
            parsed = [code.strip() for code in value.split(",") if code.strip()]
            return parsed or ["11110"]
        if isinstance(value, (int, float)):
            return [str(int(value))]
        if isinstance(value, list):
            parsed = [str(item).strip() for item in value if str(item).strip()]
            return parsed or ["11110"]
        raise ValueError("target_region_codes must be a comma-separated string or list")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance."""

    return Settings()
