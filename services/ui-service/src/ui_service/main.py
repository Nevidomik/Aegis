"""FastAPI application for the Aegis UI service."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from ui_service.backend_client import BackendClient
from ui_service.config import Settings, get_settings
from ui_service.routes import router


def create_backend_http_client(settings: Settings) -> httpx.AsyncClient:
    """Create the Backend client owned by the UI application lifespan."""
    return httpx.AsyncClient(
        base_url=str(settings.backend_service_url).rstrip("/"),
        timeout=settings.backend_timeout_seconds,
        follow_redirects=False,
    )


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Open and close one reusable Backend HTTP client."""
    http_client = create_backend_http_client(get_settings())
    application.state.backend_client = BackendClient(http_client)
    try:
        yield
    finally:
        await http_client.aclose()


app = FastAPI(title="Aegis UI Service", lifespan=lifespan)
app.include_router(router)
