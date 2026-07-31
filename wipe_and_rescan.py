import sys
import os
import asyncio
import re
import json

# Force immediate unbuffered UTF-8 logging output
os.environ["PYTHONUNBUFFERED"] = "1"
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import discord
from discord.ext import commands

import config
import ocr
import sheets

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

CATEGORY_ORDER = {
    "Service": 1,
    "Upgrades": 2,
    "Kits": 3,
    "VIP Claim": 4,
    "Expenses": 5
}
CATEGORY_LABELS = {
    1: "Service Logs (Category 1)",
    2: "Upgrade Logs (Category 2)",
    3: "Kit Logs (Category 3)",
    4: "VIP Claim Logs (Category 4)",
    5: "Expense / Bill Claim Logs (Category 5)"
}


def get_channel_priority_order(channel) -> int:
    cfg, _key, _name = bot_module.get_effective_channel_config(channel)
    if cfg:
        return CATEGORY_ORDER.get(cfg.get("sheet_name"), 99)
    return 99


import bot as bot_module


@bot.event
async def on_ready():
    print("=" * 70)
    print(f"[Wipe & Rescan Tool] Logged in as Discord Bot: {bot.user} (ID: {bot.user.id})")
    print(f"[Wipe & Rescan Tool] Connected to {len(bot.guilds)} Guild(s).")
    print("=" * 70)

    # 1. Reset local image hash deduplication cache
    print("\n[Step 1/4] Erasing local processed image hash cache...")
    bot_module.processed_hashes = set()
    if os.path.exists(config.PROCESSED_HASHES_FILE):
        try:
            with open(config.PROCESSED_HASHES_FILE, "w") as f:
                f.write("[]")
        except Exception as e:
            print(f"  Notice: Could not reset processed_images.json: {e}")
    print("  ✓ Local deduplication cache reset successfully.")

    # 2. Perform ultra-fast Google Sheets wipe & header setup
    print("\n[Step 2/4] Wiping Google Sheets (Service, Upgrades, Kits, Expenses, VIP Claim, Transactions, Dashboard, Employee Tracker)...")
    sheets._LOGGED_IDS_CACHE = set()
    sheets.clear_rows_cache(hard=True)
    try:
        sheets.wipe_all_data_sheets()
        print("  ✓ Google Sheets data wiped & fresh headers initialized successfully.")
    except Exception as e:
        print(f"  ❌ Error wiping Google Sheets: {e}")

    # 3. Collect and sort all target Discord channels by strict priority order
    print("\n[Step 3/4] Collecting target text channels and threads across server(s)...")
    all_targets = []
    for guild in bot.guilds:
        targets = await bot_module.collect_target_channels(guild)
        all_targets.extend(targets)

    # Group channels by category priority (1 to 5)
    channels_by_category = {1: [], 2: [], 3: [], 4: [], 5: []}
    for ch in all_targets:
        order = get_channel_priority_order(ch)
        if order in channels_by_category:
            if ch not in channels_by_category[order]:
                channels_by_category[order].append(ch)

    print(f"  ✓ Found {len(all_targets)} matching channels/threads across 5 priority categories.")

    # 4. Perform chronological (oldest to newest) order-wise scan for July 1 to July 31
    july_start = datetime.datetime(2026, 7, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
    august_start = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
    total_messages_processed = 0

    for cat_num in (1, 2, 3, 4, 5):
        cat_name = CATEGORY_LABELS.get(cat_num, f"Category {cat_num}")
        cat_channels = channels_by_category[cat_num]
        print(f"\n▶ [{cat_name}] Scanning {len(cat_channels)} channel(s)...")

        if not cat_channels:
            print("  (No channels found for this category)")
            continue

        for idx, channel in enumerate(cat_channels, start=1):
            ch_name = getattr(channel, "name", "channel")
            norm = config.normalize_channel_name(ch_name)
            clean_display_name = re.sub(r"[^\x20-\x7E]", "", norm).strip("┆| ") or ch_name

            print(f"   [{idx}/{len(cat_channels)}] Scanning #{clean_display_name} chronologically (July 1 -> July 31)...")
            count = 0
            try:
                async for message in channel.history(limit=None, after=july_start, before=august_start, oldest_first=True):
                    if message.author.bot:
                        continue

                    cfg, _key, effective_name = bot_module.get_effective_channel_config(channel)
                    if not cfg:
                        continue

                    img_urls = bot_module.extract_image_urls(message)
                    if not img_urls and not message.content and not cfg.get("expense_channel") and not cfg.get("vip_claim_channel"):
                        continue

                    await bot_module.process_invoice_message(message, effective_name, is_backfill=True)
                    count += 1
                    total_messages_processed += 1
                    await asyncio.sleep(0.02)

                print(f"      ✓ Finished #{clean_display_name}: {count} invoice message(s) logged.")
            except discord.Forbidden:
                print(f"      ❌ #{clean_display_name}: Missing permission to read channel history.")
            except Exception as e:
                print(f"      ❌ #{clean_display_name}: Error during scan: {e}")

    # 5. Final chronological sorting, sync & recalculations
    print("\n[Step 4/4] Sorting all Google Sheets chronologically (July 1 -> July 31) & updating July Summary & Dashboard...")
    try:
        sheets.sort_all_sheets_by_timestamp()
        sheets.force_refresh_all()
        sheets.update_employee_tracker()
        sheets.update_dashboard()
        sheets.update_july_summary()
        print("  ✓ Sheets sorted from July 1 to July 31 and July Summary & Dashboard updated successfully!")
    except Exception as e:
        print(f"  Notice during final sync: {e}")


    print("\n" + "=" * 70)
    print(f"🎉 [COMPLETE] FULL WIPE AND ORDER-WISE RE-SCAN FINISHED!")
    print(f"   Total Messages Processed & Logged: {total_messages_processed}")
    print("=" * 70 + "\n")

    await bot.close()


def main():
    token = config.DISCORD_TOKEN
    if not token or token == "YOUR_DISCORD_BOT_TOKEN":
        print("[Error] DISCORD_TOKEN is missing in config.py or .env!")
        return

    print("[Wipe & Rescan Tool] Starting Wipe & Sequential Order-Wise Re-Scan...")
    bot.run(token)


if __name__ == "__main__":
    main()
