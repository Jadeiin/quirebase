from __future__ import annotations

import json
from pathlib import Path

import typer
import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text

from .config import get_settings
from .db import SessionLocal, engine
from .legacy_migration import migrate_legacy
from .maintenance import check_objects, create_backup, restore_backup, verify_backup
from .models import User
from .search import reindex_all
from .security import hash_password
from .worker import run_forever

app = typer.Typer(help="Quirebase administration")


@app.command("serve")
def serve(host: str = "127.0.0.1", port: int = 9060, reload: bool = False):
    uvicorn.run("quirebase.app:app", host=host, port=port, reload=reload)


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
    if not inspect(engine).has_table("users"):
        failures += 1
        typer.echo("[failed] schema is not initialized; run quirebase init-db")
    else:
        with SessionLocal() as db:
            object_errors = check_objects(db)
        if object_errors:
            failures += len(object_errors)
            for error in object_errors:
                typer.echo(f"[failed] object {error}")
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
    force: bool = typer.Option(False, "--force", help="Replace the configured database and objects"),
):
    if not force:
        raise typer.BadParameter("restore is destructive; inspect the target and pass --force")
    engine.dispose()
    restore_backup(archive.resolve(), force=True)
    typer.echo("Backup restored. Restart all web and worker processes.")


@app.command("migrate-legacy")
def migrate_legacy_command(
    database: Path = typer.Option(..., exists=True, dir_okay=False, readable=True),
    data_dir: Path = typer.Option(..., exists=True, file_okay=False, readable=True),
    owner: str = typer.Option(..., help="Existing account that will own imported records"),
    commit: bool = typer.Option(False, "--commit", help="Write after the default read-only preflight"),
    report: Path | None = typer.Option(None, help="Write the JSON migration report here"),
):
    with SessionLocal() as db:
        account = db.scalar(select(User).where(User.username == owner))
        if account is None:
            raise typer.BadParameter("owner account does not exist")
        result = migrate_legacy(db, database.resolve(), data_dir.resolve(), account, commit=commit)
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    if report:
        report.write_text(rendered + "\n", encoding="utf-8")
    typer.echo(rendered)


if __name__ == "__main__":
    app()
