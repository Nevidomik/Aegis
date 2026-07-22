"""FastAPI application for the Aegis UI service."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from ui_service.application_client import ApplicationClient
from ui_service.config import Settings, get_settings
from ui_service.routes import (
    request_logging_middleware,
    router,
    unexpected_exception_handler,
)


def create_history_http_client(settings: Settings) -> httpx.AsyncClient:
    """Create the History client owned by the UI application lifespan."""
    return httpx.AsyncClient(
        base_url=str(settings.history_service_url).rstrip("/"),
        timeout=httpx.Timeout(
            connect=settings.history_connect_timeout_seconds,
            read=settings.history_read_timeout_seconds,
            write=settings.history_write_timeout_seconds,
            pool=settings.history_pool_timeout_seconds,
        ),
        follow_redirects=False,
    )


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Open and close one reusable History HTTP client."""
    settings = get_settings()
    http_client = create_history_http_client(settings)
    application.state.application_client = ApplicationClient(
        http_client,
        operation_timeout_seconds=settings.history_operation_timeout_seconds,
    )
    try:
        yield
    finally:
        await http_client.aclose()


app = FastAPI(title="Aegis UI Service", lifespan=lifespan, debug=False)
app.middleware("http")(request_logging_middleware)
app.add_exception_handler(Exception, unexpected_exception_handler)
app.include_router(router)
