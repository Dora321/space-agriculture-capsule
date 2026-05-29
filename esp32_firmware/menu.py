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

    def run_day_selection(self, current_day=0, plant_info=None):
        """天数选择：红/黄 ±1（持续按住加速），绿确认，蓝跳过保留原值。

        Args:
            current_day: 当前天数（默认值）
            plant_info: 可选，用于显示对应生长阶段名称

        Returns:
            int: 选择的天数（蓝键取消时返回 current_day）
        """
        import config as _cfg
        day = max(0, int(current_day))
        MAX_DAY = 365

        def _stage_for(d):
            if not plant_info:
                return None
            s = _cfg.get_growth_stage(plant_info, d)
            return s.get("stage") if s else None

        self._display.show_day_select(day, _stage_for(day))

        while True:
            delta = self._control.nav_held()

            if delta != 0:
                day = max(0, min(MAX_DAY, day + delta))
                self._display.show_day_select(day, _stage_for(day))

            # 绿键确认
            self._control.update()   # 排干 pending_event 以检测 OK/BACK
            if self._control.pressed():
                self._control.reset_press()
                return day

            # 蓝键跳过
            if self._control.back_pressed():
                self._control.reset_press()
                return current_day

            time.sleep_ms(50)

    def run_main_menu(self, state, get_wifi_status, get_ip):
        """主菜单：Plant / Set Day / Manual / System Info。蓝键直接退出。"""
        items = ["Plant Select", "Set Day", "Manual Ctrl", "System Info"]
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
                if idx == 0:   # Plant Select
                    new_plant = self.run_plant_selection(
                        default_index=self._plant_index(state.plant_type)
                    )
                    state.plant_type = new_plant
                    state.plant_info = None
                    self._display.show_complete_menu("Menu", items, idx)
                elif idx == 1:  # Set Day
                    plant_info = state.plant_info
                    new_day = self.run_day_selection(
                        current_day=state.days_since_planting,
                        plant_info=plant_info,
                    )
                    state.manual_day = new_day
                    state.days_since_planting = new_day
                    self._display.show_complete_menu("Menu", items, idx)
                elif idx == 2:  # Manual Ctrl
                    self._run_manual_control(state)
                    self._display.show_complete_menu("Menu", items, idx)
                elif idx == 3:  # System Info
                    self._run_system_info(get_wifi_status, get_ip)
                    self._display.show_complete_menu("Menu", items, idx)

            if self._control.back_pressed():
                self._control.reset_press()
                return

            time.sleep_ms(50)

    def _run_manual_control(self, state):
        """手动控制：Water Pump / Grow Light。绿确认立即执行，蓝返回。"""
        import actuators
        import config as _cfg

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
                    dur = _cfg.PUMP_WATER_DEFAULT_SEC
                    self._show_running("Water Pump", "WATER", dur)
                    actuators.run_water_pump(dur)
                elif idx == 1:
                    dur = getattr(_cfg, "MANUAL_LIGHT_SEC", 30)
                    self._show_running("Grow Light", "LIGHT", dur)
                    actuators.run_light(dur)
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

    def _show_running(self, title, action, duration_sec):
        """执行中画面：标题 + 动作 + 时长，在 actuator 阻塞期间保持显示。"""
        try:
            import display
            if not hasattr(display, "_check_init") or not display._check_init():
                return
            display._oled.fill(0)
            display._draw_inverted(">> {}".format(title))
            display._draw_centered(">{}< ".format(action), 22)
            display._draw_centered("{}s".format(duration_sec), 36)
            display._draw_centered("Running...", 50)
            display._oled.show()
        except Exception:
            pass

    # ── 工具 ─────────────────────────────────────────────────────

    def _plant_index(self, plant_name):
        try:
            return self._plant_list.index(plant_name)
        except ValueError:
            return 0
