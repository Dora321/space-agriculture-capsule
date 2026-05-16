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
            last_nutrient=0, current_time=1000,
        )
        assert d["action"] == "water"
        assert d["duration_sec"] > info["water_sec"]  # 延长

    def test_below_threshold_triggers_water(self):
        """低于阈值 → 正常浇水"""
        info = _plant()
        d = local_fallback_decision(
            soil=info["soil_threshold"] - 5,
            plant_info=info,
            last_nutrient=0, current_time=1000,
        )
        assert d["action"] == "water"
        assert d["duration_sec"] == info["water_sec"]

    def test_above_threshold_no_water(self):
        """高于阈值 → 不浇水"""
        info = _plant()
        d = local_fallback_decision(
            soil=info["soil_threshold"] + 20,
            plant_info=info,
            last_nutrient=0, current_time=1000,
        )
        assert d["action"] != "water"


class TestNutrientDecision:
    """营养液决策测试"""

    def test_nutrient_interval_expired(self):
        """营养液间隔到期 + 土壤适中 → 补充营养"""
        info = _plant()
        interval = info["nutrient_interval"]
        d = local_fallback_decision(
            soil=info["soil_threshold"] + 5,
            plant_info=info,
            last_nutrient=0,
            current_time=interval + 1,
        )
        assert d["action"] == "nutrient"

    def test_nutrient_not_due(self):
        """营养液间隔未到 → 不补充"""
        info = _plant()
        d = local_fallback_decision(
            soil=60, plant_info=info,
            last_nutrient=100, current_time=200,
        )
        assert d["action"] != "nutrient"


class TestIdleDecision:
    """待机决策测试"""

    def test_all_normal_idle(self):
        """一切正常 → 待机"""
        d = local_fallback_decision(
            soil=60,
            plant_info=_plant(),
            last_nutrient=100, current_time=100,
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
            last_nutrient=100,
            current_time=100,
        )
        assert d["action"] == "idle"
        assert "light LOW" in d["reason"]


class TestPriority:
    """决策优先级测试"""

    def test_dry_beats_nutrient(self):
        """土壤干燥优先于营养液"""
        info = _plant()
        d = local_fallback_decision(
            soil=info["soil_threshold"] - 5,
            plant_info=info,
            last_nutrient=0,
            current_time=info["nutrient_interval"] + 1,
        )
        assert d["action"] == "water"


class TestAllPlants:
    """所有植物类型的决策测试"""

    def test_each_plant_dry_soil(self):
        """每种植物在土壤干燥时都应触发浇水"""
        for idx in range(8):
            name = config.get_plant_name(idx)
            info = config.get_plant_info(name)
            d = local_fallback_decision(
                soil=0, plant_info=info,
                last_nutrient=0, current_time=1000,
            )
            assert d["action"] == "water", f"植物 '{name}' 土壤为0%时未触发浇水"

    def test_each_plant_normal_idle(self):
        """每种植物在一切正常时应待机"""
        for idx in range(8):
            name = config.get_plant_name(idx)
            info = config.get_plant_info(name)
            d = local_fallback_decision(
                soil=80, plant_info=info,
                last_nutrient=100, current_time=100,
            )
            assert d["action"] == "idle", f"植物 '{name}' 正常状态下未待机"
