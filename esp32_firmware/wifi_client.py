"""
WiFi 连接模块
"""

import network
import time
import gc
import config


# 全局 WLAN 对象
_wlan = None


def _ticks_ms():
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms()
    return int(time.time() * 1000)


def _ticks_diff(now, start):
    if hasattr(time, "ticks_diff"):
        return time.ticks_diff(now, start)
    return now - start


def _sleep_ms(ms):
    if hasattr(time, "sleep_ms"):
        time.sleep_ms(ms)
    else:
        time.sleep(ms / 1000)


def connect(timeout=None, reset=False, allow_full_reset=True):
    """连接 WiFi。

    reset=False 时，若驱动已 active 但掉线，先做"软重连"——不拆 WiFi 驱动、
    保留 rx 缓冲，仅重新关联，避免运行期重建驱动需要 ~130KB 连续堆导致 OOM。
    软重连失败才回退到硬复位（active False/True 重建驱动）。
    timeout: 超时秒数。返回: True=成功, False=失败
    """
    global _wlan

    if timeout is None:
        timeout = getattr(config, "WIFI_CONNECT_TIMEOUT", 12)

    gc.collect()
    try:
        _wlan = network.WLAN(network.STA_IF)
    except OSError as e:
        print(f"[WiFi] WLAN init failed: {e}")
        _wlan = None
        return False

    # 已连接且有 IP，直接返回
    if _wlan.active() and _wlan.isconnected():
        ip = _wlan.ifconfig()[0]
        if ip and ip != "0.0.0.0":
            print("[WiFi] Already connected, IP:", ip)
            return True

    # ── 软重连：驱动已 active，先不拆驱动直接重关联（保留 rx 缓冲，绕开 OOM）──
    if _wlan.active() and not reset:
        gc.collect()
        print("[WiFi] Soft reconnect (keep driver, free mem={})...".format(gc.mem_free()))
        if _soft_reassociate(timeout):
            _post_connect()
            return True
        if not allow_full_reset:
            print("[WiFi] Soft reconnect failed, full reset deferred")
            return False
        print("[WiFi] Soft reconnect failed, falling back to full reset")

    # ── 硬复位：拆掉重建 WiFi 驱动（需要 ~130KB 连续堆）──
    try:
        if _wlan.active():
            try:
                _wlan.disconnect()
            except Exception:
                pass
            _wlan.active(False)
            _sleep_ms(1500)  # 让 PHY/MAC 完全 power down
        _wlan.active(True)
        _sleep_ms(800)       # PHY/MAC 上电后等稳定
        if getattr(config, "WIFI_DISABLE_POWER_SAVE", True):
            try:
                _wlan.config(pm=0xa11140)
            except Exception:
                pass
    except OSError as e:
        print(f"[WiFi] WLAN reset failed: {e}")
        return False

    print(f"[WiFi] Connecting to {config.WIFI_SSID}...")
    try:
        _wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
    except OSError as e:
        print(f"[WiFi] Connect failed: {e}")
        return False

    if not _wait_connected(timeout):
        return False
    _post_connect()
    return True


def _soft_reassociate(timeout):
    """不拆 WiFi 驱动、仅重新关联。先 disconnect 进干净状态再 connect，
    避免半挂态下直接 connect 抛 "Wifi Internal State Error"。"""
    try:
        try:
            _wlan.disconnect()
        except Exception:
            pass
        _sleep_ms(200)
        if getattr(config, "WIFI_DISABLE_POWER_SAVE", True):
            try:
                _wlan.config(pm=0xa11140)
            except Exception:
                pass
        _wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
    except OSError as e:
        print(f"[WiFi] Soft reassoc exc: {e}")
        return False
    return _wait_connected(timeout)


def _wait_connected(timeout):
    start_time = time.time()
    while not _wlan.isconnected():
        if time.time() - start_time > timeout:
            print("[WiFi] Connection timeout")
            return False
        _sleep_ms(250)
    return True


def _post_connect():
    print(f"[WiFi] Connected successfully!")
    print(f"  IP: {get_ip()}")
    print(f"  Subnet mask: {_wlan.ifconfig()[1]}")
    print(f"  Gateway: {_wlan.ifconfig()[2]}")
    if getattr(config, "NTP_SYNC_ON_CONNECT", False):
        _sync_ntp()


def _sync_ntp():
    """WiFi 连接后同步 NTP，设置 RTC 为北京时间（UTC+8）。"""
    try:
        import ntptime
        ntptime.host = "ntp.aliyun.com"
        ntptime.settime()           # 写入 UTC 时间到 RTC
        # 手动加 8 小时偏移量写回 RTC
        import machine
        t = time.localtime(time.time() + 8 * 3600)
        machine.RTC().datetime((t[0], t[1], t[2], t[6], t[3], t[4], t[5], 0))
        t2 = time.localtime()
        print(f"[NTP] Synced: {t2[0]}-{t2[1]:02d}-{t2[2]:02d} {t2[3]:02d}:{t2[4]:02d} CST")
    except Exception as e:
        print(f"[NTP] Sync failed: {e}")


def disconnect():
    """断开 WiFi 连接"""
    global _wlan
    if _wlan:
        try:
            _wlan.disconnect()
            _wlan.active(False)
            print("[WiFi] Disconnected")
        except OSError as e:
            print(f"[WiFi] Disconnect failed: {e}")


def _has_ip():
    global _wlan
    try:
        current = network.WLAN(network.STA_IF)
        if current.active():
            ip = current.ifconfig()[0]
            if ip and ip != "0.0.0.0":
                _wlan = current
                return True
    except Exception:
        pass
    if _wlan is not None:
        try:
            ip2 = _wlan.ifconfig()[0]
            if ip2 and ip2 != "0.0.0.0":
                return True
        except Exception:
            pass
    return False


def is_connected(grace_ms=0):
    """检查 WiFi 是否已连接（基于 IP 判断，比 isconnected() 稳健）。"""
    global _wlan
    start_ms = _ticks_ms()
    for attempt in range(3):
        if _has_ip():
            return True
        if attempt < 2:
            _sleep_ms(200)
    while grace_ms and _ticks_diff(_ticks_ms(), start_ms) < grace_ms:
        _sleep_ms(250)
        if _has_ip():
            return True
    return False


def get_ip():
    """获取 IP 地址，未分配时返回 None。"""
    global _wlan
    try:
        current = network.WLAN(network.STA_IF)
        if current.active() and current.isconnected():
            _wlan = current
    except Exception:
        pass
    if _wlan and _wlan.isconnected():
        ip = _wlan.ifconfig()[0]
        return ip if ip != "0.0.0.0" else None
    return None


def get_rssi():
    """获取信号强度"""
    global _wlan
    if _wlan and _wlan.isconnected():
        return _wlan.status('rssi')
    return -100


def reconnect():
    """重新连接 WiFi"""
    disconnect()
    _sleep_ms(500)
    return connect(reset=True)


def smart_connect():
    """
    智能连接：尝试连接，失败后自动重试
    最多重试 3 次
    """
    for attempt in range(3):
        print(f"[WiFi] Connection attempt {attempt + 1}/3")
        try:
            if connect(timeout=20):
                return True
        except OSError as e:
            print(f"[WiFi] Retry skipped: {e}")
        print(f"[WiFi] Waiting 5s to retry...")
        gc.collect()
        time.sleep(5)
    
    print("[WiFi] All connection attempts failed")
    return False


def scan_networks():
    """
    扫描可用的 WiFi 网络
    返回: 网络列表
    """
    global _wlan
    _wlan = network.WLAN(network.STA_IF)
    _wlan.active(True)
    
    networks = _wlan.scan()
    result = []
    
    for net in networks:
        ssid = net[0].decode('utf-8')
        rssi = net[3]
        auth = net[4]
        result.append({
            "ssid": ssid,
            "rssi": rssi,
            "auth": auth
        })
    
    return result


def test_connection():
    """测试网络连接"""
    if not is_connected():
        print("[Test] WiFi not connected")
        return False
    
    import socket
    
    try:
        print("[Test] Trying to connect to baidu.com...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(('baidu.com', 80))
        sock.close()
        print("[Test] Network connection normal!")
        return True
    except Exception as e:
        print(f"[Test] Network connection failed: {e}")
        return False


def get_connection_info():
    """获取详细的连接信息"""
    if not is_connected():
        return None
    
    info = _wlan.ifconfig()
    return {
        "ip": info[0],
        "subnet": info[1],
        "gateway": info[2],
        "dns": info[3],
        "rssi": get_rssi()
    }
