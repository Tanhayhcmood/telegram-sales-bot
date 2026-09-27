from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.core.security import verify_api_key
from typing import Annotated

DBSession = Annotated[AsyncSession, Depends(get_db)]
APIKeyDep = Annotated[str, Depends(verify_api_key)]
