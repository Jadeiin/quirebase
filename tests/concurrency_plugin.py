"""Report executed concurrency schedules and attach bounded failure evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from concurrency_helpers import PostgresRace

CASES = json.loads(Path(__file__).with_name("concurrency_cases.json").read_text())
REPORTS = pytest.StashKey[dict]()


def pytest_addoption(parser):
    parser.addoption(
        "--concurrency-report-dir", help="Write concurrency coverage and failure evidence"
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "concurrency_case(id): invariant in concurrency_cases.json")
    destination = config.getoption("concurrency_report_dir")
    if destination and not hasattr(config, "workerinput"):
        config.pluginmanager.register(ConcurrencyReport(Path(destination)), "concurrency-report")


def pytest_collection_modifyitems(items):
    known = {case["id"] for case in CASES}
    for item in items:
        marker = item.get_closest_marker("concurrency_case")
        if marker and (len(marker.args) != 1 or marker.args[0] not in known):
            raise pytest.UsageError(f"Unknown concurrency case on {item.nodeid}: {marker.args}")


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    item.stash.setdefault(REPORTS, {})[report.when] = report
    marker = item.get_closest_marker("concurrency_case")
    if marker:
        report.user_properties.extend([
            ("concurrency_case", marker.args[0]),
            ("concurrency_evidence", "postgres_race" in item.fixturenames),
        ])
    return report


@pytest.fixture
async def postgres_race(postgres_sessions, request, tmp_path):
    destination = request.config.getoption("concurrency_report_dir")
    evidence_dir = (Path(destination) if destination else tmp_path) / "failures"
    race = PostgresRace(postgres_sessions, node_id=request.node.nodeid, evidence_dir=evidence_dir)
    yield race
    failed = any(report.failed for report in request.node.stash.get(REPORTS, {}).values())
    try:
        if failed and race.evidence_path is None:
            await race.capture(AssertionError("Test failed"))
        await race.close(failed=failed)
    finally:
        if race.evidence_path:
            request.node.add_report_section(
                "teardown", "concurrency evidence", str(race.evidence_path)
            )


class ConcurrencyReport:
    def __init__(self, destination: Path):
        self.destination = destination
        self.runs: dict[str, dict] = {}

    def pytest_runtest_logreport(self, report):
        properties = dict(report.user_properties)
        case_id = properties.get("concurrency_case")
        if not case_id:
            return
        run = self.runs.setdefault(
            report.nodeid,
            {
                "node_id": report.nodeid,
                "case": case_id,
                "outcome": "not_run",
                "evidence_enabled": properties["concurrency_evidence"],
            },
        )
        if report.failed:
            run["outcome"] = "failed"
        elif run["outcome"] != "failed" and (report.when == "call" or report.skipped):
            run["outcome"] = report.outcome

    def pytest_sessionfinish(self, session, exitstatus):
        cases = []
        lines = [
            "# Concurrency coverage",
            "",
            f"Pytest exit status: {int(exitstatus)}",
            "",
            "Only executed node IDs describe covered schedules; skipped cases are not coverage.",
            "Evidence is enabled only for tests using postgres_race.",
            "",
            "| Case | Status | Passed | Failed | Skipped |",
            "| --- | --- | --- | --- | --- |",
        ]
        for definition in CASES:
            runs = sorted(
                (run for run in self.runs.values() if run["case"] == definition["id"]),
                key=lambda run: run["node_id"],
            )
            outcomes = [run["outcome"] for run in runs]
            status = next(
                (value for value in ("failed", "skipped", "passed") if value in outcomes), "not_run"
            )
            cases.append({**definition, "status": status, "runs": runs})
            lines.append(
                f"| {definition['id']} | {status} | {outcomes.count('passed')} | "
                f"{outcomes.count('failed')} | {outcomes.count('skipped')} |"
            )
        for case in cases:
            lines.extend([
                "",
                f"## {case['id']}",
                "",
                case["invariant"],
                "",
                "Operations: " + ", ".join(case["operations"]),
                "",
            ])
            lines.extend(
                f"- {run['outcome']}: `{run['node_id']}` (evidence: {run['evidence_enabled']})"
                for run in case["runs"]
            )
        self.destination.mkdir(parents=True, exist_ok=True)
        (self.destination / "coverage.json").write_text(
            json.dumps({"exit_status": int(exitstatus), "cases": cases}, indent=2) + "\n"
        )
        (self.destination / "coverage.md").write_text("\n".join(lines) + "\n")
