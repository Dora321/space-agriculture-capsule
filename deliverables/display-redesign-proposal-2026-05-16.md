# OLED 显示模块改造设计方案

**日期**: 2026-05-16
**类型**: 功能规格书（设计方案）
**参与成员**: 方向明（主理人）

---

## TL;DR

- **核心目标**: 将 OLED 从"5行原始数据"升级为"3页轮播+有意义的信息展示"
- **关键决策**: 多页轮播（5s/页）+ 光照数据意义化（阈值对比+日照累计+决策联动）
- **下一步**: 按 P0/P1/P2 优先级分阶段实施，先改 display.py + plants.json，再改数据流

---

## 核心结论卡片

| 项目 | 内容 |
|------|------|
| 推荐方案 | 三页轮播 + 光照阈值化 + 累计日照 |
| 优先级 | P0（显示层改造）+ P1（数据层补齐）+ P2（决策层联动） |
| 预期影响 | 用户可读性大幅提升，光照从装饰变决策依据 |
| 资源需求 | display.py + main.py + plants.json + utils.py + ai_client.py + config.py.example |
| 风险等级 | 分阶段控制：P0低，P1/P2中低（涉及数据流和决策入参） |

---

## 1. 现状分析

### 1.1 当前 show_data() 布局（128x64, 8px字体, 约6个文本带可用）

```
y=0  : SPACE FARM v1.0     ← 固定标题，每帧浪费
y=12 : Plant:Lettuce        ← 仅植物名
y=24 : Soil:25% L:65%       ← 原始值，无阈值对比
y=36 : T:24C H:62%          ← OK
y=48 : Action:WATER         ← 仅动作名，无原因
y=56 : (心跳/轮次)          ← 仅被 show_overlay 占用
```

### 1.2 核心问题

| # | 问题 | 影响 |
|---|------|------|
| 1 | "SPACE FARM v1.0" 每帧占 y=0 | 浪费最宝贵的首行 |
| 2 | 缺少种植天数(D15)、生长阶段(SGL) | 用户最关心的信息只在串口 |
| 3 | 土壤湿度无阈值对比 | 看不出 25% 是否需要浇水 |
| 4 | 光照 L:65% 是"装饰数字" | 无阈值、无决策、无累计日照 |
| 5 | Action:WATER 无原因 | 不知道为什么浇水 |
| 6 | y=56 几乎未利用 | 正文只用了5行，底部状态区缺少规划 |
| 7 | WiFi/AI状态不在主屏 | 系统状态不可见 |

### 1.3 数据利用率

| 数据维度 | 已采集 | 串口输出 | OLED显示 | 决策使用 |
|----------|--------|----------|----------|----------|
| soil_moisture | Yes | Yes | Yes (原始值) | Yes |
| light_level | Yes | Yes | Yes (原始值) | **No** |
| temperature | Yes | Yes | Yes | AI only |
| humidity | Yes | Yes | Yes | AI only |
| days_since_planting | Yes | Yes | **No** | AI only |
| growth_stage | Yes | Yes | **No** | AI only |
| fert (施肥配方) | Yes | Yes | **No** | No |
| soil_threshold | Yes (JSON) | Yes | **No** | Yes |
| light_threshold | **No** | **No** | **No** | **No** |
| decision_reason | Yes | Yes | **No** | - |
| WiFi status | Yes | Yes | **No** | - |
| AI status | Yes | Yes | **No** | - |
| memory/uptime | Yes | Yes | **No** | - |

**利用率**: 13维数据，OLED仅展示5个原始值 = 38%

---

## 2. 多页轮播方案

### 2.1 轮播机制

```
Page 1 (5s) → Page 2 (5s) → Page 3 (5s) → Page 1 ...
```

- **轮播间隔**: 5000ms（可配置，`config.PAGE_ROTATE_SEC = 5`，同步更新 `config.py.example`）
- **中断机制**: 执行动作时暂停轮播，显示 show_action()，完成后恢复
- **错误覆盖**: show_error() 依然中断所有页面
- **页码指示**: 底部 3 个 3x3 像素方点，当前页实心；不使用 `● ○ ○` 等 Unicode 字符，避免 SSD1306 内置 ASCII 字体无法显示

### 2.2 Page 1 — 核心传感器（最重要，首屏）

```
y=0  : Lettuce    D15  SGL  WiFi
y=10 : Soil:25% <30% | WATER
y=20 : L:65%  >50%  | 6.2h/d
y=30 : T:24C  H:62%
y=40 : soil dry, water 8s
y=56 : [#][ ][ ]  (pixel dots)
```

**逐行说明**:

| 行 | 内容 | 格式 | 数据来源 |
|----|------|------|----------|
| y=0 | 植物名 + 天数 + 阶段缩写 + WiFi | `Lettuce D15 SGL WiFi` | plant_type, days_since_planting, growth_stage, wifi_connected |
| y=10 | 土壤湿度 + 阈值对比 + 状态 | `Soil:25% <30% | WATER` | soil_moisture, soil_threshold, action |
| y=20 | 光照 + 阈值对比 + 日照时长 | `L:65% >50% | 6.2h/d` | light_level, light_min, sun_hours_today |
| y=30 | 温湿度 | `T:24C H:62%` | temperature, humidity |
| y=40 | 决策原因 | `soil dry, water 8s` | decision.reason |

**阈值对比格式**:
- 低于阈值: `Soil:25% <30%`（单色屏用 `<` + `LOW/DRY` 文本表达，不依赖颜色）
- 高于阈值: `L:65% >50%`（单色屏用 `>` + `OK/BEST` 文本表达）
- 正常范围: `Soil:45% >30%`（保持静态文本，必要时可用反白矩形突出异常）

**生长阶段缩写**:

| 原文 | 缩写 | 中文含义 |
|------|------|----------|
| seedling | SGL | 幼苗期 |
| vegetative | VEG | 营养生长期 |
| flowering | FLR | 开花期 |
| fruiting | FRT | 结果期 |
| harvesting | HRV | 采收期 |

### 2.3 Page 2 — 生长状态

```
y=0  : Lettuce D15   SGL
y=10 : Stage: [====      ] 38%
y=20 : Fert:N    Water:light
y=30 : Sun:6.2h/8h  OK
y=40 : Next:VEG D8 (7d left)
y=56 : [ ][#][ ]  (pixel dots)
```

**逐行说明**:

| 行 | 内容 | 格式 | 数据来源 |
|----|------|------|----------|
| y=0 | 植物+天数+阶段 | `Lettuce D15 SGL` | 同Page1 |
| y=10 | 生长进度条+百分比 | `[====      ] 38%` | days_in_stage / stage_total_days |
| y=20 | 施肥配方+需水等级 | `Fert:N  Water:light` | growth_stage.fert, growth_stage.water_need |
| y=30 | 今日日照/目标+状态 | `Sun:6.2h/8h OK` | sun_hours_today, light_hours_target |
| y=40 | 下一里程碑+倒计时 | `Next:VEG D8 (7d left)` | next_stage_name, next_stage_start_day |

**进度条实现**:
- OLED 8x8 字体下，用 10 个字符宽度（80px）画进度条
- `[` + N个`=` + (10-N)个空格 + `]`
- 或用 `fill_rect` 画矩形进度条（更美观）

**生长进度计算**:
```python
# 当前阶段: seedling, days [0, 7], 当前第3天
# progress = 3 / (7 - 0 + 1) = 3/8 = 37.5% ≈ 38%
progress = (days_in_stage) / (stage_end_day - stage_start_day + 1)
```

**日照累计逻辑** (新增 state 字段):
```python
# state.sun_minutes_today: int  # 今日累计光照分钟数
# 每次读取传感器时:
#   if light_level >= plant_info["light_min"]:
#       state.sun_minutes_today += READ_INTERVAL / 60
# 显示: sun_hours_today = state.sun_minutes_today / 60
# 每日零点重置 sun_minutes_today
```

**需水等级缩写**:

| 原文 | 缩写 | 含义 |
|------|------|------|
| light | light | 少浇水 |
| normal | normal | 正常浇水 |
| heavy | heavy | 多浇水 |
| reduce | reduce | 控水 |

### 2.4 Page 3 — 系统状态

```
y=0  : WiFi:OK  192.168.1.5
y=10 : AI:DeepSeek  ON
y=20 : Mem:48KB  Up:3h20m
y=30 : Acts:3/12h  R25
y=40 : Last:water 8s @14:30
y=56 : [ ][ ][#]  (pixel dots)
```

**逐行说明**:

| 行 | 内容 | 格式 | 数据来源 |
|----|------|------|----------|
| y=0 | WiFi状态+IP | `WiFi:OK 192.168.1.5` | wifi_connected, wifi_client.get_ip() |
| y=10 | AI引擎+状态 | `AI:DeepSeek ON/OFF` | config.AI_MODEL, wifi_connected |
| y=20 | 内存+运行时长 | `Mem:48KB  Up:3h20m` | gc.mem_free(), time.time()-start_time |
| y=30 | 动作计数+轮次 | `Acts:3/12h  R25` | action_count, read_count |
| y=40 | 上次动作摘要 | `Last:water 8s @14:30` | last_action, last_action_time |

---

## 3. 光照数据意义化改造

### 3.1 plants.json 新增字段

每个植物增加 3 个光照相关字段（下方为带注释示例，实际 `plants.json` 需移除注释）:

```jsonc
{
  "生菜": {
    "soil_threshold": 30,
    "light_min": 30,       // 最低光照阈值（%），低于此值触发"光照不足"告警
    "light_opt": 50,       // 最适光照（%），达到此值为最佳状态
    "light_hours": [6, 8], // 每日目标日照时长范围（小时），[min, max]
    "water_sec": 8, "nutrient_sec": 5, "ventilate_sec": 30,
    "nutrient_interval": 259200,
    "growth_stages": [...]
  }
}
```

**14种植物光照参数表**:

| 植物 | light_min | light_opt | light_hours | 分类 |
|------|-----------|-----------|-------------|------|
| 生菜 | 30 | 50 | [6,8] | 耐阴叶菜 |
| 小白菜 | 30 | 50 | [6,8] | 耐阴叶菜 |
| 菠菜 | 25 | 45 | [6,8] | 半耐阴叶菜 |
| 韭菜 | 30 | 50 | [6,8] | 耐阴叶菜 |
| 番茄 | 50 | 70 | [8,12] | 喜光果菜 |
| 辣椒 | 45 | 65 | [8,10] | 中等光照果菜 |
| 黄瓜 | 45 | 65 | [8,10] | 中等光照果菜 |
| 茄子 | 45 | 65 | [8,10] | 中等光照果菜 |
| 豆角 | 40 | 60 | [7,10] | 中等光照 |
| 西葫芦 | 45 | 65 | [8,10] | 喜光果菜 |
| 萝卜 | 35 | 55 | [6,8] | 半耐阴根菜 |
| 大蒜 | 30 | 50 | [6,8] | 耐阴 |
| 葱 | 25 | 45 | [6,8] | 耐阴 |
| 生姜 | 20 | 40 | [4,6] | 喜阴 |

### 3.2 光照状态判定逻辑

```python
def get_light_status(light_level, plant_info):
    """
    判定光照状态
    返回: ("LOW"/"OK"/"BEST", 阈值显示文本)
    """
    light_min = plant_info.get("light_min", 30)
    light_opt = plant_info.get("light_opt", 50)
    
    if light_level < light_min:
        return "LOW", f"<{light_min}%"
    elif light_level < light_opt:
        return "OK", f">{light_min}%"
    else:
        return "BEST", f">{light_opt}%"
```

**OLED 显示示例**:
- 光照不足: `L:20% <30% | LOW`（单色静态标记，必要时仅 LOW 文本反白）
- 光照正常: `L:65% >50% | 6.2h/d`
- 光照最佳: `L:80% >70% | BEST`

### 3.3 累计日照时长

**新增 state 字段**:
```python
class SystemState:
    def __init__(self):
        # ... 现有字段 ...
        self.sun_minutes_today = 0    # 今日累计光照分钟数
        self.sun_date = ""            # 今日日期字符串，用于零点重置
```

**累计逻辑** (在 read_all_sensors() 中):
```python
def read_all_sensors():
    # ... 现有读取逻辑 ...
    
    # 日照累计
    today = f"{time.localtime()[0]}-{time.localtime()[1]}-{time.localtime()[2]}"
    if today != state.sun_date:
        state.sun_date = today
        state.sun_minutes_today = 0  # 新的一天，重置
    
    light_min = plant_info.get("light_min", 30)
    if state.light_level >= light_min:
        state.sun_minutes_today += config.READ_INTERVAL / 60
```

**显示**:
- Page 1: `L:65% >50% | 6.2h/d` — 当日累计日照小时数
- Page 2: `Sun:6.2h/8h OK` — 累计/目标 + 达标状态

**日照达标判定**:
```python
light_hours = plant_info.get("light_hours", [6, 8])
sun_hours = state.sun_minutes_today / 60
if sun_hours >= light_hours[0]:
    status = "OK"
else:
    status = "LOW"
```

### 3.4 光照数据接入决策

#### 3.4.1 本地规则（utils.py）

当前 `local_fallback_decision()` 完全忽略光照。改造后:

```python
def local_fallback_decision(
    soil, light, plant_info, last_nutrient, current_time,
    sun_minutes=0, uptime_sec=0
):
    # ... 现有土壤判断 ...
    soil_threshold = plant_info["soil_threshold"]
    
    # 新增: 光照不足建议（仅提示，不自动执行，因为无补光灯）
    light_min = plant_info.get("light_min", 30)
    light_hours_target = plant_info.get("light_hours", [6, 8])
    sun_hours = sun_minutes / 60
    
    if light < light_min:
        # 不自动触发动作（无补光灯硬件），但在 reason 中标注
        if soil >= soil_threshold:  # 土壤不缺水时才提示光照
            return {
                "action": "idle",
                "duration_sec": 0,
                "reason": f"light LOW({light}%<{light_min}%), move to sun"
            }
    
    # 日照不足也提示
    if sun_hours < light_hours_target[0] and uptime_sec > 43200:
        # 已过半天但日照不足
        pass  # 在 reason 中附加提示；utils.py 不直接引用 main.state
    
    # ... 原有逻辑 ...
```

**注意**: 由于当前硬件**没有补光灯**，光照不足只能**提示**用户手动移位，不能自动执行。未来接入补光灯后，可增加 `"action": "supplement_light"` 动作。

#### 3.4.2 AI 决策（ai_client.py）

在 AI prompt 中增加光照相关上下文:

```python
# 当前 ai_client.query_decision() 的 prompt 缺少光照规则
# 改造后增加:
prompt += f"""
Light rules:
- Current light: {light_level}%, plant min: {plant_info.get('light_min', 30)}%, optimal: {plant_info.get('light_opt', 50)}%
- Sun hours today: {sun_hours:.1f}h / target: {light_hours[0]}-{light_hours[1]}h
- If light < light_min, suggest moving plant to brighter location (no auto action available)
- Consider light level when deciding watering: low light = less evaporation = less water needed
"""
```

---

## 4. 代码改造清单

### 4.1 P0 — 显示层（立即可做，不影响控制逻辑）

| # | 文件 | 改动 | 工作量 |
|---|------|------|--------|
| 1 | display.py | 新增 `show_page1()` / `show_page2()` / `show_page3()` | 2h |
| 2 | display.py | 新增 `_draw_page_dots()` 页码指示（3x3像素点） | 0.5h |
| 3 | display.py | 删除/降级 "SPACE FARM v1.0" 标题 | 0.1h |
| 4 | main.py | 新增 `_page_index` / `_last_page_time` 轮播状态 | 0.5h |
| 5 | main.py | 主循环中调用轮播逻辑，替换 `show_data()` | 1h |
| 6 | config.py.example | 新增 `PAGE_ROTATE_SEC = 5` 示例配置 | 0.1h |
| 7 | display.py | 为 14 种植物补齐 `_PLANT_NAMES` 英文名映射 | 0.2h |

### 4.2 P1 — 数据层（让光照有阈值可用）

| # | 文件 | 改动 | 工作量 |
|---|------|------|--------|
| 8 | plants.json | 14种植物增加 light_min / light_opt / light_hours | 0.5h |
| 9 | main.py | state 新增 sun_minutes_today / sun_date | 0.2h |
| 9.1 | main.py | `read_all_sensors()` 增加日照累计 | 0.5h |
| 10 | display.py | Page1/2 光照行使用阈值对比格式 | 0.5h |
| 11 | display.py | Page2 进度条 + 里程碑计算 | 1h |

### 4.3 P2 — 决策层（让光照参与决策）

| # | 文件 | 改动 | 工作量 |
|---|------|------|--------|
| 12 | utils.py | `local_fallback_decision()` 增加 `light` / `sun_minutes` / `uptime_sec` 参数 | 1h |
| 13 | ai_client.py | AI prompt 增加光照规则上下文 | 0.5h |
| 14 | main.py | `make_decision()` 传递 light + sun_minutes + uptime_sec | 0.3h |

---

## 5. 关键设计决策

### 5.1 为什么是3页而不是2页或4页？

- **2页**: 传感器+生长/系统合为一页 → 信息过载，128px宽度不够
- **3页**: 传感器(核心) / 生长(关注) / 系统(运维) — 三类用户需求正交
- **4页**: 增加一页CO2/通风 → 但CO2传感器代码未实现，为时过早

### 5.2 为什么轮播5秒？

- 60秒采样间隔内，用户最多看12次轮播（每页4次）
- 5秒足够读完一页5行信息
- 太快(3s)看不完，太慢(10s)等不及看下一页

### 5.3 光照不足为什么不自动补光？

- **当前硬件无补光灯**，只有水泵/营养液泵/风扇
- 补光灯需要额外GPIO + 继电器通道
- 设计为**提示用户**移动种植舱位置
- 未来可扩展: 增加 `RELAY_LIGHT_PIN` + `"action": "supplement_light"`

### 5.4 进度条为什么用 fill_rect 而不是字符？

- 字符进度条 `[====      ]` 在8x8字体下占10字符=80px，效果一般
- `fill_rect(x, y, width, 6)` 可以画6px高的细条，更紧凑美观
- 但要注意: SSD1306 的 `fill_rect` 在 MicroPython 中性能OK

### 5.5 页码为什么用像素点而不是字符圆点？

- SSD1306 MicroPython 内置 `text()` 字体主要覆盖 ASCII，`●/○` 这类字符可能显示为空白或乱码
- 使用 `fill_rect()` / `rect()` 画 3x3 像素点可控、节省空间，且不占用 8px 字符行
- 页码点固定放在 y=56-62 区域，避免和右下角心跳 `*`、读取轮次 `R25` 抢同一块文本空间

### 5.6 y坐标间距为什么从12变为10？

- 64px 高度下，8px 字体采用 10px 行距，推荐正文行: y = 0, 10, 20, 30, 40
- y=50 可作为短状态/提示备用行；y=56-62 留给页码点和心跳，不再放完整文本
- 原 `y=0/12/24/36/48` 只能稳定放5行；改为 10px 行距后，在不挤压页码区的前提下提升信息密度

---

## 6. 数据流图（改造后）

```
sensors.read_all()
  ├─ soil_moisture ──┐
  ├─ light_level ────┤
  ├─ temp, hum ──────┤
  ├─ plant_type ─────┤
  └─ days, stage ────┤
                     ↓
              main.py: state 更新
              + sun_minutes_today 累计
              + light_status 判定
                     ↓
         ┌───────────┼───────────┐
         ↓           ↓           ↓
    Page 1       Page 2       Page 3
    传感器       生长状态     系统状态
    (5s)         (5s)         (5s)
         ↓           ↓           ↓
    display.show_page1/2/3()
    + _draw_page_dots()
```

---

## 7. Non-goals（明确不做）

- ❌ 不实现 CO2 页面（sensors.py 无 read_co2()）
- ❌ 不增加补光灯控制（当前无硬件）
- ❌ 不改变采样间隔（保持 60s）
- ❌ 不增加 OLED 触摸/按键翻页（无按键硬件）
- ❌ 不做中文显示（SSD1306 8x8 不支持中文字库）

---

## 8. 待确认问题

| # | 问题 | 选项 | 建议 |
|---|------|------|------|
| 1 | 是否增加 DIP 按键翻页？ | 是/否 | 否，保持自动轮播 |
| 2 | 执行动作时暂停轮播多久？ | 动作完成即恢复 / 显示3秒 | 动作完成即恢复 |
| 3 | 进度条用字符还是 fill_rect？ | 字符 / fill_rect | fill_rect（更美观） |
| 4 | 光照 LOW 时是否闪烁显示？ | 闪烁 / 静态文本/反白 | 静态标 `<30% LOW`（单色屏更稳定，闪烁费电） |
| 5 | Page3 的 IP 地址是否截断？ | 截断 / 滚动 | 截断后3段 `xxx.xxx.xxx.x` |

---

> 本方案由产品战略团队方向明设计，仅作为设计方案，未修改任何代码文件。
