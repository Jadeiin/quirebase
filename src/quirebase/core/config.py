from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="QUIREBASE_",
        env_file=".env",
        populate_by_name=True,
    )

    database_url: str = "sqlite:///./quirebase.db"
    data_dir: Path = Path("./quirebase-data")
    object_store: Literal["local", "s3"] = "local"
    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_endpoint: str | None = None
    s3_prefix: str | None = None
    session_cookie: str = "quirebase_session"
    session_days: int = 30
    secure_cookies: bool = False
    max_pdf_bytes: int = 250 * 1024 * 1024
    max_attachment_bytes: int = 250 * 1024 * 1024
    export_ttl_hours: int = 24
    worker_poll_seconds: float = Field(default=1.0, ge=0.1)
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    mcp_allowed_origins: str = ""
    metadata_timeout_seconds: float = Field(
        default=10.0,
        ge=1.0,
        le=30.0,
        validation_alias="INQUIRO_TIMEOUT_SECONDS",
    )
    metadata_max_response_bytes: int = Field(
        default=2 * 1024 * 1024,
        ge=1024,
        validation_alias="INQUIRO_MAX_RESPONSE_BYTES",
    )
    metadata_contact_email: str | None = Field(
        default=None,
        validation_alias="INQUIRO_CONTACT_EMAIL",
    )
    ncbi_api_key: str | None = Field(default=None, validation_alias="INQUIRO_NCBI_API_KEY")
    openalex_api_key: str | None = Field(
        default=None,
        validation_alias="INQUIRO_OPENALEX_API_KEY",
    )
    nasa_ads_token: str | None = Field(
        default=None,
        validation_alias="INQUIRO_NASA_ADS_TOKEN",
    )
    ieee_api_key: str | None = Field(default=None, validation_alias="INQUIRO_IEEE_API_KEY")
    recommendation_engine: str = "yake"
    recommendation_max_chars: int = Field(default=200_000, ge=1_000, le=2_000_000)
    keybert_model_path: Path | None = None
    keybert_model_sha256: str | None = None

    @property
    def allowed_host_list(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    @property
    def mcp_allowed_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.mcp_allowed_origins.split(",") if origin.strip()]

    @property
    def object_dir(self) -> Path:
        return self.data_dir / "objects"

    @property
    def export_dir(self) -> Path:
        return self.data_dir / "exports"


@lru_cache
def get_settings() -> Settings:
    return Settings()
