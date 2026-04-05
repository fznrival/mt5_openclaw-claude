#!/bin/bash
# =============================================================================
#  setup_cron.sh (REVISED - Full Automated Trading System)
#  Daftarkan semua cron job: scanner, monitor, daily/weekly/monthly report
# =============================================================================

PYTHON="python3"
BASE="$HOME/mt5_openclaw/python"
LOG="/tmp"

echo ""
echo "======================================================="
echo "  Setup Cron — Full Automated Trading System"
echo "======================================================="
echo ""

crontab -l 2>/dev/null > /tmp/crontab_backup_$(date +%Y%m%d).txt

(
  crontab -l 2>/dev/null | grep -v "mt5_openclaw\|trade_summary\|ict_executor\|position_monitor"

  echo "# ============================================================"
  echo "# MT5 + OpenClaw Full Automated Trading System - $(date)"
  echo "# ============================================================"

  # ICT Scanner setiap 15 menit
  echo "*/15 * * * * WINEPREFIX=$HOME/.wine_mt5 wine python $BASE/mt5_ict_executor.py >> $LOG/ict_trade.log 2>&1"

  # Position Monitor setiap 30 menit
  echo "*/30 * * * * WINEPREFIX=$HOME/.wine_mt5 wine python $BASE/position_monitor.py >> $LOG/position_monitor.log 2>&1"

  # Daily Report Senin-Jumat 23:00 WIB (UTC 16:00)
  echo "0 16 * * 1-5 $PYTHON $BASE/trade_summary.py --period today >> $LOG/trade_summary_cron.log 2>&1"

  # Weekly Report Jumat 23:30 WIB
  echo "30 16 * * 5 $PYTHON $BASE/trade_summary.py --period week >> $LOG/trade_summary_cron.log 2>&1"

  # Monthly Report akhir bulan 23:45 WIB
  echo "45 16 28-31 * * [ \"\$(date +\%d -d tomorrow)\" = '01' ] && $PYTHON $BASE/trade_summary.py --period month >> $LOG/trade_summary_cron.log 2>&1"

) | crontab -

echo "Cron jobs aktif:"
crontab -l | grep -E "ict_executor|position_monitor|trade_summary"
echo ""
echo "Log: tail -f /tmp/ict_trade.log"
echo "Log: tail -f /tmp/position_monitor.log"
echo "Log: tail -f /tmp/trade_summary_cron.log"
