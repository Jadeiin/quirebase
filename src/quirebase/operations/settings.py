from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError

from quirebase.access import SystemAction, require_system_action
from quirebase.audit import record_event
from quirebase.core.config import get_settings
from quirebase.core.errors import ValidationFailure
from quirebase.core.persistence import Repository, Service
from quirebase.models import SystemSetting, User

if TYPE_CHECKING:
    from uuid import UUID

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


class RuntimeSettingRepository(Repository[SystemSetting]):
    model_type = SystemSetting
    id_attribute = "key"


class RuntimeSettingsService(Service[SystemSetting]):
    repository_type = RuntimeSettingRepository

    async def store(self, actor_id: UUID, updates: dict[str, Any]) -> None:
        sanitized = {key: _setting_value(key, value) for key, value in updates.items()}
        if not sanitized:
            return
        existing_keys = {
            record.key for record in await self.get_many(SystemSetting.key.in_(sanitized))
        }
        now = datetime.now(UTC)
        values = {
            key: {"key": key, "value": value, "updated_by": actor_id, "updated_at": now}
            for key, value in sanitized.items()
        }
        pending = set(sanitized) - existing_keys
        while pending:
            try:
                async with self.repository.session.begin_nested():
                    await self.create_many([values[key] for key in sorted(pending)])
                break
            except IntegrityError:
                # A concurrent administrator may have installed one of the missing keys.
                # Every retry removes those keys; unrelated constraint failures propagate.
                installed = {
                    record.key for record in await self.get_many(SystemSetting.key.in_(pending))
                }
                if not installed:
                    raise
                existing_keys.update(installed)
                pending -= installed
        if existing_keys:
            await self.update_many(
                [values[key] for key in sorted(existing_keys)],
                execution_options={"populate_existing": True},
            )


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
    db_settings = await RuntimeSettingsService(db).get_many()
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
        record = await RuntimeSettingsService(db).get_one_or_none(key=key)
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
    await RuntimeSettingsService(db).store(admin.id, updates)
    record_event(
        db,
        admin.id,
        "system.settings_update",
        "system_settings",
        None,
        detail={"modified_keys": list(updates)},
    )
    await db.commit()
