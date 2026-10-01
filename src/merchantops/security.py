from __future__ import annotations

import re

from merchantops.errors import ReadOnlyViolation

_EMAIL = re.compile(r"\b([A-Za-z0-9._%+\-]+)@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b")
_PHONE = re.compile(r"(?<!\w)(?:\+91[\s-]?)?([6-9]\d{9})(?!\w)")

# Writes this connector will not perform, even if a future caller asks.
REFUSED_ACTIONS = {
    "create_purchase_order": "Creating a purchase order mutates purchasing. Not exposed.",
    "create_sales_order": "Creating a sales order mutates orders. Not exposed.",
    "inventory_adjustment": "An agent must not change on-hand stock. Not exposed.",
    "update_order_status": "Confirming, voiding, or approving orders is not exposed.",
    "create_package": "Creating packages is a warehouse write. Not exposed.",
    "create_shipment": "Creating shipments is a warehouse write. Not exposed.",
    "transfer_stock": "Moving stock between warehouses is an inventory write. Not exposed.",
    "replenish": "Raising a purchase order is a write. Not exposed.",
    "email_customer": "This connector will not email customers.",
    "delete_order": "Deletes are not exposed and are not on the roadmap for this server.",
    "delete_invoice": "Deletes are not exposed.",
    "payment_execution": "Moving money is a Razorpay payment-tool concern, not an inventory connector.",
    "void_invoice": "Voiding invoices is not exposed.",
}


def assert_http_read(method: str) -> None:
    if method.upper() != "GET":
        raise ReadOnlyViolation(
            f"Blocked {method.upper()} to Zoho. This connector only issues GET requests."
        )


def mask_email(email: str | None) -> str | None:
    if not email:
        return None
    if "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    prefix = local[:1] if local else ""
    return f"{prefix}***@{domain}"


def mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 4:
        return "******"
    return f"******{digits[-4:]}"


def scrub_free_text(value: str | None) -> str | None:
    if not value:
        return value
    masked = _EMAIL.sub(lambda match: mask_email(match.group(0)) or "***", value)
    return _PHONE.sub(lambda match: mask_phone(match.group(1)) or "******", masked)


def refusal_for(action_type: str) -> str:
    key = action_type.strip().lower()
    return REFUSED_ACTIONS.get(
        key,
        "That action is not a read. This connector does not mutate Zoho Inventory or Razorpay.",
    )
