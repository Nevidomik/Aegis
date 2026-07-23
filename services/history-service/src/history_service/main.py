"""FastAPI application for the Aegis history service."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.types import ExceptionHandler

from history_service.config import Settings, get_settings
from history_service.exceptions import ApplicationError
from history_service.provider_client import ProviderClient
from history_service.routes import (
    application_exception_handler,
    idempotency_conflict_exception_handler,
    request_id_middleware,
    router,
    unavailable_exception_handler,
    unexpected_exception_handler,
    validation_exception_handler,
)
from history_service.service import HistoryUnavailableError, IdempotencyConflictError


def create_provider_http_client(settings: Settings) -> httpx.Client:
    """Create History's reusable client for the internal Provider API."""
    return httpx.Client(
        base_url=str(settings.provider_service_url).rstrip("/"),
        timeout=httpx.Timeout(
            connect=settings.provider_connect_timeout_seconds,
            read=settings.provider_read_timeout_seconds,
            write=settings.provider_write_timeout_seconds,
            pool=settings.provider_pool_timeout_seconds,
        ),
        follow_redirects=False,
    )


@asynccontextmanager
async def managed_lifespan(
    application: FastAPI,
    settings: Settings,
) -> AsyncIterator[None]:
    """Own only the Provider client used for manual reputation lookups."""
    http_client = create_provider_http_client(settings)
    application.state.provider_client = ProviderClient(http_client)
    try:
        yield
    finally:
        http_client.close()


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Use environment-backed dependencies for the default application."""
    async with managed_lifespan(application, get_settings()):
        yield


def create_app(
    *,
    settings: Settings | None = None,
) -> FastAPI:
    """Create an independently configured History application."""
    if settings is None:
        selected_lifespan = lifespan
    else:
        configured = settings

        @asynccontextmanager
        async def selected_lifespan(application: FastAPI) -> AsyncIterator[None]:
            async with managed_lifespan(application, configured):
                yield

    application = FastAPI(
        title="Aegis History Service", lifespan=selected_lifespan, debug=False
    )
    application.middleware("http")(request_id_middleware)
    application.add_exception_handler(
        ApplicationError, cast(ExceptionHandler, application_exception_handler)
    )
    application.add_exception_handler(
        RequestValidationError, cast(ExceptionHandler, validation_exception_handler)
    )
    application.add_exception_handler(
        HistoryUnavailableError, cast(ExceptionHandler, unavailable_exception_handler)
    )
    application.add_exception_handler(
        IdempotencyConflictError,
        cast(ExceptionHandler, idempotency_conflict_exception_handler),
    )
    application.add_exception_handler(Exception, unexpected_exception_handler)
    application.include_router(router)
    return application


app = create_app()
