# Architecture

The agent should see merchant questions, not Zoho endpoints.

```text
Agent Studio
    │  MCP (stdio or streamable HTTP)
    ▼
Zoho MerchantOps
    ├─ tool registry, resources, prompts
    ├─ policy: read-only process, PII mask, audit line
    ├─ intelligence: health, risks, reconciliation, brief
    └─ backend
         ├─ demo catalog (no credentials)
         └─ Zoho client
              auth → token bucket (80/min) → semaphore (5)
              → cache / in-flight dedup → GET only → retry
```

A weak connector is `50 CRUD tools → Zoho`. This server exposes 17 tools. Seven of them read a normalized record. The rest answer an operational question and say when the answer is incomplete.

## Layers

| Layer | Responsibility |
| --- | --- |
| `auth/` | Authorization-code URL with `access_type=offline`, refresh, encrypted token file, self-client access token |
| `zoho/client.py` | Datacenter routing, `Authorization: Zoho-oauthtoken`, `organization_id` on every call, 429 handling |
| `intelligence.py` | Pure functions over a snapshot. No HTTP. Tests lock the arithmetic |
| `service.py` | Pagination, field projection, snapshot cache, audit, structured errors |
| `server.py` | MCP tools, three resources, three prompts |

## Rate limit

```text
tool call
  → snapshot cache (45s) or one page
  → if the local daily counter is exhausted: fail, no HTTP
  → token bucket
  → at most 5 concurrent GETs
  → 429 code 44: backoff with jitter, retry
  → 429 code 45: fail fast, scope=daily, retry_after=null
```

Retries count toward the daily meter because Zoho already counted them. Cache hits do not. Two identical GETs that overlap share one upstream call.

`api_domain` from a token response is accepted only when the host is one of the eight Zoho API hosts (`us`, `eu`, `in`, `au`, `jp`, `ca`, `sa`, `cn`). Anything else is refused. Indian merchants use `ZOHO_DC=in`.

## Agent-shaped responses

Every tool returns:

- `summary`, one line the model can say out loud
- `meta.read_only`, `meta.pii_redacted`, `meta.truncated`, `meta.calls_used`, `meta.source` (`demo` or `zoho`)
- `meta.fetched_at`, and `meta.sources` with the system, resource, and record ids behind the numbers
- a trimmed record, not the Zoho payload
- `next_cursor` when another page exists

Pages default to 20 and cannot exceed 50. `fields` drops keys the agent did not ask for.

Intelligence tools load one snapshot (orders, items, invoices, shipments, packages, warehouses) and reuse it for 45 seconds. The demo conversation spends 7 logical reads on the whole script, against a free-plan ceiling of 1,000.

## Reconciliation

`match_order_to_payment` does not call Razorpay. It reads `pay_` and `plink_` ids from the Zoho order's reference number, notes, or `cf_razorpay_payment_id`, then compares that with the linked invoice. "Paid on Razorpay but not invoiced" means the id is present and no invoice is linked. A captured payment that nobody copied onto the order is invisible here, and the tool says so when it finds nothing.

`reconcile_orders` uses that same join key and, when a Razorpay export is loaded, the export's status and settlement id. Buckets are mutually exclusive: refunded with stock not returned, then paid but not invoiced, then invoiced but unpaid, then paid and shipped, then paid and not shipped. Captured payments missing from a processed settlement are listed beside the buckets. Demo mode ships a fixture export. Live mode reads `RAZORPAY_EXPORT_PATH` or leaves every id unverified.

## Errors the agent can explain

```json
{
  "summary": "Zoho daily API quota is exhausted for this organization.",
  "error": {
    "code": "rate_limited",
    "scope": "daily",
    "retry_after": null,
    "message": "..."
  }
}
```

Per-minute limits include `retry_after`. Not-found, bad cursors, and refused writes use the same envelope. Unexpected exceptions are logged and returned as `internal` without the stack or the token.
