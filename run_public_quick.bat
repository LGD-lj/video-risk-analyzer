@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   视频风险点分析系统 - 公网临时访问模式
echo ============================================
echo.

:: 检查 cloudflared
where cloudflared >nul 2>nul
if %errorlevel% neq 0 (
    if exist "cloudflared.exe" (
        set CLOUDFLARED=cloudflared.exe
    ) else (
        echo [错误] 未找到 cloudflared
        echo 请先安装: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
        echo 或把 cloudflared.exe 放到本项目目录下
        pause
        exit /b 1
    )
) else (
    set CLOUDFLARED=cloudflared
)

:: 检查 .env
if not exist ".env" (
    echo [错误] 公网模式需要 .env 配置
    echo 请从 .env.example 复制并设置:
    echo   PUBLIC_ACCESS_ENABLED=true
    echo   UPLOAD_TOKEN=你的口令
    pause
    exit /b 1
)

:: 检查 Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python
    pause
    exit /b 1
)

:: 安装依赖
echo [1/3] 检查依赖...
pip install -r requirements.txt -q

:: 创建目录
if not exist "data\jobs" mkdir data\jobs

:: 启动 FastAPI（后台）
echo [2/3] 启动本地服务...
start "VideoRiskAnalyzer" /B python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

:: 等待服务就绪
echo 等待服务启动...
timeout /t 3 /nobreak >nul

:: 启动 Cloudflare Tunnel
echo [3/3] 启动 Cloudflare Quick Tunnel...
echo.
echo ============================================
echo   公网访问链接（临时，每次可能变化）：
echo ============================================
echo.

%CLOUDFLARED% tunnel --url http://127.0.0.1:8000

echo.
echo Tunnel 已停止。
pause
