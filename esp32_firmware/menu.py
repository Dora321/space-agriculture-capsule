"""
OLED 按钮菜单系统

按键约定（全局统一，无长按）：
  红(UP)   / 黄(DOWN) → 上下导航
  绿(OK)              → 确认 / 进入
  蓝(BACK)            → 返回上一层 / 退出菜单
"""

import time
import gc

try:
    import config
except ImportError:
    config = None


class Menu:
    """OLED 菜单导航系统。"""

    def __init__(self, display_mod, control, plant_list):
        self._display = display_mod
        self._control = control
        self._plant_list = plant_list

    # ── 主循环触发 ───────────────────────────────────────────────

    def check_menu_trigger(self):
        """主循环中检测蓝键单击 → 进入菜单。
        注意：调用方需在此之前已调用 _control.update() 处理上下导航。
        """
        return self._control.back_pressed()

    # ── 菜单页面 ─────────────────────────────────────────────────

    def run_plant_selection(self, default_index=0):
        """植物选择菜单：红/黄切换，绿确认，蓝取消并保留原选项。"""
        plant_count = len(self._plant_list)
        idx = default_index
        self._control.set_value(idx)
        self._display.show_plant_select(self._plant_list, idx)

        while True:
            direction = self._control.update()

            if direction != 0:
                idx = (idx + direction) % plant_count
                self._control.set_value(idx)
                self._display.show_plant_select(self._plant_list, idx)

            if self._control.pressed():
                self._control.reset_press()
                return self._plant_list[idx]

            if self._control.back_pressed():
                self._control.reset_press()
                return self._plant_list[default_index]

            time.sleep_ms(50)

    def run_main_menu(self, state, get_wifi_status, get_ip):
        """主菜单：Plant / Manual / System Info。蓝键直接退出。"""
        items = ["Plant Select", "Manual Ctrl", "System Info"]
        idx = 0
        self._control.set_value(0)
        self._display.show_complete_menu("Menu", items, idx)

        while True:
            direction = self._control.update()

            if direction != 0:
                idx = (idx + direction) % len(items)
                self._control.set_value(idx)
                self._display.show_complete_menu("Menu", items, idx)

            if self._control.pressed():
                self._control.reset_press()
                if idx == 0:
                    new_plant = self.run_plant_selection(
                        default_index=self._plant_index(state.plant_type)
                    )
                    state.plant_type = new_plant
                    state.plant_info = None
                    self._display.show_complete_menu("Menu", items, idx)
                elif idx == 1:
                    self._run_manual_control(state)
                    self._display.show_complete_menu("Menu", items, idx)
                elif idx == 2:
                    self._run_system_info(get_wifi_status, get_ip)
                    self._display.show_complete_menu("Menu", items, idx)

            if self._control.back_pressed():
                self._control.reset_press()
                return

            time.sleep_ms(50)

    def _run_manual_control(self, state):
        """手动控制：Water Pump / Grow Light。绿确认执行，蓝返回。"""
        items = ["Water Pump", "Grow Light"]
        idx = 0
        self._control.set_value(0)
        self._display.show_complete_menu("Manual Ctrl", items, idx)

        while True:
            direction = self._control.update()

            if direction != 0:
                idx = (idx + direction) % len(items)
                self._control.set_value(idx)
                self._display.show_complete_menu("Manual Ctrl", items, idx)

            if self._control.pressed():
                self._control.reset_press()
                if idx == 0:
                    self._show_action_confirm("Water Pump", "WATER")
                    state._manual_action = "water"
                elif idx == 1:
                    self._show_action_confirm("Grow Light", "LIGHT")
                    state._manual_action = "light"
                return

            if self._control.back_pressed():
                self._control.reset_press()
                return

            time.sleep_ms(50)

    def _run_system_info(self, get_wifi_status, get_ip):
        """系统信息界面。任意键返回（优先蓝键）。"""
        try:
            gc.collect()
            mem_kb = int(gc.mem_free() / 1024)
        except Exception:
            mem_kb = 0

        wifi = get_wifi_status() if callable(get_wifi_status) else False
        ip = get_ip() if callable(get_ip) else "-"
        self._display.show_system_info(wifi, ip, mem_kb)

        while True:
            self._control.update()
            if self._control.back_pressed() or self._control.pressed():
                self._control.reset_press()
                return
            time.sleep_ms(100)

    def _show_action_confirm(self, title, action):
        """执行确认画面（1.5s 后自动消失）。"""
        try:
            import display
            if not hasattr(display, "_check_init") or not display._check_init():
                return
            display._oled.fill(0)
            display._draw_centered(title, 8)
            display._draw_centered("Executing...", 28)
            display._draw_centered(">{}< ".format(action), 44)
            display._oled.show()
            time.sleep_ms(1500)
        except Exception:
            pass

    # ── 工具 ─────────────────────────────────────────────────────

    def _plant_index(self, plant_name):
        try:
            return self._plant_list.index(plant_name)
        except ValueError:
            return 0
