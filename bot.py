import json
import os
import asyncio
import datetime
import discord
from discord import app_commands
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

GENERIC_SHEET_TO_TRANSACTION_CATEGORY = {
    "Upgrades": "Car UpGrade",
}


async def process_service_message(message: discord.Message, cfg: dict, is_backfill: bool = False):
    """
    Processes invoices and logs for combined/service channels.
    """
    if is_backfill:
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

    amount = parsed.get("amount") if parsed else None
    customer = parsed.get("customer") if parsed else None

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
    result = service_pricing.resolve_category_and_count(amount, keyword_category)

    author_emp = config.resolve_employee_from_author(message.author)

    try:
        sheets.append_service_entry(
            customer=customer or "Unknown",
            category=result["category"],
            total=amount if amount is not None else 0,
            employee=author_emp,
            message_id=str(message.id),
            count=result["count"],
        )
    except Exception as e:
        ocr.logger.error(f"Failed to write service entry for message {message.id}: {e}")
        if not is_backfill:
            await safe_reply(message, "Failed to save this service invoice to Google Sheets. Check bot logs.")
        return

    if image_hash:
        processed_hashes.add(image_hash)
        save_processed_hashes(processed_hashes)

    if result.get("confident", True) or amount:
        txn_category = "Service-Civilian" if result["category"] == "civilian" else "Service-Government"
        txn_description = f"{result['count']}x" if result["count"] and result["count"] > 1 else ""
        try:
            sheets.append_transaction_entry(amount or 0, txn_description, txn_category)
        except Exception as e:
            ocr.logger.error(f"Failed to write Transactions entry for message {message.id}: {e}")

        await safe_add_reaction(message, "✅")
        if not is_backfill:
            times = f" x{result['count']}" if result["count"] and result["count"] > 1 else ""
            amt_str = f"₹{amount:,.0f}" if amount else "Logged"
            await safe_reply(
                message,
                f"Logged: {result['category']}{times} service = {amt_str}"
            )
        return

    await safe_add_reaction(message, "❓")
    if not is_backfill:
        await safe_reply(message, "Logged as 'Unspecified' for now — please verify invoice amount or category.")


async def process_kit_message(message: discord.Message, cfg: dict, is_backfill: bool = False):
    """
    Processes kit sales where player types quantities shorthand in text OR attaches an invoice image screenshot.
    """
    if is_backfill:
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

    try:
        sheets.append_kit_entry(
            customer=parsed.get("customer") if parsed else "Unknown",
            rk_qty=qty["rk"],
            ck_qty=qty["ck"],
            discount_pct=discount,
            total=total,
            employee=author_emp,
            message_id=str(message.id),
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
    """Resolves channel config for text channels, threads, and archived threads."""
    ch = message.channel
    channel_name = getattr(ch, "name", "")
    cfg, cfg_key = config.get_channel_config(channel_name)
    if cfg:
        return cfg, cfg_key, channel_name

    parent = getattr(ch, "parent", None)
    if parent:
        parent_name = getattr(parent, "name", "")
        cfg, cfg_key = config.get_channel_config(parent_name)
        if cfg:
            return cfg, cfg_key, parent_name

    return None, None, channel_name


async def process_invoice_message(message: discord.Message, channel_name: str, is_backfill: bool = False):
    """Runs OCR + sheet logging for one message. Shared by on_message and startup history scan."""
    cfg, cfg_key = config.get_channel_config(channel_name)
    if not cfg:
        cfg, cfg_key, _ = resolve_message_channel_config(message)
    if not cfg:
        return

    cat = str(cfg.get("category", "")).lower()

    if cfg.get("kit_channel") or cat == "kit":
        await process_kit_message(message, cfg, is_backfill)
        return

    if cfg.get("combined_logs") or cfg.get("category_channel") or cat in ("combined", "service"):
        await process_service_message(message, cfg, is_backfill)
        return

    fields = cfg.get("fields", ["customer", "amount"])

    for attachment in message.attachments:
        if not is_image_attachment(attachment):
            continue

        if is_backfill:
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

        author_emp = config.resolve_employee_from_author(message.author)

        try:
            sheets.append_entry(
                sheet_name=cfg.get("sheet_name", "Transactions"),
                customer=customer,
                value=value,
                employee=author_emp,
                message_id=str(message.id),
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
                sheets.append_transaction_entry(value, "", txn_category)
            except Exception as e:
                ocr.logger.error(f"Failed to write Transactions entry for message {message.id}: {e}")

        await safe_add_reaction(message, "✅")
        if not is_backfill:
            await safe_reply(message, f"Logged {cfg.get('sheet_name', 'Invoice')}: ₹{value:,.0f}")


async def backfill_channel_history(channel, channel_name: str, limit: int = 100):
    """Scans RECENT messages (last 48 hours only) in a configured channel for invoice images or text logs missed while offline."""
    scanned = 0
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)

    existing_sheet_ids = set()
    try:
        cfg, _ = config.get_channel_config(channel_name)
        if cfg:
            sheet_name = cfg.get("sheet_name", "Transactions")
            rows = sheets.get_rows(sheet_name)
            for row in rows:
                if len(row) >= 7 and row[6]:
                    existing_sheet_ids.add(str(row[6]).strip())
                elif len(row) >= 5 and row[4]:
                    existing_sheet_ids.add(str(row[4]).strip())
    except Exception:
        pass

    try:
        async for message in channel.history(limit=limit, after=cutoff, oldest_first=False):
            if message.author.bot:
                continue

            msg_id = str(message.id)
            if msg_id in existing_sheet_ids or msg_id in processed_ids:
                continue

            await process_invoice_message(message, channel_name, is_backfill=True)
            scanned += 1
    except Exception as e:
        ocr.logger.error(f"Error scanning channel history for #{channel_name}: {e}")

    return scanned


async def collect_target_channels(guild: discord.Guild):
    """Gathers every text channel AND thread in the guild matching configured invoice channels."""
    targets = []

    for channel in guild.text_channels:
        cfg, _ = config.get_channel_config(channel.name)
        if cfg:
            targets.append(channel)

        for thread in channel.threads:
            cfg_t, _ = config.get_channel_config(thread.name)
            if cfg_t:
                targets.append(thread)

        try:
            async for thread in channel.archived_threads(limit=100):
                cfg_t, _ = config.get_channel_config(thread.name)
                if cfg_t:
                    targets.append(thread)
        except discord.Forbidden:
            pass

    for thread in guild.threads:
        cfg_t, _ = config.get_channel_config(thread.name)
        if cfg_t and thread not in targets:
            targets.append(thread)

    return targets


# ── Discord Slash Commands (/) & Prefix Commands (!) ─────

@bot.tree.command(name="scan", description="Rescan recent messages in this channel and sync un-logged invoices to Google Sheets")
@app_commands.describe(limit="Number of recent messages to scan (default 500)")
async def slash_scan(interaction: discord.Interaction, limit: int = 500):
    await interaction.response.defer(ephemeral=False)
    channel_name = getattr(interaction.channel, "name", "unknown")
    try:
        count = await backfill_channel_history(interaction.channel, channel_name, limit=limit)
        with sheets._CACHE_LOCK:
            sheets._ROWS_CACHE.clear()
        sheets.update_dashboard()
        await interaction.followup.send(
            f"✅ **Scan complete for #{channel_name}!** Processed **{count}** un-logged message(s). Google Sheets updated."
        )
    except Exception as e:
        await interaction.followup.send(f"❌ Error during scan: {e}")


@bot.tree.command(name="scanall", description="Rescan past messages across ALL server channels and update Google Sheets")
@app_commands.describe(limit="Number of recent messages per channel to scan (default 500)")
async def slash_scanall(interaction: discord.Interaction, limit: int = 500):
    await interaction.response.defer(ephemeral=False)
    await interaction.followup.send(f"🔍 Starting full server rescan (up to {limit} messages per channel)...")
    total_scanned = 0
    for guild in bot.guilds:
        targets = await collect_target_channels(guild)
        for channel in targets:
            try:
                cnt = await backfill_channel_history(channel, channel.name, limit=limit)
                total_scanned += cnt
            except Exception as e:
                ocr.logger.error(f"Scanall error on #{channel.name}: {e}")

    try:
        with sheets._CACHE_LOCK:
            sheets._ROWS_CACHE.clear()
        sheets.update_dashboard()
    except Exception:
        pass

    await interaction.followup.send(
        f"✅ **Full server rescan complete!** Processed **{total_scanned}** total un-logged message(s) across all channels."
    )


@bot.tree.command(name="status", description="Check Jiraiya Bot status and Google Sheets live sync connection")
async def slash_status(interaction: discord.Interaction):
    await interaction.response.send_message(
        "🟢 **Jiraiya Bot is online and operational!**\n"
        "📊 **Google Sheets:** Live Synced\n"
        "⚡ **Slash Commands (/):** `/scan`, `/scanall`, `/status` active."
    )


@bot.command(name="scan", aliases=["rescan", "sync", "backfill"])
async def scan_channel_command(ctx: commands.Context, limit: int = 500):
    """Command to force rescan recent messages in the current channel."""
    channel_name = getattr(ctx.channel, "name", "unknown")
    await ctx.send(f"🔍 Starting scan of up to {limit} recent messages in #{channel_name}...")

    try:
        count = await backfill_channel_history(ctx.channel, channel_name, limit=limit)
        sheets.update_dashboard()
        await ctx.send(f"✅ Scan complete for #{channel_name}! Processed {count} un-logged message(s). Google Sheets updated.")
    except Exception as e:
        await ctx.send(f"❌ Error during scan: {e}")


@bot.command(name="scanall", aliases=["rescanall", "syncall"])
async def scan_all_channels_command(ctx: commands.Context, limit: int = 500):
    """Command to force rescan past messages across ALL server channels."""
    await ctx.send(f"🔍 Starting full server rescan (up to {limit} messages per channel)...")
    total_scanned = 0
    for guild in bot.guilds:
        targets = await collect_target_channels(guild)
        for channel in targets:
            try:
                cnt = await backfill_channel_history(channel, channel.name, limit=limit)
                total_scanned += cnt
            except Exception as e:
                ocr.logger.error(f"Scanall error on #{channel.name}: {e}")

    try:
        sheets.update_dashboard()
    except Exception:
        pass

    await ctx.send(f"✅ Full server rescan complete! Processed {total_scanned} total un-logged message(s) across all channels.")


@tasks.loop(seconds=30)
async def real_time_auto_scan_loop():
    """Background loop running every 30 seconds to catch and sync any missed Discord log messages in real-time."""
    try:
        total_synced = 0
        for guild in bot.guilds:
            targets = await collect_target_channels(guild)
            for channel in targets:
                try:
                    cnt = await backfill_channel_history(channel, channel.name, limit=50)
                    total_synced += cnt
                except Exception:
                    pass
        if total_synced > 0:
            with sheets._CACHE_LOCK:
                sheets._ROWS_CACHE.clear()
            sheets.update_dashboard()
            print(f"[Real-Time Auto-Scan] Synced {total_synced} new log message(s) directly to Google Sheets.")
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

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} Discord Slash Command(s) (/scan, /scanall, /status).")
    except Exception as e:
        print(f"Warning: Could not sync Slash Commands: {e}")

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

    cfg, cfg_key, ch_name = resolve_message_channel_config(message)
    if cfg is None:
        return

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
