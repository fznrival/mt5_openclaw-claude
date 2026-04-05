#!/usr/bin/env python3
"""
trade_summary.py
================
Baca trade log CSV dari MT5, hitung statistik trading (winrate, RR, PnL, dll),
lalu kirim summary ke Telegram.

Author  : fznrival
Project : MT5 + OpenClaw Trading Reporter
"""

import os
import sys
import csv
import json
import math
import logging
import requests
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional
from collections import defaultdict

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/tmp/trade_summary.log"),
    ],
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
CONFIG_PATH = Path.home() / ".openclaw" / "trade_config.json"

DEFAULT_CONFIG = {
    "telegram_bot_token": "YOUR_BOT_TOKEN_HERE",
    "telegram_chat_id": "YOUR_CHAT_ID_HERE",
    "csv_path": str(Path.home() / "mt5_data" / "trade_log.csv"),
    "account_balance": 1000.0,
    "currency": "USD",
    "risk_per_trade_pct": 1.0,
    "timezone_label": "WIB",
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        # merge dengan default agar key baru selalu ada
        return {**DEFAULT_CONFIG, **cfg}
    log.warning("Config tidak ditemukan, gunakan default. Edit: %s", CONFIG_PATH)
    return DEFAULT_CONFIG


def save_config(cfg: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    log.info("Config disimpan ke %s", CONFIG_PATH)


# ── CSV Reader ────────────────────────────────────────────────────────────────

def load_trades(csv_path: str) -> list[dict]:
    """Baca CSV dan kembalikan list of dict trade."""
    path = Path(csv_path)
    if not path.exists():
        log.warning("CSV tidak ditemukan: %s", csv_path)
        return []

    trades = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                trades.append({
                    "ticket":       row.get("ticket", ""),
                    "open_time":    _parse_dt(row.get("open_time", "")),
                    "close_time":   _parse_dt(row.get("close_time", "")),
                    "symbol":       row.get("symbol", "").upper(),
                    "type":         row.get("type", "").upper(),
                    "volume":       _f(row.get("volume", 0)),
                    "open_price":   _f(row.get("open_price", 0)),
                    "close_price":  _f(row.get("close_price", 0)),
                    "sl":           _f(row.get("sl", 0)),
                    "tp":           _f(row.get("tp", 0)),
                    "profit":       _f(row.get("profit", 0)),
                    "commission":   _f(row.get("commission", 0)),
                    "swap":         _f(row.get("swap", 0)),
                    "net_profit":   _f(row.get("net_profit", 0)),
                    "duration_min": int(_f(row.get("duration_min", 0))),
                    "rr_actual":    _f(row.get("rr_actual", 0)),
                    "session":      row.get("session", "Unknown"),
                    "comment":      row.get("comment", ""),
                })
            except Exception as e:
                log.debug("Skip row error: %s | %s", e, row)

    log.info("Loaded %d trades dari %s", len(trades), csv_path)
    return trades


def _parse_dt(s: str) -> Optional[datetime]:
    for fmt in ("%Y.%m.%d %H:%M", "%Y-%m-%d %H:%M", "%Y.%m.%d %H:%M:%S"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            pass
    return None


def _f(v) -> float:
    try:
        return float(str(v).replace(",", "."))
    except (ValueError, TypeError):
        return 0.0


# ── Filter by Period ──────────────────────────────────────────────────────────

def filter_trades(trades: list[dict], period: str = "today") -> list[dict]:
    """
    period: 'today' | 'week' | 'month' | 'all'
    """
    now = datetime.now()
    if period == "today":
        start = datetime.combine(date.today(), datetime.min.time())
        end   = now
    elif period == "week":
        start = datetime.combine(date.today() - timedelta(days=date.today().weekday()), datetime.min.time())
        end   = now
    elif period == "month":
        start = datetime.combine(date.today().replace(day=1), datetime.min.time())
        end   = now
    else:  # all
        return trades

    return [
        t for t in trades
        if t["close_time"] and start <= t["close_time"] <= end
    ]


# ── Statistics Calculator ─────────────────────────────────────────────────────

def calc_stats(trades: list[dict], config: dict) -> dict:
    """Hitung semua statistik dari list trades."""
    if not trades:
        return {"total": 0}

    wins   = [t for t in trades if t["net_profit"] > 0]
    losses = [t for t in trades if t["net_profit"] < 0]
    be     = [t for t in trades if t["net_profit"] == 0]

    total      = len(trades)
    n_wins     = len(wins)
    n_losses   = len(losses)
    winrate    = (n_wins / total * 100) if total > 0 else 0

    gross_profit = sum(t["net_profit"] for t in wins)
    gross_loss   = abs(sum(t["net_profit"] for t in losses))
    net_pnl      = gross_profit - gross_loss
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    avg_win  = (gross_profit / n_wins) if n_wins > 0 else 0
    avg_loss = (gross_loss / n_losses) if n_losses > 0 else 0

    # RR aktual: avg win / avg loss
    rr_actual = (avg_win / avg_loss) if avg_loss > 0 else 0

    # Max drawdown sederhana (running balance)
    balance = config.get("account_balance", 1000)
    peak = balance
    max_dd = 0
    running = balance
    for t in sorted(trades, key=lambda x: x["close_time"] or datetime.min):
        running += t["net_profit"]
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd

    # Consecutive wins/losses
    max_consec_win  = _max_consecutive(trades, win=True)
    max_consec_loss = _max_consecutive(trades, win=False)

    # Best & worst trade
    best_trade  = max(trades, key=lambda t: t["net_profit"])
    worst_trade = min(trades, key=lambda t: t["net_profit"])

    # Avg duration
    durations = [t["duration_min"] for t in trades if t["duration_min"] > 0]
    avg_duration = sum(durations) / len(durations) if durations else 0

    # Per symbol breakdown
    symbol_stats = defaultdict(lambda: {"total": 0, "wins": 0, "net": 0.0})
    for t in trades:
        s = t["symbol"]
        symbol_stats[s]["total"] += 1
        symbol_stats[s]["net"]   += t["net_profit"]
        if t["net_profit"] > 0:
            symbol_stats[s]["wins"] += 1

    # Per session breakdown
    session_stats = defaultdict(lambda: {"total": 0, "wins": 0, "net": 0.0})
    for t in trades:
        s = t["session"]
        session_stats[s]["total"] += 1
        session_stats[s]["net"]   += t["net_profit"]
        if t["net_profit"] > 0:
            session_stats[s]["wins"] += 1

    return {
        "total":            total,
        "wins":             n_wins,
        "losses":           n_losses,
        "breakeven":        len(be),
        "winrate":          round(winrate, 1),
        "gross_profit":     round(gross_profit, 2),
        "gross_loss":       round(gross_loss, 2),
        "net_pnl":          round(net_pnl, 2),
        "profit_factor":    round(profit_factor, 2) if profit_factor != float("inf") else "∞",
        "avg_win":          round(avg_win, 2),
        "avg_loss":         round(avg_loss, 2),
        "rr_actual":        round(rr_actual, 2),
        "max_drawdown":     round(max_dd, 2),
        "max_consec_win":   max_consec_win,
        "max_consec_loss":  max_consec_loss,
        "best_trade":       best_trade,
        "worst_trade":      worst_trade,
        "avg_duration_min": round(avg_duration, 0),
        "symbol_stats":     dict(symbol_stats),
        "session_stats":    dict(session_stats),
        "currency":         config.get("currency", "USD"),
    }


def _max_consecutive(trades: list[dict], win: bool) -> int:
    max_c = cur = 0
    for t in sorted(trades, key=lambda x: x["close_time"] or datetime.min):
        if (win and t["net_profit"] > 0) or (not win and t["net_profit"] < 0):
            cur += 1
            max_c = max(max_c, cur)
        else:
            cur = 0
    return max_c


# ── Message Formatter ─────────────────────────────────────────────────────────

def format_message(stats: dict, period: str, config: dict) -> str:
    """Format statistik jadi pesan Telegram yang rapi."""
    if stats.get("total", 0) == 0:
        return (
            f"📊 *TRADING REPORT — {period.upper()}*\n\n"
            f"Tidak ada trade pada periode ini."
        )

    cur  = stats["currency"]
    now  = datetime.now().strftime("%d %b %Y, %H:%M")
    tz   = config.get("timezone_label", "WIB")

    period_labels = {
        "today": f"HARIAN — {date.today().strftime('%d %b %Y')}",
        "week":  f"MINGGUAN — Minggu ini",
        "month": f"BULANAN — {date.today().strftime('%B %Y')}",
        "all":   "ALL TIME",
    }
    period_label = period_labels.get(period, period.upper())

    # Emoji berdasarkan performa
    pnl_emoji  = "🟢" if stats["net_pnl"] >= 0 else "🔴"
    wr_emoji   = "🔥" if stats["winrate"] >= 60 else ("✅" if stats["winrate"] >= 50 else "⚠️")

    # Best & worst trade info
    best  = stats["best_trade"]
    worst = stats["worst_trade"]
    best_sym  = best.get("symbol", "-")
    worst_sym = worst.get("symbol", "-")
    best_pnl  = best.get("net_profit", 0)
    worst_pnl = worst.get("net_profit", 0)

    # Symbol breakdown (top 3)
    sym_lines = ""
    sorted_syms = sorted(stats["symbol_stats"].items(), key=lambda x: abs(x[1]["net"]), reverse=True)[:3]
    for sym, s in sorted_syms:
        wr = round(s["wins"] / s["total"] * 100) if s["total"] > 0 else 0
        sign = "+" if s["net"] >= 0 else ""
        sym_lines += f"  {sym}: {s['total']} trade | WR {wr}% | {sign}{s['net']:.2f} {cur}\n"

    # Session breakdown
    ses_lines = ""
    for ses, s in sorted(stats["session_stats"].items(), key=lambda x: x[1]["total"], reverse=True):
        wr = round(s["wins"] / s["total"] * 100) if s["total"] > 0 else 0
        ses_lines += f"  {ses}: {s['total']} trade | WR {wr}%\n"

    msg = (
        f"📈 *TRADING REPORT — {period_label}*\n"
        f"🕐 _{now} {tz}_\n"
        f"{'─' * 30}\n\n"

        f"📊 *OVERVIEW*\n"
        f"Total Trade  : `{stats['total']}`\n"
        f"✅ Win        : `{stats['wins']}`\n"
        f"❌ Loss       : `{stats['losses']}`\n"
        f"➖ Breakeven  : `{stats['breakeven']}`\n"
        f"{wr_emoji} Winrate     : `{stats['winrate']}%`\n\n"

        f"💰 *PROFIT & LOSS*\n"
        f"Gross Profit : `+{stats['gross_profit']} {cur}`\n"
        f"Gross Loss   : `-{stats['gross_loss']} {cur}`\n"
        f"{pnl_emoji} Net P&L    : `{'+' if stats['net_pnl'] >= 0 else ''}{stats['net_pnl']} {cur}`\n"
        f"Profit Factor: `{stats['profit_factor']}`\n\n"

        f"📐 *RISK & REWARD*\n"
        f"Avg RR Actual: `1:{stats['rr_actual']}`\n"
        f"Avg Win      : `+{stats['avg_win']} {cur}`\n"
        f"Avg Loss     : `-{stats['avg_loss']} {cur}`\n"
        f"Max Drawdown : `-{stats['max_drawdown']} {cur}`\n\n"

        f"🏆 *HIGHLIGHTS*\n"
        f"Best Trade   : `{best_sym} +{best_pnl:.2f} {cur}`\n"
        f"Worst Trade  : `{worst_sym} {worst_pnl:.2f} {cur}`\n"
        f"Max Con. Win : `{stats['max_consec_win']} trade`\n"
        f"Max Con. Loss: `{stats['max_consec_loss']} trade`\n"
        f"Avg Duration : `{int(stats['avg_duration_min'])} menit`\n\n"
    )

    if sym_lines:
        msg += f"📌 *TOP PAIRS*\n{sym_lines}\n"

    if ses_lines:
        msg += f"⏰ *BY SESSION*\n{ses_lines}\n"

    msg += f"_Generated by OpenClaw + MT5 Reporter_"
    return msg


# ── Telegram Sender ───────────────────────────────────────────────────────────

def send_telegram(token: str, chat_id: str, text: str) -> bool:
    """Kirim pesan ke Telegram."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id":    chat_id,
        "text":       text,
        "parse_mode": "Markdown",
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        data = resp.json()
        if data.get("ok"):
            log.info("Pesan berhasil dikirim ke Telegram (chat_id=%s)", chat_id)
            return True
        else:
            log.error("Telegram error: %s", data)
            return False
    except Exception as e:
        log.error("Gagal kirim Telegram: %s", e)
        return False


# ── Main Entry Point ──────────────────────────────────────────────────────────

def run(period: str = "today", dry_run: bool = False):
    """
    Fungsi utama: load config → baca CSV → hitung stats → kirim Telegram.
    
    Args:
        period  : 'today' | 'week' | 'month' | 'all'
        dry_run : True = print saja, tidak kirim ke Telegram
    """
    config = load_config()

    log.info("=== Trade Summary Reporter ===")
    log.info("Period: %s | CSV: %s", period, config["csv_path"])

    trades  = load_trades(config["csv_path"])
    filtered = filter_trades(trades, period)
    stats   = calc_stats(filtered, config)
    message = format_message(stats, period, config)

    print("\n" + "=" * 50)
    print(message)
    print("=" * 50 + "\n")

    if dry_run:
        log.info("DRY RUN — tidak kirim ke Telegram.")
        return stats

    token   = config["telegram_bot_token"]
    chat_id = config["telegram_chat_id"]

    if token == "YOUR_BOT_TOKEN_HERE":
        log.error("Bot token belum dikonfigurasi! Edit: %s", CONFIG_PATH)
        return stats

    success = send_telegram(token, chat_id, message)
    if success:
        log.info("Summary berhasil dikirim!")
    else:
        log.error("Gagal kirim summary.")

    return stats


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MT5 Trade Summary Reporter")
    parser.add_argument(
        "--period", "-p",
        choices=["today", "week", "month", "all"],
        default="today",
        help="Periode laporan (default: today)",
    )
    parser.add_argument(
        "--dry-run", "-d",
        action="store_true",
        help="Print saja tanpa kirim ke Telegram",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Buat file config default",
    )
    args = parser.parse_args()

    if args.setup:
        save_config(DEFAULT_CONFIG)
        print(f"Config dibuat: {CONFIG_PATH}")
        print("Edit file tersebut dan isi bot_token + chat_id kamu.")
        sys.exit(0)

    run(period=args.period, dry_run=args.dry_run)
