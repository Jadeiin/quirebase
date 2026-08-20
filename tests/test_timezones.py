from __future__ import annotations

import tomllib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from quirebase.core import timezones

ROOT = Path(__file__).parents[1]


def test_runtime_dependencies_supply_cross_platform_timezone_data():
    with (ROOT / "pyproject.toml").open("rb") as pyproject:
        dependencies = tomllib.load(pyproject)["project"]["dependencies"]

    tzdata = next(dependency for dependency in dependencies if dependency.startswith("tzdata"))
    assert "sys_platform == 'win32'" in tzdata
    assert any(dependency.startswith("tzlocal") for dependency in dependencies)


def test_server_timezone_preserves_dst_rules(monkeypatch):
    local_zone = ZoneInfo("America/New_York")
    monkeypatch.setattr(timezones, "get_localzone", lambda: local_zone)

    resolved = timezones.server_timezone()

    assert datetime(2025, 1, 1, tzinfo=resolved).utcoffset().total_seconds() == -5 * 60 * 60
    assert datetime(2025, 7, 1, tzinfo=resolved).utcoffset().total_seconds() == -4 * 60 * 60


def test_invalid_annotation_timezone_falls_back_to_server_zone(monkeypatch):
    local_zone = ZoneInfo("Europe/Berlin")
    monkeypatch.setattr(timezones, "get_localzone", lambda: local_zone)

    assert timezones.annotation_export_timezone("not/a-zone") is local_zone
