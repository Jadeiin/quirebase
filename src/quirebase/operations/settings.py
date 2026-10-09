from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from quirebase.access import SystemAction, require_system_action
from quirebase.audit import record_event
from quirebase.core.config import get_settings
from quirebase.core.errors import ValidationFailure
from quirebase.core.persistence import conflict_insert
from quirebase.models import SystemSetting, User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

ALLOWED_RUNTIME_KEYS: set[str] = {
    "registration_policy",
    "workspace_creation_policy",
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


def _setting_value(key: str, value: Any) -> str:
    if key not in ALLOWED_RUNTIME_KEYS:
        raise ValidationFailure(f"setting '{key}' cannot be modified at runtime")
    normalized = str(value).strip() if value is not None else ""
    if key == "registration_policy" and normalized not in {"open", "closed", "invitation_only"}:
        raise ValidationFailure("invalid registration policy")
    if key == "workspace_creation_policy" and normalized not in {"admins_only", "members_allowed"}:
        raise ValidationFailure("invalid Workspace creation policy")
    if key in INTEGER_KEYS and normalized:
        try:
            if int(normalized) < 1:
                raise ValidationFailure(f"'{key}' must be positive")
        except ValueError as error:
            raise ValidationFailure(f"'{key}' must be a valid integer") from error
    return normalized


async def get_runtime_settings(db: AsyncSession) -> dict[str, Any]:
    base = get_settings()
    current: dict[str, Any] = {
        "registration_policy": base.registration_policy,
        "workspace_creation_policy": base.workspace_creation_policy,
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
    db_settings = await db.scalars(select(SystemSetting))
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


async def get_effective_setting(db: AsyncSession, key: str, default: Any = None) -> Any:
    if key in ALLOWED_RUNTIME_KEYS:
        record = await db.scalar(select(SystemSetting).where(SystemSetting.key == key))
        if record is not None and record.value is not None:
            if key in INTEGER_KEYS:
                try:
                    return int(record.value)
                except ValueError:
                    return record.value
            return record.value
    return getattr(get_settings(), key, default)


async def get_effective_settings_model(db: AsyncSession) -> Any:
    from quirebase.core.config import Settings

    return Settings(**await get_runtime_settings(db))


async def update_runtime_settings(db: AsyncSession, admin: User, updates: dict[str, Any]) -> None:
    admin = await require_system_action(db, admin, SystemAction.settings_manage, lock="shared")
    settings = {key: _setting_value(key, value) for key, value in updates.items()}
    now = datetime.now(UTC)
    if settings:
        statement = conflict_insert(db, SystemSetting).values([
            {"key": key, "value": settings[key], "updated_by": admin.id, "updated_at": now}
            for key in sorted(settings)
        ])
        async with db.begin_nested():
            records = await db.scalars(
                statement
                .on_conflict_do_update(
                    index_elements=[SystemSetting.key],
                    set_={
                        "value": statement.excluded.value,
                        "updated_by": statement.excluded.updated_by,
                        "updated_at": statement.excluded.updated_at,
                    },
                )
                .returning(SystemSetting)
                .execution_options(populate_existing=True)
            )
            records.all()
    record_event(
        db,
        admin.id,
        "system.settings_update",
        "system_settings",
        None,
        detail={"modified_keys": list(updates)},
    )
    await db.commit()
