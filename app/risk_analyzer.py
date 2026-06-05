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
    min_gap_seconds: int = 30,
) -> list[VisionResult]:
    """类型感知去重：
    - 对每个已保留的帧，检查新帧的类型重叠率
    - 重叠 >= 50% 且时间间隔 < min_gap_seconds → 视为重复，跳过
    - 重叠 < 50% 或时间间隔足够 → 保留
    """
    if not results:
        return []

    # 按 risk_score 降序排列（高分优先保留）
    sorted_results = sorted(results, key=lambda r: r.risk_score, reverse=True)

    kept: list[VisionResult] = []

    for r in sorted_results:
        is_duplicate = False
        r_types = set(r.risk_types) if r.risk_types else set()

        for k in kept:
            k_types = set(k.risk_types) if k.risk_types else set()
            if not r_types or not k_types:
                continue

            # 计算类型重叠率
            overlap = len(r_types & k_types)
            min_len = min(len(r_types), len(k_types))
            overlap_ratio = overlap / min_len if min_len > 0 else 0

            # 时间间隔
            time_gap = abs(r.timestamp_seconds - k.timestamp_seconds)

            # 类型重叠 >= 50% 且时间 < min_gap_seconds → 重复
            if overlap_ratio >= 0.5 and time_gap < min_gap_seconds:
                is_duplicate = True
                break

        if not is_duplicate:
            kept.append(r)

    # 最终按时间排序输出
    kept.sort(key=lambda r: r.timestamp_seconds)
    return kept


def _select_top_risks(
    results: list[VisionResult],
    max_count: int = 12,
) -> list[VisionResult]:
    """按 risk_score 排序筛选最终风险点

    原则：
    - risk_score 优先（高分的更有代表性）
    - 上限 max_count 个
    - 风险少时少于目标数量也可以
    """
    if not results:
        return []

    # 按 risk_score 降序，同分按时间
    sorted_results = sorted(
        results,
        key=lambda r: (r.risk_score, -r.timestamp_seconds),
        reverse=True,
    )

    return sorted_results[:max_count]


def _parse_risk_type(risk_type_str: str) -> RiskType:
    """将字符串风险类型转为枚举"""
    mapping = {
        "施工": RiskType.CONSTRUCTION, "限高": RiskType.HEIGHT_LIMIT,
        "锥桶": RiskType.CONE_BARREL, "窄路": RiskType.NARROW_ROAD,
        "闸口": RiskType.GATE, "行人": RiskType.PEDESTRIAN,
        "非机动车": RiskType.NON_MOTOR_VEHICLE, "货车遮挡": RiskType.TRUCK_BLOCK,
        "停车占道": RiskType.PARKING_OCCUPY, "低净空": RiskType.LOW_CLEARANCE,
        "物流装卸区": RiskType.LOGISTICS_ZONE, "出入口密集": RiskType.DENSE_ENTRANCE,
        "路面异常": RiskType.ROAD_ABNORMAL, "临时导流": RiskType.TEMP_DIVERSION,
        "桥洞": RiskType.BRIDGE_TUNNEL, "顶棚": RiskType.CANOPY,
        "会车空间不足": RiskType.NARROW_MEETING, "门岗": RiskType.GUARD_POST,
        "护栏": RiskType.GUARDRAIL, "隔离墩": RiskType.BARRIER,
        "视线遮挡": RiskType.SIGHT_BLOCKED, "商铺门口": RiskType.SHOP_ENTRANCE,
        "车辆低速通过": RiskType.SLOW_PASS,
    }
    return mapping.get(risk_type_str, RiskType.OTHER)


def run_analysis(
    job_id: str,
    video_path: str,
    job_dir: str,
    progress_callback: Optional[callable] = None,
    user_notes: str = "",
) -> tuple[list[RiskPoint], str, str]:
    """执行完整风险分析流程

    Args:
        job_id: 任务 ID
        video_path: 视频文件路径
        job_dir: 任务工作目录
        progress_callback: 进度回调 (stage, percent, message)
        user_notes: 用户额外关注内容

    Returns:
        (risk_points, report_path, screenshots_zip_path)
    """

    def update_progress(stage: str, percent: int, message: str = ""):
        if progress_callback:
            progress_callback(stage, percent, message)

    # ---------- Step 1: 视频校验 ----------
    update_progress("视频校验", 3)
    video_info = get_video_info(video_path)

    # ---------- Step 2: 抽帧（根据分析模式选择间隔） ----------
    update_progress("抽帧中", 8)
    frames_dir = os.path.join(job_dir, "frames")

    # full 模式: 每 FRAME_INTERVAL_SECONDS 秒抽一帧，不限帧数
    # quick 模式: 每 QUICK_FRAME_INTERVAL 秒抽一帧，最多 QUICK_MAX_FRAMES 帧
    if config.ANALYSIS_MODE == "quick":
        frame_interval = config.QUICK_FRAME_INTERVAL
        max_frames_limit = config.QUICK_MAX_FRAMES
        print(f"[INFO] Quick test mode: interval={frame_interval}s, max={max_frames_limit} frames")
    else:
        frame_interval = config.FRAME_INTERVAL_SECONDS
        max_frames_limit = 0  # 0 = 不限制
        print(f"[INFO] Full analysis mode: interval={frame_interval}s, no frame limit")

    frames = extract_frames(video_path, frames_dir, frame_interval)
    if max_frames_limit > 0 and len(frames) > max_frames_limit:
        frames = frames[:max_frames_limit]
    total_frames = len(frames)
    update_progress("抽帧中", 10, f"已抽取 {total_frames} 帧")

    # ---------- Step 3: 风险识别（候选池机制） ----------
    vision = create_vision_provider(
        provider_type=config.VISION_PROVIDER,
        api_key=config.VISION_API_KEY,
        base_url=config.VISION_BASE_URL,
        model=config.VISION_MODEL,
    )

    risk_results: list[VisionResult] = []
    all_results: list[dict] = []  # 保存所有帧的完整结果用于调试
    min_score = config.MIN_RISK_SCORE if config.RISK_RECALL_MODE else 50

    for i, frame in enumerate(frames):
        pct = 10 + int((i / max(total_frames, 1)) * 60)  # 10% → 70%
        ts_display = _format_timestamp(frame["timestamp_seconds"])
        update_progress(
            "风险识别中",
            pct,
            f"分析第 {i+1}/{total_frames} 帧 ({ts_display})",
        )

        result = vision.analyze_frame(
            image_path=frame["path"],
            frame_index=frame["index"],
            timestamp_seconds=frame["timestamp_seconds"],
            user_notes=user_notes,
        )

        # 记录所有帧结果（调试用）
        all_results.append({
            "frame_index": result.frame_index,
            "timestamp_seconds": result.timestamp_seconds,
            "has_risk": result.has_risk,
            "risk_score": result.risk_score,
            "risk_types": result.risk_types,
            "severity": result.severity,
            "description": result.description[:80],
            "reason": getattr(result, 'reason', ''),
        })
        # 候选池：保留 risk_score >= MIN_RISK_SCORE 的所有帧
        if result.has_risk and result.risk_score >= min_score:
            risk_results.append(result)

    # 保存原始分析结果到文件
    raw_path = os.path.join(job_dir, "vision_raw.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"[DEBUG] Saved vision_raw.json with {len(all_results)} frames to {raw_path}")

    candidate_count = len(risk_results)
    # 候选池上限裁剪：按分数保留最高的
    if candidate_count > config.MAX_CANDIDATE_POOL:
        risk_results.sort(key=lambda r: r.risk_score, reverse=True)
        risk_results = risk_results[:config.MAX_CANDIDATE_POOL]
        candidate_count = len(risk_results)

    update_progress("风险识别中", 70, f"候选池 {candidate_count} 个风险帧（score>={min_score}）")

    # ---------- Step 4: 类型感知去重 ----------
    update_progress("生成报告中", 75, f"去重中（同类型间隔>={config.MIN_GAP_SECONDS}s）")
    deduped = _deduplicate_risks(risk_results, config.MIN_GAP_SECONDS)

    # ---------- Step 5: 按分数排序筛选 ----------
    update_progress("生成报告中", 80, f"从{len(deduped)}个候选筛选")
    selected = _select_top_risks(deduped, config.MAX_RISK_POINTS)

    # ---------- Step 6: 保存截图 ----------
    update_progress("生成报告中", 85, "保存风险截图")
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
            "risk_score": result.risk_score,
            "risk_types": result.risk_types,
            "description": result.description,
            "reason": getattr(result, 'reason', ''),
            "screenshot_path": screenshot_path,
        })

    # ---------- Step 7: DeepSeek 润色描述 ----------
    update_progress("生成报告中", 90, "AI 润色风险描述")
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

    # ---------- Step 8.5: 保存 risk_points.json ----------
    update_progress("生成报告中", 92, "保存分析结果")
    try:
        risk_points_json = []
        for idx, rp in enumerate(risk_points):
            risk_points_json.append({
                "index": idx + 1,
                "timestamp_seconds": rp.timestamp_seconds,
                "timestamp_display": rp.timestamp_display,
                "severity": rp.severity.value if hasattr(rp.severity, 'value') else rp.severity,
                "risk_types": [rt.value if hasattr(rt, 'value') else str(rt) for rt in rp.risk_types],
                "description": rp.description,
            })
        json_path = os.path.join(job_dir, "risk_points.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(risk_points_json, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] 保存 risk_points.json 失败: {e}")

    # ---------- Step 9: 生成 Word 报告 ----------
    update_progress("生成报告中", 93, "生成 Word 报告")
    report_path = os.path.join(job_dir, "风险分析报告.docx")
    generate_word_report(
        video_info=video_info,
        risk_points=risk_points,
        output_path=report_path,
    )

    # ---------- Step 10: 打包截图 ZIP ----------
    update_progress("生成报告中", 97, "打包截图")
    zip_path = os.path.join(job_dir, "screenshots.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rp in risk_points:
            if os.path.exists(rp.screenshot_path):
                arcname = os.path.basename(rp.screenshot_path)
                zf.write(rp.screenshot_path, arcname)

    update_progress("已完成", 100, "分析完成")
    return risk_points, report_path, zip_path
