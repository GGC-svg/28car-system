@echo off
chcp 65001 >nul
title 每日簡訊發送

cd /d "%~dp0"

echo ============================================
echo    每日簡訊自動發送
echo    時間: %date% %time%
echo ============================================
echo.

:: 啟動虛擬環境（如果存在）
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

:: 執行簡訊發送
python sms_sender.py --daily

echo.
echo ============================================
echo    發送完成
echo ============================================

:: 如果是手動執行，暫停顯示結果
if "%1"=="" pause
