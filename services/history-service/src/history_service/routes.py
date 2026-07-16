"""HTTP routes and error mapping for the History service."""

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from history_service.database import get_session
from history_service.schemas import (
    CheckCreate,
    ErrorDetail,
    ErrorResponse,
    HistoryList,
    HistoryListQuery,
    HistoryRecord,
)
from history_service.service import (
    HistoryService,
    HistoryUnavailableError,
    IdempotencyConflictError,
    get_history_service,
)

router = APIRouter()


def request_id_from(request: Request) -> str:
    """Return the request ID established by middleware."""
    return str(getattr(request.state, "request_id", uuid4()))


def error_response(
    *, status_code: int, code: str, message: str, request_id: str
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorDetail(code=code, message=message, request_id=request_id)
    )
    return JSONResponse(status_code=status_code, content=body.model_dump())


async def request_id_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    supplied_request_id = request.headers.get("X-Request-ID")
    if supplied_request_id is None:
        request_id = uuid4()
    else:
        try:
            request_id = UUID(supplied_request_id)
        except ValueError:
            generated_request_id = str(uuid4())
            response = error_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                code="INVALID_REQUEST_ID",
                message="X-Request-ID must be a valid UUID.",
                request_id=generated_request_id,
            )
            response.headers["X-Request-ID"] = generated_request_id
            return response

    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = str(request_id)
    return response


@router.get("/health/live", tags=["health"])
async def liveness() -> dict[str, str]:
    """Confirm that the History service process is running."""
    return {"status": "ok"}


@router.get("/health/ready", tags=["health"], response_model=None)
def readiness(
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str] | JSONResponse:
    """Confirm that the service can execute a minimal database query."""
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not ready"},
        )
    return {"status": "ready"}


@router.post(
    "/internal/v1/checks",
    response_model=HistoryRecord,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}},
    tags=["history"],
)
def create_check(
    payload: CheckCreate,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[HistoryService, Depends(get_history_service)],
) -> HistoryRecord:
    result = service.create(session, payload)
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return HistoryRecord.from_record(result.record)


@router.get(
    "/internal/v1/checks",
    response_model=HistoryList,
    tags=["history"],
)
def list_checks(
    query: Annotated[HistoryListQuery, Query()],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[HistoryService, Depends(get_history_service)],
) -> HistoryList:
    result = service.list(session, query)
    return HistoryList(
        items=[HistoryRecord.from_record(record) for record in result.records],
        limit=query.limit,
        offset=query.offset,
        total=result.total,
    )


@router.get(
    "/internal/v1/checks/{history_id}",
    response_model=HistoryRecord,
    responses={404: {"model": ErrorResponse}},
    tags=["history"],
)
def get_check(
    history_id: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[HistoryService, Depends(get_history_service)],
) -> HistoryRecord | JSONResponse:
    record = service.get(session, history_id)
    if record is None:
        return error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code="HISTORY_RECORD_NOT_FOUND",
            message="The requested history record does not exist.",
            request_id=request_id_from(request),
        )
    return HistoryRecord.from_record(record)


async def validation_exception_handler(
    request: Request, _: RequestValidationError
) -> JSONResponse:
    """Return validation failures without exposing implementation details."""
    return error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="INVALID_REQUEST",
        message="The request did not satisfy the API contract.",
        request_id=request_id_from(request),
    )


async def unavailable_exception_handler(
    request: Request, _: HistoryUnavailableError
) -> JSONResponse:
    """Hide database error details from callers."""
    return error_response(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        code="HISTORY_UNAVAILABLE",
        message="History storage is temporarily unavailable.",
        request_id=request_id_from(request),
    )


async def idempotency_conflict_exception_handler(
    request: Request, _: IdempotencyConflictError
) -> JSONResponse:
    """Return a stable conflict when one idempotency key changes meaning."""
    return error_response(
        status_code=status.HTTP_409_CONFLICT,
        code="IDEMPOTENCY_CONFLICT",
        message="The request ID was already used with different check data.",
        request_id=request_id_from(request),
    )
