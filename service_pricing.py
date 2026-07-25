"""
Parses the service category a mechanic types alongside a service invoice
(e.g. "civilian", "civ", "police", "pd", "ems", "government", "gov", "taxi")
and maps it to the flat rate in config.SERVICE_PRICES.

Unlike kits, service pricing isn't calculated from a quantity — it's a
fixed rate per category. If no category keyword is found in the message
(mechanic forgot to type it), the caller falls back to OCR'ing the amount
straight off the invoice screenshot and flags the entry for manual review.
"""
import re

import config

# Longest/most specific keywords first so e.g. "government" isn't cut short
# by a shorter overlapping keyword during matching.
_CATEGORY_KEYWORDS = {
    "civilian": "civilian",
    "civ": "civilian",
    "government": "gov",
    "govt": "gov",
    "gov": "gov",
    "police": "pd",
    "pdm": "pd",
    "pd": "pd",
    "ems": "ems",
    "taxi": "taxi",
}

# Sorted longest-first so the regex alternation matches "government" before
# it could otherwise be partially matched by a shorter keyword.
_SORTED_KEYWORDS = sorted(_CATEGORY_KEYWORDS.keys(), key=len, reverse=True)
_CATEGORY_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _SORTED_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def parse_service_category(text: str):
    """Returns one of 'civilian', 'pd', 'ems', 'gov', 'taxi', or None if no
    category keyword is found in the text."""
    if not text:
        return None
    match = _CATEGORY_RE.search(text)
    if not match:
        return None
    return _CATEGORY_KEYWORDS[match.group(1).lower()]


def price_for(category: str):
    return config.SERVICE_PRICES.get(category)


def resolve_category_and_count(amount, keyword_category):
    """
    Works out the category AND how many service calls were bundled into one
    invoice, e.g. 6000 = civilian x2, 15000 = government-tier x3 — because a
    payer sometimes gets billed for multiple services in a single invoice.

    Priority: if the message has a keyword AND the amount cleanly divides by
    that category's price, trust the keyword (it tells us the specific
    subtype — ems/pd/gov/taxi — that amount alone can't distinguish, since
    they all share the 5000 rate). Otherwise infer purely from which price(s)
    the amount is a clean multiple of.

    Returns dict: {category, count, confident, reason}
        category: 'civilian' | 'ems' | 'pd' | 'gov' | 'taxi' | None
        count:    int (number of services billed together) | None
        confident: bool — False means this needs manual review
        reason:   short string explaining why, for logging/replies
    """
    if amount is None or amount <= 0:
        return {"category": keyword_category, "count": None, "confident": False, "reason": "no_amount"}

    amount = round(amount)

    if keyword_category:
        base = config.SERVICE_PRICES.get(keyword_category)
        if base and amount % base == 0:
            return {
                "category": keyword_category, "count": amount // base,
                "confident": True, "reason": "keyword_confirmed_by_amount",
            }
        return {
            "category": keyword_category, "count": None,
            "confident": False, "reason": "amount_does_not_match_keyword_category",
        }

    # No keyword given — infer the tier purely from which base price(s) the
    # amount cleanly divides by. Civilian is unambiguous since it's the only
    # category at 3000; the 5000 tier covers ems/pd/gov/taxi, which amount
    # alone can't tell apart, so it comes back as a generic "gov" bucket.
    civ_multiple = amount % 3000 == 0
    gov_multiple = amount % 5000 == 0

    if civ_multiple and not gov_multiple:
        return {"category": "civilian", "count": amount // 3000, "confident": True, "reason": "amount_matches_civilian"}
    if gov_multiple and not civ_multiple:
        return {"category": "gov", "count": amount // 5000, "confident": True, "reason": "amount_matches_government_tier"}
    if civ_multiple and gov_multiple:
        # e.g. 15000 = civilian x5 OR government-tier x3 — genuinely ambiguous
        # without a keyword, needs a human to confirm.
        return {"category": None, "count": None, "confident": False, "reason": "ambiguous_amount_matches_both_tiers"}
    return {"category": None, "count": None, "confident": False, "reason": "amount_not_a_clean_multiple"}