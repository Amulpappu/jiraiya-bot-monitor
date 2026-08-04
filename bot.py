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


def is_image_attachment(attachment: discord.Attachment) -> bool:
    """Checks if an attachment is an image via content_type or file extension."""
    if attachment.content_type and "image" in attachment.content_type:
        return True
    ext = os.path.splitext(attachment.filename.lower())[1]
    return ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


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

    if is_backfill:
        existing_reactions = {str(r.emoji) for r in message.reactions if r.me}
        if existing_reactions & {"✅", "🔁", "❓"}:
            return

    image_attachment = next(
        (a for a in message.attachments if is_image_attachment(a)),
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
        await message.add_reaction("❓")
        if not is_backfill:
            await message.reply(
                "Couldn't read the invoice image, so I can't work out the category "
                "or amount. Please resend a clearer screenshot."
            )
        return

    if config.IGNORE_DUPLICATE_IMAGES and image_hash and image_hash in processed_hashes:
        await message.add_reaction("🔁")
        return

    amount = parsed.get("amount")
    keyword_category = service_pricing.parse_service_category(message.content)
    result = service_pricing.resolve_category_and_count(amount, keyword_category)

    try:
        sheets.append_service_entry(
            customer=parsed.get("customer"),
            category=result["category"],
            total=amount if amount is not None else 0,
            employee=str(message.author),
            message_id=str(message.id),
            count=result["count"],
        )
    except Exception as e:
        ocr.logger.error(f"Failed to write service entry for message {message.id}: {e}")
        if not is_backfill:
            await message.reply("Failed to save this service invoice to Google Sheets. Check bot logs.")
        return

    if image_hash:
        processed_hashes.add(image_hash)
        save_processed_hashes(processed_hashes)

    if result["confident"]:
        # Map the specific category to the two buckets the in-game
        # Transactions dropdown actually has.
        txn_category = "Service-Civilian" if result["category"] == "civilian" else "Service-Government"
        txn_description = f"{result['count']}x" if result["count"] and result["count"] > 1 else ""
        try:
            sheets.append_transaction_entry(amount, txn_description, txn_category)
        except Exception as e:
            ocr.logger.error(f"Failed to write Transactions entry for message {message.id}: {e}")

        await message.add_reaction("✅")
        if not is_backfill:
            times = f" x{result['count']}" if result["count"] and result["count"] > 1 else ""
            await message.reply(
                f"Logged: {result['category']}{times} service = ₹{amount:,.0f}"
            )
        return

    # ── Not confident — flag for manual review, but still logged so nothing gets lost ──
    await message.add_reaction("❓")
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

    await message.reply(f"Logged as 'Unspecified' for now — {note}")


async def process_kit_message(message: discord.Message, cfg: dict, is_backfill: bool = False):
    """
    For the kit channels: the player types the RK/CK quantity as text
    alongside the invoice screenshot (e.g. "each 10", "100 each", "1x rk, ck").
    """
    if not message.attachments:
        return

    if is_backfill:
        existing_reactions = {str(r.emoji) for r in message.reactions if r.me}
        if existing_reactions & {"✅", "🔁", "❓"}:
            return

    qty = kit_pricing.parse_kit_quantities(message.content)
    if qty is None:
        await message.add_reaction("❓")
        if not is_backfill:
            await message.reply(
                "Couldn't find a kit quantity in your message (e.g. `each 10`, "
                "`100 each`, `rk 10`, or `10 rk`). Please resend with the quantity included."
            )
        return

    image_attachment = next(
        (a for a in message.attachments if is_image_attachment(a)),
        None,
    )
    if image_attachment is None:
        return

    try:
        image_hash, parsed, _raw_text = await ocr.process_invoice_image(
            image_attachment.url, ["customer"]
        )
    except Exception as e:
        ocr.logger.error(f"OCR failed for kit message {message.id}: {e}")
        image_hash, parsed = None, {"customer": None}

    if config.IGNORE_DUPLICATE_IMAGES and image_hash and image_hash in processed_hashes:
        await message.add_reaction("🔁")
        return

    total, discount, combined_qty, rk_subtotal, ck_subtotal = kit_pricing.calculate_kit_total(
        qty["rk"], qty["ck"]
    )

    try:
        sheets.append_kit_entry(
            customer=parsed.get("customer"),
            rk_qty=qty["rk"],
            ck_qty=qty["ck"],
            discount_pct=discount,
            total=total,
            employee=str(message.author),
            message_id=str(message.id),
        )
    except Exception as e:
        ocr.logger.error(f"Failed to write kit entry for message {message.id}: {e}")
        if not is_backfill:
            await message.reply("Failed to save this kit sale to Google Sheets. Check bot logs.")
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

    await message.add_reaction("✅")
    if not is_backfill:
        await message.reply(
            f"Logged: {qty['rk']}x Repair Kit + {qty['ck']}x Cleaning Kit "
            f"(combined {combined_qty}, {int(discount * 100)}% discount) = ₹{total:,.0f}"
        )


async def process_invoice_message(message: discord.Message, channel_name: str, is_backfill: bool = False):
    """Runs OCR + sheet logging for one message's image attachments.
    Shared by on_message (live) and the startup history scan (backfill)."""
    cfg = config.CHANNEL_CONFIG[channel_name]

    if cfg.get("kit_channel"):
        await process_kit_message(message, cfg, is_backfill)
        return

    if cfg.get("category_channel"):
        await process_service_message(message, cfg, is_backfill)
        return

    for attachment in message.attachments:
        if not is_image_attachment(attachment):
            continue

        if is_backfill:
            existing_reactions = {str(r.emoji) for r in message.reactions if r.me}
            if existing_reactions & {"✅", "🔁"}:
                continue

        try:
            image_hash, parsed, raw_text = await ocr.process_invoice_image(
                attachment.url, cfg["fields"]
            )
        except Exception as e:
            ocr.logger.error(
                f"OCR failed for message {message.id} in #{channel_name} "
                f"({attachment.filename}): {e}"
            )
            if not is_backfill:
                await message.reply(
                    f"Couldn't read that invoice image (`{attachment.filename}`). "
                    f"Please re-upload a clearer screenshot."
                )
            continue

        if config.IGNORE_DUPLICATE_IMAGES and image_hash in processed_hashes:
            await message.add_reaction("🔁")
            continue

        customer = parsed.get("customer")
        missing = [k for k, v in parsed.items() if v is None]

        if missing:
            ocr.logger.warning(
                f"Missing fields {missing} for message {message.id} in #{channel_name}. "
                f"Raw OCR text: {raw_text!r}"
            )
            if not is_backfill:
                await message.reply(
                    f"Could only partially read that invoice - missing: "
                    f"{', '.join(missing)}. Logged with placeholder values, please verify "
                    f"in the {cfg['sheet_name']} sheet."
                )

        value = parsed.get("amount") if "amount" in cfg["fields"] else parsed.get("quantity")
        value = value if value is not None else 0

        try:
            sheets.append_entry(
                sheet_name=cfg["sheet_name"],
                customer=customer,
                value=value,
                employee=str(message.author),
                message_id=str(message.id),
            )
        except Exception as e:
            ocr.logger.error(
                f"Failed to write to Google Sheets for message {message.id}: {e}"
            )
            if not is_backfill:
                await message.reply("Failed to save this invoice to Google Sheets. Check bot logs.")
            continue

        processed_hashes.add(image_hash)
        save_processed_hashes(processed_hashes)

        txn_category = GENERIC_SHEET_TO_TRANSACTION_CATEGORY.get(cfg["sheet_name"])
        if txn_category:
            try:
                sheets.append_transaction_entry(value, "", txn_category)
            except Exception as e:
                ocr.logger.error(f"Failed to write Transactions entry for message {message.id}: {e}")

        await message.add_reaction("✅")


async def backfill_channel_history(channel, channel_name: str, limit: int = 1000):
    """Scans past messages in a configured channel for invoice images the bot
    never got to react to (e.g. posted while the bot was offline)."""
    scanned = 0
    async for message in channel.history(limit=limit, oldest_first=True):
        if message.author.bot or not message.attachments:
            continue
        await process_invoice_message(message, channel_name, is_backfill=True)
        scanned += 1
    return scanned


async def collect_target_channels(guild: discord.Guild):
    """Gathers every text channel AND thread (active + archived) in the guild
    whose name matches a configured invoice channel."""
    targets = []

    for channel in guild.text_channels:
        if channel.name.lower() in config.CHANNEL_CONFIG:
            targets.append(channel)

        for thread in channel.threads:
            if thread.name.lower() in config.CHANNEL_CONFIG:
                targets.append(thread)

        try:
            async for thread in channel.archived_threads(limit=100):
                if thread.name.lower() in config.CHANNEL_CONFIG:
                    targets.append(thread)
        except discord.Forbidden:
            pass

    for thread in guild.threads:
        if thread.name.lower() in config.CHANNEL_CONFIG and thread not in targets:
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
            channel_name = channel.name.lower()
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
    channel_name = channel_name.lower()
    if channel_name not in config.CHANNEL_CONFIG:
        return

    if not message.attachments:
        return

    await process_invoice_message(message, channel_name, is_backfill=False)


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
