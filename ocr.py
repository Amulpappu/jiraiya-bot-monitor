import os
import re
import io
import hashlib
import logging
import requests
from PIL import Image, ImageEnhance

try:
    import pytesseract
    for tess_path in [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        r"C:\Users\lohit\AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
    ]:
        if os.path.exists(tess_path):
            pytesseract.pytesseract.tesseract_cmd = tess_path
            break
except ImportError:
    pytesseract = None

logger = logging.getLogger("ocr")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.FileHandler("ocr_errors.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)


def compute_image_hash(image_bytes: bytes) -> str:
    """Computes SHA-256 hash of image bytes for deduplication."""
    return hashlib.sha256(image_bytes).hexdigest()


def preprocess_image(img: Image.Image) -> Image.Image:
    """Enhances image contrast and converts to grayscale for optimal Tesseract OCR accuracy."""
    try:
        gray = img.convert("L")
        enhancer = ImageEnhance.Contrast(gray)
        enhanced = enhancer.enhance(2.0)
        return enhanced
    except Exception as e:
        logger.warning(f"Image preprocessing fallback: {e}")
        return img


def extract_numeric_amount(text: str) -> float:
    """Extracts exact numeric monetary amount from OCR text image output."""
    if not text:
        return None

    lines = text.splitlines()
    for line in lines:
        if any(k in line.lower() for k in ("total", "amount", "subtotal", "price", "pay", "cost", "amt", "grand total")):
            m = re.search(r"[\$₹§€£sS]?\s*([\d,]+(?:\.\d+)?)", line)
            if m:
                try:
                    val = float(m.group(1).replace(",", ""))
                    if 100 <= val <= 1000000:
                        return val
                except ValueError:
                    pass

    # FiveM Tablet Invoice pattern: "Unpaid 8/1/2026 Mr Sivakumar $541,500"
    for line in lines:
        m_tab = re.search(r"^(?:Unpaid|Paid)\s+\S+\s+.+?\s+[\$₹§€£sS]?\s*([\d,]+(?:\.\d+)?)$", line.strip(), re.IGNORECASE)
        if m_tab:
            try:
                val = float(m_tab.group(1).replace(",", ""))
                if 100 <= val <= 1000000:
                    return val
            except ValueError:
                pass

    m_curr = re.search(r"[\$₹§€£]\s*([\d,]+(?:\.\d+)?)", text)
    if m_curr:
        try:
            val = float(m_curr.group(1).replace(",", ""))
            if 100 <= val <= 1000000:
                return val
        except ValueError:
            pass

    matches = re.findall(r"\b([\d,]{4,7})\b", text)
    for m in matches:
        try:
            val = float(m.replace(",", ""))
            if 100 <= val <= 1000000:
                return val
        except ValueError:
            continue

    return None


def _is_valid_name(name: str) -> bool:
    """Validates extracted customer/person name."""
    if not name:
        return False
    clean = name.strip()
    if len(clean) < 2 or len(clean) > 40:
        return False
    if any(k in clean.lower() for k in ("total", "amount", "price", "invoice", "date", "service", "upgrade", "kit", "status", "unpaid", "paid", "refresh", "create")):
        return False
    return True


def extract_recipient_name(text: str) -> str:
    """Extracts Recipient / Customer name directly from invoice image text (e.g. 'Mr Sivakumar')."""
    if not text:
        return None

    # FiveM Tablet Invoice pattern: "Unpaid 8/1/2026 Mr Sivakumar $541,500"
    lines = text.splitlines()
    for line in lines:
        line_clean = line.strip()
        m_tab = re.search(r"^(?:Unpaid|Paid)\s+\S+\s+(.+?)\s+[\$₹§€£sS]?\s*[\d,]+(?:\.\d+)?$", line_clean, re.IGNORECASE)
        if m_tab:
            candidate = m_tab.group(1).strip()
            if _is_valid_name(candidate):
                return candidate

    # Recipient / Billed To pattern
    m_rec = re.search(r"(?:Recipient|Customer|Client|Name|Billed To|Billed|To)\s*[:\-]?\s*([^\n\$₹§€£\d]{2,35})", text, re.IGNORECASE)
    if m_rec:
        candidate = m_rec.group(1).strip()
        if _is_valid_name(candidate):
            return candidate

    # Title prefix pattern (Mr/Ms/Mrs/Dr)
    m_title = re.search(r"\b(Mr|Ms|Mrs|Dr)\.?\s+([A-Z][a-z0-9_]+(?:\s+[A-Z][a-z0-9_]+)?)", text)
    if m_title:
        candidate = f"{m_title.group(1)} {m_title.group(2)}".strip()
        if _is_valid_name(candidate):
            return candidate

    return None


async def process_invoice_image(image_url: str, fields: list = None) -> tuple:
    """Downloads image, computes hash, executes OCR text extraction, and parses amount & customer name."""
    if fields is None:
        fields = ["amount", "customer"]

    try:
        resp = requests.get(image_url, timeout=10)
        resp.raise_for_status()
        img_bytes = resp.content
    except Exception as e:
        logger.error(f"Failed to download image from {image_url}: {e}")
        return None, {}, ""

    img_hash = compute_image_hash(img_bytes)
    raw_text = ""
    parsed = {"amount": None, "customer": None}

    if pytesseract is None:
        logger.warning("Pytesseract not installed/available. Skipping OCR text extraction.")
        return img_hash, parsed, ""

    try:
        img = Image.open(io.BytesIO(img_bytes))
        proc_img = preprocess_image(img)
        raw_text = pytesseract.image_to_string(proc_img)
    except Exception as e:
        logger.error(f"Tesseract OCR failed for image: {e}")
        return img_hash, parsed, ""

    parsed["amount"] = extract_numeric_amount(raw_text)
    parsed["customer"] = extract_recipient_name(raw_text)

    return img_hash, parsed, raw_text
