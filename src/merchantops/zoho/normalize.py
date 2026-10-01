from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any

from merchantops.models import (
    Contact,
    Invoice,
    Item,
    LineItem,
    Package,
    SalesOrder,
    Shipment,
    Warehouse,
    WarehouseStock,
)
from merchantops.security import scrub_free_text

_PAY = re.compile(r"\b((?:pay|plink)_[A-Za-z0-9]+)\b")


def _date(value: Any) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _optional_money(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return _money(value)


def _money(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def _int(value: Any) -> int:
    if value is None or value == "":
        return 0
    return int(Decimal(str(value)))


def _stock_returned(value: Any) -> bool:
    if value is None or value == "":
        return True
    return str(value).strip().lower() not in {"false", "0", "no"}


def payment_ids_from(*parts: Any) -> list[str]:
    seen: list[str] = []
    for part in parts:
        if not part:
            continue
        for match in _PAY.findall(str(part)):
            if match not in seen:
                seen.append(match)
    return seen


def normalize_item(raw: dict[str, Any]) -> Item:
    warehouses: list[WarehouseStock] = []
    for row in raw.get("warehouses") or []:
        warehouses.append(
            WarehouseStock(
                warehouse_id=str(row.get("warehouse_id") or ""),
                warehouse_name=str(row.get("warehouse_name") or row.get("warehouse_id") or ""),
                available=_int(row.get("warehouse_available_stock", row.get("warehouse_actual_available_stock"))),
                on_hand=_int(row.get("warehouse_stock_on_hand")),
            )
        )
    available = _int(raw.get("available_stock", raw.get("actual_available_stock")))
    on_hand = _int(raw.get("stock_on_hand"))
    if warehouses and "available_stock" not in raw and "actual_available_stock" not in raw:
        available = sum(row.available for row in warehouses)
        on_hand = sum(row.on_hand for row in warehouses)
    return Item(
        id=str(raw.get("item_id") or raw.get("id")),
        sku=str(raw.get("sku") or ""),
        name=str(raw.get("name") or raw.get("item_name") or ""),
        available=available,
        committed=_int(raw.get("committed_stock")),
        on_hand=on_hand,
        reorder_level=_int(raw.get("reorder_level")),
        selling_rate=_optional_money(raw.get("rate", raw.get("selling_price"))),
        purchase_rate=_optional_money(raw.get("purchase_rate")),
        warehouses=warehouses,
    )


def normalize_order(raw: dict[str, Any]) -> SalesOrder:
    lines: list[LineItem] = []
    for row in raw.get("line_items") or []:
        lines.append(
            LineItem(
                item_id=str(row.get("item_id") or ""),
                sku=str(row.get("sku") or ""),
                name=str(row.get("name") or ""),
                quantity=_int(row.get("quantity")),
                rate=_money(row.get("rate")),
                warehouse_id=(str(row["warehouse_id"]) if row.get("warehouse_id") else None),
                warehouse_name=(str(row["warehouse_name"]) if row.get("warehouse_name") else None),
            )
        )
    ordered = _int(raw.get("quantity")) or sum(line.quantity for line in lines)
    shipped = _int(raw.get("quantity_shipped"))
    if shipped == 0:
        shipped = sum(_int(row.get("quantity_shipped")) for row in raw.get("line_items") or [])
    reference = scrub_free_text(str(raw.get("reference_number"))) if raw.get("reference_number") else None
    payments = payment_ids_from(raw.get("reference_number"), raw.get("notes"), raw.get("cf_razorpay_payment_id"))
    return SalesOrder(
        id=str(raw.get("salesorder_id") or raw.get("id")),
        number=str(raw.get("salesorder_number") or raw.get("salesorder_id") or ""),
        date=_date(raw.get("date")) or date.min,
        status=str(raw.get("status") or "unknown"),
        shipment_date=_date(raw.get("shipment_date")),
        customer_id=str(raw.get("customer_id") or ""),
        customer_name=str(raw.get("customer_name") or ""),
        currency=str(raw.get("currency_code") or raw.get("currency") or "INR"),
        total=_money(raw.get("total")),
        reference_number=reference,
        payment_ids=payments,
        invoiced_status=str(raw.get("invoiced_status") or "not_invoiced"),
        line_items=lines,
        quantity_ordered=ordered,
        quantity_shipped=shipped,
        stock_returned=_stock_returned(raw.get("cf_stock_returned")),
    )


def _linked_salesorder_id(raw: dict[str, Any]) -> str | None:
    if raw.get("salesorder_id"):
        return str(raw["salesorder_id"])
    linked = raw.get("salesorders") or []
    if linked and isinstance(linked, list) and linked[0].get("salesorder_id"):
        return str(linked[0]["salesorder_id"])
    return None


def normalize_invoice(raw: dict[str, Any]) -> Invoice:
    return Invoice(
        id=str(raw.get("invoice_id") or raw.get("id")),
        number=str(raw.get("invoice_number") or raw.get("invoice_id") or ""),
        salesorder_id=_linked_salesorder_id(raw),
        customer_id=str(raw.get("customer_id") or ""),
        status=str(raw.get("status") or "unknown"),
        total=_money(raw.get("total")),
        balance=_money(raw.get("balance")),
        date=_date(raw.get("date")) or date.min,
        currency=str(raw.get("currency_code") or "INR"),
        tax_rate=_money(raw.get("tax_percentage", raw.get("tax_rate"))),
        tax_amount=_money(raw.get("tax_total", raw.get("tax_amount"))),
    )


def normalize_shipment(raw: dict[str, Any]) -> Shipment:
    return Shipment(
        id=str(raw.get("shipment_id") or raw.get("id")),
        number=str(raw.get("shipment_number") or raw.get("shipment_id") or ""),
        salesorder_id=str(raw.get("salesorder_id") or ""),
        status=str(raw.get("status") or "unknown"),
        date=_date(raw.get("date") or raw.get("shipment_date")),
        tracking_number=(str(raw["tracking_number"]) if raw.get("tracking_number") else None),
        warehouse_id=(str(raw["warehouse_id"]) if raw.get("warehouse_id") else None),
    )


def normalize_package(raw: dict[str, Any]) -> Package:
    return Package(
        id=str(raw.get("package_id") or raw.get("id")),
        salesorder_id=str(raw.get("salesorder_id") or ""),
        status=str(raw.get("status") or "unknown"),
        date=_date(raw.get("date")),
    )


def normalize_contact(raw: dict[str, Any]) -> Contact:
    return Contact(
        id=str(raw.get("contact_id") or raw.get("id")),
        name=str(raw.get("contact_name") or raw.get("name") or ""),
        email=(str(raw["email"]) if raw.get("email") else None),
        phone=(str(raw["phone"] or raw.get("mobile")) if (raw.get("phone") or raw.get("mobile")) else None),
        company=(str(raw["company_name"]) if raw.get("company_name") else None),
    )


def normalize_warehouse(raw: dict[str, Any]) -> Warehouse:
    return Warehouse(
        id=str(raw.get("warehouse_id") or raw.get("id")),
        name=str(raw.get("warehouse_name") or raw.get("name") or ""),
        city=(str(raw["city"]) if raw.get("city") else None),
    )
