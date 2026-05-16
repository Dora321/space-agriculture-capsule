"""
DHT 传感器诊断脚本
直接在 OLED 上显示实时读取结果，无需看串口
用法: py -m mpremote connect COM3 run debug_dht.py
"""
import machine
import dht
import time
from machine import I2C, Pin
import ssd1306

# 配置（与 config.py 一致）
DHT_PIN = 4
DHT_TYPE = "DHT11"
OLED_SDA = 21
OLED_SCL = 22

# 初始化 OLED
print("[DEBUG] Init OLED...")
try:
    i2c = I2C(0, scl=Pin(OLED_SCL), sda=Pin(OLED_SDA), freq=400000)
    oled = ssd1306.SSD1306_I2C(128, 64, i2c)
    oled.fill(0)
    oled.text("DHT DEBUG", 30, 0)
    oled.text("Init...", 40, 28)
    oled.show()
    has_oled = True
except Exception as e:
    print(f"[DEBUG] OLED failed: {e}")
    has_oled = False

# 初始化 DHT
print(f"[DEBUG] Init {DHT_TYPE} on GPIO{DHT_PIN}...")
pin = machine.Pin(DHT_PIN)
if DHT_TYPE == "DHT22":
    sensor = dht.DHT22(pin)
else:
    sensor = dht.DHT11(pin)

if has_oled:
    oled.fill(0)
    oled.text("DHT DEBUG MODE", 10, 0)
    oled.text("GPIO4 DHT11", 20, 12)
    oled.text("Reading...", 30, 28)
    oled.show()

time.sleep(1)

# 连续读取 20 次，每 3 秒一次
for i in range(20):
    status = ""
    try:
        sensor.measure()
        t = sensor.temperature()
        h = sensor.humidity()
        status = f"OK  T={t} H={h}"
        print(f"[{i+1:2d}/20] T={t}C  H={h}%")
    except OSError as e:
        status = f"ERR {e}"
        print(f"[{i+1:2d}/20] FAILED: {e}")

    if has_oled:
        oled.fill_rect(0, 24, 128, 40, 0)  # 清除下方区域
        oled.text(f"#{i+1}/20", 0, 24)
        # 状态可能太长，截断显示
        if len(status) > 16:
            oled.text(status[:16], 0, 36)
            oled.text(status[16:32], 0, 48)
        else:
            oled.text(status, 0, 36)
        oled.show()

    time.sleep(3)

if has_oled:
    oled.fill(0)
    oled.text("DEBUG DONE", 30, 28)
    oled.show()

print("[DEBUG] Test complete")
