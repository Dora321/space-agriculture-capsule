# 树莓派 SSH 与 Camera Module 3 拍照指南

本文用于项目现场调试，说明如何连接树莓派、调用 Camera Module 3、手动拍照，以及在电脑上查看或保存照片。

## 1. 当前设备参数

| 项目 | 当前配置 |
| --- | --- |
| 树莓派地址 | `192.168.125.121` |
| SSH 用户 | `mx` |
| SSH 端口 | `22` |
| 主机名 | `mx` |
| 树莓派项目目录 | `/home/mx/spacefarm` |
| 摄像头 | Raspberry Pi Camera Module 3 |
| 本地视觉接口 | `http://127.0.0.1:8791`，仅树莓派本机可访问 |
| 云端地面站 | `http://43.156.68.157:8790/` |

电脑需要和树莓派处于同一局域网。当前已经配置 SSH 免密登录，不需要在脚本或文档中保存密码。

## 2. 从 Windows 连接树莓派

在 PowerShell 中先检查 22 端口：

```powershell
Test-NetConnection 192.168.125.121 -Port 22
```

看到 `TcpTestSucceeded : True` 后连接：

```powershell
ssh mx@192.168.125.121
```

登录成功后，可用下面的命令确认身份和项目目录：

```bash
hostname
whoami
cd /home/mx/spacefarm
pwd
```

退出 SSH：

```bash
exit
```

如果连接超时，通常是树莓派未开机、电脑不在同一网络，或树莓派通过 DHCP 获得了新地址。可先检查：

```powershell
ping 192.168.125.121
Test-NetConnection 192.168.125.121 -Port 22
```

## 3. 检查摄像头和视觉服务

SSH 登录树莓派后执行：

```bash
rpicam-hello --list-cameras
```

Camera Module 3 被正确识别时，列表中会出现 IMX708 摄像头。

检查项目的四个视觉服务：

```bash
systemctl is-active spacefarm-vision-capture.service
systemctl is-active spacefarm-vision-api.service
systemctl is-active spacefarm-vision-local-api.service
systemctl is-active spacefarm-vision-sync.service
```

正常情况下均应返回 `active`。查看综合健康状态：

```bash
curl -sS http://127.0.0.1:8791/healthz
```

常见拍照状态：

| 状态 | 含义 |
| --- | --- |
| `WAITING_TELEMETRY` | 尚未收到新鲜的 ESP32 遥测 |
| `WAITING_INTERVAL` | 自动拍照距上次未满两小时 |
| `WAITING_LIGHT` | 光照低于拍摄阈值 |
| `READY` | 拍摄条件满足 |
| `QUEUED_FOR_ANALYSIS` | 已拍照，正在等待多模态模型分析 |
| `QUALITY_REJECTED` | 照片已拍，但清晰度等质量检查未通过 |
| `CAPTURE_ERROR` | 摄像头或文件写入异常 |

查看服务日志：

```bash
journalctl -u spacefarm-vision-capture.service -n 50 --no-pager
journalctl -u spacefarm-vision-api.service -n 50 --no-pager
journalctl -u spacefarm-vision-sync.service -n 50 --no-pager
```

## 4. 推荐方式：通过项目接口手动拍照

正式项目中，`spacefarm-vision-capture` 是摄像头的唯一所有者。人工拍照应向本地接口提交请求，不要直接启动第二个摄像头进程。

SSH 登录树莓派后执行：

```bash
curl -sS -X POST http://127.0.0.1:8791/v1/capture \
  -H 'Content-Type: application/json' \
  -d '{"operator":"team","reason":"现场手动拍照"}'
```

接口返回 `202` 和 `request_id` 表示拍照请求已经进入队列。后台通常在 10 秒内检查请求。

人工请求只跳过“距离上次拍照满两小时”的限制，不会跳过以下安全与质量条件：

- 必须有新鲜的 ESP32 遥测；
- 当前光照必须达到阈值；
- 图片必须通过清晰度等质量检查；
- 多模态 API 分析仍是异步执行。

提交后查看最新状态和事件：

```bash
curl -sS http://127.0.0.1:8791/healthz
curl -sS 'http://127.0.0.1:8791/v1/events?limit=3'
curl -sS http://127.0.0.1:8791/v1/latest
```

`/v1/latest` 只返回最近一次已经完成 AI 分析的照片。因此刚拍完时，它可能暂时仍显示上一张照片；应结合 `/healthz` 和 `/v1/events` 判断新照片是否仍在排队。

## 5. 项目调用 Camera Module 3 的 Python 代码

项目实际使用的适配器位于 `tools/vision/camera.py`。最小调用方式如下：

```python
from tools.vision.camera import CameraModule3

output = "/home/mx/camera-test.jpg"

with CameraModule3(
    size=(2304, 1296),
    autofocus=True,
    warmup_sec=2.0,
) as camera:
    camera.capture(output)

print(f"照片已保存：{output}")
```

适配器内部使用 Picamera2，核心代码为：

```python
from picamera2 import Picamera2

camera = Picamera2()
config = camera.create_still_configuration(
    main={"size": (2304, 1296), "format": "RGB888"}
)
camera.configure(config)
camera.set_controls({"AfMode": 2})
camera.start()
camera.capture_file("/home/mx/camera-test.jpg")
camera.stop()
```

### 单独运行测试代码

后台拍照服务运行时已经占用摄像头。只有需要进行底层硬件测试时，才临时停止服务：

```bash
cd /home/mx/spacefarm
sudo systemctl stop spacefarm-vision-capture.service
```

运行自己的 Python 脚本，或使用系统拍照命令：

```bash
rpicam-still -t 2000 --autofocus-mode auto -o /home/mx/camera-test.jpg
```

测试结束后必须恢复项目服务：

```bash
sudo systemctl start spacefarm-vision-capture.service
systemctl is-active spacefarm-vision-capture.service
```

如果看到 `Device or resource busy`，说明还有其他进程占用摄像头，应先检查拍照服务状态，不要反复启动多个拍照程序。

## 6. 在电脑浏览器中查看最新照片

本地视觉接口故意只绑定树莓派的 `127.0.0.1`，不能直接访问 `http://192.168.125.121:8791`。应通过 SSH 隧道安全查看。

在 Windows PowerShell 的第一个窗口运行，并保持窗口开启：

```powershell
ssh -N -L 8791:127.0.0.1:8791 mx@192.168.125.121
```

在第二个 PowerShell 窗口读取最新事件：

```powershell
$latest = Invoke-RestMethod http://127.0.0.1:8791/v1/latest
$latest | ConvertTo-Json -Depth 8
```

如果 `$latest.available` 为 `True`，打开对应照片：

```powershell
$imageUrl = "http://127.0.0.1:8791/v1/images/$($latest.event_id)-thumb.jpg"
Start-Process $imageUrl
```

保存到当前电脑目录：

```powershell
Invoke-WebRequest $imageUrl -OutFile ".\spacefarm-latest.jpg"
```

完成后，在第一个窗口按 `Ctrl+C` 关闭 SSH 隧道。

## 7. 通过云端地面站查看

照片完成 AI 分析并成功同步腾讯云后，打开：

```text
http://43.156.68.157:8790/
```

在“Camera Module 3 · 表型筛选”区域查看最近拍摄照片、拍摄时间和 AI 表型分析结果。

如果树莓派本地已有新照片，而云端仍显示旧照片，检查：

```bash
systemctl is-active spacefarm-vision-sync.service
journalctl -u spacefarm-vision-sync.service -n 80 --no-pager
```

云端查看依赖“拍照成功 → AI 分析成功 → 云端同步成功”三个阶段；摄像头拍照成功并不等于照片已经立即出现在云端。

## 8. 直接复制测试照片到电脑

对于用 `rpicam-still` 或独立 Python 脚本保存的 `/home/mx/camera-test.jpg`，在 Windows PowerShell 中执行：

```powershell
scp mx@192.168.125.121:/home/mx/camera-test.jpg .
Start-Process .\camera-test.jpg
```

项目自动拍摄的照片位于视觉数据目录下的 `captures/<event_id>/overview.jpg`。实际数据根目录由 `/home/mx/spacefarm/.config/vision.env` 中的 `SPACEFARM_VISION_DATA_DIR` 决定，可在树莓派上查看：

```bash
grep '^SPACEFARM_VISION_DATA_DIR=' /home/mx/spacefarm/.config/vision.env
find /home/mx/spacefarm/data/vision /var/lib/spacefarm/vision \
  -type f -path '*/captures/*/overview.jpg' -printf '%T@ %p\n' 2>/dev/null \
  | sort -nr | head -5
```

通常使用第 6 节的 SSH 隧道查看更方便，也不需要手工判断数据目录。

## 9. 最短操作流程

只需要记住下面四步：

1. PowerShell 登录：`ssh mx@192.168.125.121`。
2. 在树莓派上调用 `POST http://127.0.0.1:8791/v1/capture` 请求拍照。
3. 电脑建立隧道：`ssh -N -L 8791:127.0.0.1:8791 mx@192.168.125.121`。
4. 读取 `/v1/latest` 的 `event_id`，再打开 `/v1/images/<event_id>-thumb.jpg`。

> 注意：不要把多模态 API 密钥、云端上传令牌或实验修改口令写进脚本、截图和培训文档。
