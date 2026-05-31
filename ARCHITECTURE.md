# ARCHITECTURE.md — 太空农业智能种植舱系统架构

## 1. 系统总览

```
┌──────────────── 太空舱端 ESP32（飞控 / 只要有电就跑）────────────────┐
│  ┌── SENSE ───────────┐  ┌── THINK ───────────────┐  ┌── ACT ────────────┐ │
│  │ 🌡️ 土壤 ADC GPIO34 │  │ 📋 本地规则引擎(兜底)  │  │ 💧 水泵 GPIO5      │ │
│  │ ☀️ 光照 ADC GPIO32 │─▶│ 📡 采纳树莓派 advice   │─▶│ 💡 补光灯 GPIO18   │ │
│  │ 🌡️ 温湿 DHT11 GPIO4│  │   (在线优先, 过安全门) │  │ 🌈 WS2812 GPIO26   │ │
│  │ 🔢 旋钮选作物       │  │                        │  │                    │ │
│  └────────────────────┘  └────────────────────────┘  └────────────────────┘ │
│      OLED 三页轮播 + WS2812 12 种信号动画（Decision Plane / Action Plane）    │
└───────────────────────────────────│─────────────────────────────────────────┘
                                     │ UART2 115200 · JSON-over-Line
                                     │ ↑ report/pong   ↓ ping/advice
            ┌────────────────────────▼──────── 树莓派（载荷计算机）──────────┐
            │  🔌 serial_gateway        🤖 DeepSeek (pi_advisor)            │
            │  收 report · 调 AI 回 advice · 转发大屏 · 负责联网/AI          │
            └────────────────────────│──────────────────────────────────────┘
                                     │ HTTP POST（树莓派联网）
            ┌────────────────────────▼──────── 云端地面站 ──────────────────┐
            │  📊 Web 实时大屏 (port 8790)   单向接收 · 无反向控制通道       │
            └───────────────────────────────────────────────────────────────┘
```

**自治边界**：ESP32 保留传感器、执行器、本地规则和安全护栏，断网断树莓派也能种活作物。树莓派承担联网、大屏、AI——挂了只是变笨/看不到。大屏只读，不向 ESP32 下发控制命令。AI（DeepSeek）跑在树莓派侧（见 §4 三层降级、§9.4）。

### 1.1 树莓派双层 UART 模式（2026-05-30 实机路线）

为落地“ESP32 舱内飞控 + 树莓派载荷计算机/地面站”的双层架构，系统支持另一种运行模式：

```
ESP32（飞控 / 下位机）                         树莓派（载荷计算机 / 上位机）
┌─────────────────────────────┐              ┌─────────────────────────────┐
│ SENSE: 传感器读取             │              │ serial_gateway.py            │
│ THINK: 本地规则 + Pi advice   │ JSON Line    │ - 收 ESP32 report            │
│ ACT: 水泵/补光/OLED/WS2812    │ UART2 115200 │ - 发 ping/advice             │
│ SAFE: 温度/时长/限频护栏       │◄───────────►│ - 转发 dashboard /api/state  │
└─────────────────────────────┘              │ - 后续接入 AI/SQLite/视觉     │
                                               └─────────────────────────────┘
```

配置：

```python
UART_ENABLED = True
UART_SKIP_WIFI = True
UART_ID = 2
UART_BAUD = 115200
UART_TX_PIN = 17
UART_RX_PIN = 16
UART_RXBUF = 256
UART_OFFLINE_TIMEOUT_MS = 30000
```

接线必须三线齐全且 TX/RX 交叉：

```
ESP32 GPIO17 (U2 TX) -> Raspberry Pi GPIO15/RXD pin 10
ESP32 GPIO16 (U2 RX) <- Raspberry Pi GPIO14/TXD pin 8
ESP32 GND            -> Raspberry Pi GND pin 6
```

**关键约束**：启用 UART 双层模式时，ESP32 默认跳过 WiFi（`UART_SKIP_WIFI=True`），由树莓派负责联网、大屏和 AI。实机验证发现 ESP32 同时开启 WiFi 驱动、OLED/I2C、UART2 时堆内存压力过高，UART 初始化会出现 `UART driver malloc error`，或提前初始化后在 OLED I2C 初始化阶段触发底层崩溃。跳过 ESP32 WiFi 后，日志已确认稳定启动：

```text
[WiFi] Skipped: UART mode uses Raspberry Pi networking
[UART] Pi link initialized
[Display] OLED initialized successfully
[Init] Starting plant selection...
```

这与架构原则一致：ESP32 保留“断了会死作物”的飞控职责，树莓派承担“断了只是变笨/看不到”的网络、AI、数据库和大屏职责。

### 1.2 树莓派端部署要点（2026-05-30 实机验收通过）

`/dev/serial0` 全链路（report/ping/pong/advice）已在真机跑通，ESP32 后续 report 的 `ai_src` 变为 `pi`，证明 ESP32 真正采用了 Pi 的建议。落地时按顺序排掉的三个坑，已固化为部署清单：

1. **接线必须三线齐全且 TX/RX 交叉、共地接牢**。共地松动时 Pi 的 RX 悬空，串口只读到持续 `0xFF` 噪声（可打印率 0%）；正常空闲线应安静（0 字节）。共地是最容易忽略又最先要查的。
2. **必须把 `/dev/serial0` 从内核控制台释放**。树莓派默认 `console=serial0`，会把该 UART 当内核控制台：① 设备节点被锁成 `root:tty 600`，普通用户打不开；② 与网关的双向流量争用——**只读能收到干净 report，但网关一旦回写 ping/advice，RX 立刻被打断**。修法：`sudo sed -i 's/console=serial0,115200 //' /boot/firmware/cmdline.txt`（保留 `console=tty1`）+ 重启，并 `sudo systemctl disable --now serial-getty@ttyS0.service`。重启后节点变 `root:dialout 660`，dialout 组用户免 sudo 可开。注意 ttyS0 是 mini-UART（不如 PL011 稳），波特率随核心时钟，务必 `enable_uart=1`。
3. **若 Pi 上跑着进程监管/沙箱（如 openclaw 硬件看门狗），先查它的杀进程规则**。本机 `hw-watchdog.service` 每 30s `kill -9` 命令行匹配硬件库关键词的 Python 进程，其 `board` 裸子串误伤了网关的 `--dashboard` 参数。规避：网关的 dashboard URL 改用环境变量 `SPACEFARM_DASHBOARD`（systemd `Environment=` 传，不出现在 argv）；并把看门狗 `board` 收紧为词边界正则。详见 [DEVLOG/2026-05-30.md](./DEVLOG/2026-05-30.md) #41。

**开机自启**：网关做成 systemd 服务 `spacefarm-gateway.service`（`User=mx Group=dialout`，`Restart=always`，`Environment=SPACEFARM_DASHBOARD=http://43.156.68.157:8790/api/state`，`--auto-advice`），已验证转发到云端大屏 `live:true` 实时刷新。

---

## 2. Decision Plane / Action Plane 分离架构

### 2.1 核心思想

传统 IoT 控制器是「执行器驱动」——有什么硬件就做什么决策。本系统采用「决策驱动」——决策层输出完整的多维诊断，执行层仅响应有硬件支撑的动作，其余诊断信息通过 WS2812 灯条动画即时广播。

```
Decision Plane                          Action Plane
┌─────────────────────┐                ┌──────────────────────┐
│ AI / 本地规则引擎   │                │ 物理执行器          │
│                     │   WATER ──────▶│ 💧 水泵 (GPIO5)     │
│ 输出:               │   LIGHT_LOW ─▶│ 💡 补光灯 (GPIO18)  │
│  action: water/light/idle            │                      │
│  signals: [...]     │                │ 虚拟执行器          │
│  breeding_obs: ...  │   TEMP_HIGH ──▶│ 🌡️ WS2812 动画      │
│                     │   NEED_N ─────▶│ 🌱 WS2812 动画      │
│                     │   ...          │ ...                  │
└─────────────────────┘                └──────────────────────┘
```

### 2.2 信号体系

| 信号 | 类别 | WS2812 动画 | 物理执行器 | 含义 |
|------|------|------------|-----------|------|
| WATER | 物理 | 黄色流水 | 水泵 | 正在浇水 |
| LIGHT_LOW | 物理 | 蓝色脉冲 | 补光灯 | 光照不足，执行补光 |
| LIGHT_HIGH | 虚拟 | 白色快闪 | — | 光照过强警告 |
| TEMP_HIGH | 虚拟 | 红色呼吸 | — | 舱内高温警告 |
| TEMP_LOW | 虚拟 | 蓝色呼吸 | — | 舱内低温警告 |
| HUMID_LOW | 虚拟 | 青色脉冲 | — | 湿度偏低 |
| NEED_N | 虚拟 | 绿色脉冲 | — | 缺氮 |
| NEED_P | 虚拟 | 绿色脉冲 | — | 缺磷 |
| NEED_K | 虚拟 | 绿色脉冲 | — | 缺钾 |
| SENSOR_FAIL | 虚拟 | 红色快闪 | — | 传感器故障 |
| OFFLINE_MODE | 虚拟 | 琥珀色呼吸 | — | 离线模式（无 AI） |
| BREEDING_GEN_UP | 虚拟 | 彩虹 | — | 育种代际升级 |

### 2.3 信号广播流程

```
传感器采样 → 决策引擎 → 决策结果
                           │
              ┌────────────┼────────────────┐
              ▼            ▼                ▼
         action 分支   signals 分支    breeding_obs
              │            │                │
              ▼            ▼                ▼
         物理执行器    WS2812 动画       遥测上报
         (水泵/补光)   (先物理信号,      (大屏信号面板+
                       后advisory信号)    育种观察面板)
```

1. 动作执行前，播放物理信号动画（WATER→黄色流水 3s，LIGHT_LOW→蓝色脉冲 3s）
2. 动作执行后，播放 advisory 信号（TEMP_HIGH→红色呼吸，NEED_N→绿色脉冲等）
3. 即使 action=idle，也播放 advisory 信号
4. 最多连续播放 3 个信号动画，物理信号优先

---

## 3. 固件架构

### 3.1 模块依赖图

```
main.py (薄壳，仅依赖注入接线)
  │
  ├── boot_runtime.py ──▶ sensors.py, display.py, status_strip.py
  ├── loop_runtime.py ──▶ sensor_runtime.py, decision.py, action_runtime.py, display_runtime.py, telemetry.py
  │       │
  │       ├── sensor_runtime.py ──▶ sensors.py
  │       ├── decision.py ──▶ ai_client.py, utils.py
  │       │       │               │
  │       │       │               └── local_fallback_decision (纯函数，无 I/O)
  │       │       │
  │       │       └── _should_request_ai (AI 门控逻辑)
  │       │
  │       ├── action_runtime.py ──▶ actuators.py, utils.py
  │       │       │
  │       │       └── safety_check (防抖/限频/降级)
  │       │
  │       ├── display_runtime.py ──▶ display.py ──▶ sh1106.py
  │       │
  │       └── telemetry.py (fire-and-forget HTTP POST)
  │
  └── 共享状态: state.py (SystemState 单例)
```

### 3.2 模块职责

| 模块 | 行数 | 职责 | 测试覆盖 |
|------|------|------|---------|
| `main.py` | ~80 | 依赖注入接线，不包含逻辑 | 间接覆盖 |
| `state.py` | ~40 | `SystemState` 可变状态容器 | 间接覆盖 |
| `config.py` | ~60 | 硬件引脚、安全常量、AI 参数 | test_config.py (22 用例) |
| `plants.json` | ~120 | 8 种作物完整参数（阈值/阶段/施肥/光照） | test_config.py |
| `sensors.py` | ~120 | ADC/DHT/拨码读取 + 校准 | test_runtime_edges.py |
| `actuators.py` | ~120 | 双继电器控制（水泵+补光灯）+ 安全超时 | test_runtime_edges.py |
| `status_strip.py` | ~260 | WS2812 11 灯珠（湿度温度计 + 12 种信号动画） | test_runtime_edges.py |
| `utils.py` | ~340 | 本地决策规则 + 信号收集 + 通用工具 | test_local_decision.py (24 用例) |
| `decision.py` | ~100 | AI 门控 + 决策编排 | test_runtime_edges.py |
| `action_runtime.py` | ~130 | 动作执行 + 信号广播 | test_runtime_edges.py |
| `ai_client.py` | ~180 | AI Prompt + HTTP 请求 + 响应解析 | test_ai_parse.py (15 用例) |
| `display.py` | ~250 | OLED 三页绘制 + 菜单/天数选择页 | test_runtime_edges.py |
| `display_runtime.py` | ~80 | OLED 生命周期管理（懒初始化/释放/advance_page） | 间接覆盖 |
| `buttons.py` | ~120 | ADC 模拟键盘（GPIO33 四键，8 次均值，nav_held 长按加速） | 间接覆盖 |
| `menu.py` | ~230 | OLED 菜单系统（植物/天数/手动控制/系统信息，蓝键统一返回） | 间接覆盖 |
| `telemetry.py` | ~80 | 遥测 POST + 信号/育种观察上报 | test_runtime_edges.py |

### 3.3 依赖注入模式

`main.py` 通过参数注入将副作用函数传入 runtime 模块，使测试可以用 mock 驱动：

```python
# main.py (简化)
state = SystemState()
loop_runtime.run(
    state=state,
    read_sensors=lambda: sensor_runtime.read(state),
    make_decision=lambda: decision.make_decision(state),
    execute_decision=lambda d: action_runtime.execute_decision(state, d),
    refresh_display=lambda **kw: display_runtime.refresh(state, **kw),
)
```

测试无需 monkey-patch 全局变量，直接传入 mock 函数即可。

---

## 4. 决策引擎

> **2026-05-30 重构**：云 AI（DeepSeek）已从 ESP32 移到树莓派侧（`tools/pi_advisor.py`）。
> ESP32 上不再有 `_should_request_ai` / `AI_*_DELTA` / `AI_MIN_FREE_MEM` / TLS 内存门控——
> 这些随 `ai_client.py` 一起删除。下面的 4.1 改为"三层降级"。

### 4.1 三层降级架构

决策从聪明到可靠分三层，上层挂了下层接住：

```
① DeepSeek（树莓派 tools/pi_advisor.py，serial_gateway --ai-advice 调用）
      └ 用 ESP32 report 建 prompt → 调 DeepSeek → advice 经 UART 回 ESP32
        ↓ 超时 / 没网 / 没 key
② 树莓派阈值规则（serial_gateway._heuristic_advice_from_report）
        ↓ UART 断 / 树莓派没了
③ ESP32 本地规则（utils.local_fallback_decision，板上常驻兜底）

ESP32 侧 main.make_decision：
    1. _take_pi_decision()：有在线 Pi advice 则经 _guard_pi_decision 安全门后优先采用
    2. 否则 decision.make_decision() → local_fallback_decision（②/① 不可达时的 ③）
```

ESP32 收到的每条 Pi advice 仍要过本地安全护栏（温度/时长）才会驱动执行器——Pi 只是建议者。

### 4.2 本地决策优先级

```
1. 土壤极度干燥 (< threshold - 15)  → water (救命优先，不受温度限制)
2. 低温 (≤ TEMP_LOW_C)              → idle  (跳过所有动作，含补光)
3. 土壤干燥 (< threshold, 非高温)    → water
4. 光照不足 (< light_min)            → light (不受高温浇水限制)
5. 高温 (≥ TEMP_HIGH_C)              → idle  (跳过浇水，但允许补光已由 #4 处理)
6. 一切正常                          → idle
```

每个决策返回：
```python
{
    "action": "water" | "light" | "idle",
    "duration_sec": int,
    "reason": str,
    "signals": ["WATER", "TEMP_HIGH", ...],  # Decision Plane 信号
    "breeding_observation": "..."              # 育种观察
}
```

### 4.3 AI 请求格式

AI 接收的 prompt 包含：
- 植物类型、生长天数、当前阶段
- 传感器读数（土壤/光照/温度/湿度）
- 今日累计日照时长
- 作物参数（阈值/光照需求/施肥配方）

AI 返回格式：
```json
{
  "action": "water",
  "duration_sec": 8,
  "reason": "soil moisture below threshold",
  "signals": ["WATER", "NEED_N"],
  "breeding_observation": "叶片边缘微卷，建议补充氮肥"
}
```

---

## 5. 启动顺序与内存管理

### 5.1 WiFi 优先启动

ESP32 WiFi 驱动初始化需要约 130KB 连续堆内存（10 个 rx 缓冲区 × 1600B）。
若 `utils.py` / `status_strip.py`（合计 22KB）先被加载，堆碎片会导致 OOM。

**启动顺序约定（严禁乱序）**：

```
main.py 顶层 import：仅 config / wifi_client / display_runtime / state（轻量）
    ↓
init_system() 开始：gc.collect() × 2 → wifi_client.connect()  ← 此时堆最干净
    ↓
import boot_runtime（拉入 utils / status_strip / actuators）
    ↓
boot_runtime.init_system()：sensors → actuators → utils.init_leds() → display init
```

`boot_runtime / sensor_runtime / action_runtime / decision / loop_runtime`
均改为首次调用时懒加载（函数内 `import`），不在 `main.py` 顶层 import。
违反此约定会导致 WiFi init 可用内存下降，出现 "Expected to init N rx buffer, actual is M" OOM。

### 5.2 UART 双层模式启动顺序

`UART_ENABLED=True` 且 `UART_SKIP_WIFI=True` 时，ESP32 跳过 WiFi，优先初始化 UART2，再加载重模块：

```
main.py 顶层 import：仅轻量模块
    ↓
init_system()：检测 UART_SKIP_WIFI → 跳过 wifi_client.connect()
    ↓
_init_uart_link()：UART2 GPIO17/16, rxbuf=256
    ↓
boot_runtime.init_system()：sensors → actuators → status_strip → OLED
    ↓
启动菜单：植物选择 → 天数选择 → 主循环
```

实机结论：UART 放在 OLED 之后会 `UART driver malloc error`；UART 放在 WiFi 之后但 OLED 之前，如果 WiFi 仍启用，会触发底层崩溃。因此双层模式必须把联网从 ESP32 移到树莓派侧。

### 5.3 AI 请求内存管理

AI 请求（直连 HTTPS TLS 握手）需要约 110KB 自由堆（`AI_MIN_FREE_MEM = 110000`）。
请求前 `decision.py` 调用 `release_display()` 释放 OLED 模块与帧缓冲（约 2KB）。
返回后 display 通过 `display_runtime.display()` 惰性重初始化。

**注意**：`release_display()` 会从 `sys.modules` 删除 `display` 模块，
`Menu._display` 持有的是旧模块引用（`_oled = None`）。
每次进入菜单前必须执行 `_menu._display = display_runtime.display()` 同步引用。

---

## 6. 按键交互

### 6.1 硬件

单 ADC 引脚（GPIO33）模拟键盘，4 个按键串联不同阻值产生不同电压：

| 颜色 | 功能 | ADC 实测 | 阈值范围 |
|------|------|---------|---------|
| 红 (UP) | 上翻 / 上一项 | ~3246 | 3201–3800 |
| 黄 (DOWN) | 下翻 / 下一项 | ~2840（最大 3166）| 2601–3200 |
| 绿 (OK) | 确认 / 进入 | ~2305 | 2201–2600 |
| 蓝 (BACK) | 返回 / 退出 | ~2030 | 200–2200 |

闲置时 ADC < 200（下拉到 GND）。

### 6.2 交互规则（全局统一，无长按）

```
红 / 黄  →  上下导航（主界面翻页 / 菜单滚动）
绿       →  确认 / 进入子菜单 / 执行手动动作
蓝       →  退出 / 返回上一层（任何层级均有效）
```

从主界面按蓝键直接进入主菜单，在任意菜单内按蓝键直接退出一层，无长按逻辑。

### 6.3 主循环按键轮询

`loop_runtime.run_loop()` 末尾以 100ms 为间隔轮询按键，持续约 900ms（即 1s 周期内有 9 次检测机会）：

```python
_t0 = time.ticks_ms()
while time.ticks_diff(time.ticks_ms(), _t0) < 900:
    if check_menu is not None:
        _triggered = check_menu()
        ...
    time.sleep_ms(100)
```

---

## 7. 安全机制

### 7.1 执行器安全

| 安全规则 | 常量 | 默认值 |
|---------|------|-------|
| 水泵单次最长运行 | `PUMP_MAX_RUN_SEC` | 60s |
| 补光灯单次最长运行 | `LIGHT_MAX_RUN_SEC` | 120s |
| 动作最小间隔 | `MIN_ACTION_INTERVAL` | 120s |
| 每小时最大动作次数 | `MAX_ACTIONS_PER_HOUR` | 12 |
| 温度安全护栏 | `TEMP_HIGH_C` / `TEMP_LOW_C` | 35℃ / 8℃ |

### 7.2 传感器降级

| 传感器 | 故障行为 | 降级值 |
|-------|---------|-------|
| 土壤湿度 | 返回 None → 本地规则用安全低值 | 20% |
| 光照 | 返回 None → 本地规则用安全低值 | 10% |
| DHT 温湿度 | 返回 None → 温度安全规则不生效 | None |

### 7.3 容错链

```
传感器故障 → 自动切安全值 → 继续运行
执行器运行中 → 跳过新动作 → 避免叠加
DeepSeek 超时/失败 → 树莓派阈值规则兜底 → 仍有 advice
树莓派/UART 断联 → ESP32 本地规则全自治 → 恢复后继续采纳 advice
Pi advice 过期 → 丢弃 → 回到本地规则
看门狗超时 → 硬件重启 → 自动恢复运行
```

---

## 8. 遥测与大屏

### 8.1 数据流

```
ESP32 ──UART JSON Line──▶ serial_gateway.py ──HTTP POST──▶ dashboard_server.py ──HTTP GET──▶ 浏览器
                            (树莓派)             (port 8790)         (contest-demo-dashboard.html)
```

ESP32 不直传遥测（`telemetry.py` 已于 2026-05-30 移除）；树莓派网关收到 `report` 后转发 `/api/state`。ESP32 的 `wifi=false` 是预期状态——树莓派才是联网节点。

### 8.2 遥测 Payload

```json
{
  "soil": 42, "light": 72, "temperature": 24.5, "humidity": 62,
  "plant": "生菜", "stage": "vegetative", "days": 15,
  "action": "idle", "duration": 0, "reason": "status normal",
  "signals": ["NEED_N"], "breeding_observation": "",
  "sun_hours": 3.2, "wifi": true, "ai": true,
  "read_count": 120, "action_count": 5, "error_count": 0,
  "uptime_sec": 7200, "decision_source": "cloud",
  "soil_threshold": 30, "light_min": 30, "light_opt": 50,
  "light_hours": [6, 8]
}
```

### 8.3 大屏布局

```
┌──────────────────────────────────────────────────────────────────────┐
│  太空农业智能种植舱                    [实时/演示] [WiFi] [AI]      │
├──────────────┬──────────────────────────┬───────────────────────────┤
│  SVG 圆弧仪表 │     种植舱 3D 可视化      │    智能决策               │
│  ┌─ 土壤 ─┐  │                          │    当前动作：待机          │
│  │  42%   │  │    [种植舱 SVG]           │    决策原因：环境正常      │
│  └────────┘  │                          │    ┌─ 决策信号 ─────────┐  │
│  ┌─ 光照 ─┐  │    土壤湿度/光照/温度      │    │ 💧 浇水  🌡️ 高温  │  │
│  │  72%   │  │    实时变化动画            │    │ 🌱 缺氮 (虚线框)  │  │
│  └────────┘  │                          │    └──────────────────┘  │
│  ┌─ 温度 ─┐  │                          │    育种观察：...          │
│  │  24.5℃ │  │                          │    [演示浇水]            │
│  └────────┘  │                          │                          │
│  ┌─ 湿度 ─┐  │    趋势曲线 (Canvas)      │    植物状态 / 系统健康    │
│  │  62%   │  │    土壤/光照/温度/湿度     │    执行记录              │
│  └────────┘  │                          │                          │
├──────────────┴──────────────────────────┴───────────────────────────┤
│  信号标签：physical=绿色实线边框  virtual=灰色虚线边框              │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 9. PC 端工具

### 9.1 dashboard_server.py

- 端口 8790，托管 `contest-demo-dashboard.html`
- `/api/state` GET 返回最新遥测，POST 接收 ESP32 上报
- `_validate_state` 白名单校验 + 范围钳位 + signals 过滤
- 超 120s 无数据标记为 stale，大屏自动切 DEMO 模式

### 9.2 ai_proxy.py（legacy）

- 端口 8787，HTTP→DeepSeek 的独立中转。早期供 ESP32 直发明文请求、代理替它扛 HTTPS。
- 2026-05-30 重构后 ESP32 不再调 AI，网关直接调 DeepSeek（见 9.4），此代理转为可选/历史工具。
- `_validate_decision` 白名单校验 action + signals + 截断 reason/observation；nutrient 静默 remap 为 idle。

### 9.3 serial_gateway.py

- 运行在树莓派，连接 `/dev/serial0`，默认 `115200 8N1`
- 收 ESP32 `report`，转为 dashboard `/api/state`
- 每 10 秒发送 `ping`，ESP32 自动返回 `pong`
- **`--ai-advice`**：收到 report 后调 DeepSeek（经 9.4 的 `pi_advisor`）→ advice 回 ESP32；AI 失败自动回退 `--auto-advice` 启发式
- `--auto-advice`：根据土壤/光照阈值生成保守建议（也是 `--ai-advice` 的本地兜底）
- `--test-advice water --test-duration 8`：收到首条 report 后只下发一次固定建议，用于验收“树莓派能让 ESP32 执行动作”
- `--dashboard` 默认取自环境变量 `SPACEFARM_DASHBOARD`（规避 openclaw 看门狗对 `board` 子串的误杀，见 §1.2 与 DEVLOG #41）
- 已做成开机自启服务 `spacefarm-gateway.service`（实机验收通过）

### 9.4 pi_advisor.py（DeepSeek 大脑，2026-05-30 从 ESP32 搬来）

- 树莓派侧的云 AI：`build_messages(report)` 建 prompt（镜像原 `ai_client.SYSTEM_PROMPT`）→ `DeepSeekAdvisor.advise()` 调 DeepSeek → `validate_decision` 归一为 advice
- key/model 走环境变量 `SPACEFARM_AI_API_KEY` / `SPACEFARM_AI_MODEL`（不进 argv：既避看门狗，也不让 key 出现在 `ps`）
- 纯 stdlib，HTTP 依赖注入，`tests/test_pi_advisor.py` 无网络可测；信号白名单与 `uart_link.VALID_SIGNALS` 跨端一致

---

## 10. 测试体系

| 测试文件 | 用例数 | 覆盖内容 |
|---------|-------|---------|
| test_config.py | 22 | 植物数据库完整性、安全常量、拨码编码 |
| test_local_decision.py | 24 | 本地决策优先级、温度安全、Decision Plane 信号 |
| test_runtime_edges.py | 16 | 硬件 mock、执行动作分支、WS2812、Pi advice、demo |
| test_pi_advisor.py | 11 | 树莓派 DeepSeek advisor：prompt/校验/HTTP注入/降级/信号白名单跨端一致 |
| test_dashboard_server.py | 7 | 遥测校验、nutrient remap、signals/breeding 透传 |
| test_utils.py | 9 | 时间格式化、移动平均、平滑值 |
| test_docs_quality.py | 2 | Markdown UTF-8 完整性、链接有效性 |
| test_loop_runtime.py | 3 | 主循环周期、传感器故障降级、UART poll/report 注入 |
| test_serial_gateway.py | 18 | 树莓派串口网关、心跳、advice、跨端协议兼容 |
| test_uart_link.py | 21 | ESP32 UART 编解码、ping/pong、advice 转换、在线超时 |
| **合计** | **133** | |

---

## 11. 跨文档不变量

以下数据在多处重复，修改时必须同步更新：

| 数据项 | 权威来源 | 需同步的镜像 |
|-------|---------|------------|
| 作物数量描述 | `plants.json` (8 条) | README.md, 评委展示方案.md, KT板设计文档.md, 选型报告.md |
| 测试用例数 | `py -m pytest` 输出 | README 徽章, 数据见证表, 测试指南.md, 本文测试表 |
| BOM 成本 | 选型报告.md BOM 表 (¥140/套) | README 徽章, KT板, 评委展示方案.md |
| 动作集 | `action_runtime.py` valid_actions | ai_client.SYSTEM_PROMPT, ai_proxy._validate_decision, dashboard_server._validate_state, 大屏 action labels |
| 信号类型 | `status_strip.py` 12 种常量 | ai_proxy._validate_decision 白名单, 大屏 SIGNAL_LABELS |
| AI 模型名 | `config.py` AI_MODEL | 评委展示方案.md Q&A, KT板技术参数表 |

---

## 12. 电源域与 WiFi 稳定性排查

> 2026-05-29 现场调试记录。**重要更正**：最初怀疑"12V 水泵继电器吸合导致 brownout"是误判——
> 当时 12V 电源根本没打开、水泵从未真正运转，brownout 属凭空假设。据此加的软件 hack
> （禁用 BOD、水泵脉冲分段）已于同日全部回退。详见 [DEVLOG/2026-05-29.md](./DEVLOG/2026-05-29.md) #34。

### 12.1 电源拓扑（推荐）

ESP32 与 12V 执行器**电源域隔离、仅共地**是最稳妥接法，避免执行器瞬态耦合进 ESP32 供电：

```
推荐（隔离 + 退耦）
┌─ USB 5V / 独立 5V ──── ESP32（VIN 加 1000µF + 0.1µF 退耦）
│
└─ 12V/2A ─┬── 水泵（电机/线圈两端 1N4007 续流）
           └── COB 灯（1N4007 续流）
       （共地，电源域隔离；WS2812 数据线串 470Ω，电源并 100µF）
```

> 反面教材：曾出现 USB 5V 与 12V→稳压器 5V **同时**接到 ESP32 5V 引脚，两路互灌，
> 既伤稳压器/USB 口，也让串口/WiFi 不稳。务必单一 5V 源。

### 12.2 实测结论（2026-05-29，独立供电下逐一验证）

| 假设 | 实测 | 结论 |
|------|------|------|
| 水泵继电器吸合 → brownout 复位 | 12V 开、水管入水、泵真转：全程**无复位**，仅 RSSI 短暂掉 ~10dB | ❌ 未复现，非根因（最初观察时 12V 没开，泵根本没转） |
| WS2812 关中断干扰 WiFi | 禁灯条后 WiFi 仍在 ~60s 掉线 | ❌ 排除 |
| 重连时 OOM（需 ~130KB 连续堆） | 改"软重连"不重建驱动后仍 20s 超时 | ❌ 非卡点 |
| **运行中掉线后无法重关联** | 开机能连(~5s)，运行 ~60s 掉线，软/硬重连均 20s 超时 | ✅ 真实现象，排查中 |

最强线索：轻量监听脚本（不发遥测）同一热点稳跑 135s+ 零掉线；完整 main.py 向云端
43.156.68.157 发遥测且一直 ETIMEDOUT，约 60s 后掉线。疑似"失败的遥测 POST"或"热点无外网"
是诱因，待验证。

### 12.3 现存软件兜底（仍在代码中）

```python
# _send_telemetry 内
if not wifi_client.is_connected():        # 基于 ifconfig[0] != "0.0.0.0" 判断
    if not wifi_client.connect(reset=False):  # 软重连优先，失败自动回退硬复位
        _wifi_fail_streak += 1
        if _wifi_fail_streak >= 3:
            machine.reset()               # 目前唯一已验证有效的 WiFi 恢复手段
```

> BOD 已恢复默认开启（移除禁用代码）；水泵已恢复连续运行（移除脉冲分段）。

### 12.4 调试工具

- `tools/serial_monitor.py`：pyserial 被动读 UART、不抢 raw REPL，绕过 mpremote 在
  main.py 自动运行后进不去 REPL 的问题。`py tools/serial_monitor.py 135 COM3`
- `esp32_firmware/diagnostics/wifi_stability.py`：WiFi 长时间在线监测 + RSSI，含可选
  STRESS 模式（脉冲水泵/补光灯，默认关）。用 `mpremote run` 执行。
