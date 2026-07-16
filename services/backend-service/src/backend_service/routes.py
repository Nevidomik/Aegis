"""Thin HTTP routing and public error mapping for Backend."""

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend_service.exceptions import ApplicationError
from backend_service.history_client import HistoryClient, get_history_client
from backend_service.provider import AbuseIPDBProvider, get_reputation_provider
from backend_service.schemas import (
    CheckRequest,
    CheckResponse,
    ErrorDetail,
    ErrorResponse,
)
from backend_service.service import CheckService, get_check_service

router = APIRouter()


def error_response(
    *, status_code: int, code: str, message: str, request_id: str
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorDetail(code=code, message=message, request_id=request_id)
    )
    return JSONResponse(status_code=status_code, content=body.model_dump())


def current_request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", uuid4()))


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
    """Confirm that the Backend process is running."""
    return {"status": "ok"}


@router.post(
    "/api/v1/checks",
    response_model=CheckResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    tags=["checks"],
)
async def create_check(
    payload: CheckRequest,
    request: Request,
    service: Annotated[CheckService, Depends(get_check_service)],
    provider: Annotated[AbuseIPDBProvider, Depends(get_reputation_provider)],
    history_client: Annotated[HistoryClient, Depends(get_history_client)],
) -> CheckResponse:
    return await service.check(
        payload,
        request.state.request_id,
        provider,
        history_client,
    )


async def application_exception_handler(
    request: Request, error: ApplicationError
) -> JSONResponse:
    return error_response(
        status_code=error.status_code,
        code=error.code,
        message=error.message,
        request_id=current_request_id(request),
    )


async def validation_exception_handler(
    request: Request, _: RequestValidationError
) -> JSONResponse:
    return error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="INVALID_REQUEST",
        message="The request did not satisfy the API contract.",
        request_id=current_request_id(request),
    )
