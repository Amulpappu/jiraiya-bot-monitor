import re
import config


def parse_service_category(text: str) -> str:
    """Parses service category keywords from text (e.g. 'pd', 'ems', 'taxi', 'gov', 'civilian', 'upgrade')."""
    if not text:
        return ""
    t = text.lower()

    if any(k in t for k in ("upgrade", "stage", "turbo", "engine", "brakes", "armor", "tuning")):
        return "upgrade"
    elif any(k in t for k in ("pd", "police", "cop")):
        return "pd"
    elif any(k in t for k in ("ems", "medic", "hospital")):
        return "ems"
    elif "taxi" in t:
        return "taxi"
    elif any(k in t for k in ("gov", "govt", "government")):
        return "govt"
    elif any(k in t for k in ("civ", "civilian", "car service", "service")):
        return "civilian"

    return ""


def is_upgrade_message(text: str, amount: float = None) -> bool:
    """Detects whether a message represents a Vehicle Upgrade (vs standard Car Service).
    Upgrade amounts do not exceed ₹40,000."""
    if not text:
        text = ""
    t = text.lower()
    if any(k in t for k in ("upgrade", "stage", "turbo", "engine", "brakes", "armor", "tuning", "custom")):
        return True
    if amount is not None and amount >= 15000.0:
        # Amount 15,000+ that doesn't cleanly match 7,000 or 10,000 service multiples
        if amount % 7000 != 0 and amount % 10000 != 0:
            return True
        if amount >= 35000.0:
            return True
    return False


def resolve_category_and_count(amount: float, keyword_cat: str = "") -> dict:
    """Resolves exact service category, count, and unit price given an amount and keyword.
    Preserves and logs the exact correct amount parsed from the invoice image/text."""
    cat = keyword_cat.lower() if keyword_cat else "civilian"
    unit_price = float(config.SERVICE_PRICES.get(cat, 7000.0))

    if amount is None or amount <= 0:
        return {"category": cat, "count": 1, "unit_price": unit_price, "total": unit_price}

    # Count calculation based on unit price
    cnt = max(1, int(round(amount / unit_price)))
    # Log the exact correct amount parsed from the invoice image/text!
    total = float(amount)

    return {
        "category": cat,
        "count": cnt,
        "unit_price": unit_price,
        "total": total,
    }
