# 太空农业种植舱 - ESP32 固件

基于 MicroPython 的智能种植舱控制系统，支持 AI 决策、本地规则兜底、实时数据显示。

## 文件结构

```
esp32_firmware/
├── main.py              # 主程序入口
├── config.py.example    # 配置模板（复制为 config.py 使用）
├── config.py            # 实际配置（gitignore，含密钥）
├── plants.json          # 植物数据库（8种作物的养护参数和生长阶段）
├── state.py             # 主循环共享运行状态
├── action_runtime.py    # 执行动作、安全检查和动作计数
├── boot_runtime.py      # 系统启动初始化流程编排
├── decision.py          # 本地规则、AI 请求门控和云端决策编排
├── display_runtime.py   # OLED 初始化、释放和分页刷新编排
├── loop_runtime.py      # 主循环采样、决策、执行、上报和重连调度
├── sensor_runtime.py    # 传感器读取编排、离线降级和生长统计
├── sensors.py           # 传感器读取模块
├── actuators.py         # 执行器控制模块
├── wifi_client.py       # WiFi 连接模块
├── ai_client.py         # AI API 客户端
├── display.py           # OLED 显示模块（英文模式）
├── telemetry.py         # 实时大屏遥测上报
├── uart_link.py         # 树莓派 UART JSON-over-Line 协议层
├── utils.py             # 工具函数（LED控制、本地决策、时间格式化）
├── diagnostics/         # 设备端诊断脚本，不属于生产启动链路
└── README.md            # 说明文档
```

## 快速开始

### 1. 硬件准备

| 配件 | 型号 | 数量 |
|------|------|------|
| 主控板 | ESP32 DevKit v1 | 1 |
| 土壤湿度 | 电容式 v1.2 | 1 |
| 环境亮度 | HS-S20L-B 光敏模块 | 1 |
| 温湿度 | DHT11 | 1 |
| 继电器 | 5V 低电平触发 | 1 |
| 水泵 | 12V 蠕动泵 | 1 |
| 状态灯条 | WS2812 RGB（11 颗灯珠） | 1 |
| OLED | SH1106 I2C | 1 |

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
py -m mpremote connect COM3 cp state.py :
py -m mpremote connect COM3 cp action_runtime.py :
py -m mpremote connect COM3 cp boot_runtime.py :
py -m mpremote connect COM3 cp decision.py :
py -m mpremote connect COM3 cp display_runtime.py :
py -m mpremote connect COM3 cp loop_runtime.py :
py -m mpremote connect COM3 cp sensor_runtime.py :
py -m mpremote connect COM3 cp sensors.py :
py -m mpremote connect COM3 cp actuators.py :
py -m mpremote connect COM3 cp wifi_client.py :
py -m mpremote connect COM3 cp ai_client.py :
py -m mpremote connect COM3 cp display.py :
py -m mpremote connect COM3 cp sh1106.py :
py -m mpremote connect COM3 cp status_strip.py :
py -m mpremote connect COM3 cp telemetry.py :
py -m mpremote connect COM3 cp uart_link.py :
py -m mpremote connect COM3 cp utils.py :
```

> **注意**：MicroPython 默认不内置 `neopixel` 模块的某些版本——ESP32 官方 MicroPython 是内置的；若使用裁剪固件需先 `import neopixel` 验证。

> **注意**：`plants.json` 必须上传，否则 `get_plant_info()` 只能返回 fallback 最小数据。

5. 重启 ESP32

### 5. 测试

```bash
# 传感器测试
py -m mpremote connect COM3 exec "import sensors; sensors.init(); sensors.test_all()"

# 执行器测试
py -m mpremote connect COM3 exec "import actuators; actuators.init(); actuators.test_sequence()"

# 显示测试
py -m mpremote connect COM3 exec "import display; display.init(); display.show_boot(); display.show_data(45, 65, 24.5, 65, 'Tomato', 'idle'); display.show_error('DHT OFFLINE'); display.show_graphic(); print('Display OK')"

# WiFi 测试
py -m mpremote connect COM3 exec "import wifi_client; wifi_client.connect(); wifi_client.test_connection()"

# AI API 测试
py -m mpremote connect COM3 exec "import ai_client; ai_client.test_api()"
```

> 如果 ESP32 正在运行 main.py，mpremote 会报 `could not enter raw repl`，先执行 `py -m mpremote connect COM3 soft-reset` 中断程序。

## 功能说明

### 主循环逻辑

```
每 READ_INTERVAL 秒采样一次：
1. 读取所有传感器（土壤湿度、光照、温湿度、拨码作物）
2. 更新 OLED 轮播页面和 Web 大屏遥测

每 DECISION_INTERVAL 秒决策一次：
1. 安全检查（动作防抖、每小时动作上限、传感器离线）
2. 先生成本地规则决策
3. 仅在阈值事件、环境明显变化或周期复核时请求云端 AI
4. AI 不可用、内存不足或请求被限频时，继续使用本地规则
5. 执行动作（水泵/营养液/待机）并上报执行记录
```

默认配置下 `READ_INTERVAL = 60`、`DECISION_INTERVAL = 60`。云端 AI 另有请求门控：

- `AI_MIN_REQUEST_INTERVAL`：两次云端 AI 请求的最小间隔
- `AI_FORCE_REQUEST_INTERVAL`：稳定状态下的周期复核间隔
- `AI_SOIL_DELTA` / `AI_LIGHT_DELTA` / `AI_TEMP_DELTA` / `AI_HUM_DELTA`：环境明显变化阈值

这意味着系统每分钟仍会执行本地安全判断，但不会在环境稳定时每分钟都请求云端 AI。

### 树莓派 UART 上位机（可选）

`UART_ENABLED = True` 后，ESP32 会通过 UART2 与树莓派交换 JSON-over-Line：

- ESP32 → Pi：每轮采样后发送 `report`，包含传感器、作物、动作、决策来源
- Pi → ESP32：发送 `ping` 心跳和 `advice` 建议
- ESP32 30 秒收不到 Pi 消息时，`pi_online=False`，继续使用本地规则引擎自治

实机推荐配置：

```python
UART_ENABLED = True
UART_SKIP_WIFI = True
UART_RXBUF = 256
STARTUP_MENU_ON_BOOT = True
```

`UART_SKIP_WIFI=True` 时，ESP32 会跳过 WiFi 初始化，OLED 第三页显示 WiFi offline/AI off 属于正常状态。树莓派负责联网、大屏和后续 AI/数据库；ESP32 保留传感器、OLED、执行器、本地规则和安全护栏。实机验证表明，如果 ESP32 同时启用 WiFi、OLED/I2C、UART2，会因堆内存压力导致 `UART driver malloc error` 或底层崩溃。

接线：

```text
ESP32 GPIO17 (U2 TX) -> Raspberry Pi GPIO15/RXD pin 10
ESP32 GPIO16 (U2 RX) <- Raspberry Pi GPIO14/TXD pin 8
ESP32 GND            -> Raspberry Pi GND pin 6
```

树莓派运行：

```bash
python3 tools/serial_gateway.py --port /dev/serial0 --baud 115200 --auto-advice
```

Pi 的 `advice` 永远只是建议；ESP32 会先做本地护栏检查（温度、动作时长上限、动作限频），再决定是否执行。

### 植物类型选择

使用模拟键盘（ADC 电阻分压，GPIO33）选择 8 种植物：
- 生菜、小白菜、菠菜、韭菜、番茄、辣椒、黄瓜、茄子

| 按钮 | 功能 | 说明 |
|:---:|:---:|---|
| UP (Red) | 上一个 | 按键通过特定电阻接 GND，ADC 分压识别 |
| DOWN (Yellow) | 下一个 | 同上 |
| OK (Green) | 确认 | 同上 |
| BACK (Blue) | 返回/菜单 | 同上，长按触发菜单 |

**四个按钮共用一个 ADC 引脚 GPIO33**，通过不同电阻值产生不同分压：
```
VCC(3.3V) → R_pullup → GPIO33 ─┬─ R_up ── SW_UP ── GND
                                ├─ R_dn ── SW_DN ── GND
                                ├─ R_ok ── SW_OK ── GND
                                └─ R_bk ── SW_BK ── GND
```
代码通过 `AnalogKeypad` 类读取 ADC 值并比对阈值区分按键。
首次使用可运行 `AnalogKeypad.calibrate(33)` 自动校准阈值。

> 注意：GPIO33 是 ADC1_CH5，支持模拟读取。确认你的 ESP32 开发板 GPIO33 可用作 ADC 输入（大多数 ESP32 DevKit 均可）。

每种植物有独立的：
- 土壤湿度阈值
- 浇水/营养液时长
- 完整的生长阶段模型（苗期→生长期→开花期→结果期→采收期）

### 本地规则兜底

即使 WiFi 断开，AI 不可用，系统仍能根据本地规则工作（单泵架构 2026-05-27 起）：

1. 土壤湿度 < 阈值-15 → 立即救命浇水（延长时间，温度异常也照常浇）
2. 温度 ≥ TEMP_HIGH_C 或 ≤ TEMP_LOW_C → 跳过浇水（避免闷根/冻根）
3. 土壤湿度 < 阈值 → 正常浇水
4. 一切正常 → 待机

### OLED 显示

系统使用英文模式显示（SH1106 framebuffer ASCII 5x8 字体）：
- 启动画面："SPACE FARM v1.0"
- 实时传感器数据：Soil/L(光照)/T/H
- 当前动作：Water/Idle
- 错误信息：OFFLINE 告警

### WS2812 状态灯条（育种舱生物指示灯）

11 颗 RGB 灯珠作为"土壤湿度温度计 + 系统状态指示"：
- **平时**：按土壤湿度点亮对应数量灯珠（每颗约 9%），颜色梯度暖红 → 黄 → 绿 → 冷蓝
- **浇水中**：整条黄色
- **离线/错误**：整条红色（或首尾两颗暗红常亮表示传感器离线）
- **正常空闲**：整条柔和绿

亮度通过 `WS2812_BRIGHTNESS`（0.0-1.0）控制，默认 0.4 避免功耗过高 + 不刺眼。

### 传感器离线降级

| 传感器 | 离线降级值 | 说明 |
|--------|-----------|------|
| 土壤湿度 | 0% | 触发安全浇水；WS2812 首尾暗红警示 |
| 环境亮度 | 0% | 降级为无光照 |
| DHT11 | 25°C / 60% | 默认舒适值 |

传感器离线时 WS2812 红闪 + OLED 显示 "OFFLINE: ..." 告警。

### 诊断脚本

`diagnostics/` 下的脚本用于现场排查硬件问题，不属于生产固件启动链路：

```bash
# DHT/OLED 组合诊断
py -m mpremote connect COM3 run diagnostics/debug_dht.py

# 轻量 DHT 读数检查
py -m mpremote connect COM3 run diagnostics/dht_check.py
```

如果设备端尚未创建 `diagnostics/` 目录，也可以临时上传到根目录运行：

```bash
py -m mpremote connect COM3 cp diagnostics/debug_dht.py :debug_dht.py
py -m mpremote connect COM3 run debug_dht.py
```

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
[Sensor] Soil:45% | Light:65% | Temp:24C | Hum:65%
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

4. **AI API 超时（-116 ETIMEDOUT）**
   - 推理模型思考时间长，增大 `AI_TIMEOUT`（建议 20 秒）
   - 非推理模型可缩短至 10 秒

5. **AI 返回 `finish_reason: length`**
   - 推理 token 消耗了 max_tokens 预算，增大 `max_tokens`（当前 1024）

6. **AI 请求体截断 / JSON 解析失败**
   - MicroPython `urequests` 对中文字符的 Content-Length 计算有 bug
   - 代码已使用 `.encode('utf-8')` 修复，确保使用最新版 `ai_client.py`

7. **传感器离线告警**
   - 传感器读取失败时，系统返回 None 并触发 LED 红闪 + OLED 显示 "OFFLINE" 告警
   - 土壤传感器离线 → 降级为 0%（触发安全浇水）
   - 光敏模块离线 → 降级为 0%
   - DHT11 离线 → 降级为 25°C / 60%

## 设计限制说明

1. **执行器运行期间主循环阻塞**：12V 水泵运行时使用 `time.sleep(1)` 分段等待，期间无法响应新传感器数据或 WiFi 断连。这是 ESP32 单线程 MicroPython 的已知限制。最大阻塞时间 = 单次最大运行时长（默认 60 秒）。

2. **OLED 英文模式**：系统使用 SH1106 framebuffer ASCII 5x8 字体显示，植物名称和状态以英文显示。如需中文显示，需自行添加 16x16 点阵字库文件。

3. **API 密钥安全**：`config.py` 中 API 密钥为明文存储，这是嵌入式设备的常见做法。但请注意：
   - **不要将 `config.py` 上传到公开 Git 仓库**（已在 `.gitignore` 中排除）
   - 建议使用 `/secrets/` 目录存储密钥（`_load_secret()` 函数支持）
   - DeepSeek API 密钥可在 https://platform.deepseek.com/ 随时重置

## 扩展

### 添加更多传感器

在 `sensors.py` 中添加新函数，例如添加 CO2 传感器：

```python
def read_co2():
    """读取 CO2 浓度"""
    # 使用 MH-Z19B 或 MQ-135
    pass
```

### 添加更多植物

编辑 `plants.json`，在 JSON 中添加新条目：

```json
"新植物": {
  "soil_threshold": 35,
  "water_sec": 10,
  "light_min": 30, "light_opt": 50, "light_hours": [6, 8],
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
