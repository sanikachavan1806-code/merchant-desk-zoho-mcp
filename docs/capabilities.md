# What the agent can and cannot do

This connector is a read-only merchant-operations layer. It is not a Zoho Inventory admin API, and it is not a payments API.

The guarantee is enforced in two places: the HTTP client rejects every method other than `GET`, and the process refuses to start if `READ_ONLY=false`. `propose_action` exists so the agent has somewhere to land when a person asks for a mutation. It records the request and changes nothing.

## Can

| Capability | Tool | Approval |
| --- | --- | --- |
| Search and fetch sales orders | `search_orders`, `get_order` | No |
| Search stock, including per warehouse | `list_inventory`, `get_inventory_item` | No |
| List warehouses, invoices, shipments | `list_warehouses`, `list_invoices`, `list_shipments` | No |
| Read a customer with phone and email masked | `get_customer` | No |
| Say whether one order is healthy, watch, or at risk | `get_order_health` | No |
| Find stock, shipment, collection, and imbalance risks | `detect_operational_risks` | No |
| Check if another warehouse can cover a quantity | `find_alternate_fulfillment` | No |
| Rank what a person should look at next | `recommend_next_actions` | No |
| Show the arithmetic behind a recommendation | `explain_recommendation` | No |
| Produce today's operations brief | `get_daily_operations_brief` | No |
| Match a Zoho order to a Razorpay `pay_` or `plink_` id stored on that order | `match_order_to_payment` | No |
| Bucket orders across Zoho invoices, shipments, and an optional Razorpay export | `reconcile_orders` | No |
| Value stock that has not sold in N days | `dead_stock` | No |
| Sum invoice tax by rate for a month | `gst_summary` | No |
| Flag order spikes, unusual discounts, and failed-then-paid payments | `detect_anomalies` | No |
| See today's Zoho call budget before scanning | `get_api_budget` | No |
| Ask for a write and be refused | `propose_action` | The refusal is the behavior |

Recommendations are not execution. `executable` is always `false`. Replenishment and stock transfers are labeled as actions that would need approval if a write path existed. This server does not have that path.

## Cannot

| Request | Why it is not here |
| --- | --- |
| Create, confirm, void, or delete a sales order | An agent mutating orders is a high-impact mistake. The brief asks for reads. |
| Adjust stock, transfer warehouses, create packages or shipments | Same reason. `find_alternate_fulfillment` answers the question and stops. |
| Create a purchase order | Replenishment is recommended with evidence. Raising the PO stays with a person. |
| Email a customer | The connector can see that an invoice is unpaid. It will not send mail. |
| Capture, refund, or move a Razorpay payment | Payment execution belongs on Razorpay's own tools. This server only reads a payment id that Zoho already stored on the order. |
| Delete anything | Not exposed, and not planned for this server. |
| Webhooks or a live sync | Out of scope. Answers are request-time reads with a short cache. |
| SQL over the Zoho catalog | Hard to keep read-only and easy to turn into a full export. |
| A full catalog crawl | List tools cap a page at 50. Intelligence tools scan at most 4 pages per resource, then set `meta.truncated`. |
| `ZohoInventory.*.ALL` or any write scope | The OAuth URL requests granular `.READ` scopes only. |

## PII

Order payloads do not include email, phone, or free-text notes. Payment ids are extracted from the reference and notes first; the notes themselves are dropped, and any phone or email left in a reference is masked.

`get_customer` returns `r***@example.com` and `******3210` by default. Passing `include_pii=true` does nothing unless the operator set `ZOHO_REVEAL_PII=true` before startup. The model cannot talk the server into revealing contact details. The audit log stores parameter names and ids, not the search text, the reason text, or the contact fields.

## Quota

Zoho Inventory's API introduction documents:

- 100 requests per minute per organization
- Daily ceilings of 1,000 (Free), 2,000 (Standard), 5,000 (Professional), 10,000 (Premium and Enterprise)

A US knowledge-base page lists Standard as 2,500 and Premium as 75,000. `get_api_budget` uses the introduction figures unless `ZOHO_DAILY_LIMIT` is set for that organization. Say which number you are using if a merchant disputes it.

HTTP 429 is not one failure:

- Body code **44** is the per-minute block. The client waits with exponential backoff and jitter, then retries.
- Body code **45** is the daily ceiling (Zoho's own example uses "call rate limit of 1000"). The client fails immediately with `error.code = rate_limited` and `scope = daily`. Retrying would not help and can extend a block.

The client also keeps its own token bucket at 80 requests per minute, so it stays under the platform cap, and a semaphore of 5, which is the free-plan concurrent-call ceiling and is therefore safe on every plan. List responses are cached for about 45 seconds, and identical in-flight GETs share one Zoho call.

In demo mode the same budget tool counts logical reads against the fixture, not HTTP calls. The counting mode is in the payload.

## Known gaps, chosen on purpose

- **No write path after approval.** A confirmation flag that still cannot call Zoho is clearer than a half-built approval workflow. `propose_action` is the boundary.
- **No live Razorpay API.** `match_order_to_payment` trusts the `pay_` / `plink_` id a merchant already wrote onto the Zoho order. `reconcile_orders` can also read a payments export (`RAZORPAY_EXPORT_PATH`, JSON with `payments` and `settlements`). Amounts in that file are rupees unless `amount_unit` is `paise`. Without an export, a stored id is `referenced_not_verified`. A payment that was never copied onto the order stays invisible.
- **GST summary is not a return.** `gst_summary` adds `tax_amount` by `tax_rate` on non-void invoices. It does not file GSTR-1 or split CGST and SGST.
- **Anomalies are rules.** A day with at least 4 orders and more than twice the median, a line below 70% of the selling rate, and a failed payment followed by a capture on the same order. No model is trained.
- **Roadmap, not built.** A restock purchase order that a person must approve, a Razorpay payment-link suggestion for an unpaid invoice, and webhook alerts. None of those write today.
- **Stock checks use Zoho's available-stock snapshot.** Available already nets commitments, so a line that is itself committed can look short. The evidence lists the numbers it compared. It does not "fix" the snapshot.
- **Demand is the last 7 days of non-void orders, divided evenly.** `explain_recommendation` says this. It is not a forecast model, and it should not be described as one.
- **`low_stock_only` compares total available stock with the item reorder level.** In the demo, Mini Speakers are not "low stock" in total (44 available, reorder 10) while Bengaluru is two days from empty. That is why the risk tool exists.
- **Scans are capped.** A merchant with more than 200 orders in the scanned pages gets `meta.truncated: true`. The agent is instructed not to treat that as the whole catalog.
- **Demo mode is Mira Audio on 1 October 2026.** It is there so a reviewer can run the server with no Zoho org. It is not that merchant's live inventory.

## Scopes requested in live mode

`ZohoInventory.salesorders.READ`, `ZohoInventory.items.READ`, `ZohoInventory.invoices.READ`, `ZohoInventory.contacts.READ`, `ZohoInventory.settings.READ`, `ZohoInventory.shipmentorders.READ`, `ZohoInventory.packages.READ`.

`ZohoInventory.FullAccess.ALL` is never requested.
