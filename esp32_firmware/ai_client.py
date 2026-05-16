"""
AI 决策客户端 - 调用云端 AI API 获取养护决策
支持 DeepSeek / OpenAI 兼容 API（当前配置: DeepSeek deepseek-chat）
"""

import ujson
import time
import config


# System Prompt
SYSTEM_PROMPT = """You are a space agriculture AI.
Rules:
1. Stage needs: Seedling=low water/fert; Veg=high water/N; Bloom=low water, high P/K; Fruit=high water/K.
2. Safety first. Avoid system overload.
3. Save water.
4. One action at a time.
Actions:
- water: if soil dry
- nutrient: if fert needed
- idle: if normal
Fertilizers: N, P, K, PK, NK.
Output strict JSON:
{"action":"water|nutrient|idle","duration_sec":int,"reason":"short reason"}"""

def _build_payload(plant_type, soil_moisture, temp, humidity, plant_info, days_since_planting=0, growth_stage=None):
    """Build API payload"""
    
    stage_info = ""
    if growth_stage:
        fert = growth_stage.get("fert", "NPK")
        water_need = growth_stage.get("water_need", "normal")
        
        stage_info = f"""
Stage: {growth_stage.get('stage', '')} (Day {days_since_planting})
Fert: {fert}, Water: {water_need}"""
    
    user_content = f"""Data:
Plant: {plant_type}
Soil: {soil_moisture}% (thr: {plant_info['soil_threshold']}%)
Temp: {temp}C
Hum: {humidity}%{stage_info}

Decision:"""
    
    return {
        "model": config.AI_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.3,
        "max_tokens": 1024,
    }


def query_decision(plant_type, soil_moisture, temperature, humidity, plant_info, days_since_planting=0, growth_stage=None):
    """
    向 AI 查询养护决策
    返回: dict 或 None（失败时）
    """
    proxy_url = getattr(config, "AI_PROXY_URL", "")
    if not proxy_url and (not config.AI_API_KEY or "你的" in config.AI_API_KEY):
        print("[AI] API key not configured, skipping cloud AI")
        return None
    
    url = proxy_url if proxy_url else config.AI_API_URL
    headers = {"Content-Type": "application/json"}
    if not proxy_url:
        headers["Authorization"] = f"Bearer {config.AI_API_KEY}"
    elif getattr(config, "AI_PROXY_TOKEN", ""):
        headers["X-Proxy-Token"] = config.AI_PROXY_TOKEN
    
    payload = _build_payload(plant_type, soil_moisture, temperature, humidity, plant_info, days_since_planting, growth_stage)
    
    response = None
    try:
        import gc
        # Serialize to JSON string early and encode to bytes for correct Content-Length
        payload_bytes = ujson.dumps(payload).encode('utf-8')
        # Delete the large dictionary and user_content string
        del payload
        # Force garbage collection to free RAM for the TLS handshake
        gc.collect()
        import urequests
        
        if proxy_url:
            print(f"[AI] Sending proxy request... plant={plant_type} soil={soil_moisture}%")
        else:
            print(f"[AI] Sending request... plant={plant_type} soil={soil_moisture}%")
        
        response = urequests.post(
            url,
            data=payload_bytes,
            headers=headers,
            timeout=config.AI_TIMEOUT
        )
        
        # 检查 HTTP 状态码
        status_code = response.status_code
        if status_code != 200:
            body = response.text[:200] if hasattr(response, 'text') else ''
            print(f"[AI] HTTP error: {status_code}, Response: {body}")
            return None
        
        # 安全检查：响应体不应超过 8KB
        resp_text = response.text
        if len(resp_text) > 8192:
            print(f"[AI] Response too large ({len(resp_text)} bytes), dropping")
            return None
        
        # 解析 JSON 响应（MicroPython urequests.Response 无 .json() 方法，直接用 ujson.loads）
        result = ujson.loads(resp_text)

        if 'action' in result and 'duration_sec' in result:
            print(f"[AI] Decision success: {result}")
            return result
        
        # 解析响应
        if 'choices' in result and len(result['choices']) > 0:
            content = result['choices'][0]['message']['content'].strip()
            
            # 尝试解析 JSON
            try:
                # 提取 JSON（可能在 markdown 代码块中）
                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                
                decision = ujson.loads(content.strip())
                
                # 验证必要字段
                if 'action' in decision and 'duration_sec' in decision:
                    print(f"[AI] Decision success: {decision}")
                    return decision
                else:
                    print(f"[AI] Invalid response format: {decision}")
                    
            except Exception as e:
                print(f"[AI] JSON parse failed: {e}")
                print(f"[AI] Raw response: {content}")
        
        print(f"[AI] API response exception: {result}")
        return None
        
    except Exception as e:
        print(f"[AI] Request failed: {e}")
        return None
    finally:
        if response is not None:
            try:
                response.close()
            except:
                pass


def test_api():
    """测试 API 连接"""
    if not config.AI_API_KEY or "你的" in config.AI_API_KEY:
        print("[Test] API key not configured")
        return False
    
    plant_info = config.get_plant_info("生菜")
    test_stage = config.get_growth_stage(plant_info, 15)  # 模拟第15天
    
    test_data = {
        "plant_type": "生菜",
        "soil_moisture": 25,
        "temperature": 24.5,
        "humidity": 65,
        "plant_info": plant_info,
        "days_since_planting": 15,
        "growth_stage": test_stage
    }
    
    print("[Test] Sending test request (Lettuce day 15)...")
    result = query_decision(**test_data)
    
    if result:
        print(f"[Test] Success! Decision: {result}")
        return True
    else:
        print("[Test] Failed")
        return False


def format_decision_log(decision, soil, temp, plant):
    """格式化决策日志"""
    action_names = {
        "water": "浇水",
        "nutrient": "营养液",
        "idle": "待机"
    }
    
    action = decision.get('action', 'unknown')
    duration = decision.get('duration_sec', 0)
    reason = decision.get('reason', '')
    
    return (
        f"[{time.localtime()[1]:02d}/{time.localtime()[2]:02d} {time.localtime()[3]:02d}:{time.localtime()[4]:02d}] "
        f"{plant} | 土:{soil}% T:{temp}C | "
        f"决策:{action_names.get(action, action)} {duration}s | {reason}"
    )


def parse_decision_from_text(text):
    """
    从纯文本中解析决策（备用方法，当JSON解析失败时）
    """
    text = text.lower()
    
    # 尝试匹配动作关键词
    action = "idle"
    duration = 0
    
    if "water" in text or "浇水" in text:
        action = "water"
        duration = 8
    elif "nutrient" in text or "营养" in text:
        action = "nutrient"
        duration = 5
    # 尝试提取时长（用简单字符串操作替代 re，避免 MicroPython re 模块不可用的风险）
    idx = text.find("duration")
    if idx >= 0:
        sub = text[idx:]
        num_start = None
        num_end = None
        for i, ch in enumerate(sub):
            if ch.isdigit():
                if num_start is None:
                    num_start = i
                num_end = i + 1
            elif num_start is not None:
                break
        if num_start is not None and num_end is not None:
            duration = int(sub[num_start:num_end])
    
    return {
        "action": action,
        "duration_sec": duration,
        "reason": "从文本解析"
    }
