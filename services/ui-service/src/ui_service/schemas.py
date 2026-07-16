"""UI-owned models for the Backend public contract."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CheckResult(BaseModel):
    """Normalized check rendered by the UI."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    history_id: int
    ip_address: str
    ip_version: int
    is_public: bool
    is_whitelisted: bool | None
    abuse_confidence_score: int = Field(ge=0, le=100)
    country_code: str | None
    usage_type: str | None
    isp: str | None
    domain: str | None
    total_reports: int = Field(ge=0)
    num_distinct_users: int = Field(ge=0)
    last_reported_at: datetime | None
    max_age_days: int = Field(ge=1, le=365)
    source: str
    checked_at: datetime


class HistoryPage(BaseModel):
    """Recent persisted checks returned by Backend."""

    model_config = ConfigDict(extra="forbid")

    items: list[CheckResult]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    total: int = Field(ge=0)


class BackendErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str


class BackendErrorResponse(BaseModel):
    error: BackendErrorDetail
