from __future__ import annotations

import asyncio
import json

from merchantops.config import Settings
from merchantops.service import build_service


def _print(title: str, payload: dict) -> None:
    print(f"\n=== {title} ===")
    print(payload.get("summary", ""))
    brief = payload.get("brief")
    if brief:
        print(brief)
        return
    risks = payload.get("risks")
    if risks is not None:
        for risk in risks:
            print(f"  [{risk['severity']}] {risk['type']}: {risk['title']}")
        return
    actions = payload.get("actions")
    if actions is not None:
        for action in actions[:5]:
            print(f"  ({action['priority']}) {action['title']} [executable={action['executable']}]")
        if payload.get("omitted"):
            print(f"  ... {payload['omitted']} more")
        return
    matches = payload.get("matches")
    if matches is not None:
        for match in matches:
            print(
                f"  {match['order_number']} payments={match['payment_ids']} "
                f"invoiced={match['invoiced']} settled={match['settled_in_zoho']}"
            )
        return
    if "health" in payload:
        print(f"  health={payload['health']}")
        for reason in payload.get("reasons") or []:
            print(f"  - {reason}")
        return
    if "executed" in payload:
        print(json.dumps({key: payload[key] for key in ("executed", "action_type", "refusal")}, indent=2))
        return
    buckets = payload.get("buckets")
    if buckets:
        for name, rows in buckets.items():
            numbers = ", ".join(row["order_number"] for row in rows) or "none"
            print(f"  {name}: {numbers}")
        return
    if "value_tied_up" in payload and "items" in payload:
        for item in payload["items"]:
            print(f"  {item['sku']} on_hand={item['on_hand']} tied_up={item['value_tied_up']}")
        return
    if "items" in payload:
        for item in payload["items"]:
            print(f"  {item['sku']} available={item['available']} reorder={item['reorder_level']}")
        return
    if "fulfillment_possible" in payload:
        print(
            f"  source {payload['source_warehouse_name']} can_fulfill={payload['source_can_fulfill']} "
            f"alternatives={[row['warehouse_name'] for row in payload['alternatives']]}"
        )
        return
    if "daily_used" in payload:
        print(
            f"  daily {payload['daily_used']}/{payload['daily_limit']} "
            f"per-minute budget {payload['per_minute_budget']}"
        )


async def run_demo(settings: Settings | None = None) -> dict:
    settings = settings or Settings(_env_file=None, mode="demo", audit_log_path="logs/demo-audit.jsonl")
    service = build_service(settings)
    transcript = {}
    print("Merchant: What needs attention today?")
    transcript["risks"] = await service.detect_operational_risks()
    _print("detect_operational_risks", transcript["risks"])

    print("\nMerchant: What should I do?")
    transcript["actions"] = await service.recommend_next_actions()
    _print("recommend_next_actions", transcript["actions"])

    print("\nMerchant: Why replenish the earbuds in Mumbai?")
    transcript["explain"] = await service.explain_recommendation("stockout:SKU-EARBUD-PRO:wh_mum")
    _print("explain_recommendation", transcript["explain"])
    print("  evidence: " + "; ".join(transcript["explain"]["evidence"]))

    print("\nMerchant: Can Bengaluru fulfill 6 Mini Speakers, or can Mumbai?")
    transcript["alternate"] = await service.find_alternate_fulfillment("SKU-SPEAKER-MINI", 6, "wh_blr")
    _print("find_alternate_fulfillment", transcript["alternate"])

    print("\nMerchant: Which paid orders are not invoiced yet?")
    transcript["unbilled"] = await service.match_order_to_payment(only_paid_not_invoiced=True)
    _print("match_order_to_payment", transcript["unbilled"])

    print("\nMerchant: What's wrong with SO-1002?")
    transcript["health"] = await service.get_order_health("SO-1002")
    _print("get_order_health SO-1002", transcript["health"])

    print("\nMerchant: Show low stock. (This misses the warehouse imbalance on purpose.)")
    transcript["low_stock"] = await service.list_inventory(low_stock_only=True)
    _print("list_inventory low_stock_only", transcript["low_stock"])

    print("\nMerchant: Move 20 speakers from Mumbai to Bengaluru.")
    transcript["refused"] = await service.propose_action(
        "transfer_stock",
        reason="Bengaluru is short",
        payload={"sku": "SKU-SPEAKER-MINI", "quantity": 20},
    )
    _print("propose_action", transcript["refused"])

    print("\nMerchant: Which of last week's paid orders haven't shipped?")
    transcript["reconcile"] = await service.reconcile_orders()
    _print("reconcile_orders", transcript["reconcile"])

    print("\nMerchant: Where is cash tied up in stock that isn't selling?")
    transcript["dead"] = await service.dead_stock(days=30)
    _print("dead_stock", transcript["dead"])

    transcript["budget"] = await service.get_api_budget()
    _print("get_api_budget", transcript["budget"])

    transcript["brief"] = await service.get_daily_operations_brief()
    _print("get_daily_operations_brief", transcript["brief"])
    _check(transcript)
    print("\nDemo checks passed. The fixture merchant is Mira Audio on 2026-10-01. No Zoho account was called.")
    return transcript


def _check(transcript: dict) -> None:
    risks = transcript["risks"]["risks"]
    earbud = next(risk for risk in risks if risk["id"] == "stockout:SKU-EARBUD-PRO:wh_mum")
    assert "about 4 days" in earbud["title"]
    assert any(risk["id"] == "stockout:SKU-EARBUD-PRO:wh_blr" and risk["severity"] == "high" for risk in risks)
    assert any(risk["type"] == "imbalance" and "SKU-SPEAKER-MINI" in risk["sku"] for risk in risks)
    assert transcript["alternate"]["source_can_fulfill"] is False
    assert transcript["alternate"]["alternatives"][0]["warehouse_name"] == "Mumbai"
    assert [row["order_number"] for row in transcript["unbilled"]["matches"]] == ["SO-1008"]
    assert transcript["health"]["health"] == "AT_RISK"
    assert transcript["low_stock"]["items"][0]["sku"] == "SKU-EARBUD-PRO"
    assert all(item["sku"] != "SKU-SPEAKER-MINI" for item in transcript["low_stock"]["items"])
    shipped = [row["order_number"] for row in transcript["reconcile"]["buckets"]["paid_not_shipped"]]
    assert shipped == ["SO-1010"]
    assert transcript["reconcile"]["buckets"]["paid_not_invoiced"][0]["order_number"] == "SO-1008"
    assert transcript["dead"]["items"][0]["sku"] == "SKU-STAND-OLD"
    assert transcript["refused"]["executed"] is False
    assert transcript["explain"]["executable"] is False
    assert "4.0" in transcript["explain"]["evidence"][2] or "days_of_cover=4.0" in transcript["explain"]["evidence"]
    calls = transcript["budget"]["daily_used"]
    assert calls < 20, calls


def main() -> None:
    asyncio.run(run_demo())


if __name__ == "__main__":
    main()
