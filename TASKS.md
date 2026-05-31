# TASKS.md — 当前任务与待办

> 历史工作记录见 [DEVLOG/](./DEVLOG/)

## 当前冲刺

### 电源/EMI（最紧迫，#33 后留下）

- [ ] **12V 水泵/灯走独立电源** — 不要与 ESP32 USB 共享，根治 brownout（见 [DEVLOG/2026-05-29.md](./DEVLOG/2026-05-29.md) #33）
- [ ] **ESP32 VIN 加 1000µF + 0.1µF 退耦电容** — 吸收继电器吸合的瞬态压降
- [ ] **继电器线圈反接 1N4007 续流二极管** — 抑制断开尖峰 EMI
- [ ] **WS2812 数据线串 470Ω + 电源 100µF 退耦** — 降低对 WiFi 2.4G 的串扰
- [x] ~~验证 WiFi 沉默掉线根因~~ — **已随双层重构作废**：ESP32 不再使用 WiFi，联网由树莓派承担
- [x] ~~AI 代理 EHOSTUNREACH 复查~~ — **已作废**：DeepSeek 改由树莓派 `pi_advisor` 调用，ESP32 不再走代理

### 比赛前收尾

- [ ] **比赛现场彩排** — 验证菜单交互流程（蓝键进/退/蓝键返回），确认评委能独立操作
- [ ] **config.py.example 检查** — `PAGE_ROTATE_SEC=0` 表示关闭自动翻页，与 display_runtime.py 逻辑对齐
- [ ] **决定是否开启 NTP** — `NTP_SYNC_ON_CONNECT` 当前 False 导致 Day 永远=0、生长阶段算错；现场如演示天数则改 True
- [ ] **现场目视确认浇水执行** — `--test-advice water` 的 advice 已实机下发，但 8s 水泵是否真出水仅剩现场目视确认（遥测侧 round-trip 已通，`ai_src=pi`）
- [ ] **按键长期可靠** — 已换元器件、三键解码干净（#43）；比赛前再确认长期稳定，可选微调红键阈值（3137/3242 卡 3200 边界），并保持 `STARTUP_MENU_ON_BOOT=True`
- [ ] **大屏离线字体本地化** — `groundstation.html` 用 Google Fonts CDN；离线 Pi 会回退系统字体，需要时下载 woff2 内嵌
- [ ] **分支合并 master** — `refactor/remove-wifi-only-path` 重构 + 大屏全部实机验收通过后合并并推送

## P1 待办

- [ ] **育种观察日志大屏面板** — AI 返回的 `breeding_observation` 在大屏上展示为时间线（当前仅显示最新一条）
- [ ] **KT 板 Decision Plane 架构说明** — 在 `deliverables/KT板展示设计-最新版.md` 增加「决策平面/执行平面」模块图和信号类型表
- [ ] **智能种植舱控制器选型报告更新** — BOM 增加补光灯继电器 + COB 灯条，成本更新为 ¥140/套

## P2 待办

- [ ] **大屏信号触发演示按钮** — KT 板增加手动触发特定信号动画的按钮（演示用，不控制真实硬件）
- [ ] **信号动画强度分级** — 同一信号根据严重程度（如 TEMP_HIGH 36℃ vs 42℃）使用不同动画频率/亮度

## 已完成

| 日期 | 任务 | 详见 |
|------|------|------|
| 2026-05-31 | #44 地面站监控大屏 `groundstation.html`：retro-futuristic 航天控制台，接真实 `/api/state`（网关增强转发 AI reason/signals/育种观察）；DeepSeek 中文输出；北京时间/2035/育种团队/去界面英文；顶替云端大屏 | [DEVLOG/2026-05-31.md](./DEVLOG/2026-05-31.md) |
| 2026-05-31 | #43 重构实机验收：ESP32 烧新固件、DeepSeek 在 Pi 全链路跑通（`ai_src=pi`）；按键接触不良→换元器件修复；天数从 1 起算（OLED/大屏统一）；移除 2035 模式切换 | [DEVLOG/2026-05-31.md](./DEVLOG/2026-05-31.md) |
| 2026-05-30 | #42 砍单层老路 + DeepSeek 搬到树莓派（分支 `refactor/remove-wifi-only-path`，133 测试绿）：删 wifi_client/telemetry/ai_client，固件固定走双层；新增 `tools/pi_advisor.py` + `serial_gateway --ai-advice` 让 Pi 调 DeepSeek；三层降级成型 | [DEVLOG/2026-05-30.md](./DEVLOG/2026-05-30.md) |
| 2026-05-30 | 树莓派端实机验收完成（#39-41）：`/dev/serial0` 全链路跑通（report/ping/pong/advice，`ai_src=pi`）；清掉共地松动、mini-UART 控制台争用（移除 `console=serial0`）、openclaw 看门狗 `board` 误杀三坑；`serial_gateway` 做成开机自启 systemd 服务转发云端大屏 | [DEVLOG/2026-05-30.md](./DEVLOG/2026-05-30.md) |
| 2026-05-30 | 树莓派双层架构阶段二：ESP32 UART 主循环接入 + Pi 网关 auto/test advice 下发 + 实机 UART 初始化；UART 模式跳过 ESP32 WiFi | [DEVLOG/2026-05-30.md](./DEVLOG/2026-05-30.md) |
| 2026-05-29 | #33 Brownout 根因定位 + 软件兜底：BOD 禁用 + 水泵脉冲 + is_connected 基于 IP + machine.reset 兜底 | [DEVLOG/2026-05-29.md](./DEVLOG/2026-05-29.md) |
| 2026-05-29 | #32 WiFi 重连冻结根治：单次 8s 替代 smart_connect 3×25s，最长冻结 77s→9s | [DEVLOG/2026-05-29.md](./DEVLOG/2026-05-29.md) |
| 2026-05-29 | #31 开机/菜单天数选择：nav_held 长按加速 + show_day_select + state.manual_day | [DEVLOG/2026-05-29.md](./DEVLOG/2026-05-29.md) |
| 2026-05-29 | #30 手动操作后卡页修复：去除 sensor 块 reset_page=True + 菜单退出重置 last_read | [DEVLOG/2026-05-29.md](./DEVLOG/2026-05-29.md) |
| 2026-05-29 | #29 手动控制真实执行：直接调用 actuators.run_water_pump/run_light，删除无效 state 字段 | [DEVLOG/2026-05-29.md](./DEVLOG/2026-05-29.md) |
| 2026-05-29 | #28 开机闪第 1 页修复：boot_runtime 传入 refresh_display=None，选完才首次渲染 | [DEVLOG/2026-05-29.md](./DEVLOG/2026-05-29.md) |
| 2026-05-29 | #27 菜单交互统一：删除所有长按逻辑，蓝键单击统一返回 | [DEVLOG/2026-05-29.md](./DEVLOG/2026-05-29.md) |
| 2026-05-29 | #26 菜单黑屏修复：display 引用同步，删除无效 release/init 对 | [DEVLOG/2026-05-29.md](./DEVLOG/2026-05-29.md) |
| 2026-05-29 | #25 按键响应：主循环 10Hz 轮询 + DOWN 阈值修正 + ADC 8 次均值 | [DEVLOG/2026-05-29.md](./DEVLOG/2026-05-29.md) |
| 2026-05-29 | #24 WiFi OOM 根治：重模块懒加载 + WiFi 先于 utils/status_strip 连接 | [DEVLOG/2026-05-29.md](./DEVLOG/2026-05-29.md) |
| 2026-05-28 | #18-23 Decision Plane / Action Plane 架构升级 | [DEVLOG/2026-05-28.md](./DEVLOG/2026-05-28.md) |
| 2026-05-28 | 实机烧录验证：WiFi 已连通、遥测上报正常、Dashboard 收到数据 | git `39f918a` |
| 2026-05-27 | 12V COB 补光灯执行器（GPIO18 继电器低电平触发） | git `71df7ce` |
| 2026-05-27 | 比赛 2035 主题冲刺——KT板/话术/大屏/工作日志/演示脚本 | git `d36b728` |
