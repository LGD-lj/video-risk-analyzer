"""自动清理超时的任务文件"""

import os
import shutil
import json
import time
from pathlib import Path


def cleanup_old_jobs(data_dir: str, max_hours: int = 24, failed_hours: int = 1) -> int:
    """清理超时的任务目录

    - 成功完成的任务: 超过 max_hours 小时自动清理
    - 失败的任务: 超过 failed_hours 小时自动清理（默认 1 小时）

    返回: 清理的目录数量
    """
    if not os.path.isdir(data_dir):
        return 0

    now = time.time()
    max_age_seconds = max_hours * 3600
    failed_age_seconds = failed_hours * 3600
    cleaned = 0

    for entry in os.scandir(data_dir):
        if not entry.is_dir():
            continue

        # 跳过 _meta 目录
        if entry.name == "_meta":
            continue

        try:
            mtime = os.path.getmtime(entry.path)
            age = now - mtime

            # 判断是否失败任务
            is_failed = False
            meta_path = os.path.join(data_dir, "_meta", f"{entry.name}.json")
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    if meta.get("status") == "failed":
                        is_failed = True
                except (json.JSONDecodeError, OSError):
                    pass

            threshold = failed_age_seconds if is_failed else max_age_seconds

            if age > threshold:
                shutil.rmtree(entry.path)
                # 同时清理 meta 文件
                if os.path.exists(meta_path):
                    os.remove(meta_path)
                cleaned += 1
                print(f"[CLEANUP] 已清理{'失败' if is_failed else ''}任务目录: {entry.name} (年龄: {age/3600:.1f}h)")

        except OSError:
            pass

    # 清理孤儿 meta 文件（对应 job 目录已不存在）
    meta_dir = os.path.join(data_dir, "_meta")
    if os.path.isdir(meta_dir):
        for entry in os.scandir(meta_dir):
            if entry.is_file() and entry.name.endswith(".json"):
                job_id = entry.name.replace(".json", "")
                job_dir = os.path.join(data_dir, job_id)
                if not os.path.isdir(job_dir):
                    try:
                        os.remove(entry.path)
                        cleaned += 1
                    except OSError:
                        pass

    return cleaned


def get_job_dir_size_mb(job_dir: str) -> float:
    """计算任务目录大小（MB）"""
    total = 0
    for dirpath, dirnames, filenames in os.walk(job_dir):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total / (1024 * 1024)
