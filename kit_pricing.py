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

_LABEL_PATTERN = (
    r"(\d+)?\s*x?\s*"
    r"(rk|ck|repair\s*kit|repairkit|repair|cleaning\s*kit|cleaningkit|clean(?:ing)?)"
)
_TOKEN_RE = re.compile(_LABEL_PATTERN, re.IGNORECASE)
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
    Returns {"rk": int, "ck": int} parsed from shorthand text or OCR output,
    or None if nothing recognizable was found.

    Examples:
        "each 10"     -> {"rk": 10, "ck": 10}
        "100 each"    -> {"rk": 100, "ck": 100}
        "100 rk 100 ck" -> {"rk": 100, "ck": 100}
        "rk 100 ck 50" -> {"rk": 100, "ck": 50}
        "rk: 100, ck: 50" -> {"rk": 100, "ck": 50}
        "10 rk"       -> {"rk": 10, "ck": 0}
        "rk 10"       -> {"rk": 10, "ck": 0}
        "10 kits"     -> {"rk": 10, "ck": 10}
        "100"         -> {"rk": 100, "ck": 100}
    """
    if not text:
        return None
    t = text.strip()

    # 1. "100 each", "each 100", "100 ea", "ea 100", "100 per", "100 a piece"
    each_match = re.search(r"(\d+)\s*(?:each|ea|per|a\s*piece)|(?:each|ea|per)\s*(\d+)", t, re.IGNORECASE)
    if each_match:
        n = int(each_match.group(1) or each_match.group(2))
        return {"rk": n, "ck": n}

    rk_qty = None
    ck_qty = None

    pattern = re.compile(
        r"(?P<label1>rk|rks|repair\s*kits?|repairkit|repairkits|repair|ck|cks|clean(?:ing)?\s*kits?|cleaningkit|cleaningkits)\s*[:=\-]?\s*x?\s*(?P<num1>\d+)"
        r"|"
        r"(?P<num2>\d+)\s*x?\s*(?P<label2>rk|rks|repair\s*kits?|repairkit|repairkits|repair|ck|cks|clean(?:ing)?\s*kits?|cleaningkit|cleaningkits)\b",
        re.IGNORECASE
    )

    for m in pattern.finditer(t):
        lbl = m.group("label1") or m.group("label2")
        num_str = m.group("num1") or m.group("num2")
        if not lbl or not num_str:
            continue
        num = int(num_str)
        norm_lbl = "rk" if lbl.lower().startswith("r") else "ck"
        if norm_lbl == "rk" and rk_qty is None:
            rk_qty = num
        elif norm_lbl == "ck" and ck_qty is None:
            ck_qty = num

    if rk_qty is not None or ck_qty is not None:
        r_val = rk_qty if rk_qty is not None else 0
        c_val = ck_qty if ck_qty is not None else 0

        # 4. Handle trailing label without its own number (e.g. "100 rk, ck")
        if r_val > 0 and c_val == 0:
            if re.search(r"\b(?:ck|cks|clean(?:ing)?\s*kits?)\b", t, re.IGNORECASE):
                c_val = r_val
        elif c_val > 0 and r_val == 0:
            if re.search(r"\b(?:rk|rks|repair\s*kits?)\b", t, re.IGNORECASE):
                r_val = c_val

        return {"rk": r_val, "ck": c_val}

    # 5. Check for generic "100 kits" / "100 kit" / "kit 100"
    kit_gen = re.search(r"(\d+)\s*x?\s*(?:kits?)\b|\b(?:kits?)\s*[:=\-]?\s*x?\s*(\d+)\b", t, re.IGNORECASE)
    if kit_gen:
        n = int(kit_gen.group(1) or kit_gen.group(2))
        return {"rk": n, "ck": n}

    # 6. Check for standalone number(s) in short text (e.g. "100" or "50")
    digits_only = re.findall(r"\b(\d{1,4})\b", t)
    if digits_only and len(digits_only) == 1:
        n = int(digits_only[0])
        if 0 < n <= 2000:
            return {"rk": n, "ck": n}
    elif digits_only and len(digits_only) == 2:
        n1, n2 = int(digits_only[0]), int(digits_only[1])
        if 0 < n1 <= 2000 and 0 < n2 <= 2000:
            return {"rk": n1, "ck": n2}

    return None



def _discount_for(combined_qty: int) -> float:
    for lo, hi, pct in config.KIT_DISCOUNT_BRACKETS:
        if lo <= combined_qty <= hi:
            return pct
    # Above the top bracket's max, keep applying the highest discount.
    top_lo, top_hi, top_pct = max(config.KIT_DISCOUNT_BRACKETS, key=lambda b: b[1])
    if combined_qty > top_hi:
        return top_pct
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
