@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   视频风险点分析系统 - 本地模式
echo   访问地址: http://127.0.0.1:8000
echo ============================================
echo.

:: 检查 Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

:: 检查 FFmpeg
where ffprobe >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未找到 FFmpeg (ffprobe)
    pause
    exit /b 1
)

:: 检查 .env
if not exist ".env" (
    echo [提示] 未找到 .env，从 .env.example 复制...
    copy .env.example .env >nul
    echo [重要] 请编辑 .env 填入 API Key
    notepad .env
    pause
)

:: 安装依赖
echo [1/2] 检查依赖...
pip install -r requirements.txt -q

:: 创建数据目录
if not exist "data\jobs" mkdir data\jobs

:: 启动
echo [2/2] 启动本地服务...
echo.
echo ============================================
echo   本地访问: http://127.0.0.1:8000
echo   按 Ctrl+C 停止
echo ============================================
echo.

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

pause
