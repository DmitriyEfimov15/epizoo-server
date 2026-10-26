import secrets
from typing import Annotated

from fastapi import Header, HTTPException, Request


async def require_api_key(request: Request, x_api_key: Annotated[str | None, Header()] = None):
    expected = request.app.state.settings.api_key
    if not expected or not x_api_key or not secrets.compare_digest(expected, x_api_key):
        raise HTTPException(
            401, detail={"code": "unauthorized", "message": "Требуется корректный X-API-Key"}
        )
