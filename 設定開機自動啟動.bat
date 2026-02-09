@echo off
chcp 65001 >nul
title 設定開機自動啟動

echo ============================================
echo    28Car 車輛管理系統 - 開機自動啟動設定
echo ============================================
echo.

:: 取得目前腳本所在目錄
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

:: Windows 啟動資料夾路徑
set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

:: 捷徑名稱
set "SHORTCUT_NAME=28Car伺服器.lnk"

echo 偵測到安裝路徑: %SCRIPT_DIR%
echo 啟動資料夾: %STARTUP_FOLDER%
echo.

:: 檢查是否已設定
if exist "%STARTUP_FOLDER%\%SHORTCUT_NAME%" (
    echo [!] 已經設定過開機自動啟動
    echo.
    choice /C YN /M "是否要移除開機自動啟動"
    if errorlevel 2 goto :END
    if errorlevel 1 (
        del "%STARTUP_FOLDER%\%SHORTCUT_NAME%"
        echo.
        echo [OK] 已移除開機自動啟動
        goto :END
    )
)

:: 建立 VBS 腳本來產生捷徑（Windows 原生方法）
set "VBS_FILE=%TEMP%\create_shortcut.vbs"

echo Set oWS = WScript.CreateObject("WScript.Shell") > "%VBS_FILE%"
echo sLinkFile = "%STARTUP_FOLDER%\%SHORTCUT_NAME%" >> "%VBS_FILE%"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%VBS_FILE%"

:: 優先使用 exe，否則用 bat
if exist "%SCRIPT_DIR%\28car_server.exe" (
    echo oLink.TargetPath = "%SCRIPT_DIR%\28car_server.exe" >> "%VBS_FILE%"
) else (
    echo oLink.TargetPath = "%SCRIPT_DIR%\啟動伺服器.bat" >> "%VBS_FILE%"
)

echo oLink.WorkingDirectory = "%SCRIPT_DIR%" >> "%VBS_FILE%"
echo oLink.Description = "28Car 車輛管理系統" >> "%VBS_FILE%"
echo oLink.WindowStyle = 7 >> "%VBS_FILE%"
echo oLink.Save >> "%VBS_FILE%"

:: 執行 VBS 建立捷徑
cscript //nologo "%VBS_FILE%"
del "%VBS_FILE%"

if exist "%STARTUP_FOLDER%\%SHORTCUT_NAME%" (
    echo.
    echo ============================================
    echo [OK] 設定成功！
    echo.
    echo 下次開機後，伺服器會自動在背景啟動
    echo 你可以用瀏覽器開啟 http://localhost:5000
    echo ============================================
) else (
    echo.
    echo [錯誤] 設定失敗，請手動設定
)

:END
echo.
pause
