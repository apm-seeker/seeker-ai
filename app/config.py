from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "local"
    log_level: str = "INFO"

    database_url: str = "mysql+aiomysql://root:root@127.0.0.1:3306/seeker_ai"

    seeker_web_base_url: str = "http://127.0.0.1:8080"
    seeker_web_timeout_sec: int = 10

    llm_model: str = "google_genai:gemini-2.0-flash"
    google_api_key: str | None = None

    default_user_id: str = "default"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
