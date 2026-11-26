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
for %%P in ("*LTE_CoBTS_CHT.xlsx" "*LTE_CoCell_CHT.xlsx" "*nrBts_DB_CHT.xlsx" "*nrCell_DB_CHT.xlsx" "*LTE_RMOD_EAC_CHT.xlsx" "*LTE_SMOD_EAC_CHT.xlsx" "*NR_RMOD_EAC_CHT.xlsx" "*NR_SMOD_EAC_CHT.xlsx" "*LTE_RMOD_SFP.xlsx" "*NR_RMOD_SFP.xlsx") do (
    set "LATEST="
    for /f "delims=" %%F in ('dir /b /o:-n "%%~P" 2^>nul') do (
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
    echo 請將十個 xlsx 檔案放入本資料夾後再執行本腳本。
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
git add data.js data5g.js topo.js index.html update_data.py topology.py sw.js .gitignore
if errorlevel 1 (
    echo [錯誤] git add 失敗
    pause
    exit /b 1
)

echo.
echo [3/4] 提交更新...
git commit -m "更新站台資料"
if errorlevel 1 (
    git diff --cached --quiet
    if not errorlevel 1 (
        echo [略過] 沒有新的資料變更，繼續推送...
    ) else (
        echo [錯誤] git commit 失敗
        pause
        exit /b 1
    )
)

echo.
echo [4/4] 推送至 GitHub...
REM 清掉本機殘留的 outage.json 變更（台電查詢.bat 會另外用 API 上傳，不需要進這個 commit）
REM 否則 git pull --rebase 會因「未提交的變更」直接失敗
if exist outage.json (
    copy /y outage.json "%TEMP%\outage_backup.json" >nul 2>&1
    git checkout -- outage.json 2>nul
)
REM 其他未提交的變更先暫存起來，pull 完再還原
set "STASHED="
git stash push -u -m "更新資料前自動暫存" >nul 2>&1
git stash list | findstr /c:"更新資料前自動暫存" >nul && set "STASHED=1"

git pull --rebase origin master
if errorlevel 1 (
    echo [錯誤] git pull --rebase 失敗
    pause
    exit /b 1
)
git push origin master
if errorlevel 1 (
    echo 第一次推送失敗，重試中...
    git pull --rebase origin master
    if errorlevel 1 (
        echo [錯誤] git pull --rebase 失敗
        pause
        exit /b 1
    )
    git push origin master
    if errorlevel 1 (
        echo [錯誤] git push 失敗
        pause
        exit /b 1
    )
)

if defined STASHED (
    git stash pop >nul 2>&1
    if errorlevel 1 (
        echo [提醒] 剛才自動暫存的變更無法自動還原，請執行 git stash list 查看、git stash pop 手動還原。
    )
)

echo.
echo ============================================
echo   完成！網站已更新
echo ============================================
pause