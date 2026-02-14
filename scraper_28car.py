"""
28car.com 完整爬蟲系統
==========================================
功能：
  1. 列表頁全分頁爬取（私人 sell + 車行 cmy 兩套系統）
  2. 詳情頁完整資料爬取（規格、描述、聯絡人）
  3. 圖片下載到本地資料夾（images/{car_no}/）
  4. SQLite 資料庫，圖片存相對路徑供網站讀取
  5. 增量更新 UPSERT（新車 INSERT、舊車 UPDATE）
  6. 智能每日更新（偵測新增/更新車源，自動停止掃描）
  7. 支援 Windows 排程 / cron 每日自動執行

網站結構摘要：
  - 編碼：Big5
  - 私人列表頁：index2.php?tourl=%2Fsell_lst.php
  - 車行列表頁：index2.php?tourl=%2Fcmy_lst.php
  - 私人詳情頁：sell_dsp.php?h_vid={VID}&h_vw=1
  - 車行詳情頁：cmy_dsp.php?h_vid={VID}&h_vw=1
  - 車輛 VID：TD onclick="goDsp(idx, VID, mode)"
  - 詳情頁欄位：frm_l(標題) + frm_t(值)
  - 圖片 CDN：djlfajk23a.28car.com/data/image/{sell|cmy}/...
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import cloudscraper  # Cloudflare 繞過
import re
import time
import random
import json
import sqlite3
import os
import sys
import signal
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

def normalize_updated_at(raw_time):
    """
    將 28car 的更新時間格式 (DD/MMhh:mm 或 DD/MMYYYY) 轉換為標準格式 (YYYY-MM-DD HH:MM)
    根據當前日期推斷年份：如果結果日期在未來，認為是去年
    """
    if not raw_time or len(raw_time) < 9:
        return raw_time

    try:
        day = int(raw_time[0:2])
        month = int(raw_time[3:5])

        now = datetime.now()
        current_year = now.year
        today = now.date()

        # 格式1: DD/MMhh:mm (例如 07/0209:30) - 長度 10
        if len(raw_time) >= 10 and ':' in raw_time:
            time_part = raw_time[5:]  # hh:mm
            # 先假設是今年
            from datetime import date
            try:
                test_date = date(current_year, month, day)
            except ValueError:
                test_date = today  # 無效日期時用今天
            # 如果日期在未來，改成去年
            if test_date > today:
                year = current_year - 1
            else:
                year = current_year
            return f'{year}-{month:02d}-{day:02d} {time_part}'

        # 格式2: DD/MMYYYY (例如 31/012025) - 長度 9，無時間
        elif len(raw_time) == 9:
            year = int(raw_time[5:9])
            return f'{year}-{month:02d}-{day:02d}'

        return raw_time
    except Exception:
        return raw_time

# ============================================================
# 設定（支援環境變數覆蓋，方便 server 部署）
# ============================================================
BASE_DIR = os.environ.get('APP_BASE_DIR', os.path.dirname(os.path.abspath(__file__)))
BASE_URL = os.environ.get('APP_BASE_URL', "https://www.28car.com")
CDN_URL = os.environ.get('APP_CDN_URL', "https://dj1jklak2e.28car.com")  # 詳情頁內容 CDN
DB_PATH = os.environ.get('DB_PATH', os.path.join(BASE_DIR, "cars_28car.db"))
IMAGES_DIR = os.environ.get('IMAGES_DIR', os.path.join(BASE_DIR, "images"))
LOG_PATH = os.environ.get('LOG_PATH', os.path.join(BASE_DIR, "scraper.log"))
LOCK_PATH = os.path.join(BASE_DIR, ".scraper.lock")

# --- 兩套來源系統 ---
SOURCES = {
    'sell': {
        'name': '私人賣車庫',
        'list_page': 'sell_lst.php',
        'detail_page': 'sell_dsp.php',
        'image_dir': 'sell',
    },
    'cmy': {
        'name': '車行賣車庫',
        'list_page': 'cmy_lst.php',
        'detail_page': 'cmy_dsp.php',
        'image_dir': 'cmy',
    },
}

# --- 車輛類別 ---
CATEGORIES = {
    1: '私家車',
    2: '客貨車',
    3: '貨車',
    4: '電單車',
    5: '經典車',
}

# 多個 User-Agent 隨機輪換，模擬不同瀏覽器
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
]

HEADERS = {
    'User-Agent': random.choice(USER_AGENTS),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'zh-TW,zh-HK;q=0.9,zh;q=0.8,en-US;q=0.7,en;q=0.6',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Cache-Control': 'max-age=0',
}

# 延遲設定（秒）
PAGE_DELAY_MIN = 2.0
PAGE_DELAY_MAX = 4.0
DETAIL_DELAY_MIN = 2.0
DETAIL_DELAY_MAX = 4.0

# ============================================================
# 日誌設定（RotatingFileHandler 防止 log 無限增長）
# ============================================================
log = logging.getLogger('scraper_28car')
log.setLevel(logging.INFO)
_fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
_fh = RotatingFileHandler(LOG_PATH, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
_fh.setFormatter(_fmt)
_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)
log.addHandler(_fh)
log.addHandler(_sh)


# ============================================================
# 資料庫初始化
# ============================================================
def init_db():
    """建立 SQLite 資料庫和所有資料表"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    c = conn.cursor()

    # --- 車輛主表 ---
    c.execute('''
        CREATE TABLE IF NOT EXISTS cars (
            vid             TEXT PRIMARY KEY,
            car_no          TEXT,
            car_type        TEXT,
            source          TEXT DEFAULT 'sell',
            make            TEXT,
            make_en         TEXT,
            model           TEXT,
            fuel            TEXT,
            seats           TEXT,
            engine_cc       TEXT,
            transmission    TEXT,
            year            TEXT,
            price           TEXT,
            price_num       INTEGER DEFAULT 0,
            original_price  TEXT,
            original_price_num INTEGER DEFAULT 0,
            description     TEXT,
            contact_name    TEXT,
            contact_phone   TEXT,
            has_photo       INTEGER DEFAULT 0,
            photo_count     INTEGER DEFAULT 0,
            comments        INTEGER DEFAULT 0,
            views           INTEGER DEFAULT 0,
            is_sold         INTEGER DEFAULT 0,
            updated_at      TEXT,
            detail_url      TEXT,
            source_url      TEXT,
            detail_scraped  INTEGER DEFAULT 0,
            scraped_at      TEXT,
            first_seen      TEXT,
            last_seen       TEXT
        )
    ''')

    # --- 圖片表（相對路徑供網站使用）---
    c.execute('''
        CREATE TABLE IF NOT EXISTS car_photos (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            vid             TEXT NOT NULL,
            photo_index     INTEGER,
            original_url    TEXT,
            local_path      TEXT,
            downloaded      INTEGER DEFAULT 0,
            created_at      TEXT,
            FOREIGN KEY (vid) REFERENCES cars(vid) ON DELETE CASCADE
        )
    ''')

    # --- 爬取日誌 ---
    c.execute('''
        CREATE TABLE IF NOT EXISTS scrape_log (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at          TEXT,
            finished_at         TEXT,
            total_pages         INTEGER DEFAULT 0,
            total_list_cars     INTEGER DEFAULT 0,
            new_cars            INTEGER DEFAULT 0,
            updated_cars        INTEGER DEFAULT 0,
            details_scraped     INTEGER DEFAULT 0,
            photos_downloaded   INTEGER DEFAULT 0,
            status              TEXT DEFAULT 'running'
        )
    ''')

    # --- 遷移：為舊資料庫新增 source 欄位（必須在建索引之前） ---
    try:
        c.execute("SELECT source FROM cars LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE cars ADD COLUMN source TEXT DEFAULT 'sell'")
        log.info("已為 cars 表新增 source 欄位")

    # --- 遷移：新增 original_price 欄位 ---
    try:
        c.execute("SELECT original_price FROM cars LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE cars ADD COLUMN original_price TEXT")
        c.execute("ALTER TABLE cars ADD COLUMN original_price_num INTEGER DEFAULT 0")
        log.info("已為 cars 表新增 original_price 欄位")

    # --- 索引 ---
    c.execute('CREATE INDEX IF NOT EXISTS idx_car_no ON cars(car_no)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_make ON cars(make)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_year ON cars(year)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_price_num ON cars(price_num)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_is_sold ON cars(is_sold)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_first_seen ON cars(first_seen)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_detail_scraped ON cars(detail_scraped)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_source ON cars(source)')
    c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_photo_vid_idx ON car_photos(vid, photo_index)')

    conn.commit()
    return conn


# ============================================================
# 爬蟲主體
# ============================================================
class Scraper28Car:
    def __init__(self):
        # 使用 cloudscraper 繞過 Cloudflare 保護
        self.session = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True,
            }
        )
        self.session.headers.update(HEADERS)
        os.makedirs(IMAGES_DIR, exist_ok=True)
        self._shutdown = False
        # 失敗重試隊列
        self._failed_queue = []  # [(vid, source, retry_count), ...]
        self._max_retries = 3  # 最大重試次數

    def handle_shutdown(self, signum, frame):
        """優雅關閉：收到 SIGINT/SIGTERM 時完成當前任務後停止"""
        log.info(f"收到停止信號 ({signum})，將在當前任務完成後停止...")
        self._shutdown = True

    def _random_headers(self, referer=None):
        """生成隨機 headers 模擬真實瀏覽器"""
        return {
            'User-Agent': random.choice(USER_AGENTS),
            'Referer': referer or f'{BASE_URL}/',
        }

    def _fetch(self, url, timeout=30, referer=None):
        """抓取頁面，Big5 解碼（自動 retry by session adapter）"""
        headers = self._random_headers(referer)
        resp = self.session.get(url, timeout=timeout, headers=headers)
        resp.raise_for_status()
        return resp.content.decode('big5', errors='replace')

    def _fetch_bytes(self, url, timeout=30, referer=None):
        """抓取二進位內容（圖片用）"""
        headers = self._random_headers(referer)
        resp = self.session.get(url, timeout=timeout, headers=headers)
        resp.raise_for_status()
        return resp.content

    def _delay(self, min_s=PAGE_DELAY_MIN, max_s=PAGE_DELAY_MAX):
        time.sleep(random.uniform(min_s, max_s))

    def _parse_price(self, price_str):
        """'$61,880' / 'HKD$61,880' -> 61880"""
        if not price_str:
            return 0
        nums = re.sub(r'[^0-9]', '', price_str)
        return int(nums) if nums else 0

    # --- URL 建構輔助函數 ---
    def _list_url(self, source, page=1):
        """建構列表頁 URL（支援 sell / cmy）"""
        list_page = SOURCES[source]['list_page']
        if page <= 1:
            return f"{BASE_URL}/index2.php?tourl=%2F{list_page}"
        else:
            return f"{BASE_URL}/index2.php?tourl=%2F{list_page}%3Fh_page%3D{page}"

    def _detail_url(self, source, vid):
        """建構詳情頁 URL（支援 sell / cmy）- 直接使用 CDN"""
        detail_page = SOURCES[source]['detail_page']
        return f"{CDN_URL}/{detail_page}?h_vid={vid}&h_vw=1"

    # ============================================================
    # 列表頁解析
    # ============================================================
    def _parse_car_row(self, rw_td, source='sell'):
        """解析列表頁中單一車輛行"""
        try:
            car = {}
            car['source'] = source

            # 車輛編號 + 有無圖片
            title = rw_td.get('title', '')
            m = re.search(r'編號\s*:\s*(\w+)', title)
            car['car_no'] = m.group(1) if m else ''
            car['has_photo'] = 1 if '有圖片' in title else 0

            # VID
            rw_html = str(rw_td)
            m = re.search(r"goDsp\(\d+,\s*(\d+),\s*'n'\)", rw_html)
            if not m:
                return None
            car['vid'] = m.group(1)

            # 找 onclick='n' 的 TD
            onclick_td = rw_td.find('td', onclick=re.compile(r"goDsp.*'n'"))
            if not onclick_td:
                return None

            inner_table = onclick_td.find('table')
            if not inner_table:
                return None

            trs = inner_table.find_all('tr', recursive=False)
            if not trs:
                return None

            # 第一行：結構化欄位
            tds = trs[0].find_all('td', recursive=False)
            if len(tds) >= 7:
                bold = tds[0].find('b')
                car['make'] = bold.get_text(strip=True) if bold else ''
                full = tds[0].get_text(strip=True)
                car['model'] = full.replace(car['make'], '', 1).strip()

                fields = ['fuel', 'seats', 'engine_cc', 'transmission', 'year', 'price']
                for i, name in enumerate(fields):
                    idx = i + 1
                    car[name] = tds[idx].get_text(strip=True) if idx < len(tds) else ''

                car['price_num'] = self._parse_price(car.get('price', ''))

                if len(tds) > 7:
                    t = tds[7].get_text(strip=True)
                    car['comments'] = int(t) if t.isdigit() else 0
                else:
                    car['comments'] = 0

                if len(tds) > 8:
                    t = tds[8].get_text(strip=True)
                    car['views'] = int(t) if t.isdigit() else 0
                else:
                    car['views'] = 0

                if len(tds) > 9:
                    t = tds[9].get_text(strip=True)
                    car['is_sold'] = 1 if t else 0
                else:
                    car['is_sold'] = 0

            # 第二行：描述 + 聯絡人
            if len(trs) > 1:
                desc_td = trs[1].find('td')
                if desc_td:
                    full_desc = desc_td.get_text(strip=True)
                    contact_b = desc_td.find('b')
                    contact_raw = contact_b.get_text(strip=True) if contact_b else ''
                    car['description'] = full_desc.replace(contact_raw, '').strip().rstrip(',').rstrip(',')
                    car['contact_raw'] = contact_raw
                    # 如果聯絡人資訊包含「已售」，標記為已售
                    if '已售' in contact_raw:
                        car['is_sold'] = 1
                else:
                    car['description'] = ''
                    car['contact_raw'] = ''
            else:
                car['description'] = ''
                car['contact_raw'] = ''

            # 更新時間
            time_td = rw_td.find('td', onclick=re.compile(r"goDsp.*'y'"))
            raw_time = time_td.get_text(strip=True) if time_td else ''
            car['updated_at'] = normalize_updated_at(raw_time)

            # 詳情頁 URL（使用 CDN）
            detail_page = SOURCES[source]['detail_page']
            car['detail_url'] = f"{CDN_URL}/{detail_page}?h_vid={car['vid']}&h_vw=1"

            return car
        except Exception as e:
            log.warning(f"解析車輛行失敗: {e}")
            return None

    def _parse_list_page(self, soup, source='sell'):
        """從 BeautifulSoup 解析列表頁所有車輛"""
        cars = []
        for rw_td in soup.find_all('td', id=re.compile(r'^rw_\d+')):
            car = self._parse_car_row(rw_td, source)
            if car:
                cars.append(car)
        return cars

    def _detect_total_pages(self, soup):
        """偵測總頁數（從 genPage(total, current) JS 呼叫解析）"""
        text = str(soup)
        # genPage(4716, 1) → 總共 4716 頁
        m = re.search(r'genPage\((\d+),\s*\d+\)', text)
        if m:
            return int(m.group(1))
        # 備用：從 goPage onclick
        total = 1
        for el in soup.find_all(attrs={'onclick': re.compile(r'goPage')}):
            m = re.search(r'goPage\((\d+)\)', el.get('onclick', ''))
            if m:
                total = max(total, int(m.group(1)))
        return total

    def scrape_all_list_pages(self, source='sell', max_pages=None):
        """爬取指定來源的所有列表頁"""
        all_cars = []
        src_name = SOURCES[source]['name']

        # 第 1 頁
        url = self._list_url(source, 1)
        log.info(f"[{src_name}] 正在抓取列表第 1 頁...")
        text = self._fetch(url)
        soup = BeautifulSoup(text, 'html.parser')

        total_pages = self._detect_total_pages(soup)
        if max_pages:
            total_pages = min(total_pages, max_pages)
        log.info(f"[{src_name}] 共偵測到 {total_pages} 頁")

        # 解析第 1 頁（不重複抓取）
        cars = self._parse_list_page(soup, source)
        log.info(f"  第 1 頁: {len(cars)} 輛車")
        all_cars.extend(cars)

        # 第 2 頁起
        for page in range(2, total_pages + 1):
            self._delay()
            url = self._list_url(source, page)
            log.info(f"[{src_name}] 正在抓取列表第 {page}/{total_pages} 頁...")
            try:
                text = self._fetch(url)
                soup = BeautifulSoup(text, 'html.parser')
                cars = self._parse_list_page(soup, source)
                log.info(f"  第 {page} 頁: {len(cars)} 輛車")
                all_cars.extend(cars)
            except Exception as e:
                log.error(f"  第 {page} 頁抓取失敗: {e}")

        # 去重
        seen = set()
        unique = []
        for car in all_cars:
            if car['vid'] not in seen:
                seen.add(car['vid'])
                unique.append(car)

        log.info(f"[{src_name}] 列表頁總計: {len(unique)} 輛不重複車輛")
        return unique, total_pages

    # ============================================================
    # 詳情頁解析
    # ============================================================
    def scrape_detail(self, vid, source='sell'):
        """
        爬取單一車輛詳情頁
        回傳 dict 包含完整資料 + 圖片 URLs
        注意：sell_dsp.php / cmy_dsp.php 會回傳 frameset，必須用 index2.php 包裝
        """
        url = self._detail_url(source, vid)
        # 使用列表頁作為 Referer，模擬正常瀏覽行為
        list_page = SOURCES[source]['list_page']
        referer = f"{BASE_URL}/{list_page}"
        try:
            text = self._fetch(url, referer=referer)
        except Exception as e:
            log.error(f"詳情頁抓取失敗 vid={vid} source={source}: {e}")
            return None

        soup = BeautifulSoup(text, 'html.parser')
        detail = {}

        # --- 解析 frm_l / frm_t 欄位對 ---
        spec_map = {}
        for td_label in soup.find_all('td', class_='frm_l'):
            label = td_label.get_text(strip=True)
            # 先找同層 sibling
            td_value = td_label.find_next_sibling('td', class_='frm_t')
            if not td_value:
                parent_tr = td_label.find_parent('tr')
                if parent_tr:
                    td_value = parent_tr.find('td', class_='frm_t')
            if td_value:
                spec_map[label] = td_value

        # 編號
        if '編號' in spec_map:
            detail['car_no'] = spec_map['編號'].get_text(strip=True)

        # 車類
        if '車類' in spec_map:
            detail['car_type'] = spec_map['車類'].get_text(strip=True)

        # 車廠（中文 + 英文）
        if '車廠' in spec_map:
            raw = spec_map['車廠'].get_text(strip=True)
            parts = raw.split()
            detail['make'] = parts[0] if parts else raw
            detail['make_en'] = parts[1] if len(parts) > 1 else ''

        # 型號
        if '型號' in spec_map:
            detail['model'] = spec_map['型號'].get_text(strip=True)

        # 燃料 (Big5 下可能顯示為 燃炓)
        for key in ['燃料', '燃炓']:
            if key in spec_map:
                detail['fuel'] = spec_map[key].get_text(strip=True)
                break

        if '座位' in spec_map:
            detail['seats'] = spec_map['座位'].get_text(strip=True)

        if '容積' in spec_map:
            detail['engine_cc'] = spec_map['容積'].get_text(strip=True)

        if '傳動' in spec_map:
            detail['transmission'] = spec_map['傳動'].get_text(strip=True)

        if '年份' in spec_map:
            detail['year'] = spec_map['年份'].get_text(strip=True)

        # 簡評（完整版）
        if '簡評' in spec_map:
            detail['description'] = spec_map['簡評'].get_text(strip=True)

        # 售價 + 原價
        if '售價' in spec_map:
            price_td = spec_map['售價']
            price_text = price_td.get_text(strip=True)

            # 提取原價 [原價 $XX,XXX]
            orig_match = re.search(r'原價[^$]*\$?([\d,]+)', price_text)
            if orig_match:
                orig_str = orig_match.group(1).replace(',', '')
                detail['original_price'] = f'${orig_match.group(1)}'
                detail['original_price_num'] = int(orig_str) if orig_str else 0
                # 現價：取原價之前的部分
                before_orig = price_text[:orig_match.start()]
                detail['price'] = before_orig.strip().rstrip('[').strip()
                detail['price_num'] = self._parse_price(before_orig)
            else:
                detail['price'] = price_text
                detail['price_num'] = self._parse_price(price_text)

        # 聯絡人資料
        if '聯絡人資料' in spec_map:
            contact_raw = spec_map['聯絡人資料'].get_text(strip=True)
            m = re.match(r'(.+?)\s*電話[：:]\s*(\d[\d\-]*)', contact_raw)
            if m:
                detail['contact_name'] = m.group(1).strip()
                detail['contact_phone'] = m.group(2).strip()
            else:
                detail['contact_name'] = contact_raw
                detail['contact_phone'] = ''

        # 更新日期
        if '更新日期' in spec_map:
            detail['updated_at'] = normalize_updated_at(spec_map['更新日期'].get_text(strip=True))

        # 網址
        if '網址' in spec_map:
            detail['source_url'] = spec_map['網址'].get_text(strip=True)

        # --- 留言數 + 瀏覽次數 ---
        page_text = soup.get_text()
        m = re.search(r'留言數目\s*:\s*(\d+)', page_text)
        if m:
            detail['comments'] = int(m.group(1))
        m = re.search(r'瀏覽次數\s*:\s*(\d+)', page_text)
        if m:
            detail['views'] = int(m.group(1))

        # --- 圖片 URLs（同時匹配 sell 和 cmy 路徑）---
        # 從 car_no 取得 entity_id，用來過濾只屬於這輛車的圖片
        # sell: car_no = s2678925 → entity_id = 2678925
        # cmy:  car_no = c184881  → entity_id = 184881
        car_no = detail.get('car_no', '')
        entity_id = re.sub(r'^[sc]', '', car_no) if car_no else ''

        photo_urls = []
        for img in soup.find_all('img', src=re.compile(r'/data/image/(sell|cmy)/')):
            src = img.get('src', '')
            if not src:
                continue
            # 過濾：只保留路徑中包含本車 entity_id 的圖片
            if entity_id and f'/{entity_id}/' in src:
                photo_urls.append(src)
            elif not entity_id:
                photo_urls.append(src)  # 無 car_no 時不過濾

        # 推導各尺寸 URL（優先順序：_b.jpg > _m.jpg > _s.jpg）
        big_urls = []
        med_urls = []
        for u in photo_urls:
            bu = re.sub(r'_(m|s)\.jpg', '_b.jpg', u)
            mu = re.sub(r'_(b|s)\.jpg', '_m.jpg', u)
            big_urls.append(bu)
            med_urls.append(mu)

        detail['photo_urls'] = big_urls if big_urls else photo_urls
        detail['photo_urls_medium'] = med_urls
        detail['photo_urls_fallback'] = photo_urls
        detail['photo_count'] = len(photo_urls)

        return detail

    # ============================================================
    # 圖片下載
    # ============================================================
    def download_photos(self, vid, car_no, photo_urls, fallback_urls=None, medium_urls=None):
        """
        下載圖片到 images/{car_no}/
        優先級：_b.jpg (大圖) → _m.jpg (中圖) → 原始 URL
        回傳: [(photo_index, original_url, local_path, success), ...]
        """
        if not photo_urls:
            return []

        # 大圖最低 8KB，低於此值視為縮圖需重下載
        MIN_GOOD_SIZE = 8000

        folder_name = car_no if car_no else vid
        folder = os.path.join(IMAGES_DIR, folder_name)
        os.makedirs(folder, exist_ok=True)

        # 清除資料夾內舊圖片（避免殘留錯誤圖片）
        for old_file in os.listdir(folder):
            old_path = os.path.join(folder, old_file)
            if os.path.isfile(old_path) and old_file.endswith('.jpg'):
                os.remove(old_path)

        results = []
        for i, url in enumerate(photo_urls):
            idx = i + 1
            local_rel = f"images/{folder_name}/{idx}.jpg"
            local_abs = os.path.join(BASE_DIR, local_rel)

            # 已下載且尺寸正常就跳過（< 8KB 視為縮圖，重新下載）
            if os.path.exists(local_abs) and os.path.getsize(local_abs) >= MIN_GOOD_SIZE:
                results.append((idx, url, local_rel, True))
                continue

            success = False

            # 1) 嘗試下載大圖 _b.jpg
            try:
                data = self._fetch_bytes(url)
                if len(data) >= MIN_GOOD_SIZE:
                    with open(local_abs, 'wb') as f:
                        f.write(data)
                    success = True
            except Exception:
                pass

            # 2) 大圖失敗 → 嘗試中圖 _m.jpg
            if not success and medium_urls and i < len(medium_urls):
                try:
                    time.sleep(0.2)
                    data = self._fetch_bytes(medium_urls[i])
                    if len(data) >= MIN_GOOD_SIZE:
                        with open(local_abs, 'wb') as f:
                            f.write(data)
                        success = True
                except Exception:
                    pass

            # 3) 中圖也失敗 → 備用原始 URL（可能是縮圖，但有總比沒有好）
            if not success and fallback_urls and i < len(fallback_urls):
                try:
                    time.sleep(0.2)
                    data = self._fetch_bytes(fallback_urls[i])
                    if len(data) > 500:
                        with open(local_abs, 'wb') as f:
                            f.write(data)
                        success = True
                except Exception:
                    pass

            results.append((idx, url, local_rel, success))

            if idx < len(photo_urls):
                time.sleep(0.3)

        return results

    # ============================================================
    # 智能每日更新
    # ============================================================
    def run_daily_update(self, stale_days=7, download_images=True, sources=None):
        """
        智能每日更新：
        - 逐一掃描指定的來源系統（sell + cmy）
        - 從第 1 頁開始往後掃描（28car 預設按更新時間降序）
        - 新 VID → INSERT + 爬詳情 + 下載圖片
        - 已知 VID 但 updated_at 變了 → UPDATE + 重爬詳情
        - 已知 VID 且 updated_at 沒變 → 跳過
        - 連續整頁全部沒變化 → 停止掃描（後面都是更舊的）
        - 超過 stale_days 天沒出現 → 標記可能下架
        """
        if sources is None:
            sources = ['sell', 'cmy']

        conn = init_db()
        now = datetime.now().isoformat()

        # 建立日誌記錄
        c = conn.cursor()
        c.execute('INSERT INTO scrape_log (started_at, status) VALUES (?, ?)', (now, 'daily_running'))
        conn.commit()
        log_id = c.lastrowid

        # 清理卡住的舊記錄（超過 6 小時還是 running 的）
        c.execute('''
            UPDATE scraper_runs
            SET status = 'cancelled',
                finished_at = ?,
                error_message = '任務被中斷或異常終止（自動清理）'
            WHERE status = 'running'
              AND finished_at IS NULL
              AND datetime(started_at) < datetime(?, '-6 hours')
        ''', (now, now))
        cleaned = c.rowcount
        if cleaned > 0:
            log.info(f"已清理 {cleaned} 筆卡住的舊執行記錄")
            conn.commit()

        # 建立 scraper_runs 記錄
        sources_str = ','.join(sources)
        c.execute('INSERT INTO scraper_runs (started_at, status, sources) VALUES (?, ?, ?)',
                  (now, 'running', sources_str))
        conn.commit()
        run_id = c.lastrowid

        stats = {
            'total_pages': 0,
            'total_list_cars': 0,
            'new_cars': 0,
            'updated_cars': 0,
            'unchanged_cars': 0,
            'details_scraped': 0,
            'photos_downloaded': 0,
            'stale_marked': 0,
        }

        try:
            log.info("=" * 60)
            log.info("  每日智能更新模式")
            log.info(f"  來源: {', '.join(SOURCES[s]['name'] for s in sources)}")
            log.info("=" * 60)

            # === 步驟 1: 逐一掃描各來源系統 ===
            for source in sources:
                src_name = SOURCES[source]['name']
                log.info("")
                log.info(f"{'='*60}")
                log.info(f"  掃描 [{src_name}] ({source})")
                log.info(f"{'='*60}")

                src_stats = self._daily_scan_source(conn, source)
                stats['total_pages'] += src_stats['pages']
                stats['total_list_cars'] += src_stats['cars']
                stats['new_cars'] += src_stats['new']
                stats['updated_cars'] += src_stats['updated']
                stats['unchanged_cars'] += src_stats['unchanged']

                log.info(f"  [{src_name}] 完成: {src_stats['pages']} 頁, "
                         f"新增:{src_stats['new']} 更新:{src_stats['updated']} "
                         f"不變:{src_stats['unchanged']}")

            # === 步驟 2: 爬取需要更新的詳情頁 + 圖片 ===
            log.info("")
            log.info("=" * 60)
            log.info("步驟 2: 爬取詳情頁 + 下載圖片")
            log.info("=" * 60)
            detail_count, photo_count = self._scrape_all_details(conn, download_images)
            stats['details_scraped'] = detail_count
            stats['photos_downloaded'] = photo_count

            # === 步驟 3: 標記可能下架的車輛 ===
            if stale_days > 0:
                log.info("")
                log.info(f"步驟 3: 標記超過 {stale_days} 天未出現的車輛")
                log.info("-" * 40)
                stale_count = self._mark_stale_cars(conn, stale_days)
                stats['stale_marked'] = stale_count

            # === 完成 ===
            self._update_log(conn, log_id, stats, 'daily_success')
            self._print_stats(conn)
            export_to_json(conn)

            # 更新 scraper_runs 記錄
            finished_at = datetime.now().isoformat()
            c.execute('''UPDATE scraper_runs SET
                finished_at=?, status=?, total_pages=?, new_cars=?, updated_cars=?,
                unchanged_cars=?, details_scraped=?, photos_downloaded=?, stale_marked=?
                WHERE id=?''',
                (finished_at, 'success', stats['total_pages'], stats['new_cars'],
                 stats['updated_cars'], stats['unchanged_cars'], stats['details_scraped'],
                 stats['photos_downloaded'], stats['stale_marked'], run_id))
            conn.commit()

            log.info("")
            log.info("=" * 60)
            log.info("  每日更新完成！")
            log.info(f"  掃描頁數: {stats['total_pages']}")
            log.info(f"  新增車輛: {stats['new_cars']}")
            log.info(f"  更新車輛: {stats['updated_cars']}")
            log.info(f"  不變車輛: {stats['unchanged_cars']}")
            log.info(f"  詳情爬取: {stats['details_scraped']}")
            log.info(f"  圖片下載: {stats['photos_downloaded']}")
            log.info(f"  標記下架: {stats['stale_marked']}")
            log.info("=" * 60)

        except Exception as e:
            log.error(f"每日更新出錯: {e}")
            import traceback
            traceback.print_exc()
            self._update_log(conn, log_id, stats, f'daily_error: {e}')
            # 更新 scraper_runs 記錄為失敗
            finished_at = datetime.now().isoformat()
            c.execute('''UPDATE scraper_runs SET
                finished_at=?, status=?, error_message=?, total_pages=?, new_cars=?,
                updated_cars=?, unchanged_cars=?, details_scraped=?, photos_downloaded=?
                WHERE id=?''',
                (finished_at, 'error', str(e), stats['total_pages'], stats['new_cars'],
                 stats['updated_cars'], stats['unchanged_cars'], stats['details_scraped'],
                 stats['photos_downloaded'], run_id))
            conn.commit()

        conn.close()
        return stats

    def _daily_scan_source(self, conn, source):
        """掃描單一來源系統的列表頁（每日更新用）"""
        src_name = SOURCES[source]['name']
        result = {'pages': 0, 'cars': 0, 'new': 0, 'updated': 0, 'unchanged': 0}

        # 讀取第 1 頁，取得總頁數
        url = self._list_url(source, 1)
        text = self._fetch(url)
        soup = BeautifulSoup(text, 'html.parser')
        total_pages = self._detect_total_pages(soup)

        # 處理第 1 頁
        cars_page = self._parse_list_page(soup, source)
        page_new, page_upd, page_unch = self._process_daily_page(conn, cars_page, source)
        result['pages'] += 1
        result['cars'] += len(cars_page)
        result['new'] += page_new
        result['updated'] += page_upd
        result['unchanged'] += page_unch

        log.info(f"  [{src_name}] 第 1/{total_pages} 頁: {len(cars_page)} 輛 "
                 f"(新:{page_new} 更新:{page_upd} 不變:{page_unch})")

        # 逐頁往後掃描
        consecutive_unchanged = 0
        stop_threshold = 2  # 連續 2 頁完全沒變化就停止

        if page_unch == len(cars_page) and len(cars_page) > 0:
            consecutive_unchanged += 1

        page = 2
        while page <= total_pages:
            if consecutive_unchanged >= stop_threshold:
                log.info(f"  [{src_name}] 連續 {stop_threshold} 頁無變化，"
                         f"停止掃描（第 {page-1} 頁止）")
                break

            self._delay()
            url = self._list_url(source, page)

            try:
                text = self._fetch(url)
                soup = BeautifulSoup(text, 'html.parser')
                cars_page = self._parse_list_page(soup, source)

                page_new, page_upd, page_unch = self._process_daily_page(conn, cars_page, source)
                result['pages'] += 1
                result['cars'] += len(cars_page)
                result['new'] += page_new
                result['updated'] += page_upd
                result['unchanged'] += page_unch

                log.info(f"  [{src_name}] 第 {page}/{total_pages} 頁: {len(cars_page)} 輛 "
                         f"(新:{page_new} 更新:{page_upd} 不變:{page_unch})")

                # 判斷是否連續整頁無變化
                if page_unch == len(cars_page) and len(cars_page) > 0:
                    consecutive_unchanged += 1
                else:
                    consecutive_unchanged = 0

            except Exception as e:
                log.error(f"  [{src_name}] 第 {page} 頁抓取失敗: {e}")

            page += 1

        return result

    def _process_daily_page(self, conn, cars, source='sell'):
        """
        處理每日更新中的一頁車輛：
        - 比對 DB 中已有的 VID 和 updated_at
        - 新車 → INSERT
        - updated_at 變了 → UPDATE + 標記需重爬詳情 (detail_scraped=0)
        - 沒變 → 只更新 last_seen
        回傳: (new_count, updated_count, unchanged_count)
        """
        c = conn.cursor()
        now = datetime.now().isoformat()
        new_count = 0
        updated_count = 0
        unchanged_count = 0

        for car in cars:
            vid = car.get('vid', '')
            if not vid:
                continue

            c.execute('SELECT vid, updated_at, detail_scraped, price, price_num FROM cars WHERE vid = ?', (vid,))
            existing = c.fetchone()

            if existing is None:
                # 全新車輛 → INSERT
                c.execute('''
                    INSERT INTO cars (
                        vid, car_no, source, make, model, fuel, seats, engine_cc,
                        transmission, year, price, price_num, description,
                        has_photo, comments, views, is_sold,
                        updated_at, detail_url, scraped_at, first_seen, last_seen,
                        detail_scraped
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)
                ''', (
                    vid, car.get('car_no', ''), source,
                    car.get('make', ''), car.get('model', ''),
                    car.get('fuel', ''), car.get('seats', ''),
                    car.get('engine_cc', ''), car.get('transmission', ''),
                    car.get('year', ''), car.get('price', ''),
                    car.get('price_num', 0), car.get('description', ''),
                    car.get('has_photo', 0), car.get('comments', 0),
                    car.get('views', 0), car.get('is_sold', 0),
                    car.get('updated_at', ''), car.get('detail_url', ''),
                    now, now, now,
                ))
                new_count += 1

            else:
                db_updated_at = existing[1] or ''
                new_updated_at = car.get('updated_at', '')

                if new_updated_at != db_updated_at:
                    # 更新時間不同 → 車源有改動，更新列表欄位 + 重置 detail_scraped
                    db_price = existing[3] or ''
                    db_price_num = existing[4] or 0
                    new_price = car.get('price', '')
                    new_price_num = car.get('price_num', 0)

                    # 檢查價格是否變化
                    if new_price_num != db_price_num and db_price_num > 0:
                        # 價格有變化，記錄舊價格
                        c.execute('''
                            UPDATE cars SET
                                source=?, price=?, price_num=?, comments=?, views=?,
                                is_sold=?, updated_at=?, scraped_at=?, last_seen=?,
                                detail_scraped=0,
                                prev_price=?, prev_price_num=?, price_changed_at=?
                            WHERE vid=?
                        ''', (
                            source,
                            new_price, new_price_num,
                            car.get('comments', 0), car.get('views', 0),
                            car.get('is_sold', 0), new_updated_at,
                            now, now,
                            db_price, db_price_num, now,
                            vid,
                        ))
                    else:
                        # 價格沒變，正常更新
                        c.execute('''
                            UPDATE cars SET
                                source=?, price=?, price_num=?, comments=?, views=?,
                                is_sold=?, updated_at=?, scraped_at=?, last_seen=?,
                                detail_scraped=0
                            WHERE vid=?
                        ''', (
                            source,
                            new_price, new_price_num,
                            car.get('comments', 0), car.get('views', 0),
                            car.get('is_sold', 0), new_updated_at,
                            now, now, vid,
                        ))
                    updated_count += 1
                else:
                    # 沒變化 → 只更新 last_seen
                    c.execute('UPDATE cars SET last_seen=? WHERE vid=?', (now, vid))
                    unchanged_count += 1

        conn.commit()
        return new_count, updated_count, unchanged_count

    def _mark_stale_cars(self, conn, stale_days):
        """標記超過 N 天沒出現在列表的車輛為已下架（驗證詳情頁後才標記）"""
        c = conn.cursor()

        # 1. 先查詢可能要標記的車輛
        c.execute('''
            SELECT vid, source FROM cars
            WHERE is_sold = 0
              AND last_seen < datetime('now', ? || ' days')
        ''', (f'-{stale_days}',))

        candidates = c.fetchall()

        if not candidates:
            log.info(f"  無需標記下架車輛")
            return 0

        log.info(f"  發現 {len(candidates)} 輛車超過 {stale_days} 天未出現，開始驗證詳情頁...")

        marked_count = 0
        still_active = 0
        now = datetime.now().isoformat()

        for vid, source in candidates:
            # 2. 驗證詳情頁是否還存在
            try:
                self._delay(0.5, 1.0)  # 短暫延遲避免被封
                url = self._detail_url(source, vid)
                text = self._fetch(url)

                # 檢查是否有「已售」或頁面內容表示已下架
                if '已售' in text or '此車輛已下架' in text or '找不到此車輛' in text:
                    c.execute('UPDATE cars SET is_sold = 1 WHERE vid = ?', (vid,))
                    marked_count += 1
                    log.info(f"    [已售] vid={vid}")
                else:
                    # 車輛還在，更新 last_seen
                    c.execute('UPDATE cars SET last_seen = ? WHERE vid = ?', (now, vid))
                    still_active += 1
                    log.info(f"    [仍在] vid={vid}，更新 last_seen")

            except Exception as e:
                # 頁面不存在或抓取失敗，標記為已售
                c.execute('UPDATE cars SET is_sold = 1 WHERE vid = ?', (vid,))
                marked_count += 1
                log.info(f"    [下架] vid={vid} (頁面無法存取: {e})")

        conn.commit()
        log.info(f"  驗證完成: {marked_count} 輛已下架, {still_active} 輛仍在售")
        return marked_count

    # ============================================================
    # 完整爬取流程
    # ============================================================
    def run_full_scrape(self, max_pages=None, scrape_details=True,
                        download_images=True, sources=None):
        """完整爬取：逐頁寫入 DB → 詳情頁 → 圖片（支援多來源）"""
        if sources is None:
            sources = ['sell', 'cmy']

        conn = init_db()
        now = datetime.now().isoformat()

        # 建立日誌記錄
        c = conn.cursor()
        c.execute('INSERT INTO scrape_log (started_at, status) VALUES (?, ?)', (now, 'running'))
        conn.commit()
        log_id = c.lastrowid

        # 建立 scraper_runs 記錄（統一記錄格式）
        sources_str = ','.join(sources)
        c.execute('INSERT INTO scraper_runs (started_at, status, sources) VALUES (?, ?, ?)',
                  (now, 'running', sources_str))
        conn.commit()
        run_id = c.lastrowid

        stats = {
            'total_pages': 0,
            'total_list_cars': 0,
            'new_cars': 0,
            'updated_cars': 0,
            'details_scraped': 0,
            'photos_downloaded': 0,
        }

        try:
            # === 步驟 1+2: 逐頁爬取列表並即時寫入 DB ===
            log.info("=" * 60)
            log.info("爬取列表頁（逐頁寫入 DB）")
            log.info(f"  來源: {', '.join(SOURCES[s]['name'] for s in sources)}")
            log.info("=" * 60)

            for source in sources:
                src_name = SOURCES[source]['name']
                log.info("")
                log.info(f"--- [{src_name}] ---")

                # 第 1 頁：取得總頁數
                url = self._list_url(source, 1)
                log.info(f"[{src_name}] 正在抓取列表第 1 頁...")
                text = self._fetch(url)
                soup = BeautifulSoup(text, 'html.parser')
                total_pages = self._detect_total_pages(soup)
                if max_pages:
                    total_pages = min(total_pages, max_pages)
                log.info(f"[{src_name}] 共偵測到 {total_pages} 頁")

                cars = self._parse_list_page(soup, source)
                new_c, upd_c = self._save_list_to_db(conn, cars)
                stats['total_pages'] += 1
                stats['total_list_cars'] += len(cars)
                stats['new_cars'] += new_c
                stats['updated_cars'] += upd_c
                log.info(f"  第 1 頁: {len(cars)} 輛 (新:{new_c} 更新:{upd_c})")

                # 第 2 頁起
                for page in range(2, total_pages + 1):
                    self._delay()
                    url = self._list_url(source, page)
                    try:
                        text = self._fetch(url)
                        soup = BeautifulSoup(text, 'html.parser')
                        cars = self._parse_list_page(soup, source)
                        new_c, upd_c = self._save_list_to_db(conn, cars)
                        stats['total_pages'] += 1
                        stats['total_list_cars'] += len(cars)
                        stats['new_cars'] += new_c
                        stats['updated_cars'] += upd_c

                        if page % 50 == 0 or page == total_pages:
                            log.info(f"  [{src_name}] 第 {page}/{total_pages} 頁 "
                                     f"(累計 新:{stats['new_cars']} 更新:{stats['updated_cars']})")
                        else:
                            log.info(f"  第 {page} 頁: {len(cars)} 輛 (新:{new_c} 更新:{upd_c})")
                    except Exception as e:
                        log.error(f"  第 {page} 頁抓取失敗: {e}")

                log.info(f"[{src_name}] 列表完成 — 共 {total_pages} 頁")

            log.info("")
            log.info(f"列表頁全部完成: 新增 {stats['new_cars']}，更新 {stats['updated_cars']}")

            # === 步驟 3: 詳情頁 + 圖片 ===
            if scrape_details:
                log.info("")
                log.info("=" * 60)
                log.info("爬取詳情頁 + 下載圖片")
                log.info("=" * 60)
                detail_count, photo_count = self._scrape_all_details(conn, download_images)
                stats['details_scraped'] = detail_count
                stats['photos_downloaded'] = photo_count

            # === 完成 ===
            self._update_log(conn, log_id, stats, 'success')
            self._print_stats(conn)
            export_to_json(conn)

            # 更新 scraper_runs 記錄
            finished_at = datetime.now().isoformat()
            c.execute(
                'UPDATE scraper_runs SET '
                'finished_at=?, status=?, total_pages=?, new_cars=?, updated_cars=?, '
                'details_scraped=?, photos_downloaded=? '
                'WHERE id=?',
                (finished_at, 'success', stats['total_pages'], stats['new_cars'],
                 stats['updated_cars'], stats['details_scraped'], stats['photos_downloaded'],
                 run_id))
            conn.commit()

        except Exception as e:
            log.error(f"爬取過程出錯: {e}")
            import traceback
            traceback.print_exc()
            self._update_log(conn, log_id, stats, f'error: {e}')

            # 更新 scraper_runs 記錄為失敗
            finished_at = datetime.now().isoformat()
            c.execute(
                'UPDATE scraper_runs SET '
                'finished_at=?, status=?, error_message=?, total_pages=?, new_cars=?, '
                'updated_cars=?, details_scraped=?, photos_downloaded=? '
                'WHERE id=?',
                (finished_at, 'error', str(e), stats['total_pages'], stats['new_cars'],
                 stats['updated_cars'], stats['details_scraped'], stats['photos_downloaded'],
                 run_id))
            conn.commit()

        conn.close()
        return stats

    def _save_list_to_db(self, conn, cars):
        """列表頁資料存入 DB（UPSERT）"""
        c = conn.cursor()
        now = datetime.now().isoformat()
        new_count = 0
        update_count = 0

        for car in cars:
            vid = car.get('vid', '')
            if not vid:
                continue

            source = car.get('source', 'sell')

            c.execute('SELECT vid, price, price_num FROM cars WHERE vid = ?', (vid,))
            existing = c.fetchone()

            if existing is None:
                c.execute('''
                    INSERT INTO cars (
                        vid, car_no, source, make, model, fuel, seats, engine_cc,
                        transmission, year, price, price_num, description,
                        has_photo, comments, views, is_sold,
                        updated_at, detail_url, scraped_at, first_seen, last_seen
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ''', (
                    vid, car.get('car_no', ''), source,
                    car.get('make', ''), car.get('model', ''),
                    car.get('fuel', ''), car.get('seats', ''),
                    car.get('engine_cc', ''), car.get('transmission', ''),
                    car.get('year', ''), car.get('price', ''),
                    car.get('price_num', 0), car.get('description', ''),
                    car.get('has_photo', 0), car.get('comments', 0),
                    car.get('views', 0), car.get('is_sold', 0),
                    car.get('updated_at', ''), car.get('detail_url', ''),
                    now, now, now,
                ))
                new_count += 1
            else:
                db_price = existing[1] or ''
                db_price_num = existing[2] or 0
                new_price = car.get('price', '')
                new_price_num = car.get('price_num', 0)

                # 檢查價格是否變化
                if new_price_num != db_price_num and db_price_num > 0:
                    # 價格有變化，記錄舊價格
                    c.execute('''
                        UPDATE cars SET
                            source=?, price=?, price_num=?, comments=?, views=?,
                            is_sold=?, updated_at=?, scraped_at=?, last_seen=?,
                            prev_price=?, prev_price_num=?, price_changed_at=?
                        WHERE vid=?
                    ''', (
                        source,
                        new_price, new_price_num,
                        car.get('comments', 0), car.get('views', 0),
                        car.get('is_sold', 0), car.get('updated_at', ''),
                        now, now,
                        db_price, db_price_num, now,
                        vid,
                    ))
                else:
                    # 價格沒變，正常更新
                    c.execute('''
                        UPDATE cars SET
                            source=?, price=?, price_num=?, comments=?, views=?,
                            is_sold=?, updated_at=?, scraped_at=?, last_seen=?
                        WHERE vid=?
                    ''', (
                        source,
                        new_price, new_price_num,
                        car.get('comments', 0), car.get('views', 0),
                        car.get('is_sold', 0), car.get('updated_at', ''),
                        now, now, vid,
                    ))
                update_count += 1

        conn.commit()
        return new_count, update_count

    def _scrape_all_details(self, conn, download_images=True):
        """爬取所有尚未爬過詳情頁的車輛"""
        c = conn.cursor()

        c.execute('''
            SELECT vid, car_no, has_photo, source
            FROM cars
            WHERE detail_scraped = 0 AND is_sold = 0
            ORDER BY first_seen DESC
        ''')
        pending = c.fetchall()

        if not pending:
            log.info("所有車輛詳情頁都已爬過")
            return 0, 0

        log.info(f"需爬取 {len(pending)} 輛車的詳情頁")
        detail_count = 0
        photo_total = 0
        consecutive_failures = 0  # 連續失敗計數
        failed_items = []  # 失敗項目隊列 [(vid, car_no, has_photo, source), ...]

        for i, row in enumerate(pending):
            vid, car_no, has_photo = row[0], row[1], row[2]
            source = row[3] if len(row) > 3 and row[3] else 'sell'

            src_tag = f"[{source}]" if source != 'sell' else ""
            log.info(f"  [{i+1}/{len(pending)}] {src_tag} 詳情 vid={vid} ({car_no})")
            self._delay(DETAIL_DELAY_MIN, DETAIL_DELAY_MAX)

            detail = self.scrape_detail(vid, source)
            if not detail:
                consecutive_failures += 1
                log.warning(f"    詳情頁爬取失敗，加入重試隊列 (連續失敗: {consecutive_failures})")
                failed_items.append((vid, car_no, has_photo, source))
                # 連續失敗時增加等待時間，避免被限流
                if consecutive_failures >= 3:
                    wait_time = min(consecutive_failures * 10, 60)  # 最多等 60 秒
                    log.info(f"    連續失敗 {consecutive_failures} 次，等待 {wait_time} 秒...")
                    time.sleep(wait_time)
                continue

            self._save_detail_to_db(conn, vid, detail)
            consecutive_failures = 0  # 成功時重置計數

            # 下載圖片
            if download_images and detail.get('photo_count', 0) > 0:
                results = self.download_photos(
                    vid, car_no or vid,
                    detail.get('photo_urls', []),
                    detail.get('photo_urls_fallback', []),
                    detail.get('photo_urls_medium', []),
                )
                self._save_photos_to_db(conn, vid, results)
                downloaded = sum(1 for r in results if r[3])
                photo_total += downloaded
                log.info(f"    圖片 {downloaded}/{len(results)} 張")

            detail_count += 1

        # 處理失敗重試隊列
        if failed_items:
            retry_success, retry_photos = self._retry_failed_details(
                conn, failed_items, download_images
            )
            detail_count += retry_success
            photo_total += retry_photos

        log.info(f"詳情頁完成: {detail_count} 輛, {photo_total} 張圖片")
        return detail_count, photo_total

    def _retry_failed_details(self, conn, failed_items, download_images=True):
        """
        重試失敗的詳情頁抓取
        最多重試 3 輪，每輪之間等待時間遞增
        """
        if not failed_items:
            return 0, 0

        detail_count = 0
        photo_total = 0
        retry_queue = list(failed_items)

        for retry_round in range(1, self._max_retries + 1):
            if not retry_queue:
                break

            log.info(f"")
            log.info(f"=== 重試第 {retry_round}/{self._max_retries} 輪，共 {len(retry_queue)} 筆 ===")

            # 每輪重試前等待，時間遞增
            wait_time = retry_round * 30  # 30秒, 60秒, 90秒
            log.info(f"等待 {wait_time} 秒後開始重試...")
            time.sleep(wait_time)

            still_failed = []

            for i, (vid, car_no, has_photo, source) in enumerate(retry_queue):
                src_tag = f"[{source}]" if source != 'sell' else ""
                log.info(f"  [重試 {i+1}/{len(retry_queue)}] {src_tag} vid={vid} ({car_no})")
                self._delay(DETAIL_DELAY_MIN + 1, DETAIL_DELAY_MAX + 2)  # 重試時延遲更長

                detail = self.scrape_detail(vid, source)
                if not detail:
                    log.warning(f"    重試失敗")
                    still_failed.append((vid, car_no, has_photo, source))
                    continue

                log.info(f"    重試成功!")
                self._save_detail_to_db(conn, vid, detail)

                # 下載圖片
                if download_images and detail.get('photo_count', 0) > 0:
                    results = self.download_photos(
                        vid, car_no or vid,
                        detail.get('photo_urls', []),
                        detail.get('photo_urls_fallback', []),
                        detail.get('photo_urls_medium', []),
                    )
                    self._save_photos_to_db(conn, vid, results)
                    downloaded = sum(1 for r in results if r[3])
                    photo_total += downloaded
                    log.info(f"    圖片 {downloaded}/{len(results)} 張")

                detail_count += 1

            retry_queue = still_failed

            if retry_queue:
                log.info(f"第 {retry_round} 輪完成，仍有 {len(retry_queue)} 筆失敗")
            else:
                log.info(f"第 {retry_round} 輪完成，所有重試都成功!")

        if retry_queue:
            log.warning(f"重試結束，仍有 {len(retry_queue)} 筆無法抓取:")
            for vid, car_no, _, source in retry_queue[:10]:  # 最多顯示 10 筆
                log.warning(f"  - {source}/{vid} ({car_no})")
            if len(retry_queue) > 10:
                log.warning(f"  ... 還有 {len(retry_queue) - 10} 筆")

        return detail_count, photo_total

    def _save_detail_to_db(self, conn, vid, detail):
        """詳情頁資料更新到 DB"""
        c = conn.cursor()
        now = datetime.now().isoformat()

        c.execute('''
            UPDATE cars SET
                car_type=?, make_en=?,
                description=?, contact_name=?, contact_phone=?,
                original_price=?, original_price_num=?,
                photo_count=?, comments=?, views=?,
                source_url=?,
                detail_scraped=1, scraped_at=?, last_seen=?
            WHERE vid=?
        ''', (
            detail.get('car_type', ''),
            detail.get('make_en', ''),
            detail.get('description', ''),
            detail.get('contact_name', ''),
            detail.get('contact_phone', ''),
            detail.get('original_price', ''),
            detail.get('original_price_num', 0),
            detail.get('photo_count', 0),
            detail.get('comments', 0),
            detail.get('views', 0),
            detail.get('source_url', ''),
            now, now, vid,
        ))

        # 用詳情頁更完整的資料覆蓋
        for field in ['make', 'model', 'fuel', 'seats', 'engine_cc', 'transmission', 'year']:
            if detail.get(field):
                c.execute(f'UPDATE cars SET {field}=? WHERE vid=?', (detail[field], vid))
        if detail.get('price'):
            c.execute('UPDATE cars SET price=?, price_num=? WHERE vid=?',
                       (detail['price'], detail.get('price_num', 0), vid))

        conn.commit()

    def _save_photos_to_db(self, conn, vid, results):
        """圖片紀錄存入 DB（先清除舊紀錄再寫入新的）"""
        c = conn.cursor()
        now = datetime.now().isoformat()

        # 清除舊紀錄（避免舊的錯誤圖片殘留，例如 cmy 車行頁混入其他車的圖）
        c.execute('DELETE FROM car_photos WHERE vid = ?', (vid,))

        for (idx, orig_url, local_path, success) in results:
            c.execute('''
                INSERT INTO car_photos (vid, photo_index, original_url, local_path, downloaded, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (vid, idx, orig_url, local_path, 1 if success else 0, now))

        conn.commit()

    def _update_log(self, conn, log_id, stats, status):
        """更新爬取日誌"""
        c = conn.cursor()
        now = datetime.now().isoformat()
        c.execute('''
            UPDATE scrape_log SET
                finished_at=?, total_pages=?, total_list_cars=?,
                new_cars=?, updated_cars=?, details_scraped=?,
                photos_downloaded=?, status=?
            WHERE id=?
        ''', (
            now, stats['total_pages'], stats['total_list_cars'],
            stats['new_cars'], stats['updated_cars'],
            stats['details_scraped'], stats['photos_downloaded'],
            status, log_id,
        ))
        conn.commit()

    def _print_stats(self, conn):
        """印出資料庫統計"""
        c = conn.cursor()

        c.execute('SELECT COUNT(*) FROM cars')
        total = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM cars WHERE is_sold = 0')
        active = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM cars WHERE is_sold = 1')
        sold = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM cars WHERE detail_scraped = 1')
        detailed = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM car_photos WHERE downloaded = 1')
        photos = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM cars WHERE first_seen >= date("now")')
        today_new = c.fetchone()[0]

        # 來源統計
        c.execute("SELECT source, COUNT(*) FROM cars WHERE is_sold=0 GROUP BY source")
        source_stats = c.fetchall()

        c.execute('''
            SELECT make, COUNT(*) as cnt FROM cars
            WHERE is_sold = 0 GROUP BY make ORDER BY cnt DESC LIMIT 10
        ''')
        top_makes = c.fetchall()

        log.info("")
        log.info("=" * 50)
        log.info("  資料庫統計")
        log.info("=" * 50)
        log.info(f"  總車輛數: {total}")
        log.info(f"  在售中:   {active}")
        log.info(f"  已售出:   {sold}")
        log.info(f"  已爬詳情: {detailed}")
        log.info(f"  已下載圖: {photos}")
        log.info(f"  今日新增: {today_new}")
        log.info("")
        log.info("  來源統計 (在售):")
        for src, cnt in source_stats:
            src_label = SOURCES.get(src, {}).get('name', src or 'sell')
            log.info(f"    {src_label}: {cnt} 輛")
        log.info("")
        log.info("  熱門品牌 (在售):")
        for make, cnt in top_makes:
            log.info(f"    {make}: {cnt} 輛")
        log.info("=" * 50)


# ============================================================
# 匯出
# ============================================================
def export_to_json(conn, output_path=None):
    """匯出所有車輛到 JSON（含圖片路徑）"""
    if output_path is None:
        output_path = os.path.join(BASE_DIR, "cars_export.json")

    c = conn.cursor()

    c.execute('SELECT * FROM cars ORDER BY first_seen DESC')
    columns = [desc[0] for desc in c.description]
    rows = c.fetchall()

    cars = []
    for row in rows:
        car = dict(zip(columns, row))

        c.execute('''
            SELECT photo_index, local_path, original_url, downloaded
            FROM car_photos WHERE vid = ? ORDER BY photo_index
        ''', (car['vid'],))
        photos = []
        for p in c.fetchall():
            photos.append({
                'index': p[0],
                'local_path': p[1],
                'original_url': p[2],
                'downloaded': bool(p[3]),
            })
        car['photos'] = photos
        cars.append(car)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(cars, f, ensure_ascii=False, indent=2)

    log.info(f"已匯出 {len(cars)} 輛車到 {output_path}")
    return output_path


# ============================================================
# 主程式入口
# ============================================================
# ============================================================
# Lock file（防止重複執行）
# ============================================================
def _acquire_lock():
    """取得 lock file，防止同時跑多個爬蟲實例"""
    if os.path.exists(LOCK_PATH):
        try:
            with open(LOCK_PATH, 'r') as f:
                pid = int(f.read().strip())
            # 檢查 PID 是否還活著
            if sys.platform == 'win32':
                import ctypes
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(0x0400, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    return False  # 程序還在跑
            else:
                os.kill(pid, 0)  # Unix: 不發信號，只檢查是否存在
                return False  # 程序還在跑
        except (ValueError, OSError, ProcessLookupError):
            pass  # PID 無效或已結束，可以覆蓋 lock

    with open(LOCK_PATH, 'w') as f:
        f.write(str(os.getpid()))
    return True


def _release_lock():
    """釋放 lock file"""
    try:
        if os.path.exists(LOCK_PATH):
            os.remove(LOCK_PATH)
    except OSError:
        pass


def main():
    import argparse

    parser = argparse.ArgumentParser(description='28car.com 完整爬蟲（私人+車行）')
    parser.add_argument('--max-pages', type=int, default=None,
                        help='每個來源最多爬幾頁列表 (預設=全部)')
    parser.add_argument('--no-details', action='store_true',
                        help='跳過詳情頁爬取')
    parser.add_argument('--no-images', action='store_true',
                        help='跳過圖片下載')
    parser.add_argument('--export-only', action='store_true',
                        help='只做 JSON 匯出（不爬取）')
    parser.add_argument('--daily', action='store_true',
                        help='每日智能更新模式（只掃描有變化的頁面）')
    parser.add_argument('--stale-days', type=int, default=14,
                        help='超過幾天沒出現標記為下架 (預設=14)')
    parser.add_argument('--source', type=str, default='all',
                        choices=['sell', 'cmy', 'all'],
                        help='爬取來源: sell=私人, cmy=車行, all=全部 (預設=all)')
    args = parser.parse_args()

    # --- Lock file 防止重複執行 ---
    if not args.export_only:
        if not _acquire_lock():
            log.error("另一個爬蟲實例正在執行中，退出。")
            log.error(f"如果確定沒有在跑，請手動刪除 {LOCK_PATH}")
            return 1

    # 確定要爬的來源
    if args.source == 'all':
        sources = ['sell', 'cmy']
    else:
        sources = [args.source]

    log.info("=" * 60)
    log.info("  28car.com 完整爬蟲系統")
    log.info(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)
    log.info(f"  資料庫: {DB_PATH}")
    log.info(f"  圖片目錄: {IMAGES_DIR}")
    log.info(f"  來源: {', '.join(SOURCES[s]['name'] for s in sources)}")
    log.info("")

    exit_code = 0

    try:
        if args.export_only:
            conn = init_db()
            export_to_json(conn)
            conn.close()
            return 0

        scraper = Scraper28Car()

        # 註冊信號處理（優雅關閉）
        signal.signal(signal.SIGINT, scraper.handle_shutdown)
        signal.signal(signal.SIGTERM, scraper.handle_shutdown)

        if args.daily:
            stats = scraper.run_daily_update(
                stale_days=args.stale_days,
                download_images=not args.no_images,
                sources=sources,
            )
            log.info("")
            log.info("每日更新完成！")
            log.info(f"  掃描頁數: {stats['total_pages']}")
            log.info(f"  列表車輛: {stats['total_list_cars']}")
            log.info(f"  新增: {stats['new_cars']}")
            log.info(f"  更新: {stats['updated_cars']}")
            log.info(f"  不變: {stats['unchanged_cars']}")
            log.info(f"  詳情: {stats['details_scraped']}")
            log.info(f"  圖片: {stats['photos_downloaded']}")
            log.info(f"  標記下架: {stats['stale_marked']}")
        else:
            stats = scraper.run_full_scrape(
                max_pages=args.max_pages,
                scrape_details=not args.no_details,
                download_images=not args.no_images,
                sources=sources,
            )
            log.info("")
            log.info("爬蟲完成！")
            log.info(f"  列表頁數: {stats['total_pages']}")
            log.info(f"  列表車輛: {stats['total_list_cars']}")
            log.info(f"  新增: {stats['new_cars']}")
            log.info(f"  更新: {stats['updated_cars']}")
            log.info(f"  詳情: {stats['details_scraped']}")
            log.info(f"  圖片: {stats['photos_downloaded']}")

        # 爬蟲完成後重建聯絡人分組
        try:
            from migrate_db import rebuild_contact_groups
            log.info("")
            log.info("重建聯絡人分組...")
            rebuild_conn = sqlite3.connect(DB_PATH, timeout=30)
            rebuild_conn.execute("PRAGMA journal_mode=WAL")
            rebuild_conn.execute("PRAGMA busy_timeout=10000")
            rebuild_contact_groups(rebuild_conn)
            rebuild_conn.close()
            log.info("聯絡人分組重建完成")
        except Exception as e:
            log.warning(f"聯絡人分組重建失敗（不影響爬蟲）: {e}")

    except Exception as e:
        log.error(f"爬蟲執行失敗: {e}")
        import traceback
        traceback.print_exc()
        exit_code = 1

    finally:
        _release_lock()

    return exit_code


if __name__ == '__main__':
    sys.exit(main() or 0)
