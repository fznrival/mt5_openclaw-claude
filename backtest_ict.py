#!/usr/bin/env python3
"""
backtest_ict.py
===============
Backtesting engine sederhana untuk strategi ICT (FVG + OTE + MSS).
Membaca data historis dari CSV atau MT5, lalu simulate entry/exit
dan hasilkan laporan winrate, RR, profit factor.

Author  : fznrival
Project : MT5 + OpenClaw Full Automated Trading System

Usage:
    python3 backtest_ict.py --symbol XAUUSD --days 30
    python3 backtest_ict.py --csv ~/mt5_data/XAUUSD_M15.csv
"""

import sys
import json
import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

try:
    import pandas as pd
    PANDAS_OK = True
except ImportError:
    PANDAS_OK = False
    print("Install pandas dulu: pip3 install pandas --break-system-packages")

try:
    import MetaTrader5 as mt5
    MT5_OK = True
except ImportError:
    MT5_OK = False

CONFIG_PATH = Path.home() / ".openclaw" / "trade_config.json"

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}

def detect_fvg(df, idx, min_pips=5.0):
    if idx < 3:
        return None
    pip = min_pips * 0.0001
    c1_high = df["high"].iloc[idx - 3]
    c1_low  = df["low"].iloc[idx - 3]
    c3_high = df["high"].iloc[idx - 1]
    c3_low  = df["low"].iloc[idx - 1]

    if c3_low > c1_high and (c3_low - c1_high) >= pip:
        return {"type": "bullish", "top": c3_low, "bottom": c1_high}
    if c3_high < c1_low and (c1_low - c3_high) >= pip:
        return {"type": "bearish", "top": c1_low, "bottom": c3_high}
    return None

def detect_mss(df, idx, lookback=5):
    if idx < lookback + 1:
        return None
    prev       = df.iloc[idx - lookback - 1: idx - 1]
    swing_high = prev["high"].max()
    swing_low  = prev["low"].min()
    last_close = df["close"].iloc[idx - 1]
    if last_close > swing_high:
        return "bullish"
    if last_close < swing_low:
        return "bearish"
    return None

def calc_ote(swing_high, swing_low, direction, fib_low=0.62, fib_high=0.79):
    rng = swing_high - swing_low
    if direction == "bullish":
        return swing_high - rng * fib_high, swing_high - rng * fib_low
    return swing_low + rng * fib_low, swing_low + rng * fib_high

# ── Backtest Engine ───────────────────────────────────────────────────────────

def run_backtest(df: "pd.DataFrame", tconf: dict) -> list:
    """
    Loop setiap candle, cari setup ICT, simulate trade.
    Return list of trade results.
    """
    lookback   = tconf.get("swing_lookback", 20)
    fib_low    = tconf.get("ote_fib_low", 0.62)
    fib_high   = tconf.get("ote_fib_high", 0.79)
    fvg_pips   = tconf.get("fvg_min_pips", 5.0)
    sl_buf     = tconf.get("sl_buffer_pips", 5.0) * 0.0001
    rr         = tconf.get("risk_reward_ratio", 2.0)
    lot        = tconf.get("lot_size", 0.01)

    trades = []
    open_trade = None

    for i in range(lookback + 5, len(df)):
        candle = df.iloc[i]

        # ── Cek apakah open trade kena TP/SL ─────────────────────────────
        if open_trade:
            hi = candle["high"]
            lo = candle["low"]
            hit_tp = hi >= open_trade["tp"] if open_trade["dir"] == "BUY" else lo <= open_trade["tp"]
            hit_sl = lo <= open_trade["sl"] if open_trade["dir"] == "BUY" else hi >= open_trade["sl"]

            if hit_tp:
                pnl = abs(open_trade["tp"] - open_trade["entry"]) * 100000 * lot
                trades.append({**open_trade, "exit": open_trade["tp"], "pnl": pnl, "result": "WIN"})
                open_trade = None
                continue
            if hit_sl:
                pnl = -abs(open_trade["sl"] - open_trade["entry"]) * 100000 * lot
                trades.append({**open_trade, "exit": open_trade["sl"], "pnl": pnl, "result": "LOSS"})
                open_trade = None
                continue
            continue  # Trade masih open, skip setup baru

        # ── Cari setup baru ───────────────────────────────────────────────
        mss = detect_mss(df, i, lookback=5)
        if not mss:
            continue

        fvg = detect_fvg(df, i, min_pips=fvg_pips)
        if not fvg or fvg["type"] != mss:
            continue

        window     = df.iloc[i - lookback: i]
        swing_high = window["high"].max()
        swing_low  = window["low"].min()
        ote_lo, ote_hi = calc_ote(swing_high, swing_low, mss, fib_low, fib_high)
        price = candle["close"]

        if not (ote_lo <= price <= ote_hi):
            continue

        # Setup valid → catat trade
        if mss == "bullish":
            entry = price
            sl    = round(swing_low - sl_buf, 5)
            risk  = abs(entry - sl)
            tp    = round(entry + risk * rr, 5)
            direction = "BUY"
        else:
            entry = price
            sl    = round(swing_high + sl_buf, 5)
            risk  = abs(entry - sl)
            tp    = round(entry - risk * rr, 5)
            direction = "SELL"

        open_trade = {
            "time":  candle.get("time", str(df.index[i])),
            "dir":   direction,
            "entry": entry,
            "sl":    sl,
            "tp":    tp,
            "mss":   mss,
            "fvg":   fvg["type"],
        }

    return trades

# ── Report Generator ──────────────────────────────────────────────────────────

def print_report(trades: list, symbol: str, tconf: dict):
    if not trades:
        print("\n[!] Tidak ada trade ditemukan pada periode ini.")
        return

    wins   = [t for t in trades if t["result"] == "WIN"]
    losses = [t for t in trades if t["result"] == "LOSS"]
    total  = len(trades)
    wr     = len(wins) / total * 100
    net    = sum(t["pnl"] for t in trades)
    gross_p = sum(t["pnl"] for t in wins)
    gross_l = abs(sum(t["pnl"] for t in losses))
    pf     = gross_p / gross_l if gross_l > 0 else float("inf")

    avg_win  = gross_p / len(wins) if wins else 0
    avg_loss = gross_l / len(losses) if losses else 0
    rr_act   = avg_win / avg_loss if avg_loss > 0 else 0

    print("\n" + "=" * 50)
    print(f"  BACKTEST REPORT — {symbol}")
    print("=" * 50)
    print(f"  Period       : {tconf.get('_period', 'N/A')}")
    print(f"  Timeframe    : M{tconf.get('timeframe', 15)}")
    print(f"  Total Trades : {total}")
    print(f"  Wins         : {len(wins)}  ({wr:.1f}%)")
    print(f"  Losses       : {len(losses)}")
    print(f"  Winrate      : {wr:.1f}%")
    print(f"  Net PnL      : {'+' if net >= 0 else ''}{net:.2f} USD")
    print(f"  Gross Profit : +{gross_p:.2f} USD")
    print(f"  Gross Loss   : -{gross_l:.2f} USD")
    print(f"  Profit Factor: {pf:.2f}")
    print(f"  Avg RR Actual: 1:{rr_act:.2f}")
    print(f"  Avg Win      : +{avg_win:.2f}")
    print(f"  Avg Loss     : -{avg_loss:.2f}")
    print("=" * 50 + "\n")

    print("  Last 5 Trades:")
    for t in trades[-5:]:
        sign = "✅ WIN " if t["result"] == "WIN" else "❌ LOSS"
        print(f"  {sign} | {t['dir']} | Entry:{t['entry']:.5f} | PnL:{t['pnl']:+.2f}")
    print()

# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ICT Strategy Backtester")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--days",   type=int, default=30)
    parser.add_argument("--csv",    default=None, help="Path ke CSV OHLCV")
    args = parser.parse_args()

    if not PANDAS_OK:
        sys.exit(1)

    cfg   = load_config()
    tconf = cfg.get("trading", {})
    tconf["_period"] = f"Last {args.days} days"

    if args.csv:
        # Load dari CSV
        df = pd.read_csv(args.csv)
        df.columns = [c.lower() for c in df.columns]
        log.info("Loaded %d rows dari %s", len(df), args.csv)
    elif MT5_OK:
        # Load dari MT5
        if not mt5.initialize():
            log.error("Gagal init MT5")
            sys.exit(1)
        tf_map = {5: mt5.TIMEFRAME_M5, 15: mt5.TIMEFRAME_M15, 60: mt5.TIMEFRAME_H1}
        tf = tf_map.get(tconf.get("timeframe", 15), mt5.TIMEFRAME_M15)
        rates = mt5.copy_rates_from_pos(args.symbol, tf, 0, args.days * 96)  # ~96 candle/day M15
        mt5.shutdown()
        if rates is None:
            log.error("Tidak bisa ambil data dari MT5")
            sys.exit(1)
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        log.info("Loaded %d candles dari MT5 untuk %s", len(df), args.symbol)
    else:
        log.error("Tidak ada sumber data. Gunakan --csv atau jalankan via Wine dengan MT5 terinstall.")
        sys.exit(1)

    trades = run_backtest(df, tconf)
    print_report(trades, args.symbol, tconf)


if __name__ == "__main__":
    main()
