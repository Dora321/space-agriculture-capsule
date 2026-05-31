import importlib.util
import pathlib


def _load_dashboard_server():
    root = pathlib.Path(__file__).resolve().parent.parent
    path = root / "tools" / "dashboard_server.py"
    spec = importlib.util.spec_from_file_location("dashboard_server_test", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_validate_state_clamps_values_and_normalizes_action():
    dashboard_server = _load_dashboard_server()
    state = dashboard_server._validate_state({
        "soil": 140,
        "light": -3,
        "temperature": 24.5,
        "humidity": 120,
        "plant": "Lettuce",
        "stage": "seedling",
        "action": "unknown",
        "action_started_at": 123.5,
        "reason": "status normal",
        "soil_threshold": 35,
        "light_min": 50,
        "light_opt": 70,
        "light_hours": [8, 12],
        "uptime_sec": 300,
        "decision_source": "cloud",
    })

    assert state["live"] is True
    assert state["soil"] == 100
    assert state["light"] == 0
    assert state["humidity"] == 100
    assert state["action"] == "idle"
    assert state["action_started_at"] == 123.5
    assert state["soil_threshold"] == 35
    assert state["light_min"] == 50
    assert state["light_opt"] == 70
    assert state["light_hours"] == [8, 12]
    assert state["uptime_sec"] == 300
    assert state["decision_source"] == "cloud"


def test_validate_state_remaps_legacy_nutrient_action():
    """单泵架构：dashboard 收到旧设备的 nutrient action 应归一到 idle"""
    dashboard_server = _load_dashboard_server()
    state = dashboard_server._validate_state({
        "action": "nutrient",
        "soil": 30,
        "light": 50,
        "temperature": 24,
        "humidity": 50,
    })
    assert state["action"] == "idle"


def test_validate_state_passes_through_signals():
    """Decision Plane：signals 列表从遥测数据透传到前端"""
    dashboard_server = _load_dashboard_server()
    state = dashboard_server._validate_state({
        "soil": 42,
        "light": 50,
        "temperature": 24,
        "humidity": 60,
        "signals": ["WATER", "TEMP_HIGH", "NEED_N"],
    })
    assert state["signals"] == ["WATER", "TEMP_HIGH", "NEED_N"]


def test_validate_state_filters_non_string_signals():
    """signals 列表中只保留字符串类型"""
    dashboard_server = _load_dashboard_server()
    state = dashboard_server._validate_state({
        "soil": 42,
        "light": 50,
        "temperature": 24,
        "humidity": 60,
        "signals": ["WATER", 123, None, "TEMP_HIGH"],
    })
    assert state["signals"] == ["WATER", "TEMP_HIGH"]


def test_validate_state_limits_signals_to_8():
    """signals 列表最多保留 8 个，防止滥用"""
    dashboard_server = _load_dashboard_server()
    state = dashboard_server._validate_state({
        "soil": 42,
        "light": 50,
        "temperature": 24,
        "humidity": 60,
        "signals": [f"SIG_{i}" for i in range(12)],
    })
    assert len(state["signals"]) == 8


def test_validate_state_passes_through_breeding_observation():
    """育种观察从遥测数据透传到前端"""
    dashboard_server = _load_dashboard_server()
    state = dashboard_server._validate_state({
        "soil": 42,
        "light": 50,
        "temperature": 24,
        "humidity": 60,
        "breeding_observation": "叶片展开，进入营养生长阶段",
    })
    assert state["breeding_observation"] == "叶片展开，进入营养生长阶段"


def test_validate_state_truncates_long_breeding_observation():
    """育种观察最多 200 字符"""
    dashboard_server = _load_dashboard_server()
    long_text = "x" * 300
    state = dashboard_server._validate_state({
        "soil": 42,
        "light": 50,
        "temperature": 24,
        "humidity": 60,
        "breeding_observation": long_text,
    })
    assert len(state["breeding_observation"]) == 200
