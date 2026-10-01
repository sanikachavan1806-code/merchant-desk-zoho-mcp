from decimal import Decimal

from merchantops.demo.catalog import build_catalog
from merchantops.intelligence import (
    Snapshot,
    detect_operational_risks,
    explain_recommendation,
    find_alternate_fulfillment,
    match_order_to_payment,
    order_health,
)


def snapshot() -> Snapshot:
    catalog = build_catalog()
    return Snapshot(
        as_of=catalog.as_of,
        orders=catalog.orders,
        items=catalog.items,
        invoices=catalog.invoices,
        shipments=catalog.shipments,
        packages=catalog.packages,
        warehouses=catalog.warehouses,
        truncated=False,
    )


def test_mumbai_earbuds_cover_exactly_four_days():
    report = detect_operational_risks(snapshot())
    earbud = next(risk for risk in report["risks"] if risk["id"] == "stockout:SKU-EARBUD-PRO:wh_mum")
    assert "about 4 days" in earbud["title"]
    assert "days_of_cover=4.0" in earbud["evidence"]
    assert earbud["severity"] == "medium"


def test_speaker_imbalance_and_alternate_warehouse():
    report = detect_operational_risks(snapshot())
    assert any(risk["type"] == "imbalance" and risk["sku"] == "SKU-SPEAKER-MINI" for risk in report["risks"])
    alternate = find_alternate_fulfillment(snapshot(), "SKU-SPEAKER-MINI", 6, "wh_blr")
    assert alternate["source_can_fulfill"] is False
    assert alternate["alternatives"][0]["warehouse_id"] == "wh_mum"
    assert alternate["fulfillment_possible"] is True


def test_razorpay_paid_but_not_invoiced_is_only_so_1008():
    report = match_order_to_payment(snapshot(), only_paid_not_invoiced=True)
    assert [row["order_number"] for row in report["matches"]] == ["SO-1008"]
    settled = match_order_to_payment(snapshot(), payment_id="pay_Settled1010")
    assert settled["matches"][0]["settled_in_zoho"] is True
    open_invoice = match_order_to_payment(snapshot(), payment_id="pay_UnpaidInv1005")
    assert open_invoice["matches"][0]["invoices"][0]["status"] == "unpaid"
    assert open_invoice["matches"][0]["paid_on_razorpay_not_invoiced"] is False


def test_order_health_states():
    assert order_health(snapshot(), "SO-1002")["health"] == "AT_RISK"
    assert order_health(snapshot(), "SO-1001")["health"] == "WATCH"
    assert order_health(snapshot(), "SO-1010")["health"] == "HEALTHY"
    explained = explain_recommendation(snapshot(), "collect:SO-1005")
    assert explained["executable"] is False
    assert Decimal(explained["evidence"][1].split(":")[1]) == Decimal("3998.00")
