@echo off
chcp 65001 >nul
cd /d "%~dp0"
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if not "%%A"=="" if not "%%A"=="#%" set "%%A=%%B"
)
echo ============================================
echo   站台照片伺服器 (Google Drive)
echo ============================================
echo.
echo  照片將存入 Google Drive 雲端資料夾。
echo  首次使用需在瀏覽器完成授權（只需一次）。
echo.
echo  將自動開啟瀏覽器 http://localhost:8000
echo  按 Ctrl+C 可停止伺服器。
echo.
echo [啟動中...]
start "" http://localhost:8000
python photo_server.py 8000
if errorlevel 1 (
    echo.
    echo [錯誤] 伺服器啟動失敗，請確認已安裝 Python
    pause
    exit /b 1
)