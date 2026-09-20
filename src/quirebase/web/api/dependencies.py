from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from quirebase.core.database import get_db
from quirebase.models import User
from quirebase.web.api.auth import current_api_user

ApiUser = Annotated[User, Depends(current_api_user)]
Database = Annotated[AsyncSession, Depends(get_db)]
