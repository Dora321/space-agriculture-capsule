"""WiFi 诊断脚本 - 在 ESP32 上跑，用 mpremote run 执行"""
import network
import time
import gc

print("=== WiFi Diagnostic ===")
print("free mem:", gc.mem_free())

w = network.WLAN(network.STA_IF)
print("current active:", w.active())
print("current status:", w.status(), "IDLE=", network.STAT_IDLE)
print("current connected:", w.isconnected())

# 强制完整复位
print("\n--- Resetting WLAN ---")
try:
    w.disconnect()
    print("disconnect ok")
except Exception as e:
    print("disconnect err:", e)

w.active(False)
time.sleep(2)
print("active(False) status:", w.status())

w.active(True)
time.sleep(2)
print("active(True) status:", w.status())
gc.collect()
print("free mem after gc:", gc.mem_free())

# 扫描确认 AP 可见
print("\n--- Scan ---")
try:
    nets = w.scan()
    for n in nets:
        ssid = n[0]
        try:
            ssid = ssid.decode()
        except Exception:
            pass
        print(" ", ssid, "rssi:", n[3], "auth:", n[4])
except Exception as e:
    print("scan error:", e)

# 尝试连接
from config import WIFI_SSID, WIFI_PASSWORD
print(f"\n--- Connect to '{WIFI_SSID}' ---")
print("password len:", len(WIFI_PASSWORD))
try:
    w.connect(WIFI_SSID, WIFI_PASSWORD)
    print("connect() called ok, waiting...")
    for i in range(30):
        s = w.status()
        c = w.isconnected()
        print(f"  t={i}s status={s} connected={c}")
        if c:
            print("SUCCESS! ip:", w.ifconfig()[0])
            break
        if s == network.STAT_WRONG_PASSWORD:
            print("FAIL: wrong password")
            break
        if s == network.STAT_NO_AP_FOUND:
            print("FAIL: no ap found")
            break
        time.sleep(1)
    else:
        print("FAIL: timeout (30s), last status:", w.status())
except Exception as e:
    print("connect() exception:", type(e).__name__, e)
