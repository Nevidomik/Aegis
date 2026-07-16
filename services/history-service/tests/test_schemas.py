from datetime import UTC

import pytest
from history_service.schemas import CheckCreate, HistoryListQuery
from pydantic import ValidationError

from .conftest import check_payload


def test_create_normalizes_ipv6_country_and_timestamp() -> None:
    payload = CheckCreate.model_validate(
        check_payload(
            ip_address="2606:4700:4700:0000:0000:0000:0000:1111",
            ip_version=6,
            country_code="us",
        )
    )

    assert payload.ip_address == "2606:4700:4700::1111"
    assert payload.country_code == "US"
    assert payload.checked_at.tzinfo == UTC


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"ip_address": "not-an-ip"}, "valid IPv4 or IPv6"),
        ({"ip_address": "127.0.0.1"}, "must be public"),
        ({"ip_address": "224.0.0.1"}, "must be public"),
        ({"ip_version": 6}, "does not match"),
        ({"checked_at": "2026-07-15T18:30:00"}, "include a timezone"),
        ({"abuse_confidence_score": "12"}, "valid integer"),
        ({"total_reports": 2_147_483_648}, "less than or equal"),
        ({"isp": "x" * 256}, "at most 255"),
    ],
)
def test_create_rejects_invalid_normalized_data(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        CheckCreate.model_validate(check_payload(**overrides))


def test_list_query_normalizes_filter_and_bounds_limit() -> None:
    query = HistoryListQuery(ip_address="2606:4700:4700:0:0:0:0:1111")

    assert query.ip_address == "2606:4700:4700::1111"
    assert query.limit == 20
    assert query.offset == 0

    with pytest.raises(ValidationError):
        HistoryListQuery(limit=101)
