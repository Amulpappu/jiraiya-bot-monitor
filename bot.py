import os
import re
import sys
import json
import time
import asyncio
import datetime
import logging
import discord
from discord.ext import commands

import config
import sheets
import ocr
import service_pricing
import kit_pricing
import database

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("bot")

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
processed_hashes = set()


def load_processed_hashes():
    global processed_hashes
    if os.path.exists(config.PROCESSED_HASHES_FILE):
        try:
            with open(config.PROCESSED_HASHES_FILE, "r") as f:
                processed_hashes = set(json.load(f))
        except Exception:
            processed_hashes = set()


def save_processed_hashes(hashes_set):
    try:
        with open(config.PROCESSED_HASHES_FILE, "w") as f:
            json.dump(list(hashes_set), f)
    except Exception:
        pass


def extract_image_urls(message: discord.Message) -> list:
    urls = []
    for att in message.attachments:
        if att.content_type and att.content_type.startswith("image/"):
            urls.append(att.url)
        elif any(att.filename.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp")):
            urls.append(att.url)
    for embed in message.embeds:
        if embed.image and embed.image.url:
            urls.append(embed.image.url)
        elif embed.thumbnail and embed.thumbnail.url:
            urls.append(embed.thumbnail.url)
    return urls


def parse_text_amount(text: str) -> float:
    if not text:
        return None
    patterns = [
        r"(?:total|amount|price|subtotal|pay|cost|amt)\s*[:\-]?\s*[\$₹§€£sS]?\s*([\d,]+(?:\.\d+)?)",
        r"[\$₹§€£sS]\s*([\d,]+(?:\.\d+)?)",
        r"\b([\d,]{3,7})\b",
    ]
    for pat in patterns:
        matches = re.findall(pat, text, re.IGNORECASE)
        for m in matches:
            try:
                val = float(m.replace(",", ""))
                if 50 <= val <= 1000000:
                    return val
            except ValueError:
                continue
    return None


def resolve_employee_name(user) -> str:
    """Resolves Discord user to exact Employee Name using config mapping table."""
    return config.resolve_employee_from_author(user)



def parse_customer_from_text(content: str) -> str:
    """Parses customer name from Discord message content (e.g. 'civ services -Luna Alice', 'civ service - Butty Paul', '- Luna Alice')."""
    if not content:
        return None
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    for line in lines:
        # 1. Hyphen/colon pattern: "civ services -Luna Alice", "civ service - Butty Paul", "- Luna Alice"
        m_hyphen = re.search(r"(?:services?|upgrades?|civ|pd|ems|kit|kits|civilian|govt)?\s*[\-\:]\s*([A-Za-z0-9_\. ]{2,35})", line, re.IGNORECASE)
        if m_hyphen:
            cand = m_hyphen.group(1).strip()
            cand = re.sub(r"^[^\w]+|[^\w\.]+$", "", cand).strip()
            if ocr._is_valid_name(cand):
                return cand

        # 2. Standard labels: customer: Luna Alice, client: Luna Alice, name: Luna Alice, billed to: Luna Alice
        m_label = re.search(r"(?:customer|client|name|billed to|for|to)\s*[:\-]?\s*([A-Za-z0-9_\. ]{2,35})", line, re.IGNORECASE)
        if m_label:
            cand = m_label.group(1).strip()
            cand = re.sub(r"^[^\w]+|[^\w\.]+$", "", cand).strip()
            if ocr._is_valid_name(cand):
                return cand
    return None


async def process_service_or_upgrade_message(message: discord.Message, cfg: dict, is_backfill: bool = False):
    """Processes messages in Services/Upgrades combined channels (e.g. 🌀┆aug-ʟᴏɢꜱ)."""
    if is_backfill and str(message.id) in sheets.get_all_logged_message_ids():
        return

    img_urls = extract_image_urls(message)
    image_url = img_urls[0] if img_urls else None
    image_hash, parsed, raw_text = None, {}, ""

    if image_url:
        try:
            image_hash, parsed, raw_text = await ocr.process_invoice_image(image_url, ["customer", "amount"])
        except Exception as e:
            logger.error(f"OCR failed for message {message.id}: {e}")

    if config.IGNORE_DUPLICATE_IMAGES and image_hash and image_hash in processed_hashes:
        if str(message.id) in sheets.get_all_logged_message_ids():
            return

    amount = parsed.get("amount")
    if (amount is None or amount <= 0) and message.content:
        amount = parse_text_amount(message.content)
    if (amount is None or amount <= 0) and raw_text:
        amount = parse_text_amount(raw_text)

    cust_name = parsed.get("customer")
    if (not cust_name or cust_name.strip().lower() in ("unknown", "none", "")) and message.content:
        cust_name = parse_customer_from_text(message.content)
    if not cust_name or cust_name.strip().lower() in ("unknown", "none", ""):
        cust_name = "Unknown"

    full_text = (message.content or "") + " " + raw_text

    ch_name_lower = getattr(message.channel, "name", "").lower()
    if "upgrade" in ch_name_lower:
        is_upgrade = True
    elif service_pricing.is_upgrade_message(full_text, amount):
        is_upgrade = True
    else:
        is_upgrade = False

    emp_name = resolve_employee_name(message.author)

    if is_upgrade:
        # Route to Car Upgrade sheet using exact parsed amount
        upgrade_amount = float(amount) if (amount and amount > 0) else 0.0
        try:
            await asyncio.to_thread(
                sheets.append_entry,
                sheet_name="Upgrades",
                value=upgrade_amount,
                employee=emp_name,
                message_id=str(message.id),
                created_at=message.created_at,
                customer=cust_name,
                skip_dashboard_update=is_backfill,
            )
            await asyncio.to_thread(
                sheets.append_transaction_entry,
                amount=upgrade_amount,
                employee=emp_name,
                category="Car UpGrade",
                description="Car UpGrade Invoice",
                created_at=message.created_at,
                skip_tracker_update=is_backfill,
            )
        except Exception as e:
            logger.error(f"Failed to write Upgrade entry for message {message.id}: {e}")
            return
    else:
        # Route to Service sheet (Civilian = ₹7,000, Govt/PD/EMS/TAXI = ₹10,000)
        kw_cat = service_pricing.parse_service_category(full_text)
        res = service_pricing.resolve_category_and_count(amount, kw_cat)
        service_cat = res["category"]
        service_cnt = res["count"]
        service_total = res["total"]

        try:
            await asyncio.to_thread(
                sheets.append_service_entry,
                category=service_cat,
                total=service_total,
                employee=emp_name,
                message_id=str(message.id),
                count=service_cnt,
                created_at=message.created_at,
                customer=cust_name,
                skip_dashboard_update=is_backfill,
            )
            txn_cat = "Service-Government" if any(g in service_cat for g in ("pd", "ems", "taxi", "gov")) else "Service-Civilian"
            await asyncio.to_thread(
                sheets.append_transaction_entry,
                amount=service_total,
                employee=emp_name,
                category=txn_cat,
                description=f"{service_cnt}x {service_cat.upper()} Service",
                created_at=message.created_at,
                skip_tracker_update=is_backfill,
            )
        except Exception as e:
            logger.error(f"Failed to write Service entry for message {message.id}: {e}")
            return

    if image_hash:
        processed_hashes.add(image_hash)
        save_processed_hashes(processed_hashes)


async def process_kit_message(message: discord.Message, cfg: dict, is_backfill: bool = False):
    """Processes messages in Kit channels (e.g. 🧰┆aug-ᴋɪᴛꜱ)."""
    if is_backfill and str(message.id) in sheets.get_all_logged_message_ids():
        return

    img_urls = extract_image_urls(message)
    image_url = img_urls[0] if img_urls else None
    image_hash, parsed, raw_text = None, {}, ""

    if image_url:
        try:
            image_hash, parsed, raw_text = await ocr.process_invoice_image(image_url, ["customer", "amount"])
        except Exception as e:
            logger.error(f"OCR failed for kit message {message.id}: {e}")

    cust_name = parsed.get("customer")
    if (not cust_name or cust_name.strip().lower() in ("unknown", "none", "")) and message.content:
        cust_name = parse_customer_from_text(message.content)
    if not cust_name or cust_name.strip().lower() in ("unknown", "none", ""):
        cust_name = "Unknown"

    full_text = (message.content or "") + " " + raw_text
    amt_parsed = parsed.get("amount") or parse_text_amount(full_text)

    qty = kit_pricing.parse_kit_quantities(full_text)

    # If OCR/text explicitly mentions "cleaning kit" or "ck", use ck price for breakdown
    full_lower = full_text.lower()
    is_ck_explicit = any(k in full_lower for k in ("cleaning kit", "cleaning", " ck ", "ck:"))

    if qty is None and amt_parsed and amt_parsed > 0:
        if is_ck_explicit:
            ck_price = config.KIT_PRICES.get("ck", 1000.0)
            pred_ck = max(1, int(round(float(amt_parsed) / ck_price)))
            qty = {"rk": 0, "ck": pred_ck}
        else:
            pred_rk, pred_ck = kit_pricing.predict_kit_quantities_from_amount(float(amt_parsed))
            qty = {"rk": pred_rk, "ck": pred_ck}
    elif qty is None:
        qty = {"rk": 1, "ck": 0}

    total, discount_pct, total_kits, rk_sub, ck_sub = kit_pricing.calculate_kit_total(qty["rk"], qty["ck"])

    # Override with exact parsed amount but keep existing qty breakdown
    if amt_parsed and amt_parsed > 0:
        total = float(amt_parsed)
        # Only re-derive qty from amount if we don't already have a valid explicit qty
        if qty["rk"] == 0 and qty["ck"] == 0:
            if is_ck_explicit:
                ck_price = config.KIT_PRICES.get("ck", 1000.0)
                qty["ck"] = max(1, int(round(total / ck_price)))
            else:
                qty["rk"] = max(1, int(round(total / config.KIT_PRICES.get("rk", 1000.0))))

    emp_name = resolve_employee_name(message.author)

    # Recalculate subtotals AFTER quantity/amount override so ck_sub is correct
    rk_price = config.KIT_PRICES.get("rk", 1000.0)
    ck_price = config.KIT_PRICES.get("ck", 1000.0)
    rk_sub = qty["rk"] * rk_price
    ck_sub = qty["ck"] * ck_price
    # Use exact parsed amount as the recorded total (not the calculated total)
    final_total = float(amt_parsed) if (amt_parsed and amt_parsed > 0) else total

    # Build human-readable description
    rk_desc = f"{qty['rk']}x Repair Kit" if qty['rk'] > 0 else ""
    ck_desc = f"{qty['ck']}x Cleaning Kit" if qty['ck'] > 0 else ""
    combined_desc = " + ".join(filter(None, [rk_desc, ck_desc])) or "Kit Sale"

    try:
        await asyncio.to_thread(
            sheets.append_kit_entry,
            rk_qty=qty["rk"],
            ck_qty=qty["ck"],
            discount_pct=discount_pct,
            total=final_total,
            employee=emp_name,
            message_id=str(message.id),
            created_at=message.created_at,
            customer=cust_name,
            skip_dashboard_update=is_backfill,
        )
        if rk_sub > 0:
            await asyncio.to_thread(
                sheets.append_transaction_entry,
                rk_sub, emp_name, "Repair Kit",
                f"{qty['rk']}x Repair Kit",
                created_at=message.created_at,
                skip_tracker_update=is_backfill,
            )
        if ck_sub > 0:
            await asyncio.to_thread(
                sheets.append_transaction_entry,
                ck_sub, emp_name, "Cleaning Kit",
                f"{qty['ck']}x Cleaning Kit",
                created_at=message.created_at,
                skip_tracker_update=is_backfill,
            )
        # If both are 0 (shouldn't happen) write a single combined entry
        if rk_sub == 0 and ck_sub == 0 and final_total > 0:
            await asyncio.to_thread(
                sheets.append_transaction_entry,
                final_total, emp_name, "Kit Sale",
                combined_desc,
                created_at=message.created_at,
                skip_tracker_update=is_backfill,
            )
    except Exception as e:
        logger.error(f"Failed to write Kit entry for message {message.id}: {e}")
        return

    if image_hash:
        processed_hashes.add(image_hash)
        save_processed_hashes(processed_hashes)


async def process_vip_claim_message(message: discord.Message, cfg: dict, is_backfill: bool = False):
    """Processes messages in VIP Claim channels (e.g. 💸┆vip-claim-logs)."""
    if is_backfill and str(message.id) in sheets.get_all_logged_message_ids():
        return

    img_urls = extract_image_urls(message)
    image_url = img_urls[0] if img_urls else None
    parsed, raw_text = {}, ""

    if image_url:
        try:
            _, parsed, raw_text = await ocr.process_invoice_image(image_url, ["customer", "amount"])
        except Exception as e:
            logger.error(f"OCR failed for VIP claim message {message.id}: {e}")

    full_text = (message.content or "") + " " + raw_text

    # Parse fields
    m_name = re.search(r"(?:Name|Person|Customer)\s*[:\-]\s*([^\n]+)", full_text, re.IGNORECASE)
    person_name = m_name.group(1).strip() if m_name else (parsed.get("customer") or "Unknown")

    m_staff = re.search(r"Staff\s*[:\-]\s*([^\n]+)", full_text, re.IGNORECASE)
    staff_name = resolve_employee_name(m_staff.group(1)) if m_staff else resolve_employee_name(message.author)

    m_veh = re.search(r"Vehicle\s*[:\-]\s*([^\n]+)", full_text, re.IGNORECASE)
    vehicle = m_veh.group(1).strip() if m_veh else "Unknown"

    amount = parsed.get("amount") or parse_text_amount(full_text) or 0.0

    try:
        await asyncio.to_thread(
            sheets.append_vip_claim_entry,
            person_name=person_name,
            category="VIP",
            vehicle=vehicle,
            staff=staff_name,
            amount=amount,
            message_id=str(message.id),
            created_at=message.created_at,
            skip_dashboard_update=is_backfill,
        )
    except Exception as e:
        logger.error(f"Failed to write VIP Claim entry for message {message.id}: {e}")
        return


async def process_expense_message(message: discord.Message, cfg: dict, is_backfill: bool = False):
    """Processes messages in Bill Claim / Expense channels (e.g. 💸┆ʙɪʟʟ_ᴄʟᴀɪᴍ)."""
    if is_backfill and str(message.id) in sheets.get_all_logged_message_ids():
        return

    img_urls = extract_image_urls(message)
    image_url = img_urls[0] if img_urls else None
    parsed, raw_text = {}, ""

    if image_url:
        try:
            _, parsed, raw_text = await ocr.process_invoice_image(image_url, ["amount"])
        except Exception as e:
            logger.error(f"OCR failed for expense message {message.id}: {e}")

    full_text = (message.content or "") + " " + raw_text
    amount = parsed.get("amount") or parse_text_amount(full_text) or 0.0
    emp_name = resolve_employee_name(message.author)

    # Extract description (e.g. Food and Water, Sicily Logistics ID : 92)
    m_desc = re.search(r"(?:Description|Reason|For|Note|Item)\s*[:\-]\s*([^\n]+)", full_text, re.IGNORECASE)
    if m_desc:
        desc = m_desc.group(1).strip()
    elif message.content:
        desc = message.content.strip()
    elif raw_text:
        desc = raw_text.splitlines()[0].strip()
    else:
        desc = "Bill Claim Expense"

    cat = "Food" if "food" in desc.lower() or "water" in desc.lower() else "Order"

    try:
        await asyncio.to_thread(
            sheets.append_expense_entry,
            amount=amount,
            employee=emp_name,
            message_id=str(message.id),
            created_at=message.created_at,
            skip_dashboard_update=is_backfill,
        )
        await asyncio.to_thread(
            sheets.append_transaction_entry,
            amount=amount,
            employee=emp_name,
            category=cat,
            description=desc,
            created_at=message.created_at,
            skip_tracker_update=is_backfill,
        )
    except Exception as e:
        logger.error(f"Failed to write Expense entry for message {message.id}: {e}")
        return


def is_ignored_category(channel) -> bool:
    """Returns True if the channel belongs to MJ FUELS or other non-Jiraiya categories."""
    cat = getattr(channel, "category", None)
    if not cat and hasattr(channel, "parent"):
        cat = getattr(channel.parent, "category", None)
    if cat and getattr(cat, "name", None):
        cat_name = cat.name.lower()
        if any(kw in cat_name for kw in ("mj", "fuel")):
            return True
    return False


async def route_invoice_message(message: discord.Message, is_backfill: bool = False):
    """Routes an incoming Discord message to the correct channel handler."""
    if message.author.bot:
        return

    # Skip MJ FUELS channels (e.g. yellow box BILL_CLAIM)
    if is_ignored_category(message.channel):
        return

    # Skip "High Command" — not an employee, should not be logged
    emp_name = resolve_employee_name(message.author)
    if emp_name and emp_name.lower() in ("high command", "high comman", "highcommand", "high_command"):
        return

    ch_name = getattr(message.channel, "name", "")
    cfg, _ = config.get_channel_config(ch_name)
    if not cfg and hasattr(message.channel, "parent") and message.channel.parent:
        cfg, _ = config.get_channel_config(message.channel.parent.name)
    if not cfg:
        return

    if cfg.get("combined_logs"):
        await process_service_or_upgrade_message(message, cfg, is_backfill=is_backfill)
    elif cfg.get("kit_channel"):
        await process_kit_message(message, cfg, is_backfill=is_backfill)
    elif cfg.get("vip_claim_channel"):
        await process_vip_claim_message(message, cfg, is_backfill=is_backfill)
    elif cfg.get("expense_channel"):
        await process_expense_message(message, cfg, is_backfill=is_backfill)


_BACKFILL_LOCK = asyncio.Lock()


async def scan_channel_messages(ch, limit, august_start):
    try:
        async for message in ch.history(limit=limit, oldest_first=True):
            if august_start and message.created_at < august_start:
                continue
            await route_invoice_message(message, is_backfill=True)
    except Exception as e:
        logger.error(f"Backfill scan error on #{getattr(ch, 'name', 'thread')}: {e}")


async def backfill_channel_history(limit=1000):
    """Scans historical messages for August 2026 month across configured channels & thread channels."""
    async with _BACKFILL_LOCK:
        logger.info("[Backfill Scan] Scanning history across configured channels & threads...")
        august_start = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        await asyncio.to_thread(sheets.clear_rows_cache, hard=True)

    for guild in bot.guilds:
        # Collect all channels and threads to scan
        channels_to_scan = []
        for channel in guild.text_channels:
            if is_ignored_category(channel):
                continue
            channels_to_scan.append(channel)

        threads_to_scan = []
        if hasattr(guild, "threads"):
            threads_to_scan.extend(guild.threads)
        if hasattr(guild, "active_threads"):
            try:
                act_threads = await guild.active_threads()
                threads_to_scan.extend(act_threads)
            except Exception as e:
                logger.error(f"Error fetching guild active threads: {e}")

        for channel in guild.text_channels:
            if is_ignored_category(channel):
                continue
            if hasattr(channel, "threads"):
                threads_to_scan.extend(channel.threads)
            if hasattr(channel, "archived_threads"):
                try:
                    async for thread in channel.archived_threads(limit=100):
                        threads_to_scan.append(thread)
                except Exception:
                    pass

        # Scan text channels first
        for ch in channels_to_scan:
            cfg, _ = config.get_channel_config(ch.name)
            if cfg:
                logger.info(f"[Backfill Scan] Scanning channel #{ch.name}...")
                await scan_channel_messages(ch, limit, august_start)

        # Scan deduplicated threads
        seen_threads = set()
        for thread in threads_to_scan:
            if not thread or thread.id in seen_threads:
                continue
            seen_threads.add(thread.id)
            if is_ignored_category(thread):
                continue

            ch_name = getattr(thread, "name", "")
            cfg, _ = config.get_channel_config(ch_name)
            if not cfg and hasattr(thread, "parent") and thread.parent:
                cfg, _ = config.get_channel_config(thread.parent.name)

            if cfg:
                logger.info(f"[Backfill Scan] Scanning thread #{ch_name} (parent #{getattr(thread.parent, 'name', 'N/A')})...")
                await scan_channel_messages(thread, limit, august_start)

    try:
        await asyncio.to_thread(sheets.update_employee_tracker)
        await asyncio.to_thread(sheets.update_dashboard)
        logger.info("[Backfill Scan] Dashboard and Employee Tracker updated.")
    except Exception as e:
        logger.error(f"Post-scan dashboard update failed: {e}")


@bot.event
async def on_ready():
    logger.info(f"Bot logged in as {bot.user} (ID: {bot.user.id})")
    load_processed_hashes()

    await asyncio.to_thread(sheets.setup_all_sheets)
    logger.info("Ready! Triggering initial channel scan...")
    asyncio.create_task(check_control_flags())
    asyncio.create_task(backfill_channel_history(limit=500))


async def check_control_flags():
    """Monitors control flag files created by monitor_app (e.g. via /api/wipe or /api/rescan)."""
    global processed_hashes
    while True:
        try:
            await asyncio.sleep(2)
            if os.path.exists("wipe_trigger.flag"):
                try:
                    os.remove("wipe_trigger.flag")
                except Exception:
                    pass
                logger.info("[Control Flag] Wipe & Rescan triggered...")
                processed_hashes.clear()
                save_processed_hashes(set())
                await asyncio.to_thread(sheets.wipe_all_data_sheets)
                asyncio.create_task(backfill_channel_history(limit=1000))

            elif os.path.exists("rescan_trigger.flag"):
                try:
                    os.remove("rescan_trigger.flag")
                except Exception:
                    pass
                logger.info("[Control Flag] Rescan triggered...")
                processed_hashes.clear()
                save_processed_hashes(set())
                await asyncio.to_thread(sheets.clear_rows_cache, hard=True)
                asyncio.create_task(backfill_channel_history(limit=1000))
        except Exception as e:
            logger.error(f"Error checking control flags: {e}")


async def _deferred_dashboard_update():
    """Waits 3 seconds then updates the dashboard and employee tracker in the background."""
    await asyncio.sleep(3)
    try:
        await asyncio.to_thread(sheets.update_employee_tracker)
        await asyncio.to_thread(sheets.update_dashboard)
    except Exception as e:
        logger.error(f"Deferred dashboard update failed: {e}")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    # Fire-and-forget: process immediately in background so Discord gateway never lags
    asyncio.create_task(_handle_live_message(message))
    await bot.process_commands(message)


async def _handle_live_message(message: discord.Message):
    """Processes a live (real-time) message: writes to sheet immediately, then defers dashboard update."""
    await route_invoice_message(message, is_backfill=False)
    # Trigger a lightweight deferred dashboard refresh 3 seconds later
    asyncio.create_task(_deferred_dashboard_update())


@bot.command(name="rescan")
async def cmd_rescan(ctx):
    """Triggers channel history rescan silently."""
    global processed_hashes
    processed_hashes.clear()
    save_processed_hashes(set())
    await asyncio.to_thread(sheets.clear_rows_cache, hard=True)
    asyncio.create_task(backfill_channel_history(limit=1000))


@bot.command(name="wipe")
async def cmd_wipe(ctx):
    """Wipes worksheets and rescans silently."""
    global processed_hashes
    processed_hashes.clear()
    save_processed_hashes(set())
    await asyncio.to_thread(sheets.wipe_all_data_sheets)
    asyncio.create_task(backfill_channel_history(limit=1000))


@bot.command(name="status")
async def cmd_status(ctx):
    """Silent status check command."""
    pass


if __name__ == "__main__":
    if not config.DISCORD_TOKEN:
        logger.error("No DISCORD_TOKEN configured!")
        sys.exit(1)
    bot.run(config.DISCORD_TOKEN)
