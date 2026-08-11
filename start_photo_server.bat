@echo off
chcp 65001 >nul
cd /d "C:\Users\shane\OneDrive - Chunghwa Telecom Co., Ltd\苗栗市站台"
python photo_server.py 8000
if errorlevel 1 (
    echo [ERROR] Failed to start photo server. Check Python installation.
    pause
    exit /b 1
)