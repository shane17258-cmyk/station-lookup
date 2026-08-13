@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   苗栗市站台資料更新
echo ============================================
echo.

REM 自動偵測最新日期的資料檔
set MISSING=0
for %%P in ("*LTE_CoBTS_CHT.xlsx" "*LTE_CoCell_CHT.xlsx" "*nrBts_DB_CHT.xlsx" "*nrCell_DB_CHT.xlsx" "*LTE_RMOD_EAC_CHT.xlsx" "*LTE_SMOD_EAC_CHT.xlsx" "*NR_RMOD_EAC_CHT.xlsx" "*NR_SMOD_EAC_CHT.xlsx") do (
    set "LATEST="
    for /f "delims=" %%F in ('dir /b /o:-d "%%~P" 2^>nul') do (
        if not defined LATEST set "LATEST=%%F"
    )
    if not defined LATEST (
        echo [錯誤] 缺少檔案: %%~P
        set MISSING=1
    ) else (
        echo 使用最新檔案: !LATEST!
    )
)
if "%MISSING%"=="1" (
    echo.
    echo 請將八個 xlsx 檔案放入本資料夾後再執行本腳本。
    pause
    exit /b 1
)

echo [1/4] 重新產生資料檔...
python update_data.py
if errorlevel 1 (
    echo [錯誤] 產生資料失敗
    pause
    exit /b 1
)

echo.
echo [2/4] 加入 Git...
git add data.js data5g.js index.html update_data.py .gitignore
if errorlevel 1 (
    echo [錯誤] git add 失敗
    pause
    exit /b 1
)

echo.
echo [3/4] 提交更新...
git commit -m "更新站台資料"
if errorlevel 1 (
    echo [錯誤] git commit 失敗
    pause
    exit /b 1
)

echo.
echo [4/4] 推送至 GitHub...
git push origin master
if errorlevel 1 (
    echo [錯誤] git push 失敗
    pause
    exit /b 1
)

echo.
echo ============================================
echo   完成！網站已更新
echo ============================================
pause