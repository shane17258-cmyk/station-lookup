@echo off
chcp 65001 >nul
cd /d "C:\Users\shane\OneDrive - Chunghwa Telecom Co., Ltd\苗栗市站台"
echo ============================================
echo   Station Photo Server (Google Drive)
echo ============================================
echo.
echo   Photos are stored in your Google Drive cloud folder.
echo   On first run, a browser will open for authorization.
echo.
echo   Opening http://localhost:8000 ...
echo   Press Ctrl+C to stop the server.
echo.
echo [Starting...]
start "" http://localhost:8000
python photo_server.py 8000
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to start server. Please check Python installation.
    pause
    exit /b 1
)