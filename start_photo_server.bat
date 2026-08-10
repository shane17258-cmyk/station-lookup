@echo off
chcp 65001 >nul
cd /d "%~dp0"
python photo_server.py 8000