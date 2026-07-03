# 实时大屏部署说明

当前架构只有树莓派联网。ESP32 通过 UART 把 `report` 发给树莓派，`serial_gateway.py` 再把遥测 POST 到大屏；不要向 ESP32 上传旧的 `telemetry.py` 或配置 Dashboard URL。

## 腾讯云地址

```text
http://43.156.68.157:8790/
http://43.156.68.157:8790/api/state
http://43.156.68.157:8790/api/experiment
```

腾讯云安全组需允许 TCP 8790。`/api/state` 和视觉结果为只读展示；`POST /api/experiment` 只修改实验元数据，不提供远程执行器控制。

## 启动 Dashboard

```bash
export SPACEFARM_EXPERIMENT_FILE="/opt/spacefarm-dashboard/data/experiment.json"
# 建议设置编辑口令；网页保存时填写同一口令
export SPACEFARM_EXPERIMENT_TOKEN="replace-with-a-random-token"
python3 tools/dashboard_server.py --host 0.0.0.0 --port 8790
```

本地浏览器打开 `http://127.0.0.1:8790/`。Windows 也可运行：

```powershell
powershell -ExecutionPolicy Bypass -File tools\start_dashboard_server.ps1
```

## 树莓派网关

```bash
export SPACEFARM_DASHBOARD="http://43.156.68.157:8790/api/state"
export SPACEFARM_EXPERIMENT_FILE="/var/lib/spacefarm/experiment.json"
# 云端启用口令时，Pi 必须使用同一值
export SPACEFARM_EXPERIMENT_TOKEN="replace-with-a-random-token"
python3 tools/serial_gateway.py \
  --port /dev/serial0 \
  --baud 115200 \
  --ai-advice \
  --plants-json esp32_firmware/plants.json
```

正式设备使用 `spacefarm-gateway.service` 开机自启。Dashboard 失败不会阻塞 UART 或 ESP32 本地规则。

## 初始化种植日期

1. 打开大屏，点击顶部“实验设置”。
2. 填写实验编号、作物、播种日期；播种当天为 D1。
3. 只有确需纠偏时才填写“日龄修正”，并填写操作者。
4. 保存后云端持久化配置，树莓派最长约 30 秒拉取并落盘。
5. 树莓派用该日龄覆盖设备旧值，并通过独立 UART `experiment` 消息同步给 ESP32。

断网时树莓派使用本地缓存继续计算。ESP32 菜单中的 `Set Day` 只用于 Pi 长期离线的临时应急，不反向覆盖正式实验记录。

## 视觉接口

`groundstation.html` 另外读取：

- `/api/vision/status`
- `/api/vision/latest`
- `/api/vision/image`
- `/api/screening/latest`

Camera Module 3 当前把结果保存在树莓派 SQLite。树莓派到腾讯云的图片和视觉 JSON 同步尚未实现，因此云端视觉接口可能返回 `{"available": false}`；这不代表摄像头不可用。
