import sys
import asyncio
import re

# Force UTF-8 stdout/stderr encoding for Windows console compatibility
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import json
import os
import discord
from discord.ext import commands

import config
import ocr
from ocr import _is_valid_name
import sheets
import kit_pricing
import service_pricing

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ── Duplicate-image tracking (local JSON file) ──────────
def load_processed_hashes():
    if os.path.exists(config.PROCESSED_HASHES_FILE):
        with open(config.PROCESSED_HASHES_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_processed_hashes(hashes):
    with open(config.PROCESSED_HASHES_FILE, "w") as f:
        json.dump(list(hashes), f)


processed_hashes = load_processed_hashes()

# Maps a channel's cfg["sheet_name"] to the matching in-game Transactions
# dropdown category, for the generic (non-kit, non-service) OCR path.
GENERIC_SHEET_TO_TRANSACTION_CATEGORY = {
    "Upgrades": "Car UpGrade",
}


def resolve_employee_name(author: discord.User | discord.Member) -> str:
    """
    Looks up a Discord author in config.EMPLOYEE_MAPPING.
    Checks author.name, author.global_name, author.display_name, and str(author).
    Returns configured Employee Name (e.g. 'Sandy', 'Amul') if found.
    Falls back to author.display_name or author.name.
    """
    mapping = {k.strip().lstrip("@").lower(): v for k, v in config.EMPLOYEE_MAPPING.items()}

    candidates = [
        getattr(author, "name", ""),
        getattr(author, "global_name", "") or "",
        getattr(author, "display_name", ""),
        str(author),
    ]

    for cand in candidates:
        if not cand:
            continue
        cleaned = cand.strip().lstrip("@").lower()
        if cleaned in mapping:
            return mapping[cleaned]
        base = cleaned.split("#")[0]
        if base in mapping:
            return mapping[base]

    return getattr(author, "display_name", str(author))


def get_message_jump_url(message: discord.Message) -> str:
    guild_id = message.guild.id if getattr(message, "guild", None) else "@me"
    return f"https://discord.com/channels/{guild_id}/{message.channel.id}/{message.id}"


def log_discord_error(message: discord.Message, error_desc: str):
    link = get_message_jump_url(message)
    ch_name = getattr(message.channel, "name", "channel")
    author_name = getattr(message.author, "name", "user")
    full_msg = f"[Error] ❌ {error_desc} in #{ch_name} (by @{author_name}) | Jump: {link}"
    ocr.logger.error(full_msg)
    try:
        import monitor_app
        monitor_app.append_log(full_msg)
    except Exception:
        pass


def resolve_customer_name(parsed_cust: str, message: discord.Message, raw_text: str = "") -> str:
    """Extracts customer name from OCR, message text caption, or raw text.
    If none found, returns 'VIP Client' instead of 'Unknown'."""
    if parsed_cust and _is_valid_name(parsed_cust):
        return parsed_cust.strip()

    patterns = [
        r"(?:customer|client|name|buyer|sold to|recipient|billed to|billed|target|patient|paid by|player|citizen|receiver|person|for|bill to|bill for|invoice to)\s*[:\-]?\s*([A-Za-z0-9 .'_\\-]{2,40})",
    ]

    if message and message.content:
        for p in patterns:
            m = re.search(p, message.content, re.IGNORECASE)
            if m and _is_valid_name(m.group(1)):
                return m.group(1).strip()
        # Fallback to non-numeric first line of message content if provided
        lines = [l.strip() for l in message.content.splitlines() if l.strip()]
        for line in lines:
            if not re.search(r"^\$?[\d,]+k?$", line, re.IGNORECASE) and _is_valid_name(line):
                return line

    if raw_text:
        for p in patterns:
            m = re.search(p, raw_text, re.IGNORECASE)
            if m and _is_valid_name(m.group(1)):
                return m.group(1).strip()

    return "VIP Client"


def extract_image_urls(message: discord.Message) -> list[str]:
    """Extracts all image URLs from attachments, embeds, and message content URLs."""
    urls = []
    if not message:
        return urls
    # 1. Attachments
    for a in getattr(message, "attachments", []):
        is_img = (a.content_type and "image" in a.content_type) or (
            a.filename and a.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"))
        )
        if is_img and getattr(a, "url", None):
            urls.append(a.url)

    # 2. Embeds
    for e in getattr(message, "embeds", []):
        if getattr(e, "image", None) and getattr(e.image, "url", None):
            urls.append(e.image.url)
        elif getattr(e, "thumbnail", None) and getattr(e.thumbnail, "url", None):
            urls.append(e.thumbnail.url)

    # 3. Direct image links in message text content
    if getattr(message, "content", None):
        for m in re.finditer(r"(https?://\S+\.(?:png|jpg|jpeg|webp|bmp))", message.content, re.IGNORECASE):
            u = m.group(1)
            if u not in urls:
                urls.append(u)

    return urls


async def add_reaction_if_enabled(message: discord.Message, emoji: str):
    """Adds an emoji reaction to a message only if ENABLE_DISCORD_REACTIONS is True in config.py."""
    if getattr(config, "ENABLE_DISCORD_REACTIONS", False):
        try:
            await message.add_reaction(emoji)
        except Exception:
            pass


async def process_service_message(message: discord.Message, is_backfill: bool = False):
    """
    For the services channel: category and how many services were billed
    together are worked out from the invoice's OWN amount.
    """
    if is_backfill:
        if str(message.id) in sheets.get_all_logged_message_ids():
            return

    img_urls = extract_image_urls(message)
    image_url = img_urls[0] if img_urls else None

    image_hash = None
    parsed = {}
    raw_text = ""

    if image_url:
        try:
            image_hash, parsed, raw_text = await ocr.process_invoice_image(
                image_url, ["customer", "amount"]
            )
        except Exception as e:
            ocr.logger.error(f"OCR failed for service message {message.id}: {e}")

    if config.IGNORE_DUPLICATE_IMAGES and image_hash and image_hash in processed_hashes:
        if str(message.id) in sheets.get_all_logged_message_ids():
            await add_reaction_if_enabled(message, "🔁")
            return

    amount = parsed.get("amount")
    if (amount is None or amount <= 0) and message.content:
        amount = parse_text_amount(message.content)

    if amount is None or amount <= 0:
        # Fallback to standard civilian service (₹3,000) so no invoice screenshot is dropped
        amount = 3000.0
        ocr.logger.warning(f"Service message {message.id}: OCR could not read amount, using fallback ₹3,000")

    keyword_category = service_pricing.parse_service_category(message.content)
    if not keyword_category and raw_text:
        keyword_category = service_pricing.parse_service_category(raw_text)

    result = service_pricing.resolve_category_and_count(amount, keyword_category)
    service_cat = result.get("category") or ("government" if "pd" in (message.content or "").lower() or "ems" in (message.content or "").lower() else "civilian")
    service_cnt = result.get("count") or max(1, int(round(amount / 3000.0)))

    try:
        await asyncio.to_thread(
            sheets.append_service_entry,
            category=service_cat,
            total=amount,
            employee=resolve_employee_name(message.author),
            message_id=str(message.id),
            count=service_cnt,
            created_at=message.created_at,
        )
    except Exception as e:
        ocr.logger.error(f"Failed to write service entry for message {message.id}: {e}")
        return

    if image_hash:
        processed_hashes.add(image_hash)
        save_processed_hashes(processed_hashes)

    txn_category = "Service-Government" if service_cat == "government" else "Service-Civilian"
    txn_desc = f"{service_cnt}x"
    try:
        await asyncio.to_thread(
            sheets.append_transaction_entry,
            amount,
            resolve_employee_name(message.author),
            txn_category,
            description=txn_desc,
            created_at=message.created_at,
            skip_tracker_update=is_backfill,
        )
    except Exception as e:
        ocr.logger.error(f"Failed to write Transactions entry for message {message.id}: {e}")

    await add_reaction_if_enabled(message, "✅")
    return

    # ── Not confident — flag for manual review, but still logged so nothing gets lost ──
    await add_reaction_if_enabled(message, "❓")
    if is_backfill:
        return

    reason = result["reason"]
    if reason == "no_amount":
        note = "couldn't read an amount off the invoice."
    elif reason == "amount_does_not_match_keyword_category":
        base = service_pricing.price_for(keyword_category)
        note = (
            f"you wrote '{keyword_category}' but ₹{amount:,.0f} isn't a clean multiple "
            f"of ₹{base:,.0f} — please double check the invoice or the category."
        )
    elif reason == "ambiguous_amount_matches_both_tiers":
        note = (
            f"₹{amount:,.0f} matches both civilian and government-tier multiples — "
            f"please reply with 'civilian' or 'government/ems/pd/taxi' to clarify."
        )
    else:  # amount_not_a_clean_multiple
        note = f"₹{amount:,.0f} isn't a clean multiple of ₹3,000 or ₹5,000 — please double check the invoice."


async def process_kit_message(message: discord.Message, cfg: dict, is_backfill: bool = False):
    """
    For kit channels: reads RK/CK quantities from message text, OCR image text,
    or estimates from total amount if missing. Ignores messages before 2026.
    """
    if is_backfill:
        if str(message.id) in sheets.get_all_logged_message_ids():
            return

    img_urls = extract_image_urls(message)
    image_url = img_urls[0] if img_urls else None

    image_hash, parsed, raw_text = None, {"customer": None, "amount": None}, ""
    if image_url:
        try:
            image_hash, parsed, raw_text = await ocr.process_invoice_image(
                image_url, ["customer", "amount"]
            )
        except Exception as e:
            ocr.logger.error(f"OCR failed for kit message {message.id}: {e}")

    if config.IGNORE_DUPLICATE_IMAGES and image_hash and image_hash in processed_hashes:
        if str(message.id) in sheets.get_all_logged_message_ids():
            await add_reaction_if_enabled(message, "🔁")
            return

    qty = kit_pricing.parse_kit_quantities(message.content)
    if qty is None and raw_text:
        qty = kit_pricing.parse_kit_quantities(raw_text)

    if qty is None:
        amt = parsed.get("amount")
        if amt and amt > 0:
            est_qty = max(1, int(round(amt / 1000.0)))
            qty = {"rk": est_qty, "ck": 0}
        else:
            # Fallback to standard 1x Repair Kit so no kit invoice screenshot is dropped
            qty = {"rk": 1, "ck": 0}
            ocr.logger.warning(f"Kit message {message.id}: could not parse kit quantity, using fallback 1x RK")

    total, discount, combined_qty, rk_subtotal, ck_subtotal = kit_pricing.calculate_kit_total(
        qty["rk"], qty["ck"]
    )
    if (total <= 0 or (qty["rk"] == 0 and qty["ck"] == 0)) and parsed.get("amount"):
        total = parsed.get("amount")
        rk_subtotal = total

    try:
        await asyncio.to_thread(
            sheets.append_kit_entry,
            rk_qty=qty["rk"],
            ck_qty=qty["ck"],
            discount_pct=discount,
            total=total,
            employee=resolve_employee_name(message.author),
            message_id=str(message.id),
            created_at=message.created_at,
        )
    except Exception as e:
        ocr.logger.error(f"Failed to write kit entry for message {message.id}: {e}")
        return

    if image_hash:
        processed_hashes.add(image_hash)
        save_processed_hashes(processed_hashes)

    # Log to the consolidated Transactions ledger as separate line items
    try:
        emp_name = resolve_employee_name(message.author)
        if qty["rk"] > 0 and rk_subtotal > 0:
            await asyncio.to_thread(sheets.append_transaction_entry, rk_subtotal, emp_name, "Repair Kit", created_at=message.created_at, skip_tracker_update=is_backfill)
        if qty["ck"] > 0 and ck_subtotal > 0:
            await asyncio.to_thread(sheets.append_transaction_entry, ck_subtotal, emp_name, "Cleaning Kit", created_at=message.created_at, skip_tracker_update=is_backfill)
        elif rk_subtotal == 0 and ck_subtotal == 0 and total > 0:
            await asyncio.to_thread(sheets.append_transaction_entry, total, emp_name, "Repair Kit", created_at=message.created_at, skip_tracker_update=is_backfill)
    except Exception as e:
        ocr.logger.error(f"Failed to write Transactions entries for message {message.id}: {e}")

    await add_reaction_if_enabled(message, "✅")


def parse_text_amount(text: str) -> float | None:
    """Parses numeric amount from text content (e.g. '$15,000', '15k', '50000', 'bill 12500')."""
    if not text:
        return None

    MAX_EXPENSE_AMOUNT = 5000000.0

    # 1. 15k / $15k / 15.5k
    m_k = re.search(r"[\$₹§€£]?\s*(\d+(?:\.\d+)?)\s*k\b", text, re.IGNORECASE)
    if m_k:
        try:
            val = float(m_k.group(1)) * 1000.0
            if 100 <= val <= MAX_EXPENSE_AMOUNT:
                return val
        except ValueError:
            pass

    # 2. Currency symbol prefix ($15000 / ₹15,000 / $ 15000)
    m_curr = re.search(r"[\$₹§€£]\s*([\d,]+(?:\.\d{1,2})?)", text)
    if m_curr:
        try:
            val = float(m_curr.group(1).replace(",", ""))
            if 100 <= val <= MAX_EXPENSE_AMOUNT:
                return val
        except ValueError:
            pass

    # 3. Explicit keywords (total 15000, amount 15000, price 15000)
    m_kw = re.search(r"(?:total|amount|price|value|cost|fee|bill)\s*[:\-]?\s*[\$₹§€£]?\s*([\d,]+(?:\.\d{1,2})?)", text, re.IGNORECASE)
    if m_kw:
        try:
            val = float(m_kw.group(1).replace(",", ""))
            if 100 <= val <= MAX_EXPENSE_AMOUNT and val not in (2025, 2026, 2027, 2028):
                return val
        except ValueError:
            pass

    # 4. Standalone numbers >= 100 (excluding dates/timestamps)
    for line in text.splitlines():
        line_lower = line.lower()
        if any(w in line_lower for w in ("id:", "phone", "date", "time", "http", "www")):
            continue
        clean_line = re.sub(r"\d{2,4}[\/\.\-]\d{2}[\/\.\-]\d{2,4}", "", line)
        clean_line = re.sub(r"\d{1,2}:\d{2}(?::\d{2})?", "", clean_line)
        for num in re.findall(r"\b([\d,]{3,9}(?:\.\d{1,2})?)\b", clean_line):
            clean_num = num.replace(",", "")
            if clean_num not in ("2025", "2026", "2027", "2028"):
                try:
                    val = float(clean_num)
                    if 100 <= val <= MAX_EXPENSE_AMOUNT:
                        return val
                except ValueError:
                    pass

    return None


async def process_expense_message(message: discord.Message, cfg: dict, is_backfill: bool = False):
    """
    For the bill_claim channel: reads the total expense amount off the order/supply bill.
    Logs to the Expenses sheet and the consolidated Transactions ledger (category='Order').
    """
    if is_backfill:
        if str(message.id) in sheets.get_all_logged_message_ids():
            return

    img_urls = extract_image_urls(message)
    image_url = img_urls[0] if img_urls else None

    amount = None
    image_hash = None

    if image_url:
        try:
            image_hash, parsed, raw_text = await ocr.process_invoice_image(
                image_url, ["amount"]
            )
            amount = parsed.get("amount")
            if (amount is None or amount <= 0) and raw_text:
                amount = parse_text_amount(raw_text)
        except Exception as e:
            ocr.logger.error(f"OCR failed for expense/bill message {message.id}: {e}")

    # Fallback to message text content if amount is missing or no image attachment
    if (amount is None or amount <= 0) and message.content:
        amount = parse_text_amount(message.content)

    if amount is None or amount <= 0:
        # Fallback default expense bill (₹5,000) so no bill claim is dropped
        amount = 5000.0
        ocr.logger.warning(f"Expense message {message.id}: OCR could not read amount, using fallback ₹5,000")

    if config.IGNORE_DUPLICATE_IMAGES and image_hash and image_hash in processed_hashes:
        if str(message.id) in sheets.get_all_logged_message_ids():
            await add_reaction_if_enabled(message, "🔁")
            return

    emp_name = resolve_employee_name(message.author)

    try:
        await asyncio.to_thread(
            sheets.append_expense_entry,
            amount=amount,
            employee=emp_name,
            message_id=str(message.id),
            created_at=message.created_at,
        )
    except Exception as e:
        ocr.logger.error(f"Failed to write expense entry for message {message.id}: {e}")
        return

    if image_hash:
        processed_hashes.add(image_hash)
        save_processed_hashes(processed_hashes)

    await add_reaction_if_enabled(message, "✅")


def normalize_vip_category(raw_cat: str) -> str:
    """Normalizes raw category text to standard dropdown values: VIP, Friends, Twin, Community, Special."""
    if not raw_cat:
        return "VIP"
    raw_lower = raw_cat.strip().lower()
    if "vip" in raw_lower:
        return "VIP"
    if "friend" in raw_lower:
        return "Friends"
    if "twin" in raw_lower:
        return "Twin"
    if "comm" in raw_lower:
        return "Community"
    if "spec" in raw_lower:
        return "Special"
    return "VIP"


async def process_vip_claim_message(message: discord.Message, cfg: dict, is_backfill: bool = False):
    """
    For the vip-claim-logs channel: parses claim details from text or OCR images.
    Logs ONLY to the VIP Claim sheet tab (never added to gross sales ledger).
    """
    if is_backfill:
        if str(message.id) in sheets.get_all_logged_message_ids():
            return

    text = message.content or ""
    img_urls = extract_image_urls(message)
    image_url = img_urls[0] if img_urls else None

    raw_text = ""
    parsed = {}
    if image_url:
        try:
            image_hash, parsed, raw_text = await ocr.process_invoice_image(
                image_url, ["customer", "amount"]
            )
        except Exception as e:
            ocr.logger.error(f"OCR failed for VIP claim message {message.id}: {e}")

    full_text = f"{text}\n{raw_text}".strip()

    # Parse Person Name
    m_person = re.search(r"(?:Person\s*Name|Customer|Client|Name|Target|Billed\s*To|Paid\s*By)\s*[:\-]\s*(.+)", full_text, re.IGNORECASE)
    if m_person and _is_valid_name(m_person.group(1)):
        person_name = m_person.group(1).strip()
    elif parsed.get("customer") and _is_valid_name(parsed.get("customer")):
        person_name = parsed["customer"].strip()
    else:
        person_name = resolve_customer_name(parsed.get("customer"), message, raw_text)

    # Parse Vehicle Category
    m_cat = re.search(r"(?:Vehicle\s*)?Category\s*[:\-]\s*(.+)", full_text, re.IGNORECASE)
    category_raw = m_cat.group(1).strip() if m_cat else "VIP"
    category = normalize_vip_category(category_raw)

    # Parse Vehicle Name
    m_veh = re.search(r"Vehicle(?:\s*Name)?\s*[:\-]\s*(.+)", full_text, re.IGNORECASE)
    vehicle_name = m_veh.group(1).strip() if m_veh else "Unknown"

    # Parse Staff Name
    m_staff = re.search(r"Staff(?:\s*Name)?\s*[:\-]\s*(.+)", full_text, re.IGNORECASE)
    if m_staff and m_staff.group(1).strip():
        staff_name = resolve_employee_name(m_staff.group(1).strip())
    else:
        staff_name = resolve_employee_name(message.author)

    # Parse Amount
    amount = parsed.get("amount")
    if amount is None or amount <= 0:
        m_amt = re.search(r"Amount\s*[:\-]\s*[\$₹§€£]?\s*([\d,]+(?:\.\d+)?)", full_text, re.IGNORECASE)
        if m_amt:
            try:
                amount = float(m_amt.group(1).replace(",", ""))
            except ValueError:
                amount = parse_text_amount(full_text) or 0.0
        else:
            amount = parse_text_amount(full_text) or 0.0

    try:
        await asyncio.to_thread(
            sheets.append_vip_claim_entry,
            person_name=person_name,
            category=category,
            vehicle=vehicle_name,
            staff=staff_name,
            amount=amount,
            message_id=str(message.id),
            created_at=message.created_at,
        )
    except Exception as e:
        ocr.logger.error(f"Failed to write VIP Claim entry for message {message.id}: {e}")
        return

    await add_reaction_if_enabled(message, "✅")


async def process_invoice_message(message: discord.Message, channel_name: str, is_backfill: bool = False):
    """Runs OCR + sheet logging for one message's image attachments or text.
    Shared by on_message (live) and the startup history scan (backfill)."""
    cfg, _key = config.get_channel_config(channel_name)
    if not cfg:
        return

    if cfg.get("vip_claim_channel"):
        await process_vip_claim_message(message, cfg, is_backfill)
        return

    if cfg.get("kit_channel"):
        await process_kit_message(message, cfg, is_backfill)
        return

    if cfg.get("category_channel"):
        await process_service_message(message, is_backfill)
        return

    if cfg.get("expense_channel"):
        await process_expense_message(message, cfg, is_backfill)
        return

    img_urls = extract_image_urls(message)
    if not img_urls and message.content:
        # Fallback for text-based upgrade invoice messages
        if is_backfill and str(message.id) in sheets.get_all_logged_message_ids():
            return
        val = parse_text_amount(message.content)
        if val and val > 0:
            cust = resolve_customer_name(None, message)
            try:
                await asyncio.to_thread(
                    sheets.append_entry,
                    sheet_name=cfg["sheet_name"],
                    value=val,
                    employee=resolve_employee_name(message.author),
                    message_id=str(message.id),
                    created_at=message.created_at,
                )
                txn_category = GENERIC_SHEET_TO_TRANSACTION_CATEGORY.get(cfg["sheet_name"], "Upgrades")
                await asyncio.to_thread(
                    sheets.append_transaction_entry,
                    val,
                    resolve_employee_name(message.author),
                    txn_category,
                    description="1x UpGrade",
                    created_at=message.created_at,
                    skip_tracker_update=is_backfill,
                )
                await add_reaction_if_enabled(message, "✅")
            except Exception as e:
                ocr.logger.error(f"Failed to write text upgrade entry for {message.id}: {e}")
        return

    for img_url in img_urls:
        if is_backfill and str(message.id) in sheets.get_all_logged_message_ids():
            continue

        try:
            image_hash, parsed, raw_text = await ocr.process_invoice_image(
                img_url, cfg["fields"]
            )
        except Exception as e:
            ocr.logger.error(f"OCR failed for upgrade message {message.id}: {e}")
            continue

        # ── Duplicate check ──
        if config.IGNORE_DUPLICATE_IMAGES and image_hash in processed_hashes:
            if str(message.id) in sheets.get_all_logged_message_ids():
                await add_reaction_if_enabled(message, "🔁")
                continue

        # ── Validate parsed fields ──
        customer = parsed.get("customer")

        if "quantity" in cfg["fields"]:
            value = parsed.get("quantity")
            if value is None:
                value = parsed.get("amount")
        else:
            value = parsed.get("amount")

        # Fallback 1: Parse amount from message text content (e.g. caption in Discord)
        if (value is None or value <= 0) and message.content:
            value = parse_text_amount(message.content)

        # Fallback 2: Parse amount from raw OCR text
        if (value is None or value <= 0) and raw_text:
            value = parse_text_amount(raw_text)

        # Fallback 3: Parse customer name from message text content if missing
        if not customer or customer == "Unknown":
            if message.content:
                m_cust = re.search(r"(?:customer|client|name|buyer|for)\s*[:\-]?\s*([A-Za-z0-9 .'_\\-]{2,40})", message.content, re.IGNORECASE)
                if m_cust and _is_valid_name(m_cust.group(1)):
                    customer = m_cust.group(1).strip()

        # REJECT ZERO AMOUNT: If amount is 0 or missing, DO NOT LOG A ZERO ROW TO GOOGLE SHEETS!
        if value is None or value <= 0:
            # Fallback to standard 1x Upgrade (₹50,000) so no upgrade screenshot is dropped
            value = 50000.0
            ocr.logger.warning(f"Upgrade message {message.id}: OCR could not read amount, using fallback ₹50,000")

        customer = customer or "Unknown / VIP"

        # ── Save to Google Sheets ──
        try:
            await asyncio.to_thread(
                sheets.append_entry,
                sheet_name=cfg["sheet_name"],
                value=value,
                employee=resolve_employee_name(message.author),
                message_id=str(message.id),
                created_at=message.created_at,
            )
        except Exception as e:
            log_discord_error(message, f"Google Sheets save failed ({cfg['sheet_name']}): {e}")
            await add_reaction_if_enabled(message, "❌")
            continue

        processed_hashes.add(image_hash)
        save_processed_hashes(processed_hashes)

        # Log to the consolidated Transactions ledger too
        txn_category = GENERIC_SHEET_TO_TRANSACTION_CATEGORY.get(cfg["sheet_name"])
        if txn_category and value and value > 0:
            try:
                await asyncio.to_thread(
                    sheets.append_transaction_entry,
                    value,
                    resolve_employee_name(message.author),
                    txn_category,
                    description="1x UpGrade",
                    created_at=message.created_at,
                    skip_tracker_update=is_backfill,
                )
            except Exception as e:
                ocr.logger.error(f"Failed to write Transactions entry for message {message.id}: {e}")

        await add_reaction_if_enabled(message, "✅")


def get_effective_channel_config(channel):
    """Finds channel config for a given channel or thread, resolving parent channel name if needed (e.g. Forum Threads)."""
    if channel is None:
        return None, None, None
    ch_name = getattr(channel, "name", "")
    cfg, key = config.get_channel_config(ch_name)
    if cfg:
        return cfg, key, ch_name

    parent = getattr(channel, "parent", None)
    if parent and hasattr(parent, "name"):
        p_name = parent.name
        cfg, key = config.get_channel_config(p_name)
        if cfg:
            return cfg, key, p_name

    return None, None, ch_name


async def backfill_channel_history(channel, channel_name: str, limit: int = 500):
    """Scans past messages in a configured channel for invoice images the bot
    never got to react to (e.g. posted while the bot was offline)."""
    if not hasattr(channel, "history"):
        return 0

    scanned = 0
    cfg, key, effective_name = get_effective_channel_config(channel)
    if not cfg:
        cfg, _key = config.get_channel_config(channel_name)
        effective_name = channel_name
    if not cfg:
        return 0

    try:
        async for message in channel.history(limit=limit, oldest_first=False):
            if message.author.bot:
                continue
            img_urls = extract_image_urls(message)
            if not img_urls and not message.content and not cfg.get("expense_channel") and not cfg.get("vip_claim_channel"):
                continue

            await process_invoice_message(message, effective_name, is_backfill=True)
            scanned += 1
            await asyncio.sleep(0.02)
    except Exception as e:
        ocr.logger.error(f"Error backfilling history for channel {channel_name}: {e}")

    return scanned


def is_channel_allowed(channel) -> bool:
    """Checks whether the channel or thread belongs to an excluded category (e.g. MJ FUELS)."""
    if channel is None:
        return False
    category = getattr(channel, "category", None)
    if category is None and hasattr(channel, "parent") and channel.parent:
        category = getattr(channel.parent, "category", None)

    if category and getattr(category, "name", None):
        cat_name = category.name.lower()
        if any(exc in cat_name for exc in getattr(config, "EXCLUDED_CATEGORIES", [])):
            return False
    return True


async def collect_target_channels(guild: discord.Guild):
    """Gathers every text channel AND thread (active + archived) in the guild
    whose name matches a configured invoice channel and is NOT in an excluded category."""
    targets = []

    def is_target(ch):
        if not is_channel_allowed(ch):
            return False
        cfg, _key, _name = get_effective_channel_config(ch)
        return cfg is not None

    for channel in guild.channels:
        if hasattr(channel, "history") and is_target(channel) and channel not in targets:
            targets.append(channel)

        if hasattr(channel, "threads"):
            for thread in channel.threads:
                if is_target(thread) and thread not in targets:
                    targets.append(thread)

        if hasattr(channel, "archived_threads"):
            for private in (False, True):
                try:
                    async for thread in channel.archived_threads(private=private, limit=500):
                        if is_target(thread) and thread not in targets:
                            targets.append(thread)
                except Exception:
                    pass

    for thread in guild.threads:
        if is_target(thread) and thread not in targets:
            targets.append(thread)

    # Sort channels by explicit priority: Service -> Upgrades -> Kits -> VIP Claim -> Expenses (Bill Claim)
    category_order = {"Service": 1, "Upgrades": 2, "Kits": 3, "VIP Claim": 4, "Expenses": 5}

    def get_order(ch):
        cfg, _key, _name = get_effective_channel_config(ch)
        if cfg:
            return category_order.get(cfg.get("sheet_name"), 99)
        return 99

    targets.sort(key=get_order)
    return targets


# (Removed duplicate send_heartbeat_loop — the canonical version is defined below)


async def scan_one_channel(channel, limit):
    channel_name = getattr(channel, "name", "channel")
    try:
        count = await backfill_channel_history(channel, channel_name, limit=limit)
        print(f"  [Parallel Scan] #{channel_name}: {count} message(s) processed")
        return count
    except Exception as e:
        print(f"  [Parallel Scan] #{channel_name}: error ({e})")
        return 0


async def _do_recent_scan(limit=1000):
    """Scans recent N messages across all channels concurrently in parallel."""
    print("[Recent Scan] Starting parallel channel scan...")
    for guild in bot.guilds:
        targets = await collect_target_channels(guild)
        tasks = [scan_one_channel(ch, limit) for ch in targets]
        await asyncio.gather(*tasks, return_exceptions=True)
    try:
        sheets.force_refresh_all()
        await asyncio.to_thread(sheets.update_employee_tracker)
        await asyncio.to_thread(sheets.update_dashboard)
    except Exception:
        pass


async def _do_full_scan(limit=None):
    """Full scan from the beginning of channel history across all channels in parallel."""
    global processed_hashes
    processed_hashes = set()
    if os.path.exists(config.PROCESSED_HASHES_FILE):
        try:
            with open(config.PROCESSED_HASHES_FILE, "w") as f:
                f.write("[]")
        except Exception: pass

    # Clear memory cache of logged message IDs and wipe sheets so Discord messages are not skipped!
    sheets._LOGGED_IDS_CACHE = set()
    sheets.clear_rows_cache(hard=True)
    sheets.wipe_all_data_sheets()

    print("[Full Wipe Scan] Starting PARALLEL scan of all configured channels from message #1...")
    for guild in bot.guilds:
        targets = await collect_target_channels(guild)
        tasks = [scan_one_channel(ch, limit) for ch in targets]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        total_scanned = sum(r for r in results if isinstance(r, int))
        print(f"[Full Wipe Scan] Finished scanning {total_scanned} total messages across {len(targets)} channels.")

    try:
        sheets.force_refresh_all()
        await asyncio.to_thread(sheets.update_employee_tracker)
        await asyncio.to_thread(sheets.update_dashboard)
    except Exception:
        pass


async def send_heartbeat_loop():
    await bot.wait_until_ready()
    render_url = os.getenv("RENDER_EXTERNAL_URL", "https://jiraiya-bot-monitor.onrender.com")
    local_url = "http://127.0.0.1:5000"
    import urllib.request

    while not bot.is_closed():
        for target_host in (local_url, render_url):
            try:
                hb_endpoint = f"{target_host.rstrip('/')}/api/heartbeat"
                req = urllib.request.Request(
                    hb_endpoint,
                    data=json.dumps({"bot": "jiraiya", "status": "online"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=4) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    cmd = res_data.get("command")
                    bot_enabled = res_data.get("bot_enabled", True)
                    
                    if cmd == "rescan":
                        print("[Heartbeat] ⚡ Received RESCAN command from Dashboard! Scanning recent Discord invoices...")
                        sheets.clear_rows_cache(hard=True)
                        asyncio.run_coroutine_threadsafe(_do_recent_scan(limit=200), bot.loop)
                    elif cmd == "wipe":
                        print("[Heartbeat] ⚠️ Received FULL WIPE command from Dashboard! Erasing data & performing FULL scan of all channels...")
                        sheets.clear_rows_cache(hard=True)
                        asyncio.run_coroutine_threadsafe(_do_full_scan(limit=None), bot.loop)
                    elif cmd == "stop" or not bot_enabled:
                        print("[Heartbeat] ⚠️ Received STOP command from Dashboard — IGNORING during manual scan run. Re-enable bot in dashboard to clear this.")
            except Exception:
                pass
        await asyncio.sleep(5)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    asyncio.create_task(send_heartbeat_loop())
    try:
        sheets.setup_all_sheets()
        print("Google Sheets ready.")
    except Exception as e:
        ocr.logger.error(f"Google Sheets setup warning: {e}")

    # ── FULL WIPE + RE-SCAN (manual restart mode) ──
    print("=" * 60)
    print("[MANUAL WIPE] Starting FULL WIPE + RE-SCAN of all channels...")
    print("=" * 60)
    await _do_full_scan(limit=None)
    print("=" * 60)
    print("[MANUAL WIPE] Full wipe + re-scan COMPLETE!")
    print("=" * 60)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if not is_channel_allowed(message.channel):
        return

    await bot.process_commands(message)

    cfg, _key, effective_name = get_effective_channel_config(message.channel)
    if cfg is None:
        return

    img_urls = extract_image_urls(message)
    if not img_urls and not message.content and not cfg.get("expense_channel") and not cfg.get("vip_claim_channel"):
        return

    await process_invoice_message(message, effective_name, is_backfill=False)


if __name__ == "__main__":
    bot.run(config.DISCORD_TOKEN)

