import json

import pytest

from merchantops.config import Settings
from merchantops.demo.catalog import build_catalog
from merchantops.finance import RazorpayBook, book_from_payload, reconcile_orders
from merchantops.formatting import dump_model
from merchantops.intelligence import Snapshot
from merchantops.service import build_service


def service(tmp_path):
    settings = Settings(_env_file=None, mode="demo", audit_log_path=str(tmp_path / "audit.jsonl"))
    return build_service(settings)


@pytest.mark.asyncio
async def test_reconcile_buckets_and_citations(tmp_path):
    svc = service(tmp_path)
    report = await svc.reconcile_orders()
    buckets = report["buckets"]
    assert [row["order_number"] for row in buckets["paid_and_shipped"]] == ["SO-0904"]
    assert [row["order_number"] for row in buckets["paid_not_invoiced"]] == ["SO-1008"]
    assert [row["order_number"] for row in buckets["invoiced_but_unpaid"]] == ["SO-1005", "SO-1006", "SO-1007"]
    assert [row["order_number"] for row in buckets["refunded_stock_not_returned"]] == ["SO-1012"]
    assert [row["order_number"] for row in buckets["paid_not_shipped"]] == ["SO-1010"]
    assert buckets["paid_not_shipped"][0]["razorpay_status"] == "captured"
    assert buckets["paid_not_shipped"][0]["razorpay_verified"] is True
    unsettled = {row["order_number"] for row in report["captured_not_settled"]}
    assert unsettled == {"SO-1005", "SO-1006", "SO-1007", "SO-1008"}
    assert report["meta"]["fetched_at"]
    systems = {source["system"] for source in report["meta"]["sources"]}
    assert systems == {"zoho", "razorpay_export"}
    assert "pay_" in report["join_key"] or "pay_" in report["summary"] or "reference" in report["join_key"]


@pytest.mark.asyncio
async def test_export_absent_does_not_claim_a_capture(tmp_path):
    svc = service(tmp_path)
    svc.razorpay = RazorpayBook.empty()
    report = await svc.reconcile_orders()
    row = report["buckets"]["paid_not_invoiced"][0]
    assert row["order_number"] == "SO-1008"
    assert row["razorpay_status"] == "referenced_not_verified"
    assert row["razorpay_verified"] is False
    assert report["captured_not_settled"] == []
    assert report["razorpay_export_loaded"] is False


@pytest.mark.asyncio
async def test_dead_stock_gst_and_anomalies(tmp_path):
    svc = service(tmp_path)
    dead = await svc.dead_stock(days=30)
    assert [item["sku"] for item in dead["items"]] == ["SKU-STAND-OLD"]
    assert dead["items"][0]["value_tied_up"] == "10000.00"
    assert dead["items"][0]["basis"] == "purchase_rate"
    assert dead["value_tied_up"] == "10000.00"

    gst = await svc.gst_summary(period="2026-09")
    by_rate = {row["tax_rate"]: row["tax_amount"] for row in gst["rates"]}
    assert by_rate["18"] == "1797.15"
    assert by_rate["5"] == "15.00"
    assert gst["tax_total"] == "1812.15"
    assert "not a filed GSTR" in gst["note"]

    flags = await svc.detect_anomalies(window_days=14)
    kinds = {flag["type"] for flag in flags["flags"]}
    assert kinds == {"order_spike", "unusual_discount", "failed_then_paid"}
    titles = " ".join(flag["title"] for flag in flags["flags"])
    assert "SO-1011" in titles
    assert "SO-1010" in titles


def test_paise_are_converted_only_when_labeled():
    book = book_from_payload(
        {"payments": [{"id": "pay_x", "amount": "199900", "amount_unit": "paise", "status": "captured"}]},
        loaded=True,
    )
    assert str(book.payments[0].amount) == "1999.00"


def test_trimmed_order_is_smaller_than_a_zoho_payload():
    order = next(row for row in build_catalog().orders if row.number == "SO-1008")
    trimmed = json.dumps(dump_model(order), default=str)
    fat = json.dumps(_zoho_shaped(order), default=str)
    assert (len(trimmed), len(fat)) == (573, 1764)
    assert len(trimmed) < len(fat) * 0.4


def _zoho_shaped(order) -> dict:
    return {
        "salesorder_id": order.id,
        "salesorder_number": order.number,
        "date": order.date.isoformat(),
        "status": order.status,
        "customer_id": order.customer_id,
        "customer_name": order.customer_name,
        "contact_persons": [{"contact_person_id": "cp_1", "email": "rahul.shah@example.com", "phone": "9876543210"}],
        "billing_address": {"address": "12 Linking Road", "city": "Mumbai", "state": "Maharashtra", "zip": "400050"},
        "shipping_address": {"address": "12 Linking Road", "city": "Mumbai", "state": "Maharashtra", "zip": "400050"},
        "notes": "Customer asked to call before delivery. pay_NotInvoiced1008",
        "custom_fields": [{"label": "Razorpay", "value": order.payment_ids[0]}],
        "line_items": [
            {
                "line_item_id": "li_1",
                "item_id": line.item_id,
                "sku": line.sku,
                "name": line.name,
                "quantity": line.quantity,
                "rate": str(line.rate),
                "tax_id": "tax_18",
                "tax_percentage": 18,
                "warehouse_id": line.warehouse_id,
                "warehouse_name": line.warehouse_name,
                "description": "Black, retail pack, serial tracked",
            }
            for line in order.line_items
        ],
        "sub_total": str(order.total),
        "tax_total": "0.00",
        "total": str(order.total),
        "currency_code": "INR",
        "reference_number": order.reference_number,
        "created_time": "2026-10-01T10:05:00+0530",
        "last_modified_time": "2026-10-01T10:06:12+0530",
        "salesperson_name": "Mira Desk",
        "delivery_method": "Shiprocket",
        "notes_html": "<p>Customer asked to call before delivery. Landmark is the blue shutter.</p>",
        "documents": [{"document_id": "doc_1", "file_name": "gst-invoice-draft.pdf", "file_size": 240112}],
        "comments": [
            {"comment_id": "c1", "description": "Payment captured on Razorpay, invoice not raised.", "commented_by": "Finance"},
            {"comment_id": "c2", "description": "Warehouse asked to hold the pack until the invoice exists.", "commented_by": "Bengaluru"},
        ],
        "taxes": [{"tax_name": "GST18", "tax_amount": 45.61}],
        "packages": [],
        "invoices": [],
    }


def test_reconcile_without_export_uses_the_same_buckets():
    catalog = build_catalog()
    snapshot = Snapshot(
        as_of=catalog.as_of,
        orders=catalog.orders,
        items=catalog.items,
        invoices=catalog.invoices,
        shipments=catalog.shipments,
        packages=catalog.packages,
        warehouses=catalog.warehouses,
        truncated=False,
    )
    report = reconcile_orders(snapshot, RazorpayBook.empty())
    assert report["buckets"]["paid_not_shipped"][0]["razorpay_status"] == "referenced_not_verified"
