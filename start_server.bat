@echo off
chcp 65001 >nul
title 28Car 車輛管理系統

echo ============================================
echo    28Car 車輛管理系統 - 啟動中...
echo ============================================
echo.

:: 檢查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [錯誤] 找不到 Python，請先安裝 Python 3.10 以上版本
    echo 下載網址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 切換到腳本所在目錄
cd /d "%~dp0"

:: 檢查虛擬環境
if not exist "venv" (
    echo [設定] 首次執行，建立虛擬環境...
    python -m venv venv
    if errorlevel 1 (
        echo [錯誤] 建立虛擬環境失敗
        pause
        exit /b 1
    )
)

:: 啟動虛擬環境
call venv\Scripts\activate.bat

:: 安裝依賴
echo [設定] 檢查套件...
pip install -r requirements.txt -q

:: 執行資料庫遷移
echo [設定] 檢查資料庫...
python migrate_db.py

:: 啟動伺服器
echo.
echo ============================================
echo    伺服器啟動成功！
echo    請在瀏覽器開啟: http://localhost:5000
echo    按 Ctrl+C 可停止伺服器
echo ============================================
echo.

python web_demo.py

pause
