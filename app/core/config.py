from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    database_url: str = "postgresql+asyncpg://epizoo:epizoo@localhost:5432/epizoo"
    api_key: str = ""
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    data_dir: Path = ROOT / "data"
    frontend_url: str = "http://localhost:5173"
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    summary_provider: Literal["template", "yandex"] = "template"
    yandex_api_key: str = ""
    yandex_folder_id: str = ""
    yandex_model: str = Field(default="yandexgpt-5-lite", min_length=1)
    summary_timeout: float = Field(default=10, gt=0, le=60)
    etl_lookback_days: int = Field(default=14, ge=1, le=365)
