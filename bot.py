import json
import os
import asyncio
import datetime
import discord

from discord.ext import commands, tasks
from aiohttp import web

import config
import ocr
import sheets
import kit_pricing
import service_pricing

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


async def safe_add_reaction(message: discord.Message, emoji: str):
    """Silent no-op: disabled per requirement (no reactions added to Discord log messages)."""
    return


async def safe_reply(message: discord.Message, content: str):
    """Silent no-op: disabled per requirement (no bot reply messages sent for logs)."""
    return


def is_image_attachment(attachment: discord.Attachment) -> bool:
    """Checks if an attachment is an image via content_type or file extension."""
    if attachment.content_type and "image" in attachment.content_type:
        return True
    ext = os.path.splitext(attachment.filename.lower())[1]
    return ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


# ── Duplicate-image tracking (local JSON file) ──────────
def load_processed_hashes():
    if os.path.exists(config.PROCESSED_HASHES_FILE):
        try:
            with open(config.PROCESSED_HASHES_FILE, "r") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def save_processed_hashes(hashes):
    try:
        with open(config.PROCESSED_HASHES_FILE, "w") as f:
            json.dump(list(hashes), f)
    except Exception:
        pass


processed_hashes = load_processed_hashes()

def message_to_ist_str(msg: discord.Message) -> str:
    """Converts a Discord message's UTC created_at timestamp to IST formatted date-time string."""
    utc_dt = msg.created_at
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=datetime.timezone.utc)
    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    ist_dt = utc_dt.astimezone(ist_tz)
    return ist_dt.strftime("%Y-%m-%d %I:%M:%S %p")


GENERIC_SHEET_TO_TRANSACTION_CATEGORY = {
    "Upgrades": "Car UpGrade",
}


async def process_service_message(message: discord.Message, cfg: dict, is_backfill: bool = False, is_full_rescan: bool = False):
    """
    Processes invoices and logs for combined/service channels.
    """
    print(f"[process_service] msg_id={message.id} backfill={is_backfill} rescan={is_full_rescan} attachments={len(message.attachments)}")
    if is_backfill and not is_full_rescan:
        existing_reactions = {str(r.emoji) for r in message.reactions if r.me}
        if "✅" in existing_reactions or "🔁" in existing_reactions:
            return

    image_attachment = next(
        (a for a in message.attachments if is_image_attachment(a)),
        None,
    )

    image_hash = None
    parsed = {}

    if image_attachment:
        try:
            image_hash, parsed, _raw_text = await ocr.process_invoice_image(
                image_attachment.url, ["customer", "amount"]
            )
        except Exception as e:
            ocr.logger.error(f"OCR failed for service message {message.id}: {e}")

    if config.IGNORE_DUPLICATE_IMAGES and image_hash and image_hash in processed_hashes:
        await safe_add_reaction(message, "🔁")
        return

    customer = parsed.get("customer") if parsed else None
    amount = parsed.get("amount") if parsed else None

    # Fallback to extracting amount from message content if OCR couldn't extract it
    if amount is None and message.content:
        import re
        numbers = re.findall(r"\b\d{4,7}\b", message.content)
        if numbers:
            try:
                amount = float(numbers[0])
            except ValueError:
                pass

    keyword_category = service_pricing.parse_service_category(message.content)
    author_emp = config.resolve_employee_from_author(message.author)
    msg_ts = message_to_ist_str(message)

    # Route vehicle upgrade messages to Upgrades sheet
    if service_pricing.is_upgrade_message(message.content, amount) or keyword_category == "upgrade":
        upgrade_val = amount if (amount and amount > 0) else 0
        try:
            sheets.append_entry(
                sheet_name="Upgrades",
                customer=customer or "Unknown",
                value=upgrade_val,
                employee=author_emp,
                message_id=str(message.id),
                timestamp=msg_ts,
            )
            sheets.append_transaction_entry(upgrade_val, customer or "Car UpGrade", "Car UpGrade")
        except Exception as e:
            ocr.logger.error(f"Failed to log Upgrade entry for message {message.id}: {e}")
        if image_hash:
            processed_hashes.add(image_hash)
            save_processed_hashes(processed_hashes)
        await safe_add_reaction(message, "✅")
        return

    result = service_pricing.resolve_category_and_count(amount, keyword_category, message.content)
    service_total = result["total"]

    try:
        sheets.append_service_entry(
            customer=customer or "Unknown",
            category=result["category"],
            total=service_total,
            employee=author_emp,
            message_id=str(message.id),
            count=result["count"],
            timestamp=msg_ts,
        )
    except Exception as e:
        ocr.logger.error(f"Failed to write service entry for message {message.id}: {e}")
        if not is_backfill:
            await safe_reply(message, "Failed to save this service invoice to Google Sheets. Check bot logs.")
        return

    if image_hash:
        processed_hashes.add(image_hash)
        save_processed_hashes(processed_hashes)

    if result.get("confident", True) or service_total > 0:
        txn_category = "Service-Civilian" if result["category"] == "civilian" else "Service-Government"
        txn_description = f"{result['count']}x {result['category']}"
        try:
            sheets.append_transaction_entry(service_total, txn_description, txn_category)
        except Exception as e:
            ocr.logger.error(f"Failed to write Transactions entry for message {message.id}: {e}")

        await safe_add_reaction(message, "✅")
        if not is_backfill:
            times = f" x{result['count']}" if result["count"] and result["count"] > 1 else ""
            amt_str = f"₹{service_total:,.0f}"
            await safe_reply(
                message,
                f"Logged: {result['category']}{times} service = {amt_str}"
            )
        return

    await safe_add_reaction(message, "❓")
    if not is_backfill:
        await safe_reply(message, "Logged as 'Unspecified' for now — please verify invoice amount or category.")


async def process_kit_message(message: discord.Message, cfg: dict, is_backfill: bool = False, is_full_rescan: bool = False):
    """
    Processes kit sales where player types quantities shorthand in text OR attaches an invoice image screenshot.
    """
    if is_backfill and not is_full_rescan:
        existing_reactions = {str(r.emoji) for r in message.reactions if r.me}
        if "✅" in existing_reactions or "🔁" in existing_reactions:
            return

    qty = kit_pricing.parse_kit_quantities(message.content)

    image_attachment = next(
        (a for a in message.attachments if is_image_attachment(a)),
        None,
    )

    image_hash, parsed = None, {"customer": None, "amount": None}
    if image_attachment:
        try:
            image_hash, parsed, _raw_text = await ocr.process_invoice_image(
                image_attachment.url, ["customer", "amount"]
            )
        except Exception as e:
            ocr.logger.error(f"OCR failed for kit message {message.id}: {e}")

    if config.IGNORE_DUPLICATE_IMAGES and image_hash and image_hash in processed_hashes:
        await safe_add_reaction(message, "🔁")
        return

    amount = parsed.get("amount") if parsed else None

    # Fallback to extracting amount from message content text if OCR missed it
    if amount is None and message.content:
        import re
        numbers = re.findall(r"\b\d{4,7}\b", message.content)
        if numbers:
            try:
                amount = float(numbers[0])
            except ValueError:
                pass

    if qty is None and amount is not None and amount > 0:
        rk_unit = kit_pricing.KIT_PRICES.get("rk", 1000)
        ck_unit = kit_pricing.KIT_PRICES.get("ck", 900)
        rk_qty = int(amount // rk_unit)
        if rk_qty > 0:
            qty = {"rk": rk_qty, "ck": 0}
        else:
            qty = {"rk": 0, "ck": int(amount // ck_unit)}

    if qty is None:
        await safe_add_reaction(message, "❓")
        if not is_backfill:
            await safe_reply(
                message,
                "Couldn't find kit quantity or invoice amount in your message. "
                "Please include quantity (e.g. `each 10`, `rk 10`) or attach an invoice screenshot."
            )
        return

    total, discount, combined_qty, rk_subtotal, ck_subtotal = kit_pricing.calculate_kit_total(
        qty["rk"], qty["ck"]
    )
    if total <= 0 and amount and amount > 0:
        total = amount

    author_emp = config.resolve_employee_from_author(message.author)
    msg_ts = message_to_ist_str(message)

    try:
        sheets.append_kit_entry(
            customer=parsed.get("customer") if parsed else "Unknown",
            rk_qty=qty["rk"],
            ck_qty=qty["ck"],
            discount_pct=discount,
            total=total,
            employee=author_emp,
            message_id=str(message.id),
            timestamp=msg_ts,
        )
    except Exception as e:
        ocr.logger.error(f"Failed to write kit entry for message {message.id}: {e}")
        if not is_backfill:
            await safe_reply(message, "Failed to save this kit sale to Google Sheets. Check bot logs.")
        return

    if image_hash:
        processed_hashes.add(image_hash)
        save_processed_hashes(processed_hashes)

    try:
        if qty["rk"] > 0:
            sheets.append_transaction_entry(rk_subtotal or total, f"{qty['rk']}x", "Repair Kit")
        if qty["ck"] > 0:
            sheets.append_transaction_entry(ck_subtotal or total, f"{qty['ck']}x", "Cleaning Kit")
        if qty["rk"] == 0 and qty["ck"] == 0 and total > 0:
            sheets.append_transaction_entry(total, "Kit Sale", "Repair Kit")
    except Exception as e:
        ocr.logger.error(f"Failed to write Transactions entries for message {message.id}: {e}")

    await safe_add_reaction(message, "✅")
    if not is_backfill:
        await safe_reply(
            message,
            f"Logged: {qty['rk']}x Repair Kit + {qty['ck']}x Cleaning Kit = ₹{total:,.0f}"
        )


def resolve_message_channel_config(message: discord.Message):
    """Resolves channel config for text channels, threads, and archived threads.
    Priority: thread name > parent channel name > direct channel name.
    This ensures threads named 'Services' or 'Upgrades' inside aug-logs are routed correctly."""
    ch = message.channel
    channel_name = getattr(ch, "name", "")

    # 1. If this is a thread, check the thread name first (e.g. 'Services', 'Upgrades')
    parent = getattr(ch, "parent", None)
    if parent:
        # It's a thread — thread name takes priority for routing
        cfg, cfg_key = config.get_channel_config(channel_name)
        if cfg:
            print(f"[resolve] thread={channel_name!r} -> matched thread name key={cfg_key!r}")
            return cfg, cfg_key, channel_name

        # Thread name didn't match — fall back to parent channel name
        parent_name = getattr(parent, "name", "")
        cfg, cfg_key = config.get_channel_config(parent_name)
        if cfg:
            print(f"[resolve] thread={channel_name!r} -> fallback to parent={parent_name!r} key={cfg_key!r}")
            return cfg, cfg_key, parent_name

        return None, None, channel_name

    # 2. Direct text channel (not a thread)
    cfg, cfg_key = config.get_channel_config(channel_name)
    if cfg:
        return cfg, cfg_key, channel_name

    return None, None, channel_name



async def process_invoice_message(message: discord.Message, channel_name: str, is_backfill: bool = False, is_full_rescan: bool = False):
    """Runs OCR + sheet logging for one message. Shared by on_message and startup history scan."""
    cfg, cfg_key, _ = resolve_message_channel_config(message)
    if not cfg:
        cfg, cfg_key = config.get_channel_config(channel_name)
    if not cfg:
        return

    cat = str(cfg.get("category", "")).lower()

    if cfg.get("kit_channel") or cat == "kit":
        await process_kit_message(message, cfg, is_backfill, is_full_rescan)
        return

    if cfg.get("combined_logs") or cfg.get("category_channel") or cat in ("combined", "service"):
        await process_service_message(message, cfg, is_backfill, is_full_rescan)
        return

    fields = cfg.get("fields", ["customer", "amount"])
    author_emp = config.resolve_employee_from_author(message.author)
    msg_ts = message_to_ist_str(message)

    # Handle text-only upgrade entries (messages without image attachments)
    if not message.attachments and message.content:
        import re
        numbers = re.findall(r"\b\d{4,7}\b", message.content)
        if numbers:
            try:
                upg_val = float(numbers[0])
                sheets.append_entry(
                    sheet_name=cfg.get("sheet_name", "Upgrades"),
                    customer="Unknown",
                    value=upg_val,
                    employee=author_emp,
                    message_id=str(message.id),
                    timestamp=msg_ts,
                )
                sheets.append_transaction_entry(upg_val, "Car UpGrade", "Car UpGrade", employee=author_emp)
                await safe_add_reaction(message, "✅")
                return
            except Exception:
                pass

    for attachment in message.attachments:
        if not is_image_attachment(attachment):
            continue

        if is_backfill and not is_full_rescan:
            existing_reactions = {str(r.emoji) for r in message.reactions if r.me}
            if "✅" in existing_reactions or "🔁" in existing_reactions:
                continue

        try:
            image_hash, parsed, raw_text = await ocr.process_invoice_image(
                attachment.url, fields
            )
        except Exception as e:
            ocr.logger.error(
                f"OCR failed for message {message.id} in #{channel_name} "
                f"({attachment.filename}): {e}"
            )
            if not is_backfill:
                await safe_reply(
                    message,
                    f"Couldn't read that invoice image (`{attachment.filename}`). "
                    f"Please re-upload a clearer screenshot."
                )
            continue

        if config.IGNORE_DUPLICATE_IMAGES and image_hash in processed_hashes:
            await safe_add_reaction(message, "🔁")
            continue

        customer = parsed.get("customer") if parsed else "Unknown"
        value = (parsed.get("amount") if "amount" in fields else parsed.get("quantity")) if parsed else 0
        value = value if value is not None else 0

        # Fallback to text number if OCR missed amount
        if value <= 0 and message.content:
            import re
            numbers = re.findall(r"\b\d{4,7}\b", message.content)
            if numbers:
                try:
                    value = float(numbers[0])
                except ValueError:
                    pass

        try:
            sheets.append_entry(
                sheet_name=cfg.get("sheet_name", "Transactions"),
                customer=customer,
                value=value,
                employee=author_emp,
                message_id=str(message.id),
                timestamp=msg_ts,
            )
        except Exception as e:
            ocr.logger.error(f"Failed to write to Google Sheets for message {message.id}: {e}")
            if not is_backfill:
                await safe_reply(message, "Failed to save this invoice to Google Sheets. Check bot logs.")
            continue

        processed_hashes.add(image_hash)
        save_processed_hashes(processed_hashes)

        txn_category = GENERIC_SHEET_TO_TRANSACTION_CATEGORY.get(cfg.get("sheet_name"))
        if txn_category:
            try:
                sheets.append_transaction_entry(value, customer or "Car UpGrade", txn_category, employee=author_emp)
            except Exception as e:
                ocr.logger.error(f"Failed to write Transactions entry for message {message.id}: {e}")

        await safe_add_reaction(message, "✅")
        if not is_backfill:
            await safe_reply(message, f"Logged {cfg.get('sheet_name', 'Invoice')}: ₹{value:,.0f}")


def get_logged_message_ids() -> set:
    """Fetches all Discord Message IDs already logged in Google Sheets (to avoid duplicate entries).

    Column layout (0-indexed):
      Service  : [Timestamp, Customer, Category, Count, Total Amount, Employee, Message ID]  → col 6
      Kits     : [Timestamp, Customer, RK Qty, CK Qty, Discount%, Total Amount, Employee, Message ID] → col 7
      Upgrades : [Timestamp, Customer, Total Amount, Employee, Message ID] → col 4
    """
    MSG_ID_COL = {"Service": 6, "Kits": 7, "Upgrades": 4}
    logged = set()
    try:
        ss = sheets.get_spreadsheet()
        for sheet_name in ["Service", "Kits", "Upgrades"]:
            try:
                ws = ss.worksheet(sheet_name)
                all_vals = ws.get_all_values()
                col = MSG_ID_COL[sheet_name]
                for row in all_vals[1:]:  # skip header
                    if len(row) > col and row[col].strip():
                        logged.add(row[col].strip())
            except Exception:
                pass
    except Exception:
        pass
    return logged


async def backfill_channel_history(channel, channel_name: str, limit: int = 500, is_full_rescan: bool = False):
    """Scans RECENT messages in a configured channel for invoice images or text logs missed while offline.
    Sorts messages in chronological order (Aug 01 -> Aug 08) before writing to Google Sheets."""
    scanned = 0
    # User directive: Scan and log ONLY August 2026 (Month 8) invoices
    cutoff = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
    existing_sheet_ids = set() if is_full_rescan else get_logged_message_ids()

    history_messages = []
    try:
        async for message in channel.history(limit=limit, oldest_first=False):
            if message.author.bot:
                continue

            if message.created_at < cutoff:
                break

            msg_id = str(message.id)
            if not is_full_rescan and msg_id in existing_sheet_ids:
                continue

            history_messages.append(message)
    except Exception as e:
        ocr.logger.error(f"Error reading channel history for #{channel_name}: {e}")

    # Sort messages chronologically (oldest first: Aug 01 -> Aug 08)
    history_messages.sort(key=lambda m: m.created_at)

    for message in history_messages:
        try:
            await process_invoice_message(message, channel_name, is_backfill=True, is_full_rescan=is_full_rescan)
            scanned += 1
            await asyncio.sleep(1.5)
        except Exception as e:
            ocr.logger.error(f"Error processing message {message.id} in #{channel_name}: {e}")

    return scanned


async def collect_target_channels(guild: discord.Guild):
    """Gathers every text channel, forum channel, AND thread in the guild matching configured invoice channels.
    Also collects threads inside matched parent channels (e.g. Services/Upgrades threads inside aug-logs)."""
    targets = []

    channels_to_check = list(guild.text_channels)
    if hasattr(guild, "forums"):
        channels_to_check.extend(guild.forums)

    for channel in channels_to_check:
        parent_cfg, _ = config.get_channel_config(channel.name)
        if parent_cfg and isinstance(channel, discord.TextChannel):
            targets.append(channel)

        for thread in getattr(channel, "threads", []):
            cfg_t, _ = config.get_channel_config(thread.name)
            if cfg_t or parent_cfg:
                if thread not in targets:
                    targets.append(thread)

        try:
            if hasattr(channel, "archived_threads"):
                async for thread in channel.archived_threads(limit=100):
                    cfg_t, _ = config.get_channel_config(thread.name)
                    if cfg_t or parent_cfg:
                        if thread not in targets:
                            targets.append(thread)
        except Exception:
            pass

    for thread in guild.threads:
        cfg_t, _ = config.get_channel_config(thread.name)
        parent = getattr(thread, "parent", None)
        parent_cfg2, _ = config.get_channel_config(getattr(parent, "name", "")) if parent else (None, None)
        if (cfg_t or parent_cfg2) and thread not in targets:
            targets.append(thread)

    return targets


@tasks.loop(seconds=30)
async def real_time_auto_scan_loop():
    """Background loop running every 30 seconds to catch and sync any missed Discord log messages in real-time.
    Dashboard is refreshed every cycle regardless of whether new messages were found, so daily/weekly/monthly
    totals stay current even during quiet periods.
    Also checks for wipe_trigger.flag and rescan_trigger.flag created by the web dashboard."""
    try:
        # Check for wipe/rescan signals from the web dashboard
        is_full_rescan = False
        if os.path.exists("wipe_trigger.flag"):
            print("[Auto-Scan] Wipe trigger detected — clearing bot caches and processed hashes...")
            # Clear in-memory caches in the bot process
            with sheets._CACHE_LOCK:
                sheets._ROWS_CACHE.clear()
                sheets._LAST_KNOWN_ROWS.clear()
                sheets._save_disk_cache()
            # Clear processed image hashes so messages aren't skipped as duplicates
            global processed_hashes
            processed_hashes.clear()
            save_processed_hashes(processed_hashes)
            try:
                os.remove("wipe_trigger.flag")
            except Exception:
                pass
            is_full_rescan = True

        if os.path.exists("rescan_trigger.flag"):
            print("[Auto-Scan] Rescan trigger detected — starting full server rescan...")
            try:
                os.remove("rescan_trigger.flag")
            except Exception:
                pass
            is_full_rescan = True

        scan_limit = 500 if is_full_rescan else 50

        total_synced = 0
        for guild in bot.guilds:
            targets = await collect_target_channels(guild)
            for channel in targets:
                try:
                    cnt = await backfill_channel_history(channel, channel.name, limit=scan_limit, is_full_rescan=is_full_rescan)
                    total_synced += cnt
                except Exception:
                    pass

        # Always clear the in-memory row cache and refresh the dashboard so
        # date-windowed totals (today/weekly/monthly) are always up to date.
        with sheets._CACHE_LOCK:
            sheets._ROWS_CACHE.clear()
        try:
            sheets.update_dashboard()
        except Exception as e:
            ocr.logger.error(f"Real-time auto-scan dashboard update error: {e}")

        if total_synced > 0 or is_full_rescan:
            print(f"[Real-Time Auto-Scan] {'Full rescan' if is_full_rescan else 'Auto-scan'}: synced {total_synced} message(s) to Google Sheets.")
    except Exception as e:
        ocr.logger.error(f"Real-time auto-scan loop error: {e}")


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    try:
        sheets.setup_all_sheets()
        print("Google Sheets ready.")
    except Exception as e:
        print(f"Warning: Google Sheets setup warning: {e}")

    # Clear any previously registered slash commands from Discord
    try:
        bot.tree.clear_commands(guild=None)
        await bot.tree.sync()
        print("Cleared all Discord Slash Commands.")
    except Exception as e:
        print(f"Warning: Could not clear Slash Commands: {e}")

    print("Scanning configured channels/threads for invoices missed while offline...")
    for guild in bot.guilds:
        targets = await collect_target_channels(guild)
        for channel in targets:
            channel_name = channel.name
            try:
                count = await backfill_channel_history(channel, channel_name)
                print(f"  #{channel.name}: scanned {count} message(s).")
            except discord.Forbidden:
                print(f"  #{channel.name}: missing permission to read history, skipped.")
            except Exception as e:
                print(f"  #{channel.name}: error during backfill scan: {e}")

    with sheets._CACHE_LOCK:
        sheets._ROWS_CACHE.clear()
    sheets.update_dashboard()
    print("Backfill scan complete.")

    if not real_time_auto_scan_loop.is_running():
        real_time_auto_scan_loop.start()
        print("[Real-Time Auto-Scan] Active (30s interval auto-sync enabled).")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    await bot.process_commands(message)

    channel_name = getattr(message.channel, "name", "??")
    print(f"[on_message] #{channel_name} | author={message.author} | attachments={len(message.attachments)} | content={message.content[:60]!r}")

    cfg, cfg_key, ch_name = resolve_message_channel_config(message)
    if cfg is None:
        print(f"[on_message] #{channel_name} -> no channel config match, ignoring.")
        return

    print(f"[on_message] #{channel_name} -> matched config key={ch_name!r}, processing...")
    await process_invoice_message(message, ch_name, is_backfill=False)

    with sheets._CACHE_LOCK:
        sheets._ROWS_CACHE.clear()


async def start_web_server():
    """Lightweight web server for standalone bot deployment.
    If running inside start_all.py alongside monitor_app, Flask handles the web port."""
    if os.getenv("RUNNING_IN_START_ALL") == "1":
        print("[Bot] Web server port handled by monitor_app in start_all.py.")
        return

    app = web.Application()

    async def health_check(request):
        return web.Response(text="Jiraiya Bot is online and operational!", status=200)

    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    try:
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        print(f"Keep-alive web server listening on port {port}")
    except Exception as e:
        print(f"[Bot Warning] Web server port {port} unavailable (handled by parent service): {e}")


async def main():
    token = config.DISCORD_TOKEN
    try:
        await start_web_server()
    except Exception as e:
        print(f"Warning: Could not start web server: {e}")

    if not token or token == "YOUR_DISCORD_BOT_TOKEN":
        print("ERROR: DISCORD_TOKEN is missing or not set!")
        if os.getenv("RUNNING_IN_START_ALL") == "1":
            print("[Bot] Waiting for DISCORD_TOKEN to be configured in Render Environment Variables...")
            while True:
                await asyncio.sleep(3600)
        return

    try:
        async with bot:
            await bot.start(token)
    except discord.LoginFailure:
        print("\n" + "="*70)
        print("ERROR: DISCORD LOGIN FAILED! The DISCORD_TOKEN is invalid or revoked.")
        print("Please reset your bot token in Discord Developer Portal and update DISCORD_TOKEN in Render Environment Variables.")
        print("="*70 + "\n")
        if os.getenv("RUNNING_IN_START_ALL") == "1":
            while True:
                await asyncio.sleep(3600)
    except Exception as e:
        print(f"ERROR starting bot: {e}")
        if os.getenv("RUNNING_IN_START_ALL") == "1":
            while True:
                await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
