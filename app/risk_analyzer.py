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


# ---------- 风险分类 ----------
_RISK_CLASS_A = {  # 强风险，优先保留
    "施工", "限高", "锥桶", "临时导流", "低净空", "桥洞", "顶棚",
    "闸口", "门岗", "隔离墩", "护栏", "货车遮挡", "路面异常", "车辆低速通过",
}
_RISK_CLASS_B = {  # 中风险，适量保留
    "非机动车", "行人", "停车占道", "窄路", "出入口密集", "商铺门口", "视线遮挡",
    "物流装卸区", "会车空间不足",
}
# 不在 A/B 中的类型为 C 类弱风险

# 每类去重间隔：强风险更短（保留更多），弱风险更长（更激进去重）
_GAP_A = 25   # A 类：25 秒
_GAP_B = 35   # B 类：35 秒
_GAP_C = 60   # C 类：60 秒

# 每类最终输出上限
_MAX_A = 8    # A 类最多 8 个（不受限但也要去重）
_MAX_B = 4    # B 类最多 4 个
_MAX_C = 1    # C 类最多 1 个

# B 类子类别上限
_MAX_NON_MOTOR = 4     # 非机动车最多 4 个
_MAX_TREE_BLOCK = 2    # 树木遮挡最多 2 个
_MAX_PARKING = 4       # 停车占道最多 4 个
_MAX_SHOP = 2          # 商铺门口最多 2 个


def _risk_class(r: "VisionResult") -> str:
    """判断风险所属类别"""
    types = set(r.risk_types) if r.risk_types else set()
    if types & _RISK_CLASS_A:
        return "A"
    if types & _RISK_CLASS_B:
        return "B"
    return "C"


def _get_gap(r: "VisionResult") -> int:
    """获取该风险点的去重间隔"""
    cls = _risk_class(r)
    if cls == "A":
        return _GAP_A
    if cls == "B":
        return _GAP_B
    return _GAP_C


def _deduplicate_risks(
    results: list["VisionResult"],
    min_gap_seconds: int = 30,
) -> list["VisionResult"]:
    """分类感知去重：
    - 强风险(A类)：较小间隔(25s)，保留更多
    - 中风险(B类)：中等间隔(45s)
    - 弱风险(C类)：较大间隔(60s)，激进去重
    - 重叠 >= 50% 且时间 < 该类间隔 → 重复
    """
    if not results:
        return []

    sorted_results = sorted(results, key=lambda r: r.risk_score, reverse=True)
    kept: list["VisionResult"] = []

    for r in sorted_results:
        is_duplicate = False
        r_types = set(r.risk_types) if r.risk_types else set()
        gap = _get_gap(r)

        for k in kept:
            k_types = set(k.risk_types) if k.risk_types else set()
            if not r_types or not k_types:
                continue
            overlap = len(r_types & k_types)
            min_len = min(len(r_types), len(k_types))
            overlap_ratio = overlap / min_len if min_len > 0 else 0
            time_gap = abs(r.timestamp_seconds - k.timestamp_seconds)

            if overlap_ratio >= 0.5 and time_gap < gap:
                is_duplicate = True
                break

        if not is_duplicate:
            kept.append(r)

    kept.sort(key=lambda r: r.timestamp_seconds)
    return kept


def _select_top_risks(
    results: list["VisionResult"],
    max_count: int = 12,
) -> list["VisionResult"]:
    """分类感知筛选：
    - A类(强风险)优先，不设硬上限但去重
    - B类(中风险)每子类有上限
    - C类(弱风险)最多 1 个
    - 总分上限 max_count
    """
    if not results:
        return []

    # 按 risk_score 降序
    sorted_results = sorted(results, key=lambda r: r.risk_score, reverse=True)

    selected: list["VisionResult"] = []
    # 子类计数器
    count_non_motor = 0
    count_tree = 0
    count_parking = 0
    count_shop = 0
    count_c = 0

    for r in sorted_results:
        cls = _risk_class(r)
        types = set(r.risk_types) if r.risk_types else set()

        # A 类点不受 B/C 上限限制（如施工+非机动车，仍应保留）
        if cls == "A" and len(selected) < max_count:
            selected.append(r)
            # 仍然递增 B 类计数器（让后续纯 B 类点受限制）
            if "非机动车" in types:
                count_non_motor += 1
            if any("树" in t for t in types):
                count_tree += 1
            if "停车占道" in types:
                count_parking += 1
            if "商铺门口" in types:
                count_shop += 1
            continue

        # B/C 类点：检查所有子类上限
        would_block = False
        if cls == "C" and count_c >= _MAX_C:
            would_block = True
        if "非机动车" in types and count_non_motor >= _MAX_NON_MOTOR:
            would_block = True
        if any("树" in t for t in types) and count_tree >= _MAX_TREE_BLOCK:
            would_block = True
        if "停车占道" in types and count_parking >= _MAX_PARKING:
            would_block = True
        if "商铺门口" in types and count_shop >= _MAX_SHOP:
            would_block = True

        if would_block:
            continue

        selected.append(r)
        if cls == "C":
            count_c += 1
        if "非机动车" in types:
            count_non_motor += 1
        if any("树" in t for t in types):
            count_tree += 1
        if "停车占道" in types:
            count_parking += 1
        if "商铺门口" in types:
            count_shop += 1

        # 总分上限
        if len(selected) >= max_count:
            break

    selected.sort(key=lambda r: r.timestamp_seconds)
    return selected


def _parse_risk_type(risk_type_str: str) -> RiskType:
    """将字符串风险类型转为枚举（支持标准类型和旧类型兼容）"""
    mapping = {
        # 标准类型
        "施工": RiskType.CONSTRUCTION, "修路": RiskType.CONSTRUCTION,
        "施工围挡": RiskType.CONSTRUCTION_FENCE,
        "锥桶": RiskType.CONE_BARREL, "临时导流": RiskType.TEMP_DIVERSION,
        "限高": RiskType.HEIGHT_LIMIT, "低净空": RiskType.LOW_CLEARANCE,
        "净空核查": RiskType.CLEARANCE_CHECK, "桥洞": RiskType.BRIDGE_TUNNEL,
        "顶棚": RiskType.CANOPY, "隧道": RiskType.BRIDGE_TUNNEL,
        "闸口": RiskType.GATE, "门岗": RiskType.GUARD_POST,
        "护栏": RiskType.GUARDRAIL, "隔离墩": RiskType.BARRIER,
        "窄路": RiskType.NARROW_ROAD, "通行空间受限": RiskType.NARROW_MEETING,
        "非机动车": RiskType.NON_MOTOR_VEHICLE, "非机动车混行": RiskType.NON_MOTOR_VEHICLE,
        "行人": RiskType.PEDESTRIAN, "行人横穿": RiskType.PEDESTRIAN,
        "停车占道": RiskType.PARKING_OCCUPY,
        "商铺门口": RiskType.SHOP_ENTRANCE, "出入口密集": RiskType.DENSE_ENTRANCE,
        "大型车辆遮挡": RiskType.TRUCK_BLOCK, "货车遮挡": RiskType.TRUCK_BLOCK,
        "货车占道": RiskType.TRUCK_OCCUPY, "工程车占道": RiskType.TRUCK_OCCUPY,
        "视线遮挡": RiskType.SIGHT_BLOCKED, "路面异常": RiskType.ROAD_ABNORMAL,
        "物流装卸区": RiskType.LOGISTICS_ZONE, "车辆低速通过": RiskType.SLOW_PASS,
        # 兜底
        "其他": RiskType.OTHER, "其他待复核": RiskType.OTHER,
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
            "long_term_risk": getattr(result, 'long_term_risk', False),
            "long_term_reason": getattr(result, 'long_term_reason', ''),
        })
        # 候选池：按分类使用不同门槛
        r_cls = _risk_class(result)
        if r_cls == "A":
            threshold = 40  # 强风险：>=40 就进池
        elif r_cls == "B":
            threshold = 50  # 中风险：>=50
        else:
            threshold = 65  # 弱风险：>=65 才进池
        if result.has_risk and result.risk_score >= threshold:
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

    update_progress("风险识别中", 70, f"候选池 {candidate_count} 个风险帧（按分类门槛筛选）")

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
            "long_term_risk": getattr(result, 'long_term_risk', False),
            "long_term_reason": getattr(result, 'long_term_reason', ''),
            "risk_attribute": getattr(result, 'risk_attribute', '待复核'),
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
            risk_attribute=item.get("risk_attribute", "待复核"),
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
