"""Tests for the analog keypad event logic (esp32_firmware/buttons.py).

重点验证 2026-06-02 的瞬态误触发修复（稳定门 + 起跳门）：模拟键盘是电阻梯，
红/黄(导航)键在高压端、绿(OK)/蓝(BACK)键在低压端，按下/松开导航键时 ADC 会
扫过 OK/BACK 电压带。若单拍瞬态被当成确认/返回，菜单就会"按着按着自己退出"。

测试用可控时钟（注入 time.ticks_ms/ticks_diff）+ 可控 ADC 值逐拍驱动 _event。
"""
import importlib

import pytest

import buttons as buttons_mod
from buttons import AnalogKeypad

# 实测各键稳态 ADC（与 DEFAULT_THRESHOLDS 对应）
IDLE = 0
BLUE = 2030    # BACK
GREEN = 2305   # OK
YEL = 2700     # DOWN
RED = 3242     # UP


@pytest.fixture
def clock(monkeypatch):
    """注入 MicroPython 风格的 ticks 时钟（PC 的 time 没有 ticks_ms）。"""
    holder = {"t": 0}
    monkeypatch.setattr(buttons_mod.time, "ticks_ms", lambda: holder["t"], raising=False)
    monkeypatch.setattr(buttons_mod.time, "ticks_diff", lambda a, b: a - b, raising=False)
    return holder


@pytest.fixture
def kp(clock):
    pad = AnalogKeypad(adc_pin=33)
    return pad


def _poll(kp, clock, adc_val, t):
    """把时钟推到 t、把 ADC 设成 adc_val，返回该拍的 (nav, ok, back)。"""
    clock["t"] = t
    kp._adc._value = adc_val
    nav = kp.update()
    ok = kp.pressed()
    back = kp.back_pressed()
    return nav, ok, back


# 轮询间隔 50ms（与菜单循环 sleep_ms(50) 一致），稳定门 30ms < 50ms
STEP = 50


def test_red_press_with_ok_transient_does_not_confirm(kp, clock):
    """按红键途中扫过绿带的单拍瞬态，绝不能触发 OK（这正是会误退的 bug）。"""
    t = 0
    # 空闲
    assert _poll(kp, clock, IDLE, t) == (0, False, False)
    # 第 1 拍：爬坡途中恰好采到绿带（OK 瞬态）
    t += STEP
    nav, ok, back = _poll(kp, clock, GREEN, t)
    assert ok is False, "单拍绿带瞬态被误判成确认"
    assert back is False
    # 第 2 拍：电压已稳定到红键
    t += STEP
    nav, ok, back = _poll(kp, clock, RED, t)
    assert ok is False and back is False
    # 第 3 拍：红键稳定 → 应报 UP(-1)，仍不触发 OK
    t += STEP
    nav, ok, back = _poll(kp, clock, RED, t)
    assert nav == -1, "稳定的红键应产生 UP 导航事件"
    assert ok is False and back is False


def test_release_sweep_through_ok_does_not_confirm(kp, clock):
    """从按住红键松手、电压一路滑过绿带，绝不能触发 OK（起跳门拦截）。"""
    t = 0
    # 先把红键按稳，产生一次 UP
    _poll(kp, clock, IDLE, t); t += STEP
    _poll(kp, clock, RED, t); t += STEP
    nav, _, _ = _poll(kp, clock, RED, t)
    assert nav == -1
    # 松手：电压在绿带停留（哪怕停 2 拍，起跳门也拦），都不该确认
    t += STEP
    _, ok, back = _poll(kp, clock, GREEN, t)
    assert ok is False and back is False
    t += STEP
    _, ok, back = _poll(kp, clock, GREEN, t)
    assert ok is False, "松手途中停在绿带被误判成确认（起跳门失效）"
    assert back is False


def test_genuine_ok_from_idle_confirms(kp, clock):
    """从空闲直接稳定按下绿键 → 必须能正常确认。"""
    t = 0
    _poll(kp, clock, IDLE, t); t += STEP
    # 第 1 拍采到绿带（候选），还不够稳定
    _, ok, _ = _poll(kp, clock, GREEN, t)
    assert ok is False
    # 第 2 拍绿键稳定 → 确认应触发
    t += STEP
    _, ok, _ = _poll(kp, clock, GREEN, t)
    assert ok is True, "从空闲稳定按下绿键应能确认"


def test_genuine_back_from_idle_triggers(kp, clock):
    """从空闲稳定按下蓝键 → 返回应触发。"""
    t = 0
    _poll(kp, clock, IDLE, t); t += STEP
    _poll(kp, clock, BLUE, t); t += STEP
    _, _, back = _poll(kp, clock, BLUE, t)
    assert back is True, "从空闲稳定按下蓝键应能返回"


def test_held_red_never_emits_ok(kp, clock):
    """红键持续按住期间，反复轮询都不该冒出 OK/BACK。"""
    t = 0
    _poll(kp, clock, IDLE, t)
    for _ in range(10):
        t += STEP
        _, ok, back = _poll(kp, clock, RED, t)
        assert ok is False and back is False
