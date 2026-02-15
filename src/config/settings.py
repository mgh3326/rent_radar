"""Application settings loaded from environment variables."""

import json
from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources.providers.dotenv import DotEnvSettingsSource
from pydantic_settings.sources.providers.env import EnvSettingsSource


VALID_PROPERTY_TYPES = ("apt", "villa", "officetel", "house")

# Fields that accept comma-separated strings in .env
_COMMA_LIST_FIELDS = frozenset(
    {"target_property_types", "target_region_codes", "mcp_enabled_tools"}
)


class _CommaListSourceMixin:
    """Allow comma-separated values for list fields instead of requiring JSON."""

    def prepare_field_value(
        self, field_name: str, field: object, value: object, value_is_complex: bool
    ) -> object:
        if field_name in _COMMA_LIST_FIELDS and isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, ValueError):
                return [v.strip() for v in value.split(",") if v.strip()]
        return super().prepare_field_value(field_name, field, value, value_is_complex)


class _Env(_CommaListSourceMixin, EnvSettingsSource):
    pass


class _DotEnv(_CommaListSourceMixin, DotEnvSettingsSource):
    pass


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
    public_data_api_base_url: str = "https://apis.data.go.kr/1613000/"
    public_data_request_timeout_seconds: float = 10.0
    public_data_fetch_months: int = Field(default=2, ge=1, le=24)
    target_property_types: list[str] = Field(default_factory=lambda: ["apt"])
    target_region_codes: list[str] = Field(default_factory=lambda: ["11110"])
    mcp_enabled_tools: list[str] = Field(default_factory=list)

    task_result_ttl_seconds: int = 3600
    crawl_dedup_ttl_seconds: int = 3600
    listing_cache_ttl_seconds: int = 1800
    seen_listing_ttl_seconds: int = 604800
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    @field_validator("target_property_types", mode="before")
    @classmethod
    def _parse_target_property_types(cls, value: object) -> list[str]:
        if value is None:
            return ["apt"]
        if isinstance(value, str):
            parsed = [ptype.strip() for ptype in value.split(",") if ptype.strip()]
            return parsed or ["apt"]
        if isinstance(value, list):
            parsed = [str(item).strip() for item in value if str(item).strip()]
            return parsed or ["apt"]
        raise ValueError(
            "target_property_types must be a comma-separated string or list"
        )

    @model_validator(mode="after")
    def _validate_target_property_types(self) -> "Settings":
        valid_types = {"apt", "villa", "officetel", "house"}
        invalid_types = {
            pt.lower() for pt in set(self.target_property_types)
        } - valid_types
        if invalid_types:
            raise ValueError(
                f"Invalid property_types: {', '.join(sorted(invalid_types))}. "
                f"Valid values are: {', '.join(sorted(valid_types))} (case-insensitive)"
            )
        return self

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

    @field_validator("mcp_enabled_tools", mode="before")
    @classmethod
    def _parse_mcp_enabled_tools(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = value.split(",")
        elif isinstance(value, list):
            raw_items = [str(item) for item in value]
        else:
            raise ValueError(
                "mcp_enabled_tools must be a comma-separated string or list"
            )

        normalized: list[str] = []
        seen: set[str] = set()
        for raw_item in raw_items:
            tool_name = raw_item.strip().lower()
            if not tool_name or tool_name in seen:
                continue
            seen.add(tool_name)
            normalized.append(tool_name)

        return normalized

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (
            init_settings,
            _Env(settings_cls),
            _DotEnv(
                settings_cls,
                env_file=settings_cls.model_config.get("env_file", ".env"),
                env_file_encoding=settings_cls.model_config.get(
                    "env_file_encoding", "utf-8"
                ),
            ),
            file_secret_settings,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance."""

    return Settings()
