"""FastAPI application for the Aegis history service."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from history_service.config import Settings, get_settings
from history_service.exceptions import ApplicationError
from history_service.provider_client import ProviderClient
from history_service.routes import (
    application_exception_handler,
    idempotency_conflict_exception_handler,
    request_id_middleware,
    router,
    unavailable_exception_handler,
    validation_exception_handler,
)
from history_service.service import HistoryUnavailableError, IdempotencyConflictError


def create_provider_http_client(settings: Settings) -> httpx.Client:
    """Create History's reusable client for the internal Provider API."""
    return httpx.Client(
        base_url=str(settings.provider_service_url).rstrip("/"),
        timeout=settings.provider_timeout_seconds,
        follow_redirects=False,
    )


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Open and close the Provider client exactly once."""
    http_client = create_provider_http_client(get_settings())
    application.state.provider_client = ProviderClient(http_client)
    try:
        yield
    finally:
        http_client.close()


app = FastAPI(title="Aegis History Service", lifespan=lifespan)
app.middleware("http")(request_id_middleware)
app.add_exception_handler(ApplicationError, application_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HistoryUnavailableError, unavailable_exception_handler)
app.add_exception_handler(
    IdempotencyConflictError, idempotency_conflict_exception_handler
)
app.include_router(router)
