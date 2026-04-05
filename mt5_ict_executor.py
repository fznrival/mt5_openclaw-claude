#!/usr/bin/env python3
"""
mt5_ict_executor.py
===================
Full Automated ICT 2022 Trading Engine
Logika: FVG Detection → MSS Confirmation → OTE Entry → SL/TP Otomatis
Notifikasi setiap event ke Telegram.

Dijalankan via cron setiap 15 menit (atau sesuai timeframe).
Kompatibel dengan Wine Python di Linux.

Author  : fznrival
Project : MT5 + OpenClaw Full Automated Trading System
"""

import os
import sys
import json
import logging
import requests
from datetime import datetime, time as dtime
from pathlib import Path

# ── Try import MT5 (hanya tersedia di Wine/Windows) ──────────────────────────
try:
    import MetaTrader5 as mt5
    import pandas as pd
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    print("[WARN] MetaTrader5 module tidak tersedia. Jalankan via Wine Python.")

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/tmp/ict_trade.log"),
    ],
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
CONFIG_PATH = Path.home() / ".openclaw" / "trade_config.json"

def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    log.error("Config tidak ditemukan: %s", CONFIG_PATH)
    sys.exit(1)

# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram(token: str, chat_id: str, text: str):
    """Kirim notifikasi Telegram."""
    if not token or token == "YOUR_BOT_TOKEN_HERE":
        log.warning("Telegram token belum dikonfigurasi.")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }, timeout=10)
        if not resp.json().get("ok"):
            log.error("Telegram error: %s", resp.text)
    except Exception as e:
        log.error("Gagal kirim Telegram: %s", e)

# ── Killzone Filter ───────────────────────────────────────────────────────────

def get_current_session(kz_cfg: dict) -> str:
    """Deteksi session aktif berdasarkan jam WIB sekarang."""
    now_wib = datetime.utcnow().replace(tzinfo=None)
    # UTC+7
    hour = (now_wib.hour + 7) % 24
    minute = now_wib.minute
    now_t = dtime(hour, minute)

    def t(s): return dtime(*map(int, s.split(":")))

    if t(kz_cfg["asia_start"]) <= now_t <= t(kz_cfg["asia_end"]):
        return "Asia-Killzone"
    if t(kz_cfg["london_start"]) <= now_t <= t(kz_cfg["london_end"]):
        return "London-Killzone"
    if t(kz_cfg["ny_start"]) <= now_t <= t(kz_cfg["ny_end"]):
        return "NY-Killzone"
    return "Off-Session"


def is_killzone_active(session: str, allowed: list) -> bool:
    return session in allowed

# ── Timeframe Map ─────────────────────────────────────────────────────────────

TF_MAP = {
    1:  "TIMEFRAME_M1",
    5:  "TIMEFRAME_M5",
    15: "TIMEFRAME_M15",
    30: "TIMEFRAME_M30",
    60: "TIMEFRAME_H1",
    240:"TIMEFRAME_H4",
}

# ── ICT Concepts ──────────────────────────────────────────────────────────────

def detect_fvg(df, min_pips: float = 5.0) -> dict | None:
    """
    Deteksi Fair Value Gap (FVG) pada 3 candle terakhir.
    Bullish FVG : low[i-1] > high[i-3]  → gap antara candle i-3 dan i-1
    Bearish FVG : high[i-1] < low[i-3]  → gap antara candle i-3 dan i-1
    """
    if len(df) < 5:
        return None

    # Index: -1 = candle terbaru, -2 = sebelumnya, dst
    c1_high = df["high"].iloc[-4]   # candle 3 lalu
    c1_low  = df["low"].iloc[-4]
    c3_high = df["high"].iloc[-2]   # candle 1 lalu
    c3_low  = df["low"].iloc[-2]

    pip = min_pips * 0.0001  # asumsi pair 5 digit; untuk index/gold adjust di config

    # Bullish FVG
    if c3_low > c1_high and (c3_low - c1_high) >= pip:
        return {
            "type":   "bullish",
            "top":    c3_low,
            "bottom": c1_high,
            "mid":    (c3_low + c1_high) / 2,
            "size":   c3_low - c1_high,
        }
    # Bearish FVG
    if c3_high < c1_low and (c1_low - c3_high) >= pip:
        return {
            "type":   "bearish",
            "top":    c1_low,
            "bottom": c3_high,
            "mid":    (c1_low + c3_high) / 2,
            "size":   c1_low - c3_high,
        }
    return None


def detect_mss(df, lookback: int = 5) -> str | None:
    """
    Market Structure Shift (MSS) sederhana:
    Bullish MSS : candle terbaru break di atas swing high terakhir
    Bearish MSS : candle terbaru break di bawah swing low terakhir
    """
    if len(df) < lookback + 2:
        return None

    recent     = df.tail(lookback + 1)
    prev       = df.iloc[-(lookback + 1):-1]
    swing_high = prev["high"].max()
    swing_low  = prev["low"].min()
    last_close = df["close"].iloc[-1]

    if last_close > swing_high:
        return "bullish"
    if last_close < swing_low:
        return "bearish"
    return None


def detect_swing_points(df, lookback: int = 20) -> tuple:
    """Return (swing_high, swing_low) dari N candle terakhir."""
    window = df.tail(lookback)
    return window["high"].max(), window["low"].min()


def calc_ote_zone(swing_high: float, swing_low: float,
                  direction: str, fib_low: float = 0.62,
                  fib_high: float = 0.79) -> tuple:
    """
    Hitung Optimal Trade Entry zone (OTE) berdasarkan fibonacci retracement.
    Bullish OTE : retracement dari swing_low ke swing_high
    Bearish OTE : retracement dari swing_high ke swing_low
    """
    rng = swing_high - swing_low
    if direction == "bullish":
        ote_upper = swing_high - (rng * fib_low)    # 0.62 retracement
        ote_lower = swing_high - (rng * fib_high)   # 0.79 retracement
    else:
        ote_lower = swing_low + (rng * fib_low)
        ote_upper = swing_low + (rng * fib_high)
    return ote_lower, ote_upper


def count_open_trades_today(magic: int) -> int:
    """Hitung berapa trade dengan magic number ini yang sudah dibuka hari ini."""
    if not MT5_AVAILABLE:
        return 0
    positions = mt5.positions_get()
    if positions is None:
        return 0
    today = datetime.now().date()
    count = 0
    for pos in positions:
        if pos.magic == magic:
            open_dt = datetime.fromtimestamp(pos.time).date()
            if open_dt == today:
                count += 1
    return count

# ── Main Scanner & Executor ───────────────────────────────────────────────────

def scan_and_trade(symbol: str, cfg: dict, tconf: dict,
                   token: str, chat_id: str) -> bool:
    """
    Scan satu symbol, eksekusi jika setup ICT terpenuhi.
    Return True jika trade dieksekusi.
    """
    if not MT5_AVAILABLE:
        log.error("MT5 module tidak tersedia.")
        return False

    tf_int  = tconf.get("timeframe", 15)
    tf_attr = TF_MAP.get(tf_int, "TIMEFRAME_M15")
    TIMEFRAME = getattr(mt5, tf_attr)

    lookback    = tconf.get("swing_lookback", 20)
    fib_low     = tconf.get("ote_fib_low", 0.62)
    fib_high    = tconf.get("ote_fib_high", 0.79)
    fvg_pips    = tconf.get("fvg_min_pips", 5.0)
    sl_buf      = tconf.get("sl_buffer_pips", 5.0) * 0.0001
    rr          = tconf.get("risk_reward_ratio", 2.0)
    lot         = tconf.get("lot_size", 0.01)
    magic       = tconf.get("magic_number", 2022001)
    slippage    = tconf.get("slippage_dev", 20)
    demo_mode   = tconf.get("demo_mode", True)
    max_trades  = tconf.get("max_trades_per_day", 3)

    # Ambil data candle
    rates = mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, lookback + 10)
    if rates is None or len(rates) < lookback + 5:
        log.warning("%s: Data tidak cukup (%s candle)", symbol, len(rates) if rates else 0)
        return False

    import pandas as pd
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")

    # ── 1. Swing Points ─────────────────────────────────────────────────────
    swing_high, swing_low = detect_swing_points(df, lookback)

    # ── 2. Market Structure Shift ────────────────────────────────────────────
    mss = detect_mss(df, lookback=5)
    if not mss:
        log.info("%s: Tidak ada MSS terdeteksi", symbol)
        return False

    # ── 3. FVG Detection ─────────────────────────────────────────────────────
    fvg = detect_fvg(df, min_pips=fvg_pips)
    if not fvg:
        log.info("%s: Tidak ada FVG terdeteksi", symbol)
        return False

    # FVG harus searah dengan MSS
    if fvg["type"] != mss:
        log.info("%s: FVG %s tidak align dengan MSS %s", symbol, fvg["type"], mss)
        return False

    # ── 4. OTE Zone ──────────────────────────────────────────────────────────
    ote_lower, ote_upper = calc_ote_zone(swing_high, swing_low, mss, fib_low, fib_high)
    current_price = df["close"].iloc[-1]

    in_ote = ote_lower <= current_price <= ote_upper
    if not in_ote:
        log.info("%s: Harga %.5f diluar OTE zone [%.5f - %.5f]",
                 symbol, current_price, ote_lower, ote_upper)
        return False

    # ── 5. Cek Max Trades per Hari ───────────────────────────────────────────
    open_today = count_open_trades_today(magic)
    if open_today >= max_trades:
        log.info("%s: Max trades hari ini sudah tercapai (%d)", symbol, max_trades)
        return False

    # ── 6. Siapkan Order ─────────────────────────────────────────────────────
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        log.error("%s: Tidak bisa ambil tick data", symbol)
        return False

    sym_info = mt5.symbol_info(symbol)
    digits   = sym_info.digits if sym_info else 5

    if mss == "bullish":
        order_type = mt5.ORDER_TYPE_BUY
        price      = tick.ask
        sl         = round(swing_low - sl_buf, digits)
        risk       = abs(price - sl)
        tp         = round(price + (risk * rr), digits)
        action_str = "BUY 🟢"
    else:
        order_type = mt5.ORDER_TYPE_SELL
        price      = tick.bid
        sl         = round(swing_high + sl_buf, digits)
        risk       = abs(price - sl)
        tp         = round(price - (risk * rr), digits)
        action_str = "SELL 🔴"

    actual_rr = round(rr, 1)
    now_str   = datetime.now().strftime("%Y-%m-%d %H:%M WIB")

    # ── 7. Eksekusi atau Demo ─────────────────────────────────────────────────
    if demo_mode:
        log.info("[DEMO] Setup ditemukan! %s %s | E:%.5f SL:%.5f TP:%.5f",
                 symbol, action_str, price, sl, tp)
        msg = (
            f"🔬 *DEMO SIGNAL DETECTED*\n\n"
            f"📌 *Symbol :* `{symbol}`\n"
            f"🛒 *Action :* {action_str}\n"
            f"💰 *Entry  :* `{price}`\n"
            f"🛑 *SL     :* `{sl}`\n"
            f"🎯 *TP     :* `{tp}`\n"
            f"📐 *RR     :* `1:{actual_rr}`\n"
            f"⚖️ *Lot    :* `{lot}`\n\n"
            f"📊 *ICT Setup :*\n"
            f"  • MSS    : `{mss.upper()}`\n"
            f"  • FVG    : `{fvg['type'].upper()} ({fvg['size']:.5f})`\n"
            f"  • OTE    : `{ote_lower:.5f} - {ote_upper:.5f}`\n\n"
            f"⚠️ _DEMO MODE — tidak ada order dikirim_\n"
            f"🕐 _{now_str}_"
        )
        send_telegram(token, chat_id, msg)
        return True

    # LIVE TRADE
    request = {
        "action":      mt5.TRADE_ACTION_DEAL,
        "symbol":      symbol,
        "volume":      float(lot),
        "type":        order_type,
        "price":       price,
        "sl":          sl,
        "tp":          tp,
        "deviation":   slippage,
        "magic":       magic,
        "comment":     "ICT_OpenClaw",
        "type_time":   mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)

    if result is None:
        log.error("%s: order_send() return None. Error: %s", symbol, mt5.last_error())
        return False

    if result.retcode == mt5.TRADE_RETCODE_DONE:
        log.info("ORDER SUKSES: %s %s ticket=%s", symbol, action_str, result.order)
        msg = (
            f"⚡ *AUTO-TRADE EXECUTED* ⚡\n\n"
            f"📌 *Symbol :* `{symbol}`\n"
            f"🛒 *Action :* {action_str}\n"
            f"💰 *Entry  :* `{price}`\n"
            f"🛑 *SL     :* `{sl}`\n"
            f"🎯 *TP     :* `{tp}`\n"
            f"📐 *RR     :* `1:{actual_rr}`\n"
            f"⚖️ *Lot    :* `{lot}`\n"
            f"🎫 *Ticket :* `{result.order}`\n\n"
            f"📊 *ICT Setup :*\n"
            f"  • MSS    : `{mss.upper()}`\n"
            f"  • FVG    : `{fvg['type'].upper()}`\n"
            f"  • OTE    : Confirmed ✅\n\n"
            f"🕐 _{now_str}_"
        )
        send_telegram(token, chat_id, msg)
        return True
    else:
        log.error("ORDER GAGAL: %s retcode=%s msg=%s", symbol, result.retcode, result.comment)
        msg = (
            f"❌ *ORDER GAGAL*\n\n"
            f"📌 Symbol  : `{symbol}`\n"
            f"🚫 Retcode : `{result.retcode}`\n"
            f"💬 Message : `{result.comment}`\n\n"
            f"🕐 _{now_str}_"
        )
        send_telegram(token, chat_id, msg)
        return False


def run():
    cfg    = load_config()
    tconf  = cfg.get("trading", {})
    token  = cfg.get("telegram_bot_token", "")
    chat_id = cfg.get("telegram_chat_id", "")

    allowed_sessions = tconf.get("trade_on_sessions", ["London-Killzone", "NY-Killzone"])
    symbols          = tconf.get("symbols", ["USTECm"])

    # ── Cek Session ───────────────────────────────────────────────────────────
    kz_cfg  = tconf.get("killzone_wib", {})
    session = get_current_session(kz_cfg)
    log.info("Session aktif: %s", session)

    if not is_killzone_active(session, allowed_sessions):
        log.info("Di luar killzone (%s). Scanner tidak berjalan.", session)
        return

    # ── Init MT5 ──────────────────────────────────────────────────────────────
    if not MT5_AVAILABLE:
        log.error("MT5 tidak tersedia. Jalankan: wine python mt5_ict_executor.py")
        return

    if not mt5.initialize():
        err_msg = f"❌ Gagal konek ke MT5. Error: {mt5.last_error()}"
        log.error(err_msg)
        send_telegram(token, chat_id, err_msg)
        return

    account = mt5.account_info()
    if account:
        log.info("MT5 Connected | Account: %s | Balance: %.2f %s",
                 account.login, account.balance, account.currency)

    # ── Scan Semua Symbol ─────────────────────────────────────────────────────
    executed = 0
    for symbol in symbols:
        if not mt5.symbol_select(symbol, True):
            log.warning("Symbol %s tidak ditemukan di broker, skip.", symbol)
            continue
        log.info("Scanning %s...", symbol)
        try:
            result = scan_and_trade(symbol, cfg, tconf, token, chat_id)
            if result:
                executed += 1
        except Exception as e:
            log.error("Error saat scan %s: %s", symbol, e)

    log.info("Scan selesai. %d/%d setup dieksekusi.", executed, len(symbols))
    mt5.shutdown()


if __name__ == "__main__":
    run()
