@echo off
chcp 65001 >nul
title 28Car 車輛管理系統

cd /d "%~dp0"

echo ============================================
echo    28Car 車輛管理系統
echo ============================================
echo.

:: 先檢查並關閉已存在的伺服器進程
echo 檢查現有伺服器進程...
tasklist /FI "IMAGENAME eq 28car_server.exe" 2>NUL | find /I "28car_server.exe" >NUL
if %ERRORLEVEL%==0 (
    echo 發現舊的伺服器進程，正在關閉...
    taskkill /F /IM 28car_server.exe >nul 2>&1
    timeout /t 2 /nobreak >nul
    echo 舊進程已關閉
)

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
