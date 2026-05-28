"""
OLED 按键菜单系统

基于 HS-KEY4A-P 四位模拟按键 + SH1106 OLED 显示屏。
- 红/黄：导航，绿：确认，蓝：长按返回/菜单
- OLED 128x64：5 项可见 + 标题 + 底部提示
"""

import time
import gc

try:
    import config
except ImportError:
    config = None


class Menu:
    """OLED 菜单导航系统。

    依赖：
    - display 模块：提供 show_menu / show_plant_select / show_system_info
    - 输入控制器实例：提供 value / pressed / long_pressed / update
    """

    def __init__(self, display_mod, control, plant_list):
        """初始化菜单系统。

        Args:
            display_mod: display 模块（已初始化的 OLED）
            control: 菜单输入控制器实例
            plant_list: 植物名称列表（中文）
        """
        self._display = display_mod
        self._control = control
        self._plant_list = plant_list

    def run_plant_selection(self, default_index=0):
        """阻塞式植物选择菜单。

        红/黄切换植物，绿键确认，返回选中的植物名称。

        Args:
            default_index: 默认选中的植物索引（0-7）

        Returns:
            str: 选中的植物名称
        """
        plant_count = len(self._plant_list)
        self._control.set_value(default_index)
        idx = default_index

        self._display.show_plant_select(self._plant_list, idx)

        while True:
            direction = self._control.update()

            if direction != 0:
                idx += direction
                # 循环边界
                if idx < 0:
                    idx = plant_count - 1
                elif idx >= plant_count:
                    idx = 0
                self._control.set_value(idx)
                self._display.show_plant_select(self._plant_list, idx)

            if self._control.pressed():
                self._control.reset_press()
                plant_name = self._plant_list[idx]
                return plant_name

            if self._control.long_pressed(2000):
                self._control.reset_press()
                return self._plant_list[default_index]

            time.sleep_ms(50)

    def run_main_menu(self, state, get_wifi_status, get_ip):
        """阻塞式主菜单（植物选择 / 手动控制 / 系统信息 / 返回）。

        Args:
            state: SystemState 实例（用于读写 plant_type）
            get_wifi_status: callable → bool，获取 WiFi 连接状态
            get_ip: callable → str，获取 IP 地址
        """
        items = ["Plant Select", "Manual Ctrl", "System Info", "Back"]
        idx = 0
        self._control.set_value(0)

        self._display.show_complete_menu("Menu", items, idx)

        while True:
            direction = self._control.update()

            if direction != 0:
                idx += direction
                if idx < 0:
                    idx = len(items) - 1
                elif idx >= len(items):
                    idx = 0
                self._control.set_value(idx)
                self._display.show_complete_menu("Menu", items, idx)

            if self._control.pressed():
                self._control.reset_press()

                if idx == 0:       # Plant Select
                    new_plant = self.run_plant_selection(
                        default_index=self._plant_index(state.plant_type)
                    )
                    state.plant_type = new_plant
                    # 返回主菜单
                    self._display.show_complete_menu("Menu", items, idx)

                elif idx == 1:     # Manual Ctrl
                    self._run_manual_control(state)
                    self._display.show_complete_menu("Menu", items, idx)

                elif idx == 2:     # System Info
                    self._run_system_info(get_wifi_status, get_ip)
                    self._display.show_complete_menu("Menu", items, idx)

                elif idx == 3:     # Back
                    return

            if self._control.long_pressed(1500):
                self._control.reset_press()
                return

            time.sleep_ms(50)

    def _run_manual_control(self, state):
        """手动控制子菜单（水泵 / 补光灯 / 返回）。

        Args:
            state: SystemState 实例
        """
        items = ["Water Pump", "Grow Light", "Back"]
        idx = 0
        self._control.set_value(0)

        self._display.show_complete_menu("Manual Ctrl", items, idx)

        while True:
            direction = self._control.update()

            if direction != 0:
                idx += direction
                if idx < 0:
                    idx = len(items) - 1
                elif idx >= len(items):
                    idx = 0
                self._control.set_value(idx)
                self._display.show_complete_menu("Manual Ctrl", items, idx)

            if self._control.pressed():
                self._control.reset_press()

                if idx == 0:       # Water Pump
                    self._show_action_confirm("Water Pump", "WATER")
                    # 触发浇水动作 → 通过设置 state 的标记让主循环执行
                    state._manual_action = "water"
                    break  # 执行后返回上级菜单

                elif idx == 1:     # Grow Light
                    self._show_action_confirm("Grow Light", "LIGHT")
                    state._manual_action = "light"
                    break

                elif idx == 2:     # Back
                    break

            if self._control.long_pressed(1500):
                self._control.reset_press()
                break

            time.sleep_ms(50)

    def _show_action_confirm(self, title, action):
        """显示手动动作确认画面。"""
        import display
        if not hasattr(display, '_check_init') or not display._check_init():
            return
        display._oled.fill(0)
        display._draw_centered(title, 8)
        display._draw_centered("Executing...", 28)
        display._draw_centered(f">{action}<", 44)
        display._oled.show()
        time.sleep(1.5)

    def _run_system_info(self, get_wifi_status, get_ip):
        """显示系统信息界面（长按返回）。"""
        try:
            import gc as gc_mod
            gc_mod.collect()
            mem_kb = int(gc_mod.mem_free() / 1024)
        except Exception:
            mem_kb = 0

        wifi = get_wifi_status() if callable(get_wifi_status) else False
        ip = get_ip() if callable(get_ip) else "-"

        self._display.show_system_info(wifi, ip, mem_kb)

        # 等待长按返回
        while True:
            if self._control.long_pressed(1500):
                self._control.reset_press()
                return
            time.sleep_ms(100)

    def _plant_index(self, plant_name):
        """根据植物中文名查找索引，找不到返回 0。"""
        try:
            return self._plant_list.index(plant_name)
        except ValueError:
            return 0

    def check_menu_trigger(self):
        """在主循环中调用，检测是否触发了长按菜单。

        Returns:
            bool: True 表示触发了菜单（调用方应暂停主循环并调用 run_main_menu）
        """
        if self._control.long_pressed(1000):
            self._control.reset_press()
            return True
        return False
