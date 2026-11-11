from __future__ import annotations

from typing import Any
import httpx

from settings import INTEGRATIONS


LABELS = {
    "authentication": "External Authentication (optional)",
    "delivery": "Delivery Provider",
    "maps": "Maps / Geocoding",
    "payments": "Payment Gateway",
    "notifications": "Notifications",
}

ENV_FIELDS = {
    "authentication": ["AUTH_SERVICE_URL"],
    "delivery": ["DELIVERY_SERVICE_URL", "DELIVERY_API_KEY"],
    "maps": ["MAPS_SERVICE_URL", "MAPS_API_KEY"],
    "payments": ["PAYMENT_SERVICE_URL", "PAYMENT_PUBLIC_KEY", "PAYMENT_SECRET_KEY"],
    "notifications": ["NOTIFICATION_SERVICE_URL", "NOTIFICATION_API_KEY", "SMS_API_KEY"],
}


def statuses() -> list[dict[str, Any]]:
    return [
        {"key": key, "name": LABELS[key], "configured": bool(url), "env_fields": ENV_FIELDS.get(key, [])}
        for key, url in INTEGRATIONS.items()
    ]


def configured(key: str) -> bool:
    return bool(INTEGRATIONS.get(key))


def call(key: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    base = INTEGRATIONS.get(key)
    if not base:
        raise RuntimeError(f"{LABELS.get(key, key)} integration is not configured")
    response = httpx.post(f"{base}/{path.lstrip('/')}", json=payload, timeout=30)
    response.raise_for_status()
    return response.json() if response.content else {}
