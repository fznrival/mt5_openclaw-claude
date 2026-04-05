#!/usr/bin/env python3
"""
position_monitor.py
===================
Monitor posisi open di MT5 dan kirim update P&L ke Telegram.
Dijalankan via cron setiap 30 menit untuk update status posisi aktif.

Author  : fznrival
Project : MT5 + OpenClaw Full Automated Trading System
"""

import os
import sys
import json
import logging
import requests
from datetime import datetime
from pathlib import Path

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("/tmp/position_monitor.log")],
)
log = logging.getLogger(__name__)

CONFIG_PATH = Path.home() / ".openclaw" / "trade_config.json"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def send_telegram(token, chat_id, text):
    if not token or token == "YOUR_BOT_TOKEN_HERE":
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        log.error("Telegram error: %s", e)


def monitor_positions():
    cfg     = load_config()
    token   = cfg.get("telegram_bot_token", "")
    chat_id = cfg.get("telegram_chat_id", "")
    magic   = cfg.get("trading", {}).get("magic_number", 2022001)
    currency = cfg.get("currency", "USD")

    if not MT5_AVAILABLE:
        log.error("MT5 tidak tersedia.")
        return

    if not mt5.initialize():
        log.error("Gagal konek MT5: %s", mt5.last_error())
        return

    positions = mt5.positions_get()
    now_str   = datetime.now().strftime("%d %b %Y, %H:%M WIB")

    if not positions:
        log.info("Tidak ada posisi open saat ini.")
        mt5.shutdown()
        return

    # Filter by magic number
    my_positions = [p for p in positions if p.magic == magic]

    if not my_positions:
        log.info("Tidak ada posisi open dari bot ini (magic=%d).", magic)
        mt5.shutdown()
        return

    # Build message
    total_profit = sum(p.profit for p in my_positions)
    pnl_emoji    = "🟢" if total_profit >= 0 else "🔴"

    lines = [
        f"📊 *POSISI OPEN — {now_str}*",
        f"{'─' * 28}",
        "",
    ]

    for p in my_positions:
        direction  = "BUY 🟢" if p.type == 0 else "SELL 🔴"
        pnl_sign   = "+" if p.profit >= 0 else ""
        open_time  = datetime.fromtimestamp(p.time).strftime("%d/%m %H:%M")
        lines.append(
            f"📌 *{p.symbol}* — {direction}\n"
            f"  Entry    : `{p.price_open}`\n"
            f"  Current  : `{p.price_current}`\n"
            f"  SL / TP  : `{p.sl}` / `{p.tp}`\n"
            f"  Lot      : `{p.volume}`\n"
            f"  P&L      : `{pnl_sign}{p.profit:.2f} {currency}`\n"
            f"  Opened   : `{open_time}`\n"
        )

    lines += [
        f"{'─' * 28}",
        f"{pnl_emoji} *Total Floating P&L :* `{'+' if total_profit >= 0 else ''}{total_profit:.2f} {currency}`",
        f"",
        f"_Posisi aktif: {len(my_positions)}_",
    ]

    msg = "\n".join(lines)
    print(msg)
    send_telegram(token, chat_id, msg)

    mt5.shutdown()
    log.info("Monitor selesai. %d posisi aktif.", len(my_positions))


if __name__ == "__main__":
    monitor_positions()
