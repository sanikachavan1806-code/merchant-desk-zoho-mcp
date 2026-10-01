from merchantops.config import Settings
from merchantops.service import build_service
from merchantops.web.app import create_app
from starlette.testclient import TestClient


def _client(tmp_path):
    settings = Settings(_env_file=None, mode="demo", audit_log_path=str(tmp_path / "audit.jsonl"))
    return TestClient(create_app(build_service(settings)))


def test_desk_page_and_live_tools(tmp_path):
    client = _client(tmp_path)
    page = client.get("/")
    assert page.status_code == 200
    assert "Mira Audio" in page.text
    assert "/static/desk.js" in page.text

    brief = client.get("/api/brief")
    assert brief.status_code == 200
    body = brief.json()
    assert "2026-10-01" in body["brief"]
    assert body["meta"]["read_only"] is True

    payments = client.get("/api/payments", params={"only_paid_not_invoiced": "true"})
    assert [row["order_number"] for row in payments.json()["matches"]] == ["SO-1008"]

    reconcile = client.get("/api/reconcile")
    assert [row["order_number"] for row in reconcile.json()["buckets"]["paid_not_shipped"]] == ["SO-1010"]
    gst = client.get("/api/gst", params={"period": "2026-09"})
    assert gst.json()["tax_total"] == "1812.15"

    shipments = client.get("/api/shipments")
    assert shipments.status_code == 200
    assert {row["number"] for row in shipments.json()["shipments"]} >= {"SHP-1005", "SHP-1006", "SHP-1007"}

    invoices = client.get("/api/invoices")
    numbers = {row["number"] for row in invoices.json()["invoices"]}
    assert "INV-1005" in numbers
    assert invoices.json()["meta"]["read_only"] is True

    fulfillment = client.post(
        "/api/fulfillment",
        json={"sku": "SKU-SPEAKER-MINI", "quantity": 6, "source_warehouse_id": "wh_blr"},
    )
    assert fulfillment.json()["source_can_fulfill"] is False
    assert fulfillment.json()["alternatives"][0]["warehouse_name"] == "Mumbai"

    refused = client.post(
        "/api/propose",
        json={"action_type": "transfer_stock", "reason": "move it", "payload": {"quantity": 20}},
    )
    assert refused.json()["executed"] is False
    assert "write" in refused.json()["refusal"].lower()

    customer = client.get("/api/customer/cus_rahul", params={"include_pii": "true"})
    assert customer.json()["customer"]["email"] == "r***@example.com"
    audit = client.get("/api/audit").json()["events"]
    assert audit[-1]["tool"] == "get_customer"
    assert "rahul.shah@example.com" not in str(audit)

    catalog = client.get("/api/mcp/catalog")
    assert catalog.status_code == 200
    body = catalog.json()
    assert body["connected"] is True
    assert body["read_only"] is True
    assert len(body["tools"]) == 21
    assert {row["name"] for row in body["prompts"]} >= {"paid_not_invoiced", "daily_ops_brief"}

    called = client.post(
        "/api/mcp/call",
        json={"name": "match_order_to_payment", "arguments": {"only_paid_not_invoiced": True}},
    )
    assert called.json()["ok"] is True
    assert called.json()["result"]["matches"][0]["order_number"] == "SO-1008"
