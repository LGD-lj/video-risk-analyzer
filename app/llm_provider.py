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

    def _mask_key(self) -> str:
        """返回脱敏后的 Key 前缀，用于日志"""
        if not self.api_key or len(self.api_key) < 8:
            return "***"
        return self.api_key[:7] + "***"

    def _chat(self, system_prompt: str, user_prompt: str, max_tokens: int = 2000) -> str:
        """通用对话接口（Mock 模式下抛出异常，由调用方捕获）"""
        if self.is_mock:
            raise RuntimeError("Mock mode: DeepSeek API Key 未配置")

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

        system_prompt = """你是一个道路运营风险分析报告撰写人，负责整理无人车路线巡检的风险点。

任务：
1. **合并相邻同场景风险**：10-20秒内同一连续场景（如施工围挡+闸口收窄+大型车辆遮挡合并为一个综合风险点，描述包含多个风险要素）
2. **不要输出"其他、其他"**：风险类型必须使用标准类型（施工围挡、锥桶、限高、净空核查、桥洞、闸口、窄路、非机动车混行、停车占道、视线遮挡等），无法归类写"其他待复核"
3. **润色描述要谨慎**：用"画面可见""疑似""可能""建议复核"，不要写"压缩约1/4""路面有碎石""需绕行""一定""必然"
4. **没有明确限高牌不要写限高**：写"净空核查"或"疑似低净空"
5. **保留风险分数最高的版本**
6. **停车占道不要轻易判断为长期风险**
7. 输出格式为 JSON 数组，每个元素包含 index 和 polished_description

重要：只润色和合并，**不要大量删除风险点**。
强风险（施工、闸口、限高、路面异常）必须保留。
普通风险（非机动车、停车占道、树木遮挡）保留代表性样例即可。

直接输出 JSON 数组，不要包含其他文字。"""

        # 构建输入
        input_items = []
        for i, r in enumerate(risks):
            input_items.append({
                "index": i,
                "time": r["timestamp_display"],
                "severity": r["severity"],
                "risk_score": r.get("risk_score", 0),
                "types": r.get("risk_types", []),
                "original": r.get("description", ""),
                "reason": r.get("reason", ""),
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
        except Exception as e:
            err_msg = str(e)
            clean_err = err_msg.replace(self.api_key, self._mask_key()) if self.api_key else err_msg
            print(f"[LLM] 风险描述润色失败（将使用原文）: {clean_err[:120]}")
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
