from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QUIREBASE_", env_file=".env")

    database_url: str = "sqlite:///./quirebase.db"
    data_dir: Path = Path("./quirebase-data")
    session_cookie: str = "quirebase_session"
    session_days: int = 30
    secure_cookies: bool = False
    max_pdf_bytes: int = 250 * 1024 * 1024
    max_attachment_bytes: int = 250 * 1024 * 1024
    export_ttl_hours: int = 24
    worker_poll_seconds: float = Field(default=1.0, ge=0.1)
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    metadata_timeout_seconds: float = Field(default=10.0, ge=1.0, le=30.0)
    metadata_max_response_bytes: int = Field(default=2 * 1024 * 1024, ge=1024)
    metadata_contact_email: str | None = None
    ncbi_api_key: str | None = None
    openalex_api_key: str | None = None
    nasa_ads_token: str | None = None
    ieee_api_key: str | None = None

    @property
    def allowed_host_list(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    @property
    def object_dir(self) -> Path:
        return self.data_dir / "objects"

    @property
    def export_dir(self) -> Path:
        return self.data_dir / "exports"


@lru_cache
def get_settings() -> Settings:
    return Settings()
