from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from merchantops.config import DEMO_AS_OF
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

Rate = Decimal


def _item(
    item_id: str,
    sku: str,
    name: str,
    reorder: int,
    warehouses: list[tuple[str, str, int, int]],
) -> Item:
    stocks = [
        WarehouseStock(warehouse_id=wh_id, warehouse_name=wh_name, available=available, on_hand=on_hand)
        for wh_id, wh_name, available, on_hand in warehouses
    ]
    return Item(
        id=item_id,
        sku=sku,
        name=name,
        available=sum(stock.available for stock in stocks),
        committed=sum(stock.on_hand - stock.available for stock in stocks),
        on_hand=sum(stock.on_hand for stock in stocks),
        reorder_level=reorder,
        selling_rate=_RATES.get(sku),
        purchase_rate=_COSTS.get(sku),
        warehouses=stocks,
    )


def _order(
    *,
    order_id: str,
    number: str,
    when: str,
    status: str,
    customer_id: str,
    customer_name: str,
    item: Item,
    quantity: int,
    warehouse_id: str,
    shipment_date: str | None = None,
    invoiced_status: str = "not_invoiced",
    quantity_shipped: int = 0,
    payment_ids: tuple[str, ...] = (),
    rate_override: str | None = None,
    stock_returned: bool = True,
) -> SalesOrder:
    warehouse_name = next(stock.warehouse_name for stock in item.warehouses if stock.warehouse_id == warehouse_id)
    rate = Rate(rate_override) if rate_override else _RATES[item.sku]
    line = LineItem(
        item_id=item.id,
        sku=item.sku,
        name=item.name,
        quantity=quantity,
        rate=rate,
        warehouse_id=warehouse_id,
        warehouse_name=warehouse_name,
    )
    return SalesOrder(
        id=order_id,
        number=number,
        date=date.fromisoformat(when),
        status=status,
        shipment_date=date.fromisoformat(shipment_date) if shipment_date else None,
        customer_id=customer_id,
        customer_name=customer_name,
        currency="INR",
        total=(rate * quantity).quantize(Decimal("0.01")),
        reference_number=payment_ids[0] if payment_ids else None,
        payment_ids=list(payment_ids),
        invoiced_status=invoiced_status,
        line_items=[line],
        quantity_ordered=quantity,
        quantity_shipped=quantity_shipped,
        stock_returned=stock_returned,
    )


_RATES = {
    "SKU-EARBUD-PRO": Rate("1999"),
    "SKU-SPEAKER-MINI": Rate("2499"),
    "SKU-CABLE-C": Rate("299"),
    "SKU-CASE-BLK": Rate("499"),
    "SKU-STAND-OLD": Rate("799"),
}

_COSTS = {
    "SKU-EARBUD-PRO": Rate("900"),
    "SKU-SPEAKER-MINI": Rate("1100"),
    "SKU-CABLE-C": Rate("40"),
    "SKU-CASE-BLK": Rate("80"),
    "SKU-STAND-OLD": Rate("250"),
}


@dataclass(frozen=True)
class Catalog:
    as_of: date
    items: tuple[Item, ...]
    orders: tuple[SalesOrder, ...]
    invoices: tuple[Invoice, ...]
    shipments: tuple[Shipment, ...]
    packages: tuple[Package, ...]
    warehouses: tuple[Warehouse, ...]
    contacts: tuple[Contact, ...]


def build_catalog(as_of: date = DEMO_AS_OF) -> Catalog:
    """Mira Audio, a two-warehouse D2C brand, on the morning of 1 Oct 2026.

    The quantities are chosen so the intelligence layer's arithmetic is
    checkable: Mumbai earbuds cover exactly 4.0 days, Bengaluru speakers
    cover exactly 2.0 days, and one Razorpay payment has no invoice.
    """

    warehouses = (
        Warehouse(id="wh_mum", name="Mumbai", city="Mumbai"),
        Warehouse(id="wh_blr", name="Bengaluru", city="Bengaluru"),
    )
    earbud = _item(
        "it_earbud",
        "SKU-EARBUD-PRO",
        "Wireless Earbuds Pro",
        20,
        [("wh_mum", "Mumbai", 8, 14), ("wh_blr", "Bengaluru", 0, 2)],
    )
    speaker = _item(
        "it_speaker",
        "SKU-SPEAKER-MINI",
        "Mini Bluetooth Speaker",
        10,
        [("wh_mum", "Mumbai", 40, 45), ("wh_blr", "Bengaluru", 4, 6)],
    )
    cable = _item(
        "it_cable",
        "SKU-CABLE-C",
        "USB-C Cable",
        15,
        [("wh_mum", "Mumbai", 36, 40), ("wh_blr", "Bengaluru", 24, 28)],
    )
    case = _item(
        "it_case",
        "SKU-CASE-BLK",
        "Earbud Case",
        10,
        [("wh_mum", "Mumbai", 80, 80), ("wh_blr", "Bengaluru", 40, 40)],
    )
    stand = _item(
        "it_stand",
        "SKU-STAND-OLD",
        "Acrylic Display Stand",
        10,
        [("wh_mum", "Mumbai", 25, 25), ("wh_blr", "Bengaluru", 15, 15)],
    )
    items = (earbud, speaker, cable, case, stand)
    rahul = ("cus_rahul", "Rahul Shah")
    meera = ("cus_meera", "Meera Iyer")
    anita = ("cus_anita", "Anita Desai")
    history = []
    cycle = (
        (earbud, "wh_mum"),
        (speaker, "wh_blr"),
        (cable, "wh_mum"),
        (case, "wh_mum"),
        (speaker, "wh_mum"),
        (cable, "wh_blr"),
    )
    people = (rahul, meera, anita)
    day = date(2026, 9, 2)
    skips = {date(2026, 9, 7), date(2026, 9, 14)}
    seq = 0
    while day <= date(2026, 9, 24):
        if day not in skips:
            item, warehouse_id = cycle[seq % len(cycle)]
            person = people[seq % len(people)]
            qty = 1 + (seq % 3)
            stamp = day.isoformat()
            history.append(
                _order(
                    order_id=f"so_08{seq + 1:02d}",
                    number=f"SO-08{seq + 1:02d}",
                    when=stamp,
                    status="closed",
                    customer_id=person[0],
                    customer_name=person[1],
                    item=item,
                    quantity=qty,
                    warehouse_id=warehouse_id,
                    shipment_date=stamp,
                    invoiced_status="invoiced",
                    quantity_shipped=qty,
                )
            )
            seq += 1
        day += timedelta(days=1)
    orders = (
        *history,
        # History that sets demand. Closed orders are not "today's problems".
        _order(order_id="so_0901", number="SO-0901", when="2026-09-28", status="closed", customer_id=rahul[0], customer_name=rahul[1], item=earbud, quantity=9, warehouse_id="wh_mum", shipment_date="2026-09-28", invoiced_status="invoiced", quantity_shipped=9),
        _order(order_id="so_0902", number="SO-0902", when="2026-09-26", status="closed", customer_id=meera[0], customer_name=meera[1], item=speaker, quantity=6, warehouse_id="wh_blr", shipment_date="2026-09-26", invoiced_status="invoiced", quantity_shipped=6),
        _order(order_id="so_0903", number="SO-0903", when="2026-09-27", status="closed", customer_id=rahul[0], customer_name=rahul[1], item=speaker, quantity=7, warehouse_id="wh_mum", shipment_date="2026-09-27", invoiced_status="invoiced", quantity_shipped=7),
        _order(order_id="so_0904", number="SO-0904", when="2026-09-29", status="closed", customer_id=anita[0], customer_name=anita[1], item=cable, quantity=5, warehouse_id="wh_mum", shipment_date="2026-09-29", invoiced_status="invoiced", quantity_shipped=5, payment_ids=("pay_Shipped0904",)),
        _order(order_id="so_0905", number="SO-0905", when="2026-09-25", status="closed", customer_id=meera[0], customer_name=meera[1], item=case, quantity=1, warehouse_id="wh_mum", shipment_date="2026-09-25", invoiced_status="invoiced", quantity_shipped=1),
        # Open operational orders.
        _order(order_id="so_1001", number="SO-1001", when="2026-10-01", status="confirmed", customer_id=rahul[0], customer_name=rahul[1], item=earbud, quantity=3, warehouse_id="wh_mum", shipment_date="2026-10-02"),
        _order(order_id="so_1002", number="SO-1002", when="2026-10-01", status="confirmed", customer_id=meera[0], customer_name=meera[1], item=earbud, quantity=2, warehouse_id="wh_blr", shipment_date="2026-10-02"),
        _order(order_id="so_1003", number="SO-1003", when="2026-10-01", status="confirmed", customer_id=anita[0], customer_name=anita[1], item=speaker, quantity=6, warehouse_id="wh_blr", shipment_date="2026-10-03"),
        _order(order_id="so_1004", number="SO-1004", when="2026-10-01", status="confirmed", customer_id=rahul[0], customer_name=rahul[1], item=cable, quantity=2, warehouse_id="wh_mum", shipment_date="2026-10-01"),
        _order(order_id="so_1005", number="SO-1005", when="2026-09-30", status="shipped", customer_id=rahul[0], customer_name=rahul[1], item=earbud, quantity=2, warehouse_id="wh_mum", shipment_date="2026-09-30", invoiced_status="invoiced", quantity_shipped=2, payment_ids=("pay_UnpaidInv1005",)),
        _order(order_id="so_1006", number="SO-1006", when="2026-09-29", status="shipped", customer_id=meera[0], customer_name=meera[1], item=speaker, quantity=2, warehouse_id="wh_blr", shipment_date="2026-09-29", invoiced_status="invoiced", quantity_shipped=2, payment_ids=("pay_Overdue1006",)),
        _order(order_id="so_1007", number="SO-1007", when="2026-09-26", status="shipped", customer_id=anita[0], customer_name=anita[1], item=cable, quantity=1, warehouse_id="wh_blr", shipment_date="2026-09-26", invoiced_status="invoiced", quantity_shipped=1, payment_ids=("pay_Partial1007",)),
        _order(order_id="so_1008", number="SO-1008", when="2026-10-01", status="confirmed", customer_id=anita[0], customer_name=anita[1], item=cable, quantity=1, warehouse_id="wh_blr", shipment_date="2026-10-08", payment_ids=("pay_NotInvoiced1008",)),
        _order(order_id="so_1010", number="SO-1010", when="2026-09-28", status="confirmed", customer_id=rahul[0], customer_name=rahul[1], item=cable, quantity=4, warehouse_id="wh_mum", shipment_date="2026-10-12", invoiced_status="invoiced", payment_ids=("pay_Settled1010",)),
        _order(order_id="so_1011", number="SO-1011", when="2026-09-27", status="closed", customer_id=meera[0], customer_name=meera[1], item=cable, quantity=1, warehouse_id="wh_mum", shipment_date="2026-09-27", invoiced_status="invoiced", quantity_shipped=1, rate_override="99"),
        _order(order_id="so_1012", number="SO-1012", when="2026-09-25", status="refunded", customer_id=anita[0], customer_name=anita[1], item=cable, quantity=1, warehouse_id="wh_blr", shipment_date="2026-09-25", invoiced_status="invoiced", quantity_shipped=1, payment_ids=("pay_Refund1012",), stock_returned=False),
    )
    invoices = (
        Invoice(id="inv_0904", number="INV-0904", salesorder_id="so_0904", customer_id="cus_anita", status="paid", total=Decimal("1495.00"), balance=Decimal("0.00"), date=date(2026, 9, 29), tax_rate=Decimal("18"), tax_amount=Decimal("228.05")),
        Invoice(id="inv_1005", number="INV-1005", salesorder_id="so_1005", customer_id="cus_rahul", status="unpaid", total=Decimal("3998.00"), balance=Decimal("3998.00"), date=date(2026, 9, 30), tax_rate=Decimal("18"), tax_amount=Decimal("610.00")),
        Invoice(id="inv_1006", number="INV-1006", salesorder_id="so_1006", customer_id="cus_meera", status="overdue", total=Decimal("4998.00"), balance=Decimal("4998.00"), date=date(2026, 9, 29), tax_rate=Decimal("18"), tax_amount=Decimal("762.00")),
        Invoice(id="inv_1007", number="INV-1007", salesorder_id="so_1007", customer_id="cus_anita", status="partially_paid", total=Decimal("299.00"), balance=Decimal("150.00"), date=date(2026, 9, 26), tax_rate=Decimal("5"), tax_amount=Decimal("15.00")),
        Invoice(id="inv_1010", number="INV-1010", salesorder_id="so_1010", customer_id="cus_rahul", status="paid", total=Decimal("1196.00"), balance=Decimal("0.00"), date=date(2026, 9, 28), tax_rate=Decimal("18"), tax_amount=Decimal("182.00")),
        Invoice(id="inv_1011", number="INV-1011", salesorder_id="so_1011", customer_id="cus_meera", status="paid", total=Decimal("99.00"), balance=Decimal("0.00"), date=date(2026, 9, 27), tax_rate=Decimal("18"), tax_amount=Decimal("15.10")),
        Invoice(id="inv_1012", number="INV-1012", salesorder_id="so_1012", customer_id="cus_anita", status="void", total=Decimal("299.00"), balance=Decimal("0.00"), date=date(2026, 9, 25), tax_rate=Decimal("18"), tax_amount=Decimal("0")),
    )
    shipments = (
        Shipment(id="ship_1005", number="SHP-1005", salesorder_id="so_1005", status="shipped", date=date(2026, 9, 30), tracking_number="BD1005", warehouse_id="wh_mum"),
        Shipment(id="ship_1006", number="SHP-1006", salesorder_id="so_1006", status="shipped", date=date(2026, 9, 29), tracking_number="BD1006", warehouse_id="wh_blr"),
        Shipment(id="ship_1007", number="SHP-1007", salesorder_id="so_1007", status="delivered", date=date(2026, 9, 27), tracking_number="BD1007", warehouse_id="wh_blr"),
    )
    packages = (
        Package(id="pkg_1005", salesorder_id="so_1005", status="shipped", date=date(2026, 9, 30)),
        Package(id="pkg_1006", salesorder_id="so_1006", status="shipped", date=date(2026, 9, 29)),
        Package(id="pkg_1007", salesorder_id="so_1007", status="shipped", date=date(2026, 9, 26)),
    )
    contacts = (
        Contact(id="cus_rahul", name="Rahul Shah", email="rahul.shah@example.com", phone="9876543210", company="Shah Retail"),
        Contact(id="cus_meera", name="Meera Iyer", email="meera.iyer@example.com", phone="9123456780", company="Iyer Stores"),
        Contact(id="cus_anita", name="Anita Desai", email="anita.desai@example.com", phone="9988776655", company="Desai Living"),
    )
    return Catalog(
        as_of=as_of,
        items=items,
        orders=orders,
        invoices=invoices,
        shipments=shipments,
        packages=packages,
        warehouses=warehouses,
        contacts=contacts,
    )
