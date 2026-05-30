"""Raspberry Pi DeepSeek advisor for the ESP32<->Pi UART gateway.

This is where the cloud-AI brain lives in the dual-layer architecture: the
gateway hands an ESP32 `report` to this advisor, it builds a prompt, calls
DeepSeek (OpenAI-compatible), and returns a validated decision dict that the
gateway sends back to the ESP32 as `advice`. The ESP32 still runs every advice
through its own safety gate before touching an actuator.

Config via environment (key is NOT passed on argv, so the openclaw hardware
watchdog can't match it and the key never shows up in `ps`):
    SPACEFARM_AI_API_KEY   required; the DeepSeek/OpenAI key
    SPACEFARM_AI_API_URL   default https://api.deepseek.com/chat/completions
    SPACEFARM_AI_MODEL     default deepseek-v4-flash
    SPACEFARM_AI_TIMEOUT   default 20 (seconds)

The HTTP call is dependency-injected (`http_post`) so the prompt-building and
validation are unit tested with no network — see tests/test_pi_advisor.py.
This mirrors the ESP32-side prompt (esp32_firmware/ai_client.SYSTEM_PROMPT) and
the validation whitelist (tools/ai_proxy._validate_decision); keep the three in
sync. The signal whitelist MUST match uart_link.VALID_SIGNALS / serial_gateway.
"""

import json
import os

PROTOCOL_VERSION = 1

# Mirror esp32_firmware/ai_client.SYSTEM_PROMPT.
SYSTEM_PROMPT = """You are a space agriculture AI assistant for an orbital breeding platform.
Hardware: water pump + grow light relay. No nutrient/fertilizer pump exists.
Rules:
1. Stage hints: Seedling=low water; Veg=high water; Bloom=low water; Fruit=high water. Fertilizer stage info is advisory only.
2. Safety first. Avoid system overload.
3. Save water.
4. One action at a time.
5. Temperature safety: if temp >= 35C, avoid watering. Exception: soil critically dry (>= 15% below threshold). If temp <= 8C, avoid ALL actions.
6. Light: if light < plant's light_min, use "light" action.
Actions (ONLY three valid): water, light, idle
NEVER output "nutrient".
Also output:
- signals: list of advisory signals from [TEMP_HIGH, TEMP_LOW, LIGHT_LOW, HUMID_LOW, NEED_N, NEED_P, NEED_K]. Multiple signals allowed. These are broadcast visually even without physical hardware.
- breeding_observation: one sentence about this plant's growth quality at this stage.
Output strict JSON:
{"action":"water|light|idle","duration_sec":int,"reason":"short reason","signals":["SIGNAL1","SIGNAL2"],"breeding_observation":"one sentence"}"""

VALID_ACTIONS = ("water", "light", "idle")

# MUST mirror uart_link.VALID_SIGNALS / serial_gateway.VALID_SIGNALS / status_strip.
VALID_SIGNALS = (
    "WATER", "LIGHT_LOW", "LIGHT_HIGH", "TEMP_HIGH", "TEMP_LOW",
    "HUMID_LOW", "NEED_N", "NEED_P", "NEED_K",
    "SENSOR_FAIL", "OFFLINE_MODE", "BREEDING_GEN_UP",
)


def _strip_code_fence(text):
    content = text.strip()
    if content.startswith("```json"):
        content = content[7:].strip()
    if content.startswith("```"):
        content = content[3:].strip()
    if content.endswith("```"):
        content = content[:-3].strip()
    return content


def build_messages(report, plant_info=None):
    """Build OpenAI-style messages from an ESP32 report dict.

    `plant_info` (optional, from plants.json) supplies thresholds; when absent
    the prompt falls back to the raw sensor values in the report.
    """
    plant = report.get("plant", "")
    soil = report.get("soil", 0)
    light = report.get("light", 0)
    temp = report.get("temp", 0)
    hum = report.get("hum", 0)
    day = report.get("day", 0)
    stage = report.get("stage", "")

    info = plant_info or {}
    soil_threshold = info.get("soil_threshold", 30)
    light_min = info.get("light_min", 30)
    light_opt = info.get("light_opt", 50)
    light_hours = info.get("light_hours", [6, 8])

    user_content = (
        "Data:\n"
        "Plant: {plant}\n"
        "Soil: {soil}% (thr: {soil_threshold}%)\n"
        "Light: {light}% (min: {light_min}%, opt: {light_opt}%)\n"
        "Target sun: {lo}-{hi}h\n"
        "Temp: {temp}C\n"
        "Hum: {hum}%\n"
        "Stage: {stage} (Day {day})\n\n"
        "Light rules:\n"
        "- If light < min, use \"light\" action with appropriate duration.\n"
        "- Low light means less evaporation, so avoid unnecessary watering.\n\n"
        "Decision:"
    ).format(
        plant=plant, soil=soil, soil_threshold=soil_threshold,
        light=light, light_min=light_min, light_opt=light_opt,
        lo=light_hours[0] if light_hours else 6,
        hi=light_hours[1] if len(light_hours) > 1 else 8,
        temp=temp, hum=hum, stage=stage, day=day,
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def validate_decision(decision):
    """Normalize a raw model decision into the gateway advice shape, or raise."""
    action = decision.get("action")
    duration = decision.get("duration_sec", 0)
    # 单泵架构：legacy nutrient action 静默归一到 idle
    if action == "nutrient":
        action = "idle"
        duration = 0
    if action not in VALID_ACTIONS:
        raise ValueError("invalid action: %r" % (action,))
    try:
        duration = int(duration)
    except (TypeError, ValueError):
        raise ValueError("duration_sec must be an int")
    duration = max(0, duration)
    if action == "idle":
        duration = 0
    signals = [s for s in decision.get("signals", []) if isinstance(s, str) and s in VALID_SIGNALS]
    return {
        "primary": action,
        "duration": duration,
        "signals": signals,
        "note": str(decision.get("reason", ""))[:120],
        "breeding_observation": str(decision.get("breeding_observation", ""))[:200],
    }


def _default_http_post(url, data, headers, timeout):
    from urllib.request import Request, urlopen
    req = Request(url, data=data, headers=headers, method="POST")
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


class DeepSeekAdvisor:
    """Calls DeepSeek and returns gateway-ready advice, or None on any failure.

    `http_post(url, data_bytes, headers, timeout) -> response_text` is injected
    so tests can run without a network.
    """

    def __init__(self, api_key=None, api_url=None, model=None, timeout=None,
                 http_post=None):
        self.api_key = api_key if api_key is not None else os.environ.get("SPACEFARM_AI_API_KEY", "")
        self.api_url = api_url or os.environ.get(
            "SPACEFARM_AI_API_URL", "https://api.deepseek.com/chat/completions")
        self.model = model or os.environ.get("SPACEFARM_AI_MODEL", "deepseek-v4-flash")
        self.timeout = int(timeout if timeout is not None
                           else os.environ.get("SPACEFARM_AI_TIMEOUT", "20"))
        self._http_post = http_post or _default_http_post

    def configured(self):
        key = self.api_key or ""
        return bool(key) and "YOUR_" not in key and "API_KEY_HERE" not in key and "你的" not in key

    def advise(self, report, plant_info=None):
        """Return advice dict (primary/duration/signals/note/...) or None."""
        if not self.configured():
            print("[Advisor] SPACEFARM_AI_API_KEY not configured; skipping AI")
            return None
        payload = {
            "model": self.model,
            "messages": build_messages(report, plant_info),
            "temperature": 0.3,
            "max_tokens": 1024,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": "Bearer %s" % self.api_key,
            "Content-Type": "application/json",
        }
        try:
            raw = self._http_post(self.api_url, body, headers, self.timeout)
            result = json.loads(raw)
            content = result["choices"][0]["message"].get("content", "")
            decision = json.loads(_strip_code_fence(content))
            advice = validate_decision(decision)
            print("[Advisor] DeepSeek:", advice.get("primary"), advice.get("duration"))
            return advice
        except Exception as e:  # network / parse / validation: fall back, never crash
            print("[Advisor] DeepSeek failed:", e)
            return None


def load_plant_info(plant_name, plants_path):
    """Best-effort load of one plant's params from plants.json; None on miss."""
    try:
        with open(plants_path, "r", encoding="utf-8") as f:
            db = json.load(f)
        return db.get(plant_name) or db.get("生菜")
    except Exception:
        return None
