from __future__ import annotations

import base64
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from merchantops.errors import InvalidArgument


def encode_cursor(page: int) -> str:
    raw = base64.urlsafe_b64encode(str(page).encode()).decode()
    return raw.rstrip("=")


def decode_cursor(cursor: str | None) -> int:
    if cursor is None or cursor == "":
        return 1
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        page = int(base64.urlsafe_b64decode(padded.encode()).decode())
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidArgument("Cursor is not valid. Pass next_cursor from the previous page.") from exc
    if page < 1:
        raise InvalidArgument("Cursor is not valid. Pass next_cursor from the previous page.")
    return page


def parse_date(value: str | None, *, field: str) -> date | None:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidArgument(f"{field} must be an ISO date (YYYY-MM-DD).") from exc


def project(record: dict[str, Any], fields: list[str] | None) -> dict[str, Any]:
    if not fields:
        return record
    unknown = [name for name in fields if name not in record]
    if unknown:
        known = ", ".join(sorted(record))
        raise InvalidArgument(f"Unknown fields: {', '.join(unknown)}. Known fields: {known}.")
    return {name: record[name] for name in fields}


def dump_model(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json", exclude_none=True)
    raise TypeError(f"Cannot serialize {type(model)!r}")


def counted(count: int, singular: str, plural: str | None = None) -> str:
    word = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {word}"


def format_money(amount: Decimal | int | float | str, currency: str = "INR") -> str:
    quantized = Decimal(str(amount)).quantize(Decimal("0.01"))
    if currency == "INR":
        return f"₹{quantized:,.2f}"
    return f"{currency} {quantized:,.2f}"


def envelope(
    summary: str,
    payload: dict[str, Any],
    *,
    source: str,
    truncated: bool = False,
    pii_redacted: bool = True,
    calls_used: int | None = None,
    sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "read_only": True,
        "pii_redacted": pii_redacted,
        "truncated": truncated,
        "source": source,
    }
    if calls_used is not None:
        meta["calls_used"] = calls_used
    if sources:
        meta["sources"] = sources
    return {"summary": summary, "meta": meta, **payload}


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value
