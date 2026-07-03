# Camera Module 3 视觉链路部署

该链路只用于 AI 早期表型筛选，不参与水泵和补光灯控制。ESP32 即使在摄像头、网络或多模态 API 故障时也继续按原控制逻辑运行。

## 1. 树莓派依赖

```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-opencv python3-numpy
```

先用系统工具复验摄像头：

```bash
rpicam-still -o camera-test.jpg
```

## 2. 配置固定 ROI

复制 `config/vision_experiment.example.json` 为 `config/vision_experiment.json`。示例坐标来自当前 2304×1296 四分区圆盆构图，P1 为右下对照区；相机或花盆位置变化后必须重新测量 `x/y/width/height`，同一轮实验中不得移动机位。

复制 `config/vision.env.example` 到 `/home/mx/spacefarm/.config/vision.env`，填写多模态 API 地址、密钥和支持图像输入的模型名，并设置权限为 `600`。API 密钥不要提交到 Git。

UART 网关环境增加：

```bash
SPACEFARM_VISION_DB=/home/mx/spacefarm/data/vision/vision.sqlite3
```

视觉上下文中的 `day` 不再依赖 ESP32 时钟。先在地面站顶部“实验设置”初始化播种日期；树莓派会把 `/api/experiment` 缓存到 `/var/lib/spacefarm/experiment.json`，再将权威日龄写入视觉遥测。

## 3. 手动联调

终端一：启动 UART 网关，并让它把最新遥测非阻塞地镜像到视觉数据库。

```bash
python3 tools/serial_gateway.py --vision-db /var/lib/spacefarm/vision/vision.sqlite3
```

终端二：每 10 分钟检查一次；仅在遥测新鲜、距离上次拍照满 2 小时且光照达到作物阈值时拍照。

```bash
python3 tools/vision_service.py capture --experiment config/vision_experiment.json
```

终端三：消费本地队列并调用远程多模态 API。

```bash
python3 tools/vision_service.py api-loop
```

网页服务器会提供 `/api/vision/status`、`/api/vision/latest`、`/api/vision/image` 和 `/api/screening/latest`。`deliverables/groundstation.html` 每 10 秒独立刷新视觉面板。

## 4. 科学口径

- 两小时照片是同一植株的重复测量，不增加独立样本量 `n`。
- `n` 只统计完成的独立种植周期；至少 3 轮才可给出 B 级初步证据，建议 5 轮。
- 候选材料只与同周期固定对照比较，展示 `ΔControl`、IQR 和优于对照的周期比例。
- 当前共享水泵、补光和单土壤传感器，因此资源响应只占 5 分，不能宣称单盆资源利用效率。
