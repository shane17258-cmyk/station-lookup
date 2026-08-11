@echo off
chcp 65001 >nul
cd /d "%~dp0"
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if not "%%A"=="" if not "%%A"=="#%" set "%%A=%%B"
)
python photo_server.py 8000