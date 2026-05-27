"""
测试本地决策逻辑 - utils.local_fallback_decision
覆盖：优先级、阈值边界、各植物类型
"""
import config
from utils import local_fallback_decision


def _plant(name="生菜"):
    return config.get_plant_info(name)


class TestWaterDecision:
    """浇水决策测试"""

    def test_dry_soil_triggers_water(self):
        """土壤极度干燥 → 浇水（延长时间）"""
        info = _plant()
        d = local_fallback_decision(
            soil=info["soil_threshold"] - 20,
            plant_info=info,
            current_time=1000,
        )
        assert d["action"] == "water"
        assert d["duration_sec"] > info["water_sec"]  # 延长

    def test_below_threshold_triggers_water(self):
        """低于阈值 → 正常浇水"""
        info = _plant()
        d = local_fallback_decision(
            soil=info["soil_threshold"] - 5,
            plant_info=info,
            current_time=1000,
        )
        assert d["action"] == "water"
        assert d["duration_sec"] == info["water_sec"]

    def test_above_threshold_no_water(self):
        """高于阈值 → 不浇水"""
        info = _plant()
        d = local_fallback_decision(
            soil=info["soil_threshold"] + 20,
            plant_info=info,
            current_time=1000,
        )
        assert d["action"] != "water"


class TestIdleDecision:
    """待机决策测试"""

    def test_all_normal_idle(self):
        """一切正常 → 待机"""
        d = local_fallback_decision(
            soil=60,
            plant_info=_plant(),
            current_time=100,
        )
        assert d["action"] == "idle"
        assert d["duration_sec"] == 0

    def test_low_light_idle_hint(self):
        """土壤正常但光照不足 → 只提示，不自动执行动作"""
        info = _plant()
        d = local_fallback_decision(
            soil=info["soil_threshold"] + 20,
            light=info["light_min"] - 1,
            plant_info=info,
            current_time=100,
        )
        assert d["action"] == "idle"
        assert "light LOW" in d["reason"]


class TestSinglePumpInvariant:
    """单水泵硬件不变量：本地决策永不产出 'nutrient' 动作"""

    def test_no_nutrient_action_when_soil_dry(self):
        info = _plant()
        d = local_fallback_decision(
            soil=info["soil_threshold"] - 5,
            plant_info=info,
            current_time=10**9,  # 任意大时间戳
        )
        assert d["action"] != "nutrient"

    def test_no_nutrient_action_when_idle(self):
        info = _plant()
        d = local_fallback_decision(
            soil=info["soil_threshold"] + 20,
            plant_info=info,
            current_time=10**9,
        )
        assert d["action"] != "nutrient"


class TestAllPlants:
    """所有植物类型的决策测试"""

    def test_each_plant_dry_soil(self):
        """每种植物在土壤干燥时都应触发浇水"""
        for idx in range(8):
            name = config.get_plant_name(idx)
            info = config.get_plant_info(name)
            d = local_fallback_decision(
                soil=0, plant_info=info, current_time=1000,
            )
            assert d["action"] == "water", f"植物 '{name}' 土壤为0%时未触发浇水"

    def test_each_plant_normal_idle(self):
        """每种植物在一切正常时应待机"""
        for idx in range(8):
            name = config.get_plant_name(idx)
            info = config.get_plant_info(name)
            d = local_fallback_decision(
                soil=80, plant_info=info, current_time=100,
            )
            assert d["action"] == "idle", f"植物 '{name}' 正常状态下未待机"


class TestTemperatureSafety:
    """温度安全规则：高温/低温下推迟浇水，但极度干旱仍优先救命"""

    def test_high_temp_skips_normal_watering(self):
        """土壤偏干但高温 → 推迟浇水，给出温度原因"""
        info = _plant()
        d = local_fallback_decision(
            soil=info["soil_threshold"] - 5,
            plant_info=info,
            current_time=1000,
            temperature=config.TEMP_HIGH_C + 1,
        )
        assert d["action"] == "idle"
        assert "HIGH" in d["reason"]

    def test_low_temp_skips_normal_watering(self):
        """土壤偏干但低温 → 推迟浇水，给出温度原因"""
        info = _plant()
        d = local_fallback_decision(
            soil=info["soil_threshold"] - 5,
            plant_info=info,
            current_time=1000,
            temperature=config.TEMP_LOW_C - 1,
        )
        assert d["action"] == "idle"
        assert "LOW" in d["reason"]

    def test_critical_dry_overrides_high_temp(self):
        """土壤极度干旱（< thr-15）→ 即使高温也救命浇水"""
        info = _plant()
        d = local_fallback_decision(
            soil=info["soil_threshold"] - 20,
            plant_info=info,
            current_time=1000,
            temperature=config.TEMP_HIGH_C + 5,
        )
        assert d["action"] == "water"

    def test_safe_temp_allows_watering(self):
        """温度安全区间内，土壤偏干仍正常浇水"""
        info = _plant()
        d = local_fallback_decision(
            soil=info["soil_threshold"] - 5,
            plant_info=info,
            current_time=1000,
            temperature=24,
        )
        assert d["action"] == "water"

    def test_none_temperature_falls_back_to_legacy_behavior(self):
        """温度传感器离线（None）→ 不改变原决策行为"""
        info = _plant()
        d = local_fallback_decision(
            soil=info["soil_threshold"] - 5,
            plant_info=info,
            current_time=1000,
            temperature=None,
        )
        assert d["action"] == "water"
