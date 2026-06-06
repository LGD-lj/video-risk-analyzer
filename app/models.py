"""数据模型定义"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class RiskSeverity(str, Enum):
    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"


class RiskType(str, Enum):
    # A 类：强风险
    CONSTRUCTION = "施工"
    CONSTRUCTION_FENCE = "施工围挡"
    CONE_BARREL = "锥桶"
    TEMP_DIVERSION = "临时导流"
    HEIGHT_LIMIT = "限高"
    LOW_CLEARANCE = "低净空"
    CLEARANCE_CHECK = "净空核查"
    BRIDGE_TUNNEL = "桥洞"
    CANOPY = "顶棚"
    GATE = "闸口"
    GUARD_POST = "门岗"
    GUARDRAIL = "护栏"
    BARRIER = "隔离墩"
    NARROW_ROAD = "窄路"
    NARROW_MEETING = "通行空间受限"
    ROAD_ABNORMAL = "路面异常"
    TRUCK_BLOCK = "大型车辆遮挡"
    TRUCK_OCCUPY = "货车占道"
    # B 类：中风险
    NON_MOTOR_VEHICLE = "非机动车混行"
    PEDESTRIAN = "行人横穿"
    PARKING_OCCUPY = "停车占道"
    SHOP_ENTRANCE = "商铺门口"
    DENSE_ENTRANCE = "出入口密集"
    SIGHT_BLOCKED = "视线遮挡"
    LOGISTICS_ZONE = "物流装卸区"
    SLOW_PASS = "车辆低速通过"
    # 兜底
    OTHER = "其他待复核"


class RiskPoint(BaseModel):
    """单个风险点"""
    timestamp_seconds: float = Field(description="风险发生的时间点（秒）")
    timestamp_display: str = Field(description="格式化的时间点，如 00:20:35")
    severity: RiskSeverity = Field(description="风险等级：高/中/低")
    risk_types: list[RiskType] = Field(description="风险类型列表")
    risk_attribute: str = Field(default="待复核", description="风险属性：长期/阶段性风险、临时/动态风险、待复核")
    description: str = Field(description="风险描述")
    screenshot_path: str = Field(description="截图文件路径")


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobInfo(BaseModel):
    """任务信息"""
    job_id: str
    status: JobStatus
    filename: str
    duration_seconds: Optional[float] = None
    resolution: Optional[str] = None
    fps: Optional[float] = None
    total_frames: Optional[int] = None
    risk_count: Optional[int] = None
    report_url: Optional[str] = None
    screenshots_zip_url: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str = ""
    estimated_time: Optional[str] = None  # 预计处理时间描述
    user_notes: Optional[str] = None  # 用户额外关注内容
    duration_display: Optional[str] = None  # 格式化后的视频时长


class VideoInfo(BaseModel):
    """视频基本信息"""
    filename: str
    duration_seconds: float
    resolution: str  # e.g. "1920x1080"
    fps: float
    codec: str = "unknown"
    frame_count: int = 0
    width: int = 0
    height: int = 0


class VisionResult(BaseModel):
    """视觉模型单帧分析结果"""
    frame_index: int
    timestamp_seconds: float
    has_risk: bool
    risk_types: list[str] = []
    severity: str = ""  # "高" / "中" / "低"
    risk_score: int = 0  # 0-100，运营风险评分
    reason: str = ""  # 为什么对运营路线有影响
    description: str = ""
    long_term_risk: bool = False  # 是否长期风险
    long_term_reason: str = ""  # 长期风险判断原因
    risk_attribute: str = "待复核"  # 长期/阶段性风险 | 临时/动态风险 | 待复核


class TaskProgress(BaseModel):
    """任务进度（用于 SSE 或轮询）"""
    job_id: str
    status: JobStatus
    stage: str = ""  # 当前阶段描述
    progress_percent: int = 0  # 0-100
    message: str = ""
