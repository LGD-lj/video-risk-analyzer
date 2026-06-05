"""自动清理超时的任务文件"""

import os
import shutil
import time
from pathlib import Path


def cleanup_old_jobs(data_dir: str, max_hours: int = 24) -> int:
    """清理超过 max_hours 小时的任务目录

    返回: 清理的目录数量
    """
    if not os.path.isdir(data_dir):
        return 0

    now = time.time()
    max_age_seconds = max_hours * 3600
    cleaned = 0

    for entry in os.scandir(data_dir):
        if entry.is_dir():
            try:
                mtime = os.path.getmtime(entry.path)
                age = now - mtime
                if age > max_age_seconds:
                    shutil.rmtree(entry.path)
                    cleaned += 1
            except OSError:
                # 权限问题等，跳过
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
