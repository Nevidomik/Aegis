"""FastAPI application for the Aegis UI service."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from ui_service.application_client import ApplicationClient
from ui_service.config import Settings, get_settings
from ui_service.routes import router


def create_history_http_client(settings: Settings) -> httpx.AsyncClient:
    """Create the History client owned by the UI application lifespan."""
    return httpx.AsyncClient(
        base_url=str(settings.history_service_url).rstrip("/"),
        timeout=settings.history_timeout_seconds,
        follow_redirects=False,
    )


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Open and close one reusable History HTTP client."""
    http_client = create_history_http_client(get_settings())
    application.state.application_client = ApplicationClient(http_client)
    try:
        yield
    finally:
        await http_client.aclose()


app = FastAPI(title="Aegis UI Service", lifespan=lifespan)
app.include_router(router)
