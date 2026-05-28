"""
显示模块 - SH1106 OLED 显示屏
英文模式显示（ASCII 8x8 内置字体）
"""

import sh1106
import time
from machine import I2C, Pin
import config


# 全局 OLED 对象
_oled = None

# 显示状态
_DISPLAY_ON = True

# 植物名称中英文映射（OLED 内置字体不支持中文）
_PLANT_NAMES = {
    "生菜": "Lettuce",
    "小白菜": "BokChoy",
    "菠菜": "Spinach",
    "韭菜": "Chives",
    "番茄": "Tomato",
    "辣椒": "Pepper",
    "黄瓜": "Cucumber",
    "茄子": "Eggplant",
}

_STAGE_CODES = {
    "seedling": "SGL",
    "vegetative": "VEG",
    "flowering": "FLR",
    "fruiting": "FRT",
    "harvesting": "HRV",
}

_ACTION_NAMES = {
    "water": "WATER",
    "idle": "IDLE",
}

_OLED_WIDTH = 128
_OLED_HEIGHT = 64
_CHAR_WIDTH = 8
_CHAR_HEIGHT = 8
_MAX_COLS = _OLED_WIDTH // _CHAR_WIDTH


def _plant_en(name):
    """将植物中文名转为 OLED 可显示的英文名"""
    return _PLANT_NAMES.get(name, name)


def _clip(text, width=16):
    """OLED 内置字体每行约 16 个 ASCII 字符，超长时截断。"""
    if text is None:
        text = ""
    text = str(text)
    clean = ""
    for ch in text:
        code = ord(ch)
        if 32 <= code <= 126:
            clean += ch
        else:
            clean += " "
    return clean[:width]


def _cols_from_x(x):
    if x < 0:
        x = 0
    if x >= _OLED_WIDTH:
        return 0
    return (_OLED_WIDTH - x) // _CHAR_WIDTH


def _draw_text(text, x=0, y=0):
    """Draw ASCII text clipped to the visible OLED area."""
    if y < 0 or y > _OLED_HEIGHT - _CHAR_HEIGHT:
        return
    if x < 0:
        x = 0
    cols = _cols_from_x(x)
    if cols <= 0:
        return
    _oled.text(_clip(text, cols), x, y)


def _draw_centered(text, y):
    text = _clip(text, _MAX_COLS)
    x = max(0, int((_OLED_WIDTH - len(text) * _CHAR_WIDTH) / 2))
    _draw_text(text, x, y)


def _clear_text_area(text, x=0, y=0):
    if y < 0 or y >= _OLED_HEIGHT or x >= _OLED_WIDTH:
        return
    if x < 0:
        x = 0
    width = min(len(_clip(text, _cols_from_x(x))) * _CHAR_WIDTH, _OLED_WIDTH - x)
    if width > 0:
        _oled.fill_rect(x, y, width, min(_CHAR_HEIGHT, _OLED_HEIGHT - y), 0)


def _safe_num(value, default="--"):
    return default if value is None else str(value)


def _stage_code(growth_stage):
    if not growth_stage:
        return "---"
    return _STAGE_CODES.get(growth_stage.get("stage", ""), "---")


def _action_en(action):
    return _ACTION_NAMES.get(action, "IDLE") if action else "IDLE"


def _plant_short(plant, width=6):
    return _clip(_plant_en(plant), width).strip()


def _light_status(light_level, plant_info):
    light_min = plant_info.get("light_min", 30) if plant_info else 30
    light_opt = plant_info.get("light_opt", 50) if plant_info else 50
    if light_level is None:
        return "--", "--"
    if light_level < light_min:
        return "LOW", f"<{light_min}%"
    if light_level < light_opt:
        return "OK", f">{light_min}%"
    return "BEST", f">{light_opt}%"


def _sun_hours_text(sun_minutes_today):
    try:
        return "{:.1f}h".format(sun_minutes_today / 60)
    except Exception:
        return "0.0h"


def _draw_square(x, y, filled):
    if filled:
        for dx in range(3):
            for dy in range(3):
                _oled.pixel(x + dx, y + dy, 1)
    else:
        _oled.pixel(x, y, 1)
        _oled.pixel(x + 1, y, 1)
        _oled.pixel(x + 2, y, 1)
        _oled.pixel(x, y + 1, 1)
        _oled.pixel(x + 2, y + 1, 1)
        _oled.pixel(x, y + 2, 1)
        _oled.pixel(x + 1, y + 2, 1)
        _oled.pixel(x + 2, y + 2, 1)


def _draw_page_dots(page_index, total_pages=3):
    """用像素点绘制页码，避免 Unicode 圆点无法显示。"""
    start_x = 54
    y = 58
    for i in range(total_pages):
        _draw_square(start_x + i * 10, y, i == page_index)


def _progress_info(plant_info, growth_stage, days_since_planting):
    if not plant_info or not growth_stage:
        return 0, 0, None, 0

    days = growth_stage.get("days", [0, 0])
    start_day = days[0] if len(days) > 0 else 0
    end_day = days[1] if len(days) > 1 else start_day
    total = max(1, end_day - start_day + 1)
    in_stage = min(max(days_since_planting - start_day, 0), total)
    pct = min(100, int(in_stage * 100 / total))

    stages = plant_info.get("growth_stages", [])
    next_stage = None
    days_left = max(0, end_day + 1 - days_since_planting)
    for i, stage in enumerate(stages):
        if stage is growth_stage and i + 1 < len(stages):
            next_stage = stages[i + 1]
            break
        if stage.get("days") == days and i + 1 < len(stages):
            next_stage = stages[i + 1]
            break
    return pct, days_left, next_stage, end_day + 1


def _last_action_text(action, duration, last_action_time):
    action_s = _action_en(action).lower()
    if not last_action_time:
        return f"Last:{action_s}"
    try:
        t = time.localtime(last_action_time)
        return f"Last:{action_s} {duration}s @{t[3]:02d}:{t[4]:02d}"
    except Exception:
        return f"Last:{action_s} {duration}s"


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

        _oled = sh1106.SH1106_I2C(128, 64, i2c, addr=0x3C)
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
    _draw_text("================", 0, 0)
    _draw_centered("SPACE FARM", 16)
    _draw_centered("TK-NYZ v1.0", 28)
    _draw_text("================", 0, 44)
    _oled.show()


def show_text(text, x=0, y=0):
    """显示一行文字（会清屏）"""
    if not _check_init():
        return

    _oled.fill(0)
    _draw_text(text, x, y)
    _oled.show()


def show_overlay(text, x=0, y=0):
    """在当前画面上叠加文字（不清屏）"""
    if not _check_init():
        return

    # 先用黑色矩形擦除该区域，再写入新文字
    _clear_text_area(text, x, y)
    _draw_text(text, x, y)
    _oled.show()


def show_page1(
    soil, light, temp, hum, plant, action, plant_info=None,
    growth_stage=None, days_since_planting=0, sun_minutes_today=0,
    wifi_connected=False, decision_reason=""
):
    """Page 1: 核心传感器 + 决策摘要。"""
    if not _check_init():
        return

    _oled.fill(0)

    soil_s = "--" if soil is None else str(soil)
    light_s = "--" if light is None else str(light)
    temp_s = "--" if temp is None else str(temp)
    hum_s = "--" if hum is None else str(hum)
    soil_threshold = plant_info.get("soil_threshold", 30) if plant_info else 30
    soil_cmp = "<" if soil is not None and soil < soil_threshold else ">"
    _, light_cmp = _light_status(light, plant_info)
    wifi_s = "W" if wifi_connected else "-"
    stage_s = _stage_code(growth_stage)
    action_s = _action_en(action)
    reason = _clip(decision_reason, 16).strip()
    if not reason:
        reason = action_s.lower()

    _draw_text(f"{_plant_short(plant)} D{days_since_planting} {stage_s} {wifi_s}", 0, 0)
    _draw_text(f"Soil:{soil_s}% {soil_cmp}{soil_threshold}%", 0, 10)
    _draw_text(f"L:{light_s}% {light_cmp} {_sun_hours_text(sun_minutes_today)}", 0, 20)
    _draw_text(f"T:{temp_s}C H:{hum_s}%", 0, 30)
    _draw_text(f"{action_s}:{reason}", 0, 40)
    _draw_page_dots(0)
    _oled.show()


def show_page2(
    plant, plant_info=None, growth_stage=None, days_since_planting=0,
    sun_minutes_today=0
):
    """Page 2: 生长状态 + 日照累计。"""
    if not _check_init():
        return

    _oled.fill(0)

    stage_s = _stage_code(growth_stage)
    pct, days_left, next_stage, next_start = _progress_info(
        plant_info, growth_stage, days_since_planting
    )
    filled = min(5, max(0, int(pct / 20)))
    bar = "=" * filled + " " * (5 - filled)
    fert = growth_stage.get("fert", "NPK") if growth_stage else "NPK"
    water_need = growth_stage.get("water_need", "normal") if growth_stage else "normal"
    light_hours = plant_info.get("light_hours", [6, 8]) if plant_info else [6, 8]
    sun_hours = sun_minutes_today / 60
    sun_status = "OK" if sun_hours >= light_hours[0] else "LOW"

    _draw_text(f"{_plant_short(plant, 8)} D{days_since_planting} {stage_s}", 0, 0)
    _draw_text(f"Stg:[{bar}]{pct}%", 0, 10)
    _draw_text(f"Fert:{fert} W:{water_need}", 0, 20)
    _draw_text(f"Sun:{sun_hours:.1f}/{light_hours[0]}h {sun_status}", 0, 30)
    if next_stage:
        next_code = _STAGE_CODES.get(next_stage.get("stage", ""), "---")
        _draw_text(f"Next:{next_code} D{next_start} {days_left}d", 0, 40)
    else:
        _draw_text("Final stage", 0, 40)
    _draw_page_dots(1)
    _oled.show()


def show_page3(
    wifi_connected=False, ip=None, ai_enabled=False, start_time=0,
    action_count=0, read_count=0, last_action="idle",
    last_action_duration=0, last_action_time=0
):
    """Page 3: 系统状态。"""
    if not _check_init():
        return

    _oled.fill(0)

    wifi_s = "OK" if wifi_connected else "OFF"
    ip_s = ip or "-"
    ai_s = "ON" if ai_enabled and wifi_connected else "OFF"
    try:
        import gc
        gc.collect()
        mem_kb = int(gc.mem_free() / 1024)
    except Exception:
        mem_kb = 0
    uptime = max(0, int(time.time() - start_time)) if start_time else 0
    up_h = int(uptime / 3600)
    up_m = int((uptime % 3600) / 60)

    _draw_text(f"WiFi:{wifi_s} {ip_s}", 0, 0)
    _draw_text(f"AI:DeepSeek {ai_s}", 0, 10)
    _draw_text(f"Mem:{mem_kb}KB Up:{up_h}h{up_m}m", 0, 20)
    _draw_text(f"Acts:{action_count}/h R{read_count}", 0, 30)
    _draw_text(_last_action_text(last_action, last_action_duration, last_action_time), 0, 40)
    _draw_page_dots(2)
    _oled.show()


def show_data(
    soil, light, temp, hum, plant, action, page_index=0, plant_info=None,
    growth_stage=None, days_since_planting=0, sun_minutes_today=0,
    wifi_connected=False, ip=None, ai_enabled=False, start_time=0,
    action_count=0, read_count=0, last_action_duration=0,
    last_action_time=0, decision_reason=""
):
    """显示传感器数据和状态（三页轮播入口，保留旧签名兼容性）。"""
    page_index = page_index % 3
    if page_index == 0:
        show_page1(
            soil, light, temp, hum, plant, action, plant_info,
            growth_stage, days_since_planting, sun_minutes_today,
            wifi_connected, decision_reason
        )
    elif page_index == 1:
        show_page2(
            plant, plant_info, growth_stage, days_since_planting,
            sun_minutes_today
        )
    else:
        show_page3(
            wifi_connected, ip, ai_enabled, start_time, action_count,
            read_count, action, last_action_duration, last_action_time
        )


def show_action(action, duration, reason):
    """显示执行动作"""
    if not _check_init():
        return

    _oled.fill(0)

    action_en = _action_en(action)

    _draw_text(f">> {action_en}", 0, 8)
    _draw_text("================", 0, 26)
    _draw_centered(f"{duration}s", 38)
    _oled.show()


def show_idle(soil, light, plant, temp=None, hum=None):
    """显示待机状态（含温湿度）"""
    show_page1(soil, light, temp, hum, plant, "idle")


def show_error(message):
    """显示错误信息"""
    if not _check_init():
        return

    _oled.fill(0)
    _draw_centered("!! ERROR !!", 4)
    _draw_text("================", 0, 18)

    # 截断过长的消息（16 ASCII 字符/行）
    message = _clip(message, 32)
    if len(message) > _MAX_COLS:
        _draw_text(message[:_MAX_COLS], 0, 34)
        _draw_text(message[_MAX_COLS:_MAX_COLS * 2], 0, 46)
    else:
        _draw_text(message, 0, 38)

    _oled.show()


def show_wifi_status(connected, ip=None):
    """显示 WiFi 状态"""
    if not _check_init():
        return

    _oled.fill(0)

    if connected:
        _draw_text("WiFi: OK", 0, 20)
        if ip:
            _draw_text(f"IP:{ip}", 0, 36)
    else:
        _draw_text("WiFi: FAIL", 0, 20)
        _draw_text("Local rules", 0, 40)

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
    _draw_centered("SPACE FARM", 55)

    _oled.show()


# ============ 菜单显示 ============

_MENU_VISIBLE_ITEMS = 5   # 每屏最多显示 5 个菜单项
_MENU_ITEM_Y_START = 8    # 第一项 Y 坐标


def show_menu(title, items, selected_idx, scroll_offset=0):
    """渲染通用菜单。

    Args:
        title: 菜单标题（ASCII，≤16 字符）
        items: 菜单项列表（字符串）
        selected_idx: 当前选中项索引
        scroll_offset: 滚动偏移量（第一项在列表中的索引）
    """
    if not _check_init():
        return

    _oled.fill(0)

    # 标题行
    _draw_centered(title, 0)

    # 可见选项范围
    visible_items = items[scroll_offset:scroll_offset + _MENU_VISIBLE_ITEMS]
    for i, item_text in enumerate(visible_items):
        abs_idx = scroll_offset + i
        y = _MENU_ITEM_Y_START + i * 10
        is_selected = (abs_idx == selected_idx)

        prefix = ">" if is_selected else " "
        display_text = f"{prefix} {_clip(item_text, 14)}"
        _draw_text(display_text, 0, y)

    # 底部提示
    hint_y = _MENU_ITEM_Y_START + _MENU_VISIBLE_ITEMS * 10 + 2
    _draw_text("[<>]Nav [OK]Sel", 0, hint_y)

    _oled.show()


def show_plant_select(plant_list, current_idx):
    """渲染植物选择菜单。

    Args:
        plant_list: 植物名称列表（中文，会自动转为英文显示）
        current_idx: 当前选中索引
    """
    if not _check_init():
        return

    _oled.fill(0)

    # 标题
    _draw_centered("Select Plant", 0)

    # 计算滚动偏移，使当前选中项尽量居中
    half = _MENU_VISIBLE_ITEMS // 2
    scroll_offset = max(0, current_idx - half)
    if scroll_offset + _MENU_VISIBLE_ITEMS > len(plant_list):
        scroll_offset = max(0, len(plant_list) - _MENU_VISIBLE_ITEMS)

    visible_items = plant_list[scroll_offset:scroll_offset + _MENU_VISIBLE_ITEMS]
    for i, plant_name in enumerate(visible_items):
        abs_idx = scroll_offset + i
        y = _MENU_ITEM_Y_START + i * 10
        is_selected = (abs_idx == current_idx)

        prefix = ">" if is_selected else " "
        en_name = _plant_en(plant_name)
        display_text = f"{prefix} {_clip(en_name, 13)}"
        _draw_text(display_text, 0, y)

    # 底部：页码提示 + 操作提示
    hint_y = _MENU_ITEM_Y_START + _MENU_VISIBLE_ITEMS * 10 + 2
    _draw_text(f"{current_idx + 1}/{len(plant_list)}", 0, hint_y)
    _draw_text("OK:Select", 74, hint_y)

    _oled.show()


def show_complete_menu(title, items, selected_idx):
    """渲染完整主菜单（植物选择 / 手动控制 / 系统信息 / 返回）。

    与 show_menu 类似，但底部提示支持长按返回。
    """
    if not _check_init():
        return

    _oled.fill(0)

    # 标题行
    _draw_centered(title, 0)

    # 选项
    visible_count = min(len(items), _MENU_VISIBLE_ITEMS)
    for i in range(visible_count):
        y = _MENU_ITEM_Y_START + i * 10
        is_selected = (i == selected_idx)

        prefix = ">" if is_selected else " "
        display_text = f"{prefix} {_clip(items[i], 14)}"
        _draw_text(display_text, 0, y)

    # 底部提示
    hint_y = _MENU_ITEM_Y_START + _MENU_VISIBLE_ITEMS * 10 + 2
    _draw_text("[<>]Nav [OK]OK", 0, hint_y)

    _oled.show()


def show_system_info(wifi_connected, ip, mem_free_kb):
    """渲染系统信息界面。"""
    if not _check_init():
        return

    _oled.fill(0)

    wifi_s = "OK" if wifi_connected else "OFF"
    ip_s = ip or "-"

    _draw_centered("System Info", 0)
    _draw_text(f"WiFi: {wifi_s}", 0, 16)
    _draw_text(f"IP:  {ip_s}", 0, 26)
    _draw_text(f"Mem: {mem_free_kb}KB free", 0, 36)
    _draw_text("", 0, 46)
    _draw_text("Long press:Back", 0, 56)

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
