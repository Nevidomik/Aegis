"""Pydantic contracts for Backend checks and History persistence."""

from datetime import datetime
from ipaddress import ip_address
from typing import Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

MAX_COUNT = 2_147_483_647


def normalize_public_ip(value: str) -> str:
    """Return a canonical public IP address or reject the value."""
    try:
        parsed = ip_address(value)
    except ValueError as error:
        raise ValueError("The value must be a valid IP address.") from error
    if (
        parsed.is_loopback
        or parsed.is_private
        or parsed.is_multicast
        or parsed.is_link_local
        or parsed.is_unspecified
        or not parsed.is_global
    ):
        raise ValueError("The IP address must be public.")
    return str(parsed)


def require_aware(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("Timestamps must include a timezone.")
    return value


class CheckRequest(BaseModel):
    """Public request to check one IP address."""

    model_config = ConfigDict(extra="forbid")

    ip_address: str = Field(min_length=1, max_length=100)
    max_age_days: int = Field(default=30, ge=1, le=365)


class ReputationResult(BaseModel):
    """Normalized provider result before persistence."""

    model_config = ConfigDict(extra="forbid")

    ip_address: StrictStr = Field(min_length=1, max_length=39)
    ip_version: Literal[4, 6]
    is_public: StrictBool
    is_whitelisted: StrictBool | None
    abuse_confidence_score: StrictInt = Field(ge=0, le=100)
    country_code: StrictStr | None = Field(default=None, min_length=2, max_length=2)
    usage_type: StrictStr | None = Field(default=None, max_length=100)
    isp: StrictStr | None = Field(default=None, max_length=255)
    domain: StrictStr | None = Field(default=None, max_length=255)
    total_reports: StrictInt = Field(ge=0, le=MAX_COUNT)
    num_distinct_users: StrictInt = Field(ge=0, le=MAX_COUNT)
    last_reported_at: datetime | None
    source: StrictStr = Field(min_length=1, max_length=32)

    @field_validator("ip_address")
    @classmethod
    def validate_ip_address(cls, value: str) -> str:
        return normalize_public_ip(value)

    @field_validator("last_reported_at")
    @classmethod
    def validate_last_reported_at(cls, value: datetime | None) -> datetime | None:
        return require_aware(value)

    @model_validator(mode="after")
    def validate_address_metadata(self) -> Self:
        if self.ip_version != ip_address(self.ip_address).version or not self.is_public:
            raise ValueError("IP address metadata is inconsistent.")
        return self


class HistoryCheckCreate(ReputationResult):
    """Normalized check sent to History."""

    request_id: UUID
    max_age_days: StrictInt = Field(ge=1, le=365)
    checked_at: datetime

    @field_validator("checked_at")
    @classmethod
    def validate_checked_at(cls, value: datetime) -> datetime:
        validated = require_aware(value)
        assert validated is not None
        return validated


class CheckResponse(HistoryCheckCreate):
    """Persisted check returned to the public caller."""

    history_id: StrictInt = Field(gt=0)


class HistoryListQuery(BaseModel):
    """Public pagination and optional IP filtering parameters."""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    ip_address: str | None = Field(default=None, min_length=1, max_length=100)


class HistoryListResponse(BaseModel):
    """One validated page returned by History."""

    model_config = ConfigDict(extra="forbid")

    items: list[CheckResponse]
    limit: StrictInt = Field(ge=1, le=100)
    offset: StrictInt = Field(ge=0, le=MAX_COUNT)
    total: StrictInt = Field(ge=0, le=MAX_COUNT)


class ReadinessResponse(BaseModel):
    """Validated readiness contract exposed by dependencies."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ready"]


class ErrorDetail(BaseModel):
    code: StrictStr = Field(min_length=1, max_length=64)
    message: StrictStr = Field(min_length=1, max_length=500)
    request_id: StrictStr = Field(min_length=1, max_length=36)


class ErrorResponse(BaseModel):
    error: ErrorDetail
