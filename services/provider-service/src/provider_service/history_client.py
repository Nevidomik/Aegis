"""Bounded authenticated client for History snapshot ingestion."""

import asyncio

import httpx
from pydantic import ValidationError

from provider_service.schemas import (
    BlacklistSnapshotDelivery,
    BlacklistSnapshotDeliveryReceipt,
)


class HistoryDeliveryError(Exception):
    """History did not provide a valid delivery acknowledgement."""


class HistoryIngestionClient:
    def __init__(
        self, client: httpx.AsyncClient, *, operation_timeout_seconds: float
    ) -> None:
        self.client = client
        self.operation_timeout_seconds = operation_timeout_seconds

    async def deliver(
        self, delivery: BlacklistSnapshotDelivery
    ) -> BlacklistSnapshotDeliveryReceipt:
        try:
            async with asyncio.timeout(self.operation_timeout_seconds):
                response = await self.client.post(
                    "/internal/v1/blacklist/snapshots",
                    json=delivery.model_dump(mode="json"),
                    headers={"X-Request-ID": str(delivery.delivery_id)},
                )
        except (httpx.RequestError, TimeoutError) as error:
            raise HistoryDeliveryError from error
        if response.status_code not in {200, 201}:
            raise HistoryDeliveryError
        try:
            receipt = BlacklistSnapshotDeliveryReceipt.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            raise HistoryDeliveryError from error
        if receipt.delivery_id != delivery.delivery_id:
            raise HistoryDeliveryError
        if response.status_code == 200 and receipt.status != "duplicate":
            raise HistoryDeliveryError
        if response.status_code == 201 and receipt.status != "accepted":
            raise HistoryDeliveryError
        return receipt
