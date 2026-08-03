import os
import re
import io
import hashlib
import logging
import subprocess
import requests
from PIL import Image, ImageEnhance

try:
    import pytesseract
    # Set tesseract path — Windows paths first, then Linux
    _tess_found = False
    for tess_path in [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        r"C:\Users\lohit\AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/nix/var/nix/profiles/default/bin/tesseract",
    ]:
        if os.path.exists(tess_path):
            pytesseract.pytesseract.tesseract_cmd = tess_path
            _tess_found = True
            break
    if not _tess_found:
        # Try finding via PATH
        try:
            result = subprocess.run(["which", "tesseract"], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                pytesseract.pytesseract.tesseract_cmd = result.stdout.strip()
                _tess_found = True
        except Exception:
            pass
except ImportError:
    pytesseract = None

logger = logging.getLogger("ocr")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.FileHandler("ocr_errors.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)


def _verify_tesseract():
    """Logs tesseract version on startup so we know if it's working."""
    if pytesseract is None:
        logger.error("[OCR] pytesseract NOT imported — install pytesseract")
        return
    try:
        ver = pytesseract.get_tesseract_version()
        logger.info(f"[OCR] Tesseract OK — version {ver} at {pytesseract.pytesseract.tesseract_cmd}")
    except Exception as e:
        logger.error(f"[OCR] Tesseract NOT working: {e} — cmd={pytesseract.pytesseract.tesseract_cmd!r}")

_verify_tesseract()



def compute_image_hash(image_bytes: bytes) -> str:
    """Computes SHA-256 hash of image bytes for deduplication."""
    return hashlib.sha256(image_bytes).hexdigest()


def preprocess_image(img: Image.Image) -> Image.Image:
    """Enhances image for Tesseract OCR — inverts dark UI backgrounds, boosts contrast, upscales small images."""
    try:
        # Upscale small images for better OCR accuracy
        w, h = img.size
        if w < 800 or h < 600:
            scale = max(800 / w, 600 / h, 2.0)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        gray = img.convert("L")
        # Check if image is dark-on-light or light-on-dark
        import statistics
        pixels = list(gray.getdata())
        avg = statistics.mean(pixels)
        if avg < 128:
            # Dark background (like FiveM tablet) — invert so text is dark on white
            from PIL import ImageOps
            gray = ImageOps.invert(gray)

        # Sharpen before contrast boost
        from PIL import ImageFilter
        gray = gray.filter(ImageFilter.SHARPEN)

        enhancer = ImageEnhance.Contrast(gray)
        enhanced = enhancer.enhance(3.0)
        return enhanced
    except Exception as e:
        logger.warning(f"Image preprocessing fallback: {e}")
        return img


def extract_numeric_amount(text: str) -> float:
    """Extracts exact numeric monetary amount from OCR text image output."""
    if not text:
        return None

    lines = text.splitlines()

    # 1. Lines containing total/amount keywords
    for line in lines:
        if any(k in line.lower() for k in ("total", "amount", "subtotal", "price", "pay", "cost", "amt", "grand total")):
            m = re.search(r"[\$₹§€£sS]?\s*([\d,]+(?:\.\d+)?)", line)
            if m:
                try:
                    val = float(m.group(1).replace(",", ""))
                    if 50 <= val <= 1000000:
                        return val
                except ValueError:
                    pass

    # 2. FiveM Tablet Invoice row pattern (relaxed — currency symbol optional)
    #    Matches: "8/2/2026 Suna Pana $480", "8/3/2026 Butty Paul 1500", "Unpaid 8/1/2026 541500"
    for line in lines:
        m_tab = re.search(
            r"\d{1,2}/\d{1,2}/\d{2,4}\s+.+?\s+[\$₹§€£sS]?\s*([\d,]{3,7}(?:\.\d+)?)",
            line.strip(), re.IGNORECASE
        )
        if m_tab:
            try:
                val = float(m_tab.group(1).replace(",", ""))
                if 50 <= val <= 1000000:
                    return val
            except ValueError:
                pass

    # 3. Any dollar/rupee sign followed by a number
    m_curr = re.search(r"[\$₹§€£sS]\s*([\d,]+(?:\.\d+)?)", text)
    if m_curr:
        try:
            val = float(m_curr.group(1).replace(",", ""))
            if 50 <= val <= 1000000:
                return val
        except ValueError:
            pass

    # 4. Standalone numbers between 50 and 1,000,000 anywhere in text
    matches = re.findall(r"\b([\d,]{3,7})\b", text)
    for m in matches:
        try:
            val = float(m.replace(",", ""))
            if 50 <= val <= 1000000:
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
    if any(k in clean.lower() for k in ("total", "amount", "price", "invoice", "date", "service", "upgrade", "kit", "status", "unpaid", "paid", "refresh", "create", "page", "show", "next", "previous", "home", "duty", "connect", "vehicle", "logout")):
        return False
    # Must contain at least one letter
    if not re.search(r"[A-Za-z]", clean):
        return False
    return True


def extract_recipient_name(text: str) -> str:
    """Extracts Recipient / Customer name directly from invoice image text (e.g. 'Tara Maaran', 'Suna Pana', 'SenthamizhanA', 'Mr Sivakumar', 'Butty Paul')."""
    if not text:
        return None

    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # 1. FiveM Tablet Row pattern (relaxed — status can be garbled OCR text)
    #    Matches: "(Gea) 8/2/2026 Suna Pana $480 i @®"
    #    or: "=) 8/1/2026 Mr Sivakumar $541,500 Hii"
    #    or: "(Unpaid) 8/3/2026 Butty Paul $1,500"
    for line in lines:
        m_row = re.search(
            r"\d{1,2}/\d{1,2}/\d{2,4}\s+([A-Za-z][A-Za-z0-9_\. ]{1,35}?)\s+[\$₹§€£sS]\s*[\d,]+",
            line,
            re.IGNORECASE
        )
        if m_row:
            candidate = m_row.group(1).strip()
            candidate = re.sub(r"^[^\w]+|[^\w\.]+$", "", candidate).strip()
            if _is_valid_name(candidate):
                return candidate

    # 2. Line with Name + Amount: "<Name> $<Amount>"
    for line in lines:
        m_name_amt = re.search(
            r"^([A-Za-z][A-Za-z0-9_\. ]{1,35})\s+[\$₹§€£sS]\s*[\d,]+",
            line,
            re.IGNORECASE
        )
        if m_name_amt:
            candidate = m_name_amt.group(1).strip()
            candidate = re.sub(r"^[^\w]+|[^\w\.]+$", "", candidate).strip()
            if _is_valid_name(candidate):
                return candidate

    # 3. Match date line followed immediately by name line
    for i, line in enumerate(lines):
        if re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", line):
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                m_next = re.search(r"^([A-Za-z][A-Za-z0-9_\. ]{1,35})", next_line)
                if m_next:
                    candidate = m_next.group(1).strip()
                    candidate = re.sub(r"^[^\w]+|[^\w\.]+$", "", candidate).strip()
                    if _is_valid_name(candidate):
                        return candidate

    # 4. Recipient / Customer label pattern (same line or next line)
    for i, line in enumerate(lines):
        m_lbl = re.search(r"(?:Recipient|Customer|Client|Billed To|Billed|To)\s*[:\-]?\s*([^\n\$₹§€£\d]{2,35})", line, re.IGNORECASE)
        if m_lbl:
            candidate = m_lbl.group(1).strip()
            candidate = re.sub(r"^[^\w]+|[^\w\.]+$", "", candidate).strip()
            if _is_valid_name(candidate):
                return candidate
        if any(lbl in line.lower() for lbl in ("recipient", "customer", "client", "billed to")):
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                m_next = re.search(r"([A-Za-z][A-Za-z0-9_\. ]{1,35})", next_line)
                if m_next:
                    candidate = m_next.group(1).strip()
                    candidate = re.sub(r"^[^\w]+|[^\w\.]+$", "", candidate).strip()
                    if _is_valid_name(candidate):
                        return candidate

    # 5. Title prefix pattern (Mr/Ms/Mrs/Dr)
    m_title = re.search(r"\b(Mr|Ms|Mrs|Dr)\.?\s+([A-Z][a-z0-9_]+(?:\s+[A-Z][a-z0-9_]+)?)", text)
    if m_title:
        candidate = f"{m_title.group(1)} {m_title.group(2)}".strip()
        if _is_valid_name(candidate):
            return candidate

    # 6. Look for any capitalized name-like words (excluding UI navigation keywords)
    for line in lines:
        if any(h in line.lower() for h in ("invoices", "refresh", "create", "previous", "home", "duty", "connect", "vehicle", "logout", "page", "show", "next")):
            continue
        m_cap = re.search(r"\b([A-Z][a-z]{1,15}(?:\s+[A-Z][a-z]{1,15}){1,3})\b", line)
        if m_cap:
            candidate = m_cap.group(1).strip()
            if _is_valid_name(candidate) and len(candidate) >= 3:
                return candidate

    return None


def ocr_space_fallback(image_url: str) -> str:
    """Fallback OCR using OCR.space free public API if local Tesseract is unavailable or returns empty text."""
    try:
        api_url = "https://api.ocr.space/parse/image"
        payload = {
            "url": image_url,
            "apikey": "helloworld",
            "language": "eng",
            "isOverlayRequired": False,
            "scale": True,
            "OCREngine": 2,
        }
        res = requests.post(api_url, data=payload, timeout=12)
        if res.status_code == 200:
            data = res.json()
            results = data.get("ParsedResults", [])
            if results:
                txt = results[0].get("ParsedText", "")
                if txt and len(txt.strip()) > 3:
                    logger.info(f"[OCR.SPACE SUCCESS] URL={image_url[-50:]} Extracted {len(txt)} chars")
                    return txt.strip()
    except Exception as e:
        logger.warning(f"OCR.space fallback failed: {e}")
    return ""


async def process_invoice_image(image_url: str, fields: list = None) -> tuple:
    """Downloads image, computes hash, executes multi-pass OCR text extraction, and parses amount & customer name."""
    if fields is None:
        fields = ["amount", "customer"]

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(image_url, headers=headers, timeout=15)
        resp.raise_for_status()
        img_bytes = resp.content
    except Exception as e:
        logger.error(f"Failed to download image from {image_url}: {e}")
        return None, {}, ""

    img_hash = compute_image_hash(img_bytes)
    raw_text = ""
    parsed = {"amount": None, "customer": None}

    # 1. Local Tesseract OCR Attempts
    if pytesseract is not None:
        try:
            img = Image.open(io.BytesIO(img_bytes))
            texts = []

            # Pass 1: Original Image
            try:
                t1 = pytesseract.image_to_string(img)
                if t1 and len(t1.strip()) > 5:
                    texts.append(t1.strip())
            except Exception as e1:
                logger.debug(f"OCR Pass 1 failed: {e1}")

            # Pass 2: Preprocessed Image
            try:
                proc_img = preprocess_image(img)
                t2 = pytesseract.image_to_string(proc_img)
                if t2 and len(t2.strip()) > 5:
                    texts.append(t2.strip())
            except Exception as e2:
                logger.debug(f"OCR Pass 2 failed: {e2}")

            # Pass 3: Preprocessed Image with PSM 6
            try:
                proc_img = preprocess_image(img)
                t3 = pytesseract.image_to_string(proc_img, config=r'--oem 3 --psm 6')
                if t3 and len(t3.strip()) > 5:
                    texts.append(t3.strip())
            except Exception as e3:
                logger.debug(f"OCR Pass 3 failed: {e3}")

            raw_text = "\n".join(texts)
        except Exception as e:
            logger.error(f"Tesseract OCR failed: {e}")

    # 2. If Tesseract returned empty text or is unavailable, use Cloud OCR API fallback
    if not raw_text or len(raw_text.strip()) < 5:
        logger.info(f"[OCR] Tesseract returned empty text for {image_url[-50:]}. Trying OCR.space cloud fallback...")
        raw_text = ocr_space_fallback(image_url)

    if raw_text:
        logger.info(f"[OCR RAW TOTAL] URL={image_url[-60:]}\n{raw_text[:300]}\n---")

    parsed["amount"] = extract_numeric_amount(raw_text)
    parsed["customer"] = extract_recipient_name(raw_text)

    return img_hash, parsed, raw_text
