"""Server-rendered routes for the Aegis UI."""

from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ui_service.application_client import (
    ApplicationClient,
    ApplicationClientError,
    get_application_client,
)
from ui_service.schemas import CheckResult, HistoryPage

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def request_id_for(request: Request) -> str:
    supplied = request.headers.get("X-Request-ID")
    if supplied is not None:
        try:
            return str(UUID(supplied))
        except ValueError:
            pass
    return str(uuid4())


async def load_history(
    application_client: ApplicationClient, request_id: str
) -> tuple[HistoryPage | None, str | None]:
    try:
        return await application_client.recent_history(request_id=request_id), None
    except ApplicationClientError as error:
        return None, str(error)


def render_page(
    request: Request,
    *,
    request_id: str,
    ip_address: str = "",
    max_age_days: str = "30",
    result: CheckResult | None = None,
    error: str | None = None,
    history: HistoryPage | None = None,
    history_error: str | None = None,
) -> HTMLResponse:
    response = templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "ip_address": ip_address,
            "max_age_days": max_age_days,
            "result": result,
            "error": error,
            "history": history,
            "history_error": history_error,
        },
    )
    response.headers["X-Request-ID"] = request_id
    return response


@router.get("/health/live", tags=["health"])
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", tags=["health"], response_model=None)
async def readiness(
    request: Request,
    application_client: Annotated[ApplicationClient, Depends(get_application_client)],
) -> dict[str, str] | JSONResponse:
    request_id = request_id_for(request)
    try:
        await application_client.ready(request_id=request_id)
    except ApplicationClientError:
        response = JSONResponse(status_code=503, content={"status": "not ready"})
    else:
        response = JSONResponse(content={"status": "ready"})
    response.headers["X-Request-ID"] = request_id
    return response


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index(
    request: Request,
    application_client: Annotated[ApplicationClient, Depends(get_application_client)],
) -> HTMLResponse:
    request_id = request_id_for(request)
    history, history_error = await load_history(application_client, request_id)
    return render_page(
        request,
        request_id=request_id,
        history=history,
        history_error=history_error,
    )


@router.post("/", response_class=HTMLResponse, include_in_schema=False)
async def submit_check(
    request: Request,
    application_client: Annotated[ApplicationClient, Depends(get_application_client)],
    ip_address: Annotated[str, Form()] = "",
    max_age_days: Annotated[str, Form()] = "30",
) -> HTMLResponse:
    request_id = request_id_for(request)
    result = None
    error = None

    if not ip_address.strip():
        error = "Enter an IPv4 or IPv6 address."
    else:
        try:
            parsed_max_age = int(max_age_days)
            if not 1 <= parsed_max_age <= 365:
                raise ValueError
        except ValueError:
            error = "Max age must be a whole number between 1 and 365."
        else:
            try:
                result = await application_client.check(
                    ip_address=ip_address.strip(),
                    max_age_days=parsed_max_age,
                    request_id=request_id,
                )
            except ApplicationClientError as application_error:
                error = str(application_error)

    history, history_error = await load_history(application_client, request_id)
    return render_page(
        request,
        request_id=request_id,
        ip_address=ip_address,
        max_age_days=max_age_days,
        result=result,
        error=error,
        history=history,
        history_error=history_error,
    )
