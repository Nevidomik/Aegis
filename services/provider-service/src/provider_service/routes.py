"""Thin HTTP routing and public error mapping for Provider."""

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from provider_service.exceptions import ApplicationError
from provider_service.provider import AbuseIPDBProvider, get_reputation_provider
from provider_service.schemas import (
    ErrorDetail,
    ErrorResponse,
    InternalReputationRequest,
    InternalReputationResponse,
)
from provider_service.service import (
    ReputationProxyService,
    get_reputation_proxy_service,
)

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
    """Confirm that the Provider process is running."""
    return {"status": "ok"}


@router.get("/health/ready", tags=["health"])
async def readiness() -> dict[str, str]:
    """Confirm that Provider initialized with its required configuration."""
    return {"status": "ready"}


@router.post(
    "/internal/v1/reputation-checks",
    response_model=InternalReputationResponse,
    status_code=status.HTTP_200_OK,
    responses={
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
    tags=["internal-reputation"],
)
async def create_internal_reputation_check(
    payload: InternalReputationRequest,
    service: Annotated[ReputationProxyService, Depends(get_reputation_proxy_service)],
    provider: Annotated[AbuseIPDBProvider, Depends(get_reputation_provider)],
) -> InternalReputationResponse:
    """Return a validated provider result without persistence or idempotency."""
    return await service.check(payload, provider)


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
