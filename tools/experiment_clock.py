#!/usr/bin/env python3
"""Persistent experiment calendar shared by the dashboard and Pi gateway."""

from __future__ import annotations

import json
import re
import threading
from datetime import date, datetime, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 fallback
    ZoneInfo = None


DEFAULT_TIMEZONE = "Asia/Taipei"
_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,48}$")


def _timezone(name: str):
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    return timezone.utc


def _now(timezone_name: str = DEFAULT_TIMEZONE) -> datetime:
    return datetime.now(_timezone(timezone_name))


def _parse_date(value: object) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError("planting_date must use YYYY-MM-DD")


def validate_experiment(payload: dict) -> dict:
    """Validate the editable portion of an experiment record."""
    if not isinstance(payload, dict):
        raise ValueError("experiment payload must be an object")

    experiment_id = str(payload.get("experiment_id", "")).strip()
    if not _ID_RE.fullmatch(experiment_id):
        raise ValueError("experiment_id must be 1-48 letters, numbers, '.', '_' or '-'")

    planting_date = _parse_date(payload.get("planting_date"))
    timezone_name = str(payload.get("timezone", DEFAULT_TIMEZONE)).strip()
    if timezone_name != DEFAULT_TIMEZONE:
        raise ValueError("timezone must be Asia/Taipei")

    try:
        day_offset = int(payload.get("day_offset", 0))
    except (TypeError, ValueError):
        raise ValueError("day_offset must be an integer")
    if not -365 <= day_offset <= 365:
        raise ValueError("day_offset must be between -365 and 365")

    return {
        "schema": "experiment.config.v1",
        "experiment_id": experiment_id,
        "plant": str(payload.get("plant", "")).strip()[:24],
        "planting_date": planting_date.isoformat(),
        "timezone": timezone_name,
        "day_offset": day_offset,
    }


def calculate_status(record: dict, now: datetime | None = None) -> dict:
    """Return a public record with authoritative plant age and elapsed time."""
    if not record:
        return {"configured": False, "schema": "experiment.config.v1"}

    value = dict(record)
    timezone_name = value.get("timezone", DEFAULT_TIMEZONE)
    current = now or _now(timezone_name)
    if current.tzinfo is None:
        current = current.replace(tzinfo=_timezone(timezone_name))
    else:
        current = current.astimezone(_timezone(timezone_name))

    planted = _parse_date(value.get("planting_date"))
    day_offset = int(value.get("day_offset", 0))
    plant_day = (current.date() - planted).days + 1 + day_offset
    value["configured"] = True
    value["plant_day"] = max(1, plant_day)
    value["day_source"] = "adjusted" if day_offset else "auto"

    started_at = value.get("experiment_started_at")
    try:
        started = datetime.fromisoformat(started_at) if started_at else current
        if started.tzinfo is None:
            started = started.replace(tzinfo=_timezone(timezone_name))
        elapsed = max(0.0, (current - started.astimezone(current.tzinfo)).total_seconds() / 3600)
    except (TypeError, ValueError):
        elapsed = 0.0
    value["experiment_elapsed_hours"] = round(elapsed, 2)
    return value


class ExperimentStore:
    """Atomic JSON store suitable for both the cloud server and Raspberry Pi."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read_unlocked(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def read(self) -> dict:
        with self._lock:
            return self._read_unlocked()

    def status(self, now: datetime | None = None) -> dict:
        return calculate_status(self.read(), now=now)

    def save(self, payload: dict, *, updated_by: str = "operator",
             now: datetime | None = None) -> dict:
        clean = validate_experiment(payload)
        current = now or _now(clean["timezone"])
        actor = str(updated_by or "operator").strip()[:32]
        with self._lock:
            previous = self._read_unlocked()
            same_experiment = previous.get("experiment_id") == clean["experiment_id"]
            clean["experiment_started_at"] = (
                previous.get("experiment_started_at")
                if same_experiment and previous.get("experiment_started_at")
                else current.isoformat(timespec="seconds")
            )
            clean["updated_at"] = current.isoformat(timespec="seconds")
            clean["updated_by"] = actor
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
            temp_path.write_text(
                json.dumps(clean, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temp_path.replace(self.path)
        return calculate_status(clean, now=current)

    def import_remote(self, payload: dict) -> dict:
        """Cache an already validated public record received from the cloud."""
        if not isinstance(payload, dict) or not payload.get("configured"):
            return self.status()
        clean = validate_experiment(payload)
        for key in ("experiment_started_at", "updated_at", "updated_by"):
            if payload.get(key):
                clean[key] = payload[key]
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
            temp_path.write_text(
                json.dumps(clean, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temp_path.replace(self.path)
        return calculate_status(clean)
