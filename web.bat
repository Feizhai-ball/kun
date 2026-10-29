
@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Flask SQLite 查询系统

if not exist "python\python.exe" (
    echo 错误：找不到便携 Python。
    pause
    exit /b 1
)

if not exist "app.py" (
    echo 错误：找不到 app.py。
    pause
    exit /b 1
)

if not exist "my_data.db" (
    echo 错误：找不到 my_data.db。
    pause
    exit /b 1
)

if not exist "templates\index.html" (
    echo 错误：找不到 templates\index.html。
    pause
    exit /b 1
)

start "" "http://127.0.0.1:5000"
python\python.exe app.py

echo.
echo 查询系统已停止。
pause
