# 太空农业种植舱 - ESP32 固件

基于 MicroPython 的智能种植舱控制系统，支持 AI 决策、本地规则兜底、实时数据显示。

## 文件结构

```
esp32_firmware/
├── main.py          # 主程序入口
├── config.py        # 配置文件（WiFi、AI API、引脚定义）
├── sensors.py       # 传感器读取模块
├── actuators.py     # 执行器控制模块
├── wifi_client.py   # WiFi 连接模块
├── ai_client.py     # AI API 客户端
├── display.py       # OLED 显示模块
├── utils.py         # 工具函数
└── README.md        # 说明文档
```

## 快速开始

### 1. 硬件准备

| 配件 | 型号 | 数量 |
|------|------|------|
| 主控板 | ESP32 DevKit v1 | 1 |
| 土壤湿度 | 电容式 v1.2 | 1 |
| CO2传感器 | MH-Z19B | 1 |
| 温湿度 | DHT22 | 1 |
| 继电器×3 | 5V低电平触发 | 3 |
| 水泵 | 5V潜水泵 | 1 |
| 营养液泵 | 12V隔膜泵 | 1 |
| 风扇 | 12V静音风扇 | 1 |
| OLED | SSD1306 I2C | 1 |

### 2. 接线

详见 `../智能种植舱控制器选型报告.md` 第四章

### 3. 配置

编辑 `config.py`：

```python
# WiFi 配置
WIFI_SSID = "你的WiFi名称"
WIFI_PASSWORD = "你的WiFi密码"

# AI API 配置（当前使用 DeepSeek，不配置则只用本地规则）
AI_API_URL = "https://api.deepseek.com/chat/completions"
AI_API_KEY = "你的DeepSeek API密钥"
AI_MODEL = "deepseek-chat"
```

### 4. 烧录固件

1. 下载 MicroPython 固件: https://micropython.org/download/esp32/
2. 使用 esptool 烧录：
```bash
esptool.py --chip esp32 --port COM3 erase_flash
esptool.py --chip esp32 --port COM3 write_flash -z 0x1000 esp32.bin
```

3. 使用 Thonny 或 ampy 上传代码：
```bash
ampy put main.py
ampy put config.py
ampy put sensors.py
ampy put actuators.py
ampy put wifi_client.py
ampy put ai_client.py
ampy put display.py
ampy put utils.py
```

4. 重启 ESP32

### 5. 测试

```python
# 在 REPL 中运行测试
import sensors
sensors.test_all()  # 测试所有传感器

import actuators
actuators.test_sequence()  # 测试执行器

import wifi_client
wifi_client.test_connection()  # 测试网络

import ai_client
ai_client.test_api()  # 测试AI API
```

## 功能说明

### 主循环逻辑

```
每5分钟执行一次：
1. 读取所有传感器
2. 安全检查
3. 向AI查询决策（或使用本地规则）
4. 执行决策（水泵/营养液/风扇）
5. 更新OLED显示
```

### 植物类型选择

使用拨码开关预设 8 种植物：
- 生菜、番茄、辣椒、黄瓜、草莓、罗勒、小白菜、薄荷

每种植物有独立的：
- 土壤湿度阈值
- CO2浓度阈值
- 浇水/营养液/换气时长

### 本地规则兜底

即使 WiFi 断开，AI 不可用，系统仍能根据本地规则工作：

1. 土壤湿度 < 阈值 → 浇水
2. CO2 > 阈值 → 换气
3. 定时补充营养液
4. 一切正常 → 待机

### OLED 显示

- 启动画面
- 实时传感器数据
- 当前动作执行
- 错误信息

## API 配置

> **当前已配置：DeepSeek deepseek-chat**（¥1/百万tokens，性价比极高）

### DeepSeek（当前配置）

1. 注册 https://platform.deepseek.com/
2. 在「API Keys」页面创建密钥
3. 修改 `config.py`（已预置，可直接填入密钥）：
```python
AI_API_URL = "https://api.deepseek.com/chat/completions"
AI_API_KEY = "你的DeepSeek API密钥"
AI_MODEL = "deepseek-chat"   # 或 deepseek-reasoner（推理模型）
```

### 火山方舟

1. 注册 https://open.bigmodel.cn/
2. 创建 API Key
3. 修改 config.py：
```python
AI_API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
AI_API_KEY = "你的密钥"
AI_MODEL = "glm-4-flash"  # 或 glm-4
```

### DeepSeek

```python
AI_API_URL = "https://api.deepseek.com/chat/completions"
AI_API_KEY = "你的密钥"
AI_MODEL = "deepseek-chat"
```

### OpenAI

```python
AI_API_URL = "https://api.openai.com/v1/chat/completions"
AI_API_KEY = "你的密钥"
AI_MODEL = "gpt-3.5-turbo"
```

## 调试

### 串口监视器

使用 PuTTY 或 minicom 连接：
```bash
# Windows
PuTTY - Serial - COM3 - 115200

# Linux/Mac
minicom -D /dev/ttyUSB0 -b 115200
```

### 日志输出

系统启动后会输出：
```
[WiFi] 连接成功! IP: 192.168.1.100
[传感器] 土壤:45% | CO2:820ppm | 温:24C | 湿:65%
[AI决策] action=idle duration=0s reason=状态正常
```

## 常见问题

1. **OLED 不亮**
   - 检查 I2C 地址（默认 0x3C）
   - 检查接线：SDA→GPIO21, SCL→GPIO22

2. **继电器不工作**
   - 确认是低电平触发模块
   - 检查共地连接

3. **WiFi 连接失败**
   - 检查 SSID 和密码
   - 确认 WiFi 2.4GHz（ESP32 不支持 5GHz）

4. **CO2 读数不准**
   - 需要预热 3 分钟
   - 放户外校准（420ppm）

5. **OLED 显示方块/乱码**
   - SSD1306 默认字库仅支持 ASCII 英文字符，中文会显示为方块
   - 当前固件已全部使用英文显示，如需中文请自行制作字模（参考 `framebuf` 的 `Framebuffer` 方法）

6. **传感器离线告警**
   - 传感器读取失败时，系统会返回 None 并触发 LED 红闪 + OLED 显示 "OFFLINE" 告警
   - 土壤传感器离线 → 降级为 0%（触发安全浇水）
   - CO2 传感器离线 → 降级为 2000ppm（触发安全换气）

## 设计限制说明

1. **执行器运行期间主循环阻塞**：水泵/营养液泵/风扇运行时使用 `time.sleep(1)` 分段等待，期间无法响应新传感器数据或 WiFi 断连。这是 ESP32 单线程 MicroPython 的已知限制。最大阻塞时间 = 单次最大运行时长（默认 60 秒）。

2. **OLED 不支持中文**：SSD1306 的 MicroPython 驱动默认仅含 ASCII 5×8 点阵字库。如需中文显示，需使用 `framebuf.FrameBuffer` 自定义字模，或外挂中文字库芯片（如 GT30L32S4W）。

3. **API 密钥安全**：`config.py` 中 API 密钥为明文存储，这是嵌入式设备的常见做法。但请注意：
   - **不要将 `config.py` 上传到公开 Git 仓库**
   - 建议在 `.gitignore` 中添加 `config.py`
   - DeepSeek API 密钥可在 https://platform.deepseek.com/ 随时重置

## 扩展

### 添加更多传感器

在 `sensors.py` 中添加新函数：

```python
def read_light():
    """读取光照强度"""
    # 使用光敏电阻或 BH1750
    pass
```

### 添加更多植物

在 `config.py` 中添加：

```python
PLANT_DB["新植物"] = {
    "soil_threshold": 35,
    "co2_threshold": 800,
    "water_sec": 10,
    "nutrient_sec": 5,
    "ventilate_sec": 30,
    "nutrient_interval": 259200,
}
```

### 添加定时任务

修改 `main.py` 中的 `main_loop()`：

```python
# 每天早上9点执行特殊任务
if time.localtime()[3] == 9 and time.localtime()[4] == 0:
    # 执行定时任务
    pass
```

## 许可证

MIT License
