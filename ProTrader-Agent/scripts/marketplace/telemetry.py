"""Telemetry helpers for the marketplace workflow."""
from __future__ import annotations

import time
from datetime import datetime, timezone

import bus

__all__ = [
    "_send_state",
    "_send_price",
    "_send_kamas",
    "_send_purchase_event",
    "_send_sale_event",
]


def _send_state(name: str) -> None:
    """Send the current FSM state to the backend bus if available."""

    if bus.client:
        bus.client.send({"type": "login_state", "state": name})
    else:
        print("ERREUR CLIENT")


def _send_price(slug: str, qty: str, price: int) -> None:
    """Send a detected marketplace price through the bus."""

    frame = {
        "type": "hdv_price",
        "ts": int(time.time()),
        "data": {
            "slug": slug,
            "qty": qty,
            "price": int(price),
        },
    }
    if bus.client:
        bus.client.send(frame)
    else:
        print("[WARN] bus.client indisponible, payload:", frame)


def _send_kamas(amount: int) -> None:
    """Send the current kamas fortune through the bus."""

    frame = {
        "type": "kamas_value",
        "ts": int(time.time()),
        "data": {"amount": int(amount)},
    }
    if bus.client:
        bus.client.send(frame)
    else:
        print("[WARN] bus.client indisponible, payload:", frame)


def _current_iso_datetime() -> str:
    """Return the current UTC datetime formatted using ISO 8601."""

    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _send_purchase_event(
    resource: str,
    quantity_label: str,
    quantity_value: int,
    unit_price: float,
    total_amount: int,
) -> None:
    """Send the payload describing a confirmed purchase."""

    frame = {
        "type": "purchase_event",
        "ts": int(time.time()),
        "data": {
            "resource": resource,
            "quantity_label": quantity_label,
            "quantity": quantity_value,
            "price": float(unit_price),
            "amount": int(total_amount),
            "date": _current_iso_datetime(),
        },
    }
    if bus.client:
        bus.client.send(frame)
    else:
        print("[WARN] bus.client indisponible, payload:", frame)


def _send_sale_event(
    resource: str,
    quantity_label: str,
    quantity_value: int,
    unit_price: float,
    total_amount: int,
) -> None:
    """Send the payload describing a confirmed sale."""

    frame = {
        "type": "sale_event",
        "ts": int(time.time()),
        "data": {
            "resource": resource,
            "quantity_label": quantity_label,
            "quantity": quantity_value,
            "price": float(unit_price),
            "amount": int(total_amount),
            "date": _current_iso_datetime(),
        },
    }
    if bus.client:
        bus.client.send(frame)
    else:
        print("[WARN] bus.client indisponible, payload:", frame)
