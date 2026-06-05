"""DeepSeek 文本模型 —— 用于润色风险描述和生成报告文案"""

import json
import re
from typing import Optional
import requests

from .models import RiskPoint


class DeepSeekProvider:
    """DeepSeek 文本模型接口"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.is_mock = not api_key

    def _chat(self, system_prompt: str, user_prompt: str, max_tokens: int = 2000) -> str:
        """通用对话接口（Mock 模式下返回空）"""
        if self.is_mock:
            raise RuntimeError("Mock mode: API Key 未配置")

        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.7,
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def polish_risk_descriptions(self, risks: list[dict]) -> list[dict]:
        """统一润色所有风险点的描述，使其专业、一致、有场景感

        Mock 模式下直接返回原文（保持描述不变）。
        """
        if not risks:
            return risks

        if self.is_mock:
            # Mock 模式：直接返回，但添加 [Mock] 标记
            for r in risks:
                if not r.get("description", "").startswith("[Mock]"):
                    r["description"] = f"[Mock] {r.get('description', '')}"
            return risks

        system_prompt = """你是一个专业的行车记录视频风险分析报告撰写人。
请对以下风险点描述进行润色，要求：

1. 每条描述 20-50 字，简洁专业
2. 包含具体场景和风险要素（位置、物体、动作）
3. 对于高风险点，明确指出需要采取的措施
4. 保持原文核心信息不变，补充场景细节使其更完整
5. 输出格式为 JSON 数组，每个元素包含 index 和 polished_description

直接输出 JSON 数组，不要包含其他文字。"""

        # 构建输入
        input_items = []
        for i, r in enumerate(risks):
            input_items.append({
                "index": i,
                "time": r["timestamp_display"],
                "severity": r["severity"],
                "types": r.get("risk_types", []),
                "original": r.get("description", ""),
            })

        user_prompt = json.dumps(input_items, ensure_ascii=False, indent=2)

        try:
            response = self._chat(system_prompt, user_prompt, max_tokens=2000)
            polished = self._parse_json_array(response)

            # 将润色结果合并回去
            for item in polished:
                idx = item.get("index", -1)
                if 0 <= idx < len(risks):
                    risks[idx]["description"] = item.get("polished_description", risks[idx]["description"])

            return risks
        except Exception:
            # 润色失败，返回原文
            return risks

    def generate_report_summary(self, video_info: dict, risks: list[dict]) -> str:
        """生成报告摘要（Mock 模式下返回默认摘要）"""
        if self.is_mock:
            return (
                "【Mock 模式】本报告由模拟数据分析生成，仅供功能测试参考。"
                "实际使用时请配置 API Key 以启用 AI 分析。"
                f"视频时长 {video_info.get('duration_display', '未知')}，"
                f"共发现 {len(risks)} 个模拟风险点。"
            )
        system_prompt = """你是一个行车记录视频分析报告撰写人。
请根据视频信息和风险点列表，写一段简洁的报告摘要（100-200字）。

要求：
1. 概括视频整体情况
2. 总结主要风险类型和分布
3. 给出总体安全建议
4. 语气专业但不生硬"""

        user_prompt = f"""视频信息：
- 文件名：{video_info.get('filename', '未知')}
- 时长：{video_info.get('duration_display', '未知')}
- 分辨率：{video_info.get('resolution', '未知')}

风险点列表：
{json.dumps(risks, ensure_ascii=False, indent=2)}

请生成报告摘要。"""

        try:
            return self._chat(system_prompt, user_prompt, max_tokens=500)
        except Exception as e:
            return f"视频分析摘要（生成失败: {e}）"

    def _parse_json_array(self, text: str) -> list:
        """从文本中提取 JSON 数组"""
        # 直接尝试解析
        try:
            result = json.loads(text)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

        # 从 markdown 代码块提取
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            try:
                result = json.loads(match.group(1))
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass

        # 匹配第一个 JSON 数组
        match = re.search(r"\[[\s\S]*\]", text)
        if match:
            try:
                result = json.loads(match.group(0))
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass

        return []
