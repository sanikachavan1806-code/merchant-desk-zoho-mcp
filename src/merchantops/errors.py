from __future__ import annotations

import re
from typing import Any


class MerchantOpsError(Exception):
    code = "internal"

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        body.update(self.details)
        return body


class ConfigError(MerchantOpsError):
    code = "config"


class NotFoundError(MerchantOpsError):
    code = "not_found"


class InvalidArgument(MerchantOpsError):
    code = "invalid_argument"


class ReadOnlyViolation(MerchantOpsError):
    code = "read_only"


class UnauthorizedError(MerchantOpsError):
    code = "unauthorized"


class UpstreamError(MerchantOpsError):
    code = "upstream"


class RateLimited(MerchantOpsError):
    """Structured quota failure the agent can explain to the merchant."""

    code = "rate_limited"

    def __init__(
        self,
        message: str,
        *,
        scope: str,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, scope=scope, retry_after=retry_after)
        self.scope = scope
        self.retry_after = retry_after


_DAILY_LIMIT_NUMBERS = re.compile(
    r"limit of (1000|2000|2500|5000|10000|75000)\b",
    re.IGNORECASE,
)


def classify_429(body: dict[str, Any] | None) -> str:
    """Map a Zoho 429 body to ``per_minute`` or ``daily``.

    Zoho Inventory's introduction documents two different 429 payloads:

    * code 44 — per-minute block (retry with backoff)
    * code 45 — daily plan ceiling, illustrated with the free-plan limit of 1000
      (fail fast; retrying burns nothing useful and can extend the block)

    The message text is a fallback because the daily example says "call rate
    limit" even though the number is the daily cap.
    """

    payload = body or {}
    code = payload.get("code")
    message = str(payload.get("message") or "")
    lowered = message.lower()
    if code == 45:
        return "daily"
    if code == 44 or "per minute" in lowered:
        return "per_minute"
    if "per day" in lowered or "for the day" in lowered or _DAILY_LIMIT_NUMBERS.search(message):
        return "daily"
    return "per_minute"
