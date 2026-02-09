# 28Car 車輛管理系統 - 技術文檔

## 系統概述

28Car 車輛管理系統是一個整合式解決方案，用於管理香港 28car.com 網站的車輛資料，包含自動爬蟲、聯絡人群組化、簡訊行銷、使用者認證等功能。

## 核心功能

### 1. 網頁爬蟲 (Web Scraper)
- **檔案**: scraper_28car.py
- **功能**: 自動爬取 28car.com 車輛列表頁面
- **資料擷取**: 車輛名稱、價格、年份、賣家電話、發布日期

### 2. 聯絡人群組系統 (Contact Grouping)
- **檔案**: migrate_db.py
- **演算法**: Union-Find (並查集)
- **功能**: 自動偵測重複聯絡人、建立電話號碼群組

### 3. 賣家分類系統
| 分類 | 車輛數量 | 說明 |
|------|----------|------|
| private | 1 | 私人賣家 |
| broker | 2-4 | 同行 |
| dealer | >=5 | 車行 |

**手動修改分類**：可批量勾選聯絡人修改分類（標記 classification_manual=1 後爬蟲不覆蓋）

### 4. 簡訊發送系統 (SMS Sender)
- **檔案**: sms_sender.py
- **API**: OneWaySMS 香港

#### OneWaySMS API 回應碼
| 代碼 | 說明 |
|------|------|
| >0 | 成功 |
| -100 | 帳密錯誤 |
| -200 | 發送者ID無效 |
| -300 | 無效號碼 |
| -400 | 語言類型無效 |
| -500 | 訊息含無效字元 |
| -600 | 餘額不足 |

### 5. 登入系統 (Authentication)
- **帳號類型**: 管理員 (admin) / 一般使用者 (user)
- **預設帳號**: admin / admin（首次登入強制改密碼）
- **Session**: Cookie Session，24 小時有效

#### 權限控制
| 功能 | 管理員 | 一般使用者 |
|------|--------|------------|
| 車輛列表 | ✓ | ✓ |
| 聯絡人目錄 | ✓ | ✓ |
| 建立活動 | ✓ | ✗ |
| 簡訊系統 | ✓ | ✗ |
| 管理後台 | ✓ | ✗ |

### 6. 管理後台
- **使用者管理**: 新增、編輯、刪除帳號
- **操作日誌**: 系統操作記錄查詢
- **網路資訊**: 區域網路連線網址

### 7. 網頁管理介面
- **檔案**: web_demo.py, index.html
- **框架**: Flask
- **網址**: http://localhost:5000
- **區域網路**: http://[本機IP]:5000

## API 端點

### 認證 API
| 端點 | 方法 | 說明 |
|------|------|------|
| /api/auth/login | POST | 登入 |
| /api/auth/logout | POST | 登出 |
| /api/auth/me | GET | 當前使用者 |
| /api/auth/change-password | POST | 改密碼 |

### 車輛/聯絡人 API（需登入）
| 端點 | 方法 | 說明 |
|------|------|------|
| /api/cars | GET | 車輛列表 |
| /api/contacts | GET | 聯絡人列表 |
| /api/contact/<id>/logs | POST | 新增溝通紀錄 |
| /api/contacts/batch-classification | PUT | 批量修改分類 |
| /api/stats | GET | 統計數據 |

### 簡訊 API（僅管理員）
| 端點 | 方法 | 說明 |
|------|------|------|
| /api/sms/config | GET/POST | 簡訊設定 |
| /api/sms/send-now | POST | 立即發送 |
| /api/sms/logs | GET | 發送記錄 |

### 管理後台 API（僅管理員）
| 端點 | 方法 | 說明 |
|------|------|------|
| /api/admin/users | GET/POST | 使用者管理 |
| /api/admin/logs | GET | 操作日誌 |
| /api/admin/network-info | GET | 網路資訊 |

## 資料庫重要欄位

### contact_groups
- classification_manual: 手動分類標記（1=手動設定，爬蟲不覆蓋）

## 部署

1. 複製 car2 資料夾到目標電腦
2. 雙擊「一鍵部署安裝.bat」
3. 首次登入 admin/admin，強制改密碼
4. 其他電腦透過 http://[伺服器IP]:5000 連入

## 版本: v1.1 (2026-02-09)

### 更新內容
- 新增登入系統（管理員/一般使用者）
- 新增管理後台（使用者管理、操作日誌、網路資訊）
- 新增區域網路連線功能
- 新增批量修改聯絡人分類功能
- 溝通紀錄「誰聯絡的」自動帶入登入帳號
