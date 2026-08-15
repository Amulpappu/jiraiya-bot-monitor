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
    """User Rule: Vehicle upgrade amount limit is ₹100 - ₹40,000.
    Amounts outside this range (e.g. ₹2,000,000 donations) are excluded."""
    if amount is not None:
        try:
            val = float(amount)
            if val < 100 or val > 40000:
                return False
        except (ValueError, TypeError):
            pass

    if not text:
        text = ""
    t = text.lower()
    if any(k in t for k in ("upgrade", "stage", "turbo", "engine", "brakes", "armor", "tuning", "custom", "mod", "transmission", "suspension")):
        return True

    if amount and amount > 0:
        val = float(amount)
        if 100 <= val <= 40000 and val % 7000.0 != 0 and val % 10000.0 != 0:
            return True

    return False


def resolve_category_and_count(amount: float, keyword_cat: str = "", text: str = "") -> dict:
    """Resolves exact service category, count, unit price, and total given amount, keyword, and message text.
    Civilian = ₹7,000 per unit, Govt / PD / EMS / Taxi = ₹10,000 per unit.
    When count is specified in text (e.g. '3x govt', 'civ 2', '2 civ'), total is calculated as count * unit_price."""
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

    # Extract explicit count from text:
    # 1. Number BEFORE category: '3x govt', '2 civ', '5 civilian'
    # 2. Number AFTER category: 'govt 3', 'civ 2', 'civ: 4', 'civ x 2'
    cnt = 1
    m_before = re.search(r"(\d+)\s*x?\s*(govt|gov|pd|ems|taxi|civ|civilian|service)", text_low)
    m_after = re.search(r"(govt|gov|pd|ems|taxi|civ|civilian|service)\s*x?\s*[:\-]?\s*(\d+)", text_low)

    if m_before:
        cnt = int(m_before.group(1))
    elif m_after:
        cnt = int(m_after.group(2))
    elif amount and amount > 0:
        cnt = max(1, int(round(amount / unit_price)))

    # If count was explicitly written in text, total is count * unit_price
    if (m_before or m_after) or (amount is None or amount <= 0):
        total = float(cnt * unit_price)
    else:
        total = float(amount)

    return {
        "category": cat,
        "count": cnt,
        "unit_price": unit_price,
        "total": total,
    }


def extract_amount_from_text(text: str) -> float:
    """Extracts numeric invoice amounts from message text or OCR fallback text,
    properly handling commas (e.g. 27,810), 'k' notation (7k, 10k, 20k), currency symbols,
    and 3 to 6 digit integers while excluding dates and years (e.g. 2026)."""
    if not text:
        return None

    # Exclude dates like 2026-08-10 or 2026/08/10
    t = re.sub(r"\b202\d[-/]\d{1,2}[-/]\d{1,2}\b", " ", text)
    # Exclude standalone year numbers 2024-2029
    t = re.sub(r"\b202[4-9]\b", " ", t)

    # 1. Match 'k' notation like 7k, 10k, 20k, 18k, 1k, 0.9k
    k_match = re.search(r"\b(\d+(?:\.\d+)?)\s*k\b", t, re.IGNORECASE)
    if k_match:
        try:
            return float(k_match.group(1)) * 1000.0
        except ValueError:
            pass

    # 2. Match currency symbols ₹, $, Rs., INR followed by numbers (including commas)
    curr_match = re.search(r"(?:[₹$]|Rs\.?|INR)\s*([\d,]+(?:\.\d{1,2})?)", t, re.IGNORECASE)
    if curr_match:
        try:
            val = float(curr_match.group(1).replace(",", ""))
            if val > 0:
                return val
        except ValueError:
            pass

    # 3. Match comma-separated numbers like 27,810 or 23,244 or 10,000 or 7,000
    comma_match = re.search(r"\b(\d{1,3}(?:,\d{3})+)\b", t)
    if comma_match:
        try:
            return float(comma_match.group(1).replace(",", ""))
        except ValueError:
            pass

    # 4. Labeled amounts like total: 7000 or amount: 10000
    label_match = re.search(r"(?:total|amount|price|paid|val|cost)\s*[:\-]?\s*(\d+)", t, re.IGNORECASE)
    if label_match:
        try:
            return float(label_match.group(1))
        except ValueError:
            pass

    # 5. Standalone numbers between 3 and 6 digits (excluding years)
    nums = re.findall(r"\b\d{3,6}\b", t)
    for n in nums:
        val = float(n)
        if 100 <= val <= 999999 and val not in (2024, 2025, 2026, 2027, 2028, 2029):
            return val

    return None
