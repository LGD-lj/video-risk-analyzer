"""视频处理工具 —— 使用 OpenCV 和 FFmpeg"""

import os
import subprocess
import json
from pathlib import Path
import cv2

from .models import VideoInfo


def format_duration_display(seconds: float) -> str:
    """将秒数格式化为用户友好显示

    - 小于1秒但大于0: 1秒
    - 小于1小时: 0分10秒、3分25秒
    - 大于1小时: 1小时05分20秒
    - 无法读取: 未知
    """
    if seconds is None or seconds < 0:
        return "未知"
    if seconds == 0:
        return "未知"
    # 小于 1 秒的视频显示为 1 秒
    if seconds < 1:
        return "1秒"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}小时{m:02d}分{s:02d}秒"
    if m > 0:
        return f"{m}分{s}秒"
    return f"0分{s}秒"


def estimate_processing_time(duration_seconds: float, frame_interval: int, is_mock: bool) -> str:
    """根据视频参数估算处理时间

    返回: 预计处理时间描述字符串
    """
    if duration_seconds <= 0:
        return "无法估算处理时间"

    total_frames = max(1, int(duration_seconds / frame_interval) + 1)
    duration_display = format_duration_display(duration_seconds)

    if is_mock:
        # Mock 模式: 每帧约 0.15s，加固定开销
        est_seconds = total_frames * 0.15 + 3
        est_min_low = max(0.1, est_seconds / 60 * 0.7)
        est_min_high = max(0.2, est_seconds / 60 * 1.5)
    else:
        # 真实视觉模型: 每帧约 3-6 秒 (API 调用)
        est_min_low = total_frames * 2.5 / 60 + 0.5
        est_min_high = total_frames * 6 / 60 + 1

    # 小于1分钟时显示秒
    if est_min_high < 1:
        return f"视频时长约 {duration_display}，预计处理 {int(est_min_low*60)}-{int(est_min_high*60)} 秒，请勿关闭页面。"

    return f"视频时长约 {duration_display}，预计处理 {int(est_min_low)}-{int(est_min_high)} 分钟，请勿关闭页面。"


def get_video_info(video_path: str) -> VideoInfo:
    """使用 ffprobe 获取视频元信息，duration 为 0 时用 OpenCV 兜底"""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 读取视频信息失败: {result.stderr}")

    data = json.loads(result.stdout)

    # 找到视频流
    video_stream = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            video_stream = stream
            break

    if video_stream is None:
        raise ValueError("未找到视频流")

    duration = float(data["format"].get("duration", 0))
    width = video_stream.get("width", 0)
    height = video_stream.get("height", 0)
    fps_str = video_stream.get("r_frame_rate", "0/1")

    # 解析帧率（可能是 "30/1" 或 "29.97" 格式）
    if "/" in fps_str:
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) != 0 else 0
    else:
        fps = float(fps_str)

    codec = video_stream.get("codec_name", "unknown")

    # 获取 frame_count（ffprobe 流中的 nb_frames 或 format 中的 nb_streams 估算）
    frame_count_str = video_stream.get("nb_frames", "0")
    try:
        frame_count = int(frame_count_str)
    except (ValueError, TypeError):
        frame_count = 0

    # ═══════════════════════════════════════════════════════
    # 关键修复：ffprobe duration 为 0 时，用 OpenCV 兜底
    # ═══════════════════════════════════════════════════════
    if duration <= 0 and fps > 0:
        try:
            cap = cv2.VideoCapture(video_path)
            if cap.isOpened():
                cv_total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                cv_fps = cap.get(cv2.CAP_PROP_FPS)
                cap.release()
                if cv_fps > 0 and cv_total_frames > 0:
                    duration = cv_total_frames / cv_fps
                    if frame_count == 0:
                        frame_count = cv_total_frames
                    if fps == 0:
                        fps = cv_fps
        except Exception:
            pass  # OpenCV 兜底失败，维持 duration=0

    return VideoInfo(
        filename=os.path.basename(video_path),
        duration_seconds=round(duration, 2),
        resolution=f"{width}x{height}",
        fps=round(fps, 2),
        codec=codec,
        frame_count=frame_count,
        width=width,
        height=height,
    )


def extract_frames(video_path: str, output_dir: str, interval_seconds: int = 5) -> list[dict]:
    """每隔 interval_seconds 秒抽一帧

    返回: [{"index": 0, "timestamp_seconds": 0.0, "path": "frames/frame_0000.jpg"}, ...]
    """
    os.makedirs(output_dir, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频文件: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 30  # 回退默认值

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps

    frames_info = []
    current_second = 0.0
    index = 0

    while current_second <= duration:
        # 定位到指定秒数
        frame_number = int(current_second * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)

        ret, frame = cap.read()
        if not ret:
            break

        # 保存为 JPG
        filename = f"frame_{index:05d}.jpg"
        filepath = os.path.join(output_dir, filename)
        cv2.imwrite(filepath, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])

        frames_info.append({
            "index": index,
            "timestamp_seconds": round(current_second, 1),
            "path": filepath,
        })

        current_second += interval_seconds
        index += 1

    cap.release()
    return frames_info


def save_risk_screenshot(
    video_path: str,
    timestamp_seconds: float,
    output_path: str,
) -> str:
    """在指定时间点截取一帧保存为截图"""
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 30

    frame_number = int(timestamp_seconds * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
    ret, frame = cap.read()
    cap.release()

    if not ret:
        raise RuntimeError(f"无法在 {timestamp_seconds}s 处截图")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cv2.imwrite(output_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return output_path


def create_muted_video(input_path: str, output_path: str) -> dict:
    """生成去除音频的静音视频

    优先使用 copy 模式（无损快速），失败则 fallback 到重新编码。

    返回: {"success": bool, "path": str, "size_bytes": int, "has_audio": bool, "error": str}
    """
    result = {"success": False, "path": output_path, "size_bytes": 0, "has_audio": False, "error": ""}

    # --- 方式1: copy 模式（无损快速）---
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-c:v", "copy",
        "-an",
        output_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    copy_ok = proc.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0

    # --- 方式2: 重新编码 fallback ---
    if not copy_ok:
        print(f"[MUTED] copy mode failed, trying re-encode...")
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-an",
            output_path,
        ]
        subprocess.run(cmd, capture_output=True, text=True)

    # --- 校验 ---
    if not os.path.exists(output_path) or os.path.getsize(output_path) <= 0:
        result["error"] = f"ffmpeg 生成失败 (copy_ok={copy_ok})"
        return result

    result["size_bytes"] = os.path.getsize(output_path)

    # ffprobe 检查音频流
    probe_cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        output_path,
    ]
    probe = subprocess.run(probe_cmd, capture_output=True, text=True)
    has_audio = False
    if probe.returncode == 0:
        try:
            import json
            data = json.loads(probe.stdout)
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "audio":
                    has_audio = True
                    break
        except Exception:
            pass

    result["has_audio"] = has_audio
    if has_audio:
        result["error"] = "静音视频仍包含音频流"
        return result

    result["success"] = True
    print(f"[MUTED] 静音视频生成成功: {output_path} ({result['size_bytes']} bytes, audio=0)")
    return result
