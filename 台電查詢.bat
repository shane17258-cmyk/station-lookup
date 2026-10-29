@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   台電電號查詢（本機執行，台灣網路直連）
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [錯誤] 找不到 Python。
    echo 請先安裝 Python，然後執行：
    echo   pip install requests beautifulsoup4 ddddocr pillow numpy
    pause
    exit /b 1
)

REM 本機查詢不使用 Cloudflare 代理（台電會擋國外機房 IP，本機在台灣可直連）
set TAIPOWER_PROXY=

python scripts\taipower_check.py
if errorlevel 1 (
    echo [錯誤] 查詢程式執行失敗
    pause
    exit /b 1
)

echo.
echo [上傳結果至 GitHub...]
python push_outage.py
if errorlevel 1 (
    echo.
    echo [錯誤] 上傳失敗。
    echo 若訊息是「找不到 GitHub 登入資訊」，請先執行同資料夾的
    echo 「設定GitHub登入.bat」（每台電腦只需做一次），再執行本檔案。
    pause
    exit /b 1
)

echo.
echo ============================================
echo   完成！網頁約 5 分鐘內自動更新
echo ============================================
pause
