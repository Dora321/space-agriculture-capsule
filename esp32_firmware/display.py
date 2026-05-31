"""
显示模块 - SH1106 OLED 显示屏
英文模式显示（ASCII 8x8 内置字体）
"""

import sh1106
import time
from machine import I2C, Pin
import config

# 2x 字体渲染：通过 framebuf 读取字形 bit 再逐像素 2x 放大
try:
    import framebuf as _framebuf
    _HAS_FRAMEBUF = True
except ImportError:
    _HAS_FRAMEBUF = False

_oled = None
_DISPLAY_ON = True

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

def _icon(rows):
    return [
        (x, y)
        for y, row in enumerate(rows)
        for x, ch in enumerate(row)
        if ch == "#"
    ]


# 7x7 阶段像素图标。仍能放进 128x64 OLED 标题栏，但比原 5x5 更像真实对象。
_STAGE_ICON_PIXELS = {
    "SGL": _icon([  # 幼苗：两片子叶 + 直立茎
        "...#...",
        ".##.##.",
        "..###..",
        "...#...",
        "...#...",
        "...#...",
        "..###..",
    ]),
    "VEG": _icon([  # 生长期：叶冠 + 茎
        "..#.#..",
        ".#####.",
        "#######",
        ".#####.",
        "..###..",
        "...#...",
        "..###..",
    ]),
    "FLR": _icon([  # 开花：花瓣围绕花心
        "..#.#..",
        ".#.#.#.",
        "..###..",
        "###.###",
        "..###..",
        ".#.#.#.",
        "..#.#..",
    ]),
    "FRT": _icon([  # 结果：带果柄的圆果
        "...#...",
        "..###..",
        ".#####.",
        "#######",
        "#######",
        ".#####.",
        "..###..",
    ]),
    "HRV": _icon([  # 采收：篮筐
        "..###..",
        ".#...#.",
        "#######",
        "#.#.#.#",
        "#######",
        ".#####.",
        "..###..",
    ]),
}


def _draw_stage_icon(stage_code, x, y, color=1):
    """在 (x, y) 处绘制 7x7 阶段像素图标。"""
    pixels = _STAGE_ICON_PIXELS.get(stage_code)
    if not pixels:
        return
    for dx, dy in pixels:
        px, py = x + dx, y + dy
        if 0 <= px < _OLED_WIDTH and 0 <= py < _OLED_HEIGHT:
            _oled.pixel(px, py, color)


_ACTION_NAMES = {
    "water": "WATER",
    "light": "LIGHT",
    "idle": "IDLE",
}

_OLED_WIDTH = 128
_OLED_HEIGHT = 64
_CHAR_WIDTH = 8
_CHAR_HEIGHT = 8
_MAX_COLS = _OLED_WIDTH // _CHAR_WIDTH


# ============ 基础工具 ============

def _plant_en(name):
    return _PLANT_NAMES.get(name, name)


def _clip(text, width=16):
    if text is None:
        text = ""
    text = str(text)
    clean = ""
    for ch in text:
        code = ord(ch)
        clean += ch if 32 <= code <= 126 else " "
    return clean[:width]


def _cols_from_x(x):
    if x < 0:
        x = 0
    if x >= _OLED_WIDTH:
        return 0
    return (_OLED_WIDTH - x) // _CHAR_WIDTH


def _draw_text(text, x=0, y=0, color=1):
    if y < 0 or y > _OLED_HEIGHT - _CHAR_HEIGHT:
        return
    if x < 0:
        x = 0
    cols = _cols_from_x(x)
    if cols <= 0:
        return
    _oled.text(_clip(text, cols), x, y, color)


def _draw_centered(text, y, color=1):
    text = _clip(text, _MAX_COLS)
    x = max(0, (_OLED_WIDTH - len(text) * _CHAR_WIDTH) // 2)
    _draw_text(text, x, y, color)


def _clear_text_area(text, x=0, y=0):
    if y < 0 or y >= _OLED_HEIGHT or x >= _OLED_WIDTH:
        return
    if x < 0:
        x = 0
    width = min(len(_clip(text, _cols_from_x(x))) * _CHAR_WIDTH, _OLED_WIDTH - x)
    if width > 0:
        _oled.fill_rect(x, y, width, min(_CHAR_HEIGHT, _OLED_HEIGHT - y), 0)


def _stage_code(growth_stage):
    if not growth_stage:
        return "---"
    return _STAGE_CODES.get(growth_stage.get("stage", ""), "---")


def _action_en(action):
    return _ACTION_NAMES.get(action, "IDLE") if action else "IDLE"


def _plant_short(plant, width=6):
    return _clip(_plant_en(plant), width).strip()


def _sun_hours_text(sun_minutes_today):
    try:
        return "{:.1f}h".format(sun_minutes_today / 60)
    except Exception:
        return "0.0h"


def _last_action_text(action, duration, last_action_time):
    action_s = _action_en(action).lower()
    if not last_action_time:
        return "Last: {}".format(action_s)
    try:
        t = time.localtime(last_action_time)
        return "Last: {} {}s @{:02d}:{:02d}".format(action_s, duration, t[3], t[4])
    except Exception:
        return "Last: {} {}s".format(action_s, duration)


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


# ============ 绘图原语 ============

def _draw_hline(y):
    _oled.line(0, y, 127, y, 1)


def _draw_inverted(text, y=0, h=10):
    """反色标题栏：白底黑字。"""
    _oled.fill_rect(0, y, 128, h, 1)
    _oled.text(_clip(text, 16), 0, y + 1, 0)


def _draw_bar(label, value, threshold, y):
    """带标签的进度条: LABEL [████░░] NNN%"""
    _draw_text(label, 0, y)
    bx, bw, bh = 34, 60, 7
    _oled.rect(bx, y, bw, bh, 1)
    if value is not None:
        fw = max(0, min(bw - 2, int((bw - 2) * value / 100)))
        if fw > 0:
            _oled.fill_rect(bx + 1, y + 1, fw, bh - 2, 1)
        if threshold is not None and 0 < threshold < 100 and y >= 2:
            tx = bx + 1 + int((bw - 2) * threshold / 100)
            _oled.pixel(tx, y - 2, 1)
            _oled.pixel(tx, y - 1, 1)
        _draw_text("{:3d}%".format(value), 96, y)
    else:
        _draw_text("  --", 96, y)


def _draw_wide_bar(value, y, h=7):
    """全宽进度条（128px），无标签，适合用在大数字下方做视觉强化。"""
    _oled.rect(0, y, 128, h, 1)
    if value is not None:
        fw = max(0, min(126, int(126 * value / 100)))
        if fw > 0:
            _oled.fill_rect(1, y + 1, fw, h - 2, 1)


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
    start_x = 54
    y = 58
    for i in range(total_pages):
        _draw_square(start_x + i * 10, y, i == page_index)


def _draw_text_2x(text, x, y, color=1):
    """2x 放大文字：每个像素渲染为 2x2 块。无 framebuf 时降级为 1x。"""
    if not _HAS_FRAMEBUF:
        _draw_text(text, x, y, color)
        return
    buf = bytearray(8)
    fb = _framebuf.FrameBuffer(buf, 8, 8, _framebuf.MONO_VLSB)
    for ci, ch in enumerate(text):
        cx = x + ci * 16
        if cx + 15 >= _OLED_WIDTH or y + 15 >= _OLED_HEIGHT:
            break
        fb.fill(0)
        fb.text(ch, 0, 0, 1)
        for py in range(8):
            for px in range(8):
                if fb.pixel(px, py):
                    _oled.fill_rect(cx + px * 2, y + py * 2, 2, 2, color)


def _draw_centered_2x(text, y, color=1):
    """2x 放大文字，居中显示。"""
    w = len(text) * 16
    x = max(0, (128 - w) // 2)
    _draw_text_2x(text, x, y, color)


# ============ 状态判断 ============

def _soil_status(soil, threshold):
    """土壤状态：返回 4 字符状态标签。"""
    if soil is None:
        return " -- "
    if soil >= threshold:
        return " OK "
    if soil >= int(threshold * 0.7):
        return " LOW"
    return "DRYN"


def _light_status_word(light, opt):
    """光照状态：返回 3 字符标签。"""
    if light is None:
        return " --"
    if light >= opt:
        return " OK"
    if light >= int(opt * 0.5):
        return "LOW"
    return "DRK"


# ============ 初始化 ============

def init():
    global _oled
    try:
        i2c = I2C(
            0,
            scl=Pin(config.OLED_SCL_PIN),
            sda=Pin(config.OLED_SDA_PIN),
            freq=config.OLED_I2C_FREQ
        )
        devices = i2c.scan()
        if 0x3C not in devices:
            print("[Display] OLED (0x3C) not detected, addresses: {}".format(devices))
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
        print("[Display] OLED initialization failed: {}".format(e))
        return False


def _check_init():
    if _oled is None:
        print("[Display] OLED not initialized")
        return False
    return True


# ============ 系统画面 ============

def clear():
    if _check_init():
        _oled.fill(0)


def show():
    if _check_init():
        _oled.show()


def show_boot():
    """欢迎界面：2x 大字 SPACE / FARM + 星空点缀。

    y= 0: 外框
    y=10-25: "SPACE" 2x 居中
    y=28-43: "FARM"  2x 居中
    y=47:   内部分隔线
    y=51:   "TK-NYZ  v2.0" 小字
    """
    if not _check_init():
        return
    _oled.fill(0)

    _oled.rect(0, 0, 128, 64, 1)  # 外框

    # 星空装饰（稀疏像素点，避开 2x 文字区域 x=24..103 y=10..43）
    for px, py in [(6, 3), (22, 5), (55, 2), (88, 4), (110, 3), (123, 6),
                   (3, 22), (3, 42), (124, 19), (124, 45),
                   (12, 60), (48, 61), (80, 61), (115, 60)]:
        _oled.pixel(px, py, 1)

    _draw_centered_2x("SPACE", 10)   # 16px 高，y=10..25
    _draw_centered_2x("FARM",  28)   # 16px 高，y=28..43

    _oled.line(10, 47, 117, 47, 1)  # 内分隔线
    _draw_centered("Seeds in Space", 51)

    _oled.show()


def show_boot_check(wifi_ok, ip=None):
    """系统自检结果界面（欢迎画面后显示约 2s）。

    y= 0- 9: [SYSTEM CHECK] 反色标题
    y=13-33: Sensors / WiFi / Actuators 状态行（右对齐标签）
    y=43:    分隔线
    y=46-56: IP 地址 + AI 状态
    """
    if not _check_init():
        return

    _oled.fill(0)
    _draw_inverted("SYSTEM CHECK")

    def _rpad(s, w):
        return (" " * max(0, w - len(s))) + s

    # 状态行：label 左对齐，状态右对齐，共 16 字符
    _draw_text("Sensors" + _rpad("OK", 9), 0, 13)
    wifi_label = "WiFi" + _rpad("Online" if wifi_ok else "Offline", 12)
    _draw_text(wifi_label, 0, 23)
    _draw_text("Actuators" + _rpad("OK", 7), 0, 33)

    _draw_hline(43)

    if wifi_ok:
        ip_line = ("IP: " + _clip(ip, 12)) if ip else "IP: connected"
        _draw_text(ip_line, 0, 46)
        _draw_text("AI: DeepSeek ON", 0, 56)
    else:
        _draw_text("AI: local rules", 0, 46)
        _draw_text("No cloud service", 0, 56)

    _oled.show()


def show_text(text, x=0, y=0):
    if not _check_init():
        return
    _oled.fill(0)
    _draw_text(text, x, y)
    _oled.show()


def show_overlay(text, x=0, y=0):
    if not _check_init():
        return
    _clear_text_area(text, x, y)
    _draw_text(text, x, y)
    _oled.show()


def show_action(action, duration, reason):
    """执行中提示：反色标题 + 倒计时框。"""
    if not _check_init():
        return
    _oled.fill(0)
    _draw_inverted(">> {}".format(_action_en(action)))
    _oled.rect(40, 15, 48, 16, 1)
    _draw_centered("{:d}s".format(duration), 19)
    if reason:
        _draw_hline(35)
        _draw_centered(_clip(reason, 16), 40)
    _oled.show()


def show_idle(soil, light, plant, temp=None, hum=None):
    show_page1(soil, light, temp, hum, plant, "idle")


def show_error(message):
    """错误画面。"""
    if not _check_init():
        return
    _oled.fill(0)
    _draw_inverted("!! ERROR !!")
    message = _clip(message, 32)
    if len(message) > _MAX_COLS:
        _draw_text(message[:_MAX_COLS], 0, 16)
        _draw_text(message[_MAX_COLS:_MAX_COLS * 2], 0, 28)
    else:
        _draw_text(message, 0, 20)
    _oled.show()


def show_wifi_status(connected, ip=None):
    """WiFi 连接结果。"""
    if not _check_init():
        return
    _oled.fill(0)
    if connected:
        _draw_inverted("WIFI: CONNECTED")
        _draw_centered(ip or "", 20)
        _draw_centered("AI enabled", 32)
    else:
        _draw_inverted("WIFI: OFFLINE")
        _draw_centered("Local rules only", 20)
        _draw_centered("AI disabled", 32)
    _oled.show()
    time.sleep(2)


# ============ 三页主显示 ============
#
# Page 1  SOIL  ── 土壤湿度占主屏，2x 大字 + 全宽进度条
#         标语：一眼知道"现在够不够水"
#
# Page 2  GROW  ── 光照 + 生长阶段 + 环境参数
#         标语：一眼知道"植物长得怎么样"
#
# Page 3  SYS   ── WiFi / AI / 内存 / 上次执行
#         标语：一眼知道"系统在不在线"
#
# 布局约束：128x64 像素，8x8 ASCII 字体，8 行
# ============

def show_page1(
    soil, light, temp, hum, plant, action, plant_info=None,
    growth_stage=None, days_since_planting=0, sun_minutes_today=0,
    wifi_connected=False, decision_reason=""
):
    """Page 1 — SOIL 主视图。

    y= 0- 9  [██ LETTU  D12  VEG  W  ██]  反色标题栏
    y=11-26  居中 2x 放大土壤湿度百分比（如 "72%"）
    y=27-34  居中状态词：SOIL  OK / SOIL  LOW / SOIL DRYN
    y=36     土壤阈值刻度（1px）
    y=37-43  全宽进度条（128px）
    y=45-52  辅助行：光照 / 温度 / 湿度
    y=54     分隔线
    y=56-63  当前动作
    """
    if not _check_init():
        return

    _oled.fill(0)

    # ── 反色标题栏 + 阶段图标 ────────────────────────────
    plant5 = _plant_short(plant, 5)
    stage_s = _stage_code(growth_stage)
    _draw_inverted("{} D{}  {}".format(plant5, days_since_planting, stage_s))
    _draw_stage_icon(stage_s, 120, 2, color=0)  # 白底黑色图标，右侧 7x7

    # ── 土壤湿度 2x 大字（居中）─────────────────────────
    soil_thr = plant_info.get("soil_threshold", 30) if plant_info else 30
    soil_s = "{}%".format(soil) if soil is not None else "--"
    _draw_centered_2x(soil_s, 11)

    # ── 状态词 ──────────────────────────────────────────
    status = _soil_status(soil, soil_thr)
    _draw_centered("SOIL {}".format(status), 28)

    # ── 全宽进度条 + 阈值刻度 ───────────────────────────
    if soil is not None and 0 < soil_thr < 100:
        tx = 1 + int(126 * soil_thr / 100)
        _oled.pixel(tx, 36, 1)   # 阈值刻度在条上方 1px
    _draw_wide_bar(soil, 37)

    # ── 辅助行：光照 / 温度 / 湿度 ──────────────────────
    light_opt = plant_info.get("light_opt", 50) if plant_info else 50
    lw = _light_status_word(light, light_opt)
    light_val = "{}".format(light) if light is not None else "--"
    temp_val = "{}".format(temp) if temp is not None else "--"
    hum_val = "{}".format(hum) if hum is not None else "--"
    _draw_text("L:{}%{}  T:{}  H:{}%".format(light_val, lw, temp_val, hum_val), 0, 45)

    # ── 分隔线 + 当前动作 ────────────────────────────────
    _draw_hline(54)
    action_s = _action_en(action)
    reason = _clip(decision_reason, 7).strip() if decision_reason else ""
    if reason:
        _draw_text("> {} {}".format(action_s, reason), 0, 56)
    else:
        _draw_text("> {}".format(action_s), 0, 56)

    _oled.show()


def show_page2(
    plant, plant_info=None, growth_stage=None, days_since_planting=0,
    sun_minutes_today=0
):
    """Page 2 — GROW 生长视图。

    y= 0- 9  [██ LETTU  D12  VEG → FLR 3d ██]  反色标题栏（含下阶段倒计时）
    y=12-18  LITE 进度条（光照）
    y=20-27  T:24C  H:65%  Sun:4.2h
    y=29-35  PROG 进度条（阶段完成度）
    y=37-43  F:NPK  W:heavy
    y=55-63  [○ ● ○] 页码点
    """
    if not _check_init():
        return

    _oled.fill(0)

    # ── 反色标题栏（含下阶段信息）─────────────────────
    pct, days_left, next_stage, _ = _progress_info(
        plant_info, growth_stage, days_since_planting
    )
    plant5 = _plant_short(plant, 5)
    stage_s = _stage_code(growth_stage)
    if next_stage:
        next_code = _STAGE_CODES.get(next_stage.get("stage", ""), "---")
        header = "{} D{}  {}>{}  {}d".format(
            plant5, days_since_planting, stage_s, next_code, days_left
        )
    else:
        header = "{} D{}  {} FINAL".format(plant5, days_since_planting, stage_s)
    _draw_inverted(header)

    # ── 光照进度条 ──────────────────────────────────────
    light_opt = plant_info.get("light_opt", 50) if plant_info else 50
    _draw_bar("LITE", None, light_opt, 12)  # value filled below by caller
    # 注意：show_page2 没有直接接收 light 参数，通过 show_data 路由时已知
    # 这里仅显示阶段数据，light 见 Page 1

    # ── 温度 / 湿度 / 日照 ──────────────────────────────
    light_hours = plant_info.get("light_hours", [6, 8]) if plant_info else [6, 8]
    sun_h = sun_minutes_today / 60
    sun_ok = "OK" if sun_h >= light_hours[0] else "LO"
    _draw_text("Sun:{:.1f}/{:d}h {}".format(sun_h, light_hours[0], sun_ok), 0, 22)

    # ── 阶段完成度进度条 ────────────────────────────────
    _draw_bar("PROG", pct, None, 32)

    # ── 施肥 + 水分需求 ─────────────────────────────────
    fert = growth_stage.get("fert", "---") if growth_stage else "---"
    water_need = growth_stage.get("water_need", "---") if growth_stage else "---"
    _draw_text("Fert:{:<3}  Water:{}".format(fert, _clip(water_need, 6)), 0, 43)

    _draw_page_dots(1)
    _oled.show()


def show_page2_full(
    plant, light, plant_info=None, growth_stage=None, days_since_planting=0,
    sun_minutes_today=0, temp=None, hum=None
):
    """Page 2 — GROW 生长视图，与 Page 1 结构完全一致。

    y= 0- 9: 反色标题（植物 + 天数 + 当前→下阶段剩余天数）
    y=11-26: 2x 阶段进度百分比（主视觉大数字）
    y=28-35: "VEG   63% done" 居中状态行
    y=37-43: 全宽阶段进度条
    y=45-52: LITE 光照进度条（label+bar+value）
    y=54:    分隔线
    y=56-63: 施肥 + 水分需求
    """
    if not _check_init():
        return

    _oled.fill(0)

    pct, days_left, next_stage, _ = _progress_info(
        plant_info, growth_stage, days_since_planting
    )
    plant5 = _plant_short(plant, 5)
    stage_s = _stage_code(growth_stage)

    # ── 反色标题：含阶段跳转路径 ────────────────────────
    if next_stage:
        next_code = _STAGE_CODES.get(next_stage.get("stage", ""), "---")
        header = "{} D{}  {}>{}  {}d".format(
            plant5, days_since_planting, stage_s, next_code, days_left
        )
    else:
        header = "{} D{}  {} FINAL".format(plant5, days_since_planting, stage_s)
    _draw_inverted(header)

    # ── 阶段进度 2x 大字（居中）─────────────────────────
    _draw_centered_2x("{}%".format(pct), 11)

    # ── 状态行 ──────────────────────────────────────────
    _draw_centered("{} {}% done".format(stage_s, pct), 28)
    _draw_stage_icon(stage_s, 0, 29)

    # ── 全宽阶段进度条 ───────────────────────────────────
    _draw_wide_bar(pct, 37)

    # ── LITE 光照进度条（与 Page 1 辅助行同风格）──────────
    light_opt = plant_info.get("light_opt", 50) if plant_info else 50
    _draw_bar("LITE", light, light_opt, 45)

    # ── 分隔线 + 施肥 / 水分需求 ─────────────────────────
    _draw_hline(54)
    fert = growth_stage.get("fert", "---") if growth_stage else "---"
    water_need = growth_stage.get("water_need", "---") if growth_stage else "---"
    _draw_text("F:{:<3}  Water:{}".format(fert, _clip(water_need, 6)), 0, 56)

    _oled.show()


def show_page3(
    wifi_connected=False, ip=None, ai_enabled=False, start_time=0,
    action_count=0, read_count=0, last_action="idle",
    last_action_duration=0, last_action_time=0,
    uart_enabled=False, pi_online=False
):
    """Page 3 — SYS 系统视图，与 Page 1 结构完全一致。

    y= 0- 9: 反色标题（WIFI/PI + AI 状态）
    y=11-26: 2x 运行时长（"2h" 或 "45m"）
    y=28-35: "UP  2h 15min" 居中状态行
    y=37-43: MEM 内存余量进度条（label+bar+value）
    y=45-52: IP 地址或 UART 链路状态
    y=54:    分隔线
    y=56-63: 上次执行记录
    """
    if not _check_init():
        return

    _oled.fill(0)

    # ── 反色标题：单机 WiFi 模式显示 WiFi，双层模式显示 Pi 链路 ─────
    if uart_enabled:
        link_s = "PI:OK  " if pi_online else "PI:OFF "
        ai_s = "AI:PI" if pi_online else "AI:LOCAL"
        _draw_inverted("{} {}".format(link_s, ai_s))
    else:
        wifi_s = "WIFI:OK " if wifi_connected else "WIFI:OFF"
        ai_s = "AI:ON" if (ai_enabled and wifi_connected) else "AI:OFF"
        _draw_inverted("{} {}".format(wifi_s, ai_s))

    # ── 内存 2x 大字（空闲 KB）──────────────────────
    try:
        import gc
        gc.collect()
        mem_free = gc.mem_free()
        mem_total = mem_free + gc.mem_alloc()
        mem_pct = int(mem_free * 100 / mem_total) if mem_total > 0 else 0
        mem_kb = int(mem_free / 1024)
    except Exception:
        mem_pct, mem_kb = 0, 0
    _draw_centered_2x("{}K".format(mem_kb), 11)

    # ── 状态行 ───────────────────────────────────────
    if mem_pct >= 50:
        mem_status = " OK "
    elif mem_pct >= 30:
        mem_status = " LOW"
    else:
        mem_status = "CRIT"
    _draw_centered("MEM {}".format(mem_status), 28)

    # ── 全宽内存余量条（与 Page 1 土壤条同风格）──────
    _draw_wide_bar(mem_pct, 37)

    # ── IP 地址 / UART 链路状态 ───────────────────────
    if uart_enabled:
        ip_line = "UART payload link" if pi_online else "UART waiting Pi"
    elif ip:
        ip_line = ip
    elif wifi_connected:
        ip_line = "DHCP pending..."
    else:
        ip_line = "no connection"
    _draw_text(_clip(ip_line, 16), 0, 45)

    # ── 分隔线 + 上次执行 ────────────────────────────
    _draw_hline(54)
    action_s = _action_en(last_action)
    if last_action_time:
        try:
            t = time.localtime(last_action_time)
            time_s = "{:02d}:{:02d}".format(t[3], t[4])
        except Exception:
            time_s = "--:--"
        _draw_text("> {} @{}".format(action_s, time_s), 0, 56)
    else:
        _draw_text("> {}".format(action_s), 0, 56)

    _oled.show()


def show_data(
    soil, light, temp, hum, plant, action, page_index=0, plant_info=None,
    growth_stage=None, days_since_planting=0, sun_minutes_today=0,
    wifi_connected=False, ip=None, ai_enabled=False, start_time=0,
    action_count=0, read_count=0, last_action_duration=0,
    last_action_time=0, decision_reason="", uart_enabled=False, pi_online=False
):
    """三页轮播入口（保留旧签名兼容性）。"""
    page_index = page_index % 3
    if page_index == 0:
        show_page1(
            soil, light, temp, hum, plant, action, plant_info,
            growth_stage, days_since_planting, sun_minutes_today,
            wifi_connected, decision_reason
        )
    elif page_index == 1:
        show_page2_full(
            plant, light, plant_info, growth_stage,
            days_since_planting, sun_minutes_today,
            temp=temp, hum=hum
        )
    else:
        show_page3(
            wifi_connected, ip, ai_enabled, start_time, action_count,
            read_count, action, last_action_duration, last_action_time,
            uart_enabled=uart_enabled, pi_online=pi_online
        )


def scroll_text(text, delay_ms=100):
    if not _check_init():
        return
    x = 128
    for _ in range(len(text) * 10):
        _oled.fill(0)
        _oled.text(text, x, 28)
        _oled.show()
        x -= 1
        if x < -len(text) * 8:
            break
        time.sleep_ms(delay_ms)


def show_graphic():
    if not _check_init():
        return
    _oled.fill(0)
    _oled.line(64, 50, 64, 30, 1)
    _oled.line(64, 35, 50, 28, 1)
    _oled.line(50, 28, 45, 35, 1)
    _oled.line(64, 35, 78, 28, 1)
    _oled.line(78, 28, 83, 35, 1)
    cx, cy, r = 64, 18, 6
    _oled.pixel(cx, cy - r, 1)
    _oled.pixel(cx + r, cy, 1)
    _oled.pixel(cx, cy + r, 1)
    _oled.pixel(cx - r, cy, 1)
    _oled.line(cx - 4, cy - 4, cx + 4, cy + 4, 1)
    _oled.line(cx - 4, cy + 4, cx + 4, cy - 4, 1)
    _draw_centered("SPACE FARM", 55)
    _oled.show()


# ============ 菜单显示 ============

_MENU_VISIBLE_ITEMS = 5
_MENU_ITEM_Y_START = 8


def show_menu(title, items, selected_idx, scroll_offset=0):
    if not _check_init():
        return
    _oled.fill(0)
    _draw_centered(title, 0)
    visible_items = items[scroll_offset:scroll_offset + _MENU_VISIBLE_ITEMS]
    for i, item_text in enumerate(visible_items):
        abs_idx = scroll_offset + i
        y = _MENU_ITEM_Y_START + i * 10
        prefix = ">" if abs_idx == selected_idx else " "
        _draw_text("{} {}".format(prefix, _clip(item_text, 14)), 0, y)
    hint_y = _MENU_ITEM_Y_START + _MENU_VISIBLE_ITEMS * 10 + 2
    _draw_text("<>nav  G:ok  B:bk", 0, hint_y)
    _oled.show()


def show_plant_select(plant_list, current_idx):
    """植物选择：光标固定在第3行，列表循环滚动经过光标。

    布局（128x64）:
      y= 0- 9  反色标题栏："Select  3/8"
      y=11-18  Row 0  普通
      y=20-27  Row 1  普通
      y=29-36  Row 2  ← 光标（反色高亮，永不移动）
      y=38-45  Row 3  普通
      y=47-54  Row 4  普通
    """
    if not _check_init():
        return

    _oled.fill(0)

    plant_count = len(plant_list)
    CURSOR_POS = 2    # 光标固定在第 3 行（0-indexed）
    ITEM_Y0 = 11      # 第一行起始 y
    ITEM_DY = 9       # 行间距（8px 字体 + 1px 间隙）

    # 反色标题栏，含当前序号
    _draw_inverted("Select  {}/{}".format(current_idx + 1, plant_count))

    # 以 current_idx 为中心，计算最顶部可见项（循环取模）
    top_idx = (current_idx - CURSOR_POS) % plant_count

    for i in range(_MENU_VISIBLE_ITEMS):
        abs_idx = (top_idx + i) % plant_count
        y = ITEM_Y0 + i * ITEM_DY
        name = _clip(_plant_en(plant_list[abs_idx]), 13)

        if i == CURSOR_POS:
            # 光标行：全宽白底 + 黑字 + ">" 前缀
            _oled.fill_rect(0, y, 128, 8, 1)
            _draw_text("> {}".format(name), 0, y, 0)
        else:
            _draw_text("  {}".format(name), 0, y, 1)

    _oled.show()


def show_day_select(day, stage_name=None):
    """天数选择界面。

    布局（128x64）：
      y= 0- 9  反色标题栏 "Set Day"
      y=14-29  2x 放大天数数字，居中
      y=32     分隔线
      y=36-43  生长阶段（如有）
      y=54-63  提示 "<>:±1  G:OK  B:Skip"
    """
    if not _check_init():
        return
    _oled.fill(0)
    _draw_inverted("Set Day")
    _draw_centered_2x("{}".format(day), 14)
    _draw_hline(32)
    if stage_name:
        _draw_centered("Stage: {}".format(stage_name), 36)
    _draw_text("<>:+-1  G:OK  B:Skip", 0, 54)
    _oled.show()


def show_complete_menu(title, items, selected_idx):
    if not _check_init():
        return
    _oled.fill(0)
    _draw_centered(title, 0)
    visible_count = min(len(items), _MENU_VISIBLE_ITEMS)
    for i in range(visible_count):
        y = _MENU_ITEM_Y_START + i * 10
        prefix = ">" if i == selected_idx else " "
        _draw_text("{} {}".format(prefix, _clip(items[i], 14)), 0, y)
    hint_y = _MENU_ITEM_Y_START + _MENU_VISIBLE_ITEMS * 10 + 2
    _draw_text("<>nav  G:ok  B:bk", 0, hint_y)
    _oled.show()


def show_system_info(wifi_connected, ip, mem_free_kb):
    if not _check_init():
        return
    _oled.fill(0)
    wifi_s = "OK" if wifi_connected else "OFF"
    _draw_centered("System Info", 0)
    _draw_text("WiFi: {}".format(wifi_s), 0, 16)
    _draw_text("IP:  {}".format(ip or "-"), 0, 26)
    _draw_text("Mem: {}KB free".format(mem_free_kb), 0, 36)
    _draw_text("Blue: Back", 0, 56)
    _oled.show()


def power_off():
    global _DISPLAY_ON
    if _check_init():
        _oled.poweroff()
        _DISPLAY_ON = False


def power_on():
    global _DISPLAY_ON
    if _check_init():
        _oled.poweron()
        _DISPLAY_ON = True
