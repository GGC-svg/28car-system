#!/usr/bin/env python3
"""
資料庫每日備份腳本
只保留一個備份檔案，每日覆蓋
"""

import os
import shutil
from datetime import datetime

# 路徑設定
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'cars_28car.db')
BACKUP_DIR = os.path.join(BASE_DIR, 'backup')
BACKUP_FILE = os.path.join(BACKUP_DIR, 'cars_28car_backup.db')
LOG_FILE = os.path.join(BACKUP_DIR, 'backup.log')

def log(msg):
    """寫入日誌"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_line = f"[{timestamp}] {msg}\n"
    print(log_line.strip())

    # 確保備份目錄存在
    os.makedirs(BACKUP_DIR, exist_ok=True)

    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_line)

def backup():
    """執行備份"""
    # 檢查資料庫是否存在
    if not os.path.exists(DB_FILE):
        log("錯誤：找不到資料庫檔案")
        return False

    try:
        # 確保備份目錄存在
        os.makedirs(BACKUP_DIR, exist_ok=True)

        # 複製檔案
        shutil.copy2(DB_FILE, BACKUP_FILE)

        # 取得檔案大小
        size_bytes = os.path.getsize(DB_FILE)
        size_mb = size_bytes / 1024 / 1024

        log(f"備份成功 (大小: {size_mb:.0f} MB)")
        return True

    except Exception as e:
        log(f"備份失敗: {e}")
        return False

def trim_log():
    """保持日誌不要太大（只保留最近 50 行）"""
    if not os.path.exists(LOG_FILE):
        return

    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if len(lines) > 50:
            with open(LOG_FILE, 'w', encoding='utf-8') as f:
                f.writelines(lines[-50:])
    except:
        pass

if __name__ == '__main__':
    success = backup()
    trim_log()
    exit(0 if success else 1)
