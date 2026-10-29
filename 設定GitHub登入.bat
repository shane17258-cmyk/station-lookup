@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  設定 GitHub 登入（每台電腦只需做一次）
echo ============================================
echo.

set "GIT="
where git >nul 2>nul && set "GIT=git"
if not defined GIT if exist "C:\Program Files\Git\cmd\git.exe" set "GIT=C:\Program Files\Git\cmd\git.exe"
if not defined GIT if exist "C:\Program Files (x86)\Git\cmd\git.exe" set "GIT=C:\Program Files (x86)\Git\cmd\git.exe"
if not defined GIT if exist "%LOCALAPPDATA%\Programs\Git\cmd\git.exe" set "GIT=%LOCALAPPDATA%\Programs\Git\cmd\git.exe"

if not defined GIT (
    echo [錯誤] 這台電腦找不到 Git。
    echo 請先安裝 Git for Windows：https://git-scm.com/download/win
    echo 安裝完成後再執行本檔案一次。
    pause
    exit /b 1
)
echo 使用 Git：!GIT!
echo.

echo [1/2] 檢查 GitHub 連線...
"!GIT!" ls-remote origin >nul 2>&1
if errorlevel 1 (
    echo.
    echo 需要登入 GitHub，請在跳出的視窗點「Sign in with browser」，
    echo 用瀏覽器登入你的 GitHub 帳號並授權即可。
    echo.
    "!GIT!" ls-remote origin
    if errorlevel 1 (
        echo.
        echo [錯誤] 登入沒有完成，請再執行本檔案一次。
        pause
        exit /b 1
    )
)
echo 登入 OK。
echo.

echo [2/2] 上傳台電查詢結果（outage.json）...
python push_outage.py
if errorlevel 1 (
    echo.
    echo [錯誤] 上傳失敗，請把上面的訊息截圖回報。
    pause
    exit /b 1
)

echo.
echo ============================================
echo  完成！之後執行「台電查詢.bat」就會自動上傳
echo ============================================
pause
