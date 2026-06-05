"""风险点分析主逻辑 —— 抽帧 → 视觉识别 → 去重 → 筛选 → 截图 → 润色"""

import os
import zipfile
import json
from typing import Optional

from .config import config
from .models import (
    VideoInfo,
    VisionResult,
    RiskPoint,
    RiskSeverity,
    RiskType,
    JobInfo,
    JobStatus,
    TaskProgress,
)
from .video_utils import get_video_info, extract_frames, save_risk_screenshot
from .vision_provider import create_vision_provider
from .llm_provider import DeepSeekProvider
from .report_generator import generate_word_report


def _format_timestamp(seconds: float) -> str:
    """将秒数格式化为 HH:MM:SS"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _severity_rank(severity: str) -> int:
    """风险等级排序权重"""
    mapping = {"高": 3, "中": 2, "低": 1}
    return mapping.get(severity, 0)


def _deduplicate_risks(
    results: list[VisionResult],
    dedup_seconds: int = 30,
) -> list[VisionResult]:
    """对风险结果去重，同类型风险在 dedup_seconds 内只保留第一个"""
    if not results:
        return []

    # 按时间排序
    sorted_results = sorted(results, key=lambda r: r.timestamp_seconds)

    kept = []
    last_kept_time = -999

    for r in sorted_results:
        if r.timestamp_seconds - last_kept_time >= dedup_seconds:
            kept.append(r)
            last_kept_time = r.timestamp_seconds

    return kept


def _select_top_risks(
    results: list[VisionResult],
    min_count: int = 5,
    max_count: int = 10,
) -> list[VisionResult]:
    """按严重程度和代表性筛选最终风险点"""
    if not results:
        return []

    # 按严重程度排序
    sorted_results = sorted(
        results,
        key=lambda r: (_severity_rank(r.severity), -r.timestamp_seconds),
        reverse=True,
    )

    selected = sorted_results[:max_count]

    # 如果够了最小数量就直接返回
    if len(selected) >= min_count:
        return selected

    # 不够的话全部返回
    return sorted_results[:max_count]


def _parse_risk_type(risk_type_str: str) -> RiskType:
    """将字符串风险类型转为枚举"""
    mapping = {
        "施工": RiskType.CONSTRUCTION,
        "限高": RiskType.HEIGHT_LIMIT,
        "锥桶": RiskType.CONE_BARREL,
        "窄路": RiskType.NARROW_ROAD,
        "闸口": RiskType.GATE,
        "行人": RiskType.PEDESTRIAN,
        "非机动车": RiskType.NON_MOTOR_VEHICLE,
        "货车遮挡": RiskType.TRUCK_BLOCK,
        "停车占道": RiskType.PARKING_OCCUPY,
        "低净空": RiskType.LOW_CLEARANCE,
    }
    return mapping.get(risk_type_str, RiskType.OTHER)


def run_analysis(
    job_id: str,
    video_path: str,
    job_dir: str,
    progress_callback: Optional[callable] = None,
) -> tuple[list[RiskPoint], str, str]:
    """执行完整风险分析流程

    Args:
        job_id: 任务 ID
        video_path: 视频文件路径
        job_dir: 任务工作目录
        progress_callback: 进度回调 (stage, percent, message)

    Returns:
        (risk_points, report_path, screenshots_zip_path)
    """

    def update_progress(stage: str, percent: int, message: str = ""):
        if progress_callback:
            progress_callback(stage, percent, message)

    # ---------- Step 1: 视频信息 ----------
    update_progress("读取视频信息", 5)
    video_info = get_video_info(video_path)

    # ---------- Step 2: 抽帧 ----------
    update_progress("抽取视频帧", 10)
    frames_dir = os.path.join(job_dir, "frames")
    frames = extract_frames(video_path, frames_dir, config.FRAME_INTERVAL_SECONDS)
    total_frames = len(frames)
    update_progress(f"共抽取 {total_frames} 帧", 15)

    # ---------- Step 3: 视觉模型逐帧分析 ----------
    vision = create_vision_provider(
        provider_type=config.VISION_PROVIDER,
        api_key=config.VISION_API_KEY,
        base_url=config.VISION_BASE_URL,
        model=config.VISION_MODEL,
    )

    risk_results: list[VisionResult] = []
    for i, frame in enumerate(frames):
        pct = 15 + int((i / max(total_frames, 1)) * 55)  # 15% → 70%
        ts_display = _format_timestamp(frame["timestamp_seconds"])
        update_progress(
            f"视觉分析第 {i+1}/{total_frames} 帧 ({ts_display})",
            pct,
        )

        result = vision.analyze_frame(
            image_path=frame["path"],
            frame_index=frame["index"],
            timestamp_seconds=frame["timestamp_seconds"],
        )

        if result.has_risk:
            risk_results.append(result)

    update_progress(f"识别到 {len(risk_results)} 个潜在风险帧", 70)

    # ---------- Step 4: 去重 ----------
    update_progress("风险去重", 75)
    deduped = _deduplicate_risks(risk_results, config.DEDUP_INTERVAL_SECONDS)

    # ---------- Step 5: 筛选 5-10 个 ----------
    update_progress("筛选最终风险点", 80)
    selected = _select_top_risks(deduped, config.MIN_RISK_POINTS, config.MAX_RISK_POINTS)

    # ---------- Step 6: 保存截图 ----------
    update_progress("保存风险截图", 85)
    screenshots_dir = os.path.join(job_dir, "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)

    risk_points_raw = []
    for i, result in enumerate(selected):
        ts_display = _format_timestamp(result.timestamp_seconds)
        screenshot_filename = f"risk_{i+1:02d}_{ts_display.replace(':', '-')}.jpg"
        screenshot_path = os.path.join(screenshots_dir, screenshot_filename)

        save_risk_screenshot(
            video_path=video_path,
            timestamp_seconds=result.timestamp_seconds,
            output_path=screenshot_path,
        )

        risk_types_enum = [_parse_risk_type(t) for t in result.risk_types]

        risk_points_raw.append({
            "index": i + 1,
            "timestamp_seconds": result.timestamp_seconds,
            "timestamp_display": ts_display,
            "severity": result.severity,
            "risk_types": result.risk_types,
            "description": result.description,
            "screenshot_path": screenshot_path,
        })

    # ---------- Step 7: DeepSeek 润色描述 ----------
    update_progress("AI 润色风险描述", 90)
    llm = DeepSeekProvider(
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
        model=config.DEEPSEEK_MODEL,
    )
    polished = llm.polish_risk_descriptions(risk_points_raw)

    # ---------- Step 8: 转换为 RiskPoint 对象 ----------
    risk_points = []
    for item in polished:
        risk_types_enum = [_parse_risk_type(t) for t in item["risk_types"]]
        severity = RiskSeverity.HIGH
        if item["severity"] == "中":
            severity = RiskSeverity.MEDIUM
        elif item["severity"] == "低":
            severity = RiskSeverity.LOW

        risk_points.append(RiskPoint(
            timestamp_seconds=item["timestamp_seconds"],
            timestamp_display=item["timestamp_display"],
            severity=severity,
            risk_types=risk_types_enum,
            description=item["description"],
            screenshot_path=item["screenshot_path"],
        ))

    # ---------- Step 9: 生成 Word 报告 ----------
    update_progress("生成 Word 报告", 93)
    report_path = os.path.join(job_dir, "风险分析报告.docx")
    generate_word_report(
        video_info=video_info,
        risk_points=risk_points,
        output_path=report_path,
    )

    # ---------- Step 10: 打包截图 ZIP ----------
    update_progress("打包截图", 97)
    zip_path = os.path.join(job_dir, "screenshots.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rp in risk_points:
            if os.path.exists(rp.screenshot_path):
                arcname = os.path.basename(rp.screenshot_path)
                zf.write(rp.screenshot_path, arcname)

    update_progress("分析完成", 100)
    return risk_points, report_path, zip_path
