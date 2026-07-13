from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tools.experiment_clock import (
    ExperimentStore,
    calculate_status,
    validate_experiment,
)


TZ = ZoneInfo("Asia/Taipei")


def test_planting_day_is_day_one_and_offset_is_explicit():
    record = {
        "experiment_id": "EXP-20260703-A",
        "planting_date": "2026-07-03",
        "timezone": "Asia/Taipei",
        "day_offset": 0,
    }
    status = calculate_status(record, now=datetime(2026, 7, 3, 15, tzinfo=TZ))
    assert status["plant_day"] == 1
    assert status["day_source"] == "auto"

    record["day_offset"] = 2
    status = calculate_status(record, now=datetime(2026, 7, 4, 8, tzinfo=TZ))
    assert status["plant_day"] == 4
    assert status["day_source"] == "adjusted"


def test_validate_experiment_rejects_bad_date_id_and_offset():
    with pytest.raises(ValueError):
        validate_experiment({"experiment_id": "has spaces", "planting_date": "2026-07-03"})
    with pytest.raises(ValueError):
        validate_experiment({"experiment_id": "EXP-1", "planting_date": "03/07/2026"})
    with pytest.raises(ValueError):
        validate_experiment({
            "experiment_id": "EXP-1", "planting_date": "2026-07-03", "day_offset": 999,
        })


def test_store_persists_and_keeps_start_time_when_editing_same_experiment(tmp_path):
    store = ExperimentStore(tmp_path / "experiment.json")
    first = store.save({
        "experiment_id": "EXP-1",
        "plant": "生菜",
        "planting_date": "2026-07-01",
        "timezone": "Asia/Taipei",
        "day_offset": 0,
    }, updated_by="tester", now=datetime(2026, 7, 3, 9, tzinfo=TZ))
    second = store.save({
        "experiment_id": "EXP-1",
        "plant": "生菜",
        "planting_date": "2026-07-01",
        "timezone": "Asia/Taipei",
        "day_offset": 1,
    }, updated_by="tester", now=datetime(2026, 7, 3, 10, tzinfo=TZ))

    assert first["experiment_started_at"] == second["experiment_started_at"]
    assert second["plant_day"] == 4
    assert ExperimentStore(store.path).read()["updated_by"] == "tester"


def test_import_remote_caches_authoritative_fields(tmp_path):
    store = ExperimentStore(tmp_path / "experiment.json")
    status = store.import_remote({
        "configured": True,
        "experiment_id": "EXP-CLOUD",
        "plant": "番茄",
        "planting_date": "2026-07-03",
        "timezone": "Asia/Taipei",
        "day_offset": 0,
        "experiment_started_at": "2026-07-03T08:00:00+08:00",
        "updated_at": "2026-07-03T08:00:00+08:00",
        "updated_by": "cloud-user",
    })
    assert status["experiment_id"] == "EXP-CLOUD"
    assert store.read()["updated_by"] == "cloud-user"
