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

### 当前实机收尾

- [ ] **恢复 ESP32 UART report** — 网关在线但视觉数据库尚未收到新遥测，自动拍照保持 `WAITING_TELEMETRY`
- [ ] **烧录最新版 ESP32 固件** — 云端与 Pi 已部署实验日龄链；需通过 ESP32 USB/REPL 上传 `main.py`、`uart_link.py`、`state.py` 和实际 `config.py`，OLED/本地生长阶段才会接收 Pi 的 `experiment` 日龄消息
- [ ] **初始化首个正式实验** — 打开云端大屏“实验设置”，填写真实实验编号、作物和播种日期；不要使用默认值代替真实记录
- [ ] **标定 Camera Module 3 固定 ROI** — 按真实四分区花盆确定坐标；图像质量只评价种植区，不用整图背景分数
- [ ] **现场目视确认浇水执行** — `--test-advice water` 已能下发，仍需确认水泵真实出水和回水
- [x] **统一种植日龄来源** — 网页初始化播种日期，云端持久化；Pi 每 30 秒同步并缓存，以 D1 起算后经 UART 同步 ESP32，按键仅离线兜底
- [ ] **比赛现场彩排** — 验证四合一模拟按键、OLED、大屏、断网降级和讲解流程

## P1 待办

- [ ] **树莓派→腾讯云视觉同步** — 图片、分析 JSON 和筛选结果分开上传，断网进入 outbox，恢复后限速补传
- [ ] **人工复核入口** — 允许确认/纠正作物、可见异常和候选结论，保留操作者与时间
- [ ] **固定对照实验** — 同作物设置 P1 对照、P2–P4 候选，至少 3 个独立周期，推荐 5 个
- [ ] **大屏时间线** — 展示最近有效图片、人工复核和跨周期证据，不生成虚构视觉观察

## P2 待办

- [ ] **大屏离线字体本地化** — 移除 Google Fonts 运行时依赖
- [ ] **图片保留策略** — 明确原图、ROI、失败图和 API 结果的磁盘配额与清理周期
- [ ] **模型校准集** — 用真实舱内图片评估 `qwen3.7-plus` 的拒识、异常描述和人工一致率

## 已完成

| 日期 | 任务 | 详见 |
|------|------|------|
| 2026-06-05 | #47 KT 板重做（HyperFrames/纯 HTML，1200×600mm，`board.pdf` 可印；移入 `deliverables/kt-board/`）+ 反向同步仓库不变量：测试 159、成本 ¥135、作物切换改四合一模拟按键（README/ARCHITECTURE/CLAUDE 已同步，深层镜像见 P2） | [DEVLOG/2026-06-05.md](./DEVLOG/2026-06-05.md) |
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
