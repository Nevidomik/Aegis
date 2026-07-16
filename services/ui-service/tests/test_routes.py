from uuid import UUID

import pytest
from httpx2 import AsyncClient

from .conftest import FakeBackendClient


@pytest.mark.anyio
async def test_readiness_reflects_backend_state(
    client: AsyncClient, backend: FakeBackendClient
) -> None:
    request_id = "6f5aa064-43e8-4dbb-a544-d60b68af5cbd"
    ready = await client.get("/health/ready", headers={"X-Request-ID": request_id})
    backend.ready_error = "Backend is unavailable"
    unavailable = await client.get("/health/ready")

    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}
    assert ready.headers["X-Request-ID"] == request_id
    assert unavailable.status_code == 503
    assert unavailable.json() == {"status": "not ready"}


@pytest.mark.anyio
async def test_main_page_displays_form_and_recent_history(
    client: AsyncClient, backend: FakeBackendClient
) -> None:
    response = await client.get("/")

    assert response.status_code == 200
    assert 'name="ip_address"' in response.text
    assert 'name="max_age_days"' in response.text
    assert "Recent history" in response.text
    assert "8.8.8.8" in response.text
    assert UUID(response.headers["X-Request-ID"])
    assert backend.history_request_id == response.headers["X-Request-ID"]


@pytest.mark.anyio
async def test_submit_displays_normalized_result_and_refreshes_history(
    client: AsyncClient, backend: FakeBackendClient
) -> None:
    request_id = "6f5aa064-43e8-4dbb-a544-d60b68af5cbd"
    response = await client.post(
        "/",
        data={
            "ip_address": "2606:4700:4700::1111",
            "max_age_days": "90",
        },
        headers={"X-Request-ID": request_id},
    )

    assert response.status_code == 200
    assert "Current normalized result" in response.text
    assert "2606:4700:4700::1111" in response.text
    assert "12%" in response.text
    assert backend.check_request == {
        "ip_address": "2606:4700:4700::1111",
        "max_age_days": 90,
        "request_id": request_id,
    }
    assert backend.history_request_id == request_id
    assert response.headers["X-Request-ID"] == request_id


@pytest.mark.anyio
async def test_backend_validation_error_is_readable_and_preserves_input(
    client: AsyncClient, backend: FakeBackendClient
) -> None:
    backend.check_error = "The supplied IP address is not globally routable."

    response = await client.post(
        "/",
        data={"ip_address": "192.168.1.25", "max_age_days": "60"},
    )

    assert response.status_code == 200
    assert "The supplied IP address is not globally routable." in response.text
    assert 'value="192.168.1.25"' in response.text
    assert 'value="60"' in response.text


@pytest.mark.anyio
async def test_local_form_error_preserves_values_without_check_call(
    client: AsyncClient, backend: FakeBackendClient
) -> None:
    response = await client.post(
        "/",
        data={"ip_address": "8.8.8.8", "max_age_days": "not-a-number"},
    )

    assert response.status_code == 200
    assert "Max age must be a whole number between 1 and 365." in response.text
    assert 'value="8.8.8.8"' in response.text
    assert 'value="not-a-number"' in response.text
    assert backend.check_request is None


@pytest.mark.anyio
async def test_dependency_error_is_readable_and_preserves_input(
    client: AsyncClient, backend: FakeBackendClient
) -> None:
    backend.check_error = "Backend Service is unavailable. Please try again."

    response = await client.post(
        "/",
        data={"ip_address": "8.8.4.4", "max_age_days": "30"},
    )

    assert response.status_code == 200
    assert "Backend Service is unavailable. Please try again." in response.text
    assert 'value="8.8.4.4"' in response.text


@pytest.mark.anyio
async def test_history_dependency_error_keeps_page_usable(
    client: AsyncClient, backend: FakeBackendClient
) -> None:
    backend.history_error = "Recent history is temporarily unavailable."

    response = await client.get("/")

    assert response.status_code == 200
    assert "Recent history is temporarily unavailable." in response.text
    assert 'name="ip_address"' in response.text
