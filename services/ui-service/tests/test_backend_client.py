from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from ui_service.backend_client import BackendClient, BackendClientError
from ui_service.schemas import CheckResult


def valid_result() -> dict[str, object]:
    return CheckResult(
        request_id=UUID("6f5aa064-43e8-4dbb-a544-d60b68af5cbd"),
        history_id=145,
        ip_address="8.8.8.8",
        ip_version=4,
        is_public=True,
        is_whitelisted=None,
        abuse_confidence_score=12,
        country_code="US",
        usage_type=None,
        isp="Example ISP",
        domain=None,
        total_reports=7,
        num_distinct_users=3,
        last_reported_at=None,
        max_age_days=30,
        source="AbuseIPDB",
        checked_at=datetime(2026, 7, 15, 18, 30, tzinfo=UTC),
    ).model_dump(mode="json")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ip_version", 6),
        ("ip_address", "192.168.1.1"),
        ("total_reports", "7"),
        ("checked_at", "2026-07-15T18:30:00"),
        ("isp", "x" * 256),
    ],
)
def test_backend_response_rejects_invalid_dependency_fields(
    field: str, value: object
) -> None:
    body = valid_result()
    body[field] = value
    response = httpx.Response(200, json=body)

    with pytest.raises(BackendClientError, match="invalid response"):
        BackendClient._validated_response(response, CheckResult)
