"""Real process death and same-version DBOS replay on isolated databases."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from quirebase.core.database import async_database_url

DRIVER = Path(__file__).with_name("durable_recovery_driver.py")


@pytest.fixture(params=["sqlite", "postgres"])
def recovery_database(request, tmp_path):
    if request.param == "sqlite":
        yield f"sqlite:///{tmp_path / 'recovery.db'}"
        return
    configured = os.getenv("QUIREBASE_TEST_POSTGRES_URL")
    if not configured:
        pytest.skip("PostgreSQL is not configured")
    url = make_url(async_database_url(configured)).set(drivername="postgresql+psycopg")
    name = f"quirebase_recovery_{uuid4().hex}"
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(
                text(f"CREATE DATABASE \"{name}\" TEMPLATE template0 ENCODING 'UTF8'")
            )
        yield url.set(database=name, drivername="postgresql").render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def run_command(arguments, environment):
    result = subprocess.run(
        [sys.executable, *map(str, arguments)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def kill_at_marker(mode, marker, directory, environment):
    log = directory / f"{mode}.log"
    with log.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            [sys.executable, str(DRIVER), mode, str(directory)],
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 60
            while not marker.exists():
                assert process.poll() is None, log.read_text(encoding="utf-8")
                assert time.monotonic() < deadline, log.read_text(encoding="utf-8")
                time.sleep(0.05)
            if mode == "worker":
                state = json.loads((directory / "state.json").read_text(encoding="utf-8"))
                url = make_url(async_database_url(environment["QUIREBASE_DATABASE_URL"]))
                url = url.set(
                    drivername="sqlite"
                    if url.get_backend_name() == "sqlite"
                    else "postgresql+psycopg"
                )
                database = create_engine(url)
                prefix = "" if url.get_backend_name() == "sqlite" else "dbos."
                try:
                    with database.connect() as connection:
                        # Two completed database checks precede the paused second Provider call.
                        checkpoints = connection.scalar(
                            text(
                                f"SELECT count(*) FROM {prefix}datasource_outputs WHERE workflow_id = :id"
                            ),
                            {"id": state["workflow_id"]},
                        )
                        assert checkpoints == 2
                        status = connection.execute(
                            text(
                                f"SELECT status, executor_id FROM {prefix}workflow_status WHERE workflow_uuid = :id"
                            ),
                            {"id": state["workflow_id"]},
                        ).one()
                        assert tuple(status) == ("PENDING", "persistence-recovery-worker")
                finally:
                    database.dispose()
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=15)


def test_pdf_import_replays_checkpoints_and_lost_confirmation_response(recovery_database, tmp_path):
    environment = os.environ | {
        "QUIREBASE_DATABASE_URL": recovery_database,
        "QUIREBASE_DATA_DIR": str(tmp_path / "data"),
        "QUIREBASE_OBJECT_STORE": "local",
        "QUIREBASE_WORKFLOW_EXECUTOR_ID": "persistence-recovery-worker",
        "QUIREBASE_LOG_LEVEL": "WARNING",
        "QUIREBASE_RECOMMENDATION_ENGINE": "yake",
        "PYTHONIOENCODING": "utf-8",
    }
    run_command(["-c", "from quirebase.cli import app; app()", "init-db"], environment)
    run_command([DRIVER, "stage", tmp_path], environment)
    kill_at_marker("worker", tmp_path / "checkpoint-reached", tmp_path, environment)
    run_command([DRIVER, "change-descriptor", tmp_path], environment)
    run_command([DRIVER, "recover", tmp_path], environment)
    run_command([DRIVER, "preview", tmp_path], environment)
    extractions = [
        json.loads(line)
        for line in (tmp_path / "extractions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [value["original_name"] for value in extractions] == [
        "uploaded-kept.pdf",
        "uploaded-rejected.pdf",
    ]
    kill_at_marker("confirm-crash", tmp_path / "confirmation-committed", tmp_path, environment)
    run_command([DRIVER, "confirm-replay", tmp_path], environment)
    run_command([DRIVER, "finish", tmp_path], environment)
