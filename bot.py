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
                image_url, ["amount"]
            )
        except Exception as e:
            ocr.logger.error(f"OCR failed for service message {message.id}: {e}")

    if config.IGNORE_DUPLICATE_IMAGES and image_hash and image_hash in processed_hashes:
        if str(message.id) in sheets.get_all_logged_message_ids():
            await add_reaction_if_enabled(message, "🔁")
            return

    keyword_category = service_pricing.parse_service_category(message.content)
    if not keyword_category and raw_text:
        keyword_category = service_pricing.parse_service_category(raw_text)

    amount = parsed.get("amount")
    if (amount is None or amount <= 0) and message.content:
        amount = parse_text_amount(message.content)
    if (amount is None or amount <= 0) and raw_text:
        amount = parse_text_amount(raw_text)

    # Determine default unit price for category (5000 for pd/ems/taxi/gov, 3000 for civilian)
    unit_price = float(config.SERVICE_PRICES.get(keyword_category, 3000.0)) if keyword_category else 3000.0

    if amount is None or amount <= 0:
        amount = unit_price
        ocr.logger.warning(f"Service message {message.id}: OCR could not read amount, using fallback ₹{amount:,.0f} for category '{keyword_category or 'civilian'}'")

    result = service_pricing.resolve_category_and_count(amount, keyword_category)
    service_cat = result.get("category") or keyword_category or ("gov" if any(g in (message.content or "").lower() for g in ("pd", "ems", "taxi", "govt", "government", "police", "cop", "medic")) else "civilian")

    cat_unit_price = float(config.SERVICE_PRICES.get(service_cat, 3000.0))
    service_cnt = result.get("count") or max(1, int(round(amount / cat_unit_price)))

    # ── ENFORCE correct total based on category price ──
    # The keyword category is the source of truth for pricing.
    # If the mechanic typed "pd"/"ems"/"taxi"/"gov" then EACH service = ₹5,000;
    # if "civilian" then EACH service = ₹3,000.
    # OCR can misread the amount (e.g. 3000 for a PD invoice), so we override
    # the total to cat_unit_price × count to guarantee correct sheet data.
    enforced_total = cat_unit_price * service_cnt
    if enforced_total != amount:
        ocr.logger.info(
            f"Service message {message.id}: Enforced total ₹{enforced_total:,.0f} "
            f"(was ₹{amount:,.0f}) for category '{service_cat}' × {service_cnt}"
        )
    amount = enforced_total

    try:
        await asyncio.to_thread(
            sheets.append_service_entry,
            category=service_cat,
            total=amount,
            employee=resolve_employee_name(message.author),
            message_id=str(message.id),
            count=service_cnt,
            created_at=message.created_at,
            skip_dashboard_update=is_backfill,
        )
    except Exception as e:
        ocr.logger.error(f"Failed to write service entry for message {message.id}: {e}")
        return

    if image_hash:
        processed_hashes.add(image_hash)
        save_processed_hashes(processed_hashes)

    is_gov_tier = service_cat in ("government", "gov", "pd", "ems", "taxi")
    txn_category = "Service-Government" if is_gov_tier else "Service-Civilian"
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
                image_url, ["amount"]
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
            skip_dashboard_update=is_backfill,
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

    # 2. Currency symbol prefix or suffix ($15000 / ₹15,000 / 15000$)
    m_curr_pref = re.search(r"[\$₹§€£]\s*([\d,]+(?:\.\d{1,2})?)", text)
    if m_curr_pref:
        try:
            val = float(m_curr_pref.group(1).replace(",", ""))
            if 1 <= val <= MAX_EXPENSE_AMOUNT:
                return val
        except ValueError:
            pass

    m_curr_suff = re.search(r"([\d,]+(?:\.\d{1,2})?)\s*[\$₹§€£]", text)
    if m_curr_suff:
        try:
            val = float(m_curr_suff.group(1).replace(",", ""))
            if 1 <= val <= MAX_EXPENSE_AMOUNT:
                return val
        except ValueError:
            pass

    # 3. Explicit keywords (total 15000, amount 15000, price 15000, upgrade 25000)
    m_kw = re.search(r"(?:total|amount|price|value|cost|fee|bill|upgrade)\s*[:\-]?\s*[\$₹§€£]?\s*([\d,]+(?:\.\d{1,2})?)", text, re.IGNORECASE)
    if m_kw:
        try:
            val = float(m_kw.group(1).replace(",", ""))
            if 1 <= val <= MAX_EXPENSE_AMOUNT and val not in (2024, 2025, 2026, 2027, 2028, 2029, 2030):
                return val
        except ValueError:
            pass

    # 4. Standalone numbers >= 1 (excluding dates/timestamps/IDs)
    candidates = []
    for line in text.splitlines():
        clean_line = re.sub(r"\b(?:id|msg_id|message_id|phone)\s*[:\-]?\s*\d+\b", "", line, flags=re.IGNORECASE)
        clean_line = re.sub(r"\b\d{1,4}[/\.\-]\d{1,2}[/\.\-]\d{1,4}\b", "", clean_line)
        clean_line = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", "", clean_line)
        clean_line = re.sub(r"https?://\S+|www\.\S+", "", clean_line)

        for num in re.findall(r"\b([\d,]{1,9}(?:\.\d{1,2})?)\b", clean_line):
            clean_num = num.replace(",", "")
            if clean_num not in ("2024", "2025", "2026", "2027", "2028", "2029", "2030"):
                try:
                    val = float(clean_num)
                    if 1 <= val <= MAX_EXPENSE_AMOUNT:
                        candidates.append(val)
                except ValueError:
                    pass

    if candidates:
        return max(candidates)

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
            skip_dashboard_update=is_backfill,
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
            skip_dashboard_update=is_backfill,
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
                    skip_dashboard_update=is_backfill,
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

        # Fallback 3: Deep search for ANY standalone positive number in raw_text or message content
        if (value is None or value <= 0):
            all_txt = f"{message.content or ''}\n{raw_text or ''}"
            nums = []
            for num in re.findall(r"\b([\d,]{1,8})\b", all_txt):
                clean = num.replace(",", "")
                if clean not in ("2024", "2025", "2026", "2027", "2028", "2029", "2030", str(message.id)):
                    try:
                        v = float(clean)
                        if 1 <= v <= 500000:
                            nums.append(v)
                    except ValueError: pass
            if nums:
                value = max(nums)

        # Fallback 4: Parse customer name from message text content if missing
        if not customer or customer == "Unknown":
            if message.content:
                m_cust = re.search(r"(?:customer|client|name|buyer|for)\s*[:\-]?\s*([A-Za-z0-9 .'_\\-]{2,40})", message.content, re.IGNORECASE)
                if m_cust and _is_valid_name(m_cust.group(1)):
                    customer = m_cust.group(1).strip()

        # Last resort fallback if absolutely zero text/number could be read from image
        if value is None or value <= 0:
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
                skip_dashboard_update=is_backfill,
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
    """Full scan from the beginning of channel history across all channels strictly in order (Service -> Upgrades -> Kits -> VIP Claim -> Expenses)."""
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

    print("[Full Wipe Scan] Starting SEQUENTIAL ORDER-WISE scan of all configured channels from message #1...")
    total_scanned = 0
    category_order = {"Service": 1, "Upgrades": 2, "Kits": 3, "VIP Claim": 4, "Expenses": 5}
    category_labels = {1: "Service", 2: "Upgrades", 3: "Kits", 4: "VIP Claim", 5: "Expenses"}

    for guild in bot.guilds:
        targets = await collect_target_channels(guild)

        def get_order(ch):
            cfg, _key, _name = get_effective_channel_config(ch)
            if cfg:
                return category_order.get(cfg.get("sheet_name"), 99)
            return 99

        for cat_num in (1, 2, 3, 4, 5):
            cat_name = category_labels.get(cat_num, f"Category {cat_num}")
            cat_channels = [ch for ch in targets if get_order(ch) == cat_num]
            if not cat_channels:
                continue

            july_start = datetime.datetime(2026, 7, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
            august_start = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)

            print(f"  ▶ [Order {cat_num}/5: {cat_name}] Scanning {len(cat_channels)} channel(s)...")
            for ch in cat_channels:
                ch_name = getattr(ch, "name", "channel")
                count = 0
                try:
                    async for message in ch.history(limit=limit, after=july_start, before=august_start, oldest_first=True):
                        if message.author.bot:
                            continue
                        cfg, _key, effective_name = get_effective_channel_config(ch)
                        if not cfg:
                            continue
                        img_urls = extract_image_urls(message)
                        if not img_urls and not message.content and not cfg.get("expense_channel") and not cfg.get("vip_claim_channel"):
                            continue

                        await process_invoice_message(message, effective_name, is_backfill=True)
                        count += 1
                        total_scanned += 1
                        await asyncio.sleep(0.02)
                    print(f"    └─ #{ch_name}: {count} message(s) processed")
                except Exception as e:
                    print(f"    └─ #{ch_name}: error ({e})")

    print(f"[Full Wipe Scan] Finished scanning {total_scanned} total messages across all channels in priority order.")

    try:
        sheets.sort_all_sheets_by_timestamp()
        sheets.force_refresh_all()
        await asyncio.to_thread(sheets.update_employee_tracker)
        await asyncio.to_thread(sheets.update_dashboard)
    except Exception:
        pass


def _fetch_heartbeat(url, data_bytes, headers):
    import urllib.request
    req = urllib.request.Request(url, data=data_bytes, headers=headers)
    with urllib.request.urlopen(req, timeout=4) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def send_heartbeat_loop():
    await bot.wait_until_ready()
    render_url = os.getenv("RENDER_EXTERNAL_URL", "https://jiraiya-bot-monitor.onrender.com")
    local_url = "http://127.0.0.1:5000"

    headers = {"Content-Type": "application/json"}
    payload = json.dumps({"bot": "jiraiya", "status": "online"}).encode("utf-8")

    while not bot.is_closed():
        for target_host in (local_url, render_url):
            try:
                hb_endpoint = f"{target_host.rstrip('/')}/api/heartbeat"
                res_data = await asyncio.to_thread(_fetch_heartbeat, hb_endpoint, payload, headers)
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
                    print("[Heartbeat] Received STOP command from Dashboard! Setting presence to offline and stopping...")
                    try:
                        await bot.change_presence(status=discord.Status.offline)
                        await asyncio.sleep(0.5)
                    except Exception: pass
                    await bot.close()
                    sys.exit(0)
            except Exception:
                pass
        await asyncio.sleep(5)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    asyncio.create_task(send_heartbeat_loop())
    try:
        await asyncio.to_thread(sheets.setup_all_sheets)
        print("Google Sheets ready.")
    except Exception as e:
        ocr.logger.error(f"Google Sheets setup warning: {e}")

    print("Scanning configured channels/threads for invoices missed while offline...")
    for guild in bot.guilds:
        targets = await collect_target_channels(guild)
        for channel in targets:
            channel_name = getattr(channel, "name", "channel")
            norm = config.normalize_channel_name(channel_name)
            clean_display_name = re.sub(r"[^\x20-\x7E]", "", norm).strip("┆| ") or channel_name
            try:
                count = await backfill_channel_history(channel, channel_name, limit=500)
                print(f"  #{clean_display_name}: scanned {count} message(s).")
            except discord.Forbidden:
                print(f"  #{clean_display_name}: missing permission to read history, skipped.")
            except Exception as e:
                print(f"  #{clean_display_name}: error during scan ({e}).")

    print("Backfill scan complete. Updating dashboard & employee roster...")
    try:
        await asyncio.to_thread(sheets.update_employee_tracker)
        await asyncio.to_thread(sheets.update_dashboard)
    except Exception as e:
        ocr.logger.error(f"Error updating dashboard post-scan: {e}")


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

