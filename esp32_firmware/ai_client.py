"""
AI 决策客户端 - 调用云端 AI API 获取养护决策
支持 DeepSeek / OpenAI 兼容 API（当前配置: DeepSeek deepseek-chat）
"""

import urequests
import ujson
import time
import config


# 系统提示词
SYSTEM_PROMPT = """你是一个专业的太空农业种植助手。

背景：
- 太空种植舱使用水培系统，资源有限，必须高效管理
- 你的决策直接影响植物生存和宇航员食物供给
- 系统需要根据植物生长阶段动态调整养护策略

决策原则：
1. 生长阶段优先：不同阶段需求不同（苗期少水少肥、生长期多水氮肥、开花期减水补磷钾、结果期多水钾肥）
2. 安全第一：任何决策都不能导致系统过载或损坏
3. 资源高效：太空每一滴水都很珍贵，精准灌溉
4. 预防为主：发现趋势问题提前处理
5. 简洁执行：每次只执行一个主要动作

动作类型：
- water: 浇水（土壤干燥时）
- nutrient: 补充营养液（需要施肥时，AI应结合生长阶段建议肥料类型）
- ventilate: 换气（CO2浓度过高时）
- idle: 待机（所有指标正常时）

肥料类型说明（含在reason中告知用户）：
- N=氮肥（促叶生长，苗期/营养生长期使用）
- P=磷肥（促根促花，开花期使用）
- K=钾肥（膨果增甜，结果期使用）
- PK=磷钾肥（开花期控旺促花）
- NK=氮钾肥（结果期兼顾生长和产量）

输入数据包含：
- 当前植物类型和种植天数
- 当前生长阶段（seedling/vegetative/flowering/fruiting/harvesting）
- 该阶段推荐肥料类型和需水强度
- 土壤湿度、CO2浓度、温湿度等实时传感器数据
- 该植物的阈值参数

输出格式（严格JSON，不要其他内容）：
{
  "action": "water|nutrient|ventilate|idle",
  "duration_sec": 数字（动作执行时长，idle时为0）,
  "reason": "判断依据（含肥料类型建议，15字以内）"
}"""


def _build_payload(plant_type, soil_moisture, co2, temp, humidity, plant_info, days_since_planting=0, growth_stage=None):
    """构建 API 请求 payload"""
    
    # 生长阶段信息
    stage_info = ""
    if growth_stage:
        stage_names = {
            "seedling": "苗期",
            "vegetative": "营养生长期",
            "flowering": "开花期",
            "fruiting": "结果期",
            "harvesting": "采收期",
        }
        stage_cn = stage_names.get(growth_stage.get("stage", ""), growth_stage.get("stage", ""))
        fert = growth_stage.get("fert", "NPK")
        water_need = growth_stage.get("water_need", "normal")
        note = growth_stage.get("note", "")
        
        stage_info = f"""
生长阶段信息：
- 种植天数：第{days_since_planting}天
- 当前阶段：{stage_cn}
- 推荐肥料：{fert}
- 需水强度：{water_need}
- 养护要点：{note}"""
    
    user_content = f"""传感器数据：
- 植物类型：{plant_type}
- 土壤湿度：{soil_moisture}%（阈值：{plant_info['soil_threshold']}%）
- CO2浓度：{co2}ppm（阈值：{plant_info['co2_threshold']}ppm）
- 环境温度：{temp}°C
- 环境湿度：{humidity}%{stage_info}

请做出决策。"""
    
    payload = {
        "model": config.AI_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.3,
        "max_tokens": 120,
    }
    
    return payload


def query_decision(plant_type, soil_moisture, co2, temperature, humidity, plant_info, days_since_planting=0, growth_stage=None):
    """
    向 AI 查询养护决策
    返回: dict 或 None（失败时）
    """
    if not config.AI_API_KEY or "你的" in config.AI_API_KEY:
        print("[AI] API密钥未配置，跳过云端AI")
        return None
    
    url = config.AI_API_URL
    headers = {
        "Authorization": f"Bearer {config.AI_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = _build_payload(plant_type, soil_moisture, co2, temperature, humidity, plant_info, days_since_planting, growth_stage)
    
    response = None
    try:
        print(f"[AI] 发送请求... plant={plant_type} soil={soil_moisture}% co2={co2}ppm")
        
        response = urequests.post(
            url,
            json=payload,
            headers=headers,
            timeout=config.AI_TIMEOUT
        )
        
        # 检查 HTTP 状态码
        status_code = response.status_code
        if status_code != 200:
            body = response.text[:200] if hasattr(response, 'text') else ''
            print(f"[AI] HTTP 错误: {status_code}, 响应: {body}")
            return None
        
        # 解析 JSON 响应（MicroPython urequests.Response 无 .json() 方法，直接用 ujson.loads）
        result = ujson.loads(response.text)
        
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
                    print(f"[AI] 决策成功: {decision}")
                    return decision
                else:
                    print(f"[AI] 响应格式错误: {decision}")
                    
            except Exception as e:
                print(f"[AI] JSON解析失败: {e}")
                print(f"[AI] 原始响应: {content}")
        
        print(f"[AI] API响应异常: {result}")
        return None
        
    except Exception as e:
        print(f"[AI] 请求失败: {e}")
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
        print("[测试] API密钥未配置")
        return False
    
    plant_info = config.get_plant_info("生菜")
    test_stage = config.get_growth_stage(plant_info, 15)  # 模拟第15天
    
    test_data = {
        "plant_type": "生菜",
        "soil_moisture": 25,
        "co2": 1200,
        "temperature": 24.5,
        "humidity": 65,
        "plant_info": plant_info,
        "days_since_planting": 15,
        "growth_stage": test_stage
    }
    
    print("[测试] 发送测试请求（生菜第15天，营养生长期）...")
    result = query_decision(**test_data)
    
    if result:
        print(f"[测试] 成功! 决策: {result}")
        return True
    else:
        print("[测试] 失败")
        return False


def format_decision_log(decision, soil, co2, temp, plant):
    """格式化决策日志"""
    action_names = {
        "water": "浇水",
        "nutrient": "营养液",
        "ventilate": "换气",
        "idle": "待机"
    }
    
    action = decision.get('action', 'unknown')
    duration = decision.get('duration_sec', 0)
    reason = decision.get('reason', '')
    
    return (
        f"[{time.localtime()[1]:02d}/{time.localtime()[2]:02d} {time.localtime()[3]:02d}:{time.localtime()[4]:02d}] "
        f"{plant} | 土:{soil}% CO2:{co2}ppm | "
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
    elif "ventilate" in text or "换气" in text or "通风" in text:
        action = "ventilate"
        duration = 30
    
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
