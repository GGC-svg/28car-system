@echo off
chcp 65001 >nul
title 打包 28Car 系統為 EXE

echo ============================================
echo    打包 28Car 車輛管理系統
echo ============================================
echo.

cd /d "%~dp0"

:: 檢查 PyInstaller
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [設定] 安裝 PyInstaller...
    pip install pyinstaller
)

:: 打包
echo [打包] 開始打包 web_demo.py...
pyinstaller --onefile --name 28car_server --add-data "index.html;." --hidden-import=sqlite3 web_demo.py

if errorlevel 1 (
    echo [錯誤] 打包失敗
    pause
    exit /b 1
)

echo.
echo ============================================
echo    打包完成！
echo    執行檔位置: dist\28car_server.exe
echo.
echo    部署時需要複製:
echo    1. dist\28car_server.exe
echo    2. cars_28car.db
echo    3. images\ 資料夾
echo    4. index.html
echo ============================================

pause
