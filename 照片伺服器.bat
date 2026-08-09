@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   站台照片伺服器
echo ============================================
echo.
echo  照片將存放在本資料夾底下的「站台照片\」，
echo  因所在目錄為 OneDrive 同步資料夾，上傳後會自動同步上雲端。
echo.
echo  將自動開啟瀏覽器 http://localhost:8000
echo  按 Ctrl+C 可停止伺服器。
echo.
echo [啟動中...]
start "" http://localhost:8000
python photo_server.py
if errorlevel 1 (
    echo.
    echo [錯誤] 伺服器啟動失敗，請確認已安裝 Python
    pause
    exit /b 1
)