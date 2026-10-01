# Sample agent conversation

Merchant: **Mira Audio**, warehouses in Mumbai and Bengaluru, as of **1 October 2026**. Run `python -m merchantops.demo` to reproduce this against the fixture. No Zoho account is called.

The interesting beat is the third one: a total-stock query hides the warehouse that is about to stock out. The risk tool does not.

## What needs attention today?

Agent calls `detect_operational_risks`.

> Risks: 4 fulfillment, 3 revenue, 3 stockout, 1 imbalance, 1 slow-moving.
>
> - SO-1004 ships today and is not fully shipped.
> - SO-1005, SO-1006, and SO-1007 are fulfilled with ₹3,998.00, ₹4,998.00, and ₹150.00 still open.
> - SKU-EARBUD-PRO is already out of stock in Bengaluru.
> - SKU-SPEAKER-MINI in Bengaluru runs out in about 2 days.
> - SKU-EARBUD-PRO in Mumbai runs out in about 4 days.
> - SKU-SPEAKER-MINI is tight in Bengaluru and comfortable in Mumbai.

## What should I do? Why the earbuds?

Agent calls `recommend_next_actions`, then `explain_recommendation` for `stockout:SKU-EARBUD-PRO:wh_mum`.

> SKU-EARBUD-PRO at Mumbai runs out in about 4 days.
> Evidence: available=8, demand over 7 days=14, days of cover=4.0, reorder level=20.
> This is a 7-day demand window, not a forecast. `executable` is false. I will not raise a purchase order.

## Can Bengaluru ship 6 Mini Speakers?

Agent calls `find_alternate_fulfillment` with SKU `SKU-SPEAKER-MINI`, quantity 6, source `wh_blr`.

> Bengaluru has 4 available, so it cannot. Mumbai has 40 and can. This did not create a transfer.

## Which paid orders are not invoiced yet?

Agent calls `match_order_to_payment` with `only_paid_not_invoiced=true`.

> SO-1008 references Razorpay payment `pay_NotInvoiced1008` and has no Zoho invoice.
> This match uses the id stored on the Zoho order. It is not a live Razorpay API call.
> SO-1005 is different: Razorpay id `pay_UnpaidInv1005` is present, and invoice INV-1005 is unpaid. That is a collection problem, not a missing invoice.

## Which of last week's paid orders haven't shipped?

Agent calls `reconcile_orders`.

> Paid and not shipped: SO-1010, payment `pay_Settled1010`, invoice paid, ships 12 Oct.
> Paid but not invoiced: SO-1008.
> Invoiced but unpaid, and captured in the export: SO-1005, SO-1006, SO-1007.
> Refunded, stock not returned: SO-1012.
> The join key is the Razorpay id on the Zoho order. The demo loads a fixture export. Without that file, the same ids are marked unverified.

## Where is cash tied up, and what GST did September collect?

Agent calls `dead_stock` with `days=30`, then `gst_summary` with `period=2026-09`.

> SKU-STAND-OLD has not sold in 30 days. 40 on hand is ₹10,000.00 at purchase rate.
> September invoices show ₹1,812.15 of tax: ₹1,797.15 at 18% and ₹15.00 at 5%. That is not a filed GST return.

## What's wrong with SO-1002?

Agent calls `get_order_health`.

> AT_RISK. SKU-EARBUD-PRO needs 2 in Bengaluru and available is 0. Shipment date is tomorrow and no package exists. Creating the package is a write, so I will not do it.

## Show me low stock

Agent calls `list_inventory` with `low_stock_only=true`.

> One item: SKU-EARBUD-PRO, 8 available against a reorder level of 20.
> Mini Speakers are not in this list. Total available is 44, above the reorder level of 10. The shortage is only in Bengaluru, which is why the risk tool exists.

## Move 20 speakers from Mumbai to Bengaluru

Agent calls `propose_action` with `transfer_stock`.

> Refused. Nothing was changed in Zoho or Razorpay. Moving stock is an inventory write and is not exposed.

The whole script uses 7 logical reads. `get_api_budget` reports 7 of 1,000 for the free plan, and a client budget of 80 per minute under Zoho's 100 per minute cap.
