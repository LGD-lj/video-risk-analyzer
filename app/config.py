"""配置读取模块 —— 所有配置从 .env 文件读取"""

import os
from dotenv import load_dotenv

# 加载项目根目录下的 .env 文件
load_dotenv()


class Config:
    """全局配置单例"""

    # ---------- 基础配置 ----------
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "8000"))
    DATA_DIR: str = os.getenv("DATA_DIR", "data/jobs")
    MAX_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "2000"))
    CLEANUP_HOURS: int = int(os.getenv("CLEANUP_HOURS", "24"))
    FAILED_JOB_RETENTION_HOURS: int = int(os.getenv("FAILED_JOB_RETENTION_HOURS", "1"))

    # ---------- 视频处理 ----------
    FRAME_INTERVAL_SECONDS: int = int(os.getenv("FRAME_INTERVAL_SECONDS", "5"))
    DEDUP_INTERVAL_SECONDS: int = int(os.getenv("DEDUP_INTERVAL_SECONDS", "30"))
    MAX_RISK_POINTS: int = int(os.getenv("MAX_RISK_POINTS", "12"))
    MIN_RISK_POINTS: int = int(os.getenv("MIN_RISK_POINTS", "3"))

    # ---------- 视觉模型配置（可替换 provider）----------
    VISION_PROVIDER: str = os.getenv("VISION_PROVIDER", "openai")  # openai | custom
    VISION_API_KEY: str = os.getenv("VISION_API_KEY", "")
    VISION_BASE_URL: str = os.getenv("VISION_BASE_URL", "https://api.openai.com/v1")
    VISION_MODEL: str = os.getenv("VISION_MODEL", "gpt-4o")

    # ---------- DeepSeek 文本模型 ----------
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    @classmethod
    def get_mock_mode(cls) -> bool:
        """检测是否处于 Mock 模式（API Key 未配置时自动进入）"""
        return not cls.VISION_API_KEY or not cls.DEEPSEEK_API_KEY

    @classmethod
    def get_missing_keys(cls) -> list[str]:
        """返回缺失的 API Key 列表"""
        missing = []
        if not cls.VISION_API_KEY:
            missing.append("VISION_API_KEY")
        if not cls.DEEPSEEK_API_KEY:
            missing.append("DEEPSEEK_API_KEY")
        return missing

    @classmethod
    def validate(cls) -> list[str]:
        """校验必要配置（Mock 模式下不报错）"""
        return cls.get_missing_keys()


config = Config()
