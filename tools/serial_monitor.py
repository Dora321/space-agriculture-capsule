"""被动串口监听器 - 抓 ESP32 自动运行的固件日志，不抢 REPL。

用法：
  py tools/serial_monitor.py [秒数] [COM口]
  py tools/serial_monitor.py 135 COM3

与 mpremote run 不同：本工具只读串口、不进 raw REPL，所以不会和设备
flash 里自动运行的 main.py 抢占冲突。每行带相对时间戳，便于关联 WiFi
掉线/重连/遥测的时序。
"""
import sys
import time

import serial

DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 135
PORT = sys.argv[2] if len(sys.argv) > 2 else "COM3"
BAUD = 115200

ser = serial.Serial(PORT, BAUD, timeout=0.5)
# 不长按 EN/GPIO0，避免把设备摁在复位/下载模式
try:
    ser.dtr = False
    ser.rts = False
except Exception:
    pass

print("=== serial monitor %s @%d for %ds ===" % (PORT, BAUD, DURATION))
t0 = time.time()
line = b""
try:
    while time.time() - t0 < DURATION:
        b = ser.read(1)
        if not b:
            continue
        if b == b"\n":
            s = line.decode("utf-8", "replace").rstrip("\r")
            print("[%6.1f] %s" % (time.time() - t0, s))
            sys.stdout.flush()
            line = b""
        else:
            line += b
finally:
    ser.close()
    print("=== monitor end ===")
