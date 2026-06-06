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

        system_prompt = f"""你是一个道路运营风险分析专家，专门为无人车路线规划、道路巡检交付评估运营风险。

你的任务是：识别画面中可能影响车辆通行、路线运营的场景。
**不需要发生事故才标记**——只要存在需要关注、减速、人工复核的情况，就应该标记。

必须使用以下标准风险类型（不要使用"其他、其他"）：
强风险：
- 施工、施工围挡、锥桶、临时导流
- 限高、净空核查、低净空、桥洞、顶棚
- 闸口、门岗、护栏、隔离墩
- 窄路、通行空间受限
- 路面异常
- 大型车辆遮挡、货车占道

中风险：
- 非机动车混行、行人横穿
- 停车占道
- 商铺门口、出入口密集
- 视线遮挡、物流装卸区

如果确实无法归类，使用"其他待复核"。
{user_notes_section}
请严格按以下 JSON 格式返回：
{{
  "has_risk": true,
  "risk_types": ["施工围挡", "锥桶"],
  "severity": "高",
  "risk_score": 85,
  "description": "画面可见道路右侧有施工围挡和锥桶，通行空间疑似变窄，建议低速通过并人工复核确认。",
  "reason": "施工围挡可能压缩行车道，无人车难以自动判断导流路线。",
  "long_term_risk": true,
  "long_term_reason": "施工围挡通常持续数周，属于阶段性固定障碍。",
  "risk_attribute": "长期/阶段性风险"
}}

risk_score 评分：
强风险（80-100，优先保留）：施工围挡、锥桶、限高、低净空、闸口收窄、大型车辆遮挡、路面异常
中风险（55-80，适量保留）：停车占道、非机动车混行、窄路、出入口密集
弱风险（30-55，只在明显影响通行时标记）：普通非机动车路过、普通树木遮挡、短时干扰

risk_attribute 判断（必须填写）：
"长期/阶段性风险"：施工围挡、修路、固定闸口、固定限高、桥洞、顶棚、固定隔离设施
"临时/动态风险"：普通非机动车、行人、临时停车、临时货车、普通商铺门口车辆
"待复核"：看不清是否长期存在的停车占道、疑似低净空但无明确标识

重要规则：
1. 不要输出"其他、其他"，无法归类用"其他待复核"
2. 没有明确限高牌或数值时，用"净空核查"或"疑似低净空"，不要直接写"限高"
3. description 要谨慎：用"画面可见""疑似""可能""建议复核"，不要写"压缩约1/4""路面有碎石""需绕行"等绝对表述
4. 停车占道不要轻易判断为长期风险，除非明显固定占道
5. description 30-80字：画面现象 + 通行影响 + 复核建议
6. 如果无风险（空旷高速），返回 has_risk=false, risk_score=0
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
                has_risk = result.get("has_risk", False)
                risk_score = int(result.get("risk_score", 0))
                # 如果 has_risk=true 但 risk_score 太低，仍保留（模型可能忘记填 risk_score）
                if has_risk and risk_score <= 0:
                    risk_score = 50
                return VisionResult(
                    frame_index=frame_index,
                    timestamp_seconds=timestamp_seconds,
                    has_risk=has_risk,
                    risk_types=result.get("risk_types", []),
                    severity=result.get("severity", ""),
                    risk_score=risk_score,
                    reason=result.get("reason", ""),
                    description=result.get("description", ""),
                    long_term_risk=result.get("long_term_risk", False),
                    long_term_reason=result.get("long_term_reason", ""),
                    risk_attribute=result.get("risk_attribute", "待复核"),
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
                        risk_score=0,
                        reason="",
                        description="",
                        risk_attribute="",
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
                risk_score=0,
                reason="",
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
            risk_score=60 + (seed_int % 35),  # Mock: 60-95
            reason=f"Mock: 检测到{scenario['risk_types'][0]}场景，影响无人车通行",
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
