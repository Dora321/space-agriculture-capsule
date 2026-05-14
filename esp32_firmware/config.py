"""
配置文件 - 太空农业种植舱
修改此文件以适配你的硬件和网络环境
"""

import sys


def _load_secret(key, default=""):
    """从 /secrets/ 目录安全加载密钥（避免明文存储）"""
    try:
        with open(f"/secrets/{key}", "r") as f:
            return f.read().strip()
    except OSError:
        # 文件不存在时返回默认值（正常情况，首次使用时密钥文件尚未创建）
        return default


# ============ WiFi 配置 ============
WIFI_SSID = "你的WiFi名称"
WIFI_PASSWORD = _load_secret("wifi_pass", "你的WiFi密码")

# ============ AI API 配置 ============
# DeepSeek 官方 API（OpenAI 兼容格式）
# 注册地址: https://platform.deepseek.com/
# 官方定价: deepseek-chat ¥1/百万tokens（非常便宜）
AI_API_URL = "https://api.deepseek.com/chat/completions"
AI_API_KEY = _load_secret("api_key", "你的DeepSeek API密钥")
AI_MODEL = "deepseek-chat"   # 可选: deepseek-chat / deepseek-reasoner
AI_TIMEOUT = 5  # API超时时间（秒）

# ============ 系统参数 ============
READ_INTERVAL = 300       # 传感器读取间隔（秒），默认5分钟
MIN_ACTION_INTERVAL = 60  # 最小动作间隔（秒），防止频繁动作
MAX_ACTIONS_PER_HOUR = 12  # 每小时最大动作次数
MAX_ERRORS = 10           # 最大连续错误次数，超过后重启
CO2_WARMUP_TIME = 30      # CO2传感器预热时间（秒）

# ============ 种植日期 ============
# 格式: (年, 月, 日)，系统据此计算种植天数和生长阶段
# 每次重新种植时更新此值
PLANTING_DATE = (2026, 5, 1)  # 例: 2026年5月1日播种

# ============ GPIO 引脚定义 ============
# 传感器
SOIL_ADC_PIN = 34         # 土壤湿度 ADC 引脚

# CO2传感器 UART
CO2_UART_NUM = 1
CO2_UART_TX = 16
CO2_UART_RX = 17
CO2_UART_BAUD = 9600

# DHT22 温湿度
DHT22_PIN = 4

# 继电器（低电平触发）
RELAY_WATER_PIN = 5       # 水泵继电器
RELAY_NUTRIENT_PIN = 18   # 营养液泵继电器
RELAY_FAN_PIN = 19        # 风扇继电器

# 拨码开关（3位拨码开关，支持 8 种组合）
# bit0~bit2 对应 DIP 开关的第1~第3位
# 使用 PULL_UP 输入：开关 OFF(断开)→1→取反为0, ON(接地)→0→取反为1
DIP_SWITCH_PINS = [13, 12, 14]

# OLED 显示屏 (I2C)
OLED_SDA_PIN = 21
OLED_SCL_PIN = 22
OLED_I2C_FREQ = 400000

# 状态LED
LED_RED_PIN = 27
LED_GREEN_PIN = 26

# ============ 传感器参数 ============
# 土壤湿度 ADC 参数
SOIL_ADC_MAX = 4095       # 干土 ADC 值
SOIL_ADC_MIN = 1500       # 湿土 ADC 值

# CO2 参数
CO2_NORMAL = 420          # 户外 CO2 基线值
CO2_DANGER_HIGH = 2000    # CO2 危险上限

# ============ 执行器参数 ============
PUMP_WATER_DEFAULT_SEC = 8     # 默认浇水时长（秒）
PUMP_NUTRIENT_DEFAULT_SEC = 5 # 默认营养液时长（秒）
FAN_DEFAULT_SEC = 30          # 默认换气时长（秒）
PUMP_MAX_RUN_SEC = 60          # 单次最大运行时长（安全限制）

# ============ 植物数据库 ============
# 每个植物的养护参数
# soil_threshold: 土壤湿度阈值（低于此值需要浇水）
# co2_threshold: CO2 阈值（高于此值需要换气）
# water_sec: 浇水时长（秒）
# nutrient_sec: 营养液时长（秒）
# ventilate_sec: 换气时长（秒）
# nutrient_interval: 营养液补充间隔（秒），默认每3天

PLANT_DB = {
    # ============ 预定义植物 (0-7) ============
    # growth_stages: 生长阶段定义
    #   - days: (起始天, 结束天)
    #   - stage: 阶段名称 (seedling=苗期, vegetative=营养生长期, flowering=开花期, fruiting=结果期, harvesting=采收期)
    #   - fert: 推荐肥料类型 (N=氮肥, P=磷肥, K=钾肥, PK=磷钾肥, NK=氮钾肥, NPK=复合肥)
    #   - water_need: 需水强度 (light=少量, normal=正常, heavy=大量, reduce=减少)
    #   - note: 养护要点

    # 叶菜类（需水多、周期短、水培首选）
    "生菜": {
        "soil_threshold": 30, "co2_threshold": 1000,
        "water_sec": 8, "nutrient_sec": 5, "ventilate_sec": 30,
        "nutrient_interval": 259200,
        "growth_stages": [
            {"days": (0, 7),   "stage": "seedling",   "fert": "N",   "water_need": "light",  "note": "少浇水保根"},
            {"days": (8, 25),  "stage": "vegetative",  "fert": "N",   "water_need": "normal", "note": "氮肥促叶"},
            {"days": (26, 40), "stage": "harvesting",  "fert": "NPK", "water_need": "normal", "note": "可陆续采收"},
        ],
    },
    "小白菜": {
        "soil_threshold": 28, "co2_threshold": 1000,
        "water_sec": 10, "nutrient_sec": 7, "ventilate_sec": 35,
        "nutrient_interval": 172800,
        "growth_stages": [
            {"days": (0, 5),   "stage": "seedling",   "fert": "N",   "water_need": "light",  "note": "保持湿润"},
            {"days": (6, 20),  "stage": "vegetative",  "fert": "N",   "water_need": "heavy",  "note": "快速生长期"},
            {"days": (21, 30), "stage": "harvesting",  "fert": "NPK", "water_need": "normal", "note": "可采收"},
        ],
    },
    "菠菜": {
        "soil_threshold": 32, "co2_threshold": 900,
        "water_sec": 9, "nutrient_sec": 6, "ventilate_sec": 30,
        "nutrient_interval": 259200,
        "growth_stages": [
            {"days": (0, 7),   "stage": "seedling",   "fert": "N",   "water_need": "light",  "note": "出苗期忌积水"},
            {"days": (8, 30),  "stage": "vegetative",  "fert": "N",   "water_need": "normal", "note": "氮肥催长"},
            {"days": (31, 50), "stage": "harvesting",  "fert": "NPK", "water_need": "normal", "note": "可分批采摘"},
        ],
    },
    "韭菜": {
        "soil_threshold": 30, "co2_threshold": 950,
        "water_sec": 8, "nutrient_sec": 6, "ventilate_sec": 30,
        "nutrient_interval": 259200,
        "growth_stages": [
            {"days": (0, 10),  "stage": "seedling",   "fert": "N",   "water_need": "light",  "note": "养根期少动"},
            {"days": (11, 30), "stage": "vegetative",  "fert": "N",   "water_need": "normal", "note": "割后追氮肥"},
            {"days": (31, 999),"stage": "harvesting",  "fert": "NPK", "water_need": "normal", "note": "割一茬长一茬"},
        ],
    },
    # 果菜类（需光多、周期长）
    "番茄": {
        "soil_threshold": 35, "co2_threshold": 800,
        "water_sec": 12, "nutrient_sec": 8, "ventilate_sec": 45,
        "nutrient_interval": 172800,
        "growth_stages": [
            {"days": (0, 14),  "stage": "seedling",   "fert": "N",   "water_need": "light",  "note": "控水蹲苗"},
            {"days": (15, 45), "stage": "vegetative",  "fert": "N",   "water_need": "normal", "note": "促枝叶生长"},
            {"days": (46, 65), "stage": "flowering",   "fert": "PK",  "water_need": "reduce", "note": "减水保花补磷钾"},
            {"days": (66, 120),"stage": "fruiting",    "fert": "K",   "water_need": "heavy",  "note": "钾肥膨果增甜"},
        ],
    },
    "辣椒": {
        "soil_threshold": 40, "co2_threshold": 700,
        "water_sec": 10, "nutrient_sec": 10, "ventilate_sec": 40,
        "nutrient_interval": 259200,
        "growth_stages": [
            {"days": (0, 14),  "stage": "seedling",   "fert": "N",   "water_need": "light",  "note": "忌低温积水"},
            {"days": (15, 50), "stage": "vegetative",  "fert": "N",   "water_need": "normal", "note": "氮肥壮棵"},
            {"days": (51, 70), "stage": "flowering",   "fert": "PK",  "water_need": "reduce", "note": "控水促花"},
            {"days": (71, 150),"stage": "fruiting",    "fert": "K",   "water_need": "normal", "note": "钾肥增辣增色"},
        ],
    },
    "黄瓜": {
        "soil_threshold": 38, "co2_threshold": 750,
        "water_sec": 15, "nutrient_sec": 8, "ventilate_sec": 50,
        "nutrient_interval": 172800,
        "growth_stages": [
            {"days": (0, 7),   "stage": "seedling",   "fert": "N",   "water_need": "light",  "note": "防徒长"},
            {"days": (8, 30),  "stage": "vegetative",  "fert": "N",   "water_need": "normal", "note": "搭架引蔓"},
            {"days": (31, 45), "stage": "flowering",   "fert": "PK",  "water_need": "normal", "note": "补磷钾促雌花"},
            {"days": (46, 90), "stage": "fruiting",    "fert": "NK",  "water_need": "heavy",  "note": "需大量水钾肥"},
        ],
    },
    "茄子": {
        "soil_threshold": 40, "co2_threshold": 750,
        "water_sec": 12, "nutrient_sec": 10, "ventilate_sec": 40,
        "nutrient_interval": 259200,
        "growth_stages": [
            {"days": (0, 14),  "stage": "seedling",   "fert": "N",   "water_need": "light",  "note": "保温促根"},
            {"days": (15, 45), "stage": "vegetative",  "fert": "N",   "water_need": "normal", "note": "壮棵期"},
            {"days": (46, 65), "stage": "flowering",   "fert": "PK",  "water_need": "reduce", "note": "门茄坐住后追肥"},
            {"days": (66, 130),"stage": "fruiting",    "fert": "NK",  "water_need": "heavy",  "note": "对茄四母斗膨大"},
        ],
    },
    # 瓜豆类
    "豆角": {
        "soil_threshold": 35, "co2_threshold": 800,
        "water_sec": 10, "nutrient_sec": 8, "ventilate_sec": 35,
        "nutrient_interval": 259200,
        "growth_stages": [
            {"days": (0, 7),   "stage": "seedling",   "fert": "N",   "water_need": "light",  "note": "出苗期少水"},
            {"days": (8, 35),  "stage": "vegetative",  "fert": "N",   "water_need": "normal", "note": "抽蔓搭架"},
            {"days": (36, 50), "stage": "flowering",   "fert": "PK",  "water_need": "reduce", "note": "控水防落花"},
            {"days": (51, 90), "stage": "fruiting",    "fert": "K",   "water_need": "normal", "note": "结荚期追钾"},
        ],
    },
    "西葫芦": {
        "soil_threshold": 38, "co2_threshold": 800,
        "water_sec": 12, "nutrient_sec": 8, "ventilate_sec": 40,
        "nutrient_interval": 259200,
        "growth_stages": [
            {"days": (0, 7),   "stage": "seedling",   "fert": "N",   "water_need": "light",  "note": "促根控水"},
            {"days": (8, 25),  "stage": "vegetative",  "fert": "N",   "water_need": "normal", "note": "展叶期"},
            {"days": (26, 40), "stage": "flowering",   "fert": "PK",  "water_need": "reduce", "note": "人工授粉"},
            {"days": (41, 80), "stage": "fruiting",    "fert": "NK",  "water_need": "heavy",  "note": "膨瓜期多水肥"},
        ],
    },
    # 根茎/葱蒜类
    "萝卜": {
        "soil_threshold": 35, "co2_threshold": 800,
        "water_sec": 10, "nutrient_sec": 8, "ventilate_sec": 35,
        "nutrient_interval": 259200,
        "growth_stages": [
            {"days": (0, 7),   "stage": "seedling",   "fert": "N",   "water_need": "light",  "note": "间苗期"},
            {"days": (8, 35),  "stage": "vegetative",  "fert": "N",   "water_need": "normal", "note": "叶丛生长"},
            {"days": (36, 70), "stage": "fruiting",    "fert": "PK",  "water_need": "heavy",  "note": "肉质根膨大需钾"},
        ],
    },
    "大蒜": {
        "soil_threshold": 30, "co2_threshold": 900,
        "water_sec": 8, "nutrient_sec": 5, "ventilate_sec": 30,
        "nutrient_interval": 345600,
        "growth_stages": [
            {"days": (0, 10),  "stage": "seedling",   "fert": "N",   "water_need": "light",  "note": "扎根期"},
            {"days": (11, 40), "stage": "vegetative",  "fert": "N",   "water_need": "normal", "note": "蒜苗采收期"},
            {"days": (41, 80), "stage": "fruiting",    "fert": "PK",  "water_need": "reduce", "note": "蒜头膨大控水"},
        ],
    },
    "葱": {
        "soil_threshold": 28, "co2_threshold": 950,
        "water_sec": 6, "nutrient_sec": 4, "ventilate_sec": 25,
        "nutrient_interval": 345600,
        "growth_stages": [
            {"days": (0, 7),   "stage": "seedling",   "fert": "N",   "water_need": "light",  "note": "缓苗期"},
            {"days": (8, 999), "stage": "vegetative",  "fert": "N",   "water_need": "normal", "note": "持续生长随割随长"},
        ],
    },
    "生姜": {
        "soil_threshold": 45, "co2_threshold": 850,
        "water_sec": 10, "nutrient_sec": 8, "ventilate_sec": 35,
        "nutrient_interval": 259200,
        "growth_stages": [
            {"days": (0, 15),  "stage": "seedling",   "fert": "N",   "water_need": "light",  "note": "避强光保湿"},
            {"days": (16, 60), "stage": "vegetative",  "fert": "N",   "water_need": "heavy",  "note": "分蘖期大量需水"},
            {"days": (61, 120),"stage": "fruiting",    "fert": "PK",  "water_need": "reduce", "note": "姜块膨大期控水"},
        ],
    },
}

# ============ 3位拨码开关编码表（0~7） ============
# 编码: bit0=DIP1, bit1=DIP2, bit2=DIP3
# 0~7: 预定义植物（见上方 PLANT_DB）
DIP_ENCODING = {
    0: "生菜",      # 叶菜
    1: "小白菜",    # 叶菜
    2: "菠菜",      # 叶菜
    3: "韭菜",      # 叶菜
    4: "番茄",      # 果菜
    5: "辣椒",      # 果菜
    6: "黄瓜",      # 果菜
    7: "茄子",      # 果菜
}


def get_plant_name(index):
    """根据拨码值获取植物名称（支持 0-7，共 8 种）"""
    return DIP_ENCODING.get(index, "生菜")  # 默认返回生菜


def get_plant_info(plant_name):
    """获取植物参数（仅支持预定义的 8 种植物）"""
    return PLANT_DB.get(plant_name, PLANT_DB["生菜"])  # 默认返回生菜参数


def get_growth_stage(plant_info, days_since_planting):
    """
    根据种植天数获取当前生长阶段
    返回: 当前阶段字典，包含 stage/fert/water_need/note
    """
    stages = plant_info.get("growth_stages", [])
    if not stages:
        return {"stage": "unknown", "fert": "NPK", "water_need": "normal", "note": "无阶段数据"}
    
    for s in stages:
        start_day, end_day = s["days"]
        if start_day <= days_since_planting <= end_day:
            return s
    
    # 超出所有阶段范围，返回最后一个
    return stages[-1]


def calc_days_since_planting():
    """计算从种植日期到今天的天数"""
    import time
    planting = PLANTING_DATE  # (年, 月, 日)
    now = time.localtime()
    
    # 简化计算：用年和天数差估算
    # 更精确的方式需要日历库，但 ESP32 MicroPython 不一定有
    try:
        # 尝试用 time.mktime 计算精确天数
        then_sec = time.mktime((planting[0], planting[1], planting[2], 0, 0, 0, 0, 0))
        now_sec = time.mktime((now[0], now[1], now[2], 0, 0, 0, 0, 0))
        days = int((now_sec - then_sec) / 86400)
        return max(0, days)
    except (ValueError, OverflowError):
        # 回退：粗略估算（mktime 参数异常时使用近似计算）
        days = (now[0] - planting[0]) * 365 + (now[1] - planting[1]) * 30 + (now[2] - planting[2])
        return max(0, days)
