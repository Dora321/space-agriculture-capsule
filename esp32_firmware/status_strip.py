"""WS2812 状态灯条驱动 — 决策广播层。

11 颗可寻址 RGB 灯珠，双重用途：
- 默认：按土壤湿度点亮对应数量（湿度温度计），颜色梯度暖红→绿→冷蓝
- 决策广播：整条变色/动画，向所有人展示系统"在想什么"

Decision Plane / Action Plane 分离架构：
- 物理执行器（水泵/补光灯）执行实际动作
- WS2812 广播决策信号，包括虚拟信号（风扇/施肥等未接入硬件）

信号类型与灯效映射：
  WATER           黄色流水       💧 水泵开启
  LIGHT_LOW       紫色脉冲       💡 补光灯开启
  LIGHT_HIGH      蓝色脉冲       🟡 建议遮光（虚拟）
  TEMP_HIGH       红色脉冲       🟡 建议通风（虚拟）
  TEMP_LOW        冰蓝脉冲       🟡 建议加热（虚拟）
  HUMID_LOW       青色脉冲       🟡 建议加湿（虚拟）
  NEED_N          柠檬黄呼吸     🟡 建议补氮肥（虚拟）
  NEED_P          粉色呼吸       🟡 建议补磷肥（虚拟）
  NEED_K          橙色呼吸       🟡 建议补钾肥（虚拟）
  SENSOR_FAIL     红色快闪       ⚠️ 切安全模式
  OFFLINE_MODE    缓慢黄色呼吸   🛡️ 本地规则接管
  BREEDING_GEN_UP 彩虹流光       🌱 育种代际进阶

向后兼容：`utils.set_led(color)` 通过该模块实现，无需修改调用点。
"""

import config
import time

try:
    import neopixel
    from machine import Pin
    _HAS_HARDWARE = True
except ImportError:
    _HAS_HARDWARE = False


_np = None
_count = 0
_brightness = 0.4


# ============ 信号常量 ============

SIGNAL_WATER = "WATER"
SIGNAL_LIGHT_LOW = "LIGHT_LOW"
SIGNAL_LIGHT_HIGH = "LIGHT_HIGH"
SIGNAL_TEMP_HIGH = "TEMP_HIGH"
SIGNAL_TEMP_LOW = "TEMP_LOW"
SIGNAL_HUMID_LOW = "HUMID_LOW"
SIGNAL_NEED_N = "NEED_N"
SIGNAL_NEED_P = "NEED_P"
SIGNAL_NEED_K = "NEED_K"
SIGNAL_SENSOR_FAIL = "SENSOR_FAIL"
SIGNAL_OFFLINE_MODE = "OFFLINE_MODE"
SIGNAL_BREEDING_GEN_UP = "BREEDING_GEN_UP"

# 信号是否对应已接入的物理执行器
PHYSICAL_SIGNALS = {SIGNAL_WATER, SIGNAL_LIGHT_LOW}

# 信号 → 默认动画时长（秒）
SIGNAL_DURATION = {
    SIGNAL_WATER: 5,
    SIGNAL_LIGHT_LOW: 3,
    SIGNAL_LIGHT_HIGH: 3,
    SIGNAL_TEMP_HIGH: 3,
    SIGNAL_TEMP_LOW: 3,
    SIGNAL_HUMID_LOW: 3,
    SIGNAL_NEED_N: 3,
    SIGNAL_NEED_P: 3,
    SIGNAL_NEED_K: 3,
    SIGNAL_SENSOR_FAIL: 3,
    SIGNAL_OFFLINE_MODE: 5,
    SIGNAL_BREEDING_GEN_UP: 10,
}


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
    if not getattr(config, "WS2812_ENABLED", True):
        _np = None
        print("[Strip] WS2812 disabled via config, stub mode")
        return True
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
    for _ in range(times):
        set_status(state)
        time.sleep_ms(interval_ms)
        off()
        time.sleep_ms(interval_ms)


# ============ 决策广播动画 ============

def _pulse(rgb, cycles=3, cycle_ms=600):
    """整条脉冲呼吸动画。"""
    steps = 20
    half_ms = cycle_ms // 2
    for _ in range(cycles):
        # 渐亮
        for s in range(steps):
            frac = s / steps
            c = _scale((int(rgb[0] * frac), int(rgb[1] * frac), int(rgb[2] * frac)))
            for i in range(_count):
                _np[i] = c
            _np.write()
            time.sleep_ms(half_ms // steps)
        # 渐暗
        for s in range(steps):
            frac = 1 - s / steps
            c = _scale((int(rgb[0] * frac), int(rgb[1] * frac), int(rgb[2] * frac)))
            for i in range(_count):
                _np[i] = c
            _np.write()
            time.sleep_ms(half_ms // steps)


def _breathe(rgb, cycles=3, cycle_ms=1200):
    """缓慢呼吸动画（比 pulse 更慢更柔和）。"""
    steps = 20
    half_ms = cycle_ms // 2
    for _ in range(cycles):
        for s in range(steps):
            frac = s / steps
            c = _scale((int(rgb[0] * frac), int(rgb[1] * frac), int(rgb[2] * frac)))
            for i in range(_count):
                _np[i] = c
            _np.write()
            time.sleep_ms(half_ms // steps)
        for s in range(steps):
            frac = 1 - s / steps
            c = _scale((int(rgb[0] * frac), int(rgb[1] * frac), int(rgb[2] * frac)))
            for i in range(_count):
                _np[i] = c
            _np.write()
            time.sleep_ms(half_ms // steps)


def _flow(rgb, duration_sec=5):
    """流水灯动画：亮点从左到右流动。"""
    head_ms = 80
    heads = int(duration_sec * 1000 / head_ms / _count) + 1
    for _ in range(heads):
        for head in range(_count):
            for i in range(_count):
                dist = abs(i - head)
                brightness = max(0.05, 1.0 - dist * 0.25)
                c = _scale((int(rgb[0] * brightness), int(rgb[1] * brightness), int(rgb[2] * brightness)))
                _np[i] = c
            _np.write()
            time.sleep_ms(head_ms)


def _fast_blink(rgb, times=10, interval_ms=100):
    """快速闪烁动画。"""
    for _ in range(times):
        c = _scale(rgb)
        for i in range(_count):
            _np[i] = c
        _np.write()
        time.sleep_ms(interval_ms)
        for i in range(_count):
            _np[i] = (0, 0, 0)
        _np.write()
        time.sleep_ms(interval_ms)


def _rainbow(duration_sec=10):
    """7 色彩虹流光动画。"""
    colors = [
        (255, 0, 0), (255, 127, 0), (255, 255, 0),
        (0, 255, 0), (0, 0, 255), (75, 0, 130), (148, 0, 211),
    ]
    offset = 0
    steps = int(duration_sec * 1000 / 100)
    for _ in range(steps):
        for i in range(_count):
            r, g, b = colors[(i + offset) % len(colors)]
            _np[i] = _scale((r, g, b))
        _np.write()
        offset += 1
        time.sleep_ms(100)


# 信号 → 动画函数映射
_SIGNAL_ANIMATIONS = {
    SIGNAL_WATER:           lambda dur: _flow((255, 200, 0), duration_sec=dur),
    SIGNAL_LIGHT_LOW:       lambda dur: _pulse((180, 0, 255), cycles=3, cycle_ms=600),
    SIGNAL_LIGHT_HIGH:      lambda dur: _pulse((0, 80, 255), cycles=3, cycle_ms=600),
    SIGNAL_TEMP_HIGH:       lambda dur: _pulse((255, 0, 0), cycles=3, cycle_ms=600),
    SIGNAL_TEMP_LOW:        lambda dur: _pulse((100, 180, 255), cycles=3, cycle_ms=600),
    SIGNAL_HUMID_LOW:       lambda dur: _pulse((0, 220, 220), cycles=3, cycle_ms=600),
    SIGNAL_NEED_N:          lambda dur: _breathe((255, 255, 0), cycles=3, cycle_ms=1200),
    SIGNAL_NEED_P:          lambda dur: _breathe((255, 100, 180), cycles=3, cycle_ms=1200),
    SIGNAL_NEED_K:          lambda dur: _breathe((255, 140, 0), cycles=3, cycle_ms=1200),
    SIGNAL_SENSOR_FAIL:     lambda dur: _fast_blink((255, 0, 0), times=10, interval_ms=100),
    SIGNAL_OFFLINE_MODE:    lambda dur: _breathe((255, 180, 0), cycles=3, cycle_ms=1500),
    SIGNAL_BREEDING_GEN_UP: lambda dur: _rainbow(duration_sec=dur),
}


def play_signal(signal, duration_sec=None):
    """播放决策信号对应的 WS2812 动画。

    signal: 信号常量（如 SIGNAL_WATER）
    duration_sec: 动画时长，默认取 SIGNAL_DURATION 映射
    """
    if _np is None:
        return
    anim = _SIGNAL_ANIMATIONS.get(signal)
    if anim is None:
        print(f"[Strip] Unknown signal: {signal}")
        return
    if duration_sec is None:
        duration_sec = SIGNAL_DURATION.get(signal, 3)
    print(f"[Strip] Signal: {signal} ({duration_sec}s)")
    try:
        anim(duration_sec)
    except Exception as e:
        print(f"[Strip] Signal animation error: {e}")


def play_signals(signals, max_signals=3):
    """依次播放多个决策信号动画，最多播放 max_signals 个。

    物理执行器信号（WATER/LIGHT_LOW）优先播放。
    """
    if not signals:
        return
    # 物理信号优先
    ordered = sorted(signals, key=lambda s: 0 if s in PHYSICAL_SIGNALS else 1)
    for signal in ordered[:max_signals]:
        play_signal(signal)


def test_sequence():
    """启动自检：依次显示所有信号动画，便于现场快速判断灯条是否正常。"""
    print("[Strip] Self-test: all signal animations")
    for signal in [SIGNAL_WATER, SIGNAL_LIGHT_LOW, SIGNAL_TEMP_HIGH,
                   SIGNAL_TEMP_LOW, SIGNAL_NEED_N, SIGNAL_NEED_P,
                   SIGNAL_NEED_K, SIGNAL_BREEDING_GEN_UP]:
        play_signal(signal, duration_sec=2)
        time.sleep_ms(300)
    show_moisture(50)
    time.sleep_ms(500)
    off()


# 现场演示秀的信号顺序（编排过，视觉对比强）
_DEMO_SIGNALS = [
    SIGNAL_WATER,      # 金黄流水
    SIGNAL_LIGHT_LOW,  # 紫色脉冲
    SIGNAL_TEMP_HIGH,  # 红色脉冲
    SIGNAL_HUMID_LOW,  # 青色脉冲
    SIGNAL_NEED_N,     # 黄呼吸
    SIGNAL_NEED_P,     # 粉呼吸
    SIGNAL_NEED_K,     # 橙呼吸
]


def demo_show(on_signal=None):
    """现场演示用编排灯效秀：彩虹开场 → 逐个信号动画 → 升代彩虹高潮 → 收束。

    供 OLED 菜单「LED Demo」一键触发，让评委看到舱体能广播的全部状态信号。
    on_signal(name): 可选回调，每段开始前以当前段名调用一次（供 OLED 同步显示字幕）。
    """
    if _np is None:
        return
    print("[Strip] Demo show start")
    if on_signal:
        on_signal("RAINBOW")
    _rainbow(duration_sec=3)                              # 彩虹扫场开场
    for signal in _DEMO_SIGNALS:
        if on_signal:
            on_signal(signal)
        play_signal(signal, duration_sec=2)
        time.sleep_ms(200)
    if on_signal:
        on_signal("GEN UP")
    play_signal(SIGNAL_BREEDING_GEN_UP, duration_sec=4)  # 升代彩虹高潮
    show_moisture(60)                                     # 回到湿度显示收束
    time.sleep_ms(600)
    print("[Strip] Demo show done")


def play_for(signal, total_sec):
    """在 total_sec 秒内循环播放某信号动画。

    用于手动执行水泵/补光时，在执行器开启期间持续显示对应灯效
    （单线程：动画循环本身就是"等待时长"）。
    """
    if _np is None:
        return
    start = time.ticks_ms()
    total_ms = int(total_sec * 1000)
    while time.ticks_diff(time.ticks_ms(), start) < total_ms:
        play_signal(signal, duration_sec=2)
    off()
