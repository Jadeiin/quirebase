from __future__ import annotations

from pathlib import Path

import typer
import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text

from .accounts import create_api_token, list_api_tokens, revoke_api_token
from .core.config import get_settings
from .core.crypto import hash_password
from .core.database import SessionLocal, engine
from .library.tag_recommendations import validate_engine_configuration
from .models import User
from .operations import check_objects, create_backup, restore_backup, verify_backup
from .pipeline import run_forever
from .search import reindex_all

app = typer.Typer(help="Quirebase administration")


@app.command("serve")
def serve(host: str = "127.0.0.1", port: int = 9060, reload: bool = False):
    uvicorn.run("quirebase.web.app:app", host=host, port=port, reload=reload)


@app.command("worker")
def worker():
    run_forever()


@app.command("init-db")
def init_db():
    package_dir = Path(__file__).parent
    migrations = package_dir / "migrations"
    if not migrations.exists():
        migrations = package_dir.parents[1] / "migrations"
    alembic = Config()
    alembic.set_main_option("script_location", str(migrations))
    command.upgrade(alembic, "head")
    settings = get_settings()
    settings.object_dir.mkdir(parents=True, exist_ok=True)
    settings.export_dir.mkdir(parents=True, exist_ok=True)
    typer.echo("Database and data directories initialized.")


@app.command("create-admin")
def create_admin(
    username: str = typer.Option(..., prompt=True),
    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True),
):
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.username == username)):
            raise typer.BadParameter("username already exists")
        db.add(User(username=username, password_hash=hash_password(password), role="administrator"))
        db.commit()
    typer.echo(f"Administrator {username!r} created.")


def _active_user(db, username: str) -> User:
    user = db.scalar(select(User).where(User.username == username, User.active.is_(True)))
    if user is None:
        raise typer.BadParameter("active user not found")
    return user


@app.command("create-api-token")
def create_api_token_command(
    username: str = typer.Argument(...),
    name: str = typer.Option("MCP", help="Human-readable token name"),
    days: int = typer.Option(30, min=1, max=365, help="Token lifetime in days"),
):
    with SessionLocal() as db:
        user = _active_user(db, username)
        grant = create_api_token(db, user, name, expires_in_days=days)
    typer.echo(f"Token ID: {grant.token_id}")
    typer.echo(f"Expires: {grant.expires_at.isoformat()}")
    typer.echo(f"API Token (shown once): {grant.raw_token}")


@app.command("list-api-tokens")
def list_api_tokens_command(username: str = typer.Argument(...)):
    with SessionLocal() as db:
        user = _active_user(db, username)
        tokens = list_api_tokens(db, user)
    for token in tokens:
        typer.echo(
            f"{token.token_id}\t{token.status}\t{token.expires_at.isoformat()}\t{token.name}"
        )


@app.command("revoke-api-token")
def revoke_api_token_command(
    username: str = typer.Argument(...),
    token_id: str = typer.Argument(...),
):
    with SessionLocal() as db:
        user = _active_user(db, username)
        revoke_api_token(db, user, token_id)
    typer.echo(f"Revoked API Token {token_id}.")


@app.command("doctor")
def doctor():
    failures = 0
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        typer.echo(f"[ok] database ({engine.dialect.name})")
    except Exception as error:
        failures += 1
        typer.echo(f"[failed] database: {error}")
    for label, directory in (
        ("objects", get_settings().object_dir),
        ("exports", get_settings().export_dir),
    ):
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
        model = f", model {descriptor.model_fingerprint}" if descriptor.model_fingerprint else ""
        typer.echo(f"[ok] recommendations: {descriptor.name} {descriptor.version}{model}")
    except Exception as error:
        failures += 1
        typer.echo(f"[failed] recommendations: {error}")
    if not inspect(engine).has_table("users"):
        failures += 1
        typer.echo("[failed] schema is not initialized; run quirebase init-db")
    else:
        with SessionLocal() as db:
            object_errors = check_objects(db)
        if object_errors:
            failures += len(object_errors)
            for object_error in object_errors:
                typer.echo(f"[failed] object {object_error}")
        else:
            typer.echo("[ok] object integrity")
    raise typer.Exit(code=1 if failures else 0)


@app.command("reindex")
def reindex():
    with SessionLocal() as db:
        count = reindex_all(db)
        db.commit()
    typer.echo(f"Indexed {count} items.")


@app.command("backup")
def backup(destination: Path = typer.Argument(...)):
    path = create_backup(destination.resolve())
    typer.echo(f"Backup created: {path}")


@app.command("verify-backup")
def verify_backup_command(archive: Path = typer.Argument(...)):
    manifest = verify_backup(archive.resolve())
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
    engine.dispose()
    restore_backup(archive.resolve(), force=True)
    typer.echo("Backup restored. Restart all web and worker processes.")


if __name__ == "__main__":
    app()
