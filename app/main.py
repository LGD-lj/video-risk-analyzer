"""FastAPI 入口 —— Web 服务和 API 路由 v1.1"""

import os
import uuid
import json
import shutil
import threading
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .config import config
from .models import JobInfo, JobStatus, TaskProgress
from .video_utils import get_video_info, format_duration_display, estimate_processing_time, create_muted_video
from .risk_analyzer import run_analysis
from .cleanup import cleanup_old_jobs

# ---------- 初始化 ----------
app = FastAPI(
    title="视频风险点分析系统",
    description="上传行车记录视频，AI 自动识别风险点，生成 Word 报告",
    version="1.0.0",
)

# CORS（允许本地前端调用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 确保数据目录存在
os.makedirs(config.DATA_DIR, exist_ok=True)

# 任务状态存储（内存，V1 简单实现）
# 生产环境可替换为 Redis 或数据库
_jobs_store: dict[str, dict] = {}

# 任务状态文件目录
JOBS_META_DIR = os.path.join(config.DATA_DIR, "_meta")
os.makedirs(JOBS_META_DIR, exist_ok=True)

# 并发控制锁
_job_lock = threading.Lock()
_active_job_count = 0


def _require_token(token: str = "") -> None:
    """校验访问口令（公网模式下强制）"""
    if not config.PUBLIC_ACCESS_ENABLED:
        return  # 本地模式不需要 token
    if not config.UPLOAD_TOKEN:
        raise HTTPException(status_code=503, detail="服务未配置 UPLOAD_TOKEN，请联系管理员")
    if token != config.UPLOAD_TOKEN:
        raise HTTPException(status_code=403, detail="访问口令错误，请输入正确的 UPLOAD_TOKEN")


def _check_concurrent_limit() -> None:
    """检查并发任务上限"""
    global _active_job_count
    if _active_job_count >= config.MAX_CONCURRENT_JOBS:
        raise HTTPException(
            status_code=429,
            detail=f"当前有任务正在处理中，请等待完成后再上传（最大并发: {config.MAX_CONCURRENT_JOBS}）"
        )


def _save_job_meta(job_id: str, data: dict):
    """持久化任务元数据到 JSON 文件"""
    from pathlib import Path
    meta_path = os.path.join(JOBS_META_DIR, f"{job_id}.json")
    # 确保 datetime 等可序列化
    data_copy = {}
    for k, v in data.items():
        if isinstance(v, datetime):
            data_copy[k] = v.isoformat()
        else:
            data_copy[k] = v
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(data_copy, f, ensure_ascii=False, indent=2)


def _load_job_meta(job_id: str) -> dict | None:
    """从 JSON 文件加载任务元数据"""
    meta_path = os.path.join(JOBS_META_DIR, f"{job_id}.json")
    if not os.path.exists(meta_path):
        return None
    with open(meta_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _update_job(
    job_id: str,
    status: JobStatus | None = None,
    stage: str = "",
    progress_percent: int = 0,
    message: str = "",
    **kwargs,
):
    """更新任务状态"""
    if job_id not in _jobs_store:
        return

    job = _jobs_store[job_id]

    # 计算 ETA
    started_at = job.get("started_at")
    if started_at and progress_percent > 0 and progress_percent < 100:
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at)
        elapsed = (datetime.now() - started_at).total_seconds()
        if elapsed > 0:
            eta_seconds = elapsed / progress_percent * (100 - progress_percent)
            job["eta_seconds"] = int(eta_seconds)

    if status:
        job["status"] = status

    job["stage"] = stage
    job["progress_percent"] = progress_percent
    job["message"] = message
    job.update(kwargs)

    _save_job_meta(job_id, job)


def _run_analysis_background(job_id: str, video_path: str, job_dir: str, user_notes: str = ""):
    """后台线程执行分析"""
    global _active_job_count
    with _job_lock:
        _active_job_count += 1
    try:
        def progress_callback(stage: str, percent: int, message: str = ""):
            _update_job(
                job_id,
                status=JobStatus.PROCESSING,
                stage=stage,
                progress_percent=percent,
                message=message,
            )

        risk_points, report_path, zip_path = run_analysis(
            job_id=job_id,
            video_path=video_path,
            job_dir=job_dir,
            progress_callback=progress_callback,
            user_notes=user_notes,
        )

        # ---------- Step 11: 生成静音视频 ----------
        muted_result = {"success": False, "path": "", "size_bytes": 0, "has_audio": True, "error": ""}
        try:
            muted_path = os.path.join(job_dir, "muted_video.mp4")
            muted_result = create_muted_video(video_path, muted_path)
        except Exception as e:
            muted_result["error"] = str(e)
            print(f"[MUTED] 静音视频生成异常: {e}")

        # ---------- 成功后清理 ----------
        _cleanup_job_files(job_id, job_dir, video_path)

        _update_job(
            job_id,
            status=JobStatus.COMPLETED,
            stage="已完成",
            progress_percent=100,
            message="分析完成",
            risk_count=len(risk_points),
            report_path=report_path,
            screenshots_zip_path=zip_path,
            video_path=None,  # 原始视频已删除
            muted_video_path=muted_result.get("path", ""),
            muted_video_status="success" if muted_result.get("success") else "failed",
            muted_video_size=muted_result.get("size_bytes", 0),
            muted_video_has_audio=muted_result.get("has_audio", True),
            muted_video_error=muted_result.get("error", ""),
        )

    except Exception as e:
        import traceback
        error_detail = f"{str(e)}\n{traceback.format_exc()}"
        print(f"[ERROR] 任务 {job_id} 失败: {error_detail}")
        # 提取用户可读的错误原因（去掉技术性 traceback）
        user_msg = str(e)
        if len(user_msg) > 200:
            user_msg = user_msg[:200] + "..."
        _update_job(
            job_id,
            status=JobStatus.FAILED,
            stage="错误",
            progress_percent=0,
            message=user_msg,
            error_message=user_msg,  # 用简短版本，不要 traceback
            failed_at=datetime.now().isoformat(),
        )
    finally:
        with _job_lock:
            _active_job_count -= 1


def _cleanup_job_files(job_id: str, job_dir: str, video_path: str = None):
    """任务成功后清理临时文件：删除原始视频和抽帧图片"""
    files_removed = []

    # 删除原始上传视频
    if video_path and os.path.exists(video_path):
        try:
            os.remove(video_path)
            files_removed.append("原始视频")
        except OSError as e:
            print(f"[CLEANUP] 删除视频失败 {video_path}: {e}")

    # 删除 frames 目录
    frames_dir = os.path.join(job_dir, "frames")
    if os.path.isdir(frames_dir):
        try:
            shutil.rmtree(frames_dir, ignore_errors=True)
            files_removed.append("抽帧图片")
        except OSError as e:
            print(f"[CLEANUP] 删除 frames 失败 {frames_dir}: {e}")

    if files_removed:
        print(f"[CLEANUP] 任务 {job_id}: 已清理 {', '.join(files_removed)}")


# ==================== API 路由 ====================

@app.get("/api/health")
async def health_check():
    """健康检查"""
    missing_keys = config.get_missing_keys()
    mock_mode = config.get_mock_mode()
    return {
        "status": "ok",
        "version": "1.0.0",
        "mock_mode": mock_mode,
        "missing_keys": missing_keys,
        "public_access": config.PUBLIC_ACCESS_ENABLED,
        "active_jobs": _active_job_count,
        "max_concurrent_jobs": config.MAX_CONCURRENT_JOBS,
        "warning": "Mock 模式已启用，AI 分析结果仅为模拟数据。请配置 API Key 后重启服务。" if mock_mode else None,
    }


@app.post("/api/upload", response_model=JobInfo)
async def upload_video(
    file: UploadFile = File(...),
    user_notes: str = Form(""),
    token: str = Form(""),
    uploader_name: str = Form(""),
):
    """上传视频文件，创建分析任务"""
    # Token 校验（公网模式）
    _require_token(token)

    # 并发限制
    _check_concurrent_limit()

    mock_mode = config.get_mock_mode()
    if mock_mode:
        print(f"[INFO] Mock mode active, missing keys: {config.get_missing_keys()}")

    # 校验文件格式
    filename = file.filename or "unknown.mp4"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {ext}，请上传 mp4/mov/avi/mkv/webm 视频",
        )

    # 校验文件大小
    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > config.MAX_UPLOAD_SIZE_MB:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大 ({size_mb:.1f}MB)，最大支持 {config.MAX_UPLOAD_SIZE_MB}MB",
        )

    # 创建任务目录
    job_id = uuid.uuid4().hex[:12]
    job_dir = os.path.join(config.DATA_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    # 保存视频文件
    safe_filename = f"video{ext}"
    video_path = os.path.join(job_dir, safe_filename)
    with open(video_path, "wb") as f:
        f.write(content)

    # 获取视频信息
    try:
        video_info = get_video_info(video_path)
    except Exception as e:
        # 清理
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"无法读取视频文件: {e}")

    # 预估处理时间
    estimated_time = estimate_processing_time(
        duration_seconds=video_info.duration_seconds,
        frame_interval=config.FRAME_INTERVAL_SECONDS,
        is_mock=mock_mode,
    )
    duration_display = format_duration_display(video_info.duration_seconds)

    # 创建任务记录
    started_at = datetime.now()
    job_data = {
        "job_id": job_id,
        "status": JobStatus.PROCESSING,  # 直接进入处理状态
        "filename": filename,
        "original_filename": filename,
        "duration_seconds": video_info.duration_seconds,
        "duration_display": duration_display,
        "resolution": video_info.resolution,
        "fps": video_info.fps,
        "total_frames": None,
        "risk_count": None,
        "report_url": None,
        "screenshots_zip_url": None,
        "error_message": None,
        "stage": "已上传",
        "progress_percent": 0,
        "message": estimated_time,
        "created_at": started_at,
        "started_at": started_at,
        "estimated_time": estimated_time,
        "user_notes": user_notes.strip() if user_notes else "",
        "uploader_name": uploader_name.strip() if uploader_name else "",
        "public_access": config.PUBLIC_ACCESS_ENABLED,
        "upload_time": started_at.isoformat(),
        "analysis_mode": config.ANALYSIS_MODE,
        "mock_mode": mock_mode,
        "video_path": video_path,
    }
    _jobs_store[job_id] = job_data
    _save_job_meta(job_id, job_data)

    # 后台启动分析
    thread = threading.Thread(
        target=_run_analysis_background,
        args=(job_id, video_path, job_dir, user_notes.strip() if user_notes else ""),
        daemon=True,
    )
    thread.start()

    return JobInfo(
        job_id=job_id,
        status=JobStatus.PROCESSING,
        filename=filename,
        duration_seconds=video_info.duration_seconds,
        duration_display=duration_display,
        resolution=video_info.resolution,
        fps=video_info.fps,
        created_at=job_data["created_at"].isoformat(),
        estimated_time=estimated_time,
        user_notes=user_notes.strip() if user_notes else "",
    )


@app.get("/api/status/{job_id}")
async def get_job_status(job_id: str, token: str = Query("")):
    """查询任务状态"""
    _require_token(token)
    job = _jobs_store.get(job_id)
    if not job:
        # 尝试从磁盘加载
        meta = _load_job_meta(job_id)
        if not meta:
            raise HTTPException(status_code=404, detail="任务不存在")
        job = meta

    # 构建下载 URL
    report_url = None
    zip_url = None
    if job.get("status") == JobStatus.COMPLETED or (
        isinstance(job.get("status"), str) and job.get("status") == "completed"
    ):
        if job.get("report_path"):
            report_url = f"/api/download/{job_id}/report"
        if job.get("screenshots_zip_path"):
            zip_url = f"/api/download/{job_id}/screenshots"

    return {
        "job_id": job.get("job_id", job_id),
        "status": job.get("status", "unknown"),
        "filename": job.get("filename", ""),
        "duration_seconds": job.get("duration_seconds"),
        "duration_display": job.get("duration_display", ""),
        "resolution": job.get("resolution"),
        "fps": job.get("fps"),
        "risk_count": job.get("risk_count"),
        "report_url": report_url,
        "screenshots_zip_url": zip_url,
        "stage": job.get("stage", ""),
        "progress_percent": job.get("progress_percent", 0),
        "message": job.get("message", ""),
        "error_message": job.get("error_message"),
        "created_at": str(job.get("created_at", "")),
        "estimated_time": job.get("estimated_time", ""),
        "eta_seconds": job.get("eta_seconds"),
        "user_notes": job.get("user_notes", ""),
        "uploader_name": job.get("uploader_name", ""),
        "public_access": job.get("public_access", False),
        "mock_mode": job.get("mock_mode", config.get_mock_mode()),
        "active_jobs": _active_job_count,
        "muted_video_status": job.get("muted_video_status", ""),
        "muted_video_url": f"/api/download/{job_id}/muted-video" if job.get("muted_video_status") == "success" else None,
    }


@app.get("/api/download/{job_id}/report")
async def download_report(job_id: str, token: str = Query("")):
    """下载 Word 报告"""
    _require_token(token)
    job = _jobs_store.get(job_id)
    if not job:
        job = _load_job_meta(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    report_path = job.get("report_path")
    if not report_path or not os.path.exists(report_path):
        raise HTTPException(status_code=404, detail="报告文件不存在")

    original_filename = job.get("original_filename", "video")
    base_name = os.path.splitext(original_filename)[0]
    download_name = f"{base_name}_风险分析报告.docx"

    return FileResponse(
        path=report_path,
        filename=download_name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.get("/api/download/{job_id}/screenshots")
async def download_screenshots(job_id: str, token: str = Query("")):
    """下载截图 ZIP"""
    _require_token(token)
    job = _jobs_store.get(job_id)
    if not job:
        job = _load_job_meta(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    zip_path = job.get("screenshots_zip_path")
    if not zip_path or not os.path.exists(zip_path):
        raise HTTPException(status_code=404, detail="截图文件不存在")

    original_filename = job.get("original_filename", "video")
    base_name = os.path.splitext(original_filename)[0]
    download_name = f"{base_name}_风险截图.zip"

    return FileResponse(
        path=zip_path,
        filename=download_name,
        media_type="application/zip",
    )


@app.get("/api/download/{job_id}/muted-video")
async def download_muted_video(job_id: str, token: str = Query("")):
    """下载静音视频"""
    _require_token(token)
    job = _jobs_store.get(job_id)
    if not job:
        job = _load_job_meta(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    muted_path = job.get("muted_video_path", "")
    if not muted_path or not os.path.exists(muted_path):
        raise HTTPException(status_code=404, detail="静音视频不存在或生成失败")

    original_filename = job.get("original_filename", "video")
    base_name = os.path.splitext(original_filename)[0]
    download_name = f"{base_name}_静音视频.mp4"

    return FileResponse(
        path=muted_path,
        filename=download_name,
        media_type="video/mp4",
    )


@app.post("/api/cleanup")
async def trigger_cleanup():
    """手动触发清理旧任务"""
    count = cleanup_old_jobs(config.DATA_DIR, config.CLEANUP_HOURS, config.FAILED_JOB_RETENTION_HOURS)
    return {"cleaned_jobs": count, "max_age_hours": config.CLEANUP_HOURS}


# ==================== 前端页面 ====================

# 获取 web 目录的绝对路径
WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """服务首页"""
    index_path = os.path.join(WEB_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>index.html 未找到</h1>", status_code=404)


# ==================== 启动时清理 ====================

@app.on_event("startup")
async def startup_cleanup():
    """启动时清理过期任务并输出配置状态"""
    vision_ok = config.has_vision_key()
    deepseek_ok = config.has_deepseek_key()
    mock_mode = config.get_mock_mode()

    print("=" * 50)
    print("  视频风险点分析系统 v2")
    print("=" * 50)
    print(f"  Vision Key   : {'已配置' if vision_ok else '未配置'}")
    print(f"  DeepSeek Key : {'已配置' if deepseek_ok else '未配置'}")
    print(f"  运行模式     : {'Mock 模拟' if mock_mode else '真实 AI 分析'}")
    if mock_mode:
        print(f"  提示: 在 .env 中配置 API Key 后重启即可启用真实 AI")
    print("=" * 50)

    count = cleanup_old_jobs(config.DATA_DIR, config.CLEANUP_HOURS, config.FAILED_JOB_RETENTION_HOURS)
    if count > 0:
        print(f"[CLEANUP] 清理了 {count} 个过期任务目录")


# ==================== 入口 ====================

if __name__ == "__main__":
    import uvicorn
    print("Starting server...")
    uvicorn.run(
        "app.main:app",
        host=config.HOST,
        port=config.PORT,
        reload=True,
    )

 
