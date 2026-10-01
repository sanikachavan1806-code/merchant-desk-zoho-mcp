# Zoho MerchantOps MCP

Existing connectors expose Zoho's endpoints. This one answers merchant questions that span inventory and payments, safely, within Zoho's API quotas.

A read-only operational layer over Zoho Inventory for a Razorpay merchant agent. It answers "what should I worry about today?" instead of wrapping Zoho's REST API as fifty create/list tools.

Zoho Inventory is the right system for this: Indian SMB merchants, orders and stock in one API, granular read scopes, and a real per-minute and per-day quota. Community servers already cover generic CRUD (Composio, MCPBundles) or read-only SQL (CData). Zoho's own MCP catalog, as publicly listed, covers CRM, Mail, Desk, and similar apps, not Inventory. The gap worth filling is merchant judgment: stock cover, fulfillment risk, unpaid fulfilled orders, and a Razorpay payment id that never became an invoice.

Agent Studio's connector document was not available here, so the server speaks MCP: tools, resources, and prompts, over stdio and streamable HTTP.

## Run the demo

No Zoho account is required. The fixture merchant is Mira Audio, Mumbai and Bengaluru, on 1 October 2026.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
python -m merchantops.demo
```

The merchant desk runs the same tools in the browser:

```bash
merchantops-desk
```

Open http://127.0.0.1:8787. Ask a question or pick a card. The path above the answer shows the question, the read-only check, the tool, the data source, and the result. A 30-day orders and revenue chart sits at the bottom. **Check a warehouse** opens the floor window.

## Proof

Three ways to show the server is the one an agent would call:

```bash
pytest
python -m merchantops.demo.smoke
merchantops-desk
```

The smoke script runs the Mira Audio story (4-day cover, SO-1008 unpaid-to-invoice, SO-1010 paid and not shipped, September GST ₹1,812.15, masked contact, refused transfer) and prints the error envelopes: `not_found`, `invalid_argument`, and the page cap. It exits non-zero if a number drifts. No Zoho account is called.

A configured organization, two reads only:

```bash
python -m merchantops.demo.smoke --live
```

`docs/TOOL_SPEC.md` is the contract: every tool, the shared envelope, and the error strings the agent receives.

MCP Inspector, demo mode so a live `.env` is not used. The server command comes first:

```bash
npx @modelcontextprotocol/inspector --cli .venv/bin/merchantops --method tools/list -e ZOHO_MODE=demo
```

The same call against `match_order_to_payment` returns SO-1008 from the demo fixture. The interactive UI is that command without `--cli` and `--method`.

![Inspector result for match_order_to_payment](docs/proof/inspector-match-order.png)

stdio, for a local agent:

```bash
merchantops
```

```json
{
  "mcpServers": {
    "zoho-merchantops": {
      "command": "merchantops",
      "env": { "ZOHO_MODE": "demo" }
    }
  }
}
```

Streamable HTTP is `http://127.0.0.1:8000/mcp` after `merchantops --transport streamable-http`.

## What a merchant can ask

| Question | Tool |
| --- | --- |
| What needs attention today? | `get_daily_operations_brief`, `detect_operational_risks` |
| What should I do, and why? | `recommend_next_actions`, `explain_recommendation` |
| What's wrong with SO-1002? | `get_order_health` |
| Can Mumbai cover a Bengaluru shortfall? | `find_alternate_fulfillment` |
| Which paid orders have no invoice? | `match_order_to_payment` |
| Which of last week's paid orders haven't shipped? | `reconcile_orders` |
| Where is cash tied up in stock that isn't selling? | `dead_stock` |
| How much GST did we collect in September? | `gst_summary` |
| Anything unusual in the last two weeks? | `detect_anomalies` |
| Show this SKU, these orders, this warehouse | `list_inventory`, `search_orders`, `list_warehouses` |
| Move stock / email the customer / capture the payment | `propose_action` refuses |

`docs/demo-conversation.md` is the scripted conversation. `docs/capabilities.md` is the can / cannot list, including quota and PII. `docs/architecture.md` is the request path.

In the fixture, Mumbai earbuds cover exactly 4.0 days (8 available, 14 sold in 7 days). Bengaluru speakers cover 2.0 days, and Mumbai can fulfill the open quantity of 6. SO-1008 carries `pay_NotInvoiced1008` and has no invoice. A low-stock list does **not** include the speaker, because total stock is above the reorder level. That miss is intentional.

### Questions that cross inventory and payments

Stripe, PayPal, Cashfree, and Razorpay each expose their own product. Third-party Zoho connectors expose Zoho's endpoints. None of them join stock, invoices, and a payment export. These four calls are the demo of that join. The payment id on the Zoho order (`reference_number`, notes, or `cf_razorpay_payment_id`) is the join key. Demo mode loads a built-in Razorpay export. Live mode uses `RAZORPAY_EXPORT_PATH` when you have one, and otherwise marks those ids as claimed, not captured.

**Which of last week's paid orders haven't shipped?**

`reconcile_orders` → `paid_not_shipped` is SO-1010 (`pay_Settled1010`, invoice paid, shipment date 12 Oct). SO-1008 is in `paid_not_invoiced` instead, because it has no invoice. SO-1012 is `refunded_stock_not_returned`. SO-1005, SO-1006, and SO-1007 are `invoiced_but_unpaid` even though the export shows those payments captured.

**Where is cash tied up?**

`dead_stock` with `days=30` → SKU-STAND-OLD, 40 on hand, ₹10,000.00 at purchase rate. The cases sold on 25 Sep, so they are slow, not dead.

**How much GST did we collect in September?**

`gst_summary` with `period=2026-09` → ₹1,812.15, of which ₹1,797.15 is at 18% and ₹15.00 is at 5%. This is the tax on the invoices. It is not a filed GSTR return.

**Anything unusual?**

`detect_anomalies` → 1 Oct has more orders than a typical day in the window, SO-1011 sold a cable at ₹99 against a ₹299 list rate, and SO-1010 failed once (`pay_Failed1010`) before `pay_Settled1010` captured.

A trimmed SO-1008 is 573 characters. The same order shaped like a Zoho sales-order payload, with addresses, notes, and comments, is 1,764 characters. `tests/test_standout.py` locks both numbers. At about 4 characters per token, that is roughly 143 tokens versus 441.

## Live Zoho

Copy `.env.example` to `.env`.

Self-client, no browser: set `ZOHO_MODE=live`, `ZOHO_DC=in`, `ZOHO_ORGANIZATION_ID`, and `ZOHO_ACCESS_TOKEN`. Add `ZOHO_REFRESH_TOKEN` plus the client id and secret if the access token should refresh.

Browser consent:

```bash
export TOKEN_ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
merchantops-auth login
```

The consent URL asks for read scopes only (`ZohoInventory.salesorders.READ` and the other `.READ` scopes in `auth/oauth.py`). It sends `access_type=offline` and `prompt=consent`. The refresh token is Fernet-encrypted on disk. Requests use `Authorization: Zoho-oauthtoken <token>` and `organization_id` on every call. The access token is refreshed in the minute before it expires, and once on HTTP 401.

`ZOHO_DC` is one of `us`, `eu`, `in`, `au`, `jp`, `ca`, `sa`, `cn`. A token `api_domain` is accepted only if its host is one of those eight API hosts.

The process exits if `READ_ONLY=false`. There is no flag that turns on writes.

## Quota

From the [Zoho Inventory API introduction](https://www.zoho.com/inventory/api/v1/introduction/):

- 100 requests per minute per organization
- Daily: Free 1,000, Standard 2,000, Professional 5,000, Premium 10,000, Enterprise 10,000

A US knowledge-base article lists different Standard and Premium numbers. Set `ZOHO_DAILY_LIMIT` when an organization does not match the introduction. `get_api_budget` tells the agent which ceiling it is using.

429 code **44** is per-minute: backoff with jitter, then retry. 429 code **45** is the daily cap: fail immediately with `error.scope = "daily"` and no `retry_after`. The client also stays at 80 requests per minute and 5 concurrent calls, caches list GETs for 45 seconds, and collapses duplicate in-flight GETs. Tests mock both 429s and a 401 that must refresh.

## Safety

- Phone and email are masked. `include_pii=true` is ignored unless `ZOHO_REVEAL_PII=true` was set by the operator.
- Order notes are not returned. Razorpay ids are pulled out first.
- Every tool call appends one audit line: tool, status, latency, source. Search text and free-text reasons are stored as `present`, not as values.
- Pages default to 20 and cap at 50. Intelligence scans at most 4 pages per resource and sets `meta.truncated` when it stops.
- `match_order_to_payment` does not call Razorpay. It only sees a payment id that Zoho already has on the order.
- `reconcile_orders` uses that same id. A Razorpay status of `captured` or `refunded` is present only when an export was loaded. Without one, the status is `referenced_not_verified`.
- Successful tool results include `meta.fetched_at` and `meta.sources` (system, resource, record ids) so a number can be traced back.

## What this deliberately does not do

Writes, customer email, payment capture, deletes, webhooks, SQL over the catalog, and full exports. Reasons are in `docs/capabilities.md`. A connector that can adjust stock from a prompt is a worse FDE submission than one that can explain why it will not.

## Layout

```text
src/merchantops/
  auth/            OAuth URL, refresh, encrypted store, login CLI
  zoho/            read-only client, normalizer, 429 policy
  intelligence.py  health, risks, cover
  finance.py       reconcile, dead stock, GST, anomaly rules
  service.py       pagination, cache, audit, envelopes
  server.py        MCP tools, resources, prompts
  demo/            Mira Audio fixture, demo script, smoke proof
tests/             429s, refresh, PII, cover arithmetic, MCP surface, smoke
docs/TOOL_SPEC.md  tools, envelopes, and every error string
```

## Tests

`pytest` covers the per-minute retry, the daily fail-fast, token refresh on 401, in-flight dedup, the read-only POST block, masked PII, the 4.0 day cover, the Razorpay not-invoiced match, and the MCP tool list. The demo script asserts the same story and exits non-zero if the fixture drifts.
