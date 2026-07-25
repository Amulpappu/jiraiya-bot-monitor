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


async def add_reaction_if_enabled(message: discord.Message, emoji: str):
    """Adds an emoji reaction to a message only if ENABLE_DISCORD_REACTIONS is True in config.py."""
    if getattr(config, "ENABLE_DISCORD_REACTIONS", False):
        try:
            await message.add_reaction(emoji)
        except Exception:
            pass


async def process_service_message(message: discord.Message, cfg: dict, is_backfill: bool = False):
    """
    For the services channel: category and how many services were billed
    together are worked out from the invoice's OWN amount (e.g. 6000 =
    civilian x2, 15000 = government-tier x3), since payers sometimes get
    billed for multiple services in one invoice. A text keyword
    (civilian/civ, police/pd, ems, government/gov, taxi), if present, is used
    to confirm the exact subtype and to break ties on ambiguous amounts that
    are a clean multiple of both 3000 and 5000.
    """
    if not message.attachments:
        return

    if message.created_at.year != 2026 or message.created_at.month != 7:
        return

    if is_backfill:
        if str(message.id) in sheets.get_all_logged_message_ids():
            return

    image_attachment = next(
        (a for a in message.attachments if a.content_type and "image" in a.content_type),
        None,
    )
    if image_attachment is None:
        return

    try:
        image_hash, parsed, _raw_text = await ocr.process_invoice_image(
            image_attachment.url, ["customer", "amount"]
        )
    except Exception as e:
        ocr.logger.error(f"OCR failed for service message {message.id}: {e}")
        await add_reaction_if_enabled(message, "❓")
        return

    if config.IGNORE_DUPLICATE_IMAGES and image_hash and image_hash in processed_hashes:
        await add_reaction_if_enabled(message, "🔁")
        return

    amount = parsed.get("amount")
    if amount and amount > 100000:
        # Ignore invalid 6-digit/7-digit misreads (e.g. 2,118,064)
        await add_reaction_if_enabled(message, "❓")
        return

    keyword_category = service_pricing.parse_service_category(message.content)
    result = service_pricing.resolve_category_and_count(amount, keyword_category)

    if not result["confident"] or not result["category"] or result["category"] == "Unspecified":
        await add_reaction_if_enabled(message, "❓")
        return

    try:
        await asyncio.to_thread(
            sheets.append_service_entry,
            customer=parsed.get("customer"),
            category=result["category"],
            total=amount if amount is not None else 0,
            employee=resolve_employee_name(message.author),
            message_id=str(message.id),
            count=result["count"],
            created_at=message.created_at,
        )
    except Exception as e:
        ocr.logger.error(f"Failed to write service entry for message {message.id}: {e}")
        return

    if image_hash:
        processed_hashes.add(image_hash)
        save_processed_hashes(processed_hashes)

    if result["confident"]:
        txn_category = "Service-Civilian" if result["category"] == "civilian" else "Service-Government"
        txn_desc = f"{result['count']}x" if result.get("count") else "1x"
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
    if not message.attachments:
        return

    if message.created_at.year != 2026 or message.created_at.month != 7:
        return

    if is_backfill:
        if str(message.id) in sheets.get_all_logged_message_ids():
            return

    image_attachment = next(
        (a for a in message.attachments if a.content_type and "image" in a.content_type),
        None,
    )
    if image_attachment is None:
        return

    try:
        image_hash, parsed, raw_text = await ocr.process_invoice_image(
            image_attachment.url, ["customer", "amount"]
        )
    except Exception as e:
        ocr.logger.error(f"OCR failed for kit message {message.id}: {e}")
        image_hash, parsed, raw_text = None, {"customer": None, "amount": None}, ""

    if config.IGNORE_DUPLICATE_IMAGES and image_hash and image_hash in processed_hashes:
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
            await add_reaction_if_enabled(message, "❓")
            return

    total, discount, combined_qty, rk_subtotal, ck_subtotal = kit_pricing.calculate_kit_total(
        qty["rk"], qty["ck"]
    )
    if (total <= 0 or (qty["rk"] == 0 and qty["ck"] == 0)) and parsed.get("amount"):
        total = parsed.get("amount")
        rk_subtotal = total

    try:
        await asyncio.to_thread(
            sheets.append_kit_entry,
            customer=parsed.get("customer"),
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

    MAX_EXPENSE_AMOUNT = 3000000.0

    m_k = re.search(r"[\$₹§€£]?\s*(\d+(?:\.\d+)?)\s*k\b", text, re.IGNORECASE)
    if m_k:
        try:
            val = float(m_k.group(1)) * 1000.0
            if 0 < val <= MAX_EXPENSE_AMOUNT:
                return val
        except ValueError:
            pass

    m_curr = re.search(r"[\$₹§€£]\s*([\d,]+(?:\.\d{1,2})?)", text)
    if m_curr:
        try:
            val = float(m_curr.group(1).replace(",", ""))
            if 0 < val <= MAX_EXPENSE_AMOUNT:
                return val
        except ValueError:
            pass

    for line in text.splitlines():
        if "id:" in line.lower() or "id :" in line.lower() or "phone" in line.lower():
            continue
        for num in re.findall(r"\b([\d,]{2,9}(?:\.\d{1,2})?)\b", line):
            clean_num = num.replace(",", "")
            if clean_num not in ("2025", "2026", "2027"):
                try:
                    val = float(clean_num)
                    if 0 < val <= MAX_EXPENSE_AMOUNT:
                        return val
                except ValueError:
                    pass

    return None


async def process_expense_message(message: discord.Message, cfg: dict, is_backfill: bool = False):
    """
    For the bill_claim channel: reads the total expense amount off the order/supply bill.
    Logs to the Expenses sheet and the consolidated Transactions ledger (category='Order').
    """
    if message.created_at.year != 2026 or message.created_at.month != 7:
        return

    if is_backfill:
        if str(message.id) in sheets.get_all_logged_message_ids():
            return

    image_attachment = next(
        (a for a in message.attachments if a.content_type and "image" in a.content_type),
        None,
    )

    amount = None
    image_hash = None

    if image_attachment is not None:
        try:
            image_hash, parsed, raw_text = await ocr.process_invoice_image(
                image_attachment.url, ["amount"]
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
        await add_reaction_if_enabled(message, "❓")
        return

    if config.IGNORE_DUPLICATE_IMAGES and image_hash and image_hash in processed_hashes:
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
    For the vip-claim-logs channel: parses text-format claim details:
    Person Name : ...
    Vehicle Category : ...
    Vehicle Name : ...
    Staff Name : ...
    Amount : ...
    Logs to the VIP Claim sheet tab.
    """
    if message.created_at.year != 2026 or message.created_at.month != 7:
        return

    if is_backfill:
        if str(message.id) in sheets.get_all_logged_message_ids():
            return

    text = message.content or ""

    # Parse Person Name
    m_person = re.search(r"Person\s*Name\s*[:\-]\s*(.+)", text, re.IGNORECASE)
    person_name = m_person.group(1).strip() if m_person else "Unknown"

    # Parse Vehicle Category
    m_cat = re.search(r"(?:Vehicle\s*)?Category\s*[:\-]\s*(.+)", text, re.IGNORECASE)
    category_raw = m_cat.group(1).strip() if m_cat else "VIP"
    category = normalize_vip_category(category_raw)

    # Parse Vehicle Name
    m_veh = re.search(r"Vehicle(?:\s*Name)?\s*[:\-]\s*(.+)", text, re.IGNORECASE)
    vehicle_name = m_veh.group(1).strip() if m_veh else "Unknown"

    # Parse Staff Name
    m_staff = re.search(r"Staff(?:\s*Name)?\s*[:\-]\s*(.+)", text, re.IGNORECASE)
    if m_staff and m_staff.group(1).strip():
        staff_name = resolve_employee_name(m_staff.group(1).strip())
    else:
        staff_name = resolve_employee_name(message.author)

    # Parse Amount
    m_amt = re.search(r"Amount\s*[:\-]\s*[\$₹§€£]?\s*([\d,]+(?:\.\d+)?)", text, re.IGNORECASE)
    if m_amt:
        try:
            amount = float(m_amt.group(1).replace(",", ""))
        except ValueError:
            amount = parse_text_amount(text) or 0.0
    else:
        amount = parse_text_amount(text) or 0.0

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
    if message.created_at.year != 2026 or message.created_at.month != 7:
        return

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
        await process_service_message(message, cfg, is_backfill)
        return

    if cfg.get("expense_channel"):
        await process_expense_message(message, cfg, is_backfill)
        return

    for attachment in message.attachments:
        if not attachment.content_type or "image" not in attachment.content_type:
            continue

        # ── Skip messages already handled (logged in Google Sheets) ──
        if is_backfill:
            if str(message.id) in sheets.get_all_logged_message_ids():
                continue

        # ── OCR ──
        try:
            image_hash, parsed, raw_text = await ocr.process_invoice_image(
                attachment.url, cfg["fields"]
            )
        except Exception as e:
            ocr.logger.error(
                f"OCR failed for message {message.id} in #{channel_name} "
                f"({attachment.filename}): {e}"
            )
            await add_reaction_if_enabled(message, "❓")
            continue

        # ── Duplicate check ──
        if config.IGNORE_DUPLICATE_IMAGES and image_hash in processed_hashes:
            await add_reaction_if_enabled(message, "🔁")
            continue

        # ── Validate parsed fields ──
        customer = parsed.get("customer")
        missing = [k for k, v in parsed.items() if v is None]

        if missing:
            ocr.logger.warning(
                f"Missing fields {missing} for message {message.id} in #{channel_name}. "
                f"Raw OCR text: {raw_text!r}"
            )

        # If quantity couldn't be read, fall back to amount; if amount also missing, use 0
        if "quantity" in cfg["fields"]:
            value = parsed.get("quantity")
            if value is None:
                value = parsed.get("amount")
        else:
            value = parsed.get("amount")
        value = value if value is not None else 0

        # ── Save to Google Sheets ──
        try:
            await asyncio.to_thread(
                sheets.append_entry,
                sheet_name=cfg["sheet_name"],
                customer=customer,
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
            if message.created_at.year != 2026 or message.created_at.month != 7:
                continue
            if not message.attachments and not cfg.get("expense_channel"):
                continue

            await process_invoice_message(message, effective_name, is_backfill=True)
            scanned += 1
            await asyncio.sleep(0.3)
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


async def send_heartbeat_loop():
    """Background task sending heartbeat pings every 15 seconds & executing cloud remote commands."""
    import urllib.request
    import json
    urls = [
        "http://localhost:5000/api/heartbeat",
        "http://127.0.0.1:5000/api/heartbeat"
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Content-Type": "application/json"
    }
    while True:
        await asyncio.sleep(15)
        for u in urls:
            try:
                req = urllib.request.Request(u, data=b"{}", headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    raw = resp.read().decode('utf-8')
                    res_data = json.loads(raw)
                    cmd = res_data.get("command")
                    if cmd == "stop":
                        print("[Remote Command] Received Stop command from Web dashboard. Closing bot...")
                        await bot.close()
                        return

                    elif cmd == "wipe":
                        print("[Remote Command] FULL WIPE + FULL re-scan from beginning...")
                        sheets.clear_rows_cache()
                        sheets._LOGGED_IDS_CACHE = None
                        asyncio.create_task(_do_full_scan(limit=2000))
            except Exception as e:
                pass


async def _do_recent_scan(limit=50):
    """Scans only the most recent N messages per channel for missed invoices."""
    for guild in bot.guilds:
        targets = await collect_target_channels(guild)
        for channel in targets:
            channel_name = getattr(channel, "name", "channel")
            try:
                count = await backfill_channel_history(channel, channel_name, limit=limit)
                print(f"  [Recent Scan] #{channel_name}: {count} message(s)")
            except Exception as e:
                print(f"  [Recent Scan] #{channel_name}: error ({e})")
    try:
        await asyncio.to_thread(sheets.update_dashboard)
    except Exception:
        pass


async def _do_full_scan(limit=2000):
    """Full scan from the beginning of channel history (used after wipe)."""
    for guild in bot.guilds:
        targets = await collect_target_channels(guild)
        for channel in targets:
            channel_name = getattr(channel, "name", "channel")
            try:
                count = await backfill_channel_history(channel, channel_name, limit=limit)
                print(f"  [Full Scan] #{channel_name}: {count} message(s)")
            except Exception as e:
                print(f"  [Full Scan] #{channel_name}: error ({e})")
    try:
        await asyncio.to_thread(sheets.update_employee_tracker)
        await asyncio.to_thread(sheets.update_dashboard)
    except Exception:
        pass


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    asyncio.create_task(send_heartbeat_loop())
    try:
        sheets.setup_all_sheets()
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
                count = await backfill_channel_history(channel, channel_name, limit=50)
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

    if not message.attachments and not cfg.get("expense_channel"):
        return

    await process_invoice_message(message, effective_name, is_backfill=False)


if __name__ == "__main__":
    bot.run(config.DISCORD_TOKEN)

