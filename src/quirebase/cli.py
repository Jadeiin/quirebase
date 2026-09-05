from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import typer
import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text

from .accounts import (
    ApiTokenGrant,
    ApiTokenSummary,
    create_api_token,
    list_api_tokens,
    revoke_api_token,
)
from .core.config import get_settings
from .core.crypto import hash_password_async
from .core.database import AsyncSessionLocal, engine
from .core.logging import configure_logging
from .core.storage import get_object_store
from .core.workflows import (
    initialize_durable_operations,
    launch_worker,
    recover_workflows,
    verify_durable_operations,
)
from .library.tag_recommendations import validate_engine_configuration
from .models import User
from .operations import check_objects, create_backup, restore_backup, verify_backup
from .operations.object_migration import migrate_legacy_objects
from .operations.workflows import maintenance_schedules
from .search import reindex_all

app = typer.Typer(help="Quirebase administration")


def _register_workflows() -> None:
    import quirebase.documents.workflows  # ruff: ignore[unused-import]
    import quirebase.library.workflows  # ruff: ignore[unused-import]
    import quirebase.operations.workflows  # ruff: ignore[unused-import]


@app.command("serve")
def serve(host: str = "127.0.0.1", port: int = 9060, reload: bool = False):
    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_format == "json")
    uvicorn.run("quirebase.web.app:app", host=host, port=port, reload=reload, log_config=None)


@app.command("worker")
def worker():
    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_format == "json")
    _register_workflows()
    asyncio.run(_run_worker())


async def _run_worker() -> None:
    await launch_worker(maintenance_schedules())


@app.command("init-db")
def init_db():
    package_dir = Path(__file__).parent
    migrations = package_dir / "migrations"
    if not migrations.exists():
        migrations = package_dir.parents[1] / "migrations"
    alembic = Config()
    alembic.set_main_option("script_location", str(migrations))
    command.upgrade(alembic, "head")
    asyncio.run(initialize_durable_operations())
    settings = get_settings()
    if settings.object_store == "local":
        settings.object_dir.mkdir(parents=True, exist_ok=True)
    settings.export_dir.mkdir(parents=True, exist_ok=True)
    typer.echo("Database and data directories initialized.")


@app.command("create-admin")
def create_admin(
    username: str = typer.Option(..., prompt=True),
    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True),
):
    async def create() -> None:
        async with AsyncSessionLocal() as db:
            if await db.scalar(select(User).where(User.username == username)):
                raise typer.BadParameter("username already exists")
            db.add(
                User(
                    username=username,
                    password_hash=await hash_password_async(password),
                    role="administrator",
                )
            )
            await db.commit()

    asyncio.run(create())
    typer.echo(f"Administrator {username!r} created.")


async def _active_user(db, username: str) -> User:
    user = await db.scalar(select(User).where(User.username == username, User.active.is_(True)))
    if user is None:
        raise typer.BadParameter("active user not found")
    return user


@app.command("create-api-token")
def create_api_token_command(
    username: str = typer.Argument(...),
    name: str = typer.Option("MCP", help="Human-readable token name"),
    days: int = typer.Option(30, min=1, max=365, help="Token lifetime in days"),
):
    async def create() -> ApiTokenGrant:
        async with AsyncSessionLocal() as db:
            user = await _active_user(db, username)
            return await create_api_token(db, user, name, expires_in_days=days)

    grant = asyncio.run(create())
    typer.echo(f"Token ID: {grant.token_id}")
    typer.echo(f"Expires: {grant.expires_at.isoformat()}")
    typer.echo(f"API Token (shown once): {grant.raw_token}")


@app.command("list-api-tokens")
def list_api_tokens_command(username: str = typer.Argument(...)):
    async def list_tokens() -> tuple[ApiTokenSummary, ...]:
        async with AsyncSessionLocal() as db:
            user = await _active_user(db, username)
            return await list_api_tokens(db, user)

    tokens = asyncio.run(list_tokens())
    for token in tokens:
        typer.echo(
            f"{token.token_id}\t{token.status}\t{token.expires_at.isoformat()}\t{token.name}"
        )


@app.command("revoke-api-token")
def revoke_api_token_command(
    username: str = typer.Argument(...),
    token_id: str = typer.Argument(...),
):
    async def revoke() -> None:
        async with AsyncSessionLocal() as db:
            user = await _active_user(db, username)
            await revoke_api_token(db, user, token_id)

    asyncio.run(revoke())
    typer.echo(f"Revoked API Token {token_id}.")


@app.command("doctor")
def doctor():
    async def database_check() -> tuple[str, bool, list[str]]:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            dialect = connection.dialect.name
            has_users = await connection.run_sync(lambda sync: inspect(sync).has_table("users"))
        object_errors: list[str] = []
        if has_users:
            async with AsyncSessionLocal() as db:
                object_errors = await check_objects(db)
        return dialect, has_users, object_errors

    failures = 0
    has_users = False
    object_errors: list[str] = []
    try:
        dialect, has_users, object_errors = asyncio.run(database_check())
        typer.echo(f"[ok] database ({dialect})")
    except Exception as error:
        failures += 1
        typer.echo(f"[failed] database: {error}")
    try:

        async def probe_object_store() -> None:
            store = get_object_store()
            key = f".doctor/{uuid4().hex}"
            try:
                await store.put(key, b"ok")
                await store.head(key)
            finally:
                await store.delete(key)

        asyncio.run(probe_object_store())
        typer.echo(f"[ok] objects: {get_settings().object_store}")
    except Exception as error:
        failures += 1
        typer.echo(f"[failed] objects: {error}")
    try:
        asyncio.run(verify_durable_operations())
        typer.echo("[ok] workflows: DBOS system schema and Client")
    except Exception as error:
        failures += 1
        typer.echo(f"[failed] workflows: {error}")
    for label, directory in (("exports", get_settings().export_dir),):
        try:
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / ".write-test"
            probe.touch()
            probe.unlink()
            typer.echo(f"[ok] {label}: {directory}")
        except OSError as error:
            failures += 1
            typer.echo(f"[failed] {label}: {error}")
    try:
        import pymupdf

        typer.echo(f"[ok] PyMuPDF ({pymupdf.__version__})")
    except Exception as error:
        failures += 1
        typer.echo(f"[failed] PDF dependencies: {error}")
    try:
        descriptor = validate_engine_configuration(get_settings())
        typer.echo(f"[ok] recommendations: {descriptor.name} {descriptor.version}")
    except Exception as error:
        failures += 1
        typer.echo(f"[failed] recommendations: {error}")
    if not has_users:
        failures += 1
        typer.echo("[failed] schema is not initialized; run quirebase init-db")
    else:
        if object_errors:
            failures += len(object_errors)
            for object_error in object_errors:
                typer.echo(f"[failed] object {object_error}")
        else:
            typer.echo("[ok] object integrity")
    raise typer.Exit(code=1 if failures else 0)


@app.command("recover-workflows")
def recover_workflows_command(
    dead_executor_id: str = typer.Argument(..., help="Stable ID of the dead executor"),
    apply: bool = typer.Option(False, "--apply", help="Trigger recovery; default is dry-run"),
):
    _register_workflows()
    workflow_ids = asyncio.run(recover_workflows(dead_executor_id, apply=apply))
    mode = "recovering" if apply else "would recover"
    for workflow_id in workflow_ids:
        typer.echo(f"{mode}: {workflow_id}")
    typer.echo(f"{len(workflow_ids)} workflow(s) {mode} for executor {dead_executor_id}.")


@app.command("migrate-objects")
def migrate_objects_command(
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Copy objects and update references; Web and workers must be stopped",
    ),
):
    async def run():
        async with AsyncSessionLocal() as db:
            return await migrate_legacy_objects(db, apply=apply)

    report = asyncio.run(run())
    mode = "applied" if apply else "dry-run"
    typer.echo(
        f"Object migration {mode}: planned={report.planned}, copied={report.copied}, "
        f"updated={report.references_updated}, deleted={report.legacy_deleted}"
    )


@app.command("reindex")
def reindex():
    async def run() -> int:
        async with AsyncSessionLocal() as db:
            count = await reindex_all(db)
            await db.commit()
            return count

    count = asyncio.run(run())
    typer.echo(f"Indexed {count} items.")


@app.command("backup")
def backup(destination: Path = typer.Argument(...)):
    path = asyncio.run(create_backup(destination.resolve()))
    typer.echo(f"Backup created: {path}")


@app.command("verify-backup")
def verify_backup_command(archive: Path = typer.Argument(...)):
    manifest = asyncio.run(verify_backup(archive.resolve()))
    typer.echo(f"Backup verified: {manifest['database_kind']} {manifest['created_at']}")


@app.command("restore")
def restore(
    archive: Path = typer.Argument(...),
    force: bool = typer.Option(
        False, "--force", help="Replace the configured database and objects"
    ),
):
    if not force:
        raise typer.BadParameter("restore is destructive; inspect the target and pass --force")
    asyncio.run(engine.dispose())
    asyncio.run(restore_backup(archive.resolve(), force=True))
    typer.echo("Backup restored. Restart all web and worker processes.")


if __name__ == "__main__":
    app()
