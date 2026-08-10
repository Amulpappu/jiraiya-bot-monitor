import config

names = [
    "\U0001f300\u2506aug-\u029f\u1d0f\u0262\ua731",  # 🌀┆aug-ʟᴏɢꜱ
    "\U0001f9f0\u2506aug-\u1d0b\u026a\u1d1b\ua731",  # 🧰┆aug-ᴋɪᴛꜱ
    "Services",
    "upgrades",
    "random-channel",
]
for name in names:
    cfg, key = config.get_channel_config(name)
    matched = "YES" if cfg else "NO"
    safe_name = name.encode("ascii", errors="replace").decode()
    print(f"{safe_name!r} -> matched={matched} key={key!r}")
