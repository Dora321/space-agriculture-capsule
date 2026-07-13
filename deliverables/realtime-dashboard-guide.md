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
export SPACEFARM_VISION_DATA_DIR="/opt/spacefarm-dashboard/data/vision"
# 建议设置编辑口令；网页保存时填写同一口令
export SPACEFARM_EXPERIMENT_TOKEN="replace-with-a-random-token"
export DASHBOARD_TOKEN="replace-with-a-different-random-token"
export VISION_UPLOAD_TOKEN="replace-with-a-third-random-token"
export DASHBOARD_ALLOWED_ORIGIN="http://43.156.68.157:8790"
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
export DASHBOARD_TOKEN="replace-with-a-different-random-token"
export VISION_UPLOAD_TOKEN="replace-with-a-third-random-token"
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
- `/api/vision/events?limit=4`
- `/api/vision/images/{event_id}`
- `/api/screening/latest`

`spacefarm-vision-sync.service` 从树莓派 SQLite 中租约一个未同步事件，先上传 JPEG，再幂等提交分析 JSON。成功才标记完成；失败按 30 秒起步指数退避，服务重启后 outbox 仍在。云端把图片写入专用目录、元数据写入 SQLite，因此 Dashboard 重启不会丢失最近视觉结果。

筛选写入统一使用 `POST /api/screening/results`，输入必须是 `screening.input.v1` 的候选/对照逐周期分数。服务端自行复算独立周期数、ΔControl 中位数、IQR、优于对照比例、表型加权分和证据等级；客户端上传的派生数字会被忽略。

## 生产安全

- `/api/state` 使用 `DASHBOARD_TOKEN`；视觉和筛选写接口使用 `VISION_UPLOAD_TOKEN`。
- 未配置令牌时，服务端只允许本机 loopback 写入，公网写请求返回 503。
- CORS 只允许 `DASHBOARD_ALLOWED_ORIGIN` 的精确 origin，不发送 `Access-Control-Allow-Origin: *`。
- 当前公网仍是 HTTP。正式长期运行应在前面增加 HTTPS 反向代理，避免令牌明文传输。
