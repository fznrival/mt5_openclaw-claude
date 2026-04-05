#!/bin/bash
# =============================================================================
#  install_deps.sh
#  Install semua dependencies Python yang dibutuhkan sistem ini
# =============================================================================

echo ""
echo "======================================================="
echo "  Install Dependencies — MT5 + OpenClaw Trading System"
echo "======================================================="
echo ""

# ── 1. Python dependencies (Linux native) ─────────────────────────────────
echo "[1/3] Install Python packages (Linux)..."
pip3 install requests pandas --break-system-packages 2>/dev/null || \
pip3 install requests pandas 2>/dev/null || \
pip install requests pandas --break-system-packages 2>/dev/null
echo "      ✅ requests, pandas"

# ── 2. Wine Python dependencies (untuk mt5_ict_executor.py) ───────────────
echo ""
echo "[2/3] Install Python packages di Wine (untuk MT5 API)..."
echo "      Ini butuh MT5 sudah terinstall via Wine."

if command -v wine &>/dev/null; then
    WINEPREFIX="$HOME/.wine_mt5" wine python -m pip install MetaTrader5 pandas requests 2>&1 | tail -5
    echo "      ✅ MetaTrader5, pandas, requests (Wine)"
else
    echo "      ⚠️  Wine tidak ditemukan. Jalankan setup_mt5_wine.sh dulu."
fi

# ── 3. Buat folder data ────────────────────────────────────────────────────
echo ""
echo "[3/3] Membuat folder data..."
mkdir -p "$HOME/mt5_data"
mkdir -p "$HOME/.openclaw/skills"
echo "      ✅ $HOME/mt5_data"
echo "      ✅ $HOME/.openclaw/skills"

# ── 4. Copy skills ke OpenClaw ────────────────────────────────────────────
echo ""
echo "Menyalin OpenClaw skills..."
SKILL_DIR="$HOME/mt5_openclaw/openclaw_skill"
if [ -d "$SKILL_DIR" ]; then
    cp "$SKILL_DIR"/*.json "$HOME/.openclaw/skills/" 2>/dev/null && \
    echo "✅ Skills disalin ke ~/.openclaw/skills/" || \
    echo "⚠️  Gagal salin skills"
fi

echo ""
echo "======================================================="
echo "  Semua dependencies terinstall!"
echo ""
echo "  Langkah selanjutnya:"
echo "  1. Edit config: nano ~/.openclaw/trade_config.json"
echo "  2. Test demo  : WINEPREFIX=~/.wine_mt5 wine python"
echo "                  ~/mt5_openclaw/python/mt5_ict_executor.py"
echo "  3. Setup cron : bash ~/mt5_openclaw/setup_cron.sh"
echo "======================================================="
