"""UI-owned models for the Backend public contract."""

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


class CheckResult(BaseModel):
    """Normalized check rendered by the UI."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    history_id: StrictInt = Field(gt=0)
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
    max_age_days: StrictInt = Field(ge=1, le=365)
    source: StrictStr = Field(min_length=1, max_length=32)
    checked_at: datetime

    @field_validator("ip_address")
    @classmethod
    def validate_ip_address(cls, value: str) -> str:
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

    @field_validator("last_reported_at", "checked_at")
    @classmethod
    def validate_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Timestamps must include a timezone.")
        return value

    @model_validator(mode="after")
    def validate_address_metadata(self) -> Self:
        if self.ip_version != ip_address(self.ip_address).version or not self.is_public:
            raise ValueError("IP address metadata is inconsistent.")
        return self


class HistoryPage(BaseModel):
    """Recent persisted checks returned by Backend."""

    model_config = ConfigDict(extra="forbid")

    items: list[CheckResult]
    limit: StrictInt = Field(ge=1, le=100)
    offset: StrictInt = Field(ge=0, le=MAX_COUNT)
    total: StrictInt = Field(ge=0, le=MAX_COUNT)


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready"]


class BackendErrorDetail(BaseModel):
    code: StrictStr = Field(min_length=1, max_length=64)
    message: StrictStr = Field(min_length=1, max_length=500)
    request_id: StrictStr = Field(min_length=1, max_length=36)


class BackendErrorResponse(BaseModel):
    error: BackendErrorDetail
