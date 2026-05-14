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
            co2=400, plant_info=info,
            last_nutrient=0, current_time=1000,
        )
        assert d["action"] == "water"
        assert d["duration_sec"] > info["water_sec"]  # 延长

    def test_below_threshold_triggers_water(self):
        """低于阈值 → 正常浇水"""
        info = _plant()
        d = local_fallback_decision(
            soil=info["soil_threshold"] - 5,
            co2=400, plant_info=info,
            last_nutrient=0, current_time=1000,
        )
        assert d["action"] == "water"
        assert d["duration_sec"] == info["water_sec"]

    def test_above_threshold_no_water(self):
        """高于阈值 → 不浇水"""
        info = _plant()
        d = local_fallback_decision(
            soil=info["soil_threshold"] + 20,
            co2=400, plant_info=info,
            last_nutrient=0, current_time=1000,
        )
        assert d["action"] != "water"


class TestVentilateDecision:
    """换气决策测试"""

    def test_high_co2_triggers_ventilate(self):
        """CO2 超标 → 换气"""
        info = _plant()
        d = local_fallback_decision(
            soil=60, co2=info["co2_threshold"] + 100,
            plant_info=info,
            last_nutrient=0, current_time=1000,
        )
        assert d["action"] == "ventilate"

    def test_critical_co2_longer_ventilation(self):
        """CO2 严重超标 → 延长换气"""
        info = _plant()
        d = local_fallback_decision(
            soil=60, co2=info["co2_threshold"] + 500,
            plant_info=info,
            last_nutrient=0, current_time=1000,
        )
        assert d["action"] == "ventilate"
        assert d["duration_sec"] > info["ventilate_sec"]

    def test_normal_co2_no_ventilate(self):
        """CO2 正常 → 不换气"""
        d = local_fallback_decision(
            soil=60, co2=400,
            plant_info=_plant(),
            last_nutrient=0, current_time=1000,
        )
        assert d["action"] != "ventilate"


class TestNutrientDecision:
    """营养液决策测试"""

    def test_nutrient_interval_expired(self):
        """营养液间隔到期 + 土壤适中 → 补充营养"""
        info = _plant()
        interval = info["nutrient_interval"]
        d = local_fallback_decision(
            soil=info["soil_threshold"] + 5,
            co2=400, plant_info=info,
            last_nutrient=0,
            current_time=interval + 1,
        )
        assert d["action"] == "nutrient"

    def test_nutrient_not_due(self):
        """营养液间隔未到 → 不补充"""
        info = _plant()
        d = local_fallback_decision(
            soil=60, co2=400, plant_info=info,
            last_nutrient=100, current_time=200,
        )
        assert d["action"] != "nutrient"


class TestIdleDecision:
    """待机决策测试"""

    def test_all_normal_idle(self):
        """一切正常 → 待机"""
        d = local_fallback_decision(
            soil=60, co2=400,
            plant_info=_plant(),
            last_nutrient=100, current_time=100,
        )
        assert d["action"] == "idle"
        assert d["duration_sec"] == 0


class TestPriority:
    """决策优先级测试"""

    def test_extreme_dry_beats_high_co2(self):
        """极度干燥优先于 CO2 超标"""
        info = _plant()
        d = local_fallback_decision(
            soil=5, co2=info["co2_threshold"] + 500,
            plant_info=info,
            last_nutrient=0, current_time=1000,
        )
        assert d["action"] == "water"

    def test_dry_beats_nutrient(self):
        """土壤干燥优先于营养液"""
        info = _plant()
        d = local_fallback_decision(
            soil=info["soil_threshold"] - 5,
            co2=400, plant_info=info,
            last_nutrient=0,
            current_time=info["nutrient_interval"] + 1,
        )
        assert d["action"] == "water"

    def test_co2_beats_nutrient(self):
        """CO2 超标优先于营养液"""
        info = _plant()
        d = local_fallback_decision(
            soil=60, co2=info["co2_threshold"] + 100,
            plant_info=info,
            last_nutrient=0,
            current_time=info["nutrient_interval"] + 1,
        )
        assert d["action"] == "ventilate"


class TestAllPlants:
    """所有植物类型的决策测试"""

    def test_each_plant_dry_soil(self):
        """每种植物在土壤干燥时都应触发浇水"""
        for idx in range(8):
            name = config.get_plant_name(idx)
            info = config.get_plant_info(name)
            d = local_fallback_decision(
                soil=0, co2=400, plant_info=info,
                last_nutrient=0, current_time=1000,
            )
            assert d["action"] == "water", f"植物 '{name}' 土壤为0%时未触发浇水"

    def test_each_plant_high_co2(self):
        """每种植物在 CO2 超标时都应触发换气"""
        for idx in range(8):
            name = config.get_plant_name(idx)
            info = config.get_plant_info(name)
            d = local_fallback_decision(
                soil=80, co2=info["co2_threshold"] + 100,
                plant_info=info,
                last_nutrient=0, current_time=1000,
            )
            assert d["action"] == "ventilate", f"植物 '{name}' CO2超标时未触发换气"

    def test_each_plant_normal_idle(self):
        """每种植物在一切正常时应待机"""
        for idx in range(8):
            name = config.get_plant_name(idx)
            info = config.get_plant_info(name)
            d = local_fallback_decision(
                soil=80, co2=400, plant_info=info,
                last_nutrient=100, current_time=100,
            )
            assert d["action"] == "idle", f"植物 '{name}' 正常状态下未待机"
