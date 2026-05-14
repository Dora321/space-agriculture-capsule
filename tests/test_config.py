"""
测试配置模块 - 植物数据库完整性、生长阶段逻辑、安全参数
"""
import json
import pathlib
import config


def _load_plant_db():
    """从 plants.json 加载完整植物数据库（测试用）"""
    fw_dir = str(pathlib.Path(__file__).resolve().parent.parent / "esp32_firmware")
    with open(str(pathlib.Path(fw_dir) / "plants.json"), encoding="utf-8") as f:
        return json.load(f)


_PLANT_DB = _load_plant_db()


class TestPlantDatabase:
    """植物数据库完整性测试"""

    def test_all_dip_plants_in_db(self):
        """8 种拨码对应的植物必须全在 PLANT_DB 中"""
        for idx in range(8):
            name = config.get_plant_name(idx)
            info = config.get_plant_info(name)
            assert "soil_threshold" in info, f"植物 '{name}' 缺少 soil_threshold"
            assert "co2_threshold" in info, f"植物 '{name}' 缺少 co2_threshold"
            assert "growth_stages" in info, f"植物 '{name}' 缺少 growth_stages"

    def test_required_fields(self):
        """每种植物必须包含所有必要字段"""
        required = [
            "soil_threshold", "co2_threshold",
            "water_sec", "nutrient_sec", "ventilate_sec",
            "nutrient_interval", "growth_stages",
        ]
        for name, info in _PLANT_DB.items():
            for field in required:
                assert field in info, f"植物 '{name}' 缺少字段 '{field}'"

    def test_min_growth_stages(self):
        """每种植物至少 2 个生长阶段"""
        for name, info in _PLANT_DB.items():
            stages = info["growth_stages"]
            assert len(stages) >= 2, f"植物 '{name}' 只有 {len(stages)} 个阶段，至少需要 2 个"

    def test_growth_stage_day_coverage(self):
        """生长阶段天数必须连续覆盖（无间隔）"""
        for name, info in _PLANT_DB.items():
            stages = info["growth_stages"]
            # 第一个阶段应从第 0 天开始
            assert stages[0]["days"][0] == 0, \
                f"植物 '{name}' 第一阶段不是从第 0 天开始"
            # 相邻阶段天数连续
            for i in range(1, len(stages)):
                prev_end = stages[i - 1]["days"][1]
                curr_start = stages[i]["days"][0]
                assert curr_start == prev_end + 1, \
                    f"植物 '{name}': 阶段 {i-1} 结束于第{prev_end}天，" \
                    f"阶段 {i} 起始于第{curr_start}天，存在间隔"

    def test_growth_stage_required_fields(self):
        """每个生长阶段必须包含 stage/fert/water_need/note"""
        required_stage_fields = ["days", "stage", "fert", "water_need", "note"]
        for name, info in _PLANT_DB.items():
            for i, stage in enumerate(info["growth_stages"]):
                for field in required_stage_fields:
                    assert field in stage, \
                        f"植物 '{name}' 阶段 {i} 缺少字段 '{field}'"

    def test_soil_threshold_range(self):
        """土壤湿度阈值应在合理范围 (10-60)"""
        for name, info in _PLANT_DB.items():
            t = info["soil_threshold"]
            assert 10 <= t <= 60, f"植物 '{name}' soil_threshold={t} 超出合理范围"

    def test_co2_threshold_range(self):
        """CO2 阈值应在 600-2000"""
        for name, info in _PLANT_DB.items():
            t = info["co2_threshold"]
            assert 600 <= t <= 2000, f"植物 '{name}' co2_threshold={t} 超出合理范围"


class TestGrowthStage:
    """生长阶段查询逻辑测试"""

    def test_seedling_stage(self):
        info = config.get_plant_info("生菜")
        stage = config.get_growth_stage(info, 0)
        assert stage["stage"] == "seedling"

    def test_boundary_day(self):
        """阶段边界日测试"""
        info = config.get_plant_info("生菜")
        # 第 7 天应该还在 seedling
        assert config.get_growth_stage(info, 7)["stage"] == "seedling"
        # 第 8 天应进入 vegetative
        assert config.get_growth_stage(info, 8)["stage"] == "vegetative"

    def test_last_stage(self):
        info = config.get_plant_info("生菜")
        assert config.get_growth_stage(info, 40)["stage"] == "harvesting"

    def test_beyond_max_day(self):
        """超出所有阶段范围应返回最后一个阶段"""
        info = config.get_plant_info("生菜")
        stage = config.get_growth_stage(info, 9999)
        assert stage["stage"] == "harvesting"

    def test_empty_stages(self):
        """空阶段列表应返回 unknown"""
        fake = {"growth_stages": []}
        stage = config.get_growth_stage(fake, 10)
        assert stage["stage"] == "unknown"


class TestDipEncoding:
    """拨码开关编码测试"""

    def test_valid_range(self):
        """0-7 都应返回有效植物名"""
        for i in range(8):
            name = config.get_plant_name(i)
            assert name in _PLANT_DB

    def test_out_of_range_default(self):
        """超出范围应返回默认值（生菜）"""
        assert config.get_plant_name(99) == "生菜"
        assert config.get_plant_name(-1) == "生菜"

    def test_unknown_plant_default(self):
        """未知植物名应返回生菜参数"""
        info = config.get_plant_info("不存在的植物")
        default_info = config.get_plant_info("生菜")
        assert info["soil_threshold"] == default_info["soil_threshold"]


class TestSafetyConstants:
    """安全参数合理性测试"""

    def test_pump_max_run(self):
        assert 10 <= config.PUMP_MAX_RUN_SEC <= 120

    def test_max_actions_per_hour(self):
        assert config.MAX_ACTIONS_PER_HOUR <= 20

    def test_min_action_interval(self):
        assert config.MIN_ACTION_INTERVAL >= 30

    def test_max_errors(self):
        assert 5 <= config.MAX_ERRORS <= 20

    def test_read_interval(self):
        assert config.READ_INTERVAL >= 60, "读取间隔不应低于 60 秒"
