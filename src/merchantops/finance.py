"""Inventory and payment questions that a Zoho-only or Razorpay-only connector cannot answer."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from merchantops.errors import InvalidArgument
from merchantops.formatting import format_money
from merchantops.intelligence import Snapshot, _fulfilled
from merchantops.models import Invoice, SalesOrder

UNPAID = {"unpaid", "overdue", "partially_paid", "sent"}
_STATUS_RANK = {"captured": 0, "authorized": 1, "refunded": 2, "failed": 3}


@dataclass(frozen=True)
class RazorpayPayment:
    id: str
    amount: Decimal
    currency: str
    status: str
    created_at: str
    zoho_salesorder_number: str | None
    settlement_id: str | None


@dataclass(frozen=True)
class RazorpaySettlement:
    id: str
    status: str
    payment_ids: tuple[str, ...]


@dataclass(frozen=True)
class RazorpayBook:
    payments: tuple[RazorpayPayment, ...]
    settlements: tuple[RazorpaySettlement, ...]
    loaded: bool

    @classmethod
    def empty(cls) -> RazorpayBook:
        return cls(payments=(), settlements=(), loaded=False)


def load_razorpay_book(path: str | None, *, demo_fallback: dict | None = None) -> RazorpayBook:
    if path:
        file = Path(path)
        if not file.exists():
            raise InvalidArgument(f"RAZORPAY_EXPORT_PATH does not exist: {path}")
        payload = json.loads(file.read_text(encoding="utf-8"))
        return book_from_payload(payload, loaded=True)
    if demo_fallback is not None:
        return book_from_payload(demo_fallback, loaded=True)
    return RazorpayBook.empty()


def book_from_payload(payload: dict[str, Any], *, loaded: bool) -> RazorpayBook:
    payments = tuple(_payment(row) for row in payload.get("payments") or [])
    settlements = tuple(
        RazorpaySettlement(
            id=str(row.get("id")),
            status=str(row.get("status") or "unknown"),
            payment_ids=tuple(str(item) for item in row.get("payment_ids") or []),
        )
        for row in payload.get("settlements") or []
    )
    return RazorpayBook(payments=payments, settlements=settlements, loaded=loaded)


def _payment(row: dict[str, Any]) -> RazorpayPayment:
    amount = Decimal(str(row.get("amount") or "0"))
    if str(row.get("amount_unit") or "").lower() == "paise":
        amount = (amount / Decimal("100")).quantize(Decimal("0.01"))
    return RazorpayPayment(
        id=str(row.get("id")),
        amount=amount,
        currency=str(row.get("currency") or "INR"),
        status=str(row.get("status") or "unknown"),
        created_at=str(row.get("created_at") or ""),
        zoho_salesorder_number=(str(row["zoho_salesorder_number"]) if row.get("zoho_salesorder_number") else None),
        settlement_id=(str(row["settlement_id"]) if row.get("settlement_id") else None),
    )


def _invoices_for(snapshot: Snapshot, order_id: str) -> list[Invoice]:
    return [invoice for invoice in snapshot.invoices if invoice.salesorder_id == order_id]


def _payments_for(order: SalesOrder, book: RazorpayBook) -> list[RazorpayPayment]:
    keys = {order.number, order.id, *order.payment_ids}
    return [
        payment
        for payment in book.payments
        if payment.id in order.payment_ids or (payment.zoho_salesorder_number and payment.zoho_salesorder_number in keys)
    ]


def _best_payment(payments: list[RazorpayPayment]) -> RazorpayPayment | None:
    if not payments:
        return None
    return sorted(payments, key=lambda payment: _STATUS_RANK.get(payment.status, 9))[0]


def _in_range(when: date, start: date | None, end: date | None) -> bool:
    if start and when < start:
        return False
    if end and when > end:
        return False
    return True


def reconcile_orders(
    snapshot: Snapshot,
    book: RazorpayBook,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    """Bucket orders by Zoho fulfillment and invoice state joined to Razorpay.

    The join key is the pay_/plink_ id stored on the Zoho order. When an export
    is loaded, its status wins. Without an export, a stored id is treated as a
    claimed capture and marked unverified.
    """

    start = date_from if date_from is not None else snapshot.as_of - timedelta(days=6)
    end = date_to if date_to is not None else snapshot.as_of
    if start > end:
        raise InvalidArgument("date_from must be on or before date_to.")
    buckets: dict[str, list[dict[str, Any]]] = {
        "paid_and_shipped": [],
        "paid_not_invoiced": [],
        "invoiced_but_unpaid": [],
        "refunded_stock_not_returned": [],
        "paid_not_shipped": [],
    }
    settled_ids = {
        payment_id
        for settlement in book.settlements
        if settlement.status == "processed"
        for payment_id in settlement.payment_ids
    }
    captured_not_settled: list[dict[str, Any]] = []
    for order in snapshot.orders:
        if order.status == "void" or not _in_range(order.date, start, end):
            continue
        invoices = _invoices_for(snapshot, order.id)
        linked = _payments_for(order, book) if book.loaded else []
        payment = _best_payment(linked)
        verified = payment is not None
        if payment is None and order.payment_ids:
            status = "captured"
            verified = False
            payment_ids = list(order.payment_ids)
        elif payment is None:
            if not any(invoice.balance > 0 and invoice.status in UNPAID for invoice in invoices):
                continue
            status = "none"
            payment_ids = []
        else:
            status = payment.status
            payment_ids = [payment.id]
        bucket = _bucket(order, invoices, status)
        if bucket is None:
            continue
        row = _row(order, invoices, status, payment_ids, verified, book.loaded, settled_ids)
        buckets[bucket].append(row)
        if status == "captured" and book.loaded and payment_ids and payment_ids[0] not in settled_ids:
            captured_not_settled.append(row)
    counts = {name: len(rows) for name, rows in buckets.items()}
    summary = (
        f"{counts['paid_and_shipped']} paid and shipped, "
        f"{counts['paid_not_invoiced']} paid but not invoiced, "
        f"{counts['invoiced_but_unpaid']} invoiced but unpaid, "
        f"{counts['refunded_stock_not_returned']} refunded without a stock return, "
        f"{counts['paid_not_shipped']} paid and not shipped."
    )
    if book.loaded:
        pending = len(captured_not_settled)
        word = "payment" if pending == 1 else "payments"
        summary += f" {pending} captured {word} are not in a processed settlement."
    else:
        summary += " No Razorpay export was loaded, so payment ids on Zoho orders are claimed, not verified."
    return {
        "summary_text": summary,
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "join_key": "Zoho reference_number or notes containing a Razorpay pay_ or plink_ id.",
        "razorpay_export_loaded": book.loaded,
        "counts": counts,
        "buckets": buckets,
        "captured_not_settled": captured_not_settled,
        "order_ids": [row["order_id"] for rows in buckets.values() for row in rows],
        "payment_ids": [payment_id for rows in buckets.values() for row in rows for payment_id in row["payment_ids"]],
    }


def _bucket(order: SalesOrder, invoices: list[Invoice], status: str) -> str | None:
    has_invoice = bool(invoices)
    settled = has_invoice and all(invoice.status == "paid" and invoice.balance == 0 for invoice in invoices)
    open_invoice = any(invoice.balance > 0 and invoice.status in UNPAID for invoice in invoices)
    shipped = _fulfilled(order)
    if status == "refunded" and not order.stock_returned:
        return "refunded_stock_not_returned"
    if status == "captured" and not has_invoice:
        return "paid_not_invoiced"
    if open_invoice:
        return "invoiced_but_unpaid"
    if status == "captured" and shipped and settled:
        return "paid_and_shipped"
    if status == "captured" and not shipped and settled:
        return "paid_not_shipped"
    return None


def _row(
    order: SalesOrder,
    invoices: list[Invoice],
    status: str,
    payment_ids: list[str],
    verified: bool,
    export_loaded: bool,
    settled_ids: set[str],
) -> dict[str, Any]:
    settlement = "not_in_export"
    if export_loaded and payment_ids:
        settlement = "processed" if payment_ids[0] in settled_ids else "not_settled"
    razorpay_status = status if verified or not export_loaded else "referenced_not_verified"
    if not verified and order.payment_ids:
        razorpay_status = "referenced_not_verified"
    return {
        "order_id": order.id,
        "order_number": order.number,
        "total": str(order.total),
        "currency": order.currency,
        "shipped": _fulfilled(order),
        "payment_ids": payment_ids,
        "razorpay_status": razorpay_status if status != "none" else "none",
        "razorpay_verified": verified,
        "settlement_status": settlement,
        "invoices": [
            {"number": invoice.number, "status": invoice.status, "balance": str(invoice.balance)}
            for invoice in invoices
        ],
    }


def dead_stock(snapshot: Snapshot, *, days: int = 30) -> dict[str, Any]:
    if days < 1 or days > 365:
        raise InvalidArgument("days must be between 1 and 365.")
    start = snapshot.as_of - timedelta(days=days)
    sold: set[str] = set()
    for order in snapshot.orders:
        if order.status == "void" or not (start < order.date <= snapshot.as_of):
            continue
        for line in order.line_items:
            sold.add(line.sku)
    rows = []
    tied = Decimal("0")
    for item in snapshot.items:
        if item.sku in sold or item.on_hand <= 0:
            continue
        rate = item.purchase_rate if item.purchase_rate is not None else item.selling_rate
        value = (Decimal(item.on_hand) * rate) if rate is not None else None
        if value is not None:
            tied += value
        rows.append(
            {
                "sku": item.sku,
                "name": item.name,
                "on_hand": item.on_hand,
                "purchase_rate": str(rate) if rate is not None else None,
                "value_tied_up": str(value.quantize(Decimal("0.01"))) if value is not None else None,
                "basis": "purchase_rate" if item.purchase_rate is not None else "selling_rate",
            }
        )
    rows.sort(key=lambda row: Decimal(row["value_tied_up"] or "0"), reverse=True)
    noun = "SKU" if len(rows) == 1 else "SKUs"
    summary = (
        f"{len(rows)} {noun} have not sold in {days} days. "
        f"About {format_money(tied)} is tied up at the rate on file."
        if rows
        else f"No unsold stock in the last {days} days."
    )
    return {
        "summary_text": summary,
        "days": days,
        "value_tied_up": str(tied.quantize(Decimal("0.01"))),
        "items": rows,
        "item_ids": [item.id for item in snapshot.items if item.sku in {row["sku"] for row in rows}],
    }


def gst_summary(snapshot: Snapshot, *, period: str | None = None, date_from: date | None = None, date_to: date | None = None) -> dict[str, Any]:
    start, end, label = _period(snapshot, period, date_from, date_to)
    by_rate: dict[str, dict[str, Any]] = {}
    invoice_ids: list[str] = []
    for invoice in snapshot.invoices:
        if invoice.status == "void" or not _in_range(invoice.date, start, end):
            continue
        if invoice.tax_amount <= 0:
            continue
        invoice_ids.append(invoice.id)
        key = str(invoice.tax_rate)
        slot = by_rate.setdefault(key, {"tax_rate": key, "tax_amount": Decimal("0"), "invoice_count": 0, "invoice_total": Decimal("0")})
        slot["tax_amount"] += invoice.tax_amount
        slot["invoice_total"] += invoice.total
        slot["invoice_count"] += 1
    rates = []
    tax_total = Decimal("0")
    for slot in sorted(by_rate.values(), key=lambda row: Decimal(row["tax_rate"])):
        tax_total += slot["tax_amount"]
        rates.append(
            {
                "tax_rate": slot["tax_rate"],
                "tax_amount": str(slot["tax_amount"].quantize(Decimal("0.01"))),
                "invoice_count": slot["invoice_count"],
                "invoice_total": str(slot["invoice_total"].quantize(Decimal("0.01"))),
            }
        )
    summary = f"GST collected in {label}: {format_money(tax_total)} across {len(invoice_ids)} invoices."
    return {
        "summary_text": summary,
        "period": label,
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "tax_total": str(tax_total.quantize(Decimal("0.01"))),
        "rates": rates,
        "invoice_ids": invoice_ids,
        "note": "Sum of tax_amount on non-void invoices. This is not a filed GSTR return.",
    }


def _period(
    snapshot: Snapshot,
    period: str | None,
    date_from: date | None,
    date_to: date | None,
) -> tuple[date, date, str]:
    if period:
        try:
            year, month = (int(part) for part in period.split("-", 1))
            start = date(year, month, 1)
        except (ValueError, TypeError) as exc:
            raise InvalidArgument("period must be YYYY-MM.") from exc
        if month == 12:
            end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(year, month + 1, 1) - timedelta(days=1)
        return start, end, period
    start = date_from or snapshot.as_of.replace(day=1)
    end = date_to or snapshot.as_of
    if start > end:
        raise InvalidArgument("date_from must be on or before date_to.")
    return start, end, f"{start.isoformat()} to {end.isoformat()}"


def detect_anomalies(snapshot: Snapshot, book: RazorpayBook, *, window_days: int = 14) -> dict[str, Any]:
    if window_days < 2 or window_days > 90:
        raise InvalidArgument("window_days must be between 2 and 90.")
    start = snapshot.as_of - timedelta(days=window_days)
    orders = [order for order in snapshot.orders if order.status != "void" and start < order.date <= snapshot.as_of]
    flags: list[dict[str, Any]] = []
    flags.extend(_spikes(orders))
    flags.extend(_discounts(snapshot, orders))
    flags.extend(_failed_then_paid(orders, book))
    summary = f"{len(flags)} anomaly flag(s) in the last {window_days} days." if flags else "No anomaly flags in the window."
    return {
        "summary_text": summary,
        "window_days": window_days,
        "flags": flags,
        "order_ids": sorted({order_id for flag in flags for order_id in flag.get("order_ids", [])}),
    }


def _spikes(orders: list[SalesOrder]) -> list[dict[str, Any]]:
    counts: dict[date, int] = {}
    for order in orders:
        counts[order.date] = counts.get(order.date, 0) + 1
    if len(counts) < 3:
        return []
    ordered = sorted(counts.values())
    median = ordered[len(ordered) // 2]
    flags = []
    for day, count in sorted(counts.items()):
        if count >= 4 and count > median * 2:
            flags.append(
                {
                    "type": "order_spike",
                    "severity": "medium",
                    "title": f"{count} orders on {day.isoformat()} versus a median day of {median}",
                    "order_ids": [order.id for order in orders if order.date == day],
                    "evidence": [f"count={count}", f"median={median}"],
                }
            )
    return flags


def _discounts(snapshot: Snapshot, orders: list[SalesOrder]) -> list[dict[str, Any]]:
    rates = {item.sku: item.selling_rate for item in snapshot.items if item.selling_rate is not None}
    flags = []
    for order in orders:
        for line in order.line_items:
            list_rate = rates.get(line.sku)
            if list_rate is None or list_rate <= 0:
                continue
            if line.rate < list_rate * Decimal("0.7"):
                flags.append(
                    {
                        "type": "unusual_discount",
                        "severity": "medium",
                        "title": f"{order.number} sold {line.sku} at {line.rate} against a list rate of {list_rate}",
                        "order_ids": [order.id],
                        "evidence": [f"rate={line.rate}", f"list_rate={list_rate}"],
                    }
                )
    return flags


def _failed_then_paid(orders: list[SalesOrder], book: RazorpayBook) -> list[dict[str, Any]]:
    if not book.loaded:
        return []
    flags = []
    for order in orders:
        linked = _payments_for(order, book)
        statuses = {payment.status for payment in linked}
        if "failed" in statuses and "captured" in statuses:
            flags.append(
                {
                    "type": "failed_then_paid",
                    "severity": "low",
                    "title": f"{order.number} has a failed Razorpay attempt and a later capture",
                    "order_ids": [order.id],
                    "evidence": [f"{payment.id}={payment.status}" for payment in linked],
                }
            )
    return flags
