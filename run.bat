@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   视频风险点分析系统 V1
echo ============================================
echo.

:: 检查 Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    echo 下载地址：https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 检查 FFmpeg
where ffprobe >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未找到 FFmpeg (ffprobe)，请先安装 FFmpeg
    echo 下载地址：https://ffmpeg.org/download.html
    echo 或使用 winget install ffmpeg
    pause
    exit /b 1
)

:: 检查 .env 文件
if not exist ".env" (
    echo [提示] 未找到 .env 文件，正在从 .env.example 复制...
    copy .env.example .env >nul
    echo [重要] 请编辑 .env 文件，填入你的 API Key：
    echo   - VISION_API_KEY  （视觉模型 API Key）
    echo   - DEEPSEEK_API_KEY（DeepSeek API Key）
    echo.
    echo 编辑完成后，重新运行 run.bat
    pause
    exit /b 0
)

:: 检查并安装依赖
echo [1/2] 检查 Python 依赖...
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo [错误] 依赖安装失败，请检查网络连接后重试
    pause
    exit /b 1
)

:: 创建数据目录
if not exist "data\jobs" mkdir data\jobs

:: 启动服务
echo [2/2] 启动服务...
echo.
echo ============================================
echo   服务启动!
echo   打开浏览器访问: http://127.0.0.1:8000
echo   按 Ctrl+C 停止服务
echo ============================================
echo.

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

pause
