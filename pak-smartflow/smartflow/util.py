"""Small shared helpers: JSON-safe conversion and formatting."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Mapping


def jsonable(obj: Any) -> Any:
    """Convert dataclasses/enums/datetimes/bytes into JSON-safe structures."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(obj))} bytes>"
    if is_dataclass(obj) and not isinstance(obj, type):
        return jsonable(asdict(obj))
    if isinstance(obj, Mapping):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [jsonable(v) for v in obj]
    return str(obj)


def money(amount: float, currency: str = "PKR") -> str:
    return f"{currency} {amount:,.0f}"


def money2(amount: float, currency: str = "PKR") -> str:
    return f"{currency} {amount:,.2f}"


def bar(value: float, width: int = 28, full: str = "#", empty: str = ".") -> str:
    """ASCII progress bar for terminal reporting."""
    value = max(0.0, min(100.0, value))
    filled = int(round(value / 100.0 * width))
    return full * filled + empty * (width - filled)


def truncate(text: str, width: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"
