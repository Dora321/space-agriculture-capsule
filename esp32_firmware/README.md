# 太空农业种植舱 - ESP32 固件

基于 MicroPython 的智能种植舱控制系统，支持 AI 决策、本地规则兜底、实时数据显示。

## 文件结构

```
esp32_firmware/
├── main.py              # 主程序入口
├── config.py.example    # 配置模板（复制为 config.py 使用）
├── config.py            # 实际配置（gitignore，含密钥）
├── plants.json          # 植物数据库（14种植物的养护参数和生长阶段）
├── sensors.py           # 传感器读取模块
├── actuators.py         # 执行器控制模块
├── wifi_client.py       # WiFi 连接模块
├── ai_client.py         # AI API 客户端
├── display.py           # OLED 显示模块（英文模式）
├── utils.py             # 工具函数（LED控制、本地决策、时间格式化）
└── README.md            # 说明文档
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

复制配置模板并修改：

```bash
cp config.py.example config.py
```

编辑 `config.py`：

```python
# WiFi 配置
WIFI_SSID = "你的WiFi名称"
WIFI_PASSWORD = "你的WiFi密码"

# AI API 配置（当前使用 DeepSeek，不配置则只用本地规则）
AI_API_URL = "https://api.deepseek.com/chat/completions"
AI_API_KEY = "你的DeepSeek API密钥"
AI_MODEL = "deepseek-v4-flash"
AI_TIMEOUT = 20  # 推理模型需要较长等待
```

### 4. 烧录固件

1. 下载 MicroPython 固件: https://micropython.org/download/esp32/
2. 使用 esptool 烧录：
```bash
esptool.py --chip esp32 --port COM3 erase_flash
esptool.py --chip esp32 --port COM3 write_flash -z 0x1000 esp32.bin
```

3. 安装 mpremote 工具：
```bash
py -m pip install mpremote
```

4. 上传代码到 ESP32：
```bash
py -m mpremote connect COM3 cp config.py :
py -m mpremote connect COM3 cp plants.json :
py -m mpremote connect COM3 cp main.py :
py -m mpremote connect COM3 cp sensors.py :
py -m mpremote connect COM3 cp actuators.py :
py -m mpremote connect COM3 cp wifi_client.py :
py -m mpremote connect COM3 cp ai_client.py :
py -m mpremote connect COM3 cp display.py :
py -m mpremote connect COM3 cp utils.py :
```

> **注意**：`plants.json` 必须上传，否则 `get_plant_info()` 只能返回 fallback 最小数据。

5. 重启 ESP32

### 5. 测试

```bash
# 传感器测试
py -m mpremote connect COM3 exec "import sensors; sensors.init(); sensors.test_all()"

# 执行器测试
py -m mpremote connect COM3 exec "import actuators; actuators.init(); actuators.test_sequence()"

# 显示测试
py -m mpremote connect COM3 exec "import display; display.init(); display.show_boot(); display.show_data(45, 820, 24.5, 65, 'Tomato', 'idle'); display.show_error('CO2 OFFLINE'); display.show_graphic(); print('Display OK')"

# WiFi 测试
py -m mpremote connect COM3 exec "import wifi_client; wifi_client.connect(); wifi_client.test_connection()"

# AI API 测试
py -m mpremote connect COM3 exec "import ai_client; ai_client.test_api()"
```

> 如果 ESP32 正在运行 main.py，mpremote 会报 `could not enter raw repl`，先执行 `py -m mpremote connect COM3 soft-reset` 中断程序。

## 功能说明

### 主循环逻辑

```
每5分钟执行一次：
1. 读取所有传感器
2. 安全检查（防抖、频率限制）
3. 向AI查询决策（或使用本地规则兜底）
4. 执行决策（水泵/营养液/风扇）
5. 更新OLED显示
```

### 植物类型选择

使用 3 位拨码开关预设 8 种植物（开关 OFF=0, ON=1，取反后编码）：
- 生菜、小白菜、菠菜、韭菜、番茄、辣椒、黄瓜、茄子

| 拨码 1 (GPIO13) | 拨码 2 (GPIO12) | 拨码 3 (GPIO14) | 植物类型 |
|:---:|:---:|:---:|---|
| OFF | OFF | OFF | 生菜 |
| ON | OFF | OFF | 小白菜 |
| OFF | ON | OFF | 菠菜 |
| ON | ON | OFF | 韭菜 |
| OFF | OFF | ON | 番茄 |
| ON | OFF | ON | 辣椒 |
| OFF | ON | ON | 黄瓜 |
| ON | ON | ON | 茄子 |

每种植物有独立的：
- 土壤湿度阈值
- CO2浓度阈值
- 浇水/营养液/换气时长
- 完整的生长阶段模型（苗期→生长期→开花期→结果期→采收期）

### 本地规则兜底

即使 WiFi 断开，AI 不可用，系统仍能根据本地规则工作：

1. 土壤湿度 < 阈值-15 → 立即浇水（延长时间）
2. 土壤湿度 < 阈值 → 浇水
3. CO2 > 阈值+300 → 换气（延长时间）
4. CO2 > 阈值 → 换气
5. 营养液间隔到期 → 补充营养
6. 一切正常 → 待机

### OLED 显示

系统使用英文模式显示（SSD1306 内置 ASCII 5x8 字体）：
- 启动画面："SPACE FARM v1.0"
- 实时传感器数据：Soil/CO2/T/H
- 当前动作：Water/Nutrient/Ventilate/Idle
- 错误信息：OFFLINE 告警

### 传感器离线降级

| 传感器 | 离线降级值 | 说明 |
|--------|-----------|------|
| 土壤湿度 | 0% | 触发安全浇水 |
| CO2 | 420ppm | 基线值，不触发换气 |
| DHT22 | 25°C / 60% | 默认舒适值 |

传感器离线时 LED 红闪 + OLED 显示 "OFFLINE: ..." 告警。

## API 配置

> **当前已配置：DeepSeek deepseek-v4-flash**（¥1/百万tokens，性价比极高）

### DeepSeek（当前配置）

1. 注册 https://platform.deepseek.com/
2. 在「API Keys」页面创建密钥
3. 修改 `config.py`（已预置，可直接填入密钥）：
```python
AI_API_URL = "https://api.deepseek.com/chat/completions"
AI_API_KEY = "你的DeepSeek API密钥"
AI_MODEL = "deepseek-v4-flash"
AI_TIMEOUT = 20
```

> **注意**：推理模型（如 deepseek-reasoner）思考时间较长，`AI_TIMEOUT` 建议设为 20 秒以上。如果使用非推理模型（如 deepseek-chat），可适当缩短至 10 秒。

### 火山方舟

1. 注册 https://open.bigmodel.cn/
2. 创建 API Key
3. 修改 config.py：
```python
AI_API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
AI_API_KEY = "你的密钥"
AI_MODEL = "glm-4-flash"
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

### mpremote 常用命令

```bash
# 查看设备
py -m mpremote devs

# 执行代码
py -m mpremote connect COM3 exec "import gc; gc.collect(); print(gc.mem_free())"

# 上传文件
py -m mpremote connect COM3 cp config.py :

# 中断运行中的程序
py -m mpremote connect COM3 soft-reset

# 进入交互 REPL
py -m mpremote connect COM3
```

### 日志输出

系统启动后会输出：
```
[WiFi] Connected successfully! IP: 192.168.1.100
[Sensor] Soil:45% | CO2:820ppm | Temp:24C | Hum:65%
[Growth] Day 15 | Stage: vegetative | Fert: N
[AI Decision] action=water duration=10s reason=Soil moisture below threshold
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
   - 需要预热 30 秒（`CO2_WARMUP_TIME` 控制）
   - 放户外校准（420ppm）

5. **AI API 超时（-116 ETIMEDOUT）**
   - 推理模型思考时间长，增大 `AI_TIMEOUT`（建议 20 秒）
   - 非推理模型可缩短至 10 秒

6. **AI 返回 `finish_reason: length`**
   - 推理 token 消耗了 max_tokens 预算，增大 `max_tokens`（当前 1024）

7. **AI 请求体截断 / JSON 解析失败**
   - MicroPython `urequests` 对中文字符的 Content-Length 计算有 bug
   - 代码已使用 `.encode('utf-8')` 修复，确保使用最新版 `ai_client.py`

8. **传感器离线告警**
   - 传感器读取失败时，系统返回 None 并触发 LED 红闪 + OLED 显示 "OFFLINE" 告警
   - 土壤传感器离线 → 降级为 0%（触发安全浇水）
   - CO2 传感器离线 → 降级为 420ppm（基线值，不触发换气）
   - DHT22 离线 → 降级为 25°C / 60%

## 设计限制说明

1. **执行器运行期间主循环阻塞**：水泵/营养液泵/风扇运行时使用 `time.sleep(1)` 分段等待，期间无法响应新传感器数据或 WiFi 断连。这是 ESP32 单线程 MicroPython 的已知限制。最大阻塞时间 = 单次最大运行时长（默认 60 秒）。

2. **OLED 英文模式**：系统使用 SSD1306 内置 ASCII 5x8 字体显示，植物名称和状态以英文显示。如需中文显示，需自行添加 16x16 点阵字库文件。

3. **API 密钥安全**：`config.py` 中 API 密钥为明文存储，这是嵌入式设备的常见做法。但请注意：
   - **不要将 `config.py` 上传到公开 Git 仓库**（已在 `.gitignore` 中排除）
   - 建议使用 `/secrets/` 目录存储密钥（`_load_secret()` 函数支持）
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

编辑 `plants.json`，在 JSON 中添加新条目：

```json
"新植物": {
  "soil_threshold": 35,
  "co2_threshold": 800,
  "water_sec": 10,
  "nutrient_sec": 5,
  "ventilate_sec": 30,
  "nutrient_interval": 259200,
  "growth_stages": [
    {"days": [0, 7], "stage": "seedling", "fert": "N", "water_need": "light", "note": "苗期"},
    {"days": [8, 30], "stage": "vegetative", "fert": "N", "water_need": "normal", "note": "生长期"}
  ]
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
