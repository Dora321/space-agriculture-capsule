"""
显示模块 - SSD1306 OLED 显示屏
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
            print(f"[显示] 未检测到OLED (0x3C)，地址列表: {devices}")
            # 尝试其他地址
            if 0x3D in devices:
                print("[显示] 找到 OLED (0x3D)")
            else:
                print("[显示] OLED 未连接")
                return False
        
        _oled = ssd1306.SSD1306_I2C(128, 64, i2c)
        _oled.fill(0)
        _oled.show()
        
        print("[显示] OLED 初始化成功")
        return True
        
    except Exception as e:
        print(f"[显示] OLED 初始化失败: {e}")
        return False


def _check_init():
    """检查 OLED 是否已初始化"""
    if _oled is None:
        print("[显示] OLED 未初始化")
        return False
    return True


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
    _oled.text("================", 0, 10)
    _oled.text("SPACE FARMING", 12, 22)
    _oled.text(" TK-NYZ v1.0 ", 16, 34)
    _oled.text("================", 0, 46)
    _oled.show()


def show_text(text, x=0, y=0):
    """显示一行文字"""
    if not _check_init():
        return
    
    _oled.fill(0)
    _oled.text(text, x, y)
    _oled.show()


def show_data(soil, co2, temp, hum, plant, action):
    """显示传感器数据和状态"""
    if not _check_init():
        return
    
    _oled.fill(0)
    
    # 标题行
    _oled.text("SPACE FARM v1.0", 0, 0)
    
    # 植物类型
    _oled.text(f"Plant: {plant}", 0, 12)
    
    # 传感器数据
    soil_str = f"Soil:{soil}%"
    co2_str = f"CO2:{co2}"
    _oled.text(soil_str, 0, 24)
    _oled.text(co2_str, 64, 24)
    
    # 温湿度
    env_str = f"T:{temp}C H:{hum}%"
    _oled.text(env_str, 0, 36)
    
    # 当前动作
    action_names = {
        "water": "WATERING ",
        "nutrient": "NUTRIENT ",
        "ventilate": "VENTING  ",
        "idle": "IDLE     "
    }
    action_str = f"Act:{action_names.get(action, 'UNKNOWN')}"
    _oled.text(action_str, 0, 48)
    
    _oled.show()


def show_action(action, duration, reason):
    """显示执行动作"""
    if not _check_init():
        return
    
    _oled.fill(0)
    
    # OLED 不支持中文，使用英文缩写
    action_names_en = {
        "water": "WATER",
        "nutrient": "NUTRIENT",
        "ventilate": "FAN",
        "idle": "IDLE"
    }
    
    action_name = action_names_en.get(action, action.upper())
    
    _oled.text("EXECUTING", 32, 10)
    _oled.text("================", 0, 26)
    _oled.text(f"  {action_name}  ", 24, 38)
    _oled.text(f"  {duration}s  ", 24, 50)
    _oled.show()


def show_idle(soil, co2, plant):
    """显示待机状态"""
    if not _check_init():
        return
    
    _oled.fill(0)
    
    _oled.text("STATUS: OK", 32, 8)
    _oled.text("================", 0, 22)
    _oled.text(f"Plant: {plant}", 0, 34)
    _oled.text(f"Soil:{soil}% CO2:{co2}", 0, 46)
    _oled.show()


def show_error(message):
    """显示错误信息"""
    if not _check_init():
        return
    
    _oled.fill(0)
    _oled.text("!!! ERROR !!!", 32, 20)
    
    # 截断过长的消息
    if len(message) > 16:
        _oled.text(message[:16], 0, 40)
        _oled.text(message[16:32], 0, 52)
    else:
        _oled.text(message, 0, 40)
    
    _oled.show()


def show_wifi_status(connected, ip=None):
    """显示 WiFi 状态"""
    if not _check_init():
        return
    
    _oled.fill(0)
    
    if connected:
        _oled.text("WiFi: CONNECTED", 0, 20)
        if ip:
            _oled.text(f"IP: {ip}", 0, 36)
    else:
        _oled.text("WiFi: DISCONNECTED", 0, 20)
        _oled.text("Using local rules", 0, 40)
    
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
    _oled.text("Space Farm", 32, 55)
    
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
