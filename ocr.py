import io
import re
import logging
import hashlib
import aiohttp
from PIL import Image, ImageOps
import pytesseract

import config

if config.TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD

logging.basicConfig(
    filename=config.ERROR_LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ocr")


async def download_image(url: str) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Failed to download image: HTTP {resp.status}")
            return await resp.read()


def hash_image(image_bytes: bytes) -> str:
    """Used to detect duplicate invoice screenshots."""
    return hashlib.sha256(image_bytes).hexdigest()


def extract_text(image_bytes: bytes) -> str:
    image = Image.open(io.BytesIO(image_bytes)).convert("L")  # grayscale helps OCR accuracy
    image = ImageOps.autocontrast(image)
    # Upscale small screenshots — Tesseract reads small UI text much better at 2x size.
    width, height = image.size
    if width < 1200:
        scale = 1200 / width
        image = image.resize((int(width * scale), int(height * scale)), Image.LANCZOS)
    # --psm 6 = "assume a uniform block of text", which works well for both
    # plain receipts and table-style invoice UIs (rows/columns).
    text = pytesseract.image_to_string(image, config="--psm 6")
    return text


# ── Field parsers ────────────────────────────────────────
# These are intentionally loose so they match common FiveM invoice/receipt
# screenshot formats. Add more patterns here if your server's invoice
# template uses different wording.

NAME_PATTERNS = [
    r"(?:customer|client|name|buyer|sold to|recipient)\s*[:\-]?\s*([A-Za-z .'\-]{2,40})",
]

AMOUNT_PATTERNS = [
    r"(?:total amount|total price|grand total|total|amount due|amount|price|pay|paid)\s*[:\-]?\s*[₹$Rs\.]*\s*([\d,]+\.\d{1,2}|[\d,]+)",
]

QUANTITY_PATTERNS = [
    r"(?:quantity|qty|units|amount|count)\s*[:\-]?\s*(\d{1,4})",
]

# ── Fallback patterns for table-style invoice UIs ───────
# Used if label-based patterns find nothing. Supports $, ₹, Rs., INR, or numbers.
FALLBACK_AMOUNT_PATTERNS = [
    r"[₹$]\s*([\d,]+\.\d{1,2}|[\d,]+)",
    r"(?:Rs\.?|INR)\s*([\d,]+\.\d{1,2}|[\d,]+)",
    r"\b([\d,]{4,7})\b",  # Standalone 4 to 7 digit numbers (e.g. 3000, 15000)
]

# Words that commonly appear in FiveM invoice UI chrome and should NOT be
# mistaken for a customer's name when using the fallback name pattern.
_NAME_EXCLUDE_WORDS = {
    "Invoices", "Status", "Date", "Recipient", "Total", "Unpaid", "Paid",
    "Refresh", "Create", "Previous", "Next", "Page", "Show", "Home",
    "On Duty", "Disconnect", "Vehicle", "Logout", "Connected",
    "No", "Off", "Duty", "Connect", "Resend", "Delete",
    "Novehicle", "Novehicleconnected",
}

FALLBACK_NAME_PATTERN = r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)\b"
FALLBACK_SINGLE_WORD_NAME_PATTERN = r"\b([A-Z][a-z]{2,20})\b"


def _fallback_amount(text):
    for pattern in FALLBACK_AMOUNT_PATTERNS:
        match = re.search(pattern, text)
        if match:
            # Get the first non-None capturing group
            val = next((g for g in match.groups() if g is not None), None)
            if val:
                return val
    return None


def _fallback_name(text):
    for match in re.finditer(FALLBACK_NAME_PATTERN, text):
        candidate = match.group(1).strip()
        words = candidate.split()
        if any(word in _NAME_EXCLUDE_WORDS for word in words):
            continue
        return candidate

    # No two-word name found — try a single capitalized word instead
    # (e.g. a first-name-only recipient like "Krish").
    for match in re.finditer(FALLBACK_SINGLE_WORD_NAME_PATTERN, text):
        candidate = match.group(1).strip()
        if candidate not in _NAME_EXCLUDE_WORDS:
            return candidate
    return None


def _search_patterns(patterns, text):
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _is_valid_name(candidate: str) -> bool:
    """Rejects invoice UI header words (Total, Status, Date, etc.) that can
    get mistakenly captured as a customer name when columns sit next to
    each other in the OCR text."""
    words = candidate.split()
    return not any(word in _NAME_EXCLUDE_WORDS for word in words)


def parse_invoice(text: str, fields: list) -> dict:
    """Extract requested fields from OCR text. Missing fields come back as None."""
    result = {}

    if "customer" in fields:
        name = _search_patterns(NAME_PATTERNS, text)
        if name and not _is_valid_name(name):
            name = None
        if not name:
            name = _fallback_name(text)
        result["customer"] = name.strip() if name else None

    if "amount" in fields:
        # A literal "$" amount is a much more reliable signal than a nearby
        # label word (table screenshots can have a header word like "Total"
        # sitting right next to an unrelated number). Try that first.
        amount_str = _fallback_amount(text)
        if not amount_str:
            amount_str = _search_patterns(AMOUNT_PATTERNS, text)
        if amount_str:
            amount_str = amount_str.replace(",", "")
            try:
                result["amount"] = float(amount_str)
            except ValueError:
                result["amount"] = None
        else:
            result["amount"] = None

    if "quantity" in fields:
        qty_str = _search_patterns(QUANTITY_PATTERNS, text)
        result["quantity"] = int(qty_str) if qty_str else None

    return result


async def process_invoice_image(url: str, fields: list):
    """
    Downloads an image, hashes it (for dedupe), OCRs it, and parses the
    requested fields. Returns (image_hash, parsed_fields_dict, raw_text).
    Raises on network/OCR failure — the caller should catch and log.
    """
    image_bytes = await download_image(url)
    image_hash = hash_image(image_bytes)
    raw_text = extract_text(image_bytes)
    parsed = parse_invoice(raw_text, fields)
    return image_hash, parsed, raw_text