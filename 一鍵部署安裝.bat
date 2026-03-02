@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title 28Car 一鍵部署安裝

:: ============================================
:: 檢查並請求管理員權限
:: ============================================
>nul 2>&1 "%SYSTEMROOT%\system32\cacls.exe" "%SYSTEMROOT%\system32\config\system"
if '%errorlevel%' NEQ '0' (
    echo.
    echo ============================================
    echo   需要管理員權限才能完成安裝
    echo   正在請求權限...
    echo ============================================
    echo.
    goto :UAC_Prompt
) else (
    goto :Got_Admin
)

:UAC_Prompt
echo Set UAC = CreateObject^("Shell.Application"^) > "%temp%\getadmin.vbs"
echo UAC.ShellExecute "%~s0", "", "", "runas", 1 >> "%temp%\getadmin.vbs"
"%temp%\getadmin.vbs"
del "%temp%\getadmin.vbs"
exit /b

:Got_Admin
pushd "%CD%"
cd /d "%~dp0"

echo ============================================
echo    28Car 車輛管理系統 - 一鍵部署安裝
echo ============================================
echo.
echo [OK] 已取得管理員權限
echo.

:: 取得目前腳本所在目錄
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

:: 檢查 exe 是否存在
if not exist "%SCRIPT_DIR%\28car_server.exe" (
    echo [!] 找不到 28car_server.exe
    echo     請確認檔案完整性
    echo.
    pause
    exit /b 1
)

echo 安裝路徑: %SCRIPT_DIR%
echo.
echo 即將執行以下設定:
echo   [1] 建立桌面捷徑
echo   [2] 設定開機自動啟動
echo   [3] 設定每日排程（備份 00:00、爬蟲 01:00、簡訊 10:00）
echo   [4] 設定防火牆（允許區域網路連線）
echo   [5] 啟動伺服器
echo.
choice /C YN /M "是否繼續"
if errorlevel 2 goto :END

echo.
echo ============================================
echo  步驟 1/5: 建立桌面捷徑
echo ============================================

:: 使用 PowerShell 建立桌面捷徑（避免中文編碼問題）
powershell -Command "$desktop = [Environment]::GetFolderPath('Desktop'); $ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut(\"$desktop\28Car Server.lnk\"); $sc.TargetPath = '%SCRIPT_DIR%\28car_server.exe'; $sc.WorkingDirectory = '%SCRIPT_DIR%'; $sc.Save()"
if %errorlevel%==0 (
    echo [OK] 建立捷徑: 28Car Server（啟動伺服器）
) else (
    echo [!] 建立捷徑失敗
)

powershell -Command "$desktop = [Environment]::GetFolderPath('Desktop'); $ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut(\"$desktop\28Car Web.lnk\"); $sc.TargetPath = 'http://localhost:5000'; $sc.Save()"
if %errorlevel%==0 (
    echo [OK] 建立捷徑: 28Car Web（開啟網頁）
) else (
    echo [!] 建立捷徑失敗
)

del "%VBS_FILE%"
echo [OK] 桌面捷徑已建立

echo.
echo ============================================
echo  步驟 2/5: 設定開機自動啟動
echo ============================================

set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

:: 使用 PowerShell 建立啟動資料夾捷徑（避免中文編碼問題）
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut('%STARTUP_FOLDER%\28Car Server.lnk'); $sc.TargetPath = '%SCRIPT_DIR%\28car_server.exe'; $sc.WorkingDirectory = '%SCRIPT_DIR%'; $sc.WindowStyle = 7; $sc.Save()"
if %errorlevel%==0 (
    echo [OK] 開機自動啟動已設定
) else (
    echo [!] 開機自動啟動設定失敗
)

echo.
echo ============================================
echo  步驟 3/5: 設定每日排程任務
echo ============================================

:: 刪除舊排程（如果存在）
schtasks /delete /tn "28car_backup" /f >nul 2>&1
schtasks /delete /tn "28car_daily" /f >nul 2>&1
schtasks /delete /tn "28car_sms" /f >nul 2>&1

:: 建立備份排程（每天 00:00）
if exist "%SCRIPT_DIR%\28car_backup.exe" (
    schtasks /create /tn "28car_backup" /tr "\"%SCRIPT_DIR%\28car_backup.exe\"" /sc daily /st 00:00 /f >nul 2>&1
) else (
    schtasks /create /tn "28car_backup" /tr "python \"%SCRIPT_DIR%\backup_db.py\"" /sc daily /st 00:00 /f >nul 2>&1
)
if %errorlevel%==0 (
    echo [OK] 28car_backup - 每天 00:00 自動備份資料庫
) else (
    echo [!] 備份排程設定失敗
)

:: 建立爬蟲排程（每天 01:00）
if exist "%SCRIPT_DIR%\28car_scraper.exe" (
    schtasks /create /tn "28car_daily" /tr "\"%SCRIPT_DIR%\28car_scraper.exe\" --daily" /sc daily /st 01:00 /f >nul 2>&1
) else (
    schtasks /create /tn "28car_daily" /tr "python \"%SCRIPT_DIR%\scraper_28car.py\" --daily" /sc daily /st 01:00 /f >nul 2>&1
)
if %errorlevel%==0 (
    echo [OK] 28car_daily - 每天 01:00 自動執行爬蟲
) else (
    echo [!] 爬蟲排程設定失敗
)

:: 建立簡訊排程（每天 10:00）
if exist "%SCRIPT_DIR%\28car_sms.exe" (
    schtasks /create /tn "28car_sms" /tr "\"%SCRIPT_DIR%\28car_sms.exe\" --daily" /sc daily /st 10:00 /f >nul 2>&1
) else (
    schtasks /create /tn "28car_sms" /tr "python \"%SCRIPT_DIR%\sms_sender.py\" --daily" /sc daily /st 10:00 /f >nul 2>&1
)
if %errorlevel%==0 (
    echo [OK] 28car_sms - 每天 10:00 自動發送簡訊
) else (
    echo [!] 簡訊排程設定失敗
)

echo.
echo ============================================
echo  步驟 4/5: 設定防火牆（允許區域網路連線）
echo ============================================

:: 刪除舊的防火牆規則（如果存在）
netsh advfirewall firewall delete rule name="28Car Server" >nul 2>&1

:: 新增防火牆規則
netsh advfirewall firewall add rule name="28Car Server" dir=in action=allow protocol=tcp localport=5000 >nul 2>&1
if %errorlevel%==0 (
    echo [OK] 防火牆規則已設定（允許 TCP 5000 埠）
) else (
    echo [!] 防火牆設定需要管理員權限
    echo     如需區域網路存取，請以管理員身分重新執行
)

echo.
echo ============================================
echo  步驟 5/5: 啟動伺服器
echo ============================================

:: 檢查是否已經在運行
netstat -an | findstr ":5000.*LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [OK] 伺服器已經在運行中
) else (
    echo 正在啟動伺服器...
    start "" "%SCRIPT_DIR%\28car_server.exe"
    timeout /t 3 /nobreak >nul
    echo [OK] 伺服器已啟動
)

:: 取得本機 IP 位址
set "LOCAL_IP=未知"
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    for /f "tokens=1" %%b in ("%%a") do (
        if "!LOCAL_IP!"=="未知" set "LOCAL_IP=%%b"
    )
)

echo.
echo ============================================
echo  驗證排程設定
echo ============================================

:: 驗證排程任務是否建立成功
set "BACKUP_OK=0"
set "DAILY_OK=0"
set "SMS_OK=0"

schtasks /query /tn "28car_backup" >nul 2>&1
if %errorlevel%==0 (
    set "BACKUP_OK=1"
    echo [OK] 28car_backup：已建立
) else (
    echo [!!] 28car_backup：建立失敗
)

schtasks /query /tn "28car_daily" >nul 2>&1
if %errorlevel%==0 (
    set "DAILY_OK=1"
    echo [OK] 28car_daily：已建立
) else (
    echo [!!] 28car_daily：建立失敗
)

schtasks /query /tn "28car_sms" >nul 2>&1
if %errorlevel%==0 (
    set "SMS_OK=1"
    echo [OK] 28car_sms：已建立
) else (
    echo [!!] 28car_sms：建立失敗
)

echo.
echo ============================================
echo  安裝完成！
echo ============================================
echo.
echo  桌面已新增:
echo    - 28Car Server（啟動伺服器）
echo    - 28Car Web（開啟網頁）
echo.
if "!BACKUP_OK!"=="1" if "!DAILY_OK!"=="1" if "!SMS_OK!"=="1" (
    echo  [OK] 自動化設定（全部成功）:
) else (
    echo  [!] 自動化設定（部分失敗，請檢查上方訊息）:
)
echo    - 開機時伺服器會自動啟動
echo    - 每天 00:00 自動備份資料庫
echo    - 每天 01:00 自動執行爬蟲更新資料
echo    - 每天 10:00 自動發送簡訊
echo.
echo  ============================================
echo   連線網址
echo  ============================================
echo.
echo   本機使用:
echo     http://localhost:5000
echo.
echo   其他電腦/手機連線（同一 WiFi 下）:
echo     http://!LOCAL_IP!:5000
echo.
echo   預設管理員帳號: admin / admin
echo   （首次登入需更改密碼）
echo.
echo ============================================

:: 詢問是否開啟瀏覽器
choice /C YN /M "是否立即開啟瀏覽器"
if errorlevel 2 goto :END
if errorlevel 1 (
    start http://localhost:5000
)

:END
echo.
pause
