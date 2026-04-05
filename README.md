# 🦞 MT5 + OpenClaw — Full Automated Trading System

Sistem trading otomatis penuh berbasis **ICT 2022 Methodology** yang terintegrasi dengan **OpenClaw AI Agent** dan **Telegram**.

**Siklus lengkap:** Analisis → Eksekusi → Monitor → Laporan

---

## 📁 Struktur Repo

```
mt5_openclaw/
├── mql5/
│   └── TradeExporter.mq5          ← EA MT5: export setiap trade ke CSV
├── python/
│   ├── mt5_ict_executor.py        ← 🧠 ICT Engine: FVG+MSS+OTE → eksekusi order
│   ├── position_monitor.py        ← 📊 Monitor posisi open & floating P&L
│   ├── trade_summary.py           ← 📈 Laporan harian/mingguan/bulanan
│   ├── backtest_ict.py            ← 🔬 Backtest strategi ICT dari data historis
│   └── generate_sample_data.py    ← 🧪 Generate data dummy untuk testing
├── openclaw_skill/
│   ├── ict-autotrade.skill.json   ← Skill: scan & eksekusi via Telegram
│   ├── position-monitor.skill.json← Skill: cek posisi via Telegram
│   └── trading-reporter.skill.json← Skill: laporan via Telegram
├── setup_mt5_wine.sh              ← Install Wine + MT5 di Linux
├── setup_cron.sh                  ← Setup jadwal otomatis semua komponen
├── install_deps.sh                ← Install semua Python dependencies
└── trade_config.example.json      ← Template konfigurasi lengkap
```

---

## 🚀 Setup Lengkap (Urutan)

### Step 1 — Install Wine + MT5
```bash
chmod +x ~/mt5_openclaw/setup_mt5_wine.sh
bash ~/mt5_openclaw/setup_mt5_wine.sh
```

### Step 2 — Install Dependencies
```bash
chmod +x ~/mt5_openclaw/install_deps.sh
bash ~/mt5_openclaw/install_deps.sh
```

### Step 3 — Install EA di MT5
1. Buka MT5: `mt5`
2. **File → Open Data Folder → MQL5/Experts/**
3. Copy `TradeExporter.mq5` ke folder tersebut
4. Di MT5: **Navigator → Expert Advisors → Refresh**
5. Drag ke chart → centang **Allow live trading** → OK

### Step 4 — Konfigurasi
```bash
# Buat config dari template
cp ~/mt5_openclaw/trade_config.example.json ~/.openclaw/trade_config.json

# Edit: isi bot_token, chat_id, dan sesuaikan parameter trading
nano ~/.openclaw/trade_config.json
```

**Parameter penting:**
| Key | Keterangan |
|-----|------------|
| `telegram_bot_token` | Token dari @BotFather |
| `telegram_chat_id` | Chat ID kamu (dari pairing OpenClaw) |
| `trading.symbols` | List pair yang di-scan |
| `trading.lot_size` | Ukuran lot per trade |
| `trading.demo_mode` | `true` = sinyal saja, tidak eksekusi |
| `trading.risk_reward_ratio` | Target RR (default 2.0 = 1:2) |
| `trading.trade_on_sessions` | Killzone aktif (WIB) |

### Step 5 — Test Sistem
```bash
# Generate data dummy
python3 ~/mt5_openclaw/python/generate_sample_data.py

# Test laporan (tanpa Telegram)
python3 ~/mt5_openclaw/python/trade_summary.py --period week --dry-run

# Test scanner (perlu Wine + MT5)
WINEPREFIX=~/.wine_mt5 wine python ~/mt5_openclaw/python/mt5_ict_executor.py

# Backtest strategi
python3 ~/mt5_openclaw/python/backtest_ict.py --symbol XAUUSD --days 30
```

### Step 6 — Aktivasi Cron (Jadwal Otomatis)
```bash
chmod +x ~/mt5_openclaw/setup_cron.sh
bash ~/mt5_openclaw/setup_cron.sh
```

### Step 7 — Register OpenClaw Skills
```bash
cp ~/mt5_openclaw/openclaw_skill/*.json ~/.openclaw/skills/
openclaw gateway restart
```

---

## ⚙️ Jadwal Otomatis (Cron)

| Waktu | Task |
|-------|------|
| Setiap 15 menit | ICT Scanner → eksekusi jika setup valid |
| Setiap 30 menit | Position Monitor → update floating P&L |
| Senin–Jumat 23:00 WIB | Daily Report → ringkasan hari ini |
| Jumat 23:30 WIB | Weekly Report → rekap minggu ini |
| Akhir bulan 23:45 WIB | Monthly Report → rekap bulan ini |

---

## 🧠 Logika ICT Scanner

```
Setiap 15 menit:
  1. Cek apakah dalam Killzone WIB aktif
     (Asia 08–11, London 15–18, NY 20–23)
     ↓ Jika Off-Session → berhenti
  
  2. Scan semua symbol di config
     ↓
  3. Deteksi Market Structure Shift (MSS)
     ↓ Jika tidak ada → skip symbol
  
  4. Deteksi Fair Value Gap (FVG)
     ↓ Jika FVG tidak searah MSS → skip
  
  5. Hitung OTE Zone (Fib 0.62 – 0.79)
     ↓ Jika harga di luar OTE → skip
  
  6. Cek max trades per hari
     ↓ Jika sudah mencapai limit → skip
  
  7. Eksekusi order + kirim notifikasi Telegram
```

---

## 💬 Perintah via Telegram ke OpenClaw

| Perintah | Aksi |
|----------|------|
| `cek sinyal market sekarang` | Jalankan ICT scanner manual |
| `scan market` | Scanner semua symbol |
| `cek posisi` | Status posisi open & floating |
| `kirim summary trading hari ini` | Daily report |
| `laporan trading minggu ini` | Weekly report |
| `rekap trading bulan ini` | Monthly report |

---

## 📊 Contoh Notifikasi Telegram

**Saat setup ditemukan (demo mode):**
```
🔬 DEMO SIGNAL DETECTED

📌 Symbol : USTECm
🛒 Action : BUY 🟢
💰 Entry  : 18432.50
🛑 SL     : 18380.00
🎯 TP     : 18537.00
📐 RR     : 1:2.0
⚖️ Lot    : 0.01

📊 ICT Setup :
  • MSS    : BULLISH
  • FVG    : BULLISH (52.50)
  • OTE    : Confirmed ✅

⚠️ DEMO MODE — tidak ada order dikirim
```

**Daily Report (23:00 WIB):**
```
📈 TRADING REPORT — HARIAN — 05 Apr 2026

📊 OVERVIEW
Total Trade  : 3
✅ Win        : 2  (66.7%)
❌ Loss       : 1
🔥 Winrate    : 66.7%

💰 PROFIT & LOSS
Net P&L      : +$42.50 USD
Profit Factor: 2.83

📐 RISK & REWARD
Avg RR Actual: 1:2.1
```

---

## ⚠️ Disclaimer & Risk Warning

> **PENTING:** Sistem ini dalam **DEMO MODE** secara default (`"demo_mode": true`).
> Sebelum aktifkan live trading:
> - Backtest minimal 3 bulan data historis
> - Test di akun demo minimum 4 minggu
> - Pastikan winrate > 50% dan profit factor > 1.5
> - Gunakan lot kecil (0.01) saat mulai live
> - Trading mengandung risiko kehilangan modal

---

## 🔧 Troubleshooting

**MT5 tidak konek:**
```bash
find ~/.wine_mt5 -name "terminal64.exe" 2>/dev/null
WINEPREFIX=~/.wine_mt5 wine "PATH_EXE"
```

**Module MetaTrader5 tidak ada:**
```bash
WINEPREFIX=~/.wine_mt5 wine python -m pip install MetaTrader5
```

**Telegram tidak terkirim:**
```bash
curl "https://api.telegram.org/bot<TOKEN>/getMe"
tail -f /tmp/ict_trade.log
```

**Cek semua cron aktif:**
```bash
crontab -l
```
