@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ==================================================
echo   28car 車源系統 - 首次安裝
echo ==================================================
echo.

:: 設定安裝目錄
set "INSTALL_DIR=%USERPROFILE%\28car-system"
set "REPO_URL=https://github.com/GGC-svg/28car-system.git"

:: 檢查 Git 是否安裝
where git >nul 2>&1
if errorlevel 1 (
    echo [錯誤] 未安裝 Git
    echo.
    echo 請先安裝 Git for Windows:
    echo   下載網址: https://git-scm.com/download/win
    echo.
    echo 安裝完成後，請重新執行此腳本。
    pause
    exit /b 1
)

echo [OK] Git 已安裝
echo.

:: 檢查目錄是否已存在
if exist "%INSTALL_DIR%" (
    echo [警告] 目錄已存在: %INSTALL_DIR%
    echo.
    set /p CONFIRM="是否刪除舊目錄並重新安裝？(Y/N): "
    if /i "!CONFIRM!"=="Y" (
        echo 正在刪除舊目錄...
        rmdir /s /q "%INSTALL_DIR%"
    ) else (
        echo 已取消安裝。
        pause
        exit /b 0
    )
)

echo.
echo 正在從 GitHub 下載程式...
echo   來源: %REPO_URL%
echo   目標: %INSTALL_DIR%
echo.

git clone "%REPO_URL%" "%INSTALL_DIR%"

if errorlevel 1 (
    echo.
    echo [錯誤] 下載失敗！
    echo 請檢查網路連線，或聯繫管理員。
    pause
    exit /b 1
)

echo.
echo [OK] 程式下載完成！
echo.

:: 執行一鍵部署安裝
echo 正在執行安裝程序...
echo.
cd /d "%INSTALL_DIR%"
call "一鍵部署安裝.bat"

echo.
echo ==================================================
echo   安裝完成！
echo ==================================================
echo.
echo   安裝位置: %INSTALL_DIR%
echo   啟動程式: 執行「啟動伺服器.bat」
echo   檢查更新: 執行「檢查更新.bat」
echo.
pause
