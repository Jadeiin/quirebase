from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from quirebase.audit import record_event
from quirebase.core.config import get_settings
from quirebase.core.errors import ResourceUnavailable, ValidationFailure
from quirebase.models import SystemSetting, User

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

ALLOWED_RUNTIME_KEYS: set[str] = {
    "metadata_contact_email",
    "ncbi_api_key",
    "openalex_api_key",
    "nasa_ads_token",
    "ieee_api_key",
    "session_days",
    "max_pdf_bytes",
    "max_attachment_bytes",
    "export_ttl_hours",
}

INTEGER_KEYS: set[str] = {
    "session_days",
    "max_pdf_bytes",
    "max_attachment_bytes",
    "export_ttl_hours",
}


def get_runtime_settings(db: Session) -> dict[str, Any]:
    base = get_settings()
    current: dict[str, Any] = {
        "metadata_contact_email": base.metadata_contact_email or "",
        "ncbi_api_key": base.ncbi_api_key or "",
        "openalex_api_key": base.openalex_api_key or "",
        "nasa_ads_token": base.nasa_ads_token or "",
        "ieee_api_key": base.ieee_api_key or "",
        "session_days": base.session_days,
        "max_pdf_bytes": base.max_pdf_bytes,
        "max_attachment_bytes": base.max_attachment_bytes,
        "export_ttl_hours": base.export_ttl_hours,
        "database_url": base.database_url,
        "data_dir": str(base.data_dir),
    }
    db_settings = list(db.scalars(select(SystemSetting)).all())
    for item in db_settings:
        if item.key in ALLOWED_RUNTIME_KEYS:
            if item.key in INTEGER_KEYS:
                try:
                    current[item.key] = int(item.value)
                except ValueError:
                    current[item.key] = item.value
            else:
                current[item.key] = item.value
    return current


def get_effective_setting(db: Session, key: str, default: Any = None) -> Any:
    if key in ALLOWED_RUNTIME_KEYS:
        record = db.get(SystemSetting, key)
        if record is not None and record.value is not None:
            if key in INTEGER_KEYS:
                try:
                    return int(record.value)
                except ValueError:
                    return record.value
            return record.value
    return getattr(get_settings(), key, default)


get_runtime_setting = get_effective_setting


def get_effective_settings_model(db: Session) -> Any:
    from quirebase.core.config import Settings

    return Settings(**get_runtime_settings(db))


def update_runtime_settings(db: Session, admin: User, updates: dict[str, Any]) -> None:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    sanitized: dict[str, str] = {}
    for key, value in updates.items():
        if key not in ALLOWED_RUNTIME_KEYS:
            raise ValidationFailure(f"setting '{key}' cannot be modified at runtime")
        str_val = str(value).strip() if value is not None else ""
        if key in INTEGER_KEYS and str_val:
            try:
                int_val = int(str_val)
                if int_val < 1:
                    raise ValidationFailure(f"'{key}' must be positive")
            except ValueError as error:
                raise ValidationFailure(f"'{key}' must be a valid integer") from error
        sanitized[key] = str_val

    now = datetime.now(UTC)
    for key, val in sanitized.items():
        existing = db.get(SystemSetting, key)
        if existing:
            existing.value = val
            existing.updated_at = now
            existing.updated_by = admin.id
        else:
            db.add(
                SystemSetting(
                    key=key,
                    value=val,
                    updated_at=now,
                    updated_by=admin.id,
                )
            )
    record_event(
        db,
        admin.id,
        "system.settings_update",
        "system_settings",
        None,
        detail={"modified_keys": list(sanitized.keys())},
    )
    db.commit()
