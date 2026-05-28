"""HS-KEY4A-P analog 4-button input adapter.

The module outputs one ADC voltage for each button. This adapter exposes the
small interface used by menu.py: update() for previous/next, pressed() for
confirm, and long_pressed() for menu/back.
"""

import time
from machine import ADC, Pin


class Key4Buttons:
    """Read HS-KEY4A-P four analog buttons from one ADC pin."""

    NONE = None
    RED = "red"
    YELLOW = "yellow"
    GREEN = "green"
    BLUE = "blue"

    def __init__(self, adc_pin, samples=8):
        self._adc = ADC(Pin(adc_pin))
        try:
            self._adc.atten(ADC.ATTN_11DB)
        except Exception:
            pass
        try:
            self._adc.width(ADC.WIDTH_12BIT)
        except Exception:
            pass

        self._samples = samples
        self._value = 0
        self._last_button = self.NONE
        self._press_start = 0
        self._last_event_ms = 0
        self._debounce_ms = 180
        self._pending_event = self.NONE

        print(f"[Key4] Initialized ADC GPIO{adc_pin}")

    def _read_adc(self):
        total = 0
        for _ in range(self._samples):
            total += self._adc.read()
            time.sleep_ms(2)
        self._value = total // self._samples
        return self._value

    def _button_from_value(self, value):
        if value < 1400:
            return self.NONE
        if 1700 <= value <= 2150:
            return self.BLUE
        if 2151 <= value <= 2450:
            return self.GREEN
        if 2451 <= value <= 2850:
            return self.YELLOW
        if 2851 <= value <= 3600:
            return self.RED
        return self.NONE

    def _read_button(self):
        return self._button_from_value(self._read_adc())

    def _edge(self):
        button = self._read_button()
        now = time.ticks_ms()

        event = self.NONE
        if button != self._last_button:
            if time.ticks_diff(now, self._last_event_ms) > self._debounce_ms:
                if self._last_button is self.NONE and button is not self.NONE:
                    event = button
                    self._press_start = now
                elif button is self.NONE:
                    self._press_start = 0
                self._last_button = button
                self._last_event_ms = now
        return event

    def update(self):
        """Return -1 for previous, +1 for next, or 0 when no nav event."""
        event = self._edge()
        if event == self.RED:
            return -1
        if event == self.YELLOW:
            return 1
        if event is not self.NONE:
            self._pending_event = event
        return 0

    def pressed(self):
        """Return True when the confirm button is newly pressed."""
        if self._pending_event == self.GREEN:
            self._pending_event = self.NONE
            return True
        return self._edge() == self.GREEN

    def is_held(self):
        return self._read_button() is not self.NONE

    def long_pressed(self, ms=1000):
        """Return True when the blue/menu button has been held long enough."""
        button = self._read_button()
        now = time.ticks_ms()
        if button != self.BLUE:
            if button is self.NONE:
                self._press_start = 0
            return False
        if self._last_button != self.BLUE:
            self._last_button = self.BLUE
            self._press_start = now
            return False
        return self._press_start and time.ticks_diff(now, self._press_start) > ms

    def reset_press(self):
        self._press_start = 0
        self._pending_event = self.NONE
        start = time.ticks_ms()
        while self._read_button() is not self.NONE:
            if time.ticks_diff(time.ticks_ms(), start) > 3000:
                break
            time.sleep_ms(20)
        self._last_button = self.NONE

    def value(self):
        return self._value

    def set_value(self, val):
        self._value = val

    def deinit(self):
        pass
