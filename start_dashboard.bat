@echo off
chcp 65001 >nul
cd /d "%~dp0"


:: ── 激活虚拟环境（如果存在） ──
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) else (
    echo System Python
)

echo.
echo http://127.0.0.1:8763

python -m runtime --web --port 8763 --timeout 0

if errorlevel 1 (
    echo.
    echo Error: %errorlevel%
    pause
)
