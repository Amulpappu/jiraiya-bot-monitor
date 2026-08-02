import re
import config


def parse_kit_quantities(text: str) -> dict:
    """Parses RK (Repair Kit) and CK (Cleaning Kit) quantities from message text or OCR output."""
    if not text:
        return None

    rk = 0
    ck = 0
    t = text.lower()

    m_rk = re.search(r"(\d+)\s*(?:x\s*)?(?:repair\s*kit|repair|rk)", t)
    if m_rk:
        try: rk = int(m_rk.group(1))
        except ValueError: pass

    m_ck = re.search(r"(\d+)\s*(?:x\s*)?(?:cleaning\s*kit|clean|ck)", t)
    if m_ck:
        try: ck = int(m_ck.group(1))
        except ValueError: pass

    if rk == 0 and ck == 0:
        # Check single numbers with 'kit' keyword
        m_single = re.search(r"(\d+)\s*(?:x\s*)?kits?", t)
        if m_single:
            try: rk = int(m_single.group(1))
            except ValueError: pass

    if rk == 0 and ck == 0:
        return None

    return {"rk": rk, "ck": ck}


def predict_kit_quantities_from_amount(amount: float) -> tuple:
    """Decomposes any total amount into exact integer quantities of Repair Kits (at ₹1,000) and Cleaning Kits (at ₹900).
    For example: ₹19,000 → 10x Repair Kit (₹10,000) + 10x Cleaning Kit (₹9,000).
    ₹541,500 → 285x Repair Kit + 285x Cleaning Kit."""
    if not amount or amount <= 0:
        return 1, 0

    best_match = (1, 0)
    min_diff = float("inf")
    min_rk_ck_diff = float("inf")

    for rk in range(0, 1000):
        for ck in range(0, 1000):
            if rk == 0 and ck == 0:
                continue
            tot = (rk * 1000.0) + (ck * 900.0)
            diff = abs(tot - amount)
            rk_ck_diff = abs(rk - ck)

            if diff < min_diff:
                min_diff = diff
                min_rk_ck_diff = rk_ck_diff
                best_match = (rk, ck)
            elif diff == min_diff and rk_ck_diff < min_rk_ck_diff:
                min_rk_ck_diff = rk_ck_diff
                best_match = (rk, ck)

    return best_match


def calculate_kit_total(rk_qty: int, ck_qty: int) -> tuple:
    """Calculates subtotal, discount, and total amount for RK and CK kits."""
    rk_qty = max(0, rk_qty or 0)
    ck_qty = max(0, ck_qty or 0)

    rk_price = config.KIT_PRICES["rk"]
    ck_price = config.KIT_PRICES["ck"]

    rk_subtotal = rk_qty * rk_price
    ck_subtotal = ck_qty * ck_price
    subtotal = rk_subtotal + ck_subtotal

    total_kits = rk_qty + ck_qty
    discount_pct = 0.0

    if total_kits >= 10:
        discount_pct = 0.05
    elif total_kits >= 20:
        discount_pct = 0.10

    discount_amount = subtotal * discount_pct
    total = round(subtotal - discount_amount, 2)

    return total, discount_pct, total_kits, rk_subtotal, ck_subtotal
