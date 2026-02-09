@echo off
chcp 65001 >nul
title 28Car 車輛管理系統

cd /d "%~dp0"

echo ============================================
echo    28Car 車輛管理系統
echo ============================================
echo.
echo    請在瀏覽器開啟: http://localhost:5000
echo    按 Ctrl+C 或關閉視窗可停止伺服器
echo.
echo ============================================

:: 優先使用 exe（如果存在）
if exist "28car_server.exe" (
    28car_server.exe
) else if exist "dist\28car_server.exe" (
    dist\28car_server.exe
) else (
    :: 沒有 exe，用 Python 啟動
    python web_demo.py
)

pause
