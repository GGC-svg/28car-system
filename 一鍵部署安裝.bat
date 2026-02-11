@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title 28Car 一鍵部署安裝

echo ============================================
echo    28Car 車輛管理系統 - 一鍵部署安裝
echo ============================================
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
echo   [3] 設定每日爬蟲排程
echo   [4] 設定每日資料庫備份
echo   [5] 設定防火牆（允許區域網路連線）
echo   [6] 啟動伺服器
echo.
choice /C YN /M "是否繼續"
if errorlevel 2 goto :END

echo.
echo ============================================
echo  步驟 1/6: 建立桌面捷徑
echo ============================================

set "DESKTOP=%USERPROFILE%\Desktop"
set "VBS_FILE=%TEMP%\create_shortcut.vbs"

:: 建立「啟動伺服器」桌面捷徑
echo Set oWS = WScript.CreateObject("WScript.Shell") > "%VBS_FILE%"
echo sLinkFile = "%DESKTOP%\28Car 車輛管理.lnk" >> "%VBS_FILE%"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%VBS_FILE%"
echo oLink.TargetPath = "%SCRIPT_DIR%\28car_server.exe" >> "%VBS_FILE%"
echo oLink.WorkingDirectory = "%SCRIPT_DIR%" >> "%VBS_FILE%"
echo oLink.Description = "28Car 車輛管理系統" >> "%VBS_FILE%"
echo oLink.Save >> "%VBS_FILE%"
cscript //nologo "%VBS_FILE%"

:: 建立「開啟網頁」桌面捷徑
echo Set oWS = WScript.CreateObject("WScript.Shell") > "%VBS_FILE%"
echo sLinkFile = "%DESKTOP%\28Car 開啟網頁.lnk" >> "%VBS_FILE%"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%VBS_FILE%"
echo oLink.TargetPath = "http://localhost:5000" >> "%VBS_FILE%"
echo oLink.Description = "開啟 28Car 網頁介面" >> "%VBS_FILE%"
echo oLink.Save >> "%VBS_FILE%"
cscript //nologo "%VBS_FILE%"

del "%VBS_FILE%"
echo [OK] 桌面捷徑已建立

echo.
echo ============================================
echo  步驟 2/6: 設定開機自動啟動
echo ============================================

set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_NAME=28Car伺服器.lnk"

:: 建立啟動資料夾捷徑
echo Set oWS = WScript.CreateObject("WScript.Shell") > "%VBS_FILE%"
echo sLinkFile = "%STARTUP_FOLDER%\%SHORTCUT_NAME%" >> "%VBS_FILE%"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%VBS_FILE%"
echo oLink.TargetPath = "%SCRIPT_DIR%\28car_server.exe" >> "%VBS_FILE%"
echo oLink.WorkingDirectory = "%SCRIPT_DIR%" >> "%VBS_FILE%"
echo oLink.Description = "28Car 車輛管理系統" >> "%VBS_FILE%"
echo oLink.WindowStyle = 7 >> "%VBS_FILE%"
echo oLink.Save >> "%VBS_FILE%"
cscript //nologo "%VBS_FILE%"
del "%VBS_FILE%"

echo [OK] 開機自動啟動已設定

echo.
echo ============================================
echo  步驟 3/6: 設定每日自動爬蟲排程
echo ============================================

:: 刪除舊排程（如果存在）
schtasks /delete /tn "28car_daily" /f >nul 2>&1

:: 建立新排程（每天早上 6:00 執行）
schtasks /create /tn "28car_daily" /tr "%SCRIPT_DIR%\run_daily.bat" /sc daily /st 06:00 /f >nul 2>&1
if %errorlevel%==0 (
    echo [OK] 每日排程已設定（每天早上 06:00 自動執行爬蟲）
) else (
    echo [!] 排程設定需要管理員權限，請手動設定
    echo     或以管理員身分重新執行此安裝程式
)

echo.
echo ============================================
echo  步驟 4/6: 設定每日資料庫備份
echo ============================================

:: 刪除舊排程（如果存在）
schtasks /delete /tn "28car_backup" /f >nul 2>&1

:: 建立新排程（每天凌晨 05:00 備份，在爬蟲之前）
schtasks /create /tn "28car_backup" /tr "%SCRIPT_DIR%\backup_db.bat" /sc daily /st 05:00 /f >nul 2>&1
if %errorlevel%==0 (
    echo [OK] 每日備份已設定（每天凌晨 05:00 自動備份資料庫）
    echo     備份位置: %SCRIPT_DIR%\backup\
) else (
    echo [!] 備份排程設定需要管理員權限
)

echo.
echo ============================================
echo  步驟 5/6: 設定防火牆（允許區域網路連線）
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
echo  步驟 6/6: 啟動伺服器
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
echo  安裝完成！
echo ============================================
echo.
echo  桌面已新增:
echo    - 28Car 車輛管理（啟動伺服器）
echo    - 28Car 開啟網頁（瀏覽器開啟）
echo.
echo  自動化設定:
echo    - 開機時伺服器會自動啟動
echo    - 每天 05:00 自動備份資料庫（保留於 backup 資料夾）
echo    - 每天 06:00 自動執行爬蟲更新資料
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
