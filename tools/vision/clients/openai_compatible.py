"""OpenAI-compatible multimodal HTTP client with strict output validation."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

from ..schemas import validate_capture_analysis


SYSTEM_PROMPT = """你是 AI 开放式智能花盆的单株植物视觉分析助手。输入只有一张当前植物的全景图，请始终围绕这一株植物进行分析。
请围绕这一株植物进行综合观察：植物身份匹配、生长阶段、整体长势、叶片颜色、可见特征、可能问题和温和的养护建议。只能描述图片可见证据，不得把不确定情况写成事实。
图像结论只用于辅助养护展示，绝不能直接给出水泵、灯光或其他执行器控制指令；执行器仍由传感器安全规则决定。
当植物身份或状态不确定时使用 unknown、降低 certainty，并设置 needs_human_review=true。
只返回 JSON。根对象字段为 capture_id、observations，observations 必须且只能有一项；该项包含 pot_id 和 analysis。
analysis 包含 plant、plant_match、certainty、visible_stage、vigor、leaf_color、visible_findings、possible_issues、care_suggestions、comprehensive_observation、needs_human_review。"""


def _default_post(url: str, headers: Mapping[str, str], body: bytes, timeout: int) -> bytes:
    request = Request(url, data=body, headers=dict(headers), method="POST")
    with urlopen(request, timeout=timeout) as response:  # nosec B310 - configured API endpoint
        return response.read()


class OpenAICompatibleVisionClient:
    def __init__(self, *, api_url: str, api_key: str, model: str,
                 timeout_sec: int = 30, max_image_bytes: int = 500_000,
                 post: Callable[[str, Mapping[str, str], bytes, int], bytes] = _default_post):
        if not api_url.startswith(("https://", "http://127.0.0.1", "http://localhost")):
            raise ValueError("api_url must use HTTPS (or localhost for development)")
        self.api_url = api_url.rstrip("/")
        if self.api_url.endswith("/v1"):
            self.api_url += "/chat/completions"
        self.api_key = api_key
        self.model = model
        self.timeout_sec = timeout_sec
        self.max_image_bytes = max_image_bytes
        self.post = post

    def analyze(self, capture: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
        context = capture.get("context", {})
        plant_info = context.get("plant_info", {}) if isinstance(context, Mapping) else {}
        content: list[dict[str, Any]] = [{
            "type": "text",
            "text": json.dumps({
                "capture_id": capture["capture_id"],
                "cycle_id": capture.get("cycle_id"),
                "plant": plant_info.get("plant"),
                "day": context.get("day"),
                "stage": context.get("stage"),
                "target": {"pot_id": capture["observations"][0].get("pot_id", "PLANT")},
            }, ensure_ascii=False),
        }]
        total_bytes = 0
        for item in capture["observations"]:
            path = Path(item["image_path"])
            raw = path.read_bytes()
            if len(raw) > self.max_image_bytes:
                raise ValueError(f"image exceeds API size limit: {path.name}")
            total_bytes += len(raw)
            content.append({"type": "text", "text": "单株植物全景图"})
            content.append({
                "type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")},
            })
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        raw_response = self.post(
            self.api_url,
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            body,
            self.timeout_sec,
        )
        envelope = json.loads(raw_response.decode("utf-8"))
        answer = envelope["choices"][0]["message"]["content"]
        if isinstance(answer, list):
            answer = "".join(part.get("text", "") for part in answer if isinstance(part, Mapping))
        answer = str(answer).strip()
        if answer.startswith("```"):
            lines = answer.splitlines()
            answer = "\n".join(lines[1:-1])
        data = json.loads(answer)
        data["capture_id"] = capture["capture_id"]
        data["model"] = {"provider_model": self.model}
        expected = {item["pot_id"] for item in capture["observations"]}
        result = validate_capture_analysis(data, expected)
        source = {item["pot_id"]: item for item in capture["observations"]}
        for observation in result["observations"]:
            trusted = source[observation["pot_id"]]
            observation["material_id"] = str(trusted.get("material_id", ""))[:64]
            observation["is_control"] = bool(trusted.get("is_control"))
            observation["roi_id"] = str(trusted.get("roi_id", trusted["pot_id"]))[:32]
        return result, total_bytes
