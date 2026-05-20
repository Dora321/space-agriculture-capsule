# 太空农业智能种植舱

这是一个面向教学和竞赛展示的智能种植舱项目。系统以 ESP32 为下位机，采集土壤湿度、光照、温湿度等环境数据，并通过本地规则和云端 AI 决策驱动浇水、营养液补充等动作；电脑端提供实时大屏，用于展示环境感知、决策过程和执行记录。

## 项目结构

```text
.
├── esp32_firmware/          # ESP32 MicroPython 固件
├── tools/                   # 本地/服务器辅助工具
├── tests/                   # Python 自动化测试
├── deliverables/            # 展示大屏、KT 板、评委材料等交付物
├── 智能种植舱控制器选型报告.md  # 硬件选型与接口说明
└── 测试指南.md                # 测试与验证说明
```

## 关键入口

- 固件说明：[esp32_firmware/README.md](./esp32_firmware/README.md)
- 实时大屏：[deliverables/contest-demo-dashboard.html](./deliverables/contest-demo-dashboard.html)
- 大屏部署说明：[deliverables/realtime-dashboard-guide.md](./deliverables/realtime-dashboard-guide.md)
- 交付物索引：[deliverables/README.md](./deliverables/README.md)
- 硬件选型：[智能种植舱控制器选型报告.md](./智能种植舱控制器选型报告.md)
- 测试说明：[测试指南.md](./测试指南.md)

## 快速开始

### 1. 启动实时大屏

在项目根目录运行：

```powershell
py tools/dashboard_server.py --host 0.0.0.0 --port 8790
```

浏览器打开：

```text
http://127.0.0.1:8790/
```

Windows 也可以使用脚本：

```powershell
powershell -ExecutionPolicy Bypass -File tools\start_dashboard_server.ps1
```

### 2. 配置 ESP32

复制 `esp32_firmware/config.py.example` 为 `esp32_firmware/config.py`，填写 Wi-Fi、AI 代理和 Dashboard 地址。`config.py` 包含密钥和本地配置，已经被 `.gitignore` 排除。

常用地址：

```python
AI_PROXY_URL = "http://43.156.68.157:8787/decision"
DASHBOARD_URL = "http://43.156.68.157:8790/api/state"
```

### 3. 运行测试

```powershell
py -m pytest
```

## Git 管理约定

- `esp32_firmware/config.py` 不提交，使用 `config.py.example` 作为模板。
- `deliverables/*preview*.png` 是本地截图预览，不提交。
- `deliverables/` 中正式交付物和草稿较多，新增文件前先查看 [deliverables/README.md](./deliverables/README.md)。
- 如果工作区同时有固件、测试和展示材料变更，提交时按主题拆分，避免把无关改动放进同一个 commit。
