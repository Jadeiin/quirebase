"""Render the effective Workspace capability bundle for human review."""

from __future__ import annotations

import argparse
from pathlib import Path

from quirebase.access import initialize_authorization
from quirebase.access.authorization import workspace_action_allowed
from quirebase.access.workspace_policy import ACTION_SPECS
from quirebase.models import WorkspaceRole

OUTPUT = Path(__file__).resolve().parents[1] / "docs/architecture/authorization-matrix.md"


def render() -> str:
    initialize_authorization()
    roles = tuple(WorkspaceRole)
    lines = [
        "# Effective Workspace capabilities",
        "",
        "Generated from the immutable Casbin bundle and action schema. Regenerate with",
        "`uv run python scripts/export-authorization-matrix.py`; CI checks this artifact.",
        "",
        "A = active Workspace, R = archived Workspace, F = administrative read-only freeze.",
        "A dash means denied in all three lifecycles. Each row uses a valid action relation;",
        "relations are internal request facts, rather than a public API policy language.",
        "",
        "This is capability policy for an already resolved active User/Workspace membership.",
        "Project participation, discoverability, target state, lineage and owner invariants remain",
        "domain rules; this table alone does not establish permission for a concrete command.",
        "",
        "| Resource action | Relation | " + " | ".join(role.value for role in roles) + " |",
        "| --- | --- | " + " | ".join("---" for _ in roles) + " |",
    ]
    for action, spec in sorted(ACTION_SPECS.items(), key=lambda entry: entry[0].value):
        for relation in sorted(spec.policy_relations):
            grants = [
                "/".join(
                    label
                    for label, lifecycle in (("A", "active"), ("R", "archived"), ("F", "frozen"))
                    if workspace_action_allowed(
                        role, action.resource, action.action, lifecycle, relation
                    )
                )
                or "—"
                for role in roles
            ]
            lines.append(f"| `{action.value}` | `{relation}` | " + " | ".join(grants) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Fail when the generated matrix has drifted"
    )
    args = parser.parse_args()
    rendered = render()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            parser.error("authorization matrix changed; regenerate and review its diff")
    else:
        OUTPUT.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
