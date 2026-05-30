"""Runtime state container for the ESP32 controller."""


class SystemState:
    """Mutable in-memory state shared by the controller loop.

    The project runs on MicroPython, so this deliberately stays as a small
    plain class instead of a dataclass.
    """

    def __init__(self):
        self.wifi_connected = False
        self.pi_online = False
        self.soil_moisture = 0
        self.light_level = 0
        self.temperature = 0.0
        self.humidity = 0.0
        self.plant_type = "生菜"
        self.plant_info = None
        self.days_since_planting = 0
        self.growth_stage = None
        self.sun_minutes_today = 0
        self.sun_date = ""
        self.last_action = "idle"
        self.last_action_duration = 0
        self.last_action_time = 0
        self.last_decision_reason = "status normal"
        self.last_decision_source = "local"
        self.last_signals = []
        self.last_breeding_observation = ""
        self.last_ai_request_time = 0
        self.last_ai_snapshot = None
        self.pending_pi_decision = None
        self.action_count = 0
        self.action_count_start = 0
        self.read_count = 0
        self.error_count = 0
        self.start_time = 0
        self.demo_soil_moisture = None
        self.manual_day = None      # 手动设置的种植天数；None 则按 config.PLANTING_DATE 计算
