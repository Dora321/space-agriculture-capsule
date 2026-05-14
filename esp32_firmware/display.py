"""
显示模块 - SSD1306 OLED 显示屏
英文模式显示（ASCII 8x8 内置字体）
"""

import ssd1306
import time
from machine import I2C, Pin
import config


# 全局 OLED 对象
_oled = None

# 显示状态
_DISPLAY_ON = True


def init():
    """初始化 OLED 显示屏"""
    global _oled

    try:
        i2c = I2C(
            0,
            scl=Pin(config.OLED_SCL_PIN),
            sda=Pin(config.OLED_SDA_PIN),
            freq=config.OLED_I2C_FREQ
        )

        # 检查设备是否存在
        devices = i2c.scan()
        if 0x3C not in devices:
            print(f"[Display] OLED (0x3C) not detected, addresses: {devices}")
            if 0x3D in devices:
                print("[Display] Found OLED (0x3D)")
            else:
                print("[Display] OLED not connected")
                return False

        _oled = ssd1306.SSD1306_I2C(128, 64, i2c)
        _oled.fill(0)
        _oled.show()

        print("[Display] OLED initialized successfully")
        return True

    except Exception as e:
        print(f"[Display] OLED initialization failed: {e}")
        return False


def _check_init():
    """检查 OLED 是否已初始化"""
    if _oled is None:
        print("[Display] OLED not initialized")
        return False
    return True


# ============ 显示页面 ============

def clear():
    """清屏"""
    if _check_init():
        _oled.fill(0)


def show():
    """刷新显示"""
    if _check_init():
        _oled.show()


def show_boot():
    """显示启动画面"""
    if not _check_init():
        return

    _oled.fill(0)
    _oled.text("================", 0, 0)
    _oled.text("  SPACE FARM    ", 16, 16)
    _oled.text("  TK-NYZ v1.0   ", 16, 28)
    _oled.text("================", 0, 44)
    _oled.show()


def show_text(text, x=0, y=0):
    """显示一行文字"""
    if not _check_init():
        return

    _oled.fill(0)
    _oled.text(text, x, y)
    _oled.show()


def show_data(soil, co2, temp, hum, plant, action):
    """
    显示传感器数据和状态
    布局 (128x64):
      y=0  : SPACE FARM v1.0     (8px)
      y=12 : Plant:XXXX          (8px)
      y=24 : Soil:XX% CO2:XXXX  (8px)
      y=36 : T:XXC H:XX%         (8px)
      y=48 : Action:XXXX         (8px)
    """
    if not _check_init():
        return

    _oled.fill(0)

    _oled.text("SPACE FARM v1.0", 0, 0)
    _oled.text(f"Plant:{plant}", 0, 12)
    _oled.text(f"Soil:{soil}%", 0, 24)
    _oled.text(f"CO2:{co2}", 72, 24)
    _oled.text(f"T:{temp}C H:{hum}%", 0, 36)

    action_names = {
        "water": "WATER",
        "nutrient": "NUTRIENT",
        "ventilate": "FAN",
        "idle": "IDLE"
    }
    action_en = action_names.get(action, action.upper())
    _oled.text(f"Action:{action_en}", 0, 48)

    _oled.show()


def show_action(action, duration, reason):
    """显示执行动作"""
    if not _check_init():
        return

    _oled.fill(0)

    action_names = {
        "water": "WATER",
        "nutrient": "NUTRIENT",
        "ventilate": "FAN",
        "idle": "IDLE"
    }
    action_en = action_names.get(action, action.upper())

    _oled.text(f">> {action_en}", 0, 8)
    _oled.text("================", 0, 26)
    _oled.text(f"  {duration}s  ", 40, 38)
    _oled.show()


def show_idle(soil, co2, plant):
    """显示待机状态"""
    if not _check_init():
        return

    _oled.fill(0)

    _oled.text("Status: OK", 24, 4)
    _oled.text("================", 0, 18)
    _oled.text(f"Plant:{plant}", 0, 30)
    _oled.text(f"Soil:{soil}%", 0, 44)
    _oled.text(f"CO2:{co2}", 72, 44)
    _oled.show()


def show_error(message):
    """显示错误信息"""
    if not _check_init():
        return

    _oled.fill(0)
    _oled.text("!! ERROR !!", 24, 4)
    _oled.text("================", 0, 18)

    # 截断过长的消息（16 ASCII 字符/行）
    if len(message) > 16:
        _oled.text(message[:16], 0, 34)
        _oled.text(message[16:32], 0, 46)
    else:
        _oled.text(message, 0, 38)

    _oled.show()


def show_wifi_status(connected, ip=None):
    """显示 WiFi 状态"""
    if not _check_init():
        return

    _oled.fill(0)

    if connected:
        _oled.text("WiFi: OK", 0, 20)
        if ip:
            _oled.text(f"IP:{ip}", 0, 36)
    else:
        _oled.text("WiFi: FAIL", 0, 20)
        _oled.text("Local rules", 0, 40)

    _oled.show()
    time.sleep(2)


def scroll_text(text, delay_ms=100):
    """滚动显示文字（长文本）"""
    if not _check_init():
        return

    width = 128
    x = width

    for _ in range(len(text) * 10):
        _oled.fill(0)
        _oled.text(text, x, 28)
        _oled.show()

        x -= 1
        if x < -len(text) * 8:
            break

        time.sleep_ms(delay_ms)


def show_graphic():
    """显示简单图形（装饰用）"""
    if not _check_init():
        return

    _oled.fill(0)

    # 画一个简单的植物图标
    # 茎
    _oled.line(64, 50, 64, 30, 1)
    # 叶子左
    _oled.line(64, 35, 50, 28, 1)
    _oled.line(50, 28, 45, 35, 1)
    # 叶子右
    _oled.line(64, 35, 78, 28, 1)
    _oled.line(78, 28, 83, 35, 1)
    # 顶部装饰：用四点+交叉线模拟圆形花朵
    cx, cy, r = 64, 18, 6
    _oled.pixel(cx, cy - r, 1)   # 上
    _oled.pixel(cx + r, cy, 1)   # 右
    _oled.pixel(cx, cy + r, 1)   # 下
    _oled.pixel(cx - r, cy, 1)   # 左
    _oled.line(cx - 4, cy - 4, cx + 4, cy + 4, 1)
    _oled.line(cx - 4, cy + 4, cx + 4, cy - 4, 1)

    # 文字
    _oled.text("SPACE FARM", 28, 55)

    _oled.show()


def power_off():
    """关闭显示（省电）"""
    global _DISPLAY_ON
    if _check_init():
        _oled.poweroff()
        _DISPLAY_ON = False


def power_on():
    """开启显示"""
    global _DISPLAY_ON
    if _check_init():
        _oled.poweron()
        _DISPLAY_ON = True
