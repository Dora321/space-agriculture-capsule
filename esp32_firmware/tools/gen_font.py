"""
中文字库生成器 - 在 PC 上运行
从系统字体生成 16x16 点阵数据，供 ESP32 OLED 使用
用法: py -3 gen_font.py
"""

from PIL import Image, ImageDraw, ImageFont
import os

# OLED 上需要显示的所有中文字符
CHARS = "太空种植舱生菜小白菠韭番茄辣椒黄瓜子浇水营养换气待机土壤温湿度状态正常错误动作物"

FONT_SIZE = 14  # 14pt → 在 16x16 格子中有较好填充
CHAR_W = 16
CHAR_H = 16


def render_char(font, char):
    """将一个中文字符渲染为 16x16 位图，返回 32 字节 bytearray (MONO_HMSB)"""
    img = Image.new('1', (CHAR_W, CHAR_H), 0)
    draw = ImageDraw.Draw(img)

    # 计算居中偏移
    bbox = draw.textbbox((0, 0), char, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (CHAR_W - tw) // 2 - bbox[0]
    y = (CHAR_H - th) // 2 - bbox[1]

    draw.text((x, y), char, fill=1, font=font)

    # 转为 MONO_HMSB 字节序列 (MSB 在左)
    data = bytearray()
    for row in range(CHAR_H):
        for byte_idx in range(2):  # 每行 2 字节 = 16 位
            b = 0
            for bit in range(8):
                col = byte_idx * 8 + bit
                if img.getpixel((col, row)):
                    b |= (0x80 >> bit)
            data.append(b)
    return data


def main():
    # 查找中文字体
    font_path = None
    for p in ['C:/Windows/Fonts/simhei.ttf', 'C:/Windows/Fonts/msyh.ttc']:
        if os.path.exists(p):
            font_path = p
            break
    if not font_path:
        print("Error: 未找到中文字体")
        return

    print(f"使用字体: {font_path}")
    font = ImageFont.truetype(font_path, FONT_SIZE)

    # 去重
    chars = list(dict.fromkeys(CHARS))
    print(f"生成 {len(chars)} 个字符的点阵数据...")

    # 生成
    output = os.path.join(os.path.dirname(__file__), '..', 'font_cn.py')
    with open(output, 'w', encoding='utf-8') as f:
        f.write('"""\n')
        f.write('中文 16x16 点阵字库 (MONO_HMSB)\n')
        f.write('由 tools/gen_font.py 自动生成，请勿手动编辑\n')
        f.write('"""\n\n')
        f.write('CHAR_W = 16\n')
        f.write('CHAR_H = 16\n\n')
        f.write('FONT = {\n')

        for ch in chars:
            data = render_char(font, ch)
            hex_str = ','.join(f'0x{b:02x}' for b in data)
            f.write(f'    "{ch}": bytearray([{hex_str}]),\n')

        f.write('}\n')

    print(f"已生成: {output} ({len(chars)} 字符, {len(chars)*32} 字节)")


if __name__ == '__main__':
    main()
