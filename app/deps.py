from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, Request, status

from app.database import (
    AdminUser,
    Base,
    create_db_engine,
    create_session_factory,
    upgrade_legacy_sqlite_schema,
)
from app.services import RegistrationService


async def get_service(request: Request) -> AsyncGenerator[RegistrationService, None]:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        engine = create_db_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(upgrade_legacy_sqlite_schema)
        request.app.state.engine = engine
        request.app.state.session_factory = create_session_factory(engine)
    session_factory = request.app.state.session_factory
    service = RegistrationService(session_factory)
    yield service
    await service.close()


async def get_admin_user(
    request: Request,
    service: RegistrationService = Depends(get_service),
) -> AdminUser:
    authorization = request.headers.get("Authorization", "")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin token required")

    token = authorization.split(" ", 1)[1].strip()
    try:
        admin = await service.validate_admin_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return admin
