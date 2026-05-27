# 实时大屏使用说明

## 腾讯云推荐端口

保留原有 AI 代理：

```text
http://43.156.68.157:8787/decision
```

实时大屏新开端口：

```text
http://43.156.68.157:8790/
http://43.156.68.157:8790/api/state
```

腾讯云安全组需要额外放行：

```text
TCP 8790
来源 0.0.0.0/0
```

## 1. 启动电脑端 Dashboard

在项目根目录运行：

```bash
py tools/dashboard_server.py --host 0.0.0.0 --port 8790
```

浏览器打开：

```text
http://127.0.0.1:8790/
```

如果部署在腾讯云服务器上，浏览器打开：

```text
http://43.156.68.157:8790/
```

Windows 服务器也可以直接运行：

```powershell
powershell -ExecutionPolicy Bypass -File tools\start_dashboard_server.ps1
```

## 2. 配置 ESP32

在 `esp32_firmware/config.py` 中设置：

```python
DASHBOARD_URL = "http://43.156.68.157:8790/api/state"
DASHBOARD_TOKEN = ""
DASHBOARD_TIMEOUT = 2
```

如果启用了令牌，电脑端先设置环境变量 `DASHBOARD_TOKEN`，ESP32 的
`DASHBOARD_TOKEN` 也填同一个值。

## 3. 上传新增文件

```bash
py -m mpremote connect COM3 cp telemetry.py :
py -m mpremote connect COM3 cp main.py :
py -m mpremote connect COM3 cp config.py :
```

AI 代理保持原来的端口，不要改成 8790：

```python
AI_PROXY_URL = "http://43.156.68.157:8787/decision"
DASHBOARD_URL = "http://43.156.68.157:8790/api/state"
```

## 4. 工作方式

- 有 ESP32 实时上报时，网页自动显示 `LIVE`。
- 没有实时数据或超过 120 秒未更新时，网页自动回到 `DEMO` 演示动画。
- 上报失败不会影响浇水、本地规则或 AI 决策，只会在串口打印日志。
