"""
Parses the shorthand quantity notation players type alongside a kit invoice
screenshot (e.g. "each 10", "100 each", "1x rk, ck", "5 rk 3 ck") and
calculates the correctly discounted total using config.KIT_PRICES and
config.KIT_DISCOUNT_BRACKETS.

The invoice screenshot's OCR'd $ amount is NOT used as the source of truth
for kits — the player-typed quantity is, since one shared total can't be
split unambiguously between two differently-priced kit types.
"""
import re

import config

_LABEL_BEFORE_PATTERN = (
    r"(\d+)\s*x?\s*"
    r"(rk|ck|repair\s*kit|repairkit|repair|cleaning\s*kit|cleaningkit|clean(?:ing)?)"
)
_LABEL_AFTER_PATTERN = (
    r"(rk|ck|repair\s*kit|repairkit|repair|cleaning\s*kit|cleaningkit|clean(?:ing)?)"
    r"\s*[:\-]?\s*(\d+)"
)

_BEFORE_RE = re.compile(_LABEL_BEFORE_PATTERN, re.IGNORECASE)
_AFTER_RE = re.compile(_LABEL_AFTER_PATTERN, re.IGNORECASE)
_EACH_RE = re.compile(r"(\d+)\s*each|each\s*(\d+)", re.IGNORECASE)


def _normalize_label(raw: str):
    raw = raw.lower().strip()
    if raw.startswith("r"):
        return "rk"
    if raw.startswith("c"):
        return "ck"
    return None


def parse_kit_quantities(text: str):
    """
    Returns {"rk": int, "ck": int} parsed from shorthand text, or None if
    nothing recognizable was found.

    Examples:
        "each 10"     -> {"rk": 10, "ck": 10}
        "100 each"    -> {"rk": 100, "ck": 100}
        "1x rk, ck"   -> {"rk": 1, "ck": 1}
        "5x rk 3x ck" -> {"rk": 5, "ck": 3}
        "10 rk"       -> {"rk": 10, "ck": 0}
        "rk 100"      -> {"rk": 100, "ck": 0}
        "rk: 50"      -> {"rk": 50, "ck": 0}
    """
    if not text:
        return None
    t = text.strip()

    each_match = _EACH_RE.search(t)
    if each_match:
        n = int(each_match.group(1) or each_match.group(2))
        return {"rk": n, "ck": n}

    result = {"rk": 0, "ck": 0}
    found_any = False

    # 1. Try number BEFORE label (e.g., "100 rk", "50x ck")
    for m in _BEFORE_RE.finditer(t):
        num_str, label = m.group(1), m.group(2)
        key = _normalize_label(label)
        if key and num_str:
            result[key] = int(num_str)
            found_any = True

    # 2. Try number AFTER label (e.g., "rk 100", "ck: 50")
    if not found_any:
        for m in _AFTER_RE.finditer(t):
            label, num_str = m.group(1), m.group(2)
            key = _normalize_label(label)
            if key and num_str:
                result[key] = int(num_str)
                found_any = True

    # 3. Fallback: single standalone number in kit channel (e.g. "100")
    if not found_any:
        digits = re.findall(r"\b\d{1,4}\b", t)
        if len(digits) == 1:
            n = int(digits[0])
            # Default single number to RK
            return {"rk": n, "ck": 0}

    return result if found_any else None


def _discount_for(combined_qty: int) -> float:
    """Looks up the discount fraction for a combined RK+CK quantity using
    config.KIT_DISCOUNT_BRACKETS (min, max, discount_fraction)."""
    for lo, hi, pct in config.KIT_DISCOUNT_BRACKETS:
        if lo <= combined_qty <= hi:
            return pct
    return 0.0


def calculate_kit_total(rk_qty: int, ck_qty: int):
    """
    Returns (total_amount, discount_pct, combined_qty, rk_subtotal, ck_subtotal)
    using combined-quantity discount brackets applied evenly to both kit types.
    rk_subtotal/ck_subtotal are each type's own discounted total, useful when
    logging RK and CK as separate line items even though billed together.
    """
    combined_qty = rk_qty + ck_qty
    discount = _discount_for(combined_qty)

    rk_total = round(rk_qty * config.KIT_PRICES["rk"] * (1 - discount), 2)
    ck_total = round(ck_qty * config.KIT_PRICES["ck"] * (1 - discount), 2)

    return round(rk_total + ck_total, 2), discount, combined_qty, rk_total, ck_total
