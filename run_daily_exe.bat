@echo off
chcp 65001 >nul
REM ============================================================
REM 28car.com 每日智能更新排程腳本（獨立執行檔版本）
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

echo [0/2] 執行資料庫備份...
echo [%date% %time%] 開始執行備份 >> "%LOG_FILE%"
if not exist "backup" mkdir backup
copy /Y "cars_28car.db" "backup\cars_28car_backup.db" >nul 2>&1
if %errorlevel%==0 (
    echo [%date% %time%] 備份執行成功 >> "%LOG_FILE%"
    echo      備份成功
) else (
    echo [%date% %time%] 備份執行失敗 >> "%LOG_FILE%"
    echo      備份失敗
)

echo.
echo [1/2] 執行每日爬蟲...
echo [%date% %time%] 開始執行爬蟲 >> "%LOG_FILE%"

"%~dp028car_scraper.exe" --daily --stale-days 7
set SCRAPER_RESULT=%errorlevel%

if %SCRAPER_RESULT%==0 (
    echo [%date% %time%] 爬蟲執行成功 >> "%LOG_FILE%"
) else (
    echo [%date% %time%] 爬蟲執行失敗，錯誤碼: %SCRAPER_RESULT% >> "%LOG_FILE%"
)

echo.
echo [2/2] 執行每日簡訊發送...
if exist "%~dp028car_sms.exe" (
    echo [%date% %time%] 開始執行簡訊發送 >> "%LOG_FILE%"
    "%~dp028car_sms.exe" --daily
    if %errorlevel%==0 (
        echo [%date% %time%] 簡訊發送完成 >> "%LOG_FILE%"
    ) else (
        echo [%date% %time%] 簡訊發送失敗 >> "%LOG_FILE%"
    )
) else (
    echo      (簡訊功能未安裝，跳過)
    echo [%date% %time%] 簡訊功能未安裝，跳過 >> "%LOG_FILE%"
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
