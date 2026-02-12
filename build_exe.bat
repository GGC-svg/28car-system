@echo off
chcp 65001 >nul
title 28Car 打包工具

echo ============================================
echo   28Car 打包工具 - 建立獨立執行檔
echo ============================================
echo.

:: 檢查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [!] 找不到 Python，請先安裝 Python 3.10+
    pause
    exit /b 1
)

:: 檢查 PyInstaller
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [*] 安裝 PyInstaller...
    pip install pyinstaller
)

echo.
echo [1/3] 打包主程式 (28car_server.exe)...
echo.

:: 打包主伺服器
pyinstaller --onefile --noconsole ^
    --name "28car_server" ^
    --add-data "index.html;." ^
    --add-data "static;static" ^
    --hidden-import=flask ^
    --hidden-import=sqlite3 ^
    web_demo.py

if errorlevel 1 (
    echo [!] 主程式打包失敗
    pause
    exit /b 1
)

echo.
echo [2/3] 打包爬蟲程式 (28car_scraper.exe)...
echo.

:: 打包爬蟲
pyinstaller --onefile --console ^
    --name "28car_scraper" ^
    --hidden-import=requests ^
    --hidden-import=bs4 ^
    --hidden-import=sqlite3 ^
    scraper_28car.py

if errorlevel 1 (
    echo [!] 爬蟲程式打包失敗
    pause
    exit /b 1
)

echo.
echo [3/3] 整理輸出檔案...
echo.

:: 建立發佈目錄
if not exist "release" mkdir release

:: 複製執行檔
copy /Y "dist\28car_server.exe" "release\" >nul
copy /Y "dist\28car_scraper.exe" "release\" >nul

:: 複製必要檔案
copy /Y "index.html" "release\" >nul
copy /Y "一鍵部署安裝.bat" "release\" >nul
copy /Y "run_daily_exe.bat" "release\run_daily.bat" >nul
copy /Y "backup_db.bat" "release\" >nul
copy /Y "README.md" "release\" >nul 2>nul
copy /Y "VERSION" "release\" >nul

:: 複製 static 資料夾
if exist "static" (
    if not exist "release\static" mkdir "release\static"
    xcopy /E /Y "static\*" "release\static\" >nul
)

echo.
echo ============================================
echo  打包完成！
echo ============================================
echo.
echo  輸出位置: %cd%\release\
echo.
echo  發佈檔案清單:
echo    - 28car_server.exe     (主伺服器)
echo    - 28car_scraper.exe    (爬蟲程式)
echo    - index.html           (網頁介面)
echo    - 一鍵部署安裝.bat     (安裝腳本)
echo    - run_daily.bat        (每日排程)
echo    - backup_db.bat        (資料庫備份)
echo.
echo  使用方式:
echo    1. 將 release 資料夾複製給用戶
echo    2. 用戶執行「一鍵部署安裝.bat」即可
echo.
pause
