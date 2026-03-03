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
echo   - 排程任務
echo   - 防火牆規則
echo.
echo 注意: 不會刪除程式檔案和資料庫
echo.
choice /C YN /M "是否繼續"
if errorlevel 2 goto :END

echo.

:: 移除桌面捷徑
set "DESKTOP=%USERPROFILE%\Desktop"
if exist "%DESKTOP%\28Car Server.lnk" (
    del "%DESKTOP%\28Car Server.lnk"
    echo [OK] 已移除桌面捷徑: 28Car Server
)
if exist "%DESKTOP%\28Car Web.lnk" (
    del "%DESKTOP%\28Car Web.lnk"
    echo [OK] 已移除桌面捷徑: 28Car Web
)

:: 移除開機自動啟動
set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if exist "%STARTUP_FOLDER%\28Car伺服器.lnk" (
    del "%STARTUP_FOLDER%\28Car伺服器.lnk"
    echo [OK] 已移除開機自動啟動
)
if exist "%STARTUP_FOLDER%\28Car Server.lnk" (
    del "%STARTUP_FOLDER%\28Car Server.lnk"
    echo [OK] 已移除開機自動啟動
)

:: 移除排程任務
echo.
echo 移除排程任務...
schtasks /delete /tn "28car_backup" /f >nul 2>&1
if %errorlevel%==0 echo [OK] 已移除 28car_backup
schtasks /delete /tn "28car_daily" /f >nul 2>&1
if %errorlevel%==0 echo [OK] 已移除 28car_daily
schtasks /delete /tn "28car_weekly" /f >nul 2>&1
if %errorlevel%==0 echo [OK] 已移除 28car_weekly
schtasks /delete /tn "28car_sms" /f >nul 2>&1
if %errorlevel%==0 echo [OK] 已移除 28car_sms

:: 移除防火牆規則
echo.
echo 移除防火牆規則...
netsh advfirewall firewall delete rule name="28Car Server" >nul 2>&1
if %errorlevel%==0 echo [OK] 已移除防火牆規則

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
