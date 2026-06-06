@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ============================================
echo   视频风险点分析系统 - 一键公网启动
echo ============================================
echo.

:: ---------- 1. 检查 cloudflared ----------
set CLOUDFLARED=
where cloudflared >nul 2>nul
if %errorlevel% equ 0 (
    set CLOUDFLARED=cloudflared
) else (
    if exist "cloudflared.exe" (
        set CLOUDFLARED=cloudflared.exe
    ) else (
        echo [错误] 未找到 cloudflared
        echo 请运行: winget install --id Cloudflare.cloudflared -e
        echo 或手动下载放到本项目目录
        pause
        exit /b 1
    )
)

:: ---------- 2. 检查 Python ----------
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python
    pause
    exit /b 1
)

:: ---------- 3. 检查 .env ----------
if not exist ".env" (
    echo [错误] 未找到 .env 文件
    echo 请从 .env.example 复制并配置
    pause
    exit /b 1
)

:: 使用 Python 检查 .env 配置（不显示口令内容）
echo [1/4] 检查配置...
python -c "from app.config import config; print('PUBLIC_ACCESS_ENABLED: ' + str(config.PUBLIC_ACCESS_ENABLED)); print('UPLOAD_TOKEN: ' + ('已配置' if config.UPLOAD_TOKEN else '未配置！')); print('VISION_KEY: ' + ('已配置' if config.has_vision_key() else '未配置')); print('DEEPSEEK_KEY: ' + ('已配置' if config.has_deepseek_key() else '未配置'))"

:: 用 python 做严格校验
python -c "
from app.config import config
import sys
if not config.PUBLIC_ACCESS_ENABLED:
    print('')
    print('[错误] PUBLIC_ACCESS_ENABLED=false，请先编辑 .env 设置为 true')
    sys.exit(1)
if not config.UPLOAD_TOKEN:
    print('')
    print('[错误] UPLOAD_TOKEN 未配置，请先编辑 .env 设置口令')
    sys.exit(1)
"
if %errorlevel% neq 0 (
    echo.
    echo 请在 .env 中设置:
    echo   PUBLIC_ACCESS_ENABLED=true
    echo   UPLOAD_TOKEN=你的口令
    echo.
    notepad .env
    pause
    exit /b 1
)

:: ---------- 4. 安装依赖 ----------
echo.
echo [2/4] 检查依赖...
pip install -r requirements.txt -q

:: ---------- 5. 创建数据目录 ----------
if not exist "data\jobs" mkdir data\jobs

:: ---------- 6. 启动 FastAPI ----------
echo.
echo [3/4] 启动 FastAPI 服务 (127.0.0.1:8000)...
start "VideoRiskAnalyzer" /B python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

:: 等待服务就绪
echo 等待服务启动...
:wait_loop
timeout /t 2 /nobreak >nul
curl -s http://127.0.0.1:8000/api/health >nul 2>nul
if %errorlevel% neq 0 goto wait_loop

:: ---------- 7. 获取公网配置信息 ----------
echo.
echo [4/4] 启动 Cloudflare Quick Tunnel...
echo.

echo ============================================
echo   服务已启动
echo ============================================
echo.
echo   本地地址: http://127.0.0.1:8000
echo   Token 校验: 已启用
echo   并发限制: 1 个任务
echo.
echo ============================================
echo   公网访问链接（临时，每次可能变化）：
echo ============================================
echo.

%CLOUDFLARED% tunnel --url http://127.0.0.1:8000

echo.
echo ============================================
echo   Tunnel 已停止
echo ============================================
pause
