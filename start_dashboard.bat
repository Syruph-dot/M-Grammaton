@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ════════════════════════════════════════════
echo  M-Grammaton Runtime Dashboard 启动
echo ════════════════════════════════════════════
echo.

:: ── 激活虚拟环境（如果存在） ──
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
    echo [OK] 虚拟环境已激活
) else (
    echo [!] 未找到 .venv，使用系统 Python
)

echo.
echo 启动 Runtime + Web Dashboard...
echo 访问地址: http://127.0.0.1:8763
echo 按 Ctrl+C 停止
echo.

python -m runtime --web --port 8763 --timeout 0

if errorlevel 1 (
    echo.
    echo [错误] Runtime 异常退出，错误码: %errorlevel%
    pause
)
