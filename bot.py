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
        r"(?:total|amount|price|subtotal|pay|cost|amt)\s*[:\-]?\s*[\$₹§€£]?\s*([\d,]+(?:\.\d+)?)",
        r"[\$₹§€£]\s*([\d,]+(?:\.\d+)?)",
        r"\b([\d,]{4,10})\b",
    ]
    for pat in patterns:
        matches = re.findall(pat, text, re.IGNORECASE)
        for m in matches:
            try:
                val = float(m.replace(",", ""))
                if 100 <= val <= 1000000:
                    return val
            except ValueError:
                continue
    return None


def resolve_employee_name(user: discord.User or str) -> str:
    if isinstance(user, str):
        tag = user.strip().lower()
        if tag in config.EMPLOYEE_MAPPING:
            return config.EMPLOYEE_MAPPING[tag]
        return user.strip()

    if not user:
        return "Unknown"

    name_raw = user.display_name or user.name
    tag_clean = "@" + user.name.lower()
    if tag_clean in config.EMPLOYEE_MAPPING:
        return config.EMPLOYEE_MAPPING[tag_clean]
    if user.name.lower() in config.EMPLOYEE_MAPPING:
        return config.EMPLOYEE_MAPPING[user.name.lower()]

    return name_raw


async def add_reaction_if_enabled(message: discord.Message, emoji: str):
    """Silent mode — no reactions or messages are sent to Discord channels."""
    return


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
            await add_reaction_if_enabled(message, "🔁")
            return

    amount = parsed.get("amount")
    if (amount is None or amount <= 0) and message.content:
        amount = parse_text_amount(message.content)
    if (amount is None or amount <= 0) and raw_text:
        amount = parse_text_amount(raw_text)

    cust_name = parsed.get("customer")
    if not cust_name and message.content:
        m_c = re.search(r"(?:customer|client|name|billed to)\s*[:\-]\s*([^\n]+)", message.content, re.IGNORECASE)
        if m_c:
            cust_name = m_c.group(1).strip()

    full_text = (message.content or "") + " " + raw_text
    is_upgrade = service_pricing.is_upgrade_message(full_text, amount)

    emp_name = resolve_employee_name(message.author)

    if is_upgrade:
        # Route to Car Upgrade sheet (capped at max ₹40,000)
        upgrade_amount = min(40000.0, amount) if (amount and amount > 0) else 40000.0
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

    await add_reaction_if_enabled(message, "✅")


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
    if not cust_name and message.content:
        m_c = re.search(r"(?:customer|client|name|billed to)\s*[:\-]\s*([^\n]+)", message.content, re.IGNORECASE)
        if m_c:
            cust_name = m_c.group(1).strip()

    full_text = (message.content or "") + " " + raw_text
    qty = kit_pricing.parse_kit_quantities(full_text)
    if qty is None:
        amt = parsed.get("amount") or parse_text_amount(full_text)
        if amt and amt > 0:
            est_rk = max(1, int(round(amt / 1000.0)))
            qty = {"rk": est_rk, "ck": 0}
        else:
            qty = {"rk": 1, "ck": 0}

    total, discount_pct, total_kits, rk_sub, ck_sub = kit_pricing.calculate_kit_total(qty["rk"], qty["ck"])
    amt_parsed = parsed.get("amount") or parse_text_amount(full_text)
    if amt_parsed and amt_parsed > 0:
        total = float(amt_parsed)
    emp_name = resolve_employee_name(message.author)

    try:
        await asyncio.to_thread(
            sheets.append_kit_entry,
            rk_qty=qty["rk"],
            ck_qty=qty["ck"],
            discount_pct=discount_pct,
            total=total,
            employee=emp_name,
            message_id=str(message.id),
            created_at=message.created_at,
            customer=cust_name,
            skip_dashboard_update=is_backfill,
        )
        if rk_sub > 0:
            await asyncio.to_thread(sheets.append_transaction_entry, rk_sub, emp_name, "Repair Kit", created_at=message.created_at, skip_tracker_update=is_backfill)
        if ck_sub > 0:
            await asyncio.to_thread(sheets.append_transaction_entry, ck_sub, emp_name, "Cleaning Kit", created_at=message.created_at, skip_tracker_update=is_backfill)
    except Exception as e:
        logger.error(f"Failed to write Kit entry for message {message.id}: {e}")
        return

    if image_hash:
        processed_hashes.add(image_hash)
        save_processed_hashes(processed_hashes)

    await add_reaction_if_enabled(message, "✅")


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

    await add_reaction_if_enabled(message, "✅")


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
    amount = parsed.get("amount") or parse_text_amount(full_text) or 5000.0
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
        await asyncio.to_thread(
            sheets.append_transaction_entry,
            amount=amount,
            employee=emp_name,
            category="Expense / Bill",
            description="Bill Claim Expense",
            created_at=message.created_at,
            skip_tracker_update=is_backfill,
        )
    except Exception as e:
        logger.error(f"Failed to write Expense entry for message {message.id}: {e}")
        return

    await add_reaction_if_enabled(message, "✅")


async def route_invoice_message(message: discord.Message, is_backfill: bool = False):
    """Routes an incoming Discord message to the correct channel handler."""
    if message.author.bot:
        return

    ch_name = getattr(message.channel, "name", "")
    cfg, _ = config.get_channel_config(ch_name)
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


async def backfill_channel_history(limit=500):
    """Scans historical messages across all configured channels."""
    logger.info("[Backfill Scan] Scanning history across all configured channels...")

    for guild in bot.guilds:
        for channel in guild.text_channels:
            cfg, _ = config.get_channel_config(channel.name)
            if not cfg:
                continue
            try:
                async for message in channel.history(limit=limit, oldest_first=True):
                    await route_invoice_message(message, is_backfill=True)
            except Exception as e:
                logger.error(f"Backfill error on #{channel.name}: {e}")

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
    asyncio.create_task(backfill_channel_history(limit=500))


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    await route_invoice_message(message, is_backfill=False)
    await bot.process_commands(message)


@bot.command(name="rescan")
async def cmd_rescan(ctx):
    """Triggers channel history rescan silently."""
    asyncio.create_task(backfill_channel_history(limit=1000))


@bot.command(name="wipe")
async def cmd_wipe(ctx):
    """Wipes worksheets and rescans silently."""
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
