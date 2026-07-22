"""FastAPI application for the Aegis history service."""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from history_service.blacklist_scheduler import BlacklistScheduler
from history_service.blacklist_sync import create_blacklist_sync_service
from history_service.config import Settings, get_settings
from history_service.database import get_session_factory
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

logger = logging.getLogger(__name__)
SchedulerFactory = Callable[[Settings, ProviderClient], BlacklistScheduler]


def create_provider_http_client(settings: Settings) -> httpx.Client:
    """Create History's reusable client for the internal Provider API."""
    return httpx.Client(
        base_url=str(settings.provider_service_url).rstrip("/"),
        timeout=settings.provider_timeout_seconds,
        follow_redirects=False,
    )


def create_blacklist_scheduler(
    settings: Settings, provider: ProviderClient
) -> BlacklistScheduler:
    """Build the scheduler without starting its recurring loop."""
    return BlacklistScheduler(
        sync_service=create_blacklist_sync_service(settings),
        provider=provider,
        session_factory=get_session_factory(),
    )


@asynccontextmanager
async def managed_lifespan(
    application: FastAPI,
    settings: Settings,
    scheduler_factory: SchedulerFactory,
) -> AsyncIterator[None]:
    """Own the Provider client and optional scheduler task."""
    http_client = create_provider_http_client(settings)
    application.state.provider_client = ProviderClient(http_client)
    stop_event: asyncio.Event | None = None
    scheduler_task: asyncio.Task[None] | None = None
    if settings.blacklist_scheduler_enabled:
        stop_event = asyncio.Event()
        scheduler = scheduler_factory(settings, application.state.provider_client)
        scheduler_task = asyncio.create_task(
            scheduler.run(stop_event), name="history-blacklist-scheduler"
        )
        application.state.blacklist_scheduler_task = scheduler_task
        application.state.blacklist_scheduler_stop_event = stop_event
    else:
        logger.info("blacklist_scheduler_disabled")
    try:
        yield
    finally:
        if stop_event is not None:
            logger.info("blacklist_scheduler_stopping")
            stop_event.set()
        try:
            if scheduler_task is not None:
                await scheduler_task
        finally:
            http_client.close()


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Use environment-backed dependencies for the default application."""
    async with managed_lifespan(
        application, get_settings(), create_blacklist_scheduler
    ):
        yield


def create_app(
    *,
    settings: Settings | None = None,
    scheduler_factory: SchedulerFactory | None = None,
) -> FastAPI:
    """Create an independently configured History application."""
    if settings is None and scheduler_factory is None:
        selected_lifespan = lifespan
    else:
        configured = settings or get_settings()
        factory = scheduler_factory or create_blacklist_scheduler

        @asynccontextmanager
        async def selected_lifespan(application: FastAPI) -> AsyncIterator[None]:
            async with managed_lifespan(application, configured, factory):
                yield

    application = FastAPI(title="Aegis History Service", lifespan=selected_lifespan)
    application.middleware("http")(request_id_middleware)
    application.add_exception_handler(ApplicationError, application_exception_handler)
    application.add_exception_handler(
        RequestValidationError, validation_exception_handler
    )
    application.add_exception_handler(
        HistoryUnavailableError, unavailable_exception_handler
    )
    application.add_exception_handler(
        IdempotencyConflictError, idempotency_conflict_exception_handler
    )
    application.include_router(router)
    return application


app = create_app()
