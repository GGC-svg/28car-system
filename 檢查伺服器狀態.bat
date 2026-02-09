@echo off
chcp 65001 >nul
title 檢查伺服器狀態

echo ============================================
echo    28Car 伺服器狀態檢查
echo ============================================
echo.

:: 檢查 port 5000 是否有程式在監聽
netstat -an | findstr ":5000.*LISTENING" >nul 2>&1

if %errorlevel%==0 (
    echo [OK] 伺服器運作中
    echo.
    echo     網址: http://localhost:5000
    echo.

    :: 嘗試用 curl 測試（如果有的話）
    curl -s -o nul -w "" http://localhost:5000 >nul 2>&1
    if %errorlevel%==0 (
        echo [OK] 網頁可正常存取
    ) else (
        echo [!] 網頁可能還在啟動中，請稍後再試
    )
) else (
    echo [X] 伺服器未運行
    echo.
    choice /C YN /M "是否要立即啟動伺服器"
    if errorlevel 2 goto :END
    if errorlevel 1 (
        echo.
        echo 正在啟動伺服器...
        cd /d "%~dp0"

        if exist "28car_server.exe" (
            start "" "28car_server.exe"
        ) else (
            start "" "啟動伺服器.bat"
        )

        echo.
        echo [OK] 伺服器已啟動，請稍候幾秒後開啟 http://localhost:5000
    )
)

:END
echo.
pause
