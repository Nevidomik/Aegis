"""FastAPI application for the Aegis history service."""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from history_service.routes import (
    idempotency_conflict_exception_handler,
    request_id_middleware,
    router,
    unavailable_exception_handler,
    validation_exception_handler,
)
from history_service.service import HistoryUnavailableError, IdempotencyConflictError

app = FastAPI(title="Aegis History Service")
app.middleware("http")(request_id_middleware)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HistoryUnavailableError, unavailable_exception_handler)
app.add_exception_handler(
    IdempotencyConflictError, idempotency_conflict_exception_handler
)
app.include_router(router)
