from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from merchantops.config import PER_MINUTE_PLATFORM_LIMIT, Settings, assert_read_only
from merchantops.errors import InvalidArgument, MerchantOpsError
from merchantops.finance import (
    RazorpayBook,
    dead_stock,
    detect_anomalies,
    gst_summary,
    load_razorpay_book,
    reconcile_orders,
)
from merchantops.formatting import counted, decode_cursor, dump_model, envelope, parse_date, project
from merchantops.infrastructure.audit import AuditLog
from merchantops.infrastructure.cache import TtlCache
from merchantops.infrastructure.clock import Clock
from merchantops.intelligence import (
    Snapshot,
    daily_brief,
    detect_operational_risks,
    explain_recommendation,
    find_alternate_fulfillment,
    match_order_to_payment,
    order_health,
    recommend_next_actions,
)
from merchantops.models import Item, SalesOrder
from merchantops.security import mask_email, mask_phone, refusal_for

logger = logging.getLogger("merchantops")

_AUDIT_REDACT = {"query", "search", "reason", "payload", "include_pii"}


class Service:
    def __init__(
        self,
        settings: Settings,
        backend,
        audit: AuditLog,
        clock: Clock | None = None,
        razorpay: RazorpayBook | None = None,
    ) -> None:
        self.settings = settings
        self.backend = backend
        self.audit = audit
        self.clock = clock or Clock()
        self.razorpay = razorpay if razorpay is not None else RazorpayBook.empty()
        self._snapshots = TtlCache(self.clock)

    async def load_snapshot(self) -> Snapshot:
        snapshot, _hit = await self._snapshots.get_or_set(
            "ops-snapshot",
            self.settings.cache_ttl_seconds,
            self._build_snapshot,
        )
        return snapshot

    async def _build_snapshot(self) -> Snapshot:
        orders, orders_cut = await self._collect("list_orders")
        items, items_cut = await self._collect("list_items")
        invoices, invoices_cut = await self._collect("list_invoices")
        shipments, shipments_cut = await self._collect("list_shipments")
        packages, packages_cut = await self._collect("list_packages")
        warehouses = await self.backend.list_warehouses()
        return Snapshot(
            as_of=self.settings.resolved_as_of(),
            orders=tuple(orders),
            items=tuple(items),
            invoices=tuple(invoices),
            shipments=tuple(shipments),
            packages=tuple(packages),
            warehouses=tuple(warehouses),
            truncated=any((orders_cut, items_cut, invoices_cut, shipments_cut, packages_cut)),
        )

    async def _collect(self, method: str, **filters: Any) -> tuple[list[Any], bool]:
        rows: list[Any] = []
        page = 1
        while page <= self.settings.max_scan_pages:
            result = await getattr(self.backend, method)(
                page=page,
                per_page=self.settings.page_size_cap,
                **filters,
            )
            rows.extend(result.items)
            if not result.has_more:
                return rows, False
            page += 1
        return rows, True

    async def _run(self, tool: str, args: dict[str, Any], handler) -> dict[str, Any]:
        started = time.perf_counter()
        before = self.backend.meter.daily_used if self.backend.meter is not None else 0
        try:
            payload = await handler()
        except MerchantOpsError as exc:
            await self._audit(tool, args, "error", exc.code, started)
            return {
                "summary": exc.message,
                "meta": {"read_only": True, "source": self.backend.name, "pii_redacted": True},
                "error": exc.to_dict(),
            }
        except Exception:
            logger.exception("tool %s failed", tool)
            await self._audit(tool, args, "error", "internal", started)
            return {
                "summary": "The tool failed before calling Zoho. Details were logged, not returned.",
                "meta": {"read_only": True, "source": self.backend.name, "pii_redacted": True},
                "error": {"code": "internal", "message": "Unexpected failure. See the server log."},
            }
        after = self.backend.meter.daily_used if self.backend.meter is not None else before
        if isinstance(payload, dict) and "meta" in payload:
            payload["meta"]["calls_used"] = after - before
            payload["meta"]["fetched_at"] = datetime.now(timezone.utc).isoformat()
        await self._audit(tool, args, "ok", None, started)
        return payload

    async def _audit(self, tool: str, args: dict[str, Any], status: str, error_code: str | None, started: float) -> None:
        public: dict[str, Any] = {}
        for key, value in args.items():
            if key in _AUDIT_REDACT:
                public[key] = "present" if value else "absent"
            else:
                public[key] = value
        await self.audit.write(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tool": tool,
                "status": status,
                "error_code": error_code,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "source": self.backend.name,
                "args": public,
                "pii_redacted": True,
            }
        )

    def _limit(self, limit: int | None) -> int:
        size = self.settings.default_page_size if limit is None else limit
        if size < 1 or size > self.settings.page_size_cap:
            raise InvalidArgument(f"limit must be between 1 and {self.settings.page_size_cap}.")
        return size

    def _list(
        self,
        *,
        summary: str,
        key: str,
        rows: list[Any],
        page: int,
        has_more: bool,
        fields: list[str] | None,
        truncated: bool = False,
    ) -> dict[str, Any]:
        records = [project(dump_model(row), fields) for row in rows]
        body: dict[str, Any] = {key: records, "has_more": has_more}
        if has_more:
            body["next_cursor"] = decode_note(page)
        if truncated:
            summary += " Scan hit the page cap."
        ids = [str(record.get("id") or record.get("number")) for record in records if isinstance(record, dict)]
        sources = [{"system": self.backend.name, "resource": key, "ids": ids}]
        return envelope(summary, body, source=self.backend.name, truncated=truncated, sources=sources)

    async def search_orders(
        self,
        query: str | None = None,
        status: str | None = None,
        customer_id: str | None = None,
        sku: str | None = None,
        warehouse_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        args = {
            "query": query,
            "status": status,
            "customer_id": customer_id,
            "sku": sku,
            "warehouse_id": warehouse_id,
            "date_from": date_from,
            "date_to": date_to,
            "cursor": cursor,
            "limit": limit,
            "fields": fields,
        }

        async def handler() -> dict[str, Any]:
            size = self._limit(limit)
            page = decode_cursor(cursor)
            start = parse_date(date_from, field="date_from")
            end = parse_date(date_to, field="date_to")
            local = any((sku, warehouse_id, start, end))
            if local:
                rows, truncated = await self._collect(
                    "list_orders",
                    status=status,
                    search_text=query,
                    customer_id=customer_id,
                )
                filtered = _filter_orders(rows, sku=sku, warehouse_id=warehouse_id, date_from=start, date_to=end)
                chunk, has_more = _slice(filtered, page, size)
                summary = f"{counted(len(chunk), 'sales order')} matched."
                return self._list(summary=summary, key="orders", rows=chunk, page=page, has_more=has_more, fields=fields, truncated=truncated)
            result = await self.backend.list_orders(
                page=page,
                per_page=size,
                status=status,
                search_text=query,
                customer_id=customer_id,
            )
            summary = f"{counted(len(result.items), 'sales order')} on this page."
            return self._list(
                summary=summary,
                key="orders",
                rows=result.items,
                page=page,
                has_more=result.has_more,
                fields=fields,
            )

        return await self._run("search_orders", args, handler)

    async def get_order(self, order_id: str, fields: list[str] | None = None) -> dict[str, Any]:
        async def handler() -> dict[str, Any]:
            if not order_id:
                raise InvalidArgument("order_id is required.")
            order = await self.backend.get_order(order_id)
            record = project(dump_model(order), fields)
            return envelope(
                f"{order.number} is {order.status}, total {order.total} {order.currency}.",
                {"order": record},
                source=self.backend.name,
            )

        return await self._run("get_order", {"order_id": order_id, "fields": fields}, handler)

    async def list_inventory(
        self,
        search: str | None = None,
        sku: str | None = None,
        warehouse_id: str | None = None,
        low_stock_only: bool = False,
        available_below: int | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        args = {
            "search": search,
            "sku": sku,
            "warehouse_id": warehouse_id,
            "low_stock_only": low_stock_only,
            "available_below": available_below,
            "cursor": cursor,
            "limit": limit,
            "fields": fields,
        }

        async def handler() -> dict[str, Any]:
            size = self._limit(limit)
            page = decode_cursor(cursor)
            rows, truncated = await self._collect("list_items", search_text=search)
            filtered = _filter_items(
                rows,
                sku=sku,
                warehouse_id=warehouse_id,
                low_stock_only=low_stock_only,
                available_below=available_below,
            )
            chunk, has_more = _slice(filtered, page, size)
            summary = f"{counted(len(chunk), 'item')} matched."
            if low_stock_only:
                summary += " low_stock_only compares total available stock with the item reorder level, not a single warehouse."
            return self._list(
                summary=summary,
                key="items",
                rows=chunk,
                page=page,
                has_more=has_more,
                fields=fields,
                truncated=truncated,
            )

        return await self._run("list_inventory", args, handler)

    async def get_inventory_item(self, item_id: str | None = None, sku: str | None = None) -> dict[str, Any]:
        async def handler() -> dict[str, Any]:
            key = item_id or sku
            if not key:
                raise InvalidArgument("Provide item_id or sku.")
            item = await self.backend.get_item(key)
            return envelope(
                f"{item.sku} has {item.available} available across warehouses.",
                {"item": dump_model(item)},
                source=self.backend.name,
            )

        return await self._run("get_inventory_item", {"item_id": item_id, "sku": sku}, handler)

    async def list_warehouses(self) -> dict[str, Any]:
        async def handler() -> dict[str, Any]:
            rows = await self.backend.list_warehouses()
            return envelope(
                f"{counted(len(rows), 'warehouse')}.",
                {"warehouses": [dump_model(row) for row in rows]},
                source=self.backend.name,
            )

        return await self._run("list_warehouses", {}, handler)

    async def list_invoices(
        self,
        status: str | None = None,
        customer_id: str | None = None,
        order_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        args = {
            "status": status,
            "customer_id": customer_id,
            "order_id": order_id,
            "date_from": date_from,
            "date_to": date_to,
            "cursor": cursor,
            "limit": limit,
        }

        async def handler() -> dict[str, Any]:
            size = self._limit(limit)
            page = decode_cursor(cursor)
            start = parse_date(date_from, field="date_from")
            end = parse_date(date_to, field="date_to")
            rows, truncated = await self._collect("list_invoices", status=status, customer_id=customer_id)
            if order_id:
                rows = [row for row in rows if row.salesorder_id == order_id or row.number == order_id]
            if start:
                rows = [row for row in rows if row.date >= start]
            if end:
                rows = [row for row in rows if row.date <= end]
            chunk, has_more = _slice(rows, page, size)
            return self._list(
                summary=f"{counted(len(chunk), 'invoice')} matched.",
                key="invoices",
                rows=chunk,
                page=page,
                has_more=has_more,
                fields=None,
                truncated=truncated,
            )

        return await self._run("list_invoices", args, handler)

    async def list_shipments(
        self,
        order_id: str | None = None,
        status: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        async def handler() -> dict[str, Any]:
            size = self._limit(limit)
            page = decode_cursor(cursor)
            rows, truncated = await self._collect("list_shipments")
            if order_id:
                rows = [row for row in rows if row.salesorder_id == order_id or row.number == order_id]
            if status:
                rows = [row for row in rows if row.status == status]
            chunk, has_more = _slice(rows, page, size)
            return self._list(
                summary=f"{counted(len(chunk), 'shipment')} matched.",
                key="shipments",
                rows=chunk,
                page=page,
                has_more=has_more,
                fields=None,
                truncated=truncated,
            )

        return await self._run("list_shipments", {"order_id": order_id, "status": status, "cursor": cursor, "limit": limit}, handler)

    async def get_customer(self, customer_id: str, include_pii: bool = False) -> dict[str, Any]:
        async def handler() -> dict[str, Any]:
            if not customer_id:
                raise InvalidArgument("customer_id is required.")
            contact = await self.backend.get_contact(customer_id)
            reveal = bool(include_pii and self.settings.reveal_pii)
            note = None
            if include_pii and not self.settings.reveal_pii:
                note = "ZOHO_REVEAL_PII is false, so the model cannot unmask phone or email."
            customer = {
                "id": contact.id,
                "name": contact.name,
                "company": contact.company,
                "email": contact.email if reveal else mask_email(contact.email),
                "phone": contact.phone if reveal else mask_phone(contact.phone),
            }
            body = {"customer": customer}
            if note:
                body["note"] = note
            return envelope(
                f"Contact {contact.name}. Phone and email are {'visible' if reveal else 'masked'}.",
                body,
                source=self.backend.name,
                pii_redacted=not reveal,
            )

        return await self._run("get_customer", {"customer_id": customer_id, "include_pii": include_pii}, handler)

    async def get_order_health(self, order_id: str) -> dict[str, Any]:
        async def handler() -> dict[str, Any]:
            if not order_id:
                raise InvalidArgument("order_id is required.")
            snapshot = await self.load_snapshot()
            health = order_health(snapshot, order_id)
            return envelope(
                f"{health['order_number']} is {health['health']}.",
                health,
                source=self.backend.name,
                truncated=snapshot.truncated,
            )

        return await self._run("get_order_health", {"order_id": order_id}, handler)

    async def detect_operational_risks(
        self,
        time_window_days: int = 2,
        horizon_days: int = 7,
        risk_types: list[str] | None = None,
        severity: str | None = None,
    ) -> dict[str, Any]:
        async def handler() -> dict[str, Any]:
            snapshot = await self.load_snapshot()
            report = detect_operational_risks(
                snapshot,
                time_window_days=time_window_days,
                horizon_days=horizon_days,
                risk_types=risk_types,
                severity=severity,
            )
            summary = report.pop("summary_text")
            return envelope(summary, report, source=self.backend.name, truncated=snapshot.truncated)

        return await self._run(
            "detect_operational_risks",
            {
                "time_window_days": time_window_days,
                "horizon_days": horizon_days,
                "risk_types": risk_types,
                "severity": severity,
            },
            handler,
        )

    async def find_alternate_fulfillment(self, sku: str, quantity: int, source_warehouse_id: str) -> dict[str, Any]:
        async def handler() -> dict[str, Any]:
            snapshot = await self.load_snapshot()
            result = find_alternate_fulfillment(snapshot, sku, quantity, source_warehouse_id)
            if result["source_can_fulfill"]:
                summary = f"{result['source_warehouse_name']} can fulfill {quantity} of {sku}."
            elif result["alternatives"]:
                names = ", ".join(row["warehouse_name"] for row in result["alternatives"])
                summary = f"{result['source_warehouse_name']} cannot fulfill {quantity} of {sku}. {names} can."
            else:
                summary = f"No scanned warehouse can fulfill {quantity} of {sku}."
            return envelope(summary, result, source=self.backend.name, truncated=snapshot.truncated)

        return await self._run(
            "find_alternate_fulfillment",
            {"sku": sku, "quantity": quantity, "source_warehouse_id": source_warehouse_id},
            handler,
        )

    async def recommend_next_actions(self, time_window_days: int = 2) -> dict[str, Any]:
        async def handler() -> dict[str, Any]:
            snapshot = await self.load_snapshot()
            report = recommend_next_actions(snapshot, time_window_days=time_window_days)
            summary = f"{len(report['actions'])} recommendations. None of them are executed."
            return envelope(summary, report, source=self.backend.name, truncated=snapshot.truncated)

        return await self._run("recommend_next_actions", {"time_window_days": time_window_days}, handler)

    async def explain_recommendation(self, recommendation_id: str) -> dict[str, Any]:
        async def handler() -> dict[str, Any]:
            if not recommendation_id:
                raise InvalidArgument("recommendation_id is required.")
            snapshot = await self.load_snapshot()
            explained = explain_recommendation(snapshot, recommendation_id)
            return envelope(explained["title"], explained, source=self.backend.name, truncated=snapshot.truncated)

        return await self._run("explain_recommendation", {"recommendation_id": recommendation_id}, handler)

    async def get_daily_operations_brief(self) -> dict[str, Any]:
        async def handler() -> dict[str, Any]:
            snapshot = await self.load_snapshot()
            report = daily_brief(snapshot)
            summary = report["brief"].split("\n", 2)[1] if "\n" in report["brief"] else report["brief"]
            return envelope(summary, report, source=self.backend.name, truncated=snapshot.truncated)

        return await self._run("get_daily_operations_brief", {}, handler)

    async def match_order_to_payment(
        self,
        payment_id: str | None = None,
        order_id: str | None = None,
        only_paid_not_invoiced: bool = False,
    ) -> dict[str, Any]:
        async def handler() -> dict[str, Any]:
            snapshot = await self.load_snapshot()
            report = match_order_to_payment(
                snapshot,
                payment_id=payment_id,
                order_id=order_id,
                only_paid_not_invoiced=only_paid_not_invoiced,
            )
            summary = report.pop("summary_text")
            return envelope(summary, report, source=self.backend.name, truncated=report.get("truncated", False))

        return await self._run(
            "match_order_to_payment",
            {"payment_id": payment_id, "order_id": order_id, "only_paid_not_invoiced": only_paid_not_invoiced},
            handler,
        )

    async def reconcile_orders(self, date_from: str | None = None, date_to: str | None = None) -> dict[str, Any]:
        async def handler() -> dict[str, Any]:
            snapshot = await self.load_snapshot()
            report = reconcile_orders(
                snapshot,
                self.razorpay,
                date_from=parse_date(date_from, field="date_from"),
                date_to=parse_date(date_to, field="date_to"),
            )
            summary = report.pop("summary_text")
            order_ids = report.pop("order_ids")
            payment_ids = report.pop("payment_ids")
            sources = [
                {"system": "zoho", "resource": "salesorders", "ids": order_ids},
                {"system": "razorpay_export" if self.razorpay.loaded else "zoho", "resource": "payments", "ids": payment_ids},
            ]
            return envelope(summary, report, source=self.backend.name, truncated=snapshot.truncated, sources=sources)

        return await self._run("reconcile_orders", {"date_from": date_from, "date_to": date_to}, handler)

    async def dead_stock(self, days: int = 30) -> dict[str, Any]:
        async def handler() -> dict[str, Any]:
            snapshot = await self.load_snapshot()
            report = dead_stock(snapshot, days=days)
            summary = report.pop("summary_text")
            item_ids = report.pop("item_ids")
            sources = [{"system": "zoho", "resource": "items", "ids": item_ids}]
            return envelope(summary, report, source=self.backend.name, truncated=snapshot.truncated, sources=sources)

        return await self._run("dead_stock", {"days": days}, handler)

    async def gst_summary(self, period: str | None = None, date_from: str | None = None, date_to: str | None = None) -> dict[str, Any]:
        async def handler() -> dict[str, Any]:
            snapshot = await self.load_snapshot()
            report = gst_summary(
                snapshot,
                period=period,
                date_from=parse_date(date_from, field="date_from"),
                date_to=parse_date(date_to, field="date_to"),
            )
            summary = report.pop("summary_text")
            sources = [{"system": "zoho", "resource": "invoices", "ids": report["invoice_ids"]}]
            return envelope(summary, report, source=self.backend.name, truncated=snapshot.truncated, sources=sources)

        return await self._run("gst_summary", {"period": period, "date_from": date_from, "date_to": date_to}, handler)

    async def detect_anomalies(self, window_days: int = 14) -> dict[str, Any]:
        async def handler() -> dict[str, Any]:
            snapshot = await self.load_snapshot()
            report = detect_anomalies(snapshot, self.razorpay, window_days=window_days)
            summary = report.pop("summary_text")
            sources = [{"system": "zoho", "resource": "salesorders", "ids": report["order_ids"]}]
            return envelope(summary, report, source=self.backend.name, truncated=snapshot.truncated, sources=sources)

        return await self._run("detect_anomalies", {"window_days": window_days}, handler)

    async def get_api_budget(self) -> dict[str, Any]:
        async def handler() -> dict[str, Any]:
            if self.backend.meter is None:
                raise InvalidArgument("This backend is not tracking API budget.")
            snap = self.backend.meter.snapshot(
                plan=self.settings.plan,
                budget_per_minute=self.settings.per_minute_budget,
                concurrency=self.settings.concurrency,
            )
            snap["per_minute_platform_limit"] = PER_MINUTE_PLATFORM_LIMIT
            snap["counting"] = (
                "logical reads against the fixture catalog"
                if self.backend.name == "demo"
                else "outbound HTTP attempts, including retries"
            )
            return envelope(snap["advice"], snap, source=self.backend.name)

        return await self._run("get_api_budget", {}, handler)

    async def propose_action(self, action_type: str, reason: str = "", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        async def handler() -> dict[str, Any]:
            if not action_type:
                raise InvalidArgument("action_type is required.")
            return envelope(
                "Refused. Nothing was changed in Zoho or Razorpay.",
                {
                    "executed": False,
                    "action_type": action_type,
                    "refusal": refusal_for(action_type),
                    "heard_reason": reason or None,
                    "payload_keys": sorted((payload or {}).keys()),
                },
                source=self.backend.name,
            )

        return await self._run("propose_action", {"action_type": action_type, "reason": reason, "payload": payload}, handler)


def _slice(rows: list[Any], page: int, size: int) -> tuple[list[Any], bool]:
    start = (page - 1) * size
    chunk = rows[start : start + size]
    return chunk, start + size < len(rows)


def decode_note(page: int) -> str:
    from merchantops.formatting import encode_cursor

    return encode_cursor(page + 1)


def _filter_orders(
    rows: list[SalesOrder],
    *,
    sku: str | None,
    warehouse_id: str | None,
    date_from,
    date_to,
) -> list[SalesOrder]:
    filtered: list[SalesOrder] = []
    for order in rows:
        if date_from and order.date < date_from:
            continue
        if date_to and order.date > date_to:
            continue
        if sku and not any(line.sku.lower() == sku.lower() for line in order.line_items):
            continue
        if warehouse_id and not any(line.warehouse_id == warehouse_id for line in order.line_items):
            continue
        filtered.append(order)
    return filtered


def _filter_items(
    rows: list[Item],
    *,
    sku: str | None,
    warehouse_id: str | None,
    low_stock_only: bool,
    available_below: int | None,
) -> list[Item]:
    filtered: list[Item] = []
    for item in rows:
        if sku and item.sku.lower() != sku.lower():
            continue
        if warehouse_id and not any(stock.warehouse_id == warehouse_id for stock in item.warehouses):
            continue
        if low_stock_only and item.available > item.reorder_level:
            continue
        if available_below is not None and item.available >= available_below:
            continue
        filtered.append(item)
    return filtered


def build_service(settings: Settings, *, clock: Clock | None = None, http=None) -> Service:
    assert_read_only(settings)
    clock = clock or Clock()
    from merchantops.infrastructure.limiter import BudgetMeter

    meter = BudgetMeter(
        daily_limit=settings.resolved_daily_limit(),
        per_minute_limit=PER_MINUTE_PLATFORM_LIMIT,
        clock=clock,
    )
    audit = AuditLog(settings.audit_log_path)
    if settings.mode == "demo":
        from merchantops.demo.backend import DemoBackend

        backend = DemoBackend(meter=meter)
    else:
        import httpx

        from merchantops.auth.provider import provider_from_settings
        from merchantops.infrastructure.limiter import TokenBucket
        from merchantops.zoho.client import ZohoClient

        client = http or httpx.AsyncClient(timeout=20)
        backend = ZohoClient(
            token_provider=provider_from_settings(settings, client),
            organization_id=settings.organization_id,
            dc=settings.zoho_dc,
            meter=meter,
            bucket=TokenBucket(
                rate_per_minute=settings.per_minute_budget,
                capacity=settings.per_minute_budget,
                clock=clock,
                sleeper=asyncio.sleep,
            ),
            cache=TtlCache(clock),
            concurrency=settings.concurrency,
            cache_ttl=settings.cache_ttl_seconds,
            warehouse_cache_ttl=settings.warehouse_cache_ttl_seconds,
            http=client,
        )
    from merchantops.demo.razorpay_export import DEMO_RAZORPAY_EXPORT

    fallback = DEMO_RAZORPAY_EXPORT if settings.mode == "demo" and not settings.razorpay_export_path else None
    razorpay = load_razorpay_book(settings.razorpay_export_path or None, demo_fallback=fallback)
    return Service(settings, backend, audit, clock, razorpay=razorpay)
