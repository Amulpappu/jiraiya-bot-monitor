import json
import os
import asyncio
import discord
from discord.ext import commands
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
    """Safely adds a reaction without crashing if permissions are missing."""
    try:
        await message.add_reaction(emoji)
    except Exception as e:
        ocr.logger.warning(f"Could not add reaction '{emoji}' to msg {message.id}: {e}")


async def safe_reply(message: discord.Message, content: str):
    """Safely sends a message reply without crashing if permissions are missing."""
    try:
        await message.reply(content)
    except Exception as e:
        ocr.logger.warning(f"Could not send reply to msg {message.id}: {e}")


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
        if existing_reactions & {"✅", "🔁", "❓"}:
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

    if result.get("confident", True):
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
    Processes kit sales where player types quantities shorthand in text alongside invoice image.
    """
    if is_backfill:
        existing_reactions = {str(r.emoji) for r in message.reactions if r.me}
        if existing_reactions & {"✅", "🔁", "❓"}:
            return

    qty = kit_pricing.parse_kit_quantities(message.content)
    if qty is None:
        await safe_add_reaction(message, "❓")
        if not is_backfill:
            await safe_reply(
                message,
                "Couldn't find a kit quantity in your message (e.g. `each 10`, "
                "`100 each`, `rk 10`, or `10 rk`). Please resend with quantity included."
            )
        return

    image_attachment = next(
        (a for a in message.attachments if is_image_attachment(a)),
        None,
    )

    image_hash, parsed = None, {"customer": None}
    if image_attachment:
        try:
            image_hash, parsed, _raw_text = await ocr.process_invoice_image(
                image_attachment.url, ["customer"]
            )
        except Exception as e:
            ocr.logger.error(f"OCR failed for kit message {message.id}: {e}")

    if config.IGNORE_DUPLICATE_IMAGES and image_hash and image_hash in processed_hashes:
        await safe_add_reaction(message, "🔁")
        return

    total, discount, combined_qty, rk_subtotal, ck_subtotal = kit_pricing.calculate_kit_total(
        qty["rk"], qty["ck"]
    )

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
            sheets.append_transaction_entry(rk_subtotal, f"{qty['rk']}x", "Repair Kit")
        if qty["ck"] > 0:
            sheets.append_transaction_entry(ck_subtotal, f"{qty['ck']}x", "Cleaning Kit")
    except Exception as e:
        ocr.logger.error(f"Failed to write Transactions entries for message {message.id}: {e}")

    await safe_add_reaction(message, "✅")
    if not is_backfill:
        await safe_reply(
            message,
            f"Logged: {qty['rk']}x Repair Kit + {qty['ck']}x Cleaning Kit "
            f"(combined {combined_qty}, {int(discount * 100)}% discount) = ₹{total:,.0f}"
        )


async def process_invoice_message(message: discord.Message, channel_name: str, is_backfill: bool = False):
    """Runs OCR + sheet logging for one message. Shared by on_message and startup history scan."""
    cfg, _ = config.get_channel_config(channel_name)
    if not cfg:
        cfg = config.CHANNEL_CONFIG.get(channel_name)
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
            if existing_reactions & {"✅", "🔁"}:
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


async def backfill_channel_history(channel, channel_name: str, limit: int = 1000):
    """Scans past messages in a configured channel for invoice images the bot never got to react to."""
    scanned = 0
    async for message in channel.history(limit=limit, oldest_first=True):
        if message.author.bot or not message.attachments:
            continue
        await process_invoice_message(message, channel_name, is_backfill=True)
        scanned += 1
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


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    try:
        sheets.setup_all_sheets()
        print("Google Sheets ready.")
    except Exception as e:
        print(f"Warning: Google Sheets setup warning: {e}")

    print("Scanning configured channels/threads for invoices missed while offline...")
    for guild in bot.guilds:
        targets = await collect_target_channels(guild)
        for channel in targets:
            channel_name = channel.name
            try:
                count = await backfill_channel_history(channel, channel_name)
                print(f"  #{channel.name}: scanned {count} message(s) with attachments.")
            except discord.Forbidden:
                print(f"  #{channel.name}: missing permission to read history, skipped.")
            except Exception as e:
                print(f"  #{channel.name}: error during backfill scan: {e}")
    print("Backfill scan complete.")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    await bot.process_commands(message)

    channel_name = getattr(message.channel, "name", None)
    if channel_name is None:
        return

    cfg, cfg_key = config.get_channel_config(channel_name)
    if cfg is None:
        return

    if not message.attachments:
        # Check if text-only kit or service message
        cat = str(cfg.get("category", "")).lower()
        if cfg.get("kit_channel") or cat == "kit":
            if kit_pricing.parse_kit_quantities(message.content):
                await process_invoice_message(message, cfg_key, is_backfill=False)
        return

    await process_invoice_message(message, cfg_key, is_backfill=False)


async def start_web_server():
    """Lightweight web server to satisfy Render's HTTP port check & keep bot alive."""
    app = web.Application()

    async def health_check(request):
        return web.Response(text="Jiraiya Bot is online and operational!", status=200)

    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Keep-alive web server listening on port {port}")


async def main():
    token = config.DISCORD_TOKEN
    if not token or token == "YOUR_DISCORD_BOT_TOKEN":
        print("ERROR: DISCORD_TOKEN is missing or not set!")
        return

    try:
        await start_web_server()
    except Exception as e:
        print(f"Warning: Could not start web server: {e}")

    try:
        async with bot:
            await bot.start(token)
    except discord.LoginFailure:
        print("\n" + "="*70)
        print("ERROR: DISCORD LOGIN FAILED! The DISCORD_TOKEN is invalid or revoked.")
        print("Please reset your bot token in Discord Developer Portal and update DISCORD_TOKEN in Render Environment Variables.")
        print("="*70 + "\n")
    except Exception as e:
        print(f"ERROR starting bot: {e}")


if __name__ == "__main__":
    asyncio.run(main())
