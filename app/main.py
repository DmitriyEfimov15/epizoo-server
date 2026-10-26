import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import farms, internal, public
from app.core.config import Settings
from app.core.logging import configure_logging
from app.db.session import make_engine, session_factory
from app.schemas.api import ErrorOut
from app.services.summaries import configured_provider


@asynccontextmanager
async def lifespan(app):
    configure_logging()
    yield
    await app.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(
        title="Мониторинг эпизоотической ситуации",
        version="0.1.0",
        lifespan=lifespan,
        description=(
            "Справочный сервис по сообщениям ветслужб и СМИ. Отсутствие данных не "
            "подтверждает отсутствие заболевания."
        ),
        responses={401: {"model": ErrorOut}, 404: {"model": ErrorOut}, 422: {"model": ErrorOut}},
    )
    app.state.settings = settings
    app.state.summary_provider = configured_provider(settings)
    app.state.engine = make_engine(settings.database_url)
    app.state.session_factory = session_factory(app.state.engine)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-API-Key"],
    )
    for router in (public.router, farms.router, internal.router):
        app.include_router(router, prefix="/api/v1")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: HTTPException):
        body = (
            error.detail
            if isinstance(error.detail, dict)
            else {"code": "http_error", "message": str(error.detail)}
        )
        return JSONResponse(body, status_code=error.status_code, headers=error.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        # Не возвращаем вход целиком: он может содержать токены/секреты.
        fields = ", ".join(".".join(str(part) for part in item["loc"]) for item in error.errors())
        return JSONResponse(
            {"code": "validation_error", "message": f"Некорректные параметры: {fields}"},
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception):
        logging.getLogger(__name__).error("Ошибка обработки запроса: %s", type(error).__name__)
        return JSONResponse(
            {"code": "internal_error", "message": "Внутренняя ошибка сервиса"}, status_code=500
        )

    @app.get("/health")
    async def health():
        async with app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok"}

    return app


app = create_app()
