@echo off
chcp 65001 >nul
title 28Car 解除安裝

echo ============================================
echo    28Car 車輛管理系統 - 解除安裝
echo ============================================
echo.
echo 這將會移除:
echo   - 桌面捷徑
echo   - 開機自動啟動設定
echo.
echo 注意: 不會刪除程式檔案和資料庫
echo.
choice /C YN /M "是否繼續"
if errorlevel 2 goto :END

echo.

:: 移除桌面捷徑
set "DESKTOP=%USERPROFILE%\Desktop"
if exist "%DESKTOP%\28Car 車輛管理.lnk" (
    del "%DESKTOP%\28Car 車輛管理.lnk"
    echo [OK] 已移除桌面捷徑: 28Car 車輛管理
)
if exist "%DESKTOP%\28Car 開啟網頁.lnk" (
    del "%DESKTOP%\28Car 開啟網頁.lnk"
    echo [OK] 已移除桌面捷徑: 28Car 開啟網頁
)

:: 移除開機自動啟動
set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if exist "%STARTUP_FOLDER%\28Car伺服器.lnk" (
    del "%STARTUP_FOLDER%\28Car伺服器.lnk"
    echo [OK] 已移除開機自動啟動
)

echo.
echo ============================================
echo  解除安裝完成
echo ============================================
echo.
echo 程式檔案和資料庫仍保留在原位置
echo 如需完全刪除，請手動刪除整個資料夾
echo.

:END
pause
