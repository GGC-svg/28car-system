#!/usr/bin/env python3
"""
migrate_db.py -- 資料庫遷移腳本
==============================================
執行: python migrate_db.py

功能:
  1. 建立 contact_groups 聯絡人分組表
  2. 建立 crm_contacts / crm_campaigns / crm_messages CRM 表
  3. 為 cars 表新增 contact_group_id 欄位
  4. 建立 users / sessions / operation_logs / system_settings 登入系統表
  5. 建立所有必要索引
  6. 執行初始聯絡人分組計算 (Union-Find)
  7. 建立預設管理員帳號

安全: 可重複執行 (CREATE IF NOT EXISTS + try/except ALTER)
"""

import sqlite3
import os
import json
import re
import logging
import hashlib
from datetime import datetime
from collections import defaultdict

BASE_DIR = os.environ.get('APP_BASE_DIR', os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get('DB_PATH', os.path.join(BASE_DIR, "cars_28car.db"))

# 28car 預設已售名稱前綴，必須排除（有多種變體）
DEFAULT_SOLD_PREFIX = '由於已售'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)


# ============================================================
# Union-Find 資料結構
# ============================================================

class UnionFind:
    def __init__(self):
        self.parent = {}
        self.rank = {}

    def find(self, x):
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x, y):
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1


# ============================================================
# Schema 遷移
# ============================================================

def migrate_schema(conn):
    """建立所有新表和索引"""
    c = conn.cursor()

    # --- contact_groups ---
    c.execute('''
        CREATE TABLE IF NOT EXISTS contact_groups (
            group_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_name  TEXT,
            canonical_phone TEXT,
            car_count       INTEGER DEFAULT 0,
            active_car_count INTEGER DEFAULT 0,
            classification  TEXT DEFAULT 'private',
            all_names       TEXT,
            all_phones      TEXT,
            created_at      TEXT,
            updated_at      TEXT
        )
    ''')

    # --- crm_contacts ---
    c.execute('''
        CREATE TABLE IF NOT EXISTS crm_contacts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id        INTEGER,
            contact_name    TEXT,
            contact_phone   TEXT,
            email           TEXT,
            tags            TEXT,
            notes           TEXT,
            status          TEXT DEFAULT 'new',
            send_count      INTEGER DEFAULT 0,
            last_sent_at    TEXT,
            last_replied_at TEXT,
            car_count       INTEGER DEFAULT 0,
            classification  TEXT DEFAULT 'private',
            created_at      TEXT,
            updated_at      TEXT,
            FOREIGN KEY (group_id) REFERENCES contact_groups(group_id)
        )
    ''')

    # --- crm_campaigns ---
    c.execute('''
        CREATE TABLE IF NOT EXISTS crm_campaigns (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            type            TEXT NOT NULL,
            template        TEXT,
            status          TEXT DEFAULT 'draft',
            target_filter   TEXT,
            total_targets   INTEGER DEFAULT 0,
            sent_count      INTEGER DEFAULT 0,
            failed_count    INTEGER DEFAULT 0,
            replied_count   INTEGER DEFAULT 0,
            created_at      TEXT,
            updated_at      TEXT
        )
    ''')

    # --- crm_messages ---
    c.execute('''
        CREATE TABLE IF NOT EXISTS crm_messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id     INTEGER NOT NULL,
            contact_id      INTEGER NOT NULL,
            type            TEXT NOT NULL,
            recipient       TEXT,
            content         TEXT,
            status          TEXT DEFAULT 'pending',
            external_id     TEXT,
            error_message   TEXT,
            sent_at         TEXT,
            delivered_at    TEXT,
            replied_at      TEXT,
            created_at      TEXT,
            FOREIGN KEY (campaign_id) REFERENCES crm_campaigns(id),
            FOREIGN KEY (contact_id) REFERENCES crm_contacts(id)
        )
    ''')

    # --- contact_logs 溝通紀錄表 ---
    # 注意：現在使用 vid（車輛ID）作為主要關聯，group_id 作為備用
    c.execute('''
        CREATE TABLE IF NOT EXISTS contact_logs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            vid             TEXT,
            group_id        INTEGER,
            contacted_by    TEXT,
            contact_method  TEXT,
            content         TEXT,
            contacted_at    TEXT,
            created_at      TEXT,
            updated_at      TEXT,
            FOREIGN KEY (vid) REFERENCES cars(vid),
            FOREIGN KEY (group_id) REFERENCES contact_groups(group_id)
        )
    ''')

    # --- scraper_runs 爬蟲執行記錄表 ---
    c.execute('''
        CREATE TABLE IF NOT EXISTS scraper_runs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at      TEXT NOT NULL,
            finished_at     TEXT,
            status          TEXT DEFAULT 'running',
            sources         TEXT,
            total_pages     INTEGER DEFAULT 0,
            new_cars        INTEGER DEFAULT 0,
            updated_cars    INTEGER DEFAULT 0,
            unchanged_cars  INTEGER DEFAULT 0,
            details_scraped INTEGER DEFAULT 0,
            photos_downloaded INTEGER DEFAULT 0,
            stale_marked    INTEGER DEFAULT 0,
            error_message   TEXT
        )
    ''')

    # --- sms_templates 簡訊模板表 ---
    c.execute('''
        CREATE TABLE IF NOT EXISTS sms_templates (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            content         TEXT NOT NULL,
            is_active       INTEGER DEFAULT 1,
            created_at      TEXT,
            updated_at      TEXT
        )
    ''')

    # --- sms_logs 簡訊發送記錄表 ---
    c.execute('''
        CREATE TABLE IF NOT EXISTS sms_logs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            phone           TEXT NOT NULL,
            message         TEXT,
            template_id     INTEGER,
            group_id        INTEGER,
            status          TEXT DEFAULT 'pending',
            transaction_id  TEXT,
            error_code      TEXT,
            error_message   TEXT,
            sent_at         TEXT,
            created_at      TEXT,
            FOREIGN KEY (template_id) REFERENCES sms_templates(id),
            FOREIGN KEY (group_id) REFERENCES contact_groups(group_id)
        )
    ''')

    # --- sms_daily_runs 每日發送統計表 ---
    c.execute('''
        CREATE TABLE IF NOT EXISTS sms_daily_runs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date        TEXT NOT NULL,
            started_at      TEXT,
            finished_at     TEXT,
            total_targets   INTEGER DEFAULT 0,
            sent_count      INTEGER DEFAULT 0,
            success_count   INTEGER DEFAULT 0,
            failed_count    INTEGER DEFAULT 0,
            skipped_count   INTEGER DEFAULT 0,
            status          TEXT DEFAULT 'running',
            error_message   TEXT
        )
    ''')

    # --- users 使用者帳號表 ---
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            username        TEXT NOT NULL UNIQUE,
            password_hash   TEXT NOT NULL,
            display_name    TEXT,
            role            TEXT DEFAULT 'user',
            is_active       INTEGER DEFAULT 1,
            must_change_pwd INTEGER DEFAULT 0,
            last_login_at   TEXT,
            created_at      TEXT,
            updated_at      TEXT
        )
    ''')

    # --- sessions Session 管理表 ---
    c.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            session_id      TEXT PRIMARY KEY,
            user_id         INTEGER NOT NULL,
            ip_address      TEXT,
            user_agent      TEXT,
            created_at      TEXT,
            expires_at      TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    # --- operation_logs 操作日誌表 ---
    c.execute('''
        CREATE TABLE IF NOT EXISTS operation_logs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER,
            username        TEXT,
            action          TEXT NOT NULL,
            target_type     TEXT,
            target_id       TEXT,
            details         TEXT,
            ip_address      TEXT,
            created_at      TEXT
        )
    ''')

    # --- system_settings 系統設定表 ---
    c.execute('''
        CREATE TABLE IF NOT EXISTS system_settings (
            key             TEXT PRIMARY KEY,
            value           TEXT,
            description     TEXT,
            updated_by      INTEGER,
            updated_at      TEXT
        )
    ''')

    # --- contact_groups 新增 email 欄位 ---
    try:
        c.execute("SELECT email FROM contact_groups LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE contact_groups ADD COLUMN email TEXT DEFAULT ''")
        log.info("  新增 contact_groups.email 欄位")

    # --- contact_logs 新增 vid 欄位（已存在的資料庫）---
    try:
        c.execute("SELECT vid FROM contact_logs LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE contact_logs ADD COLUMN vid TEXT DEFAULT NULL")
        log.info("  新增 contact_logs.vid 欄位")

    # --- cars 新增 contact_group_id ---
    try:
        c.execute("SELECT contact_group_id FROM cars LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE cars ADD COLUMN contact_group_id INTEGER DEFAULT NULL")
        log.info("  新增 cars.contact_group_id 欄位")

    # --- 索引 ---
    indexes = [
        ('idx_cars_scraped_at', 'cars(scraped_at)'),
        ('idx_cars_last_seen', 'cars(last_seen)'),
        ('idx_cars_contact_phone', 'cars(contact_phone)'),
        ('idx_cars_contact_name', 'cars(contact_name)'),
        ('idx_cars_contact_group_id', 'cars(contact_group_id)'),
        ('idx_cg_classification', 'contact_groups(classification)'),
        ('idx_cg_phone', 'contact_groups(canonical_phone)'),
        ('idx_cl_vid', 'contact_logs(vid)'),
        ('idx_cl_group', 'contact_logs(group_id)'),
        ('idx_cl_contacted_at', 'contact_logs(contacted_at)'),
        ('idx_crm_c_group', 'crm_contacts(group_id)'),
        ('idx_crm_c_class', 'crm_contacts(classification)'),
        ('idx_crm_c_status', 'crm_contacts(status)'),
        ('idx_crm_m_campaign', 'crm_messages(campaign_id)'),
        ('idx_crm_m_contact', 'crm_messages(contact_id)'),
        ('idx_crm_m_status', 'crm_messages(status)'),
        ('idx_scraper_runs_started', 'scraper_runs(started_at)'),
        ('idx_sms_logs_phone', 'sms_logs(phone)'),
        ('idx_sms_logs_sent_at', 'sms_logs(sent_at)'),
        ('idx_sms_logs_status', 'sms_logs(status)'),
        ('idx_sms_daily_runs_date', 'sms_daily_runs(run_date)'),
        ('idx_users_username', 'users(username)'),
        ('idx_users_role', 'users(role)'),
        ('idx_sessions_user', 'sessions(user_id)'),
        ('idx_sessions_expires', 'sessions(expires_at)'),
        ('idx_oplogs_user', 'operation_logs(user_id)'),
        ('idx_oplogs_action', 'operation_logs(action)'),
        ('idx_oplogs_created', 'operation_logs(created_at)'),
    ]
    for name, cols in indexes:
        c.execute(f'CREATE INDEX IF NOT EXISTS {name} ON {cols}')

    conn.commit()
    log.info("Schema 遷移完成")


# ============================================================
# 密碼雜湊與預設管理員
# ============================================================

def hash_password(password, salt=None):
    """密碼雜湊 (SHA-256 + salt)"""
    if salt is None:
        salt = os.urandom(16).hex()
    password_hash = hashlib.sha256(f"{password}{salt}".encode()).hexdigest()
    return f"{salt}:{password_hash}"


def create_default_admin(conn):
    """建立預設管理員帳號 (admin/admin)"""
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE username = 'admin'")
    if c.fetchone()[0] == 0:
        now = datetime.now().isoformat()
        password_hash = hash_password('admin')
        c.execute('''
            INSERT INTO users (username, password_hash, display_name, role, is_active, must_change_pwd, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', ('admin', password_hash, '系統管理員', 'admin', 1, 1, now, now))
        conn.commit()
        log.info("  建立預設管理員帳號: admin (首次登入需更改密碼)")
    else:
        log.info("  管理員帳號已存在")


# ============================================================
# 聯絡人分組重建
# ============================================================

# Email 提取正則（從 contact_name 中提取，格式如 "Allen 電子:xxx@yyy.com"）
EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')


def extract_email_from_name(name):
    """從聯絡人名稱中提取 email，回傳 (clean_name, email)"""
    m = EMAIL_RE.search(name)
    if m:
        email = m.group(0)
        # 移除 email 及 "電子:" 前綴
        clean = re.sub(r'電子[:：]?\s*' + re.escape(email), '', name).strip()
        if not clean:
            clean = name.split('電子')[0].strip() if '電子' in name else name.split(email)[0].strip()
        return clean.strip(), email
    return name, ''


def rebuild_contact_groups(conn, force=False):
    """Union-Find 演算法重建聯絡人分組（僅同電話合併，不同名合併）

    Args:
        conn: 資料庫連線
        force: 是否強制重建（忽略現有資料）

    注意：為避免影響現有的 contact_logs 和手動調整過的群組，
         只有在 contact_groups 表為空時才會執行重建。
         若需強制重建，請設定 force=True（通常只在首次安裝時使用）。
    """
    c = conn.cursor()
    now = datetime.now().isoformat()

    # 檢查是否已有聯絡人分組資料
    existing_count = c.execute('SELECT COUNT(*) FROM contact_groups').fetchone()[0]
    if existing_count > 0 and not force:
        log.info(f"聯絡人分組已存在 ({existing_count} 組)，跳過重建")
        log.info("  提示：若需強制重建，請使用網頁介面的「重建聯絡人分組」功能")
        return

    log.info("開始重建聯絡人分組...")

    # Step 1: 載入所有有聯絡資料的車輛
    c.execute('''
        SELECT vid, contact_name, contact_phone
        FROM cars
        WHERE detail_scraped = 1
          AND (length(COALESCE(contact_phone,'')) > 0
               OR length(COALESCE(contact_name,'')) > 0)
    ''')
    rows = c.fetchall()
    log.info(f"  載入 {len(rows)} 筆有聯絡資料的車輛")

    # Step 2: 建立查詢表
    uf = UnionFind()
    phone_to_keys = defaultdict(set)
    key_to_vids = defaultdict(set)
    key_to_name = {}
    key_to_phone = {}
    key_to_email = {}

    for vid, name, phone in rows:
        name = (name or '').strip()
        phone = (phone or '').strip()

        # 排除預設已售名稱（多種變體，用前綴匹配）
        if name.startswith(DEFAULT_SOLD_PREFIX):
            name = ''

        if not name and not phone:
            continue

        # 從名稱中提取 email
        clean_name, email = extract_email_from_name(name)

        key = f"{name}||{phone}"
        key_to_vids[key].add(vid)
        key_to_name[key] = clean_name
        key_to_phone[key] = phone
        if email:
            key_to_email[key] = email
        uf.find(key)

        if phone:
            phone_to_keys[phone].add(key)

    # Step 3: 僅同電話合併（不做同名合併，避免 "Chan"、"Lam" 等常見名誤合併）
    for phone, keys in phone_to_keys.items():
        keys_list = list(keys)
        for i in range(1, len(keys_list)):
            uf.union(keys_list[0], keys_list[i])

    # Step 4: 收集分組
    groups = defaultdict(lambda: {'names': set(), 'phones': set(), 'emails': set(), 'vids': set()})
    for key in key_to_vids:
        root = uf.find(key)
        name = key_to_name[key]
        phone = key_to_phone[key]
        email = key_to_email.get(key, '')
        if name:
            groups[root]['names'].add(name)
        if phone:
            groups[root]['phones'].add(phone)
        if email:
            groups[root]['emails'].add(email)
        groups[root]['vids'].update(key_to_vids[key])

    log.info(f"  找到 {len(groups)} 個聯絡人分組")

    # 建立 vid -> (name, phone) 快速查詢
    vid_map = {}
    for vid, name, phone in rows:
        vid_map[vid] = ((name or '').strip(), (phone or '').strip())

    # Step 5: 清除舊資料
    c.execute('DELETE FROM contact_groups')
    c.execute('UPDATE cars SET contact_group_id = NULL')

    # 分批查詢輔助函數 (SQLite 變數上限 999)
    BATCH_SIZE = 900

    def count_active_batch(vids):
        total = 0
        vids = list(vids)
        for i in range(0, len(vids), BATCH_SIZE):
            batch = vids[i:i + BATCH_SIZE]
            ph = ','.join('?' * len(batch))
            total += c.execute(
                f'SELECT COUNT(*) FROM cars WHERE vid IN ({ph}) AND is_sold=0', batch
            ).fetchone()[0]
        return total

    def update_group_id_batch(group_id, vids):
        vids = list(vids)
        for i in range(0, len(vids), BATCH_SIZE):
            batch = vids[i:i + BATCH_SIZE]
            ph = ','.join('?' * len(batch))
            c.execute(
                f'UPDATE cars SET contact_group_id = ? WHERE vid IN ({ph})',
                [group_id] + batch
            )

    # Step 6: 寫入新分組
    stats = defaultdict(int)
    email_count = 0

    for root_key, data in groups.items():
        car_count = len(data['vids'])
        names_list = sorted(data['names'])
        phones_list = sorted(data['phones'])
        emails_list = sorted(data['emails'])

        # 選最常出現的名字作為 canonical
        if names_list:
            name_counts = defaultdict(int)
            for vid in data['vids']:
                v_name = vid_map.get(vid, ('', ''))[0]
                if v_name and not v_name.startswith(DEFAULT_SOLD_PREFIX):
                    clean_v, _ = extract_email_from_name(v_name)
                    name_counts[clean_v] += 1
            canonical_name = max(name_counts, key=name_counts.get) if name_counts else names_list[0]
        else:
            canonical_name = ''

        canonical_phone = phones_list[0] if phones_list else ''
        email = emails_list[0] if emails_list else ''
        if email:
            email_count += 1

        # 分類
        if car_count >= 5:
            classification = 'dealer'
        elif car_count >= 2:
            classification = 'broker'
        else:
            classification = 'private'
        stats[classification] += 1

        active_count = count_active_batch(data['vids'])

        c.execute('''
            INSERT INTO contact_groups
            (canonical_name, canonical_phone, email, car_count, active_car_count,
             classification, all_names, all_phones, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            canonical_name, canonical_phone, email, car_count, active_count,
            classification,
            json.dumps(names_list, ensure_ascii=False),
            json.dumps(phones_list),
            now, now
        ))
        group_id = c.lastrowid

        update_group_id_batch(group_id, data['vids'])

    conn.commit()

    for cls in ['dealer', 'broker', 'private']:
        log.info(f"  {cls}: {stats.get(cls, 0)} 組")
    log.info(f"  含 email: {email_count} 組")

    log.info("聯絡人分組重建完成")


# ============================================================
# Main
# ============================================================

def main():
    log.info("=" * 50)
    log.info("  28car 資料庫遷移 (Features 1-3)")
    log.info("=" * 50)
    log.info(f"  DB: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")

    migrate_schema(conn)
    create_default_admin(conn)
    rebuild_contact_groups(conn)

    conn.close()
    log.info("")
    log.info("所有遷移完成！")


if __name__ == '__main__':
    main()
