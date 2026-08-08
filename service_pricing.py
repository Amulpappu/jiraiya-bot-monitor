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
    Service amounts are ALWAYS flat ₹7,000 (Civilian) or ₹10,000 (Govt/PD/EMS/Taxi).
    If an amount is NOT an exact multiple of 7,000 or 10,000 (e.g. 27810, 23122), it is a Car Upgrade."""
    if not text:
        text = ""
    t = text.lower()
    if any(k in t for k in ("upgrade", "stage", "turbo", "engine", "brakes", "armor", "tuning", "custom", "mod", "transmission", "suspension")):
        return True

    if amount and amount > 0:
        val = float(amount)
        # Non-standard service amounts (e.g. 27810, 23122) are vehicle upgrade invoices
        if val % 7000.0 != 0 and val % 10000.0 != 0:
            return True

    return False


def resolve_category_and_count(amount: float, keyword_cat: str = "", text: str = "") -> dict:
    """Resolves exact service category, count, unit price, and total given amount, keyword, and message text.
    Civilian = ₹7,000 per unit, Govt / PD / EMS / Taxi = ₹10,000 per unit.
    When count is specified in text (e.g. '3x govt'), total is calculated as count * unit_price."""
    text_low = (text or "").lower()
    cat = keyword_cat.lower() if keyword_cat else parse_service_category(text)

    # If no explicit keyword found in text, infer category from amount:
    # ₹10,000 or multiples ➔ Govt Employee
    # ₹7,000 or non-10k ➔ Civilian
    if not cat:
        if amount and (amount >= 9500.0 or (amount > 0 and amount % 10000 == 0)):
            cat = "govt"
        else:
            cat = "civilian"

    unit_price = float(config.SERVICE_PRICES.get(cat, 10000.0 if cat in ("govt", "pd", "ems", "taxi", "gov") else 7000.0))

    # Extract explicit count from text (e.g. '3x govt', '2 govt', '5x civ')
    cnt = 1
    match = re.search(r"(\d+)\s*x?\s*(govt|gov|pd|ems|taxi|civ|civilian|service)", text_low)
    if match:
        cnt = int(match.group(1))
    elif amount and amount > 0:
        cnt = max(1, int(round(amount / unit_price)))

    # If count was explicitly written in text (e.g. 3x govt), total is count * unit_price
    if match or (amount is None or amount <= 0):
        total = float(cnt * unit_price)
    else:
        total = float(amount)

    return {
        "category": cat,
        "count": cnt,
        "unit_price": unit_price,
        "total": total,
    }
