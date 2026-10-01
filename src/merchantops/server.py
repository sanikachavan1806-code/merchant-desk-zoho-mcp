from __future__ import annotations

import argparse
import logging
from typing import Annotated

from pydantic import Field

from merchantops.config import Settings
from merchantops.service import Service, build_service

INSTRUCTIONS = """
You are connected to Zoho MerchantOps, a read-only operational layer over Zoho Inventory
for an Indian Razorpay merchant.

Prefer get_daily_operations_brief, detect_operational_risks, get_order_health,
recommend_next_actions, reconcile_orders, dead_stock, gst_summary, and
match_order_to_payment over walking raw lists.
reconcile_orders joins Zoho to an optional Razorpay export. It does not call Razorpay's API.
A payment id on a Zoho order is the join key. Without an export, treat it as unverified.
Never invent stock, invoice, or payment figures. Quote tool results.
Phone and email stay masked. You cannot override that.
Paginate with next_cursor. Do not fetch every item or order one by one.
Call get_api_budget before a question that would scan broadly.
propose_action does not change Zoho or Razorpay. Do not claim a write succeeded.
Amounts are usually INR. Demo mode is a fixture merchant named Mira Audio, dated 2026-10-01.
""".strip()


def build_mcp(service: Service, *, host: str = "127.0.0.1", port: int = 8000):
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("Zoho MerchantOps", instructions=INSTRUCTIONS, host=host, port=port)

    @mcp.tool()
    async def search_orders(
        query: Annotated[str | None, Field(description="Match order number, customer name, SKU, or Razorpay payment id.")] = None,
        status: Annotated[str | None, Field(description="Zoho status such as confirmed, shipped, closed, void.")] = None,
        customer_id: Annotated[str | None, Field(description="Zoho contact id.")] = None,
        sku: Annotated[str | None, Field(description="Exact SKU on a line item.")] = None,
        warehouse_id: Annotated[str | None, Field(description="Warehouse id on a line item.")] = None,
        date_from: Annotated[str | None, Field(description="Inclusive order date, YYYY-MM-DD.")] = None,
        date_to: Annotated[str | None, Field(description="Inclusive order date, YYYY-MM-DD.")] = None,
        cursor: Annotated[str | None, Field(description="next_cursor from the previous page.")] = None,
        limit: Annotated[int | None, Field(description="Page size. Default 20, maximum 50.")] = None,
        fields: Annotated[list[str] | None, Field(description="Optional subset of order fields to return.")] = None,
    ) -> dict:
        """Search sales orders with operational filters. Use this when the merchant asks about orders, a SKU, a warehouse, or a date range. Do not use it to dump the whole order book."""
        return await service.search_orders(
            query=query,
            status=status,
            customer_id=customer_id,
            sku=sku,
            warehouse_id=warehouse_id,
            date_from=date_from,
            date_to=date_to,
            cursor=cursor,
            limit=limit,
            fields=fields,
        )

    @mcp.tool()
    async def get_order(
        order_id: Annotated[str, Field(description="Sales order id or number, for example SO-1002.")],
        fields: Annotated[list[str] | None, Field(description="Optional subset of order fields.")] = None,
    ) -> dict:
        """Fetch one normalized sales order. Prefer this over search when the order number is already known."""
        return await service.get_order(order_id, fields=fields)

    @mcp.tool()
    async def list_inventory(
        search: Annotated[str | None, Field(description="Name or SKU fragment.")] = None,
        sku: Annotated[str | None, Field(description="Exact SKU.")] = None,
        warehouse_id: Annotated[str | None, Field(description="Keep items that have a row in this warehouse.")] = None,
        low_stock_only: Annotated[bool, Field(description="True when total available stock is at or below the item reorder level. This is not per-warehouse.")] = False,
        available_below: Annotated[int | None, Field(description="Keep items whose total available stock is below this number.")] = None,
        cursor: Annotated[str | None, Field(description="next_cursor from the previous page.")] = None,
        limit: Annotated[int | None, Field(description="Page size. Default 20, maximum 50.")] = None,
        fields: Annotated[list[str] | None, Field(description="Optional subset of item fields.")] = None,
    ) -> dict:
        """List items and warehouse stock. A low total can hide a stocked-out warehouse; use detect_operational_risks or get_inventory_item for that."""
        return await service.list_inventory(
            search=search,
            sku=sku,
            warehouse_id=warehouse_id,
            low_stock_only=low_stock_only,
            available_below=available_below,
            cursor=cursor,
            limit=limit,
            fields=fields,
        )

    @mcp.tool()
    async def get_inventory_item(
        item_id: Annotated[str | None, Field(description="Zoho item id.")] = None,
        sku: Annotated[str | None, Field(description="Exact SKU, used when item_id is unknown.")] = None,
    ) -> dict:
        """Fetch one item, including available and on-hand stock in each warehouse."""
        return await service.get_inventory_item(item_id=item_id, sku=sku)

    @mcp.tool()
    async def list_warehouses() -> dict:
        """List the merchant's warehouses. Read this before reasoning about Mumbai versus Bengaluru fulfillment."""
        return await service.list_warehouses()

    @mcp.tool()
    async def list_invoices(
        status: Annotated[str | None, Field(description="paid, unpaid, overdue, partially_paid, void, or draft.")] = None,
        customer_id: Annotated[str | None, Field(description="Zoho contact id.")] = None,
        order_id: Annotated[str | None, Field(description="Sales order id linked on the invoice.")] = None,
        date_from: Annotated[str | None, Field(description="Inclusive invoice date, YYYY-MM-DD.")] = None,
        date_to: Annotated[str | None, Field(description="Inclusive invoice date, YYYY-MM-DD.")] = None,
        cursor: Annotated[str | None, Field(description="next_cursor from the previous page.")] = None,
        limit: Annotated[int | None, Field(description="Page size. Default 20, maximum 50.")] = None,
    ) -> dict:
        """List invoices. Use match_order_to_payment when the question is about Razorpay payments that Zoho has not invoiced."""
        return await service.list_invoices(
            status=status,
            customer_id=customer_id,
            order_id=order_id,
            date_from=date_from,
            date_to=date_to,
            cursor=cursor,
            limit=limit,
        )

    @mcp.tool()
    async def list_shipments(
        order_id: Annotated[str | None, Field(description="Sales order id or shipment number.")] = None,
        status: Annotated[str | None, Field(description="Shipment status such as shipped or delivered.")] = None,
        cursor: Annotated[str | None, Field(description="next_cursor from the previous page.")] = None,
        limit: Annotated[int | None, Field(description="Page size. Default 20, maximum 50.")] = None,
    ) -> dict:
        """List shipment records. Use get_order_health when the question is why an order is late, not just where the tracking number is."""
        return await service.list_shipments(order_id=order_id, status=status, cursor=cursor, limit=limit)

    @mcp.tool()
    async def get_customer(
        customer_id: Annotated[str, Field(description="Zoho contact id.")],
        include_pii: Annotated[bool, Field(description="Ask to reveal phone and email. Ignored unless the server was started with ZOHO_REVEAL_PII=true.")] = False,
    ) -> dict:
        """Fetch a customer with phone and email masked by default. Order tools already omit contact details; call this only when the merchant explicitly needs them."""
        return await service.get_customer(customer_id, include_pii=include_pii)

    @mcp.tool()
    async def get_order_health(
        order_id: Annotated[str, Field(description="Sales order id or number.")],
    ) -> dict:
        """Explain whether one order is HEALTHY, WATCH, or AT_RISK using stock, package, shipment date, and invoice balance. Recommendations are not actions."""
        return await service.get_order_health(order_id)

    @mcp.tool()
    async def detect_operational_risks(
        time_window_days: Annotated[int, Field(description="How many days ahead count as a soon-to-ship order. Default 2.")] = 2,
        horizon_days: Annotated[int, Field(description="Flag stock that covers fewer than this many days of recent demand. Default 7.")] = 7,
        risk_types: Annotated[list[str] | None, Field(description="Subset of stockout, fulfillment, revenue, imbalance, slow_moving.")] = None,
        severity: Annotated[str | None, Field(description="high, medium, or low.")] = None,
    ) -> dict:
        """Find stock, shipment, collection, and warehouse-imbalance risks in one bounded scan. Prefer this over listing every order when the merchant asks what to worry about."""
        return await service.detect_operational_risks(
            time_window_days=time_window_days,
            horizon_days=horizon_days,
            risk_types=risk_types,
            severity=severity,
        )

    @mcp.tool()
    async def find_alternate_fulfillment(
        sku: Annotated[str, Field(description="Exact SKU.")],
        quantity: Annotated[int, Field(description="Units the order needs.")],
        source_warehouse_id: Annotated[str, Field(description="Warehouse that was supposed to fulfill the order.")],
    ) -> dict:
        """Check whether another warehouse has enough available stock. Does not create a transfer."""
        return await service.find_alternate_fulfillment(sku, quantity, source_warehouse_id)

    @mcp.tool()
    async def recommend_next_actions(
        time_window_days: Annotated[int, Field(description="Shipment window passed to the risk rules. Default 2.")] = 2,
    ) -> dict:
        """Rank the next things a human should look at. executable is always false. Replenishment and transfers still need a person."""
        return await service.recommend_next_actions(time_window_days=time_window_days)

    @mcp.tool()
    async def explain_recommendation(
        recommendation_id: Annotated[str, Field(description="id from recommend_next_actions or detect_operational_risks, such as stockout:SKU-EARBUD-PRO:wh_mum.")],
    ) -> dict:
        """Show the evidence behind one recommendation. Rules use a 7-day demand window, not a forecasting model."""
        return await service.explain_recommendation(recommendation_id)

    @mcp.tool()
    async def get_daily_operations_brief() -> dict:
        """One merchant brief: open orders, risks, and the line that no writes were performed. Start here for 'what needs attention today?'."""
        return await service.get_daily_operations_brief()

    @mcp.tool()
    async def match_order_to_payment(
        payment_id: Annotated[str | None, Field(description="Razorpay payment id (pay_...) or payment link id (plink_...).")] = None,
        order_id: Annotated[str | None, Field(description="Zoho sales order id or number.")] = None,
        only_paid_not_invoiced: Annotated[bool, Field(description="True to answer: which orders reference a Razorpay payment but have no Zoho invoice?")] = False,
    ) -> dict:
        """Link a Zoho sales order to a Razorpay payment id stored on the order reference or notes. This does not call Razorpay and does not capture a payment."""
        return await service.match_order_to_payment(
            payment_id=payment_id,
            order_id=order_id,
            only_paid_not_invoiced=only_paid_not_invoiced,
        )

    @mcp.tool()
    async def reconcile_orders(
        date_from: Annotated[str | None, Field(description="Inclusive start date, YYYY-MM-DD. Defaults to the last 7 days.")] = None,
        date_to: Annotated[str | None, Field(description="Inclusive end date, YYYY-MM-DD. Defaults to the merchant's as-of date.")] = None,
    ) -> dict:
        """Join Zoho orders and invoices to Razorpay payments. Buckets: paid and shipped, paid but not invoiced, invoiced but unpaid, refunded without stock returned, paid and not shipped."""
        return await service.reconcile_orders(date_from=date_from, date_to=date_to)

    @mcp.tool()
    async def dead_stock(
        days: Annotated[int, Field(description="Look back this many days for a sale. Default 30.")] = 30,
    ) -> dict:
        """Items with stock on hand and no sale in the window, valued at purchase rate so a merchant can see cash tied up."""
        return await service.dead_stock(days=days)

    @mcp.tool()
    async def gst_summary(
        period: Annotated[str | None, Field(description="Calendar month YYYY-MM, for example 2026-09.")] = None,
        date_from: Annotated[str | None, Field(description="Inclusive start when period is omitted.")] = None,
        date_to: Annotated[str | None, Field(description="Inclusive end when period is omitted.")] = None,
    ) -> dict:
        """Tax collected by rate from Zoho invoices. This is not a filed GST return."""
        return await service.gst_summary(period=period, date_from=date_from, date_to=date_to)

    @mcp.tool()
    async def detect_anomalies(
        window_days: Annotated[int, Field(description="How many days back to scan. Default 14.")] = 14,
    ) -> dict:
        """Rule flags: order-count spikes, line rates far below list price, and a failed Razorpay attempt followed by a capture."""
        return await service.detect_anomalies(window_days=window_days)

    @mcp.tool()
    async def get_api_budget() -> dict:
        """Return today's Zoho call count, the per-minute budget, and the plan's daily ceiling so you can decide whether an expensive scan is worth it."""
        return await service.get_api_budget()

    @mcp.tool()
    async def propose_action(
        action_type: Annotated[str, Field(description="Requested mutation, for example create_purchase_order, inventory_adjustment, email_customer, delete_order, payment_execution.")],
        reason: Annotated[str, Field(description="Why the agent wants the change. Stored only as 'present' in the audit log.")] = "",
        payload: Annotated[dict | None, Field(description="Proposed arguments. Not sent to Zoho.")] = None,
    ) -> dict:
        """Record a requested write and refuse it. Use this instead of pretending a purchase order, stock adjustment, email, delete, or payment was made."""
        return await service.propose_action(action_type, reason=reason, payload=payload)

    @mcp.resource("zoho://org/warehouses")
    async def warehouses_resource() -> str:
        """Warehouse list for the connected organization."""
        import json

        payload = await service.list_warehouses()
        return json.dumps(payload, default=str)

    @mcp.resource("zoho://org/api-budget")
    async def budget_resource() -> str:
        """Current Zoho API budget snapshot."""
        import json

        payload = await service.get_api_budget()
        return json.dumps(payload, default=str)

    @mcp.resource("zoho://org/capabilities")
    def capabilities_resource() -> str:
        """What this connector will and will not do."""
        return (
            "READ: orders, items, warehouses, invoices, shipments, masked contacts, "
            "order health, operational risks, alternate fulfillment, recommendations, "
            "daily brief, Razorpay reference matching, order-payment reconciliation, "
            "dead stock, GST summary, anomaly flags, API budget.\n"
            "JOIN: Razorpay status comes from an optional payments export, not a live Razorpay call.\n"
            "NOT EXPOSED: create/update/delete of any Zoho record, stock adjustments, "
            "customer email, payment capture, webhooks, full-catalog export.\n"
            "PII: phone and email are masked unless ZOHO_REVEAL_PII=true.\n"
            "QUOTA: 80 requests/minute client budget under Zoho's 100/minute cap; "
            "daily ceiling follows the plan (free 1000)."
        )

    @mcp.prompt()
    def daily_ops_brief() -> str:
        """Ask the agent for today's merchant operations brief."""
        return (
            "Call get_daily_operations_brief. Summarize only what the tool returns. "
            "Then ask which recommendation the merchant wants explained. Do not create documents in Zoho."
        )

    @mcp.prompt()
    def orders_at_risk() -> str:
        """Ask which orders need attention."""
        return (
            "Call detect_operational_risks with time_window_days 2. Group the result by type. "
            "For one AT_RISK example, call get_order_health. Do not loop over every order id."
        )

    @mcp.prompt()
    def paid_not_shipped() -> str:
        """Ask which paid orders have not shipped."""
        return (
            "Call reconcile_orders for the last week. Report the paid_not_shipped bucket "
            "and say whether each payment was verified from a Razorpay export."
        )

    @mcp.prompt()
    def paid_not_invoiced() -> str:
        """Ask which Razorpay-paid orders have no Zoho invoice."""
        return (
            "Call match_order_to_payment with only_paid_not_invoiced true. "
            "Say clearly that the match uses the payment id stored on the Zoho order, not a live Razorpay API call."
        )

    return mcp


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Zoho MerchantOps MCP server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)
    settings = Settings()
    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port
    service = build_service(settings)
    mcp = build_mcp(service, host=settings.host, port=settings.port)
    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
