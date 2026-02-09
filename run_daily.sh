#!/bin/bash
# ============================================================
# 28car 每日自動爬取腳本 (Linux/macOS)
# ============================================================
# crontab 設定範例（每天早上 6 點執行）：
#   0 6 * * * /path/to/car2/run_daily.sh >> /var/log/28car_scraper.log 2>&1
# ============================================================

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

echo "========================================"
echo "  28car Daily Update"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

python3 scraper_28car.py --daily --stale-days 7 --source all
exit_code=$?

if [ $exit_code -ne 0 ]; then
    echo "ERROR: Scraper failed with exit code $exit_code" >&2
    exit $exit_code
fi

echo "Daily update completed successfully."
exit 0
