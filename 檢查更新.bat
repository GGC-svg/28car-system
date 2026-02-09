@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ==================================================
echo   28car 車源系統 - 檢查更新
echo ==================================================
echo.

cd /d "%~dp0"

:: 檢查 Git 是否安裝
where git >nul 2>&1
if errorlevel 1 (
    echo [錯誤] 未安裝 Git，請先安裝 Git for Windows
    echo 下載網址: https://git-scm.com/download/win
    pause
    exit /b 1
)

:: 檢查是否有遠端設定
git remote -v | findstr "origin" >nul 2>&1
if errorlevel 1 (
    echo [錯誤] 尚未設定遠端倉庫
    echo 請聯繫管理員取得倉庫連結
    pause
    exit /b 1
)

echo 正在檢查更新...
echo.

:: 取得遠端更新資訊
git fetch origin 2>nul

:: 比較本地和遠端版本
for /f %%i in ('git rev-parse HEAD 2^>nul') do set LOCAL=%%i
for /f %%i in ('git rev-parse origin/main 2^>nul') do set REMOTE=%%i

if "%LOCAL%"=="%REMOTE%" (
    echo [OK] 您的程式已是最新版本！
    echo.
    echo 本地版本: %LOCAL:~0,8%
) else (
    echo [發現新版本]
    echo   本地版本: %LOCAL:~0,8%
    echo   遠端版本: %REMOTE:~0,8%
    echo.

    :: 顯示更新內容
    echo 更新內容:
    git log --oneline HEAD..origin/main 2>nul
    echo.

    set /p CONFIRM="是否要更新？(Y/N): "
    if /i "!CONFIRM!"=="Y" (
        echo.
        echo 正在更新...

        :: 備份使用者可能修改的檔案
        if exist "config.local.py" copy "config.local.py" "config.local.py.bak" >nul

        :: 拉取更新
        git pull origin main --ff-only

        if errorlevel 1 (
            echo.
            echo [警告] 自動更新失敗，可能有本地修改衝突
            echo 請聯繫管理員協助處理
        ) else (
            echo.
            echo [OK] 更新完成！
            echo.
            echo ----------------------------------------
            echo  重要提醒：
            echo  如果有資料庫結構更新，請執行：
            echo    python migrate_db.py
            echo ----------------------------------------
        )
    ) else (
        echo 已取消更新。
    )
)

echo.
pause
