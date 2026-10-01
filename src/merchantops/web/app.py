from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from merchantops.service import Service

STATIC = Path(__file__).parent / "static"


class PayloadResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(content, default=str).encode("utf-8")


def create_app(service: Service) -> Starlette:
    from merchantops.server import build_mcp

    mcp = build_mcp(service)
    async def homepage(_: Request) -> Response:
        return FileResponse(STATIC / "index.html")

    async def brief(_: Request) -> Response:
        return PayloadResponse(await service.get_daily_operations_brief())

    async def risks(request: Request) -> Response:
        window = _int(request.query_params.get("time_window_days"), 2)
        horizon = _int(request.query_params.get("horizon_days"), 7)
        return PayloadResponse(
            await service.detect_operational_risks(time_window_days=window, horizon_days=horizon)
        )

    async def actions(request: Request) -> Response:
        window = _int(request.query_params.get("time_window_days"), 2)
        return PayloadResponse(await service.recommend_next_actions(time_window_days=window))

    async def explain(request: Request) -> Response:
        recommendation_id = request.query_params.get("id") or ""
        return PayloadResponse(await service.explain_recommendation(recommendation_id))

    async def orders(request: Request) -> Response:
        limit = _int(request.query_params.get("limit"), 50)
        return PayloadResponse(
            await service.search_orders(
                query=request.query_params.get("query"),
                status=request.query_params.get("status"),
                sku=request.query_params.get("sku"),
                limit=limit,
            )
        )

    async def health(request: Request) -> Response:
        return PayloadResponse(await service.get_order_health(request.path_params["order_id"]))

    async def invoices(request: Request) -> Response:
        return PayloadResponse(
            await service.list_invoices(status=request.query_params.get("status"), limit=_int(request.query_params.get("limit"), 50))
        )

    async def shipments(request: Request) -> Response:
        return PayloadResponse(await service.list_shipments(limit=_int(request.query_params.get("limit"), 50)))

    async def inventory(request: Request) -> Response:
        low = request.query_params.get("low_stock_only") == "true"
        return PayloadResponse(await service.list_inventory(low_stock_only=low, limit=50))

    async def fulfillment(request: Request) -> Response:
        body = await request.json()
        return PayloadResponse(
            await service.find_alternate_fulfillment(
                str(body.get("sku") or ""),
                int(body.get("quantity") or 0),
                str(body.get("source_warehouse_id") or ""),
            )
        )

    async def payments(request: Request) -> Response:
        only = request.query_params.get("only_paid_not_invoiced") == "true"
        return PayloadResponse(
            await service.match_order_to_payment(
                payment_id=request.query_params.get("payment_id"),
                order_id=request.query_params.get("order_id"),
                only_paid_not_invoiced=only,
            )
        )

    async def budget(_: Request) -> Response:
        return PayloadResponse(await service.get_api_budget())

    async def customer(request: Request) -> Response:
        include = request.query_params.get("include_pii") == "true"
        return PayloadResponse(await service.get_customer(request.path_params["customer_id"], include_pii=include))

    async def reconcile(request: Request) -> Response:
        return PayloadResponse(
            await service.reconcile_orders(
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
            )
        )

    async def dead(request: Request) -> Response:
        return PayloadResponse(await service.dead_stock(days=_int(request.query_params.get("days"), 30)))

    async def gst(request: Request) -> Response:
        return PayloadResponse(
            await service.gst_summary(
                period=request.query_params.get("period") or None,
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
            )
        )

    async def anomalies(request: Request) -> Response:
        return PayloadResponse(await service.detect_anomalies(window_days=_int(request.query_params.get("window_days"), 14)))

    async def propose(request: Request) -> Response:
        body = await request.json()
        return PayloadResponse(
            await service.propose_action(
                str(body.get("action_type") or ""),
                reason=str(body.get("reason") or ""),
                payload=body.get("payload") if isinstance(body.get("payload"), dict) else None,
            )
        )

    async def mcp_catalog(_: Request) -> Response:
        tools = await mcp.list_tools()
        resources = await mcp.list_resources()
        prompts = await mcp.list_prompts()
        return PayloadResponse(
            {
                "server": "Zoho MerchantOps",
                "connected": True,
                "mode": service.settings.mode,
                "read_only": True,
                "tools": [_dump(tool) for tool in tools],
                "resources": [_dump(resource) for resource in resources],
                "prompts": [_dump(prompt) for prompt in prompts],
            }
        )

    async def mcp_call(request: Request) -> Response:
        body = await request.json()
        name = str(body.get("name") or "")
        arguments = body.get("arguments") if isinstance(body.get("arguments"), dict) else {}
        try:
            result = await mcp._tool_manager.call_tool(
                name,
                arguments,
                context=mcp.get_context(),
                convert_result=False,
            )
        except Exception as exc:
            return PayloadResponse({"ok": False, "error": str(exc)})
        return PayloadResponse({"ok": True, "result": result})

    async def mcp_resource(request: Request) -> Response:
        uri = request.query_params.get("uri") or ""
        try:
            contents = await mcp.read_resource(uri)
        except Exception as exc:
            return PayloadResponse({"ok": False, "error": str(exc)})
        return PayloadResponse({"ok": True, "contents": [str(item.content) for item in contents]})

    async def mcp_prompt(request: Request) -> Response:
        name = request.query_params.get("name") or ""
        try:
            prompt = await mcp.get_prompt(name)
        except Exception as exc:
            return PayloadResponse({"ok": False, "error": str(exc)})
        return PayloadResponse({"ok": True, "prompt": _dump(prompt)})

    async def audit(_: Request) -> Response:
        path = Path(service.settings.audit_log_path)
        if not path.exists():
            return PayloadResponse({"events": []})
        lines = path.read_text(encoding="utf-8").splitlines()[-12:]
        events = []
        for line in lines:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return PayloadResponse({"events": events})

    return Starlette(
        routes=[
            Route("/", homepage),
            Route("/api/brief", brief),
            Route("/api/risks", risks),
            Route("/api/actions", actions),
            Route("/api/explain", explain),
            Route("/api/orders", orders),
            Route("/api/orders/{order_id}/health", health),
            Route("/api/inventory", inventory),
            Route("/api/invoices", invoices),
            Route("/api/shipments", shipments),
            Route("/api/fulfillment", fulfillment, methods=["POST"]),
            Route("/api/payments", payments),
            Route("/api/reconcile", reconcile),
            Route("/api/dead-stock", dead),
            Route("/api/gst", gst),
            Route("/api/anomalies", anomalies),
            Route("/api/budget", budget),
            Route("/api/customer/{customer_id}", customer),
            Route("/api/propose", propose, methods=["POST"]),
            Route("/api/audit", audit),
            Route("/api/mcp/catalog", mcp_catalog),
            Route("/api/mcp/call", mcp_call, methods=["POST"]),
            Route("/api/mcp/resource", mcp_resource),
            Route("/api/mcp/prompt", mcp_prompt),
            Mount("/static", app=StaticFiles(directory=STATIC), name="static"),
        ]
    )


def _dump(model: Any) -> Any:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model


def _int(value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)
