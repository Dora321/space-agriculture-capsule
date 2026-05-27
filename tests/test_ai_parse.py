"""
测试 AI 响应解析 - ai_client.parse_decision_from_text
当 AI 返回的 JSON 解析失败时，系统使用关键词匹配作为兜底
"""
from ai_client import parse_decision_from_text


class TestParseAction:
    """动作关键词解析"""

    def test_parse_water_english(self):
        d = parse_decision_from_text("suggest water for 10 seconds")
        assert d["action"] == "water"

    def test_parse_water_chinese(self):
        d = parse_decision_from_text("建议浇水8秒")
        assert d["action"] == "water"

    def test_parse_light_english(self):
        d = parse_decision_from_text("suggest light for 60 seconds")
        assert d["action"] == "light"

    def test_parse_light_chinese(self):
        d = parse_decision_from_text("建议补光60秒")
        assert d["action"] == "light"

    def test_nutrient_text_falls_back_to_idle(self):
        """单泵架构下，AI 万一返回'营养'字样也应被解析为 idle，绝不出现 nutrient action"""
        d = parse_decision_from_text("补充营养液5秒")
        assert d["action"] == "idle"

    def test_parse_idle_default(self):
        """无关键词时默认 idle"""
        d = parse_decision_from_text("一切正常无需操作")
        assert d["action"] == "idle"


class TestParseDuration:
    """时长提取"""

    def test_extract_duration_number(self):
        d = parse_decision_from_text("water duration 15 seconds")
        assert d["duration_sec"] == 15

    def test_extract_duration_underscore(self):
        d = parse_decision_from_text("water duration_sec 10 because dry")
        assert d["duration_sec"] == 10

    def test_no_duration_uses_default(self):
        """无 duration 关键词时使用默认值"""
        d = parse_decision_from_text("water now please")
        assert d["action"] == "water"
        assert d["duration_sec"] == 8  # 默认浇水时长


class TestEdgeCases:
    """边界情况"""

    def test_empty_string(self):
        d = parse_decision_from_text("")
        assert d["action"] == "idle"

    def test_mixed_case(self):
        d = parse_decision_from_text("WATER the plants NOW")
        assert d["action"] == "water"

    def test_multiple_keywords_water_wins(self):
        """单泵架构下，仅 water 是合法关键词；其它一律 idle"""
        d = parse_decision_from_text("water and then nutrient")
        assert d["action"] == "water"
