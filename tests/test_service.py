import json

import pytest

from merchantops.config import Settings
from merchantops.formatting import decode_cursor
from merchantops.service import build_service


def service(tmp_path):
    settings = Settings(
        _env_file=None,
        mode="demo",
        audit_log_path=str(tmp_path / "audit.jsonl"),
        reveal_pii=False,
    )
    return build_service(settings)


@pytest.mark.asyncio
async def test_pagination_low_stock_and_pii(tmp_path):
    svc = service(tmp_path)
    page = await svc.search_orders(limit=10)
    assert page["has_more"] is True
    assert decode_cursor(page["next_cursor"]) == 2
    total = len(page["orders"])
    while page["has_more"]:
        page = await svc.search_orders(limit=10, cursor=page["next_cursor"])
        total += len(page["orders"])
    assert total == 37

    low = await svc.list_inventory(low_stock_only=True)
    assert [item["sku"] for item in low["items"]] == ["SKU-EARBUD-PRO"]

    customer = await svc.get_customer("cus_rahul", include_pii=True)
    assert customer["customer"]["email"] == "r***@example.com"
    assert customer["customer"]["phone"] == "******3210"
    assert customer["meta"]["pii_redacted"] is True
    assert "rahul.shah@example.com" not in (tmp_path / "audit.jsonl").read_text()
    assert "9876543210" not in (tmp_path / "audit.jsonl").read_text()

    refused = await svc.propose_action("payment_execution", reason="capture it", payload={"payment_id": "pay_x"})
    assert refused["executed"] is False
    assert refused["error"] if "error" in refused else refused["refusal"]
    audit = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    propose = next(row for row in audit if row["tool"] == "propose_action")
    assert propose["args"]["reason"] == "present"
    assert "capture" not in json.dumps(propose)


@pytest.mark.asyncio
async def test_budget_counts_a_snapshot_once(tmp_path):
    svc = service(tmp_path)
    await svc.detect_operational_risks()
    first = await svc.get_api_budget()
    await svc.get_daily_operations_brief()
    second = await svc.get_api_budget()
    assert first["daily_used"] == second["daily_used"]
    assert second["daily_used"] < 15
    assert second["per_minute_budget"] == 80
    assert second["daily_limit"] == 1000


@pytest.mark.asyncio
async def test_reveal_pii_requires_the_server_flag(tmp_path):
    settings = Settings(
        _env_file=None,
        mode="demo",
        audit_log_path=str(tmp_path / "audit.jsonl"),
        reveal_pii=True,
    )
    svc = build_service(settings)
    hidden = await svc.get_customer("cus_rahul", include_pii=False)
    shown = await svc.get_customer("cus_rahul", include_pii=True)
    assert hidden["customer"]["email"] == "r***@example.com"
    assert shown["customer"]["email"] == "rahul.shah@example.com"
    assert shown["meta"]["pii_redacted"] is False
