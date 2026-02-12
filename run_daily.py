#!/usr/bin/env python3
"""
run_daily.py -- 每日自動任務統一執行腳本
=============================================
功能：
  1. 執行資料庫備份
  2. 執行每日爬蟲
  3. 執行簡訊發送（檢查時間區間）

使用方式：
  python run_daily.py              # 執行所有任務
  python run_daily.py --backup     # 只執行備份
  python run_daily.py --scraper    # 只執行爬蟲
  python run_daily.py --sms        # 只執行簡訊
  python run_daily.py --sms-force  # 強制執行簡訊（忽略時間區間）
"""

import os
import sys
import subprocess
import argparse
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, 'daily_task.log')


def log(msg):
    """寫入日誌"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_line = f"[{timestamp}] {msg}"
    print(log_line)

    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_line + '\n')
    except:
        pass


def run_backup():
    """執行資料庫備份"""
    log("開始執行備份...")
    script = os.path.join(BASE_DIR, 'backup_db.py')

    if not os.path.exists(script):
        log("備份腳本不存在，跳過")
        return False

    try:
        result = subprocess.run([sys.executable, script], cwd=BASE_DIR)
        if result.returncode == 0:
            log("備份執行成功")
            return True
        else:
            log(f"備份執行失敗，錯誤碼: {result.returncode}")
            return False
    except Exception as e:
        log(f"備份執行異常: {e}")
        return False


def run_scraper():
    """執行每日爬蟲"""
    log("開始執行爬蟲...")
    script = os.path.join(BASE_DIR, 'scraper_28car.py')

    if not os.path.exists(script):
        log("爬蟲腳本不存在，跳過")
        return False

    try:
        result = subprocess.run(
            [sys.executable, script, '--daily', '--stale-days', '14'],
            cwd=BASE_DIR
        )
        if result.returncode == 0:
            log("爬蟲執行成功")
            return True
        else:
            log(f"爬蟲執行失敗，錯誤碼: {result.returncode}")
            return False
    except Exception as e:
        log(f"爬蟲執行異常: {e}")
        return False


def run_sms(force=False):
    """執行簡訊發送"""
    log("開始執行簡訊發送...")
    script = os.path.join(BASE_DIR, 'sms_sender.py')

    if not os.path.exists(script):
        log("簡訊腳本不存在，跳過")
        return False

    try:
        cmd = [sys.executable, script, '--daily']
        if force:
            cmd.append('--force')

        result = subprocess.run(cmd, cwd=BASE_DIR)
        if result.returncode == 0:
            log("簡訊任務完成")
            return True
        else:
            log(f"簡訊任務結束，錯誤碼: {result.returncode}")
            return False
    except Exception as e:
        log(f"簡訊執行異常: {e}")
        return False


def trim_log():
    """保持日誌不要太大（只保留最近 500 行）"""
    if not os.path.exists(LOG_FILE):
        return

    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if len(lines) > 500:
            with open(LOG_FILE, 'w', encoding='utf-8') as f:
                f.writelines(lines[-500:])
    except:
        pass


def main():
    parser = argparse.ArgumentParser(description='每日自動任務執行腳本')
    parser.add_argument('--backup', action='store_true', help='只執行備份')
    parser.add_argument('--scraper', action='store_true', help='只執行爬蟲')
    parser.add_argument('--sms', action='store_true', help='只執行簡訊')
    parser.add_argument('--sms-force', action='store_true', help='強制執行簡訊（忽略時間區間）')

    args = parser.parse_args()

    # 如果沒有指定任何選項，執行全部
    run_all = not (args.backup or args.scraper or args.sms or args.sms_force)

    log("=" * 50)
    log("每日任務開始")
    log("=" * 50)

    if run_all or args.backup:
        run_backup()

    if run_all or args.scraper:
        run_scraper()

    if run_all or args.sms:
        run_sms(force=False)

    if args.sms_force:
        run_sms(force=True)

    log("=" * 50)
    log("每日任務執行完畢")
    log("=" * 50)

    trim_log()


if __name__ == '__main__':
    main()
