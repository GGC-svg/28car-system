@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: 資料庫每日備份腳本
:: 只保留一個備份檔案，每日覆蓋

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "DB_FILE=%SCRIPT_DIR%\cars_28car.db"
set "BACKUP_DIR=%SCRIPT_DIR%\backup"
set "BACKUP_FILE=%BACKUP_DIR%\cars_28car_backup.db"
set "LOG_FILE=%BACKUP_DIR%\backup.log"

:: 取得當前日期時間
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I
set "DATE_STR=%datetime:~0,4%-%datetime:~4,2%-%datetime:~6,2% %datetime:~8,2%:%datetime:~10,2%:%datetime:~12,2%"

:: 建立備份目錄（如果不存在）
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"

:: 檢查資料庫是否存在
if not exist "%DB_FILE%" (
    echo [%DATE_STR%] 錯誤：找不到資料庫檔案 >> "%LOG_FILE%"
    exit /b 1
)

:: 執行備份（覆蓋舊備份）
copy /Y "%DB_FILE%" "%BACKUP_FILE%" >nul 2>&1

if %errorlevel%==0 (
    :: 取得檔案大小
    for %%F in ("%DB_FILE%") do set "FILE_SIZE=%%~zF"
    set /a "SIZE_MB=!FILE_SIZE! / 1024 / 1024"
    echo [%DATE_STR%] 備份成功 (大小: !SIZE_MB! MB) >> "%LOG_FILE%"
) else (
    echo [%DATE_STR%] 備份失敗 >> "%LOG_FILE%"
    exit /b 1
)

:: 保持日誌檔案不要太大（只保留最近 30 行）
if exist "%LOG_FILE%" (
    set "TEMP_LOG=%BACKUP_DIR%\backup_temp.log"
    type "%LOG_FILE%" 2>nul | more +0 > "%TEMP_LOG%"
    for /f %%A in ('type "%TEMP_LOG%" ^| find /c /v ""') do set "LINE_COUNT=%%A"
    if !LINE_COUNT! gtr 30 (
        set /a "SKIP_LINES=!LINE_COUNT! - 30"
        more +!SKIP_LINES! "%TEMP_LOG%" > "%LOG_FILE%"
    )
    del "%TEMP_LOG%" 2>nul
)

exit /b 0
