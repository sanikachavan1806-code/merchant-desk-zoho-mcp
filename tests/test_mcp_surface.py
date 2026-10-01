import pytest

from merchantops.config import Settings
from merchantops.server import build_mcp
from merchantops.service import build_service

EXPECTED_TOOLS = {
    "search_orders",
    "get_order",
    "list_inventory",
    "get_inventory_item",
    "list_warehouses",
    "list_invoices",
    "list_shipments",
    "get_customer",
    "get_order_health",
    "detect_operational_risks",
    "find_alternate_fulfillment",
    "recommend_next_actions",
    "explain_recommendation",
    "get_daily_operations_brief",
    "match_order_to_payment",
    "reconcile_orders",
    "dead_stock",
    "gst_summary",
    "detect_anomalies",
    "get_api_budget",
    "propose_action",
}


@pytest.mark.asyncio
async def test_mcp_exposes_business_tools_not_crud_wrappers(tmp_path):
    settings = Settings(_env_file=None, mode="demo", audit_log_path=str(tmp_path / "audit.jsonl"))
    mcp = build_mcp(build_service(settings))
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}
    assert names == EXPECTED_TOOLS
    search = next(tool for tool in tools if tool.name == "search_orders")
    assert "sales orders" in search.description.lower()
    resources = {str(resource.uri) for resource in await mcp.list_resources()}
    assert "zoho://org/capabilities" in resources
    prompts = {prompt.name for prompt in await mcp.list_prompts()}
    assert {"daily_ops_brief", "orders_at_risk", "paid_not_invoiced", "paid_not_shipped"} <= prompts
