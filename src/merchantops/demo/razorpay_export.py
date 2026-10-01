"""Fixture Razorpay payments and settlements for Mira Audio.

Join key: a Zoho sales order's reference_number (or notes) holds the Razorpay
payment id, pay_... or plink_.... The export repeats that id and may also set
zoho_salesorder_number. Amounts are rupees. A file export may instead send
paise; the loader divides by 100 when amount_unit is "paise".

This is not a live Razorpay API call.
"""

from __future__ import annotations

DEMO_RAZORPAY_EXPORT: dict = {
    "payments": [
        {"id": "pay_Shipped0904", "amount": "1495.00", "currency": "INR", "status": "captured", "created_at": "2026-09-29T11:00:00+05:30", "zoho_salesorder_number": "SO-0904", "settlement_id": "setl_20260930"},
        {"id": "pay_UnpaidInv1005", "amount": "3998.00", "currency": "INR", "status": "captured", "created_at": "2026-09-30T16:10:00+05:30", "zoho_salesorder_number": "SO-1005"},
        {"id": "pay_Overdue1006", "amount": "4998.00", "currency": "INR", "status": "captured", "created_at": "2026-09-29T15:00:00+05:30", "zoho_salesorder_number": "SO-1006"},
        {"id": "pay_Partial1007", "amount": "299.00", "currency": "INR", "status": "captured", "created_at": "2026-09-26T12:00:00+05:30", "zoho_salesorder_number": "SO-1007"},
        {"id": "pay_NotInvoiced1008", "amount": "299.00", "currency": "INR", "status": "captured", "created_at": "2026-10-01T10:05:00+05:30", "zoho_salesorder_number": "SO-1008"},
        {"id": "pay_Failed1010", "amount": "1196.00", "currency": "INR", "status": "failed", "created_at": "2026-09-28T09:00:00+05:30", "zoho_salesorder_number": "SO-1010"},
        {"id": "pay_Settled1010", "amount": "1196.00", "currency": "INR", "status": "captured", "created_at": "2026-09-28T09:12:00+05:30", "zoho_salesorder_number": "SO-1010", "settlement_id": "setl_20260930"},
        {"id": "pay_Refund1012", "amount": "299.00", "currency": "INR", "status": "refunded", "created_at": "2026-09-25T18:40:00+05:30", "zoho_salesorder_number": "SO-1012"},
    ],
    "settlements": [
        {"id": "setl_20260930", "status": "processed", "payment_ids": ["pay_Shipped0904", "pay_Settled1010"]},
    ],
}
