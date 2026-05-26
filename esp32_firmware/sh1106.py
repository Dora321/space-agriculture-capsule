# SH1106 OLED Driver for MicroPython
# Supports I2C and SPI interfaces
# Compatible with ESP32, ESP8266, Raspberry Pi Pico

import framebuf
import time

# SH1106 Commands
SET_CONTRAST        = 0x81
SET_NORM_INV        = 0xA6
SET_DISP            = 0xAE
SET_MEM_ADDR        = 0x20
SET_COL_ADDR        = 0x21
SET_PAGE_ADDR       = 0x22
SET_DISP_START_LINE = 0x40
SET_SEG_REMAP       = 0xA0
SET_MUX_RATIO       = 0xA8
SET_COM_OUT_DIR     = 0xC0
SET_DISP_OFFSET     = 0xD3
SET_COM_PIN_CFG     = 0xDA
SET_DISP_CLK_DIV    = 0xD5
SET_PRECHARGE       = 0xD9
SET_VCOM_DESEL      = 0xDB
SET_CHARGE_PUMP     = 0x8D


class SH1106:
    """Base class for SH1106 OLED driver."""

    def __init__(self, width, height, external_vcc=False):
        self.width = width
        self.height = height
        self.external_vcc = external_vcc
        self.pages = height // 8
        self.buffer = bytearray(self.pages * self.width)
        self.framebuf = framebuf.FrameBuffer(
            self.buffer, self.width, self.height, framebuf.MONO_VLSB
        )
        self.init_display()

    def init_display(self):
        """Initialize the display with default settings."""
        cmds = [
            SET_DISP,                       # Display off
            SET_MEM_ADDR, 0x00,             # Horizontal addressing mode
            SET_DISP_START_LINE | 0x00,     # Start line 0
            SET_SEG_REMAP | 0x01,           # Segment remap (mirror horizontally)
            SET_MUX_RATIO, self.height - 1, # Multiplex ratio
            SET_COM_OUT_DIR | 0x08,         # COM scan direction (flip vertically)
            SET_DISP_OFFSET, 0x00,          # Display offset
            SET_COM_PIN_CFG,
            0x12 if self.height > 32 else 0x02,
            SET_DISP_CLK_DIV, 0x80,         # Clock divider
            SET_PRECHARGE,
            0x22 if self.external_vcc else 0xF1,
            SET_VCOM_DESEL, 0x30,           # VCOM deselect
            SET_CONTRAST, 0xFF,             # Max contrast
            SET_CHARGE_PUMP,
            0x10 if self.external_vcc else 0x14,
            SET_NORM_INV,                   # Normal (non-inverted) display
            SET_DISP | 0x01,               # Display on
        ]
        for cmd in cmds:
            self.write_cmd(cmd)
        self.fill(0)
        self.show()

    def poweroff(self):
        self.write_cmd(SET_DISP)

    def poweron(self):
        self.write_cmd(SET_DISP | 0x01)

    def contrast(self, contrast):
        """Set display contrast (0–255)."""
        self.write_cmd(SET_CONTRAST)
        self.write_cmd(contrast)

    def invert(self, invert):
        """Invert display colors."""
        self.write_cmd(SET_NORM_INV | (invert & 1))

    def rotate(self, rotate):
        """Rotate display 180 degrees."""
        self.write_cmd(SET_COM_OUT_DIR | ((rotate & 1) << 3))
        self.write_cmd(SET_SEG_REMAP | (rotate & 1))

    def show(self):
        """Push framebuffer to display."""
        for page in range(self.pages):
            # SH1106 requires page-by-page writes with column address reset
            self.write_cmd(0xB0 | page)          # Set page address
            self.write_cmd(0x02)                  # Set lower column (offset 2 for SH1106)
            self.write_cmd(0x10)                  # Set higher column
            self.write_data(
                self.buffer[page * self.width: (page + 1) * self.width]
            )

    # --- Framebuffer wrappers ---

    def fill(self, col):
        self.framebuf.fill(col)

    def pixel(self, x, y, col=1):
        self.framebuf.pixel(x, y, col)

    def hline(self, x, y, w, col=1):
        self.framebuf.hline(x, y, w, col)

    def vline(self, x, y, h, col=1):
        self.framebuf.vline(x, y, h, col)

    def line(self, x1, y1, x2, y2, col=1):
        self.framebuf.line(x1, y1, x2, y2, col)

    def rect(self, x, y, w, h, col=1):
        self.framebuf.rect(x, y, w, h, col)

    def fill_rect(self, x, y, w, h, col=1):
        self.framebuf.fill_rect(x, y, w, h, col)

    def text(self, string, x, y, col=1):
        self.framebuf.text(string, x, y, col)

    def scroll(self, dx, dy):
        self.framebuf.scroll(dx, dy)

    def blit(self, fbuf, x, y):
        self.framebuf.blit(fbuf, x, y)


class SH1106_I2C(SH1106):
    """SH1106 over I2C."""

    def __init__(self, width, height, i2c, addr=0x3C, external_vcc=False):
        self.i2c = i2c
        self.addr = addr
        self.temp = bytearray(2)
        super().__init__(width, height, external_vcc)

    def write_cmd(self, cmd):
        self.temp[0] = 0x00  # Co=0, D/C=0 => command
        self.temp[1] = cmd
        self.i2c.writeto(self.addr, self.temp)

    def write_data(self, buf):
        # Prefix with 0x40 (D/C=1 => data)
        data = bytearray(len(buf) + 1)
        data[0] = 0x40
        data[1:] = buf
        self.i2c.writeto(self.addr, data)


class SH1106_SPI(SH1106):
    """SH1106 over SPI."""

    def __init__(self, width, height, spi, dc, res, cs, external_vcc=False):
        self.spi = spi
        self.dc = dc    # Data/Command pin
        self.res = res  # Reset pin
        self.cs = cs    # Chip Select pin
        dc.init(dc.OUT, value=0)
        res.init(res.OUT, value=0)
        cs.init(cs.OUT, value=1)
        self.reset()
        super().__init__(width, height, external_vcc)

    def reset(self):
        self.res(1)
        time.sleep_ms(1)
        self.res(0)
        time.sleep_ms(10)
        self.res(1)
        time.sleep_ms(10)

    def write_cmd(self, cmd):
        self.cs(1)
        self.dc(0)
        self.cs(0)
        self.spi.write(bytearray([cmd]))
        self.cs(1)

    def write_data(self, buf):
        self.cs(1)
        self.dc(1)
        self.cs(0)
        self.spi.write(buf)
        self.cs(1)
