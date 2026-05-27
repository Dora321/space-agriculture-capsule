"""WS2812 状态灯条驱动 — 育种舱生物指示灯。

11 颗可寻址 RGB 灯珠：
- 平时：按土壤湿度点亮对应数量（每颗 ≈ 9%），颜色梯度暖红→绿→冷蓝
- 浇水中：整条黄色（兼容旧 set_led("yellow") 语义）
- 错误/离线：整条红色（兼容旧 set_led("red") 语义）
- 正常空闲：整条柔和绿（兼容旧 set_led("green") 语义）
- 关闭：全灭（兼容旧 set_led("off") 语义）

向后兼容：`utils.set_led(color)` 通过该模块实现，无需修改调用点。
"""

import config

try:
    import neopixel
    from machine import Pin
    _HAS_HARDWARE = True
except ImportError:
    _HAS_HARDWARE = False


_np = None
_count = 0
_brightness = 0.4


def _scale(rgb):
    r, g, b = rgb
    return (
        int(r * _brightness),
        int(g * _brightness),
        int(b * _brightness),
    )


def _moisture_color(pct):
    """根据湿度百分比返回 RGB —— 暖红 → 黄 → 绿 → 冷蓝渐变。"""
    pct = max(0, min(100, pct))
    if pct < 25:
        return (255, 60, 30)
    if pct < 45:
        return (255, 200, 30)
    if pct < 70:
        return (60, 220, 60)
    return (40, 140, 255)


def init():
    """初始化 WS2812 灯条。无硬件时静默成空操作。"""
    global _np, _count, _brightness
    _count = getattr(config, "WS2812_LED_COUNT", 11)
    _brightness = float(getattr(config, "WS2812_BRIGHTNESS", 0.4))
    if not _HAS_HARDWARE:
        print("[Strip] neopixel module not available, status strip in stub mode")
        return False
    try:
        pin = Pin(getattr(config, "WS2812_PIN", 26), Pin.OUT)
        _np = neopixel.NeoPixel(pin, _count)
        off()
        print(f"[Strip] WS2812 initialized on GPIO{getattr(config, 'WS2812_PIN', 26)} ({_count} LEDs)")
        return True
    except Exception as e:
        print(f"[Strip] WS2812 init failed: {e}")
        _np = None
        return False


def _write_all(rgb):
    if _np is None:
        return
    color = _scale(rgb)
    for i in range(_count):
        _np[i] = color
    _np.write()


def off():
    """全灭。"""
    if _np is None:
        return
    for i in range(_count):
        _np[i] = (0, 0, 0)
    _np.write()


def show_solid(rgb):
    """整条同色显示。"""
    _write_all(rgb)


def show_moisture(pct):
    """按土壤湿度百分比点亮对应数量灯珠，颜色按梯度变化。

    pct < 0 或 None 视为离线状态：首尾两颗暗红常亮提示。
    """
    if _np is None:
        return
    if pct is None or pct < 0:
        for i in range(_count):
            _np[i] = (0, 0, 0)
        warn = _scale((180, 20, 20))
        _np[0] = warn
        _np[_count - 1] = warn
        _np.write()
        return

    lit = int(round(pct / 100 * _count))
    lit = max(0, min(_count, lit))
    color = _scale(_moisture_color(pct))
    for i in range(_count):
        _np[i] = color if i < lit else (0, 0, 0)
    _np.write()


def set_status(state):
    """按抽象状态切换整条颜色。兼容旧 set_led API。

    state in {"red", "green", "yellow", "off"}。
    其它值视为 off。
    """
    if state == "red":
        _write_all((255, 40, 40))
    elif state == "green":
        _write_all((40, 200, 80))
    elif state == "yellow":
        _write_all((255, 180, 30))
    else:
        off()


def blink(state, times=3, interval_ms=300):
    """整条闪烁。"""
    import time
    for _ in range(times):
        set_status(state)
        time.sleep_ms(interval_ms)
        off()
        time.sleep_ms(interval_ms)


def test_sequence():
    """启动自检：依次显示红/黄/绿/湿度渐变，便于现场快速判断灯条是否正常。"""
    import time
    print("[Strip] Self-test: red -> yellow -> green -> moisture sweep")
    for color in ("red", "yellow", "green"):
        set_status(color)
        time.sleep_ms(400)
    for pct in (0, 20, 40, 60, 80, 100):
        show_moisture(pct)
        time.sleep_ms(250)
    off()
