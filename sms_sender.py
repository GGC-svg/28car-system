#!/usr/bin/env python3
"""
sms_sender.py -- OneWaySMS 簡訊發送模組
==========================================
功能：
  1. 每日自動發送簡訊給私人賣家
  2. 支援簡訊模板
  3. 記錄發送結果
  4. 每日上限控制
  5. 避免重複發送

使用方式：
  python sms_sender.py --daily     # 執行每日發送
  python sms_sender.py --test      # 測試發送單則（需指定電話）
  python sms_sender.py --balance   # 查詢餘額
"""

import os
import sys
import json
import time
import sqlite3
import logging
import argparse
import requests
import urllib.parse
from datetime import datetime, date

# ============================================================
# 設定
# ============================================================

# PyInstaller 打包後，__file__ 會指向臨時目錄，需要用 sys.executable 取得 exe 所在目錄
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "cars_28car.db")
CONFIG_PATH = os.path.join(BASE_DIR, "sms_config.json")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(BASE_DIR, 'sms_sender.log'), encoding='utf-8')
    ]
)
log = logging.getLogger(__name__)


# ============================================================
# 載入設定
# ============================================================

def load_config():
    """載入 SMS 設定"""
    if not os.path.exists(CONFIG_PATH):
        log.error(f"設定檔不存在: {CONFIG_PATH}")
        return None
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_config(config):
    """儲存 SMS 設定"""
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=4)


# ============================================================
# 資料庫操作
# ============================================================

def get_db():
    """取得資料庫連線"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_active_template(conn):
    """取得啟用中的簡訊模板"""
    c = conn.cursor()
    c.execute('SELECT * FROM sms_templates WHERE is_active = 1 ORDER BY id DESC LIMIT 1')
    return c.fetchone()


def get_private_contacts_to_send(conn, limit=100):
    """
    取得今日要發送的私人賣家列表
    條件：
      1. 分類為 private（私人）
      2. 有電話號碼
      3. 今日尚未發送過
    """
    today = date.today().isoformat()
    c = conn.cursor()

    # 查詢私人賣家，排除今日已發送的電話
    c.execute('''
        SELECT cg.group_id, cg.canonical_name, cg.canonical_phone
        FROM contact_groups cg
        WHERE cg.classification = 'private'
          AND cg.canonical_phone IS NOT NULL
          AND cg.canonical_phone != ''
          AND cg.canonical_phone NOT IN (
              SELECT phone FROM sms_logs
              WHERE DATE(sent_at) = ? AND status IN ('success', 'pending')
          )
        ORDER BY cg.created_at DESC
        LIMIT ?
    ''', (today, limit))

    return c.fetchall()


def record_sms_log(conn, phone, message, template_id, group_id, status, transaction_id=None, error_code=None, error_message=None):
    """記錄簡訊發送結果"""
    now = datetime.now().isoformat()
    c = conn.cursor()
    c.execute('''
        INSERT INTO sms_logs (phone, message, template_id, group_id, status, transaction_id, error_code, error_message, sent_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (phone, message, template_id, group_id, status, transaction_id, error_code, error_message, now, now))
    conn.commit()
    return c.lastrowid


def create_daily_run(conn):
    """建立每日發送記錄"""
    now = datetime.now()
    c = conn.cursor()
    c.execute('''
        INSERT INTO sms_daily_runs (run_date, started_at, status)
        VALUES (?, ?, 'running')
    ''', (now.date().isoformat(), now.isoformat()))
    conn.commit()
    return c.lastrowid


def update_daily_run(conn, run_id, total_targets, sent_count, success_count, failed_count, skipped_count, status='completed', error_message=None):
    """更新每日發送記錄"""
    now = datetime.now().isoformat()
    c = conn.cursor()
    c.execute('''
        UPDATE sms_daily_runs SET
            finished_at = ?, total_targets = ?, sent_count = ?,
            success_count = ?, failed_count = ?, skipped_count = ?,
            status = ?, error_message = ?
        WHERE id = ?
    ''', (now, total_targets, sent_count, success_count, failed_count, skipped_count, status, error_message, run_id))
    conn.commit()


# ============================================================
# OneWaySMS API
# ============================================================

class OneWaySMS:
    """OneWaySMS API 封裝"""

    # 回應碼對照 (依據 OneWaySMS API 文件)
    RESPONSE_CODES = {
        '-100': '帳號或密碼錯誤',
        '-200': '發送者ID無效',
        '-300': '無效的收件人號碼',
        '-400': '語言類型無效',
        '-500': '訊息含無效字元',
        '-600': '餘額不足',
    }

    def __init__(self, api_url, api_username, api_password, sender_id='28Car', language_type=2):
        self.api_url = api_url
        self.api_username = api_username
        self.api_password = api_password
        self.sender_id = sender_id
        self.language_type = language_type  # 1=英文, 2=中文Unicode

    def normalize_phone(self, phone):
        """
        正規化香港電話號碼
        - 移除所有非數字字元
        - 確保以 852 開頭
        """
        # 移除非數字
        digits = ''.join(c for c in phone if c.isdigit())

        # 如果是 8 位數字，加上 852 區碼
        if len(digits) == 8:
            digits = '852' + digits
        # 如果已有區碼但沒有 852 前綴
        elif len(digits) == 11 and not digits.startswith('852'):
            digits = '852' + digits[-8:]

        return digits

    def send_sms(self, phone, message):
        """
        發送單則簡訊
        回傳: (success: bool, transaction_id: str or None, error_code: str or None, error_message: str or None)
        """
        normalized_phone = self.normalize_phone(phone)

        if len(normalized_phone) < 11:
            return False, None, 'INVALID_PHONE', f'無效的電話號碼: {phone}'

        params = {
            'apiusername': self.api_username,
            'apipassword': self.api_password,
            'mobileno': normalized_phone,
            'senderid': self.sender_id,
            'languagetype': self.language_type,
            'message': message,
        }

        try:
            response = requests.get(self.api_url, params=params, timeout=30)
            result = response.text.strip()

            # 正數表示成功，返回的是交易ID
            if result.isdigit() or (result.startswith('-') == False and result.replace('.', '').isdigit()):
                try:
                    if int(float(result)) > 0:
                        return True, result, None, None
                except:
                    pass

            # 負數表示錯誤
            error_msg = self.RESPONSE_CODES.get(result, f'未知錯誤: {result}')
            return False, None, result, error_msg

        except requests.exceptions.Timeout:
            return False, None, 'TIMEOUT', '請求超時'
        except requests.exceptions.RequestException as e:
            return False, None, 'REQUEST_ERROR', str(e)

    def check_balance(self):
        """
        查詢餘額
        回傳: (success: bool, balance: int or None, error: str or None)
        """
        # OneWaySMS 餘額查詢 API
        balance_url = self.api_url.replace('api.aspx', 'bulktrx.aspx')
        params = {
            'apiusername': self.api_username,
            'apipassword': self.api_password,
            'type': 'bal',
        }

        try:
            response = requests.get(balance_url, params=params, timeout=30)
            result = response.text.strip()

            if result.isdigit() or (result.replace('.', '').isdigit()):
                return True, int(float(result)), None

            error_msg = self.RESPONSE_CODES.get(result, f'查詢失敗: {result}')
            return False, None, error_msg

        except Exception as e:
            return False, None, str(e)


# ============================================================
# 每日發送任務
# ============================================================

def is_within_send_window(settings):
    """檢查當前時間是否在發送時間區間內"""
    now = datetime.now()
    current_time = now.strftime('%H:%M')

    start_time = settings.get('send_window_start', '10:00')
    end_time = settings.get('send_window_end', '11:00')

    return start_time <= current_time <= end_time


def run_daily_send(force=False):
    """執行每日自動發送

    Args:
        force: 如果為 True，則忽略時間區間檢查（用於手動觸發）
    """
    log.info("=" * 60)
    log.info("  每日簡訊發送任務")
    log.info("=" * 60)

    # 載入設定
    config = load_config()
    if not config:
        log.error("無法載入設定")
        return

    sms_config = config.get('onewaysms', {})
    settings = config.get('settings', {})

    # 檢查是否啟用
    if not sms_config.get('enabled', False):
        log.warning("簡訊功能未啟用 (enabled=false)")
        return

    # 檢查時間區間（除非是強制執行）
    if not force:
        if not is_within_send_window(settings):
            start_time = settings.get('send_window_start', '10:00')
            end_time = settings.get('send_window_end', '11:00')
            log.info(f"目前時間不在發送區間 ({start_time} - {end_time})，跳過")
            return

    # 檢查 API 憑證
    if not sms_config.get('api_username') or not sms_config.get('api_password'):
        log.error("API 憑證未設定")
        return

    # 初始化
    conn = get_db()
    run_id = create_daily_run(conn)

    stats = {
        'total_targets': 0,
        'sent_count': 0,
        'success_count': 0,
        'failed_count': 0,
        'skipped_count': 0,
    }

    try:
        # 取得簡訊模板
        template = get_active_template(conn)
        if not template:
            log.error("沒有啟用的簡訊模板")
            update_daily_run(conn, run_id, 0, 0, 0, 0, 0, 'error', '沒有啟用的簡訊模板')
            return

        template_id = template['id']
        message_content = template['content']
        log.info(f"使用模板: {template['name']}")
        log.info(f"內容: {message_content[:50]}...")

        # 取得要發送的聯絡人
        daily_limit = settings.get('daily_limit', 100)
        contacts = get_private_contacts_to_send(conn, daily_limit)
        stats['total_targets'] = len(contacts)

        log.info(f"今日目標: {len(contacts)} 位私人賣家 (上限: {daily_limit})")

        if len(contacts) == 0:
            log.info("沒有需要發送的對象")
            update_daily_run(conn, run_id, 0, 0, 0, 0, 0, 'completed', '沒有需要發送的對象')
            return

        # 初始化 SMS 發送器
        sms = OneWaySMS(
            api_url=sms_config.get('api_url', 'https://gateway.onewaysms.hk/api.aspx'),
            api_username=sms_config['api_username'],
            api_password=sms_config['api_password'],
            sender_id=sms_config.get('sender_id', '28Car'),
            language_type=sms_config.get('language_type', 2),
        )

        # 發送延遲
        delay = settings.get('delay_between_sms', 1.0)

        # 開始發送
        for i, contact in enumerate(contacts):
            phone = contact['canonical_phone']
            group_id = contact['group_id']
            name = contact['canonical_name']

            log.info(f"[{i+1}/{len(contacts)}] 發送給 {name} ({phone})")

            success, txn_id, err_code, err_msg = sms.send_sms(phone, message_content)

            if success:
                log.info(f"  ✓ 成功 (交易ID: {txn_id})")
                record_sms_log(conn, phone, message_content, template_id, group_id, 'success', txn_id)
                stats['success_count'] += 1
            else:
                log.warning(f"  ✗ 失敗: {err_msg}")
                record_sms_log(conn, phone, message_content, template_id, group_id, 'failed', None, err_code, err_msg)
                stats['failed_count'] += 1

            stats['sent_count'] += 1

            # 延遲
            if i < len(contacts) - 1:
                time.sleep(delay)

        # 更新統計
        update_daily_run(conn, run_id, stats['total_targets'], stats['sent_count'],
                        stats['success_count'], stats['failed_count'], stats['skipped_count'], 'completed')

        log.info("")
        log.info("=" * 60)
        log.info("  發送完成！")
        log.info(f"  目標數: {stats['total_targets']}")
        log.info(f"  已發送: {stats['sent_count']}")
        log.info(f"  成功: {stats['success_count']}")
        log.info(f"  失敗: {stats['failed_count']}")
        log.info("=" * 60)

    except Exception as e:
        log.error(f"發送過程出錯: {e}")
        import traceback
        traceback.print_exc()
        update_daily_run(conn, run_id, stats['total_targets'], stats['sent_count'],
                        stats['success_count'], stats['failed_count'], stats['skipped_count'], 'error', str(e))

    finally:
        conn.close()


def test_send(phone):
    """測試發送單則簡訊"""
    config = load_config()
    if not config:
        log.error("無法載入設定")
        return

    sms_config = config.get('onewaysms', {})

    if not sms_config.get('api_username') or not sms_config.get('api_password'):
        log.error("API 憑證未設定，請先編輯 sms_config.json")
        return

    conn = get_db()
    template = get_active_template(conn)
    conn.close()

    if not template:
        log.error("沒有啟用的簡訊模板，請先建立模板")
        return

    message = template['content']
    log.info(f"測試發送到: {phone}")
    log.info(f"內容: {message}")

    sms = OneWaySMS(
        api_url=sms_config.get('api_url', 'https://gateway.onewaysms.hk/api.aspx'),
        api_username=sms_config['api_username'],
        api_password=sms_config['api_password'],
        sender_id=sms_config.get('sender_id', '28Car'),
        language_type=sms_config.get('language_type', 2),
    )

    success, txn_id, err_code, err_msg = sms.send_sms(phone, message)

    if success:
        log.info(f"✓ 發送成功！交易ID: {txn_id}")
    else:
        log.error(f"✗ 發送失敗: {err_msg} (錯誤碼: {err_code})")


def check_balance():
    """查詢 SMS 餘額"""
    config = load_config()
    if not config:
        log.error("無法載入設定")
        return

    sms_config = config.get('onewaysms', {})

    if not sms_config.get('api_username') or not sms_config.get('api_password'):
        log.error("API 憑證未設定")
        return

    sms = OneWaySMS(
        api_url=sms_config.get('api_url', 'https://gateway.onewaysms.hk/api.aspx'),
        api_username=sms_config['api_username'],
        api_password=sms_config['api_password'],
    )

    success, balance, error = sms.check_balance()

    if success:
        log.info(f"✓ 目前餘額: {balance} 則")
    else:
        log.error(f"✗ 查詢失敗: {error}")


# ============================================================
# 主程式
# ============================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='OneWaySMS 簡訊發送工具')
    parser.add_argument('--daily', action='store_true', help='執行每日自動發送（會檢查時間區間）')
    parser.add_argument('--force', action='store_true', help='強制執行（忽略時間區間檢查）')
    parser.add_argument('--test', type=str, metavar='PHONE', help='測試發送到指定電話')
    parser.add_argument('--balance', action='store_true', help='查詢餘額')

    args = parser.parse_args()

    if args.daily:
        run_daily_send(force=args.force)
    elif args.test:
        test_send(args.test)
    elif args.balance:
        check_balance()
    else:
        parser.print_help()
