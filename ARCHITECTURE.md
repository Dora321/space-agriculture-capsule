# ARCHITECTURE.md — 太空农业智能种植舱系统架构

## 1. 系统总览

```
┌──────────────────────────── 太空舱端（ESP32 + MicroPython）────────────────────────────┐
│                                                                                         │
│  ┌── SENSE ──────────────┐  ┌── THINK ───────────────┐  ┌── ACT ──────────────────┐    │
│  │ 🌡️ 土壤 ADC GPIO34   │  │                        │  │ 💧 水泵 继电器 GPIO5    │    │
│  │ ☀️ 光照 ADC GPIO32   │──▶│ 🤖 云端 AI (DeepSeek) │──▶│ 💡 补光灯 继电器 GPIO18 │    │
│  │ 🌡️ 温湿 DHT11 GPIO4 │  │ 📋 本地规则引擎       │  │ 🌈 WS2812 GPIO26       │    │
│  │ 🔢 拨码 ×3 位        │  │                        │  │                        │    │
│  └───────────────────────┘  └────────────────────────┘  └────────────────────────┘    │
│          │                           │                          │                       │
│          ▼                           ▼                          ▼                       │
│  ┌── OLED SH1106 ─────────── Decision Plane Signals ─── Action Plane ──────────┐       │
│  │  三页轮播（传感器/生长/系统）  WS2812 12 种信号动画    水泵+补光灯执行   │       │
│  └──────────────────────────────────────────────────────────────────────────────┘       │
└───────────────────────────────────────│─────────────────────────────────────────────────┘
                                        │ WiFi · HTTP POST
                                        ▼
                        ┌── 地面遥测站（PC / 云服务器）──────────────┐
                        │  📊 Web 实时大屏 (port 8790)              │
                        │  🤖 AI 代理中转 (port 8787)              │
                        │  单向接收 · 无反向控制通道               │
                        └───────────────────────────────────────────┘
```

**自治边界**：太空舱端所有模块（含 AI 在线/离线两种模式）均独立运行，不依赖地面实时指令。地面遥测站仅做被动监控，单向接收数据，不向 ESP32 下发控制命令。

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
| `display.py` | ~200 | OLED 三页绘制 | test_runtime_edges.py |
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

### 4.1 双引擎架构

```
         ┌──────────────┐
         │ make_decision │
         └──────┬───────┘
                │
    1. 始终计算本地规则（local_fallback_decision）
                │
    2. _should_request_ai 检查三个触发条件
       ├── 阈值事件（土壤/光照/温度越界）
       ├── 传感器变化量 > AI_*_DELTA
       └── 周期复核（距上次 AI 请求 > AI_MIN_REQUEST_INTERVAL）
                │
    3. AI 允许时，额外检查 free heap ≥ AI_MIN_FREE_MEM
       └── 使用代理时跳过 heap 检查（代理走 HTTP，无 TLS 开销）
                │
    4. AI 成功 → 返回 AI 决策；AI 失败 → 返回本地规则结果
```

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

## 5. 安全机制

### 5.1 执行器安全

| 安全规则 | 常量 | 默认值 |
|---------|------|-------|
| 水泵单次最长运行 | `PUMP_MAX_RUN_SEC` | 60s |
| 补光灯单次最长运行 | `LIGHT_MAX_RUN_SEC` | 120s |
| 动作最小间隔 | `MIN_ACTION_INTERVAL` | 120s |
| 每小时最大动作次数 | `MAX_ACTIONS_PER_HOUR` | 12 |
| 温度安全护栏 | `TEMP_HIGH_C` / `TEMP_LOW_C` | 35℃ / 8℃ |

### 5.2 传感器降级

| 传感器 | 故障行为 | 降级值 |
|-------|---------|-------|
| 土壤湿度 | 返回 None → 本地规则用安全低值 | 20% |
| 光照 | 返回 None → 本地规则用安全低值 | 10% |
| DHT 温湿度 | 返回 None → 温度安全规则不生效 | None |

### 5.3 容错链

```
传感器故障 → 自动切安全值 → 继续运行
执行器运行中 → 跳过新动作 → 避免叠加
AI 超时/失败 → 本地规则兜底 → 不中断控制
WiFi 断联 → 本地规则全自治 → 恢复后自动重连
堆内存不足 → 跳过 AI 请求 → 避免 TLS OOM
看门狗超时 → 硬件重启 → 自动恢复运行
```

---

## 6. 遥测与大屏

### 6.1 数据流

```
ESP32 ──HTTP POST──▶ dashboard_server.py ──HTTP GET──▶ 浏览器
         (telemetry.py)    (port 8790)         (contest-demo-dashboard.html)
```

### 6.2 遥测 Payload

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

### 6.3 大屏布局

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

## 7. PC 端工具

### 7.1 dashboard_server.py

- 端口 8790，托管 `contest-demo-dashboard.html`
- `/api/state` GET 返回最新遥测，POST 接收 ESP32 上报
- `_validate_state` 白名单校验 + 范围钳位 + signals 过滤
- 超 120s 无数据标记为 stale，大屏自动切 DEMO 模式

### 7.2 ai_proxy.py

- 端口 8787，ESP32 发 HTTP（非 HTTPS）到此代理
- 代理转发 HTTPS 到 DeepSeek/OpenAI，避免 ESP32 TLS 内存压力
- `_validate_decision` 白名单校验 action + signals + 截断 reason/observation
- nutrient 动作静默 remap 为 idle

---

## 8. 测试体系

| 测试文件 | 用例数 | 覆盖内容 |
|---------|-------|---------|
| test_config.py | 22 | 植物数据库完整性、安全常量、拨码编码 |
| test_local_decision.py | 24 | 本地决策优先级、温度安全、Decision Plane 信号 |
| test_ai_parse.py | 15 | AI 关键词解析、light/nutrient 动作、signals 默认值 |
| test_runtime_edges.py | 17 | 硬件 mock、执行动作分支、WS2812、AI 门控、遥测 |
| test_dashboard_server.py | 7 | 遥测校验、nutrient remap、signals/breeding 透传 |
| test_utils.py | 9 | 时间格式化、移动平均、平滑值 |
| test_docs_quality.py | 2 | Markdown UTF-8 完整性、链接有效性 |
| test_loop_runtime.py | 2 | 主循环周期、传感器故障降级 |
| **合计** | **101** | |

---

## 9. 跨文档不变量

以下数据在多处重复，修改时必须同步更新：

| 数据项 | 权威来源 | 需同步的镜像 |
|-------|---------|------------|
| 作物数量描述 | `plants.json` (8 条) | README.md, 评委展示方案.md, KT板设计文档.md, 选型报告.md |
| 测试用例数 | `py -m pytest` 输出 | README 徽章, 数据见证表, 测试指南.md |
| BOM 成本 | 选型报告.md BOM 表 (¥140/套) | README 徽章, KT板, 评委展示方案.md |
| 动作集 | `action_runtime.py` valid_actions | ai_client.SYSTEM_PROMPT, ai_proxy._validate_decision, dashboard_server._validate_state, 大屏 action labels |
| 信号类型 | `status_strip.py` 12 种常量 | ai_proxy._validate_decision 白名单, 大屏 SIGNAL_LABELS |
| AI 模型名 | `config.py` AI_MODEL | 评委展示方案.md Q&A, KT板技术参数表 |
