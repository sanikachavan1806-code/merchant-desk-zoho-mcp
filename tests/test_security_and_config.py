from datetime import datetime, timedelta, timezone

import pytest

from merchantops.auth.oauth import READ_SCOPES, build_authorization_url, token_needs_refresh
from merchantops.auth.store import TokenStore
from merchantops.config import PLAN_DAILY_LIMITS, Settings, assert_read_only
from merchantops.datacenters import DATACENTERS, resolve_datacenter, validate_api_domain
from merchantops.errors import ConfigError, classify_429
from merchantops.models import TokenSet
from merchantops.security import mask_email, mask_phone, scrub_free_text


def test_eight_datacenters_and_india_default():
    assert len(DATACENTERS) == 8
    accounts, api = resolve_datacenter("in")
    assert api == "https://www.zohoapis.in"
    assert "accounts.zoho.in" in accounts


def test_api_domain_must_be_a_zoho_host():
    assert validate_api_domain("https://www.zohoapis.in/inventory") == "https://www.zohoapis.in"
    with pytest.raises(ConfigError):
        validate_api_domain("https://evil.example/zoho")


def test_live_mode_requires_credentials(tmp_path):
    from merchantops.service import build_service

    settings = Settings(_env_file=None, mode="live", audit_log_path=str(tmp_path / "audit.jsonl"))
    with pytest.raises(ConfigError, match="ZOHO_ACCESS_TOKEN"):
        build_service(settings)


def test_read_only_refuses_to_start():
    with pytest.raises(ConfigError):
        assert_read_only(Settings(_env_file=None, mode="demo", read_only=False))


def test_plan_ceilings_match_the_introduction():
    assert PLAN_DAILY_LIMITS == {
        "free": 1000,
        "standard": 2000,
        "professional": 5000,
        "premium": 10000,
        "enterprise": 10000,
    }


def test_429_codes_follow_zoho_docs():
    assert classify_429({"code": 44, "message": "exceeded the maximum number of requests per minute"}) == "per_minute"
    assert classify_429({"code": 45, "message": "exceeded the maximum call rate limit of 1000."}) == "daily"
    assert classify_429({"message": "blocked for the day"}) == "daily"


def test_oauth_url_is_offline_and_read_only():
    url, state = build_authorization_url(
        dc="in",
        client_id="client",
        redirect_uri="http://127.0.0.1:8765/callback",
        state="fixed-state",
    )
    assert state == "fixed-state"
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "FullAccess" not in url
    for scope in READ_SCOPES:
        assert scope in url
    assert url.startswith("https://accounts.zoho.in/oauth/v2/auth?")


def test_refresh_skew_and_encrypted_store(tmp_path):
    soon = TokenSet(
        access_token="access",
        refresh_token="refresh",
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
        dc="in",
    )
    assert token_needs_refresh(soon, datetime.now(timezone.utc))
    later = soon.model_copy(update={"expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
    assert not token_needs_refresh(later, datetime.now(timezone.utc))

    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    store = TokenStore(tmp_path / "tokens.bin", key)
    store.save(soon)
    assert store.load().refresh_token == "refresh"
    assert b"refresh" not in (tmp_path / "tokens.bin").read_bytes()
    with pytest.raises(Exception):
        TokenStore(tmp_path / "tokens.bin", Fernet.generate_key().decode()).load()


def test_pii_masking():
    assert mask_email("rahul.shah@example.com") == "r***@example.com"
    assert mask_phone("9876543210") == "******3210"
    scrubbed = scrub_free_text("call 9876543210 or rahul.shah@example.com ref pay_NotInvoiced1008")
    assert "9876543210" not in scrubbed
    assert "rahul.shah@" not in scrubbed
    assert "pay_NotInvoiced1008" in scrubbed
