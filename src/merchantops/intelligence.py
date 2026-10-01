from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from merchantops.errors import InvalidArgument, NotFoundError
from merchantops.formatting import format_money
from merchantops.models import Invoice, Item, Package, SalesOrder, Shipment, Warehouse

LOOKBACK_DAYS = 7
OPEN_STATUSES = {"confirmed", "pending", "partially_shipped", "open"}
UNPAID_INVOICE_STATUSES = {"unpaid", "overdue", "partially_paid", "sent"}
RISK_TYPES = ("stockout", "fulfillment", "revenue", "imbalance", "slow_moving")


@dataclass(frozen=True)
class Snapshot:
    as_of: date
    orders: tuple[SalesOrder, ...]
    items: tuple[Item, ...]
    invoices: tuple[Invoice, ...]
    shipments: tuple[Shipment, ...]
    packages: tuple[Package, ...]
    warehouses: tuple[Warehouse, ...]
    truncated: bool


def _item_by_sku(snapshot: Snapshot) -> dict[str, Item]:
    return {item.sku: item for item in snapshot.items}


def _invoices_for(snapshot: Snapshot, order_id: str) -> list[Invoice]:
    return [invoice for invoice in snapshot.invoices if invoice.salesorder_id == order_id]


def _has_package(snapshot: Snapshot, order_id: str) -> bool:
    return any(package.salesorder_id == order_id for package in snapshot.packages)


def _fulfilled(order: SalesOrder) -> bool:
    if order.status in {"shipped", "closed", "fulfilled"}:
        return True
    return order.quantity_ordered > 0 and order.quantity_shipped >= order.quantity_ordered


def _demand(snapshot: Snapshot, sku: str, warehouse_id: str | None) -> int:
    start = snapshot.as_of - timedelta(days=LOOKBACK_DAYS)
    total = 0
    for order in snapshot.orders:
        if order.status == "void" or not (start < order.date <= snapshot.as_of):
            continue
        for line in order.line_items:
            if line.sku != sku:
                continue
            if warehouse_id and line.warehouse_id != warehouse_id:
                continue
            total += line.quantity
    return total


def _cover(available: int, demand: int) -> Decimal | None:
    if demand <= 0:
        return None
    days = (Decimal(available) / (Decimal(demand) / Decimal(LOOKBACK_DAYS))).quantize(Decimal("0.1"))
    return days


def _when(days_until: int) -> str:
    if days_until == 0:
        return "today"
    if days_until < 0:
        return "overdue"
    unit = "day" if days_until == 1 else "days"
    return f"in {days_until} {unit}"


def _cover_phrase(days: Decimal | None, available: int) -> str:
    if available <= 0:
        return "already out of stock"
    if days is None:
        return "no recent sales"
    if days == days.to_integral_value():
        shown = str(int(days))
    else:
        shown = f"{days}"
    return f"about {shown} days"


def _finding(
    *,
    risk_id: str,
    risk_type: str,
    severity: str,
    title: str,
    detail: str,
    evidence: list[str],
    order_number: str | None = None,
    sku: str | None = None,
    amount: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": risk_id,
        "type": risk_type,
        "severity": severity,
        "title": title,
        "detail": detail,
        "evidence": evidence,
    }
    if order_number:
        body["order_number"] = order_number
    if sku:
        body["sku"] = sku
    if amount:
        body["amount"] = amount
    return body


def stockout_findings(snapshot: Snapshot, horizon_days: int) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for item in snapshot.items:
        locations = item.warehouses or [
            type("W", (), {"warehouse_id": None, "warehouse_name": "all warehouses", "available": item.available})()
        ]
        for stock in locations:
            demand = _demand(snapshot, item.sku, stock.warehouse_id)
            if stock.available <= 0 and demand <= 0:
                continue
            days = _cover(stock.available, demand)
            below_reorder = stock.available < item.reorder_level and demand > 0
            short_cover = days is not None and days <= Decimal(horizon_days)
            if stock.available > 0 and not short_cover and not below_reorder:
                continue
            if stock.available > 0 and days is None and not below_reorder:
                continue
            if stock.available <= 0 or (days is not None and days <= Decimal(2)):
                severity = "high"
            elif short_cover:
                severity = "medium"
            else:
                severity = "low"
            phrase = _cover_phrase(days, stock.available)
            place = stock.warehouse_name
            if stock.available <= 0:
                title = f"{item.sku} at {place} is already out of stock"
            else:
                title = f"{item.sku} at {place} runs out in {phrase}"
            findings.append(
                _finding(
                    risk_id=f"stockout:{item.sku}:{stock.warehouse_id or 'all'}",
                    risk_type="stockout",
                    severity=severity,
                    sku=item.sku,
                    title=title,
                    detail=(
                        f"{item.name}: {stock.available} available at {place}, "
                        f"reorder point {item.reorder_level}, {demand} units sold in the last {LOOKBACK_DAYS} days."
                    ),
                    evidence=[
                        f"available={stock.available}",
                        f"demand_{LOOKBACK_DAYS}d={demand}",
                        f"days_of_cover={days if days is not None else 'n/a'}",
                        f"reorder_level={item.reorder_level}",
                    ],
                )
            )
    return findings


def fulfillment_findings(snapshot: Snapshot, time_window_days: int) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for order in snapshot.orders:
        if order.status in {"void", "draft", "closed"} or _fulfilled(order) or order.shipment_date is None:
            continue
        days_until = (order.shipment_date - snapshot.as_of).days
        if days_until > time_window_days:
            continue
        severity = "high" if days_until <= 0 else "medium"
        when = _when(days_until)
        package = "no package yet" if not _has_package(snapshot, order.id) else "package exists"
        sku = ", ".join(line.sku for line in order.line_items)
        findings.append(
            _finding(
                risk_id=f"fulfill:{order.number}",
                risk_type="fulfillment",
                severity=severity,
                order_number=order.number,
                sku=sku,
                title=f"{order.number} ships {when} and is not fully shipped",
                detail=f"Shipment date {order.shipment_date.isoformat()}, status {order.status}, {package}.",
                evidence=[
                    f"shipment_date={order.shipment_date.isoformat()}",
                    f"quantity_ordered={order.quantity_ordered}",
                    f"quantity_shipped={order.quantity_shipped}",
                    f"package={'yes' if _has_package(snapshot, order.id) else 'no'}",
                ],
            )
        )
    return findings


def revenue_findings(snapshot: Snapshot) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for order in snapshot.orders:
        if not _fulfilled(order) or order.status == "void":
            continue
        invoices = _invoices_for(snapshot, order.id)
        open_invoices = [
            invoice
            for invoice in invoices
            if invoice.status in UNPAID_INVOICE_STATUSES and invoice.balance > 0
        ]
        if not open_invoices:
            continue
        balance = sum((invoice.balance for invoice in open_invoices), Decimal("0"))
        labels = ", ".join(f"{invoice.number} ({invoice.status})" for invoice in open_invoices)
        payment = order.payment_ids[0] if order.payment_ids else None
        payment_note = f" Razorpay reference {payment} is on the order." if payment else ""
        findings.append(
            _finding(
                risk_id=f"collect:{order.number}",
                risk_type="revenue",
                severity="high",
                order_number=order.number,
                amount=str(balance),
                title=f"{order.number} is fulfilled with {format_money(balance, order.currency)} still open",
                detail=f"Invoices: {labels}.{payment_note}",
                evidence=[
                    f"order_status={order.status}",
                    *[f"{invoice.number}={invoice.status}:{invoice.balance}" for invoice in open_invoices],
                    *([f"razorpay={payment}"] if payment else []),
                ],
            )
        )
    return findings


def imbalance_findings(snapshot: Snapshot) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for item in snapshot.items:
        if len(item.warehouses) < 2:
            continue
        scored: list[tuple[Any, Decimal | None, int]] = []
        for stock in item.warehouses:
            demand = _demand(snapshot, item.sku, stock.warehouse_id)
            scored.append((stock, _cover(stock.available, demand), demand))
        for source, source_cover, _demand_qty in scored:
            if source.available > 0 and (source_cover is None or source_cover > Decimal(3)):
                continue
            for target, target_cover, _target_demand in scored:
                if target.warehouse_id == source.warehouse_id:
                    continue
                target_comfortable = target.available >= 10 and (target_cover is None or target_cover >= Decimal(14))
                if not target_comfortable:
                    continue
                findings.append(
                    _finding(
                        risk_id=f"transfer:{item.sku}:{source.warehouse_id}:{target.warehouse_id}",
                        risk_type="imbalance",
                        severity="medium",
                        sku=item.sku,
                        title=f"{item.sku} is tight in {source.warehouse_name} and comfortable in {target.warehouse_name}",
                        detail=(
                            f"{source.warehouse_name} has {source.available} available "
                            f"({_cover_phrase(source_cover, source.available)}). "
                            f"{target.warehouse_name} has {target.available} available "
                            f"({_cover_phrase(target_cover, target.available)}). "
                            "This is a recommendation, not a stock transfer."
                        ),
                        evidence=[
                            f"{source.warehouse_name}_available={source.available}",
                            f"{target.warehouse_name}_available={target.available}",
                            f"{source.warehouse_name}_cover={source_cover}",
                            f"{target.warehouse_name}_cover={target_cover}",
                        ],
                    )
                )
    return findings


def slow_moving_findings(snapshot: Snapshot) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for item in snapshot.items:
        demand = _demand(snapshot, item.sku, None)
        velocity = Decimal(demand) / Decimal(LOOKBACK_DAYS)
        if item.on_hand < 80 or velocity >= Decimal("0.3"):
            continue
        findings.append(
            _finding(
                risk_id=f"slow:{item.sku}",
                risk_type="slow_moving",
                severity="low",
                sku=item.sku,
                title=f"{item.sku} is slow-moving ({item.on_hand} on hand)",
                detail=f"{demand} units sold in {LOOKBACK_DAYS} days across warehouses. Do not replenish this SKU first.",
                evidence=[f"on_hand={item.on_hand}", f"demand_{LOOKBACK_DAYS}d={demand}"],
            )
        )
    return findings


def collect_findings(
    snapshot: Snapshot,
    *,
    time_window_days: int = 2,
    horizon_days: int = 7,
    risk_types: set[str] | None = None,
) -> list[dict[str, Any]]:
    selected = set(risk_types or RISK_TYPES)
    unknown = selected - set(RISK_TYPES)
    if unknown:
        raise InvalidArgument(f"Unknown risk_types: {', '.join(sorted(unknown))}. Use {', '.join(RISK_TYPES)}.")
    findings: list[dict[str, Any]] = []
    if "stockout" in selected:
        findings.extend(stockout_findings(snapshot, horizon_days))
    if "fulfillment" in selected:
        findings.extend(fulfillment_findings(snapshot, time_window_days))
    if "revenue" in selected:
        findings.extend(revenue_findings(snapshot))
    if "imbalance" in selected:
        findings.extend(imbalance_findings(snapshot))
    if "slow_moving" in selected:
        findings.extend(slow_moving_findings(snapshot))
    rank = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda row: (rank.get(row["severity"], 9), row["type"], row["id"]))
    return findings


def detect_operational_risks(
    snapshot: Snapshot,
    *,
    time_window_days: int = 2,
    horizon_days: int = 7,
    risk_types: list[str] | None = None,
    severity: str | None = None,
) -> dict[str, Any]:
    if time_window_days < 0 or time_window_days > 30:
        raise InvalidArgument("time_window_days must be between 0 and 30.")
    if horizon_days < 1 or horizon_days > 30:
        raise InvalidArgument("horizon_days must be between 1 and 30.")
    if severity and severity not in {"high", "medium", "low"}:
        raise InvalidArgument("severity must be high, medium, or low.")
    findings = collect_findings(
        snapshot,
        time_window_days=time_window_days,
        horizon_days=horizon_days,
        risk_types=set(risk_types) if risk_types else None,
    )
    if severity:
        findings = [row for row in findings if row["severity"] == severity]
    counts: dict[str, int] = {}
    for row in findings:
        counts[row["type"]] = counts.get(row["type"], 0) + 1
    parts = [f"{count} {name}" for name, count in counts.items()]
    summary = "No operational risks in the scanned window." if not findings else "Risks: " + ", ".join(parts) + "."
    if snapshot.truncated:
        summary += " The scan hit the page cap, so this is not the whole catalog."
    return {
        "as_of": snapshot.as_of.isoformat(),
        "summary_text": summary,
        "counts": counts,
        "risks": findings,
        "truncated": snapshot.truncated,
    }


def _stock_shortfalls(snapshot: Snapshot, order: SalesOrder) -> list[str]:
    items = _item_by_sku(snapshot)
    reasons: list[str] = []
    for line in order.line_items:
        item = items.get(line.sku)
        if item is None:
            reasons.append(f"{line.sku} was not in the scanned item pages")
            continue
        available = item.available
        place = "all warehouses"
        if line.warehouse_id:
            match = next((stock for stock in item.warehouses if stock.warehouse_id == line.warehouse_id), None)
            if match is not None:
                available = match.available
                place = match.warehouse_name
        if line.quantity > available:
            reasons.append(
                f"{line.sku} needs {line.quantity} at {place} but available is {available}"
            )
    return reasons


def order_health(snapshot: Snapshot, order_id: str) -> dict[str, Any]:
    order = next((row for row in snapshot.orders if row.id == order_id or row.number == order_id), None)
    if order is None:
        raise NotFoundError(
            f"Order '{order_id}' is not in the scanned pages. "
            "If the catalog is larger than the scan cap, call get_order and narrow the question."
            if snapshot.truncated
            else f"No sales order '{order_id}'."
        )
    reasons: list[dict[str, str]] = []
    for text in _stock_shortfalls(snapshot, order):
        reasons.append({"severity": "high", "text": text})
    if not _fulfilled(order) and order.shipment_date is not None and order.status not in {"void", "draft", "closed"}:
        days_until = (order.shipment_date - snapshot.as_of).days
        if days_until <= 2:
            severity = "high" if days_until <= 0 else "medium"
            when = _when(days_until)
            reasons.append({"severity": severity, "text": f"Shipment date is {when} ({order.shipment_date.isoformat()}) and the order is not fully shipped"})
            if not _has_package(snapshot, order.id):
                reasons.append({"severity": "medium", "text": "No package has been created"})
    for invoice in _invoices_for(snapshot, order.id):
        if invoice.status in UNPAID_INVOICE_STATUSES and invoice.balance > 0:
            reasons.append(
                {
                    "severity": "high",
                    "text": f"{invoice.number} is {invoice.status} with {format_money(invoice.balance, invoice.currency)} open",
                }
            )
    if any(reason["severity"] == "high" for reason in reasons):
        health = "AT_RISK"
    elif reasons:
        health = "WATCH"
    else:
        health = "HEALTHY"
    actions = _actions_for_health(reasons, order)
    return {
        "order_id": order.id,
        "order_number": order.number,
        "health": health,
        "reasons": [reason["text"] for reason in reasons],
        "recommended_actions": actions,
        "executable": False,
    }


def _actions_for_health(reasons: list[dict[str, str]], order: SalesOrder) -> list[str]:
    actions: list[str] = []
    text = " ".join(reason["text"] for reason in reasons)
    if "needs" in text and "available" in text:
        actions.append("Check another warehouse before promising this shipment. Do not adjust stock from the agent.")
    if "Shipment date" in text:
        actions.append(f"Prioritize packing {order.number}. Creating the package is a write and is not exposed here.")
    if "open" in text or "unpaid" in text or "overdue" in text or "partially_paid" in text:
        actions.append("Follow up on the open invoice. Do not record a payment or send mail from this connector.")
    if not actions and not reasons:
        actions.append("No action. Leave the order alone.")
    return actions


def find_alternate_fulfillment(snapshot: Snapshot, sku: str, quantity: int, source_warehouse_id: str) -> dict[str, Any]:
    if quantity < 1:
        raise InvalidArgument("quantity must be at least 1.")
    item = _item_by_sku(snapshot).get(sku)
    if item is None:
        raise NotFoundError(f"No item with SKU '{sku}' in the scanned pages.")
    source = next((stock for stock in item.warehouses if stock.warehouse_id == source_warehouse_id), None)
    if source is None:
        raise NotFoundError(f"SKU '{sku}' has no stock row for warehouse '{source_warehouse_id}'.")
    source_cover = _cover(source.available, _demand(snapshot, sku, source.warehouse_id))
    alternatives = []
    for stock in item.warehouses:
        if stock.warehouse_id == source_warehouse_id or stock.available < quantity:
            continue
        cover = _cover(stock.available, _demand(snapshot, sku, stock.warehouse_id))
        alternatives.append(
            {
                "warehouse_id": stock.warehouse_id,
                "warehouse_name": stock.warehouse_name,
                "available": stock.available,
                "days_of_cover": float(cover) if cover is not None else None,
                "can_cover_quantity": True,
            }
        )
    source_ok = source.available >= quantity
    return {
        "sku": sku,
        "quantity": quantity,
        "source_warehouse_id": source.warehouse_id,
        "source_warehouse_name": source.warehouse_name,
        "source_available": source.available,
        "source_can_fulfill": source_ok,
        "source_days_of_cover": float(source_cover) if source_cover is not None else None,
        "fulfillment_possible": source_ok or bool(alternatives),
        "alternatives": alternatives,
        "note": "Availability only. This does not create a transfer or a package.",
    }


def recommend_next_actions(snapshot: Snapshot, *, time_window_days: int = 2, limit: int = 8) -> dict[str, Any]:
    findings = collect_findings(snapshot, time_window_days=time_window_days)
    actions: list[dict[str, Any]] = []
    for finding in findings:
        action_type, requires_approval = _recommendation_class(finding["type"])
        actions.append(
            {
                "id": finding["id"],
                "action_type": action_type,
                "priority": finding["severity"],
                "title": finding["title"],
                "reason": finding["detail"],
                "evidence": finding["evidence"],
                "requires_approval": requires_approval,
                "executable": False,
            }
        )
    shown = actions[:limit]
    return {
        "actions": shown,
        "omitted": max(0, len(actions) - len(shown)),
        "note": (
            "Recommendations are not executed. Replenishment and transfers would mutate "
            "Zoho and are refused by propose_action."
        ),
    }


def _recommendation_class(risk_type: str) -> tuple[str, bool]:
    if risk_type == "stockout":
        return "replenish", True
    if risk_type == "imbalance":
        return "transfer_stock", True
    if risk_type == "revenue":
        return "follow_up", False
    if risk_type == "fulfillment":
        return "prioritize_packing", False
    return "review", False


def explain_recommendation(snapshot: Snapshot, recommendation_id: str) -> dict[str, Any]:
    report = recommend_next_actions(snapshot, limit=100)
    match = next((action for action in report["actions"] if action["id"] == recommendation_id), None)
    if match is None:
        raise NotFoundError(
            f"No recommendation '{recommendation_id}'. Call recommend_next_actions and use one of its ids."
        )
    return {
        "recommendation_id": match["id"],
        "title": match["title"],
        "reason": match["reason"],
        "evidence": match["evidence"],
        "requires_approval": match["requires_approval"],
        "executable": False,
        "confidence_note": "Deterministic rules over Zoho fields and a 7-day demand window. Not a forecast model.",
    }


def daily_brief(snapshot: Snapshot) -> dict[str, Any]:
    risks = detect_operational_risks(snapshot)
    open_orders = [order for order in snapshot.orders if order.status in OPEN_STATUSES]
    order_value = sum((order.total for order in open_orders), Decimal("0"))
    lines = [
        f"DAILY MERCHANT BRIEF — {snapshot.as_of.isoformat()}",
        f"Open orders in view: {len(open_orders)} totaling {format_money(order_value)}.",
        risks["summary_text"],
    ]
    for risk in risks["risks"]:
        if risk["severity"] == "low":
            continue
        lines.append(f"• [{risk['severity']}] {risk['title']}")
    if snapshot.truncated:
        lines.append("• Scan truncated at the page cap. Do not treat this as the full catalog.")
    lines.append("No writes were performed.")
    return {
        "as_of": snapshot.as_of.isoformat(),
        "brief": "\n".join(lines),
        "open_orders": len(open_orders),
        "open_order_value": str(order_value),
        "counts": risks["counts"],
        "highlights": [risk["title"] for risk in risks["risks"] if risk["severity"] != "low"],
    }


def match_order_to_payment(
    snapshot: Snapshot,
    *,
    payment_id: str | None = None,
    order_id: str | None = None,
    only_paid_not_invoiced: bool = False,
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for order in snapshot.orders:
        if order.status == "void":
            continue
        if payment_id and payment_id not in order.payment_ids:
            continue
        if order_id and order_id not in {order.id, order.number}:
            continue
        invoices = _invoices_for(snapshot, order.id)
        fully_settled = bool(invoices) and all(invoice.status == "paid" and invoice.balance == 0 for invoice in invoices)
        has_invoice = bool(invoices) or order.invoiced_status == "invoiced"
        paid_not_invoiced = bool(order.payment_ids) and not invoices
        if payment_id or order_id:
            include = True
        elif only_paid_not_invoiced:
            include = paid_not_invoiced
        else:
            include = bool(order.payment_ids) and not fully_settled
        if not include:
            continue
        if not order.payment_ids and not payment_id:
            continue
        matches.append(
            {
                "order_id": order.id,
                "order_number": order.number,
                "status": order.status,
                "total": str(order.total),
                "currency": order.currency,
                "payment_ids": order.payment_ids,
                "invoiced": has_invoice and bool(invoices),
                "invoices": [
                    {"number": invoice.number, "status": invoice.status, "balance": str(invoice.balance)}
                    for invoice in invoices
                ],
                "paid_on_razorpay_not_invoiced": paid_not_invoiced,
                "settled_in_zoho": fully_settled,
            }
        )
    if payment_id and not matches:
        summary = f"No scanned sales order references {payment_id}."
    elif only_paid_not_invoiced:
        summary = (
            f"{len(matches)} order(s) carry a Razorpay payment id and have no Zoho invoice."
            if matches
            else "No paid-but-not-invoiced orders in the scanned pages."
        )
    else:
        summary = f"{len(matches)} Razorpay-linked order(s) are not fully settled in Zoho."
    return {"matches": matches, "summary_text": summary, "truncated": snapshot.truncated}
