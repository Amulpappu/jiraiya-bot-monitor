import io
import re
import json
import logging
import hashlib
import aiohttp
from PIL import Image, ImageOps, ImageFilter, ImageEnhance
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


def _get_image_variants(image_bytes: bytes):
    """
    Produces PIL image variants for Tesseract.
    FiveM invoice UIs are often dark-themed with light text, or vice versa.
    We return:
      1. Normal upscaled grayscale with autocontrast
      2. Inverted upscaled grayscale with autocontrast
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("L")  # grayscale

    w, h = img.size
    if w < 2000:
        scale = 2000 / w
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    img = img.filter(ImageFilter.SHARPEN)
    img_gray = ImageOps.autocontrast(img, cutoff=1)
    img_inv = ImageOps.invert(img_gray)

    return [img_gray, img_inv]


def extract_text(image_bytes: bytes) -> str:
    """
    Runs Tesseract on image variants across multiple PSMs (6, 4, 11, 3)
    and selects the text output with the highest confidence score.
    """
    variants = _get_image_variants(image_bytes)

    best_text = ""
    max_score = -1

    for img_variant in variants:
        for psm in (6, 4, 11, 3):
            try:
                text = pytesseract.image_to_string(
                    img_variant,
                    config=f"--psm {psm} --oem 1",
                )
                score = (
                    len(re.findall(r"[\$₹§€£]", text)) * 25
                    + len(re.findall(r"(?:Unpaid|Paid|Total|Recipient|Status|Invoice|Amount)", text, re.IGNORECASE)) * 20
                    + len(re.findall(r"\b\d{2,7}\b", text)) * 5
                    + len(re.findall(r"[A-Za-z]{3,}", text))
                )
                if score > max_score:
                    max_score = score
                    best_text = text
            except Exception as e:
                logger.warning(f"Tesseract PSM {psm} failed: {e}")

    return best_text


# ── Field parsers ────────────────────────────────────────

NAME_PATTERNS = [
    r"(?:customer|client|name|buyer|sold to|recipient|billed to|billed|target|patient|paid by|player|citizen|receiver|person|for|bill to|bill for|invoice to)\s*[:\-]?\s*([A-Za-z0-9 .'_\\-]{2,40})",
]

AMOUNT_PATTERNS = [
    r"(?:total amount|total price|grand total|total|amount due|amount|price|value)\s*[:\-]?\s*[\$sS₹§€£]?\s*([\d,]+\.\d{1,2}|[\d,]+)",
]

QUANTITY_PATTERNS = [
    r"(?:quantity|qty|units|amount|count)\s*[:\-]?\s*(\d{1,4})",
]

_NAME_EXCLUDE_WORDS_LOWER = {
    "invoices", "invoice", "status", "subtotal", "total", "amount", "price",
    "unpaid", "paid", "refresh", "create", "previous", "next", "page",
    "onduty", "offduty", "disconnect", "disconnected",
    "vehicle", "vehicles", "novehicleconnected",
    "category", "resend", "delete", "logout", "login",
    "firstname", "lastname", "unspecified",
}

# Name structure fallbacks
PASCAL_NAME_PATTERN = r"\b([A-Z][a-z0-9_]+[A-Z][a-z0-9_]+)\b"
TWO_WORD_NAME_PATTERN = r"\b([A-Z][a-z0-9_]+(?:\s+[A-Z][a-z0-9_]+)+)\b"
HANDLE_NAME_PATTERN = r"\b([a-zA-Z][a-zA-Z0-9_]{2,20})\b"


def _is_valid_name(candidate: str) -> bool:
    if not candidate:
        return False

    cand_clean = candidate.strip().lower()
    if cand_clean in _NAME_EXCLUDE_WORDS_LOWER or len(cand_clean) <= 1:
        return False

    words = cand_clean.split()
    if all(w in _NAME_EXCLUDE_WORDS_LOWER for w in words):
        return False

    return True


def _parse_table_row(text: str):
    """
    Parses FiveM table row format:
    e.g. 'Unpaid 7/12/2026 LeoLogesh $25,368'
    or 'Paid 7112026 amul_pappu 20,662'
    Returns (name, amount_str) if found.
    """
    for line in text.splitlines():
        line_clean = line.strip()
        # Look for Paid/Unpaid followed by date, name, and total amount
        m = re.search(
            r"(?:Paid|Unpaid)\s+[0-9/\.\-]+\s+([A-Za-z0-9_.\- ]+?)\s+[\$sS₹§€£]?\s*([\d,]{2,10}(?:\.\d{1,2})?)",
            line_clean,
            re.IGNORECASE,
        )
        if m:
            name_candidate = m.group(1).strip()
            amt_candidate = m.group(2).strip()
            if _is_valid_name(name_candidate):
                return name_candidate, amt_candidate
    return None, None


def _fallback_amount(text: str):
    # 1. Check for explicit currency symbols or OCR misread dollar prefixes ($ / s / S / ₹)
    for m in re.finditer(r"(?:^|\s|\b)[$₹§€£sS]\s*([\d,]{2,10}(?:\.\d{1,2})?)(?:\s|$|\b)", text):
        candidate = m.group(1).replace(",", "")
        try:
            val = float(candidate)
            if val > 0 and val not in (2025, 2026, 2027):
                return m.group(1)
        except ValueError:
            pass

    # 2. Label-based search
    val = _search_patterns(AMOUNT_PATTERNS, text)
    if val:
        return val

    # 3. Standalone positive numbers > 10 in lines with invoice keywords
    for line in text.splitlines():
        if any(w in line.lower() for w in ("total", "unpaid", "paid", "amount", "price")):
            for num in re.findall(r"\b([\d,]{2,7}(?:\.\d{1,2})?)\b", line):
                clean_num = num.replace(",", "")
                if clean_num not in ("2025", "2026", "2027"):
                    try:
                        if float(clean_num) > 0:
                            return num
                    except ValueError:
                        pass

    return None


def _fallback_name(text: str):
    # 1. PascalCase / CamelCase (e.g. LeoLogesh)
    for m in re.finditer(PASCAL_NAME_PATTERN, text):
        candidate = m.group(1).strip()
        if _is_valid_name(candidate):
            return candidate

    # 2. Two-word / Multi-word names (e.g. James Gordon, Anbu Selvan)
    for m in re.finditer(TWO_WORD_NAME_PATTERN, text):
        candidate = m.group(1).strip()
        if _is_valid_name(candidate):
            return candidate

    # 3. Single word handle (e.g. amul_pappu, jarad007)
    for m in re.finditer(HANDLE_NAME_PATTERN, text):
        candidate = m.group(1).strip()
        if _is_valid_name(candidate):
            return candidate

    return None


def _search_patterns(patterns, text):
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _clean_ocr_amount(amount_val: float | None, text: str) -> float | None:
    """
    Fixes Tesseract OCR dollar-sign misreads (e.g. '414800$' misread as '4148006').
    If a parsed amount ends in '6' and trimming the '6' results in a clean round number,
    corrects the amount to the true value.
    """
    if amount_val is None or amount_val <= 0:
        return amount_val

    amt_str = str(int(amount_val))
    if len(amt_str) > 3 and amt_str.endswith("6"):
        trimmed_str = amt_str[:-1]
        try:
            trimmed_val = float(trimmed_str)
            if trimmed_val % 10 == 0 or trimmed_val % 100 == 0:
                return trimmed_val
        except ValueError:
            pass

    return amount_val


def parse_invoice(text: str, fields: list) -> dict:
    """Extract requested fields from OCR text. Missing fields come back as None."""
    result = {}

    table_name, table_amount = _parse_table_row(text)

    if "customer" in fields:
        name = table_name
        if name and not _is_valid_name(name):
            name = None
        if not name:
            name = _search_patterns(NAME_PATTERNS, text)
            if name and not _is_valid_name(name):
                name = None
        if not name:
            name = _fallback_name(text)
            if name and not _is_valid_name(name):
                name = None
        result["customer"] = name.strip() if (name and _is_valid_name(name)) else None

    if "amount" in fields:
        amount_str = table_amount
        if not amount_str:
            amount_str = _fallback_amount(text)
        if not amount_str:
            amount_str = _search_patterns(AMOUNT_PATTERNS, text)

        if amount_str:
            amount_str = amount_str.replace(",", "")
            try:
                val = float(amount_str)
                if val > 0:
                    val = _clean_ocr_amount(val, text)
                result["amount"] = val if (val and val > 0) else None
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
    Downloads an image, hashes it (for dedupe), OCRs it with multi-variant
    preprocessing, and parses the requested fields.

    Returns (image_hash, parsed_fields_dict, raw_text).
    Raises on network/OCR failure — the caller should catch and log.
    """
    image_bytes = await download_image(url)
    image_hash = hash_image(image_bytes)
    raw_text = extract_text(image_bytes)
    parsed = parse_invoice(raw_text, fields)
    return image_hash, parsed, raw_text