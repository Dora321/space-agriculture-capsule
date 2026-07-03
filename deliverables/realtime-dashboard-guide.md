# 实时大屏部署说明

当前架构只有树莓派联网。ESP32 通过 UART 把 `report` 发给树莓派，`serial_gateway.py` 再把遥测 POST 到大屏；不要向 ESP32 上传旧的 `telemetry.py` 或配置 Dashboard URL。

## 腾讯云地址

```text
http://43.156.68.157:8790/
http://43.156.68.157:8790/api/state
```

腾讯云安全组需允许 TCP 8790。公网接口为只读展示用途，不提供远程执行器控制。

## 启动 Dashboard

```bash
python3 tools/dashboard_server.py --host 0.0.0.0 --port 8790
```

本地浏览器打开 `http://127.0.0.1:8790/`。Windows 也可运行：

```powershell
powershell -ExecutionPolicy Bypass -File tools\start_dashboard_server.ps1
```

## 树莓派网关

```bash
export SPACEFARM_DASHBOARD="http://43.156.68.157:8790/api/state"
python3 tools/serial_gateway.py \
  --port /dev/serial0 \
  --baud 115200 \
  --ai-advice \
  --plants-json esp32_firmware/plants.json
```

正式设备使用 `spacefarm-gateway.service` 开机自启。Dashboard 失败不会阻塞 UART 或 ESP32 本地规则。

## 视觉接口

`groundstation.html` 另外读取：

- `/api/vision/status`
- `/api/vision/latest`
- `/api/vision/image`
- `/api/screening/latest`

Camera Module 3 当前把结果保存在树莓派 SQLite。树莓派到腾讯云的图片和视觉 JSON 同步尚未实现，因此云端视觉接口可能返回 `{"available": false}`；这不代表摄像头不可用。
