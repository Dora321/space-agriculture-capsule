"""
测试工具函数 - utils 模块
"""
from utils import format_uptime, moving_average, smooth_value, is_daytime


class TestFormatUptime:
    """运行时间格式化"""

    def test_seconds(self):
        assert format_uptime(30) == "30秒"

    def test_minutes(self):
        assert format_uptime(130) == "2分10秒"

    def test_hours(self):
        assert format_uptime(3700) == "1小时1分"

    def test_zero(self):
        assert format_uptime(0) == "0秒"


class TestMovingAverage:
    """移动平均"""

    def test_basic(self):
        values = [10, 20, 30]
        avg = moving_average(values, 40, window=5)
        assert avg == 25.0  # (10+20+30+40) / 4

    def test_window_limit(self):
        values = [1, 2, 3, 4, 5]
        avg = moving_average(values, 6, window=5)
        # 窗口 5, values 现在是 [2,3,4,5,6]
        assert avg == 4.0
        assert len(values) == 5


class TestSmoothValue:
    """平滑值变化"""

    def test_smooth_towards_target(self):
        result = smooth_value(10, 20, factor=0.5)
        assert result == 15.0

    def test_smooth_no_change(self):
        result = smooth_value(10, 10, factor=0.3)
        assert result == 10.0

    def test_smooth_factor_zero(self):
        result = smooth_value(10, 100, factor=0.0)
        assert result == 10.0
