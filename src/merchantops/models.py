from __future__ import annotations

from datetime import date as Date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class WarehouseStock(FrozenModel):
    warehouse_id: str
    warehouse_name: str
    available: int
    on_hand: int


class Item(FrozenModel):
    id: str
    sku: str
    name: str
    available: int
    committed: int
    on_hand: int
    reorder_level: int
    selling_rate: Decimal | None = None
    purchase_rate: Decimal | None = None
    warehouses: list[WarehouseStock] = Field(default_factory=list)


class LineItem(FrozenModel):
    item_id: str
    sku: str
    name: str
    quantity: int
    rate: Decimal
    warehouse_id: str | None = None
    warehouse_name: str | None = None


class SalesOrder(FrozenModel):
    id: str
    number: str
    date: Date
    status: str
    shipment_date: Date | None = None
    customer_id: str
    customer_name: str
    currency: str = "INR"
    total: Decimal
    reference_number: str | None = None
    payment_ids: list[str] = Field(default_factory=list)
    invoiced_status: str = "not_invoiced"
    line_items: list[LineItem] = Field(default_factory=list)
    quantity_ordered: int = 0
    quantity_shipped: int = 0
    stock_returned: bool = True


class Invoice(FrozenModel):
    id: str
    number: str
    salesorder_id: str | None = None
    customer_id: str
    status: str
    total: Decimal
    balance: Decimal
    date: Date
    currency: str = "INR"
    tax_rate: Decimal = Decimal("0")
    tax_amount: Decimal = Decimal("0")


class Shipment(FrozenModel):
    id: str
    number: str
    salesorder_id: str
    status: str
    date: Date | None = None
    tracking_number: str | None = None
    warehouse_id: str | None = None


class Package(FrozenModel):
    id: str
    salesorder_id: str
    status: str
    date: Date | None = None


class Contact(FrozenModel):
    id: str
    name: str
    email: str | None = None
    phone: str | None = None
    company: str | None = None


class Warehouse(FrozenModel):
    id: str
    name: str
    city: str | None = None


class Page(FrozenModel):
    items: list[Any]
    page: int
    per_page: int
    has_more: bool


class TokenSet(FrozenModel):
    access_token: str
    refresh_token: str | None = None
    expires_at: str
    api_domain: str | None = None
    dc: str = "in"
