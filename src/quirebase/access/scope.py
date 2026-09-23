"""Explicit Workspace lineage primitives."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, select

if TYPE_CHECKING:
    from quirebase.access.workspaces import WorkspaceContext


def workspace_select(model: Any, ctx: WorkspaceContext) -> Select[Any]:
    """Select rows belonging to the context's Workspace.

    This helper intentionally does not perform membership, capability, or
    Project visibility checks.  Those belong to the Access/domain boundary.
    """

    return select(model).where(model.workspace_id == ctx.workspace_id)


def workspace_id_predicate(model: Any, ctx: WorkspaceContext) -> Any:
    """Return the explicit lineage predicate for mutation statements."""

    return model.workspace_id == ctx.workspace_id
