@echo off
chcp 65001 >nul
cd /d "%~dp0"

:menu
cls
echo ================================
echo   视频风险点分析系统
echo ================================
echo.
echo   1. 本地启动（仅自己电脑使用）
echo   2. 公网启动（给同事外网使用）
echo   3. 退出
echo.
echo ================================
set /p choice="请输入选项 (1/2/3): "

if "%choice%"=="1" goto local
if "%choice%"=="2" goto public
if "%choice%"=="3" goto exit
echo 无效选项，请重新输入
timeout /t 2 /nobreak >nul
goto menu

:local
echo.
echo ================================
echo   正在启动本地服务...
echo ================================
echo.
if exist "run_local.bat" (
    call run_local.bat
) else (
    echo [错误] 未找到 run_local.bat
    pause
)
goto menu

:public
echo.
echo ================================
echo   检查公网配置...
echo ================================

:: 检查 .env 文件
if not exist ".env" (
    echo [错误] 未找到 .env 文件
    echo 请从 .env.example 复制并配置
    pause
    goto menu
)

:: 使用 Python 校验配置（不显示口令内容）
python -c "
from app.config import config
import sys
ok = True
if not config.PUBLIC_ACCESS_ENABLED:
    print('[错误] PUBLIC_ACCESS_ENABLED=false')
    ok = False
if not config.UPLOAD_TOKEN:
    print('[错误] UPLOAD_TOKEN 未配置')
    ok = False
if not ok:
    print()
    print('请在 .env 中设置:')
    print('  PUBLIC_ACCESS_ENABLED=true')
    print('  UPLOAD_TOKEN=你的口令')
    sys.exit(1)
print('PUBLIC_ACCESS_ENABLED: true')
print('UPLOAD_TOKEN: 已配置')
print('VISION_KEY: ' + ('已配置' if config.has_vision_key() else '未配置'))
print('DEEPSEEK_KEY: ' + ('已配置' if config.has_deepseek_key() else '未配置'))
"
if %errorlevel% neq 0 (
    echo.
    pause
    goto menu
)

echo.
echo ================================
echo   正在启动公网服务...
echo ================================
echo.

:: 优先使用 start_public.bat，其次 run_public_quick.bat
if exist "start_public.bat" (
    echo 使用 start_public.bat 启动...
    call start_public.bat
) else if exist "run_public_quick.bat" (
    echo 使用 run_public_quick.bat 启动...
    call run_public_quick.bat
) else (
    echo [错误] 未找到公网启动脚本
    pause
)

goto menu

:exit
echo 再见！
timeout /t 2 /nobreak >nul
exit /b 0
