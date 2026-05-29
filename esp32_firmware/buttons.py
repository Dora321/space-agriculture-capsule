"""Analog keyboard (ADC resistor ladder) for OLED menu control.

All four buttons share a single ADC pin (GPIO33 by default).
Each button connects a different resistor to GND, creating distinct voltage levels
that the ESP32 ADC can differentiate.

Circuit (standard 4-button analog keypad module):

    VCC (3.3V)
     |
    (internal resistor ladder inside keypad module)
     |
     +-------- ADC pin (GPIO33)
     |
    R_pulldown (internal)
     |
    GND

When idle: ADC ≈ 0 (pulled to GND).
When button pressed: ADC reads a specific voltage determined by the resistor divider.

API is compatible with the old ButtonPad class — menu.py needs no changes.
"""

import time
from machine import Pin, ADC


class AnalogKeypad:
    """Read a 4-button analog keypad on a single ADC pin.

    Thresholds are configurable; defaults work with common resistor values.
    Use the classmethod calibrate() to auto-detect thresholds for your hardware.
    """

    NONE = None
    UP = "up"        # Red    — previous item
    DOWN = "down"    # Yellow — next item
    OK = "ok"        # Green  — confirm
    BACK = "back"    # Blue   — back / menu trigger

    # Default ADC thresholds (12-bit, 0-4095, ATTN_11DB)
    # Calibrated from real hardware (ESP32 ADC GPIO33, 2026-05-28):
    #   Blue (BACK):  ~2030  (2019-2036)
    #   Green (OK):   ~2305  (2303-2308)
    #   Yellow (DOWN):~2840  (2638-2840)
    #   Red (UP):     ~3246  (3242-3253)
    # Each range has ≥135-unit safety margin on both sides.
    DEFAULT_THRESHOLDS = {
        BACK: (200, 2200),     # Blue   (实测 ~2030)
        OK:   (2201, 2600),    # Green  (实测 ~2305)
        DOWN: (2601, 3200),    # Yellow (实测 ~2638-2840-3166，上限扩到3200覆盖全范围)
        UP:   (3201, 3800),    # Red    (实测 ~3246，与DOWN间隔35个单位)
    }
    IDLE_THRESHOLD = 200    # Below this → no button pressed (pull-down to GND)
                            # Above 200 → button pressed (resistor divider to VCC)

    def __init__(self, adc_pin, thresholds=None):
        """Initialize the analog keypad.

        Args:
            adc_pin: GPIO pin number for ADC input (e.g. 33)
            thresholds: Optional dict of {button_name: (min_adc, max_adc)}.
                        Uses DEFAULT_THRESHOLDS if not provided.
        """
        self._adc = ADC(Pin(adc_pin))
        self._adc.atten(ADC.ATTN_11DB)
        self._adc.width(ADC.WIDTH_12BIT)

        self._thresholds = thresholds or self.DEFAULT_THRESHOLDS
        self._last_button = self.NONE
        self._press_start = 0
        self._last_event_ms = 0
        self._debounce_ms = 30
        self._pending_event = self.NONE
        self._value = 0
        # nav_held 专用：与 _event() 状态完全独立
        self._hold_button = self.NONE
        self._hold_start_ms = 0
        self._hold_last_ms = 0

        print(f"[AnalogKeypad] GPIO{adc_pin} ADC, idle < {self.IDLE_THRESHOLD}")

    # ── Internal helpers ────────────────────────────────────────

    def _read_adc(self):
        """Read ADC with averaging (8 samples) to reduce noise."""
        total = 0
        for _ in range(8):
            total += self._adc.read()
        return total // 8

    def _read_button(self):
        """Map current ADC value to a button name, or NONE when idle."""
        val = self._read_adc()
        if val < self.IDLE_THRESHOLD:
            return self.NONE
        for name, (lo, hi) in self._thresholds.items():
            if lo <= val <= hi:
                return name
        # ADC in a gap between thresholds — treat as no button
        return self.NONE

    def _event(self):
        """Return a button name on press-down edge (debounced), or NONE."""
        button = self._read_button()
        now = time.ticks_ms()

        if button is self.NONE:
            # Button released — clear state immediately for fast re-press
            self._last_button = self.NONE
            self._press_start = 0
            return self.NONE

        if self._last_button is self.NONE:
            # New press after release
            if time.ticks_diff(now, self._last_event_ms) > self._debounce_ms:
                self._last_button = button
                self._last_event_ms = now
                self._press_start = now
                return button
        elif button != self._last_button:
            # Different button pressed without release — treat as new press
            if time.ticks_diff(now, self._last_event_ms) > self._debounce_ms:
                self._last_button = button
                self._last_event_ms = now
                self._press_start = now
                return button
        return self.NONE

    # ── Public API (compatible with ButtonPad) ──────────────────

    def update(self):
        """Poll navigation events.

        Returns:
            -1 when UP is pressed, +1 when DOWN is pressed,
            0 when nothing happened (other button events are queued
            internally for pressed()).
        """
        event = self._event()
        if event == self.UP:
            return -1
        if event == self.DOWN:
            return 1
        if event is not self.NONE:
            self._pending_event = event
        return 0

    def pressed(self):
        """Return True exactly once when the OK (Green) button is pressed."""
        if self._pending_event == self.OK:
            self._pending_event = self.NONE
            return True
        return False

    def back_pressed(self):
        """Return True exactly once when the BACK (Blue) button is pressed."""
        if self._pending_event == self.BACK:
            self._pending_event = self.NONE
            return True
        return False

    def nav_held(self):
        """数字输入专用：首次按下立即响应，持续按住 600ms 后每 150ms 重复一次。
        返回 -1（UP/红）、+1（DOWN/黄）或 0（无事件）。与 _event() 状态完全独立。
        """
        button = self._read_button()
        now = time.ticks_ms()

        if button not in (self.UP, self.DOWN):
            self._hold_button = self.NONE
            self._hold_start_ms = 0
            return 0

        direction = -1 if button == self.UP else 1

        if self._hold_button != button:
            # 新按键：立即触发一次
            self._hold_button = button
            self._hold_start_ms = now
            self._hold_last_ms = now
            return direction

        # 同一键持续按住
        if time.ticks_diff(now, self._hold_start_ms) < 600:
            return 0
        if time.ticks_diff(now, self._hold_last_ms) >= 150:
            self._hold_last_ms = now
            return direction
        return 0

    def is_held(self):
        """Return True if *any* button is currently held down."""
        return self._read_button() is not self.NONE

    def long_pressed(self, ms=1000):
        """Return True when the BACK (Blue) button has been held for >= ms.

        Used for: triggering the main menu (1 s), returning from menus (1.5–2 s).
        """
        button = self._read_button()
        now = time.ticks_ms()
        if button != self.BACK:
            if button is self.NONE:
                self._press_start = 0
            return False
        if self._last_button != self.BACK:
            self._last_button = self.BACK
            self._press_start = now
            return False
        return bool(self._press_start) and time.ticks_diff(now, self._press_start) > ms

    def reset_press(self):
        """Wait until all buttons are released (max 3 s timeout)."""
        self._press_start = 0
        self._pending_event = self.NONE
        start = time.ticks_ms()
        while self._read_button() is not self.NONE:
            if time.ticks_diff(time.ticks_ms(), start) > 3000:
                break
            time.sleep_ms(20)
        self._last_button = self.NONE

    def value(self):
        """Current menu index value (set by menu navigation logic)."""
        return self._value

    def set_value(self, val):
        """Set the menu index value."""
        self._value = val

    def deinit(self):
        """Release the ADC pin. Currently a no-op on MicroPython."""
        pass

    # ── Calibration helper ──────────────────────────────────────

    @classmethod
    def calibrate(cls, adc_pin, timeout_sec=30):
        """Interactive calibration: press each button when prompted.

        Prints a threshold dict you can paste into config.py.
        Useful when you don't know the exact resistor values.

        Usage (REPL):
            from buttons import AnalogKeypad
            AnalogKeypad.calibrate(33)
        """
        adc = ADC(Pin(adc_pin))
        adc.atten(ADC.ATTN_11DB)
        adc.width(ADC.WIDTH_12BIT)

        labels = [
            (cls.UP, "UP / Red"),
            (cls.DOWN, "DOWN / Yellow"),
            (cls.OK, "OK / Green"),
            (cls.BACK, "BACK / Blue"),
        ]

        # Read idle (no button)
        print("\n=== Analog Keypad Calibration ===")
        print("Release ALL buttons...")
        time.sleep(2)
        idle_samples = [adc.read() for _ in range(20)]
        idle_avg = sum(idle_samples) // len(idle_samples)
        idle_lo = min(idle_samples)
        print(f"  Idle: avg={idle_avg}, min={idle_lo}")

        # Sample each button
        results = {}
        for name, label in labels:
            print(f"\nHold '{label}' button...")
            time.sleep(0.8)
            vals = []
            t0 = time.ticks_ms()
            while time.ticks_diff(time.ticks_ms(), t0) < 3000:
                vals.append(adc.read())
                time.sleep_ms(50)
            if not vals:
                print(f"  WARNING: no readings — is the button connected?")
                continue
            avg = sum(vals) // len(vals)
            mn, mx = min(vals), max(vals)
            print(f"  {name}: avg={avg},  range [{mn}, {mx}]")
            results[name] = (avg, mn, mx)

        if len(results) < 4:
            print("\nERROR: not all buttons detected. Check wiring.")
            return

        # Generate thresholds with safety margins
        sorted_items = sorted(results.items(), key=lambda x: x[1][0])
        print("\n\n# --- Paste into config.py ---")
        print(f"ANALOG_KEYPAD_PIN = {adc_pin}")
        print("ANALOG_KEYPAD_THRESHOLDS = {")
        prev_hi = -1
        for i, (name, (avg, mn, mx)) in enumerate(sorted_items):
            margin = max(120, (mx - mn) * 2)
            lo = max(prev_hi + 1, mn - margin)
            if i == len(sorted_items) - 1:
                hi = min(idle_lo - 50, mx + margin * 2)
            else:
                hi = mx + margin
            print(f'    "{name}": ({lo}, {hi}),')
            prev_hi = hi
        print("}")
        print(f"# IDLE threshold: {max(prev_hi + 1, idle_lo - 50)}")
        print("# --- End paste ---\n")
