from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from quirebase.access import WorkspaceContext, resolve_workspace_context
from quirebase.core.database import get_db
from quirebase.models import User
from quirebase.web.api.auth import current_api_user

ApiUser = Annotated[User, Depends(current_api_user)]
Database = Annotated[AsyncSession, Depends(get_db)]


async def current_api_workspace(
    workspace_id: str,
    user: ApiUser,
    db: Database,
) -> WorkspaceContext:
    return await resolve_workspace_context(db, user, workspace_id)


WorkspaceAccess = Annotated[WorkspaceContext, Depends(current_api_workspace)]
