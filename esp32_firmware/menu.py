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
        MIN_DAY = 1   # 种植第 1 天起算（不从 0 开始）
        day = max(MIN_DAY, int(current_day))
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
                day = max(MIN_DAY, min(MAX_DAY, day + delta))
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
        """主菜单：Plant / Set Day / Manual / LED Demo / Demo Speed。蓝键直接退出。"""
        items = ["Plant Select", "Set Day", "Manual Ctrl", "LED Demo", "Demo Speed"]
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
                    # 立即按新天数重算阶段，避免退出菜单首屏沿用旧阶段（否则会闪"苗期100%"再更新）
                    if plant_info:
                        import config as _cfg
                        state.growth_stage = _cfg.get_growth_stage(plant_info, new_day)
                    self._display.show_complete_menu("Menu", items, idx)
                elif idx == 2:  # Manual Ctrl
                    self._run_manual_control(state)
                    self._display.show_complete_menu("Menu", items, idx)
                elif idx == 3:  # LED Demo —— 现场一键播放灯效秀
                    self._run_led_demo()
                    self._display.show_complete_menu("Menu", items, idx)
                elif idx == 4:  # Demo Speed —— 切换展示模式（快速响应真实传感器）
                    state.fast_mode = not state.fast_mode
                    self._show_demo_speed(state.fast_mode)
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
                import status_strip
                if idx == 0:
                    # 水泵：开继电器 → 期间播金黄流水灯效 → 关继电器
                    dur = min(_cfg.PUMP_WATER_DEFAULT_SEC,
                              getattr(_cfg, "PUMP_MAX_RUN_SEC", 20))
                    self._show_running("Water Pump", "WATER", dur)
                    actuators.water_pump_on()
                    try:
                        status_strip.play_for(status_strip.SIGNAL_WATER, dur)
                    finally:
                        actuators.water_pump_off()
                elif idx == 1:
                    # 补光：开继电器 → 期间播紫色脉冲灯效 → 关继电器
                    dur = min(getattr(_cfg, "MANUAL_LIGHT_SEC", 30),
                              getattr(_cfg, "LIGHT_MAX_RUN_SEC", 20))
                    self._show_running("Grow Light", "LIGHT", dur)
                    actuators.light_on()
                    try:
                        status_strip.play_for(status_strip.SIGNAL_LIGHT_LOW, dur)
                    finally:
                        actuators.light_off()
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

    def _run_led_demo(self):
        """现场一键灯效演示：播放 status_strip.demo_show()，OLED 同步显示当前灯效字幕。

        灯条未启用/无硬件时静默返回（demo_show 内部判 _np）。
        """
        def _subtitle(name):
            """每段灯效开始时在 OLED 显示其名字（字幕）。"""
            try:
                import display
                if not hasattr(display, "_check_init") or not display._check_init():
                    return
                display._oled.fill(0)
                display._draw_inverted(">> LED Demo")
                display._draw_centered(str(name), 26)
                display._draw_centered("playing...", 50)
                display._oled.show()
            except Exception:
                pass

        self._show_running("LED Demo", "START", 20)
        try:
            import status_strip
            status_strip.demo_show(on_signal=_subtitle)
        except Exception as e:
            print("[Menu] LED demo error:", e)

    def _show_demo_speed(self, on):
        """展示模式切换提示：FAST ON（约3秒响应）/ OFF（正常间隔）。"""
        print("[Menu] Demo Speed:", "ON" if on else "OFF")
        try:
            import display
            if hasattr(display, "_check_init") and display._check_init():
                display._oled.fill(0)
                display._draw_inverted(">> Demo Speed")
                display._draw_centered("FAST: ON" if on else "FAST: OFF", 24)
                display._draw_centered("~3s response" if on else "normal interval", 44)
                display._oled.show()
        except Exception:
            pass
        time.sleep_ms(1100)

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
