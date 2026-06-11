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
    MAX_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "8192"))
    CLEANUP_HOURS: int = int(os.getenv("CLEANUP_HOURS", "24"))
    FAILED_JOB_RETENTION_HOURS: int = int(os.getenv("FAILED_JOB_RETENTION_HOURS", "1"))
    RESULT_KEEP_HOURS: int = int(os.getenv("RESULT_KEEP_HOURS", "24"))

    # ---------- 公网访问 ----------
    PUBLIC_ACCESS_ENABLED: bool = os.getenv("PUBLIC_ACCESS_ENABLED", "false").lower() in ("true", "1", "yes")
    UPLOAD_TOKEN: str = os.getenv("UPLOAD_TOKEN", "")
    MAX_CONCURRENT_JOBS: int = int(os.getenv("MAX_CONCURRENT_JOBS", "1"))

    # ---------- 视频处理 ----------
    FRAME_INTERVAL_SECONDS: int = int(os.getenv("FRAME_INTERVAL_SECONDS", "5"))

    # ---------- 分析模式：full(正式) | quick(快速测试) ----------
    ANALYSIS_MODE: str = os.getenv("ANALYSIS_MODE", "full")
    QUICK_FRAME_INTERVAL: int = int(os.getenv("QUICK_FRAME_INTERVAL", "15"))
    QUICK_MAX_FRAMES: int = int(os.getenv("QUICK_MAX_FRAMES", "40"))

    # ---------- 召回优先模式 ----------
    RISK_RECALL_MODE: bool = os.getenv("RISK_RECALL_MODE", "true").lower() in ("true", "1", "yes")

    # ---------- 候选池 ----------
    MIN_RISK_SCORE: int = int(os.getenv("MIN_RISK_SCORE", "40"))  # 进入候选池的最低分
    MAX_CANDIDATE_POOL: int = int(os.getenv("MAX_CANDIDATE_POOL", "60"))  # 候选池上限

    # ---------- 风险去重 ----------
    DEDUP_INTERVAL_SECONDS: int = int(os.getenv("DEDUP_INTERVAL_SECONDS", "30"))
    MIN_GAP_SECONDS: int = int(os.getenv("MIN_GAP_SECONDS", "30"))  # 同类型风险最小间隔

    # ---------- 风险点数量 ----------
    MAX_RISK_POINTS: int = int(os.getenv("MAX_RISK_POINTS", "12"))
    MIN_RISK_POINTS: int = int(os.getenv("MIN_RISK_POINTS", "3"))

    # ---------- 视觉模型配置（可替换 provider）----------
    VISION_PROVIDER: str = os.getenv("VISION_PROVIDER", "dashscope")  # openai | dashscope
    VISION_API_KEY: str = os.getenv("VISION_API_KEY", "")
    VISION_BASE_URL: str = os.getenv("VISION_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    VISION_MODEL: str = os.getenv("VISION_MODEL", "qwen-vl-plus")

    # ---------- DeepSeek 文本模型 ----------
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    @classmethod
    def has_vision_key(cls) -> bool:
        """视觉模型 Key 是否已配置"""
        return bool(cls.VISION_API_KEY and cls.VISION_API_KEY.strip())

    @classmethod
    def has_deepseek_key(cls) -> bool:
        """DeepSeek Key 是否已配置"""
        return bool(cls.DEEPSEEK_API_KEY and cls.DEEPSEEK_API_KEY.strip())

    @classmethod
    def get_mock_mode(cls) -> bool:
        """检测是否处于 Mock 模式（任一 Key 缺失即为 Mock）"""
        return not cls.has_vision_key() or not cls.has_deepseek_key()

    @classmethod
    def get_missing_keys(cls) -> list[str]:
        """返回缺失的 API Key 列表"""
        missing = []
        if not cls.has_vision_key():
            missing.append("VISION_API_KEY")
        if not cls.has_deepseek_key():
            missing.append("DEEPSEEK_API_KEY")
        return missing

    @classmethod
    def validate(cls) -> list[str]:
        """校验必要配置（Mock 模式下不报错）"""
        return cls.get_missing_keys()


config = Config()
