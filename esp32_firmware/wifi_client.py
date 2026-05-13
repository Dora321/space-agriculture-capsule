"""
WiFi 连接模块
"""

import network
import time
import config


# 全局 WLAN 对象
_wlan = None


def connect(timeout=30):
    """
    连接 WiFi
    timeout: 超时时间（秒）
    返回: True=成功, False=失败
    """
    global _wlan
    
    _wlan = network.WLAN(network.STA_IF)
    _wlan.active(True)
    
    print(f"[WiFi] 正在连接 {config.WIFI_SSID}...")
    
    _wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
    
    # 等待连接
    start_time = time.time()
    while not _wlan.isconnected():
        if time.time() - start_time > timeout:
            print("[WiFi] 连接超时")
            return False
        time.sleep(0.5)
    
    print(f"[WiFi] 连接成功!")
    print(f"  IP: {get_ip()}")
    print(f"  子网掩码: {_wlan.ifconfig()[1]}")
    print(f"  网关: {_wlan.ifconfig()[2]}")
    
    return True


def disconnect():
    """断开 WiFi 连接"""
    global _wlan
    if _wlan:
        _wlan.disconnect()
        _wlan.active(False)
        print("[WiFi] 已断开")


def is_connected():
    """检查 WiFi 是否已连接"""
    global _wlan
    if _wlan is None:
        return False
    return _wlan.isconnected()


def get_ip():
    """获取 IP 地址"""
    global _wlan
    if _wlan and _wlan.isconnected():
        return _wlan.ifconfig()[0]
    return "0.0.0.0"


def get_rssi():
    """获取信号强度"""
    global _wlan
    if _wlan and _wlan.isconnected():
        return _wlan.status('rssi')
    return -100


def reconnect():
    """重新连接 WiFi"""
    disconnect()
    time.sleep(2)
    return connect()


def smart_connect():
    """
    智能连接：尝试连接，失败后自动重试
    最多重试 3 次
    """
    for attempt in range(3):
        print(f"[WiFi] 连接尝试 {attempt + 1}/3")
        if connect(timeout=20):
            return True
        print(f"[WiFi] 等待 5 秒后重试...")
        time.sleep(5)
    
    print("[WiFi] 所有连接尝试均失败")
    return False


def scan_networks():
    """
    扫描可用的 WiFi 网络
    返回: 网络列表
    """
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
        print("[测试] WiFi 未连接")
        return False
    
    import socket
    
    try:
        print("[测试] 尝试连接百度...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(('baidu.com', 80))
        sock.close()
        print("[测试] 网络连接正常!")
        return True
    except Exception as e:
        print(f"[测试] 网络连接失败: {e}")
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
