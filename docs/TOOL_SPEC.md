# Zoho MerchantOps tool spec

MCP server name: **Zoho MerchantOps**. Transports: **stdio** and **streamable HTTP** (`/mcp`). Every tool is read-only. Errors come back as a JSON envelope, not as a raised exception the agent has to parse from a traceback.

Logging uses Python's `logging` module, which writes to stderr. The stdio transport keeps stdout for MCP framing.

Full can / cannot list: [capabilities.md](capabilities.md). This page is the contract: shared envelope, tools, and the error strings the server returns.

## Shared success envelope

```json
{
  "summary": "one line an agent can quote",
  "meta": {
    "read_only": true,
    "pii_redacted": true,
    "truncated": false,
    "source": "demo",
    "calls_used": 1,
    "fetched_at": "2026-10-01T00:00:00+00:00",
    "sources": [{ "system": "demo", "resource": "salesorders", "ids": ["so_1008"] }]
  }
}
```

`source` is `demo` or `zoho`. `calls_used` is logical reads in demo mode, and outbound HTTP attempts (retries included) in live mode. Cache hits stay at 0. `truncated` is true when an intelligence scan hit the 4-page cap.

## Shared error envelope

```json
{
  "summary": "the same text as error.message",
  "meta": { "read_only": true, "source": "demo", "pii_redacted": true },
  "error": { "code": "invalid_argument", "message": "date_from must be an ISO date (YYYY-MM-DD)." }
}
```

`rate_limited` also includes `scope` (`per_minute` or `daily`) and `retry_after` (seconds, or `null` when the daily cap is hit).

| code | When | Message the agent sees |
| --- | --- | --- |
| `invalid_argument` | Bad input | See the fixed strings below |
| `not_found` | Id is not in the scanned pages or the demo catalog | See below |
| `read_only` | A non-GET would have been sent to Zoho | `Blocked POST to Zoho. This connector only issues GET requests.` (`POST` is the method that was blocked) |
| `rate_limited` | Zoho 429 or the local daily meter | Per-minute: Zoho's message, or `Zoho per-minute limit reached.` `scope=per_minute`, `retry_after` set. Daily: `Zoho daily API quota is exhausted for this organization. Tell the merchant and stop. Retrying will not succeed until the quota resets.` or Zoho's own message. `scope=daily`, `retry_after=null` |
| `unauthorized` | Token rejected after one refresh | `Zoho rejected the access token after a refresh.` |
| `upstream` | Other Zoho HTTP error | Zoho's message, or `Zoho returned an error payload.` |
| `config` | Process should not start | `ZOHO_MODE must be 'demo' or 'live'.` · `This connector is read-only and will not start with READ_ONLY=false. Writes (purchase orders, stock adjustments, customer email, deletes, payments) are deliberately not implemented.` · `ZOHO_PER_MINUTE_BUDGET must stay at or under Zoho's 100/minute platform limit.` · `ZOHO_CONCURRENCY must be at least 1.` · `ZOHO_PAGE_SIZE_CAP must be between 1 and 50.` · `Unknown ZOHO_PLAN '<plan>'.` · `ZOHO_ORGANIZATION_ID is required in live mode. Zoho expects it on every call.` · `Unknown Zoho datacenter '<dc>'.` · `Refusing unexpected Zoho api_domain '<url>'.` |
| `internal` | Unexpected exception | `The tool failed before calling Zoho. Details were logged, not returned.` The body message is `Unexpected failure. See the server log.` |

### Fixed `invalid_argument` strings

| Message |
| --- |
| `limit must be between 1 and 50.` |
| `order_id is required.` |
| `Provide item_id or sku.` |
| `customer_id is required.` |
| `recommendation_id is required.` |
| `action_type is required.` |
| `date_from must be an ISO date (YYYY-MM-DD).` (same shape for `date_to`) |
| `date_from must be on or before date_to.` |
| `Cursor is not valid. Pass next_cursor from the previous page.` |
| `Unknown fields: <names>. Known fields: <names>.` |
| `quantity must be at least 1.` |
| `days must be between 1 and 365.` |
| `period must be YYYY-MM.` |
| `window_days must be between 2 and 90.` |
| `time_window_days must be between 0 and 30.` |
| `horizon_days must be between 1 and 30.` |
| `severity must be high, medium, or low.` |
| `Unknown risk_types: <names>. Use stockout, fulfillment, revenue, imbalance, slow_moving.` |
| `This backend is not tracking API budget.` |
| `RAZORPAY_EXPORT_PATH does not exist: <path>` |

### Fixed `not_found` strings

| Message |
| --- |
| `No sales order '<id>' in the demo catalog.` |
| `No item '<id>' in the demo catalog.` |
| `No contact '<id>' in the demo catalog.` |
| `No item with SKU '<sku>' in the scanned pages.` |
| `SKU '<sku>' has no stock row for warehouse '<id>'.` |
| `No recommendation '<id>'. Call recommend_next_actions and use one of its ids.` |
| Live Zoho 404: Zoho's message, or `Zoho resource was not found.` |

### `propose_action` refusals

`executed` is always `false`. `summary` is `Refused. Nothing was changed in Zoho or Razorpay.`

| action_type | refusal |
| --- | --- |
| `create_purchase_order` | Creating a purchase order mutates purchasing. Not exposed. |
| `create_sales_order` | Creating a sales order mutates orders. Not exposed. |
| `inventory_adjustment` | An agent must not change on-hand stock. Not exposed. |
| `update_order_status` | Confirming, voiding, or approving orders is not exposed. |
| `create_package` | Creating packages is a warehouse write. Not exposed. |
| `create_shipment` | Creating shipments is a warehouse write. Not exposed. |
| `transfer_stock` | Moving stock between warehouses is an inventory write. Not exposed. |
| `replenish` | Raising a purchase order is a write. Not exposed. |
| `email_customer` | This connector will not email customers. |
| `delete_order` | Deletes are not exposed and are not on the roadmap for this server. |
| `delete_invoice` | Deletes are not exposed. |
| `payment_execution` | Moving money is a Razorpay payment-tool concern, not an inventory connector. |
| `void_invoice` | Voiding invoices is not exposed. |
| anything else | That action is not a read. This connector does not mutate Zoho Inventory or Razorpay. |

The `reason` argument is stored in the audit log as `present` or `absent`, not as the text.

## Tools

Page size defaults to 20 and caps at 50. Pass `next_cursor` to continue. `fields` limits which keys of a record are returned.

### Reads

| Tool | Arguments | Returns |
| --- | --- | --- |
| `search_orders` | `query`, `status`, `customer_id`, `sku`, `warehouse_id`, `date_from`, `date_to`, `cursor`, `limit`, `fields` | `orders[]`, `has_more`, `next_cursor` |
| `get_order` | `order_id`, `fields` | `order` |
| `list_inventory` | `search`, `sku`, `warehouse_id`, `low_stock_only`, `available_below`, `cursor`, `limit`, `fields` | `items[]` with per-warehouse `available` and `on_hand`. `low_stock_only` compares the item total with the reorder level |
| `get_inventory_item` | `item_id` or `sku` | `item` |
| `list_warehouses` | — | `warehouses[]` |
| `list_invoices` | `status`, `customer_id`, `order_id`, `date_from`, `date_to`, `cursor`, `limit` | `invoices[]` |
| `list_shipments` | `order_id`, `status`, `cursor`, `limit` | `shipments[]` |
| `get_customer` | `customer_id`, `include_pii` | `customer`. Email `r***@example.com`, phone `******3210`. `include_pii=true` is ignored unless the operator set `ZOHO_REVEAL_PII=true` |
| `get_api_budget` | — | `daily_used`, `daily_limit`, `per_minute_budget`, `advice`, `counting` |

### Merchant judgment

| Tool | Arguments | Returns |
| --- | --- | --- |
| `get_daily_operations_brief` | — | `open_orders`, `open_order_value`, `highlights`, `brief` |
| `detect_operational_risks` | `time_window_days` (0–30), `horizon_days` (1–30), `risk_types`, `severity` | `risks[]` with `id`, `type`, `severity`, `title`, `evidence` |
| `get_order_health` | `order_id` | `health` (`HEALTHY`, `WATCH`, `AT_RISK`), `reasons` |
| `find_alternate_fulfillment` | `sku`, `quantity` (≥1), `source_warehouse_id` | `source_can_fulfill`, `source_available`, `alternatives[]`. Does not transfer stock |
| `recommend_next_actions` | `time_window_days` | `actions[]`. `executable` is always `false` |
| `explain_recommendation` | `recommendation_id` from the list above | `title`, `reason`, `evidence`, `executable: false` |
| `match_order_to_payment` | `payment_id`, `order_id`, `only_paid_not_invoiced` | `matches[]`. Uses the `pay_` / `plink_` id stored on the Zoho order. Does not call Razorpay |
| `reconcile_orders` | `date_from`, `date_to` | Buckets: `paid_and_shipped`, `paid_not_invoiced`, `invoiced_but_unpaid`, `refunded_stock_not_returned`, `paid_not_shipped`. Capture status needs `RAZORPAY_EXPORT_PATH` or the demo export. Otherwise `referenced_not_verified` |
| `dead_stock` | `days` (1–365) | Items with no sale in the window, valued at purchase rate |
| `gst_summary` | `period` (`YYYY-MM`) or `date_from` / `date_to` | `rates[]`, `tax_total`. Not a filed GST return |
| `detect_anomalies` | `window_days` (2–90) | `flags[]`: `order_spike`, `unusual_discount`, `failed_then_paid` |
| `propose_action` | `action_type`, `reason`, `payload` | `executed: false` and a refusal. Nothing is written |

## Resources and prompts

| Kind | Name | Use |
| --- | --- | --- |
| resource | `zoho://org/warehouses` | Warehouse list |
| resource | `zoho://org/api-budget` | Quota snapshot |
| resource | `zoho://org/capabilities` | Can / cannot text |
| prompt | `daily_ops_brief` | Start with `get_daily_operations_brief` |
| prompt | `orders_at_risk` | Risks, then one `get_order_health` |
| prompt | `paid_not_shipped` | `reconcile_orders` |
| prompt | `paid_not_invoiced` | `match_order_to_payment` |

## Dump the live schema

```bash
python -c "
import asyncio, json
from merchantops.config import Settings
from merchantops.server import build_mcp
from merchantops.service import build_service
settings = Settings(_env_file=None, mode='demo', audit_log_path='/tmp/merchantops-audit.jsonl')
mcp = build_mcp(build_service(settings))
tools = asyncio.run(mcp.list_tools())
print(json.dumps([{'name': t.name, 'description': t.description} for t in tools], indent=2))
"
```

## MCP Inspector

Demo mode, so a reviewer's machine does not need Zoho:

```bash
npx @modelcontextprotocol/inspector --cli .venv/bin/merchantops --method tools/list -e ZOHO_MODE=demo
```

The server command comes first. Flags after it belong to the inspector. `-e ZOHO_MODE=demo` keeps a live `.env` from being used.

Interactive UI:

```bash
npx @modelcontextprotocol/inspector .venv/bin/merchantops -e ZOHO_MODE=demo
```

Open the URL it prints. Call `match_order_to_payment` with `only_paid_not_invoiced` true. The demo result is SO-1008.
