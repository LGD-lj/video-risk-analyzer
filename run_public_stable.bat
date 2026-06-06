@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   视频风险点分析系统 - 公网稳定域名模式
echo ============================================
echo.

:: 检查 cloudflared
where cloudflared >nul 2>nul
if %errorlevel% neq 0 (
    if exist "cloudflared.exe" (
        set CLOUDFLARED=cloudflared.exe
    ) else (
        echo [错误] 未找到 cloudflared
        pause
        exit /b 1
    )
) else (
    set CLOUDFLARED=cloudflared
)

:: 检查是否已配置稳定 Tunnel
%CLOUDFLARED% tunnel list 2>nul
if %errorlevel% neq 0 (
    echo.
    echo ============================================
    echo   尚未配置稳定 Cloudflare Tunnel
    echo   请先完成以下步骤：
    echo ============================================
    echo.
    echo 1. 注册 Cloudflare 账号: https://dash.cloudflare.com/
    echo 2. 登录 cloudflared:
    echo    %CLOUDFLARED% tunnel login
    echo 3. 创建 Tunnel:
    echo    %CLOUDFLARED% tunnel create video-risk-analyzer
    echo 4. 配置 DNS:
    echo    在 Cloudflare 控制台中添加 CNAME 记录指向 Tunnel
    echo 5. 创建 config.yml（参考 README_PUBLIC.md）
    echo 6. 运行 Tunnel:
    echo    %CLOUDFLARED% tunnel run video-risk-analyzer
    echo.
    echo 详细说明见 README_PUBLIC.md
    echo.
    pause
    exit /b 0
)

:: 检查 .env
if not exist ".env" (
    echo [错误] 需要 .env 文件
    pause
    exit /b 1
)

echo [1/2] 启动本地服务...
start "VideoRiskAnalyzer" /B python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

timeout /t 3 /nobreak >nul

echo [2/2] 启动 Cloudflare 稳定 Tunnel...
echo.
%CLOUDFLARED% tunnel run video-risk-analyzer

pause
