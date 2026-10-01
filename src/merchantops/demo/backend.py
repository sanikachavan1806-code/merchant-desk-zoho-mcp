from __future__ import annotations

from merchantops.demo.catalog import Catalog, build_catalog
from merchantops.errors import NotFoundError
from merchantops.infrastructure.limiter import BudgetMeter
from merchantops.models import Contact, Item, Page, SalesOrder, Warehouse


class DemoBackend:
    """In-memory Mira Audio catalog. Same method shape as the live Zoho client."""

    name = "demo"

    def __init__(self, catalog: Catalog | None = None, meter: BudgetMeter | None = None) -> None:
        self.catalog = catalog or build_catalog()
        self.meter = meter

    async def _touch(self) -> None:
        if self.meter is not None:
            await self.meter.record()

    async def list_items(self, *, page: int, per_page: int, search_text: str | None = None) -> Page:
        await self._touch()
        rows = list(self.catalog.items)
        if search_text:
            needle = search_text.lower()
            rows = [item for item in rows if needle in item.sku.lower() or needle in item.name.lower()]
        return _page(rows, page, per_page)

    async def get_item(self, item_id: str) -> Item:
        await self._touch()
        for item in self.catalog.items:
            if item.id == item_id or item.sku == item_id:
                return item
        raise NotFoundError(f"No item '{item_id}' in the demo catalog.")

    async def list_orders(
        self,
        *,
        page: int,
        per_page: int,
        status: str | None = None,
        search_text: str | None = None,
        customer_id: str | None = None,
    ) -> Page:
        await self._touch()
        rows = list(self.catalog.orders)
        if status:
            rows = [order for order in rows if order.status == status]
        if customer_id:
            rows = [order for order in rows if order.customer_id == customer_id]
        if search_text:
            needle = search_text.lower()
            rows = [
                order
                for order in rows
                if needle in order.number.lower()
                or needle in order.customer_name.lower()
                or needle in " ".join(order.payment_ids).lower()
                or any(needle in line.sku.lower() or needle in line.name.lower() for line in order.line_items)
            ]
        return _page(rows, page, per_page)

    async def get_order(self, order_id: str) -> SalesOrder:
        await self._touch()
        for order in self.catalog.orders:
            if order.id == order_id or order.number == order_id:
                return order
        raise NotFoundError(f"No sales order '{order_id}' in the demo catalog.")

    async def list_invoices(
        self,
        *,
        page: int,
        per_page: int,
        status: str | None = None,
        search_text: str | None = None,
        customer_id: str | None = None,
    ) -> Page:
        await self._touch()
        rows = list(self.catalog.invoices)
        if status:
            rows = [invoice for invoice in rows if invoice.status == status]
        if customer_id:
            rows = [invoice for invoice in rows if invoice.customer_id == customer_id]
        if search_text:
            needle = search_text.lower()
            rows = [invoice for invoice in rows if needle in invoice.number.lower() or needle in (invoice.salesorder_id or "").lower()]
        return _page(rows, page, per_page)

    async def list_shipments(self, *, page: int, per_page: int, search_text: str | None = None) -> Page:
        await self._touch()
        rows = list(self.catalog.shipments)
        if search_text:
            needle = search_text.lower()
            rows = [row for row in rows if needle in row.number.lower() or needle in row.salesorder_id.lower()]
        return _page(rows, page, per_page)

    async def list_packages(self, *, page: int, per_page: int, search_text: str | None = None) -> Page:
        await self._touch()
        rows = list(self.catalog.packages)
        if search_text:
            needle = search_text.lower()
            rows = [row for row in rows if needle in row.salesorder_id.lower() or needle in row.id.lower()]
        return _page(rows, page, per_page)

    async def list_warehouses(self) -> list[Warehouse]:
        await self._touch()
        return list(self.catalog.warehouses)

    async def get_contact(self, contact_id: str) -> Contact:
        await self._touch()
        for contact in self.catalog.contacts:
            if contact.id == contact_id:
                return contact
        raise NotFoundError(f"No contact '{contact_id}' in the demo catalog.")


def _page(rows: list, page: int, per_page: int) -> Page:
    start = (page - 1) * per_page
    chunk = rows[start : start + per_page]
    return Page(items=chunk, page=page, per_page=per_page, has_more=start + per_page < len(rows))
