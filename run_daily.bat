@echo off
chcp 65001 >nul
REM ============================================================
REM 28car.com 每日智能更新排程腳本
REM ============================================================
REM
REM 【注意】執行「一鍵部署安裝.bat」會自動設定每日排程！
REM        一般情況下不需要手動設定。
REM
REM 使用方式：
REM   1. 自動執行: 由 Windows 排程每天 01:00 自動執行
REM   2. 手動執行: 雙擊此檔案
REM
REM 手動設定排程（如自動設定失敗）：
REM   以管理員身分執行 CMD：
REM   schtasks /create /tn "28car_daily" /tr "安裝路徑\run_daily.bat" /sc daily /st 01:00 /f
REM
REM   刪除排程：
REM   schtasks /delete /tn "28car_daily" /f
REM
REM 更新邏輯說明：
REM   --daily        智能更新：從第1頁掃描，偵測新增/更新車源
REM                  連續2頁沒變化自動停止（不需掃全部4700+頁）
REM   --stale-days 7 超過7天沒出現在列表的車輛標記為下架
REM ============================================================

REM 切換到腳本所在目錄
cd /d "%~dp0"

REM 設定日誌檔案
set "LOG_FILE=%~dp0daily_task.log"

REM 記錄開始時間
echo. >> "%LOG_FILE%"
echo ============================================ >> "%LOG_FILE%"
echo  每日任務開始 >> "%LOG_FILE%"
echo  %date% %time% >> "%LOG_FILE%"
echo ============================================ >> "%LOG_FILE%"

echo ============================================
echo  28Car 每日自動更新
echo  %date% %time%
echo ============================================
echo.

echo ============================================
echo  步驟 0/2: 執行資料庫備份
echo ============================================
echo [%date% %time%] 開始執行備份 >> "%LOG_FILE%"
python backup_db.py
if %errorlevel%==0 (
    echo [%date% %time%] 備份執行成功 >> "%LOG_FILE%"
) else (
    echo [%date% %time%] 備份執行失敗 >> "%LOG_FILE%"
)

echo.
echo ============================================
echo  步驟 1/2: 執行每日爬蟲
echo ============================================
echo [%date% %time%] 開始執行爬蟲 >> "%LOG_FILE%"

python scraper_28car.py --daily --stale-days 7
set SCRAPER_RESULT=%errorlevel%

if %SCRAPER_RESULT%==0 (
    echo [%date% %time%] 爬蟲執行成功 >> "%LOG_FILE%"
) else (
    echo [%date% %time%] 爬蟲執行失敗，錯誤碼: %SCRAPER_RESULT% >> "%LOG_FILE%"
)

echo.
echo ============================================
echo  步驟 2/2: 執行每日簡訊發送
echo ============================================
echo [%date% %time%] 開始執行簡訊發送 >> "%LOG_FILE%"

python sms_sender.py --daily
if %errorlevel%==0 (
    echo [%date% %time%] 簡訊發送完成 >> "%LOG_FILE%"
) else (
    echo [%date% %time%] 簡訊發送失敗 >> "%LOG_FILE%"
)

echo.
echo ============================================
echo  每日任務執行完畢
echo  %date% %time%
echo ============================================

echo [%date% %time%] 每日任務執行完畢 >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

REM 保留最近 1000 行日誌（避免日誌檔案過大）
if exist "%LOG_FILE%" (
    set "TEMP_LOG=%TEMP%\daily_task_temp.log"
    powershell -Command "Get-Content '%LOG_FILE%' | Select-Object -Last 1000 | Set-Content '%TEMP_LOG%'" 2>nul
    if exist "%TEMP_LOG%" (
        move /y "%TEMP_LOG%" "%LOG_FILE%" >nul 2>&1
    )
)
