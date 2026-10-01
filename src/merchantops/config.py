from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from merchantops.errors import ConfigError

# Figures from the Zoho Inventory API introduction. A US knowledge-base page
# lists Standard as 2,500 and Premium as 75,000; set ZOHO_DAILY_LIMIT when an
# organization has a non-default ceiling.
PLAN_DAILY_LIMITS: dict[str, int] = {
    "free": 1_000,
    "standard": 2_000,
    "professional": 5_000,
    "premium": 10_000,
    "enterprise": 10_000,
}

PER_MINUTE_PLATFORM_LIMIT = 100
DEMO_AS_OF = date(2026, 10, 1)
IST = ZoneInfo("Asia/Kolkata")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    mode: str = Field(default="demo", alias="ZOHO_MODE")
    zoho_dc: str = Field(default="in", alias="ZOHO_DC")
    organization_id: str = Field(default="", alias="ZOHO_ORGANIZATION_ID")
    client_id: str = Field(default="", alias="ZOHO_CLIENT_ID")
    client_secret: str = Field(default="", alias="ZOHO_CLIENT_SECRET")
    redirect_uri: str = Field(
        default="http://127.0.0.1:8765/callback",
        alias="ZOHO_REDIRECT_URI",
    )
    access_token: str = Field(default="", alias="ZOHO_ACCESS_TOKEN")
    refresh_token: str = Field(default="", alias="ZOHO_REFRESH_TOKEN")
    token_encryption_key: str = Field(default="", alias="TOKEN_ENCRYPTION_KEY")
    token_store_path: str = Field(default=".tokens/zoho.json", alias="TOKEN_STORE_PATH")
    plan: str = Field(default="free", alias="ZOHO_PLAN")
    daily_limit: int | None = Field(default=None, alias="ZOHO_DAILY_LIMIT")
    per_minute_budget: int = Field(default=80, alias="ZOHO_PER_MINUTE_BUDGET")
    concurrency: int = Field(default=5, alias="ZOHO_CONCURRENCY")
    cache_ttl_seconds: int = Field(default=45, alias="ZOHO_CACHE_TTL_SECONDS")
    warehouse_cache_ttl_seconds: int = Field(default=600, alias="ZOHO_WAREHOUSE_CACHE_TTL_SECONDS")
    max_scan_pages: int = Field(default=4, alias="ZOHO_MAX_SCAN_PAGES")
    page_size_cap: int = Field(default=50, alias="ZOHO_PAGE_SIZE_CAP")
    default_page_size: int = Field(default=20, alias="ZOHO_DEFAULT_PAGE_SIZE")
    reveal_pii: bool = Field(default=False, alias="ZOHO_REVEAL_PII")
    read_only: bool = Field(
        default=True,
        validation_alias=AliasChoices("READ_ONLY", "ZOHO_READ_ONLY"),
    )
    audit_log_path: str = Field(default="logs/audit.jsonl", alias="AUDIT_LOG_PATH")
    razorpay_export_path: str = Field(default="", alias="RAZORPAY_EXPORT_PATH")
    host: str = Field(default="127.0.0.1", alias="MERCHANTOPS_HOST")
    port: int = Field(default=8000, alias="MERCHANTOPS_PORT")
    as_of: str = Field(default="", alias="ZOHO_AS_OF")

    def resolved_daily_limit(self) -> int:
        if self.daily_limit is not None:
            return self.daily_limit
        key = self.plan.strip().lower()
        if key not in PLAN_DAILY_LIMITS:
            known = ", ".join(sorted(PLAN_DAILY_LIMITS))
            raise ConfigError(f"Unknown ZOHO_PLAN '{self.plan}'. Use one of: {known}.")
        return PLAN_DAILY_LIMITS[key]

    def resolved_as_of(self) -> date:
        if self.as_of.strip():
            return date.fromisoformat(self.as_of.strip())
        if self.mode == "demo":
            return DEMO_AS_OF
        return datetime.now(IST).date()


def assert_read_only(settings: Settings) -> None:
    if settings.mode not in {"demo", "live"}:
        raise ConfigError("ZOHO_MODE must be 'demo' or 'live'.")
    if not settings.read_only:
        raise ConfigError(
            "This connector is read-only and will not start with READ_ONLY=false. "
            "Writes (purchase orders, stock adjustments, customer email, deletes, "
            "payments) are deliberately not implemented."
        )
    if settings.per_minute_budget > PER_MINUTE_PLATFORM_LIMIT:
        raise ConfigError(
            f"ZOHO_PER_MINUTE_BUDGET must stay at or under Zoho's {PER_MINUTE_PLATFORM_LIMIT}/minute platform limit."
        )
    if settings.concurrency < 1:
        raise ConfigError("ZOHO_CONCURRENCY must be at least 1.")
    if settings.page_size_cap < 1 or settings.page_size_cap > 50:
        raise ConfigError("ZOHO_PAGE_SIZE_CAP must be between 1 and 50.")
