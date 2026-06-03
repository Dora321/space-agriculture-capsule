"""Tests for the WS2812 现场演示灯效秀 (esp32_firmware/status_strip.demo_show).

灯效是演示用、无单测覆盖；这里只锁住 demo_show 能在灯条启用时跑完不报错、
且确实写了灯条（MockNeoPixel.last_write 被设置）。time.sleep_ms 是 MicroPython
专有，PC 上没有，用 monkeypatch 注入 no-op。
"""
import config
import status_strip as ss


def _patch_sleep(monkeypatch):
    monkeypatch.setattr(ss.time, "sleep_ms", lambda ms: None, raising=False)


def test_demo_show_runs_and_writes(monkeypatch):
    _patch_sleep(monkeypatch)
    # 强制启用灯条（测试环境的本地 config 可能禁用），再初始化
    monkeypatch.setattr(config, "WS2812_ENABLED", True, raising=False)
    ss.init()
    assert ss._np is not None, "启用后灯条应初始化为 MockNeoPixel"
    ss._np.last_write = None
    ss.demo_show()
    assert ss._np.last_write is not None, "demo_show 应至少写过一次灯条"


def test_demo_show_noop_when_strip_absent(monkeypatch):
    _patch_sleep(monkeypatch)
    saved = ss._np
    try:
        ss._np = None               # 模拟无灯条/stub
        ss.demo_show()              # 不应抛异常
    finally:
        ss._np = saved


def test_demo_signal_list_all_have_animations():
    # 演示序列里的每个信号都要有对应动画，否则现场会打印 Unknown
    for sig in ss._DEMO_SIGNALS + [ss.SIGNAL_BREEDING_GEN_UP]:
        assert sig in ss._SIGNAL_ANIMATIONS


def test_demo_show_calls_on_signal_subtitle(monkeypatch):
    _patch_sleep(monkeypatch)
    monkeypatch.setattr(config, "WS2812_ENABLED", True, raising=False)
    ss.init()
    seen = []
    ss.demo_show(on_signal=lambda n: seen.append(n))
    assert "RAINBOW" in seen and "GEN UP" in seen     # 开场/高潮字幕
    assert ss.SIGNAL_WATER in seen                     # 信号段字幕


def test_play_for_loops_then_off(monkeypatch):
    _patch_sleep(monkeypatch)
    monkeypatch.setattr(config, "WS2812_ENABLED", True, raising=False)
    ss.init()
    # 假时钟：每次调用 +500ms，确保 while 循环会在 total_ms 后结束
    clk = {"t": 0}

    def ticks():
        clk["t"] += 500
        return clk["t"]

    monkeypatch.setattr(ss.time, "ticks_ms", ticks, raising=False)
    monkeypatch.setattr(ss.time, "ticks_diff", lambda a, b: a - b, raising=False)
    ss._np.last_write = None
    ss.play_for(ss.SIGNAL_WATER, total_sec=2)   # 应循环几次后 off，不死循环
    assert ss._np.last_write is not None
