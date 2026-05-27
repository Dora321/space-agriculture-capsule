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
