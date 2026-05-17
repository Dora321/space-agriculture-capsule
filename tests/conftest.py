"""
Mock MicroPython 模块，使 ESP32 固件代码能在 PC 上运行 pytest
"""
import sys
import types
import os
import pathlib
import importlib.util


# ============ Mock machine 模块 ============
machine_mock = types.ModuleType("machine")


class MockPin:
    IN = 0
    OUT = 1
    PULL_UP = 2

    def __init__(self, pin_num=0, mode=None, value=None, pull=None):
        self._pin = pin_num
        self._value = value if value is not None else 1

    def value(self, val=None):
        if val is not None:
            self._value = val
        return self._value


class MockADC:
    ATTN_11DB = 3

    def __init__(self, pin=None):
        self._value = 2500

    def atten(self, *args):
        pass

    def read(self):
        return self._value


class MockUART:
    def __init__(self, *args, **kwargs):
        pass

    def write(self, data):
        pass

    def any(self):
        return 0

    def read(self, n=0):
        return None


class MockI2C:
    def __init__(self, *args, **kwargs):
        pass

    def scan(self):
        return [0x3C]


machine_mock.Pin = MockPin
machine_mock.ADC = MockADC
machine_mock.UART = MockUART
machine_mock.I2C = MockI2C
machine_mock.reset = lambda: None
machine_mock.deepsleep = lambda ms: None
machine_mock.reset_cause = lambda: 0
sys.modules["machine"] = machine_mock

# ============ Mock network 模块 ============
net_mock = types.ModuleType("network")


class MockWLAN:
    def __init__(self, mode=None):
        self._connected = True

    def active(self, *args):
        pass

    def connect(self, *args):
        pass

    def isconnected(self):
        return self._connected

    def ifconfig(self):
        return ("192.168.1.100", "255.255.255.0", "192.168.1.1", "8.8.8.8")

    def scan(self):
        return []

    def status(self, key=None):
        return -50

    def disconnect(self):
        self._connected = False


net_mock.WLAN = MockWLAN
net_mock.STA_IF = 0
sys.modules["network"] = net_mock

# ============ Mock dht 模块 ============
dht_mock = types.ModuleType("dht")


class MockDHT22:
    def __init__(self, pin=None):
        pass

    def measure(self):
        pass

    def temperature(self):
        return 25.0

    def humidity(self):
        return 60.0


dht_mock.DHT22 = MockDHT22
dht_mock.DHT11 = MockDHT22
sys.modules["dht"] = dht_mock

# ============ Mock ssd1306 / urequests ============
ssd1306_mock = types.ModuleType("ssd1306")


class MockSSD1306_I2C:
    def __init__(self, w, h, i2c):
        pass

    def fill(self, c):
        pass

    def show(self):
        pass

    def text(self, t, x, y, *a):
        pass

    def line(self, *a):
        pass

    def pixel(self, *a):
        pass

    def fill_rect(self, *a):
        pass

    def poweroff(self):
        pass

    def poweron(self):
        pass


ssd1306_mock.SSD1306_I2C = MockSSD1306_I2C
sys.modules["ssd1306"] = ssd1306_mock

urequests_mock = types.ModuleType("urequests")
sys.modules["urequests"] = urequests_mock

# ujson → 标准 json
sys.modules["ujson"] = __import__("json")

# ============ Mock gc 模块 ============
gc_mock = types.ModuleType("gc")
gc_mock.mem_free = lambda: 80000
gc_mock.mem_alloc = lambda: 40000
gc_mock.collect = lambda: None
sys.modules["gc"] = gc_mock

# ============ 将 esp32_firmware 加入 sys.path ============
fw_dir = str(pathlib.Path(__file__).resolve().parent.parent / "esp32_firmware")
if fw_dir not in sys.path:
    sys.path.insert(0, fw_dir)

config_path = pathlib.Path(fw_dir) / "config.py"
config_example_path = pathlib.Path(fw_dir) / "config.py.example"
if "config" not in sys.modules and not config_path.exists() and config_example_path.exists():
    spec = importlib.util.spec_from_file_location("config", str(config_example_path))
    if spec is not None and spec.loader is not None:
        config_module = importlib.util.module_from_spec(spec)
        sys.modules["config"] = config_module
        spec.loader.exec_module(config_module)

# ============ Monkey-patch open() 让 plants.json 可被找到 ============
# config.py 用 open('plants.json') 打开文件，CWD 可能不是 esp32_firmware/
# 保存原始 open，在找不到文件时回退到 esp32_firmware 目录查找
_original_open = open


def _patched_open(path, *args, **kwargs):
    if isinstance(path, str) and path == "plants.json":
        candidate = str(pathlib.Path(fw_dir) / "plants.json")
        if pathlib.Path(candidate).exists():
            return _original_open(candidate, *args, **kwargs)
    return _original_open(path, *args, **kwargs)


import builtins
builtins.open = _patched_open
