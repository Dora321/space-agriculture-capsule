"""展示模式（state.fast_mode）：读真实传感器但快速响应。

验证间隔选择助手 + 动作限频在 fast_mode 下被跳过（与 DEMO_MODE 假数据解耦）。
"""
import time

import action_runtime
import actuators
import loop_runtime as lr

FAST = getattr(lr.config, "FAST_READ_INTERVAL", 3)
NORMAL_READ = lr.config.READ_INTERVAL
NORMAL_DECISION = getattr(lr.config, "DECISION_INTERVAL", 300)


class FakeState:
    def __init__(self, fast=False):
        self.fast_mode = fast
        self.last_action = "idle"
        self.last_action_time = 0
        self.action_count = 0
        self.action_count_start = 0


# ── 间隔选择 ───────────────────────────────────────────────

def test_read_interval_normal():
    assert lr._read_interval(FakeState(False), demo_enabled=False) == NORMAL_READ


def test_read_interval_fast_mode():
    assert lr._read_interval(FakeState(True), demo_enabled=False) == FAST


def test_read_interval_fast_beats_demo():
    # fast_mode 优先于 DEMO_MODE
    assert lr._read_interval(FakeState(True), demo_enabled=True) == FAST


def test_decision_interval_fast_mode():
    assert lr._decision_interval(FakeState(True), demo_enabled=False) == FAST


def test_decision_interval_normal():
    assert lr._decision_interval(FakeState(False), demo_enabled=False) == NORMAL_DECISION


# ── 动作限频在 fast_mode 下跳过 ────────────────────────────

def test_fast_mode_bypasses_action_throttle():
    actuators.init()
    s = FakeState(fast=True)
    s.last_action = "water"
    s.last_action_time = time.time()   # 刚动作过，正常会被 MIN_ACTION_INTERVAL 拦
    assert action_runtime.safety_check(s, demo_enabled=False) is True


def test_normal_mode_throttles_recent_action():
    actuators.init()
    s = FakeState(fast=False)
    s.last_action = "water"
    s.last_action_time = time.time()   # 刚动作过 → 应被拦
    assert action_runtime.safety_check(s, demo_enabled=False) is False
