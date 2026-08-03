@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   苗栗市站台資料更新
echo ============================================
echo.

REM 檢查必要檔案是否存在
set MISSING=0
for %%F in (20260730_LTE_CoBTS_CHT.xlsx 20260730_LTE_CoCell_CHT.xlsx 20260730_nrBts_DB_CHT.xlsx 20260730_nrCell_DB_CHT.xlsx) do (
    if not exist "%%F" (
        echo [錯誤] 缺少檔案: %%F
        set MISSING=1
    )
)
if "%MISSING%"=="1" (
    echo.
    echo 請將四個 xlsx 檔案放入本資料夾後再執行本腳本。
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