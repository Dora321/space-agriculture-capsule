from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deliverables" / "kt-board-preview-120x60.png"
DASH = ROOT / "deliverables" / "contest-demo-dashboard-preview.png"
OLED = ROOT / "deliverables" / "oled-screenshots" / "oled-3-page-contact-sheet-clear.png"
FONT = "C:/Windows/Fonts/simhei.ttf"

W, H = 2400, 1200
img = Image.new("RGB", (W, H), "#f4fbf7")
d = ImageDraw.Draw(img)


def font(size):
    return ImageFont.truetype(FONT, size)


F = {
    "h1": font(74),
    "h2": font(34),
    "h3": font(25),
    "body": font(21),
    "small": font(18),
    "tiny": font(16),
    "num": font(48),
    "tag": font(19),
}


def rr(xy, r, fill, outline=None, width=1):
    d.rounded_rectangle(xy, radius=r, fill=fill, outline=outline, width=width)


def text(x, y, s, f, fill, anchor=None, spacing=6):
    d.text((x, y), s, font=f, fill=fill, anchor=anchor, spacing=spacing)


def wrap_text(s, f, max_w):
    lines = []
    cur = ""
    for ch in s:
        test = cur + ch
        if d.textbbox((0, 0), test, font=f)[2] <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def paragraph(x, y, s, f, fill, max_w, line_h):
    for line in wrap_text(s, f, max_w):
        text(x, y, line, f, fill)
        y += line_h
    return y


# Background.
for i in range(760):
    t = i / 760
    r = int(7 + (16 - 7) * t)
    g = int(17 + (32 - 17) * t)
    b = int(15 + (28 - 15) * t)
    d.line((i, 0, i, H), fill=(r, g, b))
for x, y, rad, col in [
    (160, 95, 90, "#183f36"),
    (520, 210, 130, "#12302a"),
    (2100, 85, 130, "#dff5ec"),
]:
    d.ellipse((x - rad, y - rad, x + rad, y + rad), fill=col)

# Left hero.
x0, y0 = 48, 54
text(x0, y0, "未来在轨育种验证平台的地面雏形", F["h3"], "#9fe7c3")
text(x0, y0 + 58, "太空农业", F["h1"], "#edf7f3")
text(x0, y0 + 138, "智能种植舱", F["h1"], "#edf7f3")
text(x0, y0 + 232, "Space Agriculture Smart Planting Cabin", F["body"], "#a8c3ba")
d.line((x0, y0 + 296, x0, y0 + 390), fill="#55d98d", width=7)
paragraph(
    x0 + 20,
    y0 + 292,
    "ESP32 舱内飞控 + 树莓派载荷计算机 + DeepSeek 云端决策",
    F["h3"],
    "#f2fff8",
    560,
    34,
)

rr((48, 478, 682, 665), 22, "#12231f", "#35584e", 2)
paragraph(
    74,
    502,
    "2035 年，我是一名太空育种站的作物育种师。过去，太空育种要把种子送上天，再带回地面种 5 到 8 代筛选。如果种植、观察和验证本身就发生在太空舱里，育种反馈会更快。这个项目，就是未来“在轨育种验证平台”的地面原型。",
    F["small"],
    "#d9f1e8",
    582,
    28,
)

metrics = [("8", "种作物参数库"), ("4", "类环境感知"), ("2", "类物理执行"), ("133", "自动化测试 PASS")]
mx, my = 48, 700
for i, (n, lab) in enumerate(metrics):
    cx = mx + (i % 2) * 318
    cy = my + (i // 2) * 132
    rr((cx, cy, cx + 292, cy + 102), 20, "#0b1714", "#2d6254", 2)
    text(cx + 22, cy + 22, n, F["num"], "#55d98d")
    text(cx + 112, cy + 42, lab, F["small"], "#cfe4dd")

tags = ["两层自治", "自动浇水补光", "实时遥测", "安全降级", "约 ¥140 / 套"]
tx, ty = 48, 1000
for tag in tags:
    tw = d.textbbox((0, 0), tag, font=F["tag"])[2] + 34
    rr((tx, ty, tx + tw, ty + 44), 22, "#173b31", "#55d98d", 2)
    text(tx + 17, ty + 12, tag, F["tag"], "#dff9ee")
    tx += tw + 12
    if tx > 650:
        tx = 48
        ty += 56

# Center architecture.
cx0 = 800
rr((cx0, 54, 1810, 380), 24, "#ffffff", "#bdd7ca", 2)
text(cx0 + 26, 80, "系统架构", F["h2"], "#07110f")
text(cx0 + 205, 88, "ESP32 负责活下去，树莓派负责更聪明", F["small"], "#637a72")
modules = [
    ("感知 SENSE", ["土壤湿度 ADC", "环境光照 ADC", "DHT 温湿度", "旋转编码器"], "#e9e7ff", "#7f77dd", "#302a78"),
    ("决策 THINK", ["本地规则常驻", "采纳 Pi advice", "先过安全护栏", "断联自动兜底"], "#ffeaf2", "#d4537e", "#72243e"),
    ("执行 ACT", ["12V 水泵", "12V COB 补光", "WS2812 信号灯", "OLED 三页显示"], "#eaf6df", "#639922", "#27500a"),
    ("安全 SAFE", ["动作时长上限", "每小时限频", "高低温保护", "传感器降级"], "#fff2dc", "#f2bf5b", "#654108"),
]
for i, (title, items, fill, border, col) in enumerate(modules):
    x = cx0 + 24 + i * 176
    y = 128
    rr((x, y, x + 158, y + 176), 18, fill, border, 3)
    text(x + 15, y + 15, title, F["small"], col)
    yy = y + 54
    for it in items:
        text(x + 15, yy, it, F["tiny"], col)
        yy += 28
text(cx0 + 742, 185, "UART\nreport / advice", F["small"], "#55746a", spacing=4)
text(cx0 + 783, 225, "↔", font(46), "#58c7e8")
rr((cx0 + 826, 128, cx0 + 985, 304), 18, "#e8f8ff", "#58c7e8", 3)
text(cx0 + 844, 146, "树莓派", F["small"], "#07384b")
for j, it in enumerate(["接收 report", "调 DeepSeek", "转发 Web 大屏", "失败则本地兜底"]):
    text(cx0 + 844, 188 + j * 26, it, F["tiny"], "#07384b")
rr((cx0 + 24, 322, cx0 + 985, 360), 18, "#07110f")
text(cx0 + 278, 331, "两层降级链：DeepSeek 精细判断  →  ESP32 本地规则保命", F["small"], "#edf7f3")

# Features.
rr((cx0, 410, 1810, 760), 24, "#ffffff", "#bdd7ca", 2)
text(cx0 + 26, 436, "五大核心亮点", F["h2"], "#07110f")
features = [
    ("1", "深空自治架构", "断网时不是停机，而是自动切回 ESP32 本地规则。"),
    ("2", "决策/执行分离", "诊断信号全部广播，执行器只响应有硬件支撑的动作。"),
    ("3", "8 种作物库", "叶菜 4 + 果菜 4，切换后策略自动适配。"),
    ("4", "生长数据闭环", "记录环境、阶段、动作和 AI 育种观察。"),
    ("5", "地面站遥测", "大屏展示 LIVE 状态、仪表、动作链路和原因。"),
]
for i, (n, tit, desc) in enumerate(features):
    x = cx0 + 24 + i * 192
    y = 494
    rr((x, y, x + 174, y + 228), 18, "#f6fbf8", "#cfe5d9", 2)
    d.ellipse((x + 15, y + 15, x + 49, y + 49), fill="#07110f")
    text(x + 32, y + 22, n, F["tiny"], "#55d98d", anchor="ma")
    text(x + 15, y + 66, tit, F["small"], "#07110f")
    paragraph(x + 15, y + 102, desc, F["tiny"], "#36524a", 142, 25)

# Visual proof.
rr((cx0, 790, 1810, 1145), 24, "#ffffff", "#bdd7ca", 2)
text(cx0 + 26, 816, "现场可见证据", F["h2"], "#07110f")
text(cx0 + 248, 824, "实机、OLED 和 Web 大屏同步展示", F["small"], "#637a72")
if DASH.exists():
    dash = Image.open(DASH).convert("RGB")
    dash.thumbnail((540, 245))
    rr((cx0 + 26, 872, cx0 + 590, 1124), 18, "#0d1714", "#153b31", 2)
    img.paste(dash, (cx0 + 38, 884))
if OLED.exists():
    oled = Image.open(OLED).convert("RGB")
    oled.thumbnail((320, 245))
    rr((cx0 + 620, 872, cx0 + 982, 1124), 18, "#0d1714", "#153b31", 2)
    img.paste(oled, (cx0 + 642, 884))

# Right panels.
rx = 1840
rr((rx, 54, 2352, 460), 24, "#ffffff", "#bdd7ca", 2)
text(rx + 24, 80, "8 种作物参数库", F["h2"], "#07110f")
crops = [
    ("生菜", "控水促根，氮肥促叶"),
    ("小白菜", "保持湿润，快速采收"),
    ("菠菜", "忌积水，稳湿度"),
    ("韭菜", "割后追氮，持续再生"),
    ("番茄", "花期控水，果期补钾"),
    ("辣椒", "控水促花，防高温"),
    ("黄瓜", "果期水分连续"),
    ("茄子", "门茄坐住后追肥"),
]
for i, (c, desc) in enumerate(crops):
    x = rx + 24 + (i % 2) * 236
    y = 132 + (i // 2) * 74
    rr((x, y, x + 216, y + 56), 12, "#f6fbf8", "#cfe5d9", 2)
    text(x + 14, y + 10, c, F["small"], "#07110f")
    text(x + 84, y + 14, desc, F["tiny"], "#46635b")

rr((rx, 490, 2352, 820), 24, "#ffffff", "#bdd7ca", 2)
text(rx + 24, 516, "可验证数据", F["h2"], "#07110f")
datas = [
    ("60s", "默认采样周期"),
    ("12", "每小时最多动作"),
    ("20s", "单次执行上限"),
    ("¥140", "单套硬件成本"),
    ("WATER", "水泵物理动作"),
    ("LIGHT", "补光物理动作"),
]
for i, (a, b) in enumerate(datas):
    x = rx + 24 + (i % 2) * 236
    y = 570 + (i // 2) * 70
    rr((x, y, x + 216, y + 52), 12, "#07110f")
    text(x + 14, y + 10, a, F["h3"], "#58c7e8")
    text(x + 96, y + 17, b, F["tiny"], "#edf7f3")

rr((rx, 850, 2352, 1145), 24, "#07110f", "#55d98d", 2)
text(rx + 24, 876, "2035 太空育种站团队", F["h2"], "#edf7f3")
roles = [("张煦涵", "太空育种站长"), ("陈美伊", "农业育种专家"), ("杨灏辰", "总工程师")]
y = 936
for name, role in roles:
    text(rx + 26, y, name, F["h3"], "#55d98d")
    text(rx + 140, y + 4, role, F["small"], "#d9f1e8")
    y += 52
paragraph(
    rx + 26,
    1092,
    "ESP32 MicroPython / Raspberry Pi UART / DeepSeek / Web 地面站 / 在轨育种验证",
    F["tiny"],
    "#a8c3ba",
    455,
    23,
)

img.save(OUT, quality=95)
print(OUT)
