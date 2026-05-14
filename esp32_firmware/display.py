"""
显示模块 - SSD1306 OLED 显示屏
支持中英文混合显示（中文 16x16，英文 8x8）
"""

import ssd1306
import framebuf
import time
from machine import I2C, Pin
import config


# 全局 OLED 对象
_oled = None

# 显示状态
_DISPLAY_ON = True

# 中文字库（延迟加载，节省内存）
_cn_font = None


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
            # 尝试其他地址
            if 0x3D in devices:
                print("[Display] Found OLED (0x3D)")
            else:
                print("[Display] OLED not connected")
                return False

        _oled = ssd1306.SSD1306_I2C(128, 64, i2c)
        _oled.fill(0)
        _oled.show()

        # 加载中文字库
        _load_cn_font()

        print("[Display] OLED initialized successfully")
        return True

    except Exception as e:
        print(f"[Display] OLED initialization failed: {e}")
        return False


def _load_cn_font():
    """加载中文字库（仅加载一次）"""
    global _cn_font
    try:
        from font_cn import FONT
        _cn_font = FONT
        print(f"[Display] CN font loaded ({len(FONT)} chars)")
    except ImportError:
        print("[Display] CN font not installed, using English mode")
        _cn_font = None


def _check_init():
    """检查 OLED 是否已初始化"""
    if _oled is None:
        print("[Display] OLED not initialized")
        return False
    return True


# ============ 中英文混合渲染 ============

def _draw_text(text, x, y, cn_height=16):
    """
    绘制混合中英文文本
    中文字符使用 16x16 点阵，英文使用内置 8x8 字体
    cn_height: 中文字符高度（用于英文垂直居中）
    """
    cx = x
    for ch in text:
        if cx >= 128:
            break  # 超出屏幕宽度
        if _cn_font and ch in _cn_font:
            # 中文: 16x16
            fb = framebuf.FrameBuffer(
                bytearray(_cn_font[ch]), 16, 16, framebuf.MONO_HMSB
            )
            _oled.blit(fb, cx, y)
            cx += 16
        else:
            # ASCII: 8x8，垂直居中于中文行高
            offset_y = (cn_height - 8) // 2 if cn_height > 8 else 0
            _oled.text(ch, cx, y + offset_y)
            cx += 8


def _draw_ascii(text, x, y):
    """绘制纯 ASCII 文本（8x8 内置字体）"""
    _oled.text(text, x, y)


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
    _draw_ascii("================", 0, 0)
    # 中文标题：太空种植舱（居中）
    _draw_text("太空种植舱", 24, 16)
    _draw_ascii("  TK-NYZ v1.0 ", 16, 36)
    _draw_ascii("================", 0, 52)
    _oled.show()


def show_text(text, x=0, y=0):
    """显示一行文字"""
    if not _check_init():
        return

    _oled.fill(0)
    _draw_text(text, x, y)
    _oled.show()


def show_data(soil, co2, temp, hum, plant, action):
    """
    显示传感器数据和状态
    布局 (128x64):
      y=0  : SPACE FARM v1.0     (ASCII, 8px)
      y=10 : 植物名称             (中文, 16px)
      y=28 : Soil:XX%  CO2:XXXX  (ASCII, 8px)
      y=38 : T:XXC  H:XX%        (ASCII, 8px)
      y=48 : 动作名称             (中文, 16px)
    """
    if not _check_init():
        return

    _oled.fill(0)

    # 标题
    _draw_ascii("SPACE FARM v1.0", 0, 0)

    # 植物类型（中文 16x16）
    _draw_text(plant, 0, 10)

    # 传感器数据（ASCII）
    _draw_ascii(f"Soil:{soil}%", 0, 28)
    _draw_ascii(f"CO2:{co2}", 72, 28)

    # 温湿度（ASCII）
    _draw_ascii(f"T:{temp}C H:{hum}%", 0, 38)

    # 当前动作（中文）
    action_names = {
        "water": "浇水",
        "nutrient": "营养",
        "ventilate": "换气",
        "idle": "待机"
    }
    action_cn = action_names.get(action, action)
    _draw_text(action_cn, 0, 48)

    _oled.show()


def show_action(action, duration, reason):
    """显示执行动作"""
    if not _check_init():
        return

    _oled.fill(0)

    action_names = {
        "water": "浇水",
        "nutrient": "营养",
        "ventilate": "换气",
        "idle": "待机"
    }

    action_cn = action_names.get(action, action)

    _draw_text("动作:", 16, 8)
    _draw_text(action_cn, 64, 8)
    _draw_ascii("================", 0, 26)
    _draw_ascii(f"  {duration}s  ", 40, 38)
    _oled.show()


def show_idle(soil, co2, plant):
    """显示待机状态"""
    if not _check_init():
        return

    _oled.fill(0)

    _draw_text("状态:正常", 24, 4)
    _draw_ascii("================", 0, 22)
    _draw_text(plant, 0, 34)
    _draw_ascii(f"Soil:{soil}%", 0, 52)
    _draw_ascii(f"CO2:{co2}", 72, 52)
    _oled.show()


def show_error(message):
    """显示错误信息"""
    if not _check_init():
        return

    _oled.fill(0)
    _draw_text("错误", 48, 4)
    _draw_ascii("================", 0, 22)

    # 截断过长的消息（16 ASCII 字符/行）
    if len(message) > 16:
        _draw_ascii(message[:16], 0, 34)
        _draw_ascii(message[16:32], 0, 46)
    else:
        _draw_ascii(message, 0, 38)

    _oled.show()


def show_wifi_status(connected, ip=None):
    """显示 WiFi 状态"""
    if not _check_init():
        return

    _oled.fill(0)

    if connected:
        _draw_ascii("WiFi: OK", 0, 20)
        if ip:
            _draw_ascii(f"IP:{ip}", 0, 36)
    else:
        _draw_ascii("WiFi: FAIL", 0, 20)
        _draw_ascii("Local rules", 0, 40)

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
        _draw_ascii(text, x, 28)
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
    # 顶部装饰：手绘简易花朵（替代 ssd1306 不支持的 circle）
    cx, cy, r = 64, 18, 6
    # 用四点+交叉线模拟圆形花朵
    _oled.pixel(cx, cy - r, 1)   # 上
    _oled.pixel(cx + r, cy, 1)   # 右
    _oled.pixel(cx, cy + r, 1)   # 下
    _oled.pixel(cx - r, cy, 1)   # 左
    _oled.line(cx - 4, cy - 4, cx + 4, cy + 4, 1)  # 对角线
    _oled.line(cx - 4, cy + 4, cx + 4, cy - 4, 1)  # 对角线

    # 文字
    _draw_text("太空种植舱", 24, 55)

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
