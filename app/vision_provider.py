"""视觉模型接口 —— 可替换 provider，默认支持 OpenAI 视觉模型"""

import base64
import hashlib
import json
import random
import re
from abc import ABC, abstractmethod
from typing import Optional
import requests

from .models import VisionResult


def _encode_image(image_path: str) -> str:
    """将图片编码为 base64 data URL"""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

# Mock 模式的风险场景库
_MOCK_RISK_SCENARIOS = [
    {"risk_types": ["施工"], "severity": "高", "description": "前方路面施工，有围挡和施工标志，需减速变道"},
    {"risk_types": ["限高"], "severity": "中", "description": "出现限高标志杆，限高约3.5米，需确认车辆高度"},
    {"risk_types": ["锥桶"], "severity": "中", "description": "路侧有锥桶警示，提示前方道路施工区域"},
    {"risk_types": ["窄路"], "severity": "中", "description": "道路前方收窄，车道数减少，需注意并线"},
    {"risk_types": ["闸口"], "severity": "低", "description": "前方为收费站闸口，需减速通行"},
    {"risk_types": ["行人"], "severity": "高", "description": "行人正在横穿马路，需紧急减速让行"},
    {"risk_types": ["非机动车"], "severity": "中", "description": "右侧有电动车行驶，保持安全距离"},
    {"risk_types": ["货车遮挡"], "severity": "中", "description": "前方大货车遮挡视线，无法观察前方路况"},
    {"risk_types": ["停车占道"], "severity": "低", "description": "路边有违章停车，占用部分行车道"},
    {"risk_types": ["低净空"], "severity": "高", "description": "前方桥梁净空较低，大型车辆需注意限高"},
    {"risk_types": ["施工", "锥桶"], "severity": "高", "description": "道路施工区域，设有锥桶和围挡，需减速慢行"},
    {"risk_types": ["行人", "非机动车"], "severity": "中", "description": "路边有行人和非机动车混行，提高警惕"},
    {"risk_types": ["窄路", "停车占道"], "severity": "中", "description": "窄路段路边停车，通行宽度受限"},
]


class BaseVisionProvider(ABC):
    """视觉模型抽象基类 —— 实现新的 provider 只需继承此类"""

    @abstractmethod
    def analyze_frame(
        self,
        image_path: str,
        frame_index: int,
        timestamp_seconds: float,
        user_notes: str = "",
    ) -> VisionResult:
        """分析单帧图片，返回风险识别结果"""
        ...


class OpenAIVisionProvider(BaseVisionProvider):
    """OpenAI 兼容接口的视觉模型（支持 OpenAI / DeepSeek / 其他兼容 API）"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o",
        max_retries: int = 3,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_retries = max_retries

    def _mask_key(self) -> str:
        """返回脱敏后的 Key 前缀，用于日志"""
        if not self.api_key or len(self.api_key) < 8:
            return "***"
        return self.api_key[:7] + "***"

    def analyze_frame(
        self,
        image_path: str,
        frame_index: int,
        timestamp_seconds: float,
        user_notes: str = "",
    ) -> VisionResult:
        """调用视觉模型分析单帧"""
        image_b64 = _encode_image(image_path)

        # 构建 system prompt，如有 user_notes 则追加
        user_notes_section = ""
        if user_notes.strip():
            user_notes_section = f"""

用户特别关注以下风险类型：{user_notes.strip()}
请特别留意以上用户提到的内容，但同时也要自动识别其他明显风险，不要只限于用户关注的内容。"""

        system_prompt = f"""你是一个行车记录仪视频风险分析专家。请仔细观察图片，判断是否存在驾驶风险。

风险类型包括：
- 施工：路面施工、围挡、施工标志
- 锥桶：路锥、警示桶、隔离桩
- 限高：限高杆、限高标志、低矮桥梁/隧道
- 低净空：桥梁/隧道高度不足（注意判断是否对小车有限高影响）
- 窄路：车道变窄、道路收窄
- 闸口：收费站、检查站、出入口闸机
- 非机动车：自行车、电动车、三轮车
- 行人：行人横穿、路边行人
- 停车占道：路边违章停车占用行车道
- 货车遮挡：前方大货车遮挡视线
- 物流装卸区：货车装卸货、物流园区作业区域
- 出入口密集：多个出入口集中、车辆频繁交汇
- 路面异常：坑洼、积水、碎石、路面破损
{user_notes_section}
请严格按以下 JSON 格式返回（不要包含其他文字）：
{{
  "has_risk": true,
  "risk_types": ["施工", "锥桶"],
  "severity": "高",
  "description": "道路右侧存在施工围挡和锥桶，通行空间变窄，建议低速通过并人工复核。"
}}

判断标准：
- 高：直接威胁行车安全，需立即采取措施（如前方施工占道、行人突然横穿）
- 中：存在潜在风险，需注意观察（如路边锥桶、远处非机动车）
- 低：一般注意即可（如远处行人、路边停车）
- 如果画面正常无风险，has_risk 为 false，risk_types 为空数组，severity 为空字符串，description 为"无风险"
- 如果有风险，description 应包含场景细节和建议措施（20-60字），不要只写标签
"""

        for attempt in range(self.max_retries):
            try:
                resp = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": system_prompt},
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/jpeg;base64,{image_b64}",
                                            "detail": "low",
                                        },
                                    },
                                ],
                            }
                        ],
                        "max_tokens": 500,
                        "temperature": 0.1,
                    },
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]

                # 尝试提取 JSON
                result = self._parse_response(content)
                return VisionResult(
                    frame_index=frame_index,
                    timestamp_seconds=timestamp_seconds,
                    has_risk=result.get("has_risk", False),
                    risk_types=result.get("risk_types", []),
                    severity=result.get("severity", ""),
                    description=result.get("description", ""),
                )

            except Exception as e:
                err_msg = str(e)
                # 确保错误消息不含 Key
                clean_err = err_msg.replace(self.api_key, self._mask_key()) if self.api_key else err_msg
                if attempt == self.max_retries - 1:
                    print(f"[VISION] 帧 {frame_index} 分析失败（已重试 {self.max_retries} 次）: {clean_err[:120]}")
                    # 降级：跳过该帧，不阻塞整个任务
                    return VisionResult(
                        frame_index=frame_index,
                        timestamp_seconds=timestamp_seconds,
                        has_risk=False,
                        risk_types=[],
                        severity="",
                        description="",
                    )
                continue

        # 不应到达这里
        return VisionResult(
            frame_index=frame_index,
            timestamp_seconds=timestamp_seconds,
            has_risk=False,
        )

    def _parse_response(self, text: str) -> dict:
        """从模型回复中提取 JSON"""
        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试从 markdown 代码块中提取
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试匹配第一个 JSON 对象
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        # 解析失败，返回无风险
        return {"has_risk": False, "risk_types": [], "severity": "", "description": ""}


class MockVisionProvider(BaseVisionProvider):
    """Mock 视觉模型 —— API Key 未配置时使用，返回模拟风险检测结果

    使用确定性算法（基于 frame_index 的 hash），让相同画面产生一致结果。
    约 15% 的帧会标记为有风险。
    """

    def analyze_frame(
        self,
        image_path: str,
        frame_index: int,
        timestamp_seconds: float,
        user_notes: str = "",
    ) -> VisionResult:
        """模拟分析单帧"""
        # 使用 frame_index 的 hash 来产生确定性但看起来随机的输出
        seed = hashlib.md5(str(frame_index).encode()).hexdigest()
        seed_int = int(seed[:8], 16)

        # ~15% 概率标记为有风险（用 hash 取模确保确定性）
        has_risk = (seed_int % 100) < 15

        if not has_risk:
            return VisionResult(
                frame_index=frame_index,
                timestamp_seconds=timestamp_seconds,
                has_risk=False,
                risk_types=[],
                severity="",
                description="画面正常，未发现明显风险",
            )

        # 从场景库中选择
        scenario_idx = seed_int % len(_MOCK_RISK_SCENARIOS)
        scenario = _MOCK_RISK_SCENARIOS[scenario_idx]

        return VisionResult(
            frame_index=frame_index,
            timestamp_seconds=timestamp_seconds,
            has_risk=True,
            risk_types=scenario["risk_types"],
            severity=scenario["severity"],
            description=scenario["description"],
        )


def create_vision_provider(
    provider_type: str,
    api_key: str,
    base_url: str,
    model: str,
) -> BaseVisionProvider:
    """工厂函数 —— 根据配置创建视觉模型实例

    当 API Key 为空时自动返回 MockVisionProvider。
    支持 provider_type: openai | dashscope
    """
    if not api_key:
        print("[VISION] API Key 未配置，使用 MockVisionProvider")
        return MockVisionProvider()

    if provider_type in ("openai", "dashscope"):
        # DashScope 兼容 OpenAI Chat Completions 格式，可直接复用
        return OpenAIVisionProvider(
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
    else:
        raise ValueError(f"不支持的视觉模型 provider: {provider_type}")
