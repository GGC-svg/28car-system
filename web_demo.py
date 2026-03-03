"""
28car Demo 網站 - 本地預覽 / 正式 Server
==========================================
開發: python web_demo.py
正式: gunicorn -w 4 -b 0.0.0.0:5000 web_demo:app
"""

from flask import Flask, jsonify, send_from_directory, request, Response, make_response
import sqlite3
import os
import json
import csv
import io
import re
import logging
import hashlib
import uuid
import socket
from functools import wraps
from datetime import datetime, date, timedelta

# ============================================================
# 設定（支援環境變數覆蓋）
# ============================================================
import sys
# PyInstaller 打包後，__file__ 會指向臨時目錄，需要用 sys.executable 取得 exe 所在目錄
if getattr(sys, 'frozen', False):
    # 打包成 exe 執行
    _default_base = os.path.dirname(sys.executable)
else:
    # Python 腳本執行
    _default_base = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.environ.get('APP_BASE_DIR', _default_base)

# 版本號（用於檢測更新）
APP_VERSION = "1.5.20"
GITHUB_REPO = "GGC-svg/28car-system"

DB_PATH = os.environ.get('DB_PATH', os.path.join(BASE_DIR, "cars_28car.db"))
FLASK_HOST = os.environ.get('FLASK_HOST', '0.0.0.0')
FLASK_PORT = int(os.environ.get('FLASK_PORT', '5000'))
FLASK_DEBUG = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'

# SMS / Email 設定
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
TWILIO_FROM_NUMBER = os.environ.get('TWILIO_FROM_NUMBER', '')
SMTP_HOST = os.environ.get('SMTP_HOST', '')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASS = os.environ.get('SMTP_PASS', '')
SMTP_FROM = os.environ.get('SMTP_FROM', '')

app = Flask(__name__, static_folder=os.path.join(BASE_DIR, 'static'), static_url_path='/static')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)


# 全局錯誤處理器 - 捕捉所有未處理的異常
@app.errorhandler(500)
def handle_500_error(e):
    import traceback
    error_msg = str(e)
    tb = traceback.format_exc()
    log.error(f'500 錯誤: {error_msg} | {tb}')
    return jsonify({
        'error': '伺服器內部錯誤',
        'message': error_msg,
        'details': tb.split(chr(10))[-3] if tb else None
    }), 500


@app.errorhandler(Exception)
def handle_exception(e):
    import traceback
    error_msg = str(e)
    tb = traceback.format_exc()
    log.error(f'未處理異常: {error_msg} | {tb}')
    return jsonify({
        'error': '伺服器錯誤',
        'message': error_msg,
        'details': tb.split(chr(10))[-3] if tb else None
    }), 500


def get_script_command(script_name, args=None):
    """
    取得執行腳本的命令，自動判斷使用 exe 或 python
    script_name: 'scraper', 'sms', 'backup'
    args: 額外參數列表，例如 ['--daily']
    返回: 命令列表，例如 ['28car_scraper.exe', '--daily'] 或 ['python', 'scraper_28car.py', '--daily']
    """
    import subprocess

    exe_map = {
        'scraper': '28car_scraper.exe',
        'sms': '28car_sms.exe',
        'backup': '28car_backup.exe',
        'server': '28car_server.exe'
    }
    py_map = {
        'scraper': 'scraper_28car.py',
        'sms': 'sms_sender.py',
        'backup': 'backup_db.py',
        'server': 'web_demo.py'
    }

    exe_path = os.path.join(BASE_DIR, exe_map.get(script_name, ''))
    py_path = os.path.join(BASE_DIR, py_map.get(script_name, ''))

    # 優先使用 exe（如果存在）
    if os.path.exists(exe_path):
        cmd = [exe_path]
    elif os.path.exists(py_path):
        cmd = [sys.executable, py_path]
    else:
        return None

    if args:
        cmd.extend(args)

    return cmd


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================
# 認證系統（記憶體 Session - 避免 database locked）
# ============================================================
SESSION_COOKIE_NAME = '28car_session'
SESSION_EXPIRE_HOURS = 24
import threading
_sessions_lock = threading.Lock()
_sessions = {}  # {session_id: {'user_id': int, 'expires_at': str, 'ip': str, 'ua': str}}


def hash_password(password, salt=None):
    """密碼雜湊 (SHA-256 + salt)"""
    if salt is None:
        salt = os.urandom(16).hex()
    password_hash = hashlib.sha256(f"{password}{salt}".encode()).hexdigest()
    return f"{salt}:{password_hash}"


def verify_password(password, stored_hash):
    """驗證密碼"""
    try:
        salt, hash_val = stored_hash.split(':')
        return hash_password(password, salt) == stored_hash
    except:
        return False


def create_session(user_id, ip_address, user_agent):
    """建立 Session（記憶體存儲，不寫資料庫）"""
    session_id = str(uuid.uuid4())
    expires_at = (datetime.now() + timedelta(hours=SESSION_EXPIRE_HOURS)).isoformat()
    
    with _sessions_lock:
        # 清理該用戶的舊 session（可選：允許多裝置登入則移除此段）
        # for sid in list(_sessions.keys()):
        #     if _sessions[sid]['user_id'] == user_id:
        #         del _sessions[sid]
        
        _sessions[session_id] = {
            'user_id': user_id,
            'expires_at': expires_at,
            'ip': ip_address,
            'ua': user_agent
        }
    
    # 順便清理過期的 session
    cleanup_expired_sessions()
    return session_id


def cleanup_expired_sessions():
    """清理過期的 Session"""
    now = datetime.now().isoformat()
    with _sessions_lock:
        expired = [sid for sid, data in _sessions.items() if data['expires_at'] < now]
        for sid in expired:
            del _sessions[sid]
        if expired:
            log.info(f'清理了 {len(expired)} 個過期 Session')


def get_current_user():
    """從記憶體 Session 取得當前使用者"""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        return None

    now = datetime.now().isoformat()
    
    with _sessions_lock:
        session_data = _sessions.get(session_id)
        if not session_data or session_data['expires_at'] < now:
            return None
        user_id = session_data['user_id']
    
    # 從資料庫讀取用戶資料（只讀，不會 locked）
    try:
        db = get_db()
        row = db.execute("""
            SELECT id, username, display_name, role, must_change_pwd
            FROM users WHERE id = ? AND is_active = 1
        """, (user_id,)).fetchone()
        db.close()
        if row:
            return dict(row)
    except:
        pass
    return None


def log_operation(user_id, action, target_type=None, target_id=None, details=None):
    """記錄操作日誌"""
    try:
        db = get_db()
        username = None
        if user_id:
            user = db.execute('SELECT username FROM users WHERE id = ?', (user_id,)).fetchone()
            if user:
                username = user['username']

        db.execute("""
            INSERT INTO operation_logs (user_id, username, action, target_type, target_id, details, ip_address, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            username,
            action,
            target_type,
            target_id,
            json.dumps(details, ensure_ascii=False) if details else None,
            request.remote_addr if request else None,
            datetime.now().isoformat()
        ))
        db.commit()
        db.close()
    except Exception as e:
        log.error(f"記錄操作日誌失敗: {e}")


def login_required(f):
    """登入驗證裝飾器"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Unauthorized', 'code': 'LOGIN_REQUIRED'}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """管理員驗證裝飾器"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Unauthorized', 'code': 'LOGIN_REQUIRED'}), 401
        if user['role'] != 'admin':
            return jsonify({'error': 'Forbidden', 'code': 'ADMIN_REQUIRED'}), 403
        request.current_user = user
        return f(*args, **kwargs)
    return decorated


def restricted_api(f):
    """限制一般帳號的 API（CRM/SMS 專用）"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Unauthorized', 'code': 'LOGIN_REQUIRED'}), 401
        if user['role'] != 'admin':
            return jsonify({'error': 'Forbidden', 'code': 'PERMISSION_DENIED'}), 403
        request.current_user = user
        return f(*args, **kwargs)
    return decorated


# ============================================================
# 認證 API
# ============================================================
@app.route('/api/auth/login', methods=['POST'])
def api_login():
    """登入"""
    try:
        data = request.get_json(silent=True) or {}
        username = data.get('username', '').strip()
        password = data.get('password', '')

        if not username or not password:
            return jsonify({'error': '請輸入帳號密碼'}), 400

        db = get_db()
        user = db.execute(
            'SELECT * FROM users WHERE username = ? AND is_active = 1',
            (username,)
        ).fetchone()
        db.close()

        if not user or not verify_password(password, user['password_hash']):
            log_operation(None, 'LOGIN_FAILED', 'user', username, {'reason': 'invalid_credentials'})
            return jsonify({'error': '帳號或密碼錯誤'}), 401

        session_id = create_session(
            user['id'],
            request.remote_addr,
            request.headers.get('User-Agent', '')
        )

        # 更新最後登入時間
        db = get_db()
        db.execute('UPDATE users SET last_login_at = ? WHERE id = ?',
                   (datetime.now().isoformat(), user['id']))
        db.commit()
        db.close()

        log_operation(user['id'], 'LOGIN', 'user', str(user['id']), {})

        resp = make_response(jsonify({
            'success': True,
            'user': {
                'id': user['id'],
                'username': user['username'],
                'display_name': user['display_name'],
                'role': user['role'],
                'must_change_pwd': user['must_change_pwd']
            }
        }))
        resp.set_cookie(SESSION_COOKIE_NAME, session_id,
                        max_age=SESSION_EXPIRE_HOURS * 3600,
                        httponly=True, samesite='Lax')
        return resp
    except Exception as e:
        log.error(f'登入處理錯誤: {e}')
        return jsonify({'error': '伺服器處理錯誤，請稍後再試'}), 500


@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    """登出（從記憶體刪除 Session）"""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    user = get_current_user()
    
    if session_id:
        with _sessions_lock:
            if session_id in _sessions:
                del _sessions[session_id]

    if user:
        log_operation(user['id'], 'LOGOUT', 'user', str(user['id']), {})

    resp = make_response(jsonify({'success': True}))
    resp.delete_cookie(SESSION_COOKIE_NAME)
    return resp


@app.route('/api/auth/me')
def api_auth_me():
    """取得當前使用者資訊"""
    user = get_current_user()
    if not user:
        return jsonify({'authenticated': False})
    return jsonify({
        'authenticated': True,
        'user': user
    })


@app.route('/api/auth/change-password', methods=['POST'])
@login_required
def api_change_password():
    """更改密碼"""
    data = request.get_json()
    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '')

    if len(new_password) < 6:
        return jsonify({'error': '新密碼至少需要6個字元'}), 400

    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?',
                      (request.current_user['id'],)).fetchone()

    if not verify_password(old_password, user['password_hash']):
        db.close()
        return jsonify({'error': '舊密碼錯誤'}), 400

    new_hash = hash_password(new_password)
    db.execute("""
        UPDATE users SET password_hash = ?, must_change_pwd = 0, updated_at = ?
        WHERE id = ?
    """, (new_hash, datetime.now().isoformat(), user['id']))
    db.commit()
    db.close()

    log_operation(user['id'], 'CHANGE_PASSWORD', 'user', str(user['id']), {})

    return jsonify({'success': True})



# ============================================================
# 車輛列表 API
# ============================================================
@app.route('/api/cars')
@login_required
def api_cars():
    """車輛列表（支援搜尋、完整篩選、分頁、今日標記、聯絡人分類）"""
    db = get_db()
    today_str = date.today().isoformat()

    source = request.args.get('source', '')
    car_type = request.args.get('car_type', '')
    make = request.args.get('make', '')
    fuel = request.args.get('fuel', '')
    seats = request.args.get('seats', '')
    transmission = request.args.get('transmission', '')
    year = request.args.get('year', '')
    price_range = request.args.get('price_range', '')
    search = request.args.get('q', '')
    sort = request.args.get('sort', 'newest')
    sold = request.args.get('sold', '0')
    today_filter = request.args.get('today_filter', '')
    contact_type = request.args.get('contact_type', '')
    price_changed = request.args.get('price_changed', '')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 24))

    where = []
    params = []

    if sold == '0':
        where.append('c.is_sold = 0')
    elif sold == '1':
        where.append('c.is_sold = 1')

    if source:
        where.append('c.source = ?')
        params.append(source)
    if car_type:
        where.append('c.car_type = ?')
        params.append(car_type)
    if make:
        where.append('c.make = ?')
        params.append(make)
    if fuel:
        where.append('c.fuel LIKE ?')
        params.append(f'%{fuel}%')
    if seats:
        where.append('c.seats = ?')
        params.append(seats)
    if transmission:
        where.append('c.transmission LIKE ?')
        params.append(f'%{transmission}%')
    if year:
        where.append('c.year = ?')
        params.append(year)
    if price_range:
        price_filter = _parse_price_range(price_range)
        if price_filter:
            where.append(price_filter[0].replace('price_num', 'c.price_num'))
            params.extend(price_filter[1])
    if search:
        where.append('(c.make || c.model || c.description) LIKE ?')
        params.append(f'%{search}%')

    # 今日篩選
    if today_filter == 'new':
        where.append('c.first_seen >= ?')
        params.append(today_str)
    elif today_filter == 'updated':
        where.append('c.scraped_at >= ? AND c.first_seen < ?')
        params.extend([today_str, today_str])
    elif today_filter == 'all_today':
        where.append('(c.first_seen >= ? OR (c.scraped_at >= ? AND c.first_seen < ?))')
        params.extend([today_str, today_str, today_str])

    # 聯絡人分類篩選
    if contact_type in ('dealer', 'broker', 'private'):
        where.append('cg.classification = ?')
        params.append(contact_type)

    # 價格更新篩選
    if price_changed == 'yes':
        where.append('c.price_changed_at IS NOT NULL')

    where_sql = ' AND '.join(where) if where else '1=1'

    # updated_at 格式已轉為 YYYY-MM-DD HH:MM，可直接排序
    order_map = {
        'updated': 'c.updated_at DESC',
        'newest': 'c.first_seen DESC',
        'price_asc': 'c.price_num ASC',
        'price_desc': 'c.price_num DESC',
        'year_desc': 'c.year DESC',
        'views': 'c.views DESC',
    }
    order_sql = order_map.get(sort, order_map['updated'])

    base_query = f'''
        FROM cars c
        LEFT JOIN contact_groups cg ON c.contact_group_id = cg.group_id
        WHERE {where_sql}
    '''

    count = db.execute(f'SELECT COUNT(*) {base_query}', params).fetchone()[0]

    offset = (page - 1) * per_page
    rows = db.execute(
        f'SELECT c.*, cg.classification as contact_classification, cg.car_count as contact_car_count, cg.canonical_name as group_contact_name, cg.canonical_phone as group_contact_phone {base_query} ORDER BY {order_sql} LIMIT ? OFFSET ?',
        params + [per_page, offset]
    ).fetchall()

    cars = []
    for row in rows:
        car = dict(row)
        # 如果 cars 表的聯絡人資訊為空，從 contact_groups 補充
        if not car.get('contact_name') and car.get('group_contact_name'):
            car['contact_name'] = car['group_contact_name']
        if not car.get('contact_phone') and car.get('group_contact_phone'):
            car['contact_phone'] = car['group_contact_phone']
        # 今日狀態
        fs = car.get('first_seen', '') or ''
        sa = car.get('scraped_at', '') or ''
        if fs >= today_str:
            car['today_status'] = 'new'
        elif sa >= today_str:
            car['today_status'] = 'updated'
        else:
            car['today_status'] = None

        photos = db.execute(
            'SELECT photo_index, local_path, downloaded FROM car_photos WHERE vid=? ORDER BY photo_index',
            (car['vid'],)
        ).fetchall()
        car['photos'] = [dict(p) for p in photos]
        cars.append(car)

    # 今日統計
    today_new = db.execute('SELECT COUNT(*) FROM cars WHERE first_seen >= ?', (today_str,)).fetchone()[0]
    today_updated = db.execute(
        'SELECT COUNT(*) FROM cars WHERE scraped_at >= ? AND first_seen < ?',
        (today_str, today_str)
    ).fetchone()[0]

    db.close()

    return jsonify({
        'total': count,
        'page': page,
        'per_page': per_page,
        'total_pages': (count + per_page - 1) // per_page,
        'today_new': today_new,
        'today_updated': today_updated,
        'cars': cars,
    })


def _parse_price_range(price_range):
    ranges = {
        '1': ('price_num > 0 AND price_num <= ?', [30000]),
        '2': ('price_num > ? AND price_num <= ?', [30000, 50000]),
        '3': ('price_num > ? AND price_num <= ?', [50000, 100000]),
        '4': ('price_num > ? AND price_num <= ?', [100000, 200000]),
        '5': ('price_num > ? AND price_num <= ?', [200000, 400000]),
        '6': ('price_num > ? AND price_num <= ?', [400000, 600000]),
        '7': ('price_num > ? AND price_num <= ?', [600000, 800000]),
        '8': ('price_num > ? AND price_num <= ?', [800000, 1000000]),
        '9': ('price_num > ? AND price_num <= ?', [1000000, 2000000]),
        '10': ('price_num > ?', [2000000]),
    }
    return ranges.get(price_range)


# ============================================================
# 車輛詳情 API
# ============================================================
@app.route('/api/car/<vid>')
@login_required
def api_car_detail(vid):
    db = get_db()
    today_str = date.today().isoformat()
    row = db.execute('''
        SELECT c.*, cg.classification as contact_classification,
               cg.car_count as contact_car_count, cg.group_id as contact_group_id_info,
               cg.canonical_name as group_contact_name, cg.canonical_phone as group_contact_phone
        FROM cars c
        LEFT JOIN contact_groups cg ON c.contact_group_id = cg.group_id
        WHERE c.vid = ?
    ''', (vid,)).fetchone()
    if not row:
        db.close()
        return jsonify({'error': 'not found'}), 404
    car = dict(row)
    # 如果 cars 表的聯絡人資訊為空，從 contact_groups 補充
    if not car.get('contact_name') and car.get('group_contact_name'):
        car['contact_name'] = car['group_contact_name']
    if not car.get('contact_phone') and car.get('group_contact_phone'):
        car['contact_phone'] = car['group_contact_phone']
    fs = car.get('first_seen', '') or ''
    sa = car.get('scraped_at', '') or ''
    if fs >= today_str:
        car['today_status'] = 'new'
    elif sa >= today_str:
        car['today_status'] = 'updated'
    else:
        car['today_status'] = None
    photos = db.execute(
        'SELECT photo_index, local_path, original_url, downloaded FROM car_photos WHERE vid=? ORDER BY photo_index',
        (vid,)
    ).fetchall()
    car['photos'] = [dict(p) for p in photos]

    # 取得該車輛的溝通紀錄
    # 包含：1. vid 直接匹配  2. 同一聯絡人下 vid=NULL 的紀錄
    contact_group_id = car.get('contact_group_id')
    if contact_group_id:
        logs = db.execute(
            '''SELECT * FROM contact_logs
               WHERE vid = ? OR (group_id = ? AND vid IS NULL)
               ORDER BY contacted_at DESC''',
            (vid, contact_group_id)
        ).fetchall()
    else:
        logs = db.execute(
            'SELECT * FROM contact_logs WHERE vid = ? ORDER BY contacted_at DESC',
            (vid,)
        ).fetchall()
    car['contact_logs'] = [dict(l) for l in logs]

    db.close()
    return jsonify(car)


@app.route('/api/car/<vid>/similar')
@login_required
def api_car_similar(vid):
    """查詢同款車型（同 make + model）的車輛列表，用於價格參考"""
    db = get_db()

    # 取得當前車輛的 make 和 model
    car = db.execute('SELECT make, model FROM cars WHERE vid = ?', (vid,)).fetchone()
    if not car:
        db.close()
        return jsonify({'error': 'not found'}), 404

    make = car['make']
    model = car['model']

    if not make or not model:
        db.close()
        return jsonify({'cars': [], 'message': '此車輛無品牌或型號資訊'})

    # 排序參數
    sort = request.args.get('sort', 'updated')  # updated, price_asc, price_desc, year_desc, year_asc

    sort_map = {
        'updated': 'c.updated_at DESC',
        'price_asc': 'c.price_num ASC',
        'price_desc': 'c.price_num DESC',
        'year_desc': 'c.year DESC',
        'year_asc': 'c.year ASC',
    }
    order_sql = sort_map.get(sort, 'c.updated_at DESC')

    # 查詢同款車型，排除當前車輛
    rows = db.execute(f'''
        SELECT c.vid, c.car_no, c.make, c.model, c.year, c.price, c.price_num,
               c.transmission, c.fuel, c.updated_at, c.is_sold, c.description,
               (SELECT local_path FROM car_photos WHERE vid = c.vid AND downloaded = 1 ORDER BY photo_index LIMIT 1) as thumb
        FROM cars c
        WHERE c.make = ? AND c.model = ? AND c.vid != ?
        ORDER BY {order_sql}
        LIMIT 50
    ''', (make, model, vid)).fetchall()

    cars = [dict(r) for r in rows]
    db.close()

    return jsonify({
        'make': make,
        'model': model,
        'total': len(cars),
        'cars': cars
    })


# ============================================================
# 統計 API
# ============================================================
@app.route('/api/stats')
@login_required
def api_stats():
    db = get_db()
    today_str = date.today().isoformat()
    stats = {}
    stats['total'] = db.execute('SELECT COUNT(*) FROM cars').fetchone()[0]
    stats['active'] = db.execute('SELECT COUNT(*) FROM cars WHERE is_sold=0').fetchone()[0]
    stats['sold'] = db.execute('SELECT COUNT(*) FROM cars WHERE is_sold=1').fetchone()[0]
    stats['with_photos'] = db.execute('SELECT COUNT(*) FROM cars WHERE photo_count>0').fetchone()[0]
    stats['total_photos'] = db.execute('SELECT COUNT(*) FROM car_photos WHERE downloaded=1').fetchone()[0]
    stats['detail_scraped'] = db.execute('SELECT COUNT(*) FROM cars WHERE detail_scraped=1').fetchone()[0]
    stats['today_new'] = db.execute('SELECT COUNT(*) FROM cars WHERE first_seen >= ?', (today_str,)).fetchone()[0]
    stats['today_updated'] = db.execute(
        'SELECT COUNT(*) FROM cars WHERE scraped_at >= ? AND first_seen < ?',
        (today_str, today_str)
    ).fetchone()[0]

    try:
        source_rows = db.execute(
            'SELECT source, COUNT(*) as cnt FROM cars WHERE is_sold=0 GROUP BY source ORDER BY cnt DESC'
        ).fetchall()
        stats['sources'] = [{'name': s[0] or 'sell', 'count': s[1]} for s in source_rows]
    except Exception:
        stats['sources'] = []

    makes = db.execute(
        'SELECT make, COUNT(*) as cnt FROM cars WHERE is_sold=0 GROUP BY make ORDER BY cnt DESC LIMIT 20'
    ).fetchall()
    stats['makes'] = [{'name': m[0], 'count': m[1]} for m in makes]

    years = db.execute(
        "SELECT year, COUNT(*) as cnt FROM cars WHERE is_sold=0 AND year != '' GROUP BY year ORDER BY year DESC LIMIT 20"
    ).fetchall()
    stats['years'] = [{'name': y[0], 'count': y[1]} for y in years]

    fuels = db.execute(
        "SELECT fuel, COUNT(*) as cnt FROM cars WHERE is_sold=0 AND fuel != '' GROUP BY fuel ORDER BY cnt DESC"
    ).fetchall()
    stats['fuels'] = [{'name': f[0], 'count': f[1]} for f in fuels]

    db.close()

    # 加入網路資訊
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
        s.close()
    except:
        local_ip = '127.0.0.1'
    stats['network'] = {
        'local_ip': local_ip,
        'port': 5000,
        'lan_url': f'http://{local_ip}:5000'
    }

    return jsonify(stats)


# ============================================================
# 爬蟲執行記錄 API
# ============================================================
@app.route('/api/scraper/runs')
@login_required
def api_scraper_runs():
    """取得爬蟲執行記錄"""
    db = get_db()
    limit = int(request.args.get('limit', 10))

    try:
        rows = db.execute(
            '''SELECT id, started_at, finished_at, status, sources,
               total_pages, new_cars, updated_cars, unchanged_cars,
               details_scraped, photos_downloaded, stale_marked, error_message
               FROM scraper_runs ORDER BY started_at DESC LIMIT ?''',
            (limit,)
        ).fetchall()
        runs = [dict(r) for r in rows]
    except Exception:
        runs = []

    db.close()
    return jsonify({'runs': runs})


# ============================================================
# 篩選選項 API
# ============================================================
@app.route('/api/filters')
@login_required
def api_filters():
    db = get_db()

    try:
        sources = db.execute(
            "SELECT DISTINCT source FROM cars WHERE is_sold=0 AND source IS NOT NULL AND source!='' ORDER BY source"
        ).fetchall()
        source_list = [s[0] for s in sources]
    except Exception:
        source_list = ['sell']

    try:
        car_types = db.execute(
            "SELECT DISTINCT car_type FROM cars WHERE is_sold=0 AND car_type IS NOT NULL AND car_type!='' ORDER BY car_type"
        ).fetchall()
        car_type_list = [c[0] for c in car_types]
    except Exception:
        car_type_list = []

    makes = db.execute("SELECT DISTINCT make FROM cars WHERE is_sold=0 AND make!='' ORDER BY make").fetchall()
    years = db.execute("SELECT DISTINCT year FROM cars WHERE is_sold=0 AND year!='' ORDER BY year DESC").fetchall()
    fuels = db.execute("SELECT DISTINCT fuel FROM cars WHERE is_sold=0 AND fuel!='' ORDER BY fuel").fetchall()
    seats = db.execute(
        "SELECT DISTINCT seats FROM cars WHERE is_sold=0 AND seats IS NOT NULL AND seats!='' ORDER BY CAST(seats AS INTEGER)"
    ).fetchall()
    transmissions = db.execute(
        "SELECT DISTINCT transmission FROM cars WHERE is_sold=0 AND transmission IS NOT NULL AND transmission!='' ORDER BY transmission"
    ).fetchall()

    db.close()
    return jsonify({
        'sources': source_list,
        'car_types': car_type_list,
        'makes': [m[0] for m in makes],
        'years': [y[0] for y in years],
        'fuels': [f[0] for f in fuels],
        'seats': [s[0] for s in seats],
        'transmissions': [t[0] for t in transmissions],
    })


# ============================================================
# 聯絡人目錄 API (Feature 2)
# ============================================================
@app.route('/api/contacts')
@login_required
def api_contacts():
    """聯絡人目錄（車行/同行/私人，含溝通紀錄統計、簡訊統計、更新日期）"""
    db = get_db()
    classification = request.args.get('classification', '')
    search = request.args.get('q', '')
    sort = request.args.get('sort', 'car_count_desc')
    has_logs = request.args.get('has_logs', '')
    has_phone = request.args.get('has_phone', '')
    intention = request.args.get('intention', '')
    last_days = request.args.get('last_days', '')
    contacted_by = request.args.get('contacted_by', '')
    update_days = request.args.get('update_days', '')
    price_changed = request.args.get('price_changed', '')
    show_sold = request.args.get('show_sold', '0')  # 預設只顯示有在售車輛的聯絡人
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))

    where = []
    params = []

    if classification:
        where.append('cg.classification = ?')
        params.append(classification)
    if search:
        where.append('(cg.canonical_name LIKE ? OR cg.canonical_phone LIKE ? OR cg.all_names LIKE ?)')
        params.extend([f'%{search}%'] * 3)
    if has_logs == 'yes':
        where.append('log_count > 0')
    elif has_logs == 'no':
        where.append('(log_count IS NULL OR log_count = 0)')
    if has_phone == 'yes':
        where.append("cg.canonical_phone != ''")
    if intention:
        where.append('cg.intention_status = ?')
        params.append(intention)
    if last_days:
        if last_days == 'never':
            where.append('(cl.last_contacted_at IS NULL)')
        elif last_days.isdigit():  # 防止 SQL 注入
            where.append(f"cl.last_contacted_at >= date('now', '-{last_days} days')")
    if contacted_by:
        where.append('lcb.last_contacted_by = ?')
        params.append(contacted_by)
    if update_days and update_days.isdigit():  # 防止 SQL 注入
        # 使用 last_car_update 欄位，它來自 cars 表的 updated_at
        where.append(f"cu.last_car_update >= date('now', '-{update_days} days')")
    if price_changed == 'yes':
        where.append('pc.price_changed_count > 0')

    where_sql = ' AND '.join(where) if where else '1=1'

    # 固定排序：1. 意願欄有資料的優先 2. 更新日期最新的優先
    order_sql = "CASE WHEN cg.intention_status IS NOT NULL AND cg.intention_status != '' THEN 0 ELSE 1 END, last_car_update DESC"

    # 透過 vid 關聯溝通紀錄（聯絡人的所有車輛的溝通紀錄）
    # 根據 show_sold 參數動態計算車輛數
    if show_sold == '0':
        sold_filter = 'is_sold = 0'
        count_filter = 'COALESCE(ac.active_car_count, 0) > 0'
    elif show_sold == '1':
        sold_filter = 'is_sold = 1'
        count_filter = 'COALESCE(ac.active_car_count, 0) > 0'
    else:
        sold_filter = '1=1'  # 不過濾
        count_filter = '1=1'  # 顯示全部

    base_query = f'''
        FROM contact_groups cg
        LEFT JOIN (
            SELECT contact_group_id,
                   COUNT(*) as active_car_count
            FROM cars WHERE {sold_filter} GROUP BY contact_group_id
        ) ac ON cg.group_id = ac.contact_group_id
        LEFT JOIN (
            SELECT COALESCE(c.contact_group_id, l.group_id) as group_id,
                   COUNT(*) as log_count,
                   MAX(l.contacted_at) as last_contacted_at
            FROM contact_logs l
            LEFT JOIN cars c ON l.vid = c.vid
            GROUP BY COALESCE(c.contact_group_id, l.group_id)
        ) cl ON cg.group_id = cl.group_id
        LEFT JOIN (
            SELECT group_id, contacted_by as last_contacted_by
            FROM contact_logs
            WHERE id IN (
                SELECT MAX(id) FROM contact_logs GROUP BY group_id
            )
        ) lcb ON cg.group_id = lcb.group_id
        LEFT JOIN (
            SELECT contact_group_id,
                   MAX(updated_at) as last_car_update
            FROM cars WHERE {sold_filter} GROUP BY contact_group_id
        ) cu ON cg.group_id = cu.contact_group_id
        LEFT JOIN (
            SELECT group_id,
                   COUNT(*) as sms_count,
                   MAX(sent_at) as last_sms_sent
            FROM sms_logs WHERE status = 'success' GROUP BY group_id
        ) sl ON cg.group_id = sl.group_id
        LEFT JOIN (
            SELECT contact_group_id,
                   COUNT(*) as price_changed_count,
                   MAX(price_changed_at) as last_price_change
            FROM cars WHERE price_changed_at IS NOT NULL AND {sold_filter} GROUP BY contact_group_id
        ) pc ON cg.group_id = pc.contact_group_id
        WHERE {count_filter} AND {where_sql}
    '''

    count = db.execute(f'SELECT COUNT(*) {base_query}', params).fetchone()[0]

    offset = (page - 1) * per_page
    rows = db.execute(
        f'''SELECT cg.*,
               COALESCE(ac.active_car_count, 0) as active_car_count,
               COALESCE(cl.log_count, 0) as log_count,
               cl.last_contacted_at,
               lcb.last_contacted_by,
               cu.last_car_update,
               COALESCE(sl.sms_count, 0) as sms_count,
               sl.last_sms_sent
        {base_query} ORDER BY {order_sql} LIMIT ? OFFSET ?''',
        params + [per_page, offset]
    ).fetchall()

    contacts = [dict(r) for r in rows]
    db.close()

    return jsonify({
        'total': count,
        'page': page,
        'per_page': per_page,
        'total_pages': (count + per_page - 1) // per_page,
        'contacts': contacts,
    })



@app.route('/api/contacts/contacted-by-options')
@login_required
def api_contacted_by_options():
    """獲取所有聯絡人選項"""
    db = get_db()
    rows = db.execute(
        "SELECT DISTINCT contacted_by FROM contact_logs WHERE contacted_by IS NOT NULL AND contacted_by != '' ORDER BY contacted_by"
    ).fetchall()
    db.close()
    return jsonify({'options': [r[0] for r in rows]})


@app.route('/api/contacts/export')
@login_required
def api_contacts_export():
    """匯出聯絡人為 CSV"""
    db = get_db()
    classification = request.args.get('classification', '')
    intention = request.args.get('intention', '')

    where = []
    params = []

    if classification:
        where.append('cg.classification = ?')
        params.append(classification)
    if intention:
        where.append('cg.intention_status = ?')
        params.append(intention)
    if last_days:
        if last_days == 'never':
            where.append('(cl.last_contacted_at IS NULL)')
        elif last_days.isdigit():  # 防止 SQL 注入
            where.append(f"cl.last_contacted_at >= date('now', '-{last_days} days')")
    if contacted_by:
        where.append('lcb.last_contacted_by = ?')
        params.append(contacted_by)
    if update_days and update_days.isdigit():  # 防止 SQL 注入
        # 使用 last_car_update 欄位，它來自 cars 表的 updated_at
        where.append(f"cu.last_car_update >= date('now', '-{update_days} days')")
    if price_changed == 'yes':
        where.append('pc.price_changed_count > 0')

    where_sql = ' AND '.join(where) if where else '1=1'

    rows = db.execute(f'''
        SELECT cg.canonical_name, cg.canonical_phone, cg.classification, cg.car_count,
               cg.intention_status, cg.email,
               cu.last_car_update,
               COALESCE(sl.sms_count, 0) as sms_count,
               sl.last_sms_sent
        FROM contact_groups cg
        LEFT JOIN (
            SELECT contact_group_id, MAX(updated_at) as last_car_update
            FROM cars GROUP BY contact_group_id
        ) cu ON cg.group_id = cu.contact_group_id
        LEFT JOIN (
            SELECT group_id, COUNT(*) as sms_count, MAX(sent_at) as last_sms_sent
            FROM sms_logs WHERE status = 'success' GROUP BY group_id
        ) sl ON cg.group_id = sl.group_id
        WHERE {where_sql}
        ORDER BY cg.car_count DESC
    ''', params).fetchall()
    db.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['姓名', '電話', '分類', '車輛數', '意願狀態', 'Email', '最後更新', '簡訊次數', '最後發送'])

    classification_map = {'private': '私人', 'broker': '中間商', 'dealer': '車行'}
    intention_map = {'willing': '有意願', 'unwilling': '無意願', 'sold': '車輛已售'}

    for r in rows:
        writer.writerow([
            r[0] or '',
            r[1] or '',
            classification_map.get(r[2], r[2] or ''),
            r[3] or 0,
            intention_map.get(r[4], r[4] or ''),
            r[5] or '',
            r[6] or '',
            r[7] or 0,
            r[8] or ''
        ])

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=contacts.csv'}
    )


@app.route('/api/contact/<int:group_id>/intention', methods=['PUT'])
@login_required
def api_update_intention(group_id):
    """更新聯絡人意願狀態"""
    db = get_db()
    data = request.get_json()
    intention = data.get('intention_status', '')

    if intention not in ('', 'willing', 'unwilling', 'sold'):
        db.close()
        return jsonify({'error': 'Invalid intention status'}), 400

    db.execute('UPDATE contact_groups SET intention_status = ?, updated_at = ? WHERE group_id = ?',
               (intention if intention else None, datetime.now().isoformat(), group_id))
    db.commit()
    db.close()
    return jsonify({'status': 'ok'})

@app.route('/api/contacts/batch-classification', methods=['PUT'])
@login_required
def api_batch_update_classification():
    """批量更新聯絡人分類"""
    db = get_db()
    data = request.get_json()

    group_ids = data.get('group_ids', [])
    classification = data.get('classification', '')

    if not group_ids:
        db.close()
        return jsonify({'error': '未選擇聯絡人'}), 400

    if classification not in ('private', 'broker', 'dealer'):
        db.close()
        return jsonify({'error': '無效的分類'}), 400

    now = datetime.now().isoformat()

    # 批量更新：設定 classification 和 classification_manual = 1
    placeholders = ','.join(['?'] * len(group_ids))
    db.execute(f"""
        UPDATE contact_groups
        SET classification = ?, classification_manual = 1, updated_at = ?
        WHERE group_id IN ({placeholders})
    """, [classification, now] + group_ids)

    updated = db.total_changes
    db.commit()

    # 記錄操作日誌
    user = get_current_user()
    user_id = user['id'] if user else None
    log_operation(user_id, 'BATCH_UPDATE_CLASSIFICATION', 'contact_groups',
                  ','.join(map(str, group_ids)),
                  {'classification': classification, 'count': len(group_ids)})

    db.close()
    return jsonify({'status': 'ok', 'updated': updated})


@app.route('/api/contacts/sync-to-crm', methods=['POST'])
@login_required
def api_sync_contacts_to_crm():
    """將私人賣家同步到 CRM"""
    db = get_db()
    now = datetime.now().isoformat()

    # 找出尚未匯入的私人賣家
    rows = db.execute('''
        SELECT cg.group_id, cg.canonical_name, cg.canonical_phone,
               cg.car_count, cg.classification, cg.email, cg.intention_status
        FROM contact_groups cg
        WHERE cg.classification = 'private'
          AND cg.canonical_phone != ''
          AND cg.group_id NOT IN (SELECT COALESCE(group_id, 0) FROM crm_contacts)
    ''').fetchall()

    imported = 0
    for r in rows:
        db.execute('''
            INSERT INTO crm_contacts
            (group_id, contact_name, contact_phone, car_count, classification, email, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
        ''', (r[0], r[1], r[2], r[3], r[4], r[5] or '', now, now))
        imported += 1

    db.commit()
    db.close()
    return jsonify({'status': 'ok', 'imported': imported})



@app.route('/api/contact/<int:group_id>')
@login_required
def api_contact_detail(group_id):
    """單一聯絡人詳情 + 車輛列表 + 溝通紀錄"""
    db = get_db()
    contact = db.execute('SELECT * FROM contact_groups WHERE group_id = ?', (group_id,)).fetchone()
    if not contact:
        db.close()
        return jsonify({'error': 'not found'}), 404

    result = dict(contact)

    # 取得所有車輛（包含已售狀態）
    cars = db.execute(
        'SELECT vid, car_no, make, model, year, price, price_num, source, updated_at, is_sold FROM cars WHERE contact_group_id = ? ORDER BY is_sold ASC, first_seen DESC',
        (group_id,)
    ).fetchall()
    result['cars'] = [dict(c) for c in cars]

    # 計算在售車輛數
    result['active_car_count'] = sum(1 for c in result['cars'] if not c.get('is_sold'))

    # 取得該聯絡人所有溝通紀錄（透過 vid 或 group_id 關聯）
    vid_list = [c['vid'] for c in result['cars']]
    if vid_list:
        placeholders = ','.join(['?'] * len(vid_list))
        # 同時查詢：vid 在車輛列表中，或者 group_id 直接匹配
        # 當 vid 為 NULL 時，嘗試從 group_id 找第一輛車的資訊
        logs = db.execute(
            f'''SELECT l.*,
                COALESCE(c.make, (SELECT make FROM cars WHERE contact_group_id = l.group_id LIMIT 1)) as make,
                COALESCE(c.model, (SELECT model FROM cars WHERE contact_group_id = l.group_id LIMIT 1)) as model,
                COALESCE(c.car_no, (SELECT car_no FROM cars WHERE contact_group_id = l.group_id LIMIT 1)) as car_no
                FROM contact_logs l
                LEFT JOIN cars c ON l.vid = c.vid
                WHERE l.vid IN ({placeholders}) OR l.group_id = ?
                ORDER BY l.contacted_at DESC''',
            vid_list + [group_id]
        ).fetchall()
    else:
        # 沒有車輛時，直接用 group_id 查詢
        logs = db.execute(
            '''SELECT l.*,
                (SELECT make FROM cars WHERE contact_group_id = l.group_id LIMIT 1) as make,
                (SELECT model FROM cars WHERE contact_group_id = l.group_id LIMIT 1) as model,
                (SELECT car_no FROM cars WHERE contact_group_id = l.group_id LIMIT 1) as car_no
                FROM contact_logs l WHERE l.group_id = ? ORDER BY l.contacted_at DESC''',
            (group_id,)
        ).fetchall()
    result['logs'] = [dict(l) for l in logs]

    db.close()
    return jsonify(result)


@app.route('/api/contact/<int:group_id>/logs-summary')
@login_required
def api_contact_logs_summary(group_id):
    """取得聯絡人的溝通紀錄摘要（按車輛分組）"""
    db = get_db()

    # 取得該聯絡人的所有車輛
    cars = db.execute(
        'SELECT vid, car_no, make, model, year FROM cars WHERE contact_group_id = ? ORDER BY first_seen DESC',
        (group_id,)
    ).fetchall()

    result = []
    for car in cars:
        # 取得每輛車的溝通紀錄
        logs = db.execute(
            '''SELECT id, contacted_by, contact_method, content, contacted_at, intention_status
               FROM contact_logs WHERE vid = ? ORDER BY contacted_at DESC LIMIT 3''',
            (car['vid'],)
        ).fetchall()

        if logs:
            result.append({
                'vid': car['vid'],
                'car_no': car['car_no'],
                'car_info': f"{car['make']} {car['model']} ({car['year'] or '-'})",
                'log_count': len(logs),
                'logs': [dict(l) for l in logs]
            })

    # 也檢查 vid=NULL 但 group_id 匹配的紀錄
    orphan_logs = db.execute(
        '''SELECT id, contacted_by, contact_method, content, contacted_at, intention_status
           FROM contact_logs WHERE vid IS NULL AND group_id = ? ORDER BY contacted_at DESC''',
        (group_id,)
    ).fetchall()

    if orphan_logs:
        result.append({
            'vid': None,
            'car_no': '-',
            'car_info': '(未指定車輛)',
            'log_count': len(orphan_logs),
            'logs': [dict(l) for l in orphan_logs]
        })

    db.close()
    return jsonify({'cars': result})


@app.route('/api/car/<vid>/logs', methods=['POST'])
@login_required
def api_add_car_contact_log(vid):
    """新增溝通紀錄（透過車輛 vid）"""
    db = get_db()
    data = request.get_json()
    now = datetime.now().isoformat()

    # 確認車輛存在並取得 group_id
    car = db.execute('SELECT contact_group_id FROM cars WHERE vid = ?', (vid,)).fetchone()
    if not car:
        db.close()
        return jsonify({'error': 'Car not found'}), 404

    group_id = car['contact_group_id']

    # 誰聯絡的自動帶入登入帳號的顯示名稱
    contacted_by = request.current_user.get('display_name') or request.current_user.get('username')

    intention_status = data.get('intention_status', '')

    db.execute('''
        INSERT INTO contact_logs (vid, group_id, contacted_by, contact_method, content, contacted_at, intention_status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        vid,
        group_id,
        contacted_by,
        data.get('contact_method', ''),
        data.get('content', ''),
        data.get('contacted_at', now),
        intention_status,
        now, now
    ))

    # 同步更新 contact_groups 的意願狀態（取最新的）
    if intention_status and group_id:
        db.execute('UPDATE contact_groups SET intention_status = ? WHERE group_id = ?',
                   (intention_status, group_id))

    # 如果意願狀態為「車輛已售」，同步更新該車輛的 is_sold 狀態
    if intention_status == 'sold':
        db.execute('UPDATE cars SET is_sold = 1 WHERE vid = ?', (vid,))
        # 同步更新 contact_groups 的 active_car_count
        if group_id:
            db.execute('''UPDATE contact_groups SET 
                active_car_count = (SELECT COUNT(*) FROM cars WHERE contact_group_id = ? AND is_sold = 0)
                WHERE group_id = ?''', (group_id, group_id))
        log.info(f"車輛 {vid} 已標記為已售（透過溝通紀錄）")

    db.commit()
    log_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.close()

    # 記錄操作日誌
    log_operation(request.current_user['id'], 'ADD_CONTACT_LOG', 'contact_log', str(log_id),
                  {'vid': vid, 'group_id': group_id, 'method': data.get('contact_method', '')})

    return jsonify({'status': 'ok', 'log_id': log_id})


@app.route('/api/contact/<int:group_id>/logs', methods=['POST'])
@login_required
def api_add_contact_log(group_id):
    """新增溝通紀錄（透過聯絡人 group_id，需指定 vid）"""
    db = get_db()
    data = request.get_json()
    now = datetime.now().isoformat()

    vid = data.get('vid')  # 必須提供 vid
    if not vid:
        db.close()
        return jsonify({'error': 'vid is required'}), 400

    # 誰聯絡的自動帶入登入帳號的顯示名稱
    contacted_by = request.current_user.get('display_name') or request.current_user.get('username')

    intention_status = data.get('intention_status', '')

    db.execute('''
        INSERT INTO contact_logs (vid, group_id, contacted_by, contact_method, content, contacted_at, intention_status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        vid,
        group_id,
        contacted_by,
        data.get('contact_method', ''),
        data.get('content', ''),
        data.get('contacted_at', now),
        intention_status,
        now, now
    ))

    # 同步更新 contact_groups 的意願狀態（取最新的）
    if intention_status:
        db.execute('UPDATE contact_groups SET intention_status = ? WHERE group_id = ?',
                   (intention_status, group_id))

    # 如果意願狀態為「車輛已售」，同步更新該車輛的 is_sold 狀態
    if intention_status == 'sold' and vid:
        db.execute('UPDATE cars SET is_sold = 1 WHERE vid = ?', (vid,))
        # 同步更新 contact_groups 的 active_car_count
        db.execute('''UPDATE contact_groups SET 
            active_car_count = (SELECT COUNT(*) FROM cars WHERE contact_group_id = ? AND is_sold = 0)
            WHERE group_id = ?''', (group_id, group_id))
        log.info(f"車輛 {vid} 已標記為已售（透過溝通紀錄）")

    db.commit()
    log_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.close()

    # 記錄操作日誌
    log_operation(request.current_user['id'], 'ADD_CONTACT_LOG', 'contact_log', str(log_id),
                  {'vid': vid, 'group_id': group_id, 'method': data.get('contact_method', '')})

    return jsonify({'status': 'ok', 'log_id': log_id})


@app.route('/api/contact/log/<int:log_id>', methods=['PUT'])
@login_required
def api_update_contact_log(log_id):
    """更新溝通紀錄"""
    db = get_db()
    data = request.get_json()
    now = datetime.now().isoformat()

    # 權限檢查：只能編輯自己建立的紀錄（admin 除外）
    log_check = db.execute('SELECT contacted_by FROM contact_logs WHERE id = ?', (log_id,)).fetchone()
    if not log_check:
        db.close()
        return jsonify({'error': 'Log not found'}), 404

    current_user_name = request.current_user.get('display_name') or request.current_user.get('username')
    is_admin = request.current_user.get('role') == 'admin'
    is_owner = log_check['contacted_by'] == current_user_name

    if not is_admin and not is_owner:
        db.close()
        return jsonify({'error': '只能編輯自己建立的溝通紀錄'}), 403

    fields = []
    params = []
    # 可更新的欄位（contacted_by 不可修改）
    for key in ('contact_method', 'content', 'contacted_at', 'intention_status'):
        if key in data:
            fields.append(f'{key} = ?')
            params.append(data[key])

    if not fields:
        db.close()
        return jsonify({'error': 'no fields'}), 400

    fields.append('updated_at = ?')
    params.append(now)
    params.append(log_id)
    db.execute(f"UPDATE contact_logs SET {', '.join(fields)} WHERE id = ?", params)

    # 從資料庫取得該筆紀錄的 vid 和 group_id
    log_row = db.execute('SELECT vid, group_id FROM contact_logs WHERE id = ?', (log_id,)).fetchone()
    if not log_row:
        db.close()
        return jsonify({'error': 'Log not found'}), 404
    
    group_id = log_row['group_id']
    
    # 同步更新 contact_groups 的意願狀態（取該筆紀錄的狀態）
    intention_status = data.get('intention_status', '')
    if intention_status and group_id:
        db.execute('UPDATE contact_groups SET intention_status = ? WHERE group_id = ?',
                   (intention_status, group_id))

    # 如果意願狀態為「車輛已售」，同步更新該車輛的 is_sold 狀態
    if intention_status == 'sold' and log_row['vid']:
        db.execute('UPDATE cars SET is_sold = 1 WHERE vid = ?', (log_row['vid'],))
        # 同步更新 contact_groups 的 active_car_count
        if group_id:
            db.execute('''UPDATE contact_groups SET 
                active_car_count = (SELECT COUNT(*) FROM cars WHERE contact_group_id = ? AND is_sold = 0)
                WHERE group_id = ?''', (group_id, group_id))
        log.info(f"車輛 {log_row['vid']} 已標記為已售（透過溝通紀錄更新）")

    db.commit()
    db.close()

    # 記錄操作日誌
    log_operation(request.current_user['id'], 'UPDATE_CONTACT_LOG', 'contact_log', str(log_id),
                  {'group_id': group_id, 'fields': list(data.keys())})

    return jsonify({'status': 'ok'})


@app.route('/api/contact/log/<int:log_id>', methods=['DELETE'])
@login_required
def api_delete_contact_log(log_id):
    """刪除溝通紀錄"""
    db = get_db()

    # 先取得該筆紀錄的 group_id 和 contacted_by
    log_row = db.execute('SELECT group_id, contacted_by FROM contact_logs WHERE id = ?', (log_id,)).fetchone()
    if not log_row:
        db.close()
        return jsonify({'error': 'Log not found'}), 404

    group_id = log_row['group_id']

    # 權限檢查：只能刪除自己建立的紀錄（admin 除外）
    current_user_name = request.current_user.get('display_name') or request.current_user.get('username')
    is_admin = request.current_user.get('role') == 'admin'
    is_owner = log_row['contacted_by'] == current_user_name

    if not is_admin and not is_owner:
        db.close()
        return jsonify({'error': '只能刪除自己建立的溝通紀錄'}), 403

    # 刪除紀錄
    db.execute('DELETE FROM contact_logs WHERE id = ?', (log_id,))
    
    # 重新計算該聯絡人的意願狀態（取最新一筆紀錄的狀態）
    if group_id:
        latest = db.execute(
            """SELECT intention_status FROM contact_logs 
               WHERE group_id = ? AND intention_status IS NOT NULL AND intention_status != ''
               ORDER BY contacted_at DESC, id DESC LIMIT 1""",
            (group_id,)
        ).fetchone()
        new_intention = latest['intention_status'] if latest else None
        db.execute('UPDATE contact_groups SET intention_status = ? WHERE group_id = ?',
                   (new_intention, group_id))
    
    db.commit()
    db.close()

    # 記錄操作日誌
    log_operation(request.current_user['id'], 'DELETE_CONTACT_LOG', 'contact_log', str(log_id),
                  {'group_id': group_id})

    return jsonify({'status': 'ok'})


@app.route('/api/contacts/rebuild', methods=['POST'])
@admin_required
def api_rebuild_contacts():
    """手動觸發聯絡人分組重建（管理員專用）

    注意：這會重新計算所有群組ID，現有的 contact_logs 若使用 group_id 關聯可能會失效。
    建議所有 contact_logs 都改用 vid 關聯。
    """
    from migrate_db import rebuild_contact_groups
    db = get_db()
    db.row_factory = None
    rebuild_contact_groups(db, force=True)  # 強制重建
    db.close()
    log_operation(request.current_user['id'], 'REBUILD_CONTACTS', None, None, {})
    return jsonify({'status': 'ok', 'message': '聯絡人分組已重建'})


# ============================================================
# CRM API (Feature 3)
# ============================================================
@app.route('/api/crm/contacts')
@restricted_api
def api_crm_contacts():
    """CRM 聯絡人列表"""
    db = get_db()
    status = request.args.get('status', '')
    has_email = request.args.get('has_email', '')
    search = request.args.get('q', '')
    sort = request.args.get('sort', 'newest')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))

    where = []
    params = []

    if status:
        where.append('status = ?')
        params.append(status)
    if has_email == 'yes':
        where.append("email IS NOT NULL AND email != ''")
    elif has_email == 'no':
        where.append("(email IS NULL OR email = '')")
    if search:
        where.append('(contact_name LIKE ? OR contact_phone LIKE ? OR email LIKE ?)')
        params.extend([f'%{search}%'] * 3)

    where_sql = ' AND '.join(where) if where else '1=1'

    sort_map = {
        'newest': 'created_at DESC',
        'name': 'contact_name ASC',
        'car_count': 'car_count DESC',
        'last_sent': 'last_sent_at DESC',
        'send_count': 'send_count DESC',
    }
    order_sql = sort_map.get(sort, 'created_at DESC')

    count = db.execute(f'SELECT COUNT(*) FROM crm_contacts WHERE {where_sql}', params).fetchone()[0]

    offset = (page - 1) * per_page
    rows = db.execute(
        f'SELECT * FROM crm_contacts WHERE {where_sql} ORDER BY {order_sql} LIMIT ? OFFSET ?',
        params + [per_page, offset]
    ).fetchall()

    db.close()
    return jsonify({
        'total': count,
        'page': page,
        'per_page': per_page,
        'total_pages': (count + per_page - 1) // per_page,
        'contacts': [dict(r) for r in rows],
    })


@app.route('/api/crm/contact/<int:contact_id>')
@restricted_api
def api_crm_contact_detail(contact_id):
    db = get_db()
    contact = db.execute('SELECT * FROM crm_contacts WHERE id = ?', (contact_id,)).fetchone()
    if not contact:
        db.close()
        return jsonify({'error': 'not found'}), 404

    result = dict(contact)

    # 發送歷史
    messages = db.execute(
        'SELECT * FROM crm_messages WHERE contact_id = ? ORDER BY created_at DESC LIMIT 50',
        (contact_id,)
    ).fetchall()
    result['messages'] = [dict(m) for m in messages]

    # 相關車輛
    if result.get('group_id'):
        cars = db.execute(
            'SELECT vid, car_no, make, model, year, price FROM cars WHERE contact_group_id = ? LIMIT 20',
            (result['group_id'],)
        ).fetchall()
        result['cars'] = [dict(c) for c in cars]

    db.close()
    return jsonify(result)


@app.route('/api/crm/contact/<int:contact_id>', methods=['PUT'])
@restricted_api
def api_crm_contact_update(contact_id):
    """更新 CRM 聯絡人（email, notes, tags, status）"""
    db = get_db()
    data = request.get_json()
    now = datetime.now().isoformat()

    fields = []
    params = []
    for key in ('email', 'notes', 'tags', 'status'):
        if key in data:
            fields.append(f'{key} = ?')
            params.append(data[key])

    if not fields:
        db.close()
        return jsonify({'error': 'no fields to update'}), 400

    fields.append('updated_at = ?')
    params.append(now)
    params.append(contact_id)

    db.execute(f"UPDATE crm_contacts SET {', '.join(fields)} WHERE id = ?", params)
    db.commit()
    db.close()
    return jsonify({'status': 'ok'})


@app.route('/api/crm/contacts/import', methods=['POST'])
@restricted_api
def api_crm_import():
    """從 contact_groups 匯入私人賣家到 CRM"""
    db = get_db()
    now = datetime.now().isoformat()

    # 找出尚未匯入的私人賣家（有電話的）
    rows = db.execute('''
        SELECT cg.group_id, cg.canonical_name, cg.canonical_phone,
               cg.car_count, cg.classification
        FROM contact_groups cg
        WHERE cg.classification = 'private'
          AND cg.canonical_phone != ''
          AND cg.group_id NOT IN (SELECT COALESCE(group_id, 0) FROM crm_contacts)
    ''').fetchall()

    imported = 0
    for r in rows:
        db.execute('''
            INSERT INTO crm_contacts
            (group_id, contact_name, contact_phone, car_count, classification, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (r[0], r[1], r[2], r[3], r[4], now, now))
        imported += 1

    db.commit()
    db.close()
    return jsonify({'status': 'ok', 'imported': imported})


@app.route('/api/crm/contacts/export')
@restricted_api
def api_crm_export():
    """匯出 CRM 聯絡人為 CSV"""
    db = get_db()
    rows = db.execute(
        'SELECT contact_name, contact_phone, email, car_count, classification, status, send_count, last_sent_at, notes FROM crm_contacts ORDER BY contact_name'
    ).fetchall()
    db.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['姓名', '電話', 'Email', '車輛數', '分類', '狀態', '發送次數', '最後發送', '備註'])
    for r in rows:
        writer.writerow(list(r))

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=crm_contacts.csv'}
    )


# ============================================================
# CRM 活動 API
# ============================================================
@app.route('/api/crm/campaigns')
@restricted_api
def api_crm_campaigns():
    db = get_db()
    rows = db.execute('SELECT * FROM crm_campaigns ORDER BY created_at DESC').fetchall()
    db.close()
    return jsonify({'campaigns': [dict(r) for r in rows]})


@app.route('/api/crm/campaigns', methods=['POST'])
@restricted_api
def api_crm_campaign_create():
    db = get_db()
    data = request.get_json()
    now = datetime.now().isoformat()

    db.execute('''
        INSERT INTO crm_campaigns (name, type, template, status, target_filter, created_at, updated_at)
        VALUES (?, ?, ?, 'draft', ?, ?, ?)
    ''', (data.get('name', ''), data.get('type', 'sms'), data.get('template', ''),
          json.dumps(data.get('target_filter', {})), now, now))
    db.commit()
    campaign_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.close()
    return jsonify({'status': 'ok', 'campaign_id': campaign_id})


@app.route('/api/crm/campaign/<int:campaign_id>')
@restricted_api
def api_crm_campaign_detail(campaign_id):
    db = get_db()
    campaign = db.execute('SELECT * FROM crm_campaigns WHERE id = ?', (campaign_id,)).fetchone()
    if not campaign:
        db.close()
        return jsonify({'error': 'not found'}), 404

    result = dict(campaign)
    msgs = db.execute(
        'SELECT status, COUNT(*) as cnt FROM crm_messages WHERE campaign_id = ? GROUP BY status',
        (campaign_id,)
    ).fetchall()
    result['message_stats'] = {m[0]: m[1] for m in msgs}

    db.close()
    return jsonify(result)




@app.route('/api/crm/campaign/<int:campaign_id>', methods=['PUT'])
@restricted_api
def api_crm_campaign_update(campaign_id):
    db = get_db()
    data = request.get_json()
    now = datetime.now().isoformat()

    fields = []
    params = []
    for key in ('name', 'type', 'template', 'target_filter', 'status'):
        if key in data:
            if key == 'target_filter':
                fields.append(key + ' = ?')
                params.append(json.dumps(data[key]))
            else:
                fields.append(key + ' = ?')
                params.append(data[key])

    if not fields:
        db.close()
        return jsonify({'error': 'no fields to update'}), 400

    fields.append('updated_at = ?')
    params.append(now)
    params.append(campaign_id)

    sql = "UPDATE crm_campaigns SET " + ', '.join(fields) + " WHERE id = ?"
    db.execute(sql, params)
    db.commit()
    db.close()
    return jsonify({'status': 'ok'})


@app.route('/api/crm/campaign/<int:campaign_id>', methods=['DELETE'])
@restricted_api
def api_crm_campaign_delete(campaign_id):
    db = get_db()
    db.execute('DELETE FROM crm_messages WHERE campaign_id = ?', (campaign_id,))
    db.execute('DELETE FROM crm_campaigns WHERE id = ?', (campaign_id,))
    db.commit()
    db.close()
    return jsonify({'status': 'ok'})


@app.route('/api/crm/campaign/<int:campaign_id>/execute', methods=['POST'])
@restricted_api
def api_crm_campaign_execute(campaign_id):
    db = get_db()
    now = datetime.now().isoformat()
    today = datetime.now().date().isoformat()

    campaign = db.execute('SELECT * FROM crm_campaigns WHERE id = ?', (campaign_id,)).fetchone()
    if not campaign:
        db.close()
        return jsonify({'error': 'campaign not found'}), 404

    campaign = dict(campaign)

    try:
        target_filter = json.loads(campaign.get('target_filter') or '{}')
    except:
        target_filter = {}

    where = ["cg.canonical_phone != ''"]
    params = []

    classification = target_filter.get('classification', '')
    if classification:
        where.append('cg.classification = ?')
        params.append(classification)

    intention = target_filter.get('intention', '')
    if intention:
        where.append('cg.intention_status = ?')
        params.append(intention)

    car_count = target_filter.get('car_count', '')
    if car_count == '1':
        where.append('cg.car_count = 1')
    elif car_count == '2-4':
        where.append('cg.car_count BETWEEN 2 AND 4')
    elif car_count == '5+':
        where.append('cg.car_count >= 5')

    exclude_sent = target_filter.get('exclude_sent', 'yes')
    if exclude_sent == 'yes':
        where.append("cg.canonical_phone NOT IN (SELECT phone FROM sms_logs WHERE DATE(sent_at) = ? AND status IN ('success', 'pending'))")
        params.append(today)

    where_sql = ' AND '.join(where)
    sql = "SELECT cg.group_id, cg.canonical_name, cg.canonical_phone, cg.car_count, cg.email FROM contact_groups cg WHERE " + where_sql + " LIMIT 1000"
    rows = db.execute(sql, params).fetchall()

    template = campaign.get('template', '')
    msg_type = campaign.get('type', 'sms')

    sent = 0
    failed = 0

    for r in rows:
        contact = {
            'group_id': r[0],
            'contact_name': r[1],
            'contact_phone': r[2],
            'car_count': r[3],
            'email': r[4] or ''
        }

        content_text = template
        content_text = content_text.replace('{{name}}', contact.get('contact_name', ''))
        content_text = content_text.replace('{{phone}}', contact.get('contact_phone', ''))
        content_text = content_text.replace('{{car_count}}', str(contact.get('car_count', 0)))
        content_text = content_text.replace('{{email}}', contact.get('email', ''))

        recipient = contact.get('contact_phone', '') if msg_type == 'sms' else contact.get('email', '')

        if not recipient:
            failed += 1
            continue

        db.execute("INSERT INTO crm_messages (campaign_id, contact_id, type, recipient, content, status, created_at) VALUES (?, (SELECT id FROM crm_contacts WHERE group_id = ?), ?, ?, ?, 'pending', ?)",
                   (campaign_id, contact['group_id'], msg_type, recipient, content_text, now))
        sent += 1

    db.execute("UPDATE crm_campaigns SET status = 'executing', total_targets = ?, updated_at = ? WHERE id = ?",
               (sent + failed, now, campaign_id))

    db.commit()
    db.close()
    return jsonify({'status': 'ok', 'queued': sent, 'skipped': failed})


@app.route('/api/crm/campaign/<int:campaign_id>/messages')
@restricted_api
def api_crm_campaign_messages(campaign_id):
    db = get_db()
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    offset = (page - 1) * per_page

    total = db.execute('SELECT COUNT(*) FROM crm_messages WHERE campaign_id = ?', (campaign_id,)).fetchone()[0]
    rows = db.execute(
        'SELECT m.*, c.contact_name, c.contact_phone FROM crm_messages m LEFT JOIN crm_contacts c ON m.contact_id = c.id WHERE m.campaign_id = ? ORDER BY m.created_at DESC LIMIT ? OFFSET ?',
        (campaign_id, per_page, offset)
    ).fetchall()

    db.close()
    return jsonify({
        'total': total,
        'page': page,
        'messages': [dict(r) for r in rows],
    })


@app.route('/api/crm/campaign/<int:campaign_id>/send', methods=['POST'])
@restricted_api
def api_crm_campaign_send(campaign_id):
    """執行活動發送"""
    db = get_db()
    now = datetime.now().isoformat()

    campaign = db.execute('SELECT * FROM crm_campaigns WHERE id = ?', (campaign_id,)).fetchone()
    if not campaign:
        db.close()
        return jsonify({'error': 'campaign not found'}), 404

    campaign = dict(campaign)
    data = request.get_json() or {}
    contact_ids = data.get('contact_ids', [])

    if not contact_ids:
        db.close()
        return jsonify({'error': 'no contacts selected'}), 400

    template = campaign.get('template', '')
    msg_type = campaign.get('type', 'sms')

    sent = 0
    failed = 0

    for cid in contact_ids:
        contact = db.execute('SELECT * FROM crm_contacts WHERE id = ?', (cid,)).fetchone()
        if not contact:
            continue
        contact = dict(contact)

        # 渲染模板
        content = _render_template(template, contact)
        recipient = contact.get('contact_phone', '') if msg_type == 'sms' else contact.get('email', '')

        if not recipient:
            # 建立失敗記錄
            db.execute('''
                INSERT INTO crm_messages (campaign_id, contact_id, type, recipient, content, status, error_message, created_at)
                VALUES (?, ?, ?, ?, ?, 'failed', '無收件人', ?)
            ''', (campaign_id, cid, msg_type, '', content, now))
            failed += 1
            continue

        # 發送
        success = False
        external_id = ''
        error_msg = ''

        if msg_type == 'sms':
            success, result = _send_sms(recipient, content)
            if success:
                external_id = result
            else:
                error_msg = result
        elif msg_type == 'email':
            subject = campaign.get('name', '28car 通知')
            success, result = _send_email(recipient, subject, content)
            if not success:
                error_msg = result

        status = 'sent' if success else 'failed'
        db.execute('''
            INSERT INTO crm_messages (campaign_id, contact_id, type, recipient, content, status, external_id, error_message, sent_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (campaign_id, cid, msg_type, recipient, content, status,
              external_id, error_msg, now if success else None, now))

        # 更新聯絡人
        db.execute('''
            UPDATE crm_contacts SET send_count = send_count + 1, last_sent_at = ?, updated_at = ? WHERE id = ?
        ''', (now, now, cid))

        if success:
            sent += 1
        else:
            failed += 1

    # 更新活動統計
    db.execute('''
        UPDATE crm_campaigns SET
            status = 'completed',
            sent_count = sent_count + ?,
            failed_count = failed_count + ?,
            total_targets = total_targets + ?,
            updated_at = ?
        WHERE id = ?
    ''', (sent, failed, len(contact_ids), now, campaign_id))

    db.commit()
    db.close()
    return jsonify({'status': 'ok', 'sent': sent, 'failed': failed})


@app.route('/api/crm/config')
@restricted_api
def api_crm_config():
    """檢查 SMS/Email 設定狀態"""
    return jsonify({
        'sms_configured': bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER),
        'email_configured': bool(SMTP_HOST and SMTP_USER),
    })


# ============================================================
# SMS / Email 發送
# ============================================================
def _send_sms(to_phone, body):
    if not TWILIO_ACCOUNT_SID:
        return False, 'Twilio 未設定'
    try:
        from twilio.rest import Client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        if not to_phone.startswith('+'):
            to_phone = '+852' + to_phone
        message = client.messages.create(body=body, from_=TWILIO_FROM_NUMBER, to=to_phone)
        return True, message.sid
    except Exception as e:
        return False, str(e)


def _send_email(to_email, subject, body):
    if not SMTP_HOST:
        return False, 'SMTP 未設定'
    try:
        import smtplib
        from email.mime.text import MIMEText
        msg = MIMEText(body, 'plain', 'utf-8')
        msg['Subject'] = subject
        msg['From'] = SMTP_FROM
        msg['To'] = to_email
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        return True, None
    except Exception as e:
        return False, str(e)


def _render_template(template, contact):
    """替換模板佔位符"""
    result = template
    result = result.replace('{{name}}', contact.get('contact_name', ''))
    result = result.replace('{{phone}}', contact.get('contact_phone', ''))
    result = result.replace('{{car_count}}', str(contact.get('car_count', 0)))
    result = result.replace('{{email}}', contact.get('email', '') or '')
    return result


# ============================================================
# 圖片靜態文件
# ============================================================
@app.route('/images/<path:filename>')
def serve_image(filename):
    return send_from_directory(os.path.join(BASE_DIR, 'images'), filename)


# ============================================================
# SMS 簡訊系統 API
# ============================================================

@app.route('/api/sms/templates')
@restricted_api
def api_sms_templates():
    """取得簡訊模板列表"""
    db = get_db()
    rows = db.execute('SELECT * FROM sms_templates ORDER BY is_active DESC, id DESC').fetchall()
    db.close()
    return jsonify({'templates': [dict(r) for r in rows]})


@app.route('/api/sms/templates', methods=['POST'])
@restricted_api
def api_sms_template_create():
    """新增簡訊模板"""
    db = get_db()
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    content = data.get('content', '').strip()

    if not name or not content:
        db.close()
        return jsonify({'error': 'name and content required'}), 400

    now = datetime.now().isoformat()
    c = db.cursor()
    # 先將其他模板停用，新模板設為啟用
    c.execute('UPDATE sms_templates SET is_active = 0')
    c.execute('INSERT INTO sms_templates (name, content, is_active, created_at, updated_at) VALUES (?, ?, 1, ?, ?)',
              (name, content, now, now))
    db.commit()
    template_id = c.lastrowid
    db.close()
    return jsonify({'success': True, 'id': template_id})


@app.route('/api/sms/templates/<int:template_id>', methods=['PUT'])
@restricted_api
def api_sms_template_update(template_id):
    """更新簡訊模板"""
    db = get_db()
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    content = data.get('content', '').strip()
    is_active = data.get('is_active', 1)

    if not name or not content:
        db.close()
        return jsonify({'error': 'name and content required'}), 400

    now = datetime.now().isoformat()
    # 如果要啟用此模板，先關閉其他模板（確保只有一個啟用）
    if is_active:
        db.execute('UPDATE sms_templates SET is_active = 0')
    db.execute('UPDATE sms_templates SET name=?, content=?, is_active=?, updated_at=? WHERE id=?',
               (name, content, is_active, now, template_id))
    db.commit()
    db.close()
    return jsonify({'success': True})


@app.route('/api/sms/templates/<int:template_id>', methods=['DELETE'])
@restricted_api
def api_sms_template_delete(template_id):
    """刪除簡訊模板"""
    db = get_db()
    db.execute('DELETE FROM sms_templates WHERE id=?', (template_id,))
    db.commit()
    db.close()
    return jsonify({'success': True})


@app.route('/api/sms/templates/<int:template_id>/activate', methods=['POST'])
@restricted_api
def api_sms_template_activate(template_id):
    """設為啟用模板（其他模板取消啟用）"""
    db = get_db()
    db.execute('UPDATE sms_templates SET is_active = 0')
    db.execute('UPDATE sms_templates SET is_active = 1 WHERE id = ?', (template_id,))
    db.commit()
    db.close()
    return jsonify({'success': True})


@app.route('/api/sms/logs')
@restricted_api
def api_sms_logs():
    """取得簡訊發送記錄"""
    db = get_db()
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    status = request.args.get('status', '')
    date_filter = request.args.get('date', '')

    where = []
    params = []

    if status:
        where.append('sl.status = ?')
        params.append(status)
    if date_filter:
        where.append('DATE(sl.sent_at) = ?')
        params.append(date_filter)

    where_sql = ' AND '.join(where) if where else '1=1'
    offset = (page - 1) * per_page

    total = db.execute(f'SELECT COUNT(*) FROM sms_logs sl WHERE {where_sql}', params).fetchone()[0]
    rows = db.execute(f'''
        SELECT sl.*, cg.canonical_name, st.name as template_name
        FROM sms_logs sl
        LEFT JOIN contact_groups cg ON sl.group_id = cg.group_id
        LEFT JOIN sms_templates st ON sl.template_id = st.id
        WHERE {where_sql}
        ORDER BY sl.sent_at DESC
        LIMIT ? OFFSET ?
    ''', params + [per_page, offset]).fetchall()

    db.close()
    return jsonify({
        'logs': [dict(r) for r in rows],
        'total': total,
        'page': page,
        'total_pages': (total + per_page - 1) // per_page,
    })


@app.route('/api/sms/stats')
@restricted_api
def api_sms_stats():
    """取得簡訊統計"""
    db = get_db()
    today = datetime.now().date().isoformat()

    stats = {}

    # 總發送數
    stats['total_sent'] = db.execute('SELECT COUNT(*) FROM sms_logs').fetchone()[0]
    stats['total_success'] = db.execute("SELECT COUNT(*) FROM sms_logs WHERE status='success'").fetchone()[0]
    stats['total_failed'] = db.execute("SELECT COUNT(*) FROM sms_logs WHERE status='failed'").fetchone()[0]

    # 今日發送數
    stats['today_sent'] = db.execute('SELECT COUNT(*) FROM sms_logs WHERE DATE(sent_at) = ?', (today,)).fetchone()[0]
    stats['today_success'] = db.execute("SELECT COUNT(*) FROM sms_logs WHERE DATE(sent_at) = ? AND status='success'", (today,)).fetchone()[0]

    # 最近一次發送任務
    last_run = db.execute('SELECT * FROM sms_daily_runs ORDER BY started_at DESC LIMIT 1').fetchone()
    stats['last_run'] = dict(last_run) if last_run else None

    # 目前啟用模板
    active_template = db.execute('SELECT id, name FROM sms_templates WHERE is_active = 1 LIMIT 1').fetchone()
    stats['active_template'] = dict(active_template) if active_template else None

    # 待發送的私人賣家數量
    stats['pending_private'] = db.execute('''
        SELECT COUNT(*) FROM contact_groups
        WHERE classification = 'private'
        AND canonical_phone IS NOT NULL AND canonical_phone != ''
        AND canonical_phone NOT IN (
            SELECT phone FROM sms_logs WHERE DATE(sent_at) = ? AND status IN ('success', 'pending')
        )
    ''', (today,)).fetchone()[0]

    db.close()
    return jsonify(stats)


@app.route('/api/sms/daily-runs')
@restricted_api
def api_sms_daily_runs():
    """取得每日發送記錄"""
    db = get_db()
    limit = int(request.args.get('limit', 30))
    rows = db.execute('SELECT * FROM sms_daily_runs ORDER BY run_date DESC LIMIT ?', (limit,)).fetchall()
    db.close()
    return jsonify({'runs': [dict(r) for r in rows]})


@app.route('/api/sms/config')
@restricted_api
def api_sms_config():
    """取得 SMS 設定（不含密碼）"""
    config_path = os.path.join(BASE_DIR, 'sms_config.json')
    if not os.path.exists(config_path):
        return jsonify({'error': 'config not found'}), 404

    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    # 隱藏密碼
    if 'onewaysms' in config:
        config['onewaysms']['api_password'] = '******' if config['onewaysms'].get('api_password') else ''

    return jsonify(config)


@app.route('/api/sms/config', methods=['PUT'])
@restricted_api
def api_sms_config_update():
    """更新 SMS 設定"""
    config_path = os.path.join(BASE_DIR, 'sms_config.json')

    # 讀取現有設定
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    else:
        config = {'onewaysms': {}, 'settings': {}}

    data = request.get_json() or {}

    # 更新 onewaysms 設定
    if 'onewaysms' in data:
        for key in ['enabled', 'api_url', 'api_username', 'sender_id', 'language_type']:
            if key in data['onewaysms']:
                config['onewaysms'][key] = data['onewaysms'][key]
        # 密碼只有在非 ****** 時才更新
        if data['onewaysms'].get('api_password') and data['onewaysms']['api_password'] != '******':
            config['onewaysms']['api_password'] = data['onewaysms']['api_password']

    # 更新 settings
    if 'settings' in data:
        for key in ['daily_limit', 'target_classification', 'send_window_start', 'send_window_end', 'delay_between_sms']:
            if key in data['settings']:
                config['settings'][key] = data['settings'][key]

    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=4)

    return jsonify({'success': True})




@app.route('/api/sms/source-stats')
@restricted_api
def api_sms_source_stats():
    """取得各發送來源的統計數量"""
    db = get_db()
    today = datetime.now().date().isoformat()

    stats = {}

    # 私人賣家數量
    private_count = db.execute("""
        SELECT COUNT(*) FROM contact_groups cg
        WHERE cg.classification = 'private'
          AND cg.canonical_phone IS NOT NULL
          AND cg.canonical_phone != ''
          AND cg.canonical_phone NOT IN (
              SELECT phone FROM sms_logs
              WHERE DATE(sent_at) = ? AND status IN ('success', 'pending')
          )
    """, (today,)).fetchone()[0]
    stats['private'] = private_count

    # 今日新增/更新的私人賣家
    today_new_count = db.execute("""
        SELECT COUNT(DISTINCT cg.group_id) FROM contact_groups cg
        INNER JOIN cars c ON c.contact_group_id = cg.group_id
        WHERE cg.classification = 'private'
          AND cg.canonical_phone IS NOT NULL
          AND cg.canonical_phone != ''
          AND (DATE(c.scraped_at) = ? OR DATE(c.updated_at) = ?)
          AND cg.canonical_phone NOT IN (
              SELECT phone FROM sms_logs
              WHERE DATE(sent_at) = ? AND status IN ('success', 'pending')
          )
    """, (today, today, today)).fetchone()[0]
    stats['today_new'] = today_new_count

    stats['crm_campaign'] = 0
    db.close()
    return jsonify(stats)


@app.route('/api/sms/send-now', methods=['POST'])
@restricted_api
def api_sms_send_now():
    """立即發送簡訊"""
    import subprocess
    import sys

    data = request.get_json() or {}
    config_path = os.path.join(BASE_DIR, 'sms_config.json')

    if not os.path.exists(config_path):
        return jsonify({'success': False, 'error': '設定檔不存在'}), 400

    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    if not config.get('onewaysms', {}).get('api_username'):
        return jsonify({'success': False, 'error': 'API 帳號未設定'}), 400

    if not config.get('onewaysms', {}).get('api_password'):
        return jsonify({'success': False, 'error': 'API 密碼未設定'}), 400

    try:
        cmd = get_script_command('sms', ['--daily'])
        if not cmd:
            return jsonify({'success': False, 'error': '找不到簡訊程式 (exe 或 py)'}), 400

        subprocess.Popen(cmd, cwd=BASE_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jsonify({'success': True, 'message': '簡訊發送任務已啟動'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# 管理後台 API
# ============================================================
@app.route('/api/admin/users')
@admin_required
def api_admin_users():
    """取得使用者列表"""
    db = get_db()
    users = db.execute('''
        SELECT id, username, display_name, role, is_active, must_change_pwd,
               last_login_at, created_at, updated_at
        FROM users ORDER BY id
    ''').fetchall()
    db.close()
    return jsonify({'users': [dict(u) for u in users]})


@app.route('/api/admin/users', methods=['POST'])
@admin_required
def api_admin_create_user():
    """新增使用者"""
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    display_name = data.get('display_name', '').strip() or username
    role = data.get('role', 'user')
    must_change_pwd = data.get('must_change_pwd', 1)

    if not username or not password:
        return jsonify({'error': '請輸入帳號和密碼'}), 400

    if len(password) < 6:
        return jsonify({'error': '密碼至少需要6個字元'}), 400

    if role not in ('admin', 'user'):
        role = 'user'

    db = get_db()
    existing = db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
    if existing:
        db.close()
        return jsonify({'error': '帳號已存在'}), 400

    now = datetime.now().isoformat()
    password_hash = hash_password(password)
    db.execute('''
        INSERT INTO users (username, password_hash, display_name, role, is_active, must_change_pwd, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, ?, ?, ?)
    ''', (username, password_hash, display_name, role, must_change_pwd, now, now))
    db.commit()
    user_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.close()

    log_operation(request.current_user['id'], 'CREATE_USER', 'user', str(user_id),
                  {'username': username, 'role': role})

    return jsonify({'success': True, 'user_id': user_id})


@app.route('/api/admin/users/<int:user_id>', methods=['PUT'])
@admin_required
def api_admin_update_user(user_id):
    """更新使用者"""
    data = request.get_json()
    db = get_db()

    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        db.close()
        return jsonify({'error': '使用者不存在'}), 404

    updates = []
    params = []
    changes = {}

    if 'display_name' in data:
        updates.append('display_name = ?')
        params.append(data['display_name'])
        changes['display_name'] = data['display_name']

    if 'role' in data and data['role'] in ('admin', 'user'):
        updates.append('role = ?')
        params.append(data['role'])
        changes['role'] = data['role']

    if 'is_active' in data:
        updates.append('is_active = ?')
        params.append(1 if data['is_active'] else 0)
        changes['is_active'] = data['is_active']

    if 'password' in data and data['password']:
        if len(data['password']) < 6:
            db.close()
            return jsonify({'error': '密碼至少需要6個字元'}), 400
        updates.append('password_hash = ?')
        params.append(hash_password(data['password']))
        updates.append('must_change_pwd = ?')
        params.append(data.get('must_change_pwd', 0))
        changes['password_changed'] = True

    if 'must_change_pwd' in data and 'password' not in data:
        updates.append('must_change_pwd = ?')
        params.append(1 if data['must_change_pwd'] else 0)
        changes['must_change_pwd'] = data['must_change_pwd']

    if updates:
        updates.append('updated_at = ?')
        params.append(datetime.now().isoformat())
        params.append(user_id)
        db.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
        db.commit()

        log_operation(request.current_user['id'], 'UPDATE_USER', 'user', str(user_id), changes)

    db.close()
    return jsonify({'success': True})


@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@admin_required
def api_admin_delete_user(user_id):
    """刪除使用者"""
    db = get_db()

    user = db.execute('SELECT username FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        db.close()
        return jsonify({'error': '使用者不存在'}), 404

    if user['username'] == 'admin':
        db.close()
        return jsonify({'error': '無法刪除預設管理員帳號'}), 400

    db.execute('DELETE FROM sessions WHERE user_id = ?', (user_id,))
    db.execute('DELETE FROM users WHERE id = ?', (user_id,))
    db.commit()
    db.close()

    log_operation(request.current_user['id'], 'DELETE_USER', 'user', str(user_id),
                  {'username': user['username']})

    return jsonify({'success': True})


@app.route('/api/admin/logs')
@admin_required
def api_admin_logs():
    """操作日誌查詢"""
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    action = request.args.get('action', '')
    username = request.args.get('username', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    db = get_db()
    where = []
    params = []

    if action:
        where.append('action = ?')
        params.append(action)
    if username:
        where.append('username LIKE ?')
        params.append(f'%{username}%')
    if date_from:
        where.append('created_at >= ?')
        params.append(date_from)
    if date_to:
        where.append('created_at <= ?')
        params.append(date_to + 'T23:59:59')

    where_sql = 'WHERE ' + ' AND '.join(where) if where else ''

    total = db.execute(f'SELECT COUNT(*) FROM operation_logs {where_sql}', params).fetchone()[0]

    offset = (page - 1) * per_page
    logs = db.execute(f'''
        SELECT * FROM operation_logs {where_sql}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    ''', params + [per_page, offset]).fetchall()

    db.close()

    return jsonify({
        'logs': [dict(l) for l in logs],
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page
    })


@app.route('/api/admin/logs/clear', methods=['POST'])
@admin_required
def api_admin_clear_logs():
    """清理操作日誌"""
    data = request.get_json() or {}
    days = int(data.get('days', 30))  # 預設保留 30 天

    db = get_db()
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    # 統計要刪除的數量
    count = db.execute('SELECT COUNT(*) FROM operation_logs WHERE created_at < ?', (cutoff,)).fetchone()[0]

    if count > 0:
        db.execute('DELETE FROM operation_logs WHERE created_at < ?', (cutoff,))
        db.commit()

    db.close()

    # 記錄清理操作
    log_operation(request.current_user['id'], 'CLEAR_LOGS', 'operation_logs', None,
                  {'days': days, 'deleted_count': count})

    return jsonify({'status': 'ok', 'deleted': count, 'kept_days': days})


@app.route('/api/admin/settings')
@admin_required
def api_admin_settings():
    """取得系統設定"""
    db = get_db()
    settings = db.execute('SELECT key, value, description, updated_at FROM system_settings').fetchall()
    db.close()
    return jsonify({'settings': {s['key']: {'value': s['value'], 'description': s['description'], 'updated_at': s['updated_at']} for s in settings}})


@app.route('/api/admin/settings', methods=['PUT'])
@admin_required
def api_admin_update_settings():
    """更新系統設定"""
    data = request.get_json()
    db = get_db()
    now = datetime.now().isoformat()
    changes = {}

    for key, value in data.items():
        existing = db.execute('SELECT key FROM system_settings WHERE key = ?', (key,)).fetchone()
        if existing:
            db.execute('UPDATE system_settings SET value = ?, updated_by = ?, updated_at = ? WHERE key = ?',
                      (value, request.current_user['id'], now, key))
        else:
            db.execute('INSERT INTO system_settings (key, value, updated_by, updated_at) VALUES (?, ?, ?, ?)',
                      (key, value, request.current_user['id'], now))
        changes[key] = value

    db.commit()
    db.close()

    log_operation(request.current_user['id'], 'UPDATE_SETTINGS', 'settings', None, changes)

    return jsonify({'success': True})


@app.route('/api/admin/network-info')
@admin_required
def api_admin_network_info():
    """取得區域網路資訊"""
    hostname = socket.gethostname()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
        s.close()
    except:
        local_ip = '127.0.0.1'

    return jsonify({
        'hostname': hostname,
        'local_ip': local_ip,
        'port': 5000,
        'url': f'http://{local_ip}:5000'
    })


def compare_versions(v1, v2):
    """比較版本號，回傳: -1 (v1<v2), 0 (v1==v2), 1 (v1>v2)"""
    def parse_version(v):
        v = v.lstrip('v')
        return [int(x) for x in v.split('.')]

    try:
        p1, p2 = parse_version(v1), parse_version(v2)
        for a, b in zip(p1, p2):
            if a < b: return -1
            if a > b: return 1
        return len(p1) - len(p2)
    except:
        return 0


def get_git_executable():
    """取得 Git 執行檔路徑，優先使用 MinGit"""
    import shutil

    # 優先使用 MinGit（安裝包內附的）
    mingit_path = os.path.join(BASE_DIR, 'MinGit', 'cmd', 'git.exe')
    if os.path.exists(mingit_path):
        return mingit_path

    # 其次使用系統 Git
    system_git = shutil.which('git')
    if system_git:
        return system_git

    return None


@app.route('/api/admin/check-update')
@admin_required
def api_admin_check_update():
    """檢查程式更新（從 GitHub Release）"""
    import urllib.request
    import ssl

    try:
        url = f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest'

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(url, headers={'User-Agent': '28car-system'})

        try:
            with urllib.request.urlopen(req, timeout=30, context=ctx) as response:
                data = json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return jsonify({
                    'has_update': False,
                    'local_version': APP_VERSION,
                    'remote_version': None,
                    'message': '尚無發布版本'
                })
            raise

        remote_version = data.get('tag_name', '').lstrip('v')
        release_notes = data.get('body', '')
        release_url = data.get('html_url', '')

        download_url = None
        for asset in data.get('assets', []):
            if asset['name'].endswith('.exe') or asset['name'].endswith('.zip'):
                download_url = asset['browser_download_url']
                break

        has_update = compare_versions(APP_VERSION, remote_version) < 0

        return jsonify({
            'has_update': has_update,
            'local_version': APP_VERSION,
            'remote_version': remote_version,
            'release_notes': release_notes,
            'release_url': release_url,
            'download_url': download_url
        })

    except Exception as e:
        return jsonify({'error': f'檢查更新失敗: {str(e)}', 'has_update': False, 'local_version': APP_VERSION})


@app.route('/api/admin/do-update', methods=['POST'])
@admin_required
def api_admin_do_update():
    """執行程式更新（git pull）"""
    import subprocess

    git_exe = get_git_executable()

    if not git_exe:
        return jsonify({'success': False, 'error': 'Git 未安裝'})

    try:
        result = subprocess.run(
            [git_exe, 'pull', 'origin', 'main', '--ff-only'],
            capture_output=True, text=True, cwd=BASE_DIR
        )

        if result.returncode == 0:
            return jsonify({
                'success': True,
                'message': '更新完成！請重新啟動伺服器以套用更新。',
                'output': result.stdout
            })
        else:
            return jsonify({
                'success': False,
                'message': '更新失敗',
                'error': result.stderr
            })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ============================================================
# 遠端日誌查看 API
# ============================================================

@app.route('/api/admin/system-logs')
@admin_required
def api_admin_system_logs():
    """列出可用的日誌檔案"""
    log_files = []
    for filename in ['scraper.log', 'sms_sender.log', 'daily_task.log', 'server.log']:
        filepath = os.path.join(BASE_DIR, filename)
        if os.path.exists(filepath):
            stat = os.stat(filepath)
            log_files.append({
                'name': filename,
                'size': stat.st_size,
                'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            })
    return jsonify({'logs': log_files})


@app.route('/api/admin/system-logs/<filename>')
@admin_required
def api_admin_system_log_content(filename):
    """讀取指定日誌檔案內容"""
    # 安全檢查：只允許讀取特定日誌檔案
    allowed_logs = ['scraper.log', 'sms_sender.log', 'daily_task.log', 'server.log']
    if filename not in allowed_logs:
        return jsonify({'error': '不允許讀取此檔案'}), 403

    filepath = os.path.join(BASE_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({'error': '檔案不存在'}), 404

    # 讀取最後 N 行（預設 200 行）
    lines = request.args.get('lines', 200, type=int)
    lines = min(lines, 1000)  # 最多 1000 行

    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            all_lines = f.readlines()
            tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
            return jsonify({
                'filename': filename,
                'total_lines': len(all_lines),
                'returned_lines': len(tail),
                'content': ''.join(tail)
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================
# 排程管理 API
# ============================================================

@app.route('/api/admin/schedules')
@admin_required
def api_admin_schedules():
    """取得排程設定"""
    import subprocess

    schedules = {
        'scraper': {'name': '28car_daily', 'time': None, 'enabled': False, 'description': '每日爬蟲',
                    'last_run': None, 'last_status': None, 'last_result': None},
        'backup': {'name': '28car_backup', 'time': None, 'enabled': False, 'description': '每日備份',
                   'last_run': None, 'last_status': None, 'last_result': None},
        'sms': {'name': '28car_sms', 'time': None, 'enabled': False, 'description': '每日簡訊',
                'last_run': None, 'last_status': None, 'last_result': None}
    }

    try:
        # 使用 schtasks 查詢排程
        for key, info in schedules.items():
            result = subprocess.run(
                ['schtasks', '/query', '/tn', info['name'], '/fo', 'list', '/v'],
                capture_output=True, text=True, encoding='cp950', errors='ignore'
            )
            if result.returncode == 0:
                schedules[key]['enabled'] = True
                # 解析開始時間
                for line in result.stdout.split('\n'):
                    if '開始時間' in line or 'Start Time' in line:
                        parts = line.split(':', 1)
                        if len(parts) > 1:
                            time_str = parts[1].strip()
                            # 嘗試提取 HH:MM 格式
                            import re
                            match = re.search(r'(\d{1,2}):(\d{2})', time_str)
                            if match:
                                schedules[key]['time'] = f"{int(match.group(1)):02d}:{match.group(2)}"
    except Exception as e:
        log.error(f"查詢排程失敗: {e}")

    # 取得爬蟲最後執行資訊
    try:
        db = get_db()
        last_run = db.execute(
            '''SELECT started_at, finished_at, status, new_cars, updated_cars, unchanged_cars
               FROM scraper_runs ORDER BY started_at DESC LIMIT 1'''
        ).fetchone()
        db.close()
        if last_run:
            schedules['scraper']['last_run'] = last_run['finished_at'] or last_run['started_at']
            schedules['scraper']['last_status'] = last_run['status']
            # status 可能是 'success', 'completed', 'running', 'failed' 等
            if last_run['status'] in ('success', 'completed'):
                schedules['scraper']['last_result'] = f"新增 {last_run['new_cars']} / 更新 {last_run['updated_cars']} / 無變動 {last_run['unchanged_cars']}"
            elif last_run['status'] == 'running':
                schedules['scraper']['last_result'] = '執行中...'
            else:
                schedules['scraper']['last_result'] = '執行失敗'
    except Exception as e:
        log.error(f"查詢爬蟲記錄失敗: {e}")

    # 讀取 daily_task.log 的最近執行紀錄
    schedules['daily_log'] = []
    try:
        daily_log_path = os.path.join(BASE_DIR, 'daily_task.log')
        if os.path.exists(daily_log_path):
            with open(daily_log_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()[-30:]  # 最近 30 行
                schedules['daily_log'] = [line.strip() for line in lines if line.strip()]
    except Exception as e:
        log.error(f"讀取每日任務日誌失敗: {e}")

    # 取得備份最後執行資訊
    try:
        backup_log_path = os.path.join(BASE_DIR, 'backup', 'backup.log')
        if os.path.exists(backup_log_path):
            with open(backup_log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                if lines:
                    last_line = lines[-1].strip()
                    # 格式: [2026-02-11 05:00:00] 備份成功: ...
                    import re
                    match = re.match(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] (.+)', last_line)
                    if match:
                        schedules['backup']['last_run'] = match.group(1)
                        result_text = match.group(2)
                        if '成功' in result_text:
                            schedules['backup']['last_status'] = 'completed'
                            schedules['backup']['last_result'] = '備份成功'
                        else:
                            schedules['backup']['last_status'] = 'failed'
                            schedules['backup']['last_result'] = result_text[:50]
    except Exception as e:
        log.error(f"讀取備份日誌失敗: {e}")

    # 取得簡訊最後執行資訊
    try:
        db = get_db()
        last_sms = db.execute(
            '''SELECT run_date, started_at, finished_at, status, total_targets, sent_count, success_count, failed_count
               FROM sms_daily_runs ORDER BY started_at DESC LIMIT 1'''
        ).fetchone()
        db.close()
        if last_sms:
            schedules['sms']['last_run'] = last_sms['finished_at'] or last_sms['started_at']
            schedules['sms']['last_status'] = last_sms['status']
            if last_sms['status'] == 'completed':
                schedules['sms']['last_result'] = f"發送 {last_sms['sent_count']} / 成功 {last_sms['success_count']} / 失敗 {last_sms['failed_count']}"
            elif last_sms['status'] == 'running':
                schedules['sms']['last_result'] = '執行中...'
            elif last_sms['status'] == 'error':
                schedules['sms']['last_result'] = '執行失敗'
            else:
                schedules['sms']['last_result'] = last_sms['status']
    except Exception as e:
        log.error(f"查詢簡訊記錄失敗: {e}")

    return jsonify(schedules)


@app.route('/api/admin/schedules', methods=['PUT'])
@admin_required
def api_admin_update_schedule():
    """修改排程時間"""
    import subprocess

    data = request.get_json()
    schedule_type = data.get('type')  # 'scraper' or 'backup'
    new_time = data.get('time')  # 'HH:MM' 格式

    valid_types = ('scraper', 'backup', 'sms')
    if schedule_type not in valid_types:
        return jsonify({'error': '無效的排程類型'}), 400

    if not new_time or not re.match(r'^\d{2}:\d{2}$', new_time):
        return jsonify({'error': '時間格式無效，請使用 HH:MM 格式'}), 400

    # 排程任務名稱對應
    task_names = {
        'scraper': '28car_daily',
        'backup': '28car_backup',
        'sms': '28car_sms'
    }
    task_name = task_names[schedule_type]

    # 取得執行命令（優先 exe，其次 py）
    if schedule_type == 'scraper':
        cmd = get_script_command('scraper', ['--daily'])
    elif schedule_type == 'sms':
        cmd = get_script_command('sms', ['--daily'])
    else:
        cmd = get_script_command('backup')

    if not cmd:
        return jsonify({'error': '找不到對應的程式 (exe 或 py)'}), 400

    # 組合命令字串（schtasks 需要完整命令）
    script_path = ' '.join(f'"{c}"' if ' ' in c else c for c in cmd)

    try:
        # 刪除舊排程
        subprocess.run(['schtasks', '/delete', '/tn', task_name, '/f'],
                      capture_output=True, errors='ignore')

        # 建立新排程
        result = subprocess.run(
            ['schtasks', '/create', '/tn', task_name, '/tr', script_path,
             '/sc', 'daily', '/st', new_time, '/f'],
            capture_output=True, text=True, encoding='cp950', errors='ignore'
        )

        if result.returncode == 0:
            log_operation(request.current_user['id'], 'UPDATE_SCHEDULE',
                         'schedule', task_name, {'new_time': new_time})
            return jsonify({'success': True, 'message': f'排程已更新為 {new_time}'})
        else:
            return jsonify({'success': False, 'error': result.stderr or '設定失敗，可能需要管理員權限'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/admin/run-daily-scraper', methods=['POST'])
@admin_required
def api_admin_run_daily_scraper():
    """立即執行每日爬蟲（Daily 模式，非完整爬蟲）"""
    import subprocess
    import threading

    daily_log_path = os.path.join(BASE_DIR, 'daily_task.log')

    cmd = get_script_command('scraper', ['--daily'])
    if not cmd:
        return jsonify({'success': False, 'error': '找不到爬蟲程式 (exe 或 py)'})

    def write_log(msg):
        """寫入每日任務日誌"""
        try:
            with open(daily_log_path, 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
        except:
            pass

    def run_scraper():
        try:
            write_log("============================================")
            write_log("手動觸發每日爬蟲")
            write_log("開始執行爬蟲...")

            result = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True)

            if result.returncode == 0:
                write_log("爬蟲執行成功")
            else:
                write_log(f"爬蟲執行失敗，錯誤碼: {result.returncode}")

            write_log("每日任務執行完畢")
            write_log("============================================")
        except Exception as e:
            write_log(f"執行爬蟲失敗: {e}")
            log.error(f"執行爬蟲失敗: {e}")

    # 在背景執行
    thread = threading.Thread(target=run_scraper, daemon=True)
    thread.start()

    log_operation(request.current_user['id'], 'RUN_DAILY_SCRAPER', None, None, {})

    return jsonify({
        'success': True,
        'message': '每日爬蟲已在背景執行中，請稍後查看資料更新'
    })


@app.route('/api/admin/run-backup', methods=['POST'])
@admin_required
def api_admin_run_backup():
    """立即執行資料庫備份"""
    import subprocess

    cmd = get_script_command('backup')
    if not cmd:
        return jsonify({'success': False, 'error': '找不到備份程式 (exe 或 py)'})

    try:
        result = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, timeout=60)

        log_operation(request.current_user['id'], 'RUN_BACKUP', None, None, {})

        if result.returncode == 0:
            # 讀取備份日誌的最後一行
            log_path = os.path.join(BASE_DIR, 'backup', 'backup.log')
            last_log = ''
            if os.path.exists(log_path):
                with open(log_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    if lines:
                        last_log = lines[-1].strip()

            return jsonify({
                'success': True,
                'message': '備份完成！',
                'log': last_log
            })
        else:
            return jsonify({'success': False, 'error': '備份執行失敗'})
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': '備份超時'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/admin/run-sms', methods=['POST'])
@admin_required
def api_admin_run_sms():
    """立即執行簡訊發送（強制執行，忽略時間區間）"""
    import subprocess
    import threading

    cmd = get_script_command('sms', ['--daily', '--force'])
    if not cmd:
        return jsonify({'success': False, 'error': '找不到簡訊程式 (exe 或 py)'})

    def run_sms():
        try:
            subprocess.run(cmd, cwd=BASE_DIR)
        except Exception as e:
            log.error(f"執行簡訊發送失敗: {e}")

    # 在背景執行
    thread = threading.Thread(target=run_sms, daemon=True)
    thread.start()

    log_operation(request.current_user['id'], 'RUN_SMS', None, None, {})

    return jsonify({
        'success': True,
        'message': '簡訊發送已在背景執行中'
    })


# ============================================================
# 伺服器管理 API
# ============================================================

@app.route('/api/server/health')
def api_server_health():
    """健康檢查端點"""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0'
    })


@app.route('/api/server/restart', methods=['POST'])
@login_required
def api_server_restart():
    """重啟伺服器"""
    import subprocess
    import sys
    import threading

    def restart_server():
        import time
        time.sleep(1)  # 等待回應發送完成

        # 先終止當前進程，然後用 cmd /c 延遲啟動新進程
        # 這樣可以確保舊進程完全退出後才啟動新進程
        if os.name == 'nt':  # Windows
            exe_path = os.path.join(BASE_DIR, '28car_server.exe')
            if os.path.exists(exe_path):
                # 使用 cmd /c 執行：等待 2 秒後啟動新進程
                cmd = f'cmd /c "timeout /t 2 /nobreak >nul && start "" "{exe_path}""'
            else:
                py_path = os.path.join(BASE_DIR, 'web_demo.py')
                cmd = f'cmd /c "timeout /t 2 /nobreak >nul && start "" python "{py_path}""'
            subprocess.Popen(cmd, shell=True, cwd=BASE_DIR,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:  # Linux/Mac
            # 使用 bash 延遲啟動
            py_path = os.path.join(BASE_DIR, 'web_demo.py')
            subprocess.Popen(f'sleep 2 && {sys.executable} "{py_path}"',
                           shell=True, cwd=BASE_DIR, start_new_session=True)

        # 終止當前進程
        os._exit(0)

    # 在背景執行重啟
    threading.Thread(target=restart_server, daemon=True).start()

    return jsonify({
        'status': 'restarting',
        'message': '伺服器正在重啟，請稍候...'
    })


# ============================================================
# 主頁面
# ============================================================
@app.route('/')
def index():
    response = send_from_directory(BASE_DIR, 'index.html')
    # 防止瀏覽器快取 HTML 頁面，確保每次都載入最新版本
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


def kill_existing_server():
    """啟動前先關閉已存在的伺服器進程"""
    import subprocess
    import sys

    # 取得當前進程名稱
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包後的 exe
        exe_name = os.path.basename(sys.executable)
    else:
        exe_name = None

    if exe_name and exe_name.lower() == '28car_server.exe':
        try:
            # 取得當前進程 ID
            current_pid = os.getpid()

            # 使用 tasklist 找出所有同名進程
            result = subprocess.run(
                ['tasklist', '/FI', f'IMAGENAME eq {exe_name}', '/FO', 'CSV', '/NH'],
                capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
            )

            # 解析並殺掉非當前進程
            for line in result.stdout.strip().split('\n'):
                if line and exe_name.lower() in line.lower():
                    parts = line.replace('"', '').split(',')
                    if len(parts) >= 2:
                        try:
                            pid = int(parts[1])
                            if pid != current_pid:
                                subprocess.run(
                                    ['taskkill', '/F', '/PID', str(pid)],
                                    capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW
                                )
                                print(f"  已關閉舊的伺服器進程 (PID: {pid})")
                        except (ValueError, IndexError):
                            pass
        except Exception as e:
            pass  # 忽略錯誤，繼續啟動

if __name__ == '__main__':
    # 先關閉已存在的伺服器
    kill_existing_server()

    print("=" * 50)
    print("  28car Demo 網站")
    print(f"  http://localhost:{FLASK_PORT}")
    print("=" * 50)
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG, threaded=True)
