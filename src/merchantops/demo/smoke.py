"""Smoke proof for the MCP server.

Demo mode is the path a reviewer can run with no Zoho account. It calls the
same service the tools call, checks the Mira Audio story, and prints the
error envelopes an agent actually receives.

    python -m merchantops.demo.smoke

A real Zoho organization, when credentials are already in the environment:

    python -m merchantops.demo.smoke --live

That path reads warehouses and the API budget only. It does not scan the catalog.
"""

from __future__ import annotations

import argparse
import asyncio
import tempfile
from pathlib import Path

from merchantops.config import Settings
from merchantops.server import build_mcp
from merchantops.service import Service, build_service


def _line(ok: bool, tool: str, detail: str) -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"{mark}  {tool:<28} {detail}")


async def run_smoke(settings: Settings | None = None) -> dict:
    """Exercise demo tools and the stable error strings. Raises AssertionError on drift."""
    if settings is None:
        folder = tempfile.mkdtemp(prefix="merchantops-smoke-")
        settings = Settings(_env_file=None, mode="demo", audit_log_path=str(Path(folder) / "audit.jsonl"))
    service = build_service(settings)
    print("Zoho MerchantOps smoke")
    print("mode=demo  merchant=Mira Audio  as_of=2026-10-01  zoho_http=no")
    print()

    brief = await service.get_daily_operations_brief()
    _line(brief["open_orders"] == 6, "get_daily_operations_brief", f"open orders {brief['open_orders']}")

    risks = await service.detect_operational_risks()
    earbud = next(row for row in risks["risks"] if row["id"] == "stockout:SKU-EARBUD-PRO:wh_mum")
    _line("about 4 days" in earbud["title"], "detect_operational_risks", earbud["title"])

    health = await service.get_order_health("SO-1002")
    _line(health["health"] == "AT_RISK", "get_order_health", f"SO-1002 {health['health']}")

    alternate = await service.find_alternate_fulfillment("SKU-SPEAKER-MINI", 6, "wh_blr")
    _line(
        alternate["source_can_fulfill"] is False and alternate["alternatives"][0]["warehouse_name"] == "Mumbai",
        "find_alternate_fulfillment",
        f"Bengaluru {alternate['source_available']} available, Mumbai can cover 6",
    )

    payments = await service.match_order_to_payment(only_paid_not_invoiced=True)
    _line(
        [row["order_number"] for row in payments["matches"]] == ["SO-1008"],
        "match_order_to_payment",
        "paid, no invoice: SO-1008",
    )

    reconcile = await service.reconcile_orders()
    shipped = [row["order_number"] for row in reconcile["buckets"]["paid_not_shipped"]]
    _line(shipped == ["SO-1010"], "reconcile_orders", f"paid_not_shipped {', '.join(shipped)}")

    dead = await service.dead_stock(days=30)
    _line(
        dead["items"][0]["sku"] == "SKU-STAND-OLD" and dead["items"][0]["value_tied_up"] == "10000.00",
        "dead_stock",
        "SKU-STAND-OLD ₹10,000.00",
    )

    gst = await service.gst_summary(period="2026-09")
    _line(gst["tax_total"] == "1812.15", "gst_summary", "September tax ₹1,812.15")

    anomalies = await service.detect_anomalies()
    kinds = {row["type"] for row in anomalies["flags"]}
    _line(
        kinds == {"order_spike", "unusual_discount", "failed_then_paid"},
        "detect_anomalies",
        ", ".join(sorted(kinds)),
    )

    customer = await service.get_customer("cus_rahul", include_pii=True)
    email = customer["customer"]["email"]
    phone = customer["customer"]["phone"]
    _line(email == "r***@example.com" and phone == "******3210", "get_customer", f"{email}  {phone}")

    refused = await service.propose_action("transfer_stock", reason="Bengaluru is short", payload={"quantity": 20})
    _line(refused["executed"] is False and "write" in refused["refusal"].lower(), "propose_action", refused["summary"])

    missing = await service.get_order("SO-DOES-NOT-EXIST")
    _line(missing["error"]["code"] == "not_found", "error not_found", missing["error"]["message"])

    bad_date = await service.search_orders(date_from="yesterday")
    _line(
        bad_date["error"]["code"] == "invalid_argument" and "YYYY-MM-DD" in bad_date["error"]["message"],
        "error invalid_argument",
        bad_date["error"]["message"],
    )

    bad_limit = await service.search_orders(limit=99)
    _line("between 1 and 50" in bad_limit["error"]["message"], "error page cap", bad_limit["error"]["message"])

    bad_qty = await service.find_alternate_fulfillment("SKU-SPEAKER-MINI", 0, "wh_blr")
    _line(bad_qty["error"]["message"] == "quantity must be at least 1.", "error quantity", bad_qty["error"]["message"])

    bad_period = await service.gst_summary(period="September")
    _line(bad_period["error"]["message"] == "period must be YYYY-MM.", "error period", bad_period["error"]["message"])

    bad_explain = await service.explain_recommendation("no-such-id")
    _line(bad_explain["error"]["code"] == "not_found", "error explain", bad_explain["error"]["message"])

    mcp = build_mcp(service)
    tools = await mcp.list_tools()
    names = sorted(tool.name for tool in tools)
    _line(len(names) == 21, "mcp.list_tools", f"{len(names)} tools")

    budget = await service.get_api_budget()
    _line(budget["daily_limit"] == 1000, "get_api_budget", f"{budget['daily_used']}/{budget['daily_limit']} logical reads")

    print()
    print("Smoke passed. Demo fixture only. No Zoho account was called.")
    print("Live organization: python -m merchantops.demo.smoke --live")
    return {
        "brief": brief,
        "gst": gst,
        "customer_email": email,
        "tools": names,
        "missing": missing,
        "bad_date": bad_date,
        "refused": refused,
    }


async def run_live() -> None:
    """Read two safe calls from a configured Zoho organization. Does not scan orders."""
    settings = Settings()
    if settings.mode != "live":
        print("ZOHO_MODE is not live. Set credentials in .env, or run without --live for the demo proof.")
        raise SystemExit(2)
    if not settings.organization_id or not (settings.access_token or settings.refresh_token):
        print("Live mode needs ZOHO_ORGANIZATION_ID and ZOHO_ACCESS_TOKEN or ZOHO_REFRESH_TOKEN.")
        raise SystemExit(2)
    service: Service = build_service(settings)
    print("Zoho MerchantOps smoke — live")
    print("Reads list_warehouses and get_api_budget. Does not scan the order book.")
    warehouses = await service.list_warehouses()
    if warehouses.get("error"):
        print(f"FAIL  list_warehouses  {warehouses['error']['code']}: {warehouses['error']['message']}")
        raise SystemExit(1)
    names = ", ".join(row["name"] for row in warehouses.get("warehouses") or []) or "(none)"
    print(f"PASS  list_warehouses              {warehouses['summary']} {names}")
    print(f"      source={warehouses['meta']['source']} calls_used={warehouses['meta'].get('calls_used')}")
    budget = await service.get_api_budget()
    if budget.get("error"):
        print(f"FAIL  get_api_budget  {budget['error']['code']}: {budget['error']['message']}")
        raise SystemExit(1)
    print(f"PASS  get_api_budget                {budget['daily_used']}/{budget['daily_limit']}  {budget.get('counting')}")
    print("Live smoke finished. No write was sent.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test Zoho MerchantOps")
    parser.add_argument("--live", action="store_true", help="Call a configured Zoho organization. Two reads only.")
    args = parser.parse_args()
    if args.live:
        asyncio.run(run_live())
        return
    asyncio.run(run_smoke())


if __name__ == "__main__":
    main()
