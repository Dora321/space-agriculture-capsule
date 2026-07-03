"""SQLite persistence shared by the capture scheduler and API worker."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Mapping


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class VisionStore:
    """Durable capture queue with leases for separately running workers."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(
            self.path, timeout=10, isolation_level=None, check_same_thread=False
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self._initialize()

    def _initialize(self) -> None:
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS kv (
          key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS captures (
          capture_id TEXT PRIMARY KEY, captured_at REAL NOT NULL,
          cycle_id TEXT NOT NULL, overview_path TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('queued','leased','retry','succeeded','failed')),
          current_light REAL, required_light REAL, attempts INTEGER NOT NULL DEFAULT 0,
          available_at REAL NOT NULL, lease_owner TEXT, lease_until REAL,
          result_json TEXT, last_error TEXT, updated_at REAL NOT NULL,
          context_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS capture_queue_idx
          ON captures(status, available_at, captured_at);
        CREATE TABLE IF NOT EXISTS observations (
          observation_id TEXT PRIMARY KEY,
          capture_id TEXT NOT NULL REFERENCES captures(capture_id) ON DELETE CASCADE,
          pot_id TEXT NOT NULL, material_id TEXT NOT NULL, is_control INTEGER NOT NULL,
          roi_id TEXT NOT NULL, image_path TEXT NOT NULL, quality_json TEXT NOT NULL,
          analysis_json TEXT, UNIQUE(capture_id, pot_id)
        );
        CREATE TABLE IF NOT EXISTS api_usage (
          usage_id INTEGER PRIMARY KEY AUTOINCREMENT, used_at REAL NOT NULL,
          capture_id TEXT NOT NULL, image_bytes INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS cloud_sync (
          capture_id TEXT PRIMARY KEY REFERENCES captures(capture_id) ON DELETE CASCADE,
          status TEXT NOT NULL CHECK(status IN ('leased','retry','succeeded')),
          attempts INTEGER NOT NULL DEFAULT 0, available_at REAL NOT NULL DEFAULT 0,
          lease_until REAL, last_error TEXT, synced_at REAL, updated_at REAL NOT NULL
        );
        """)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(captures)")}
        if "context_json" not in columns:
            self.db.execute("ALTER TABLE captures ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}'")

    def close(self) -> None:
        self.db.close()

    def set_value(self, key: str, value: Mapping[str, Any], *, now: float | None = None) -> None:
        timestamp = time.time() if now is None else float(now)
        self.db.execute(
            "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
            (key, _dump(value), timestamp),
        )

    def get_value(self, key: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT value,updated_at FROM kv WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        value = json.loads(row["value"])
        value.setdefault("updated_at", row["updated_at"])
        return value

    def save_telemetry(self, report: Mapping[str, Any], *, received_at: float | None = None) -> None:
        value = dict(report)
        value["received_at"] = time.time() if received_at is None else float(received_at)
        self.set_value("telemetry", value, now=value["received_at"])

    def latest_telemetry(self) -> dict[str, Any] | None:
        return self.get_value("telemetry")

    def set_status(self, status: Mapping[str, Any], *, now: float | None = None) -> None:
        self.set_value("status", status, now=now)

    def status(self) -> dict[str, Any] | None:
        return self.get_value("status")

    def create_capture(self, capture: Mapping[str, Any], observations: list[Mapping[str, Any]]) -> None:
        if not observations:
            raise ValueError("a capture requires at least one observation")
        captured_at = float(capture.get("captured_at", time.time()))
        with self.db:
            self.db.execute(
                "INSERT INTO captures(capture_id,captured_at,cycle_id,overview_path,status,"
                "current_light,required_light,available_at,updated_at,context_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (capture["capture_id"], captured_at, capture.get("cycle_id", "unassigned"),
                 str(capture["overview_path"]), "queued", capture.get("current_light"),
                 capture.get("required_light"), captured_at, captured_at,
                 _dump(capture.get("context", {}))),
            )
            for item in observations:
                self.db.execute(
                    "INSERT INTO observations(observation_id,capture_id,pot_id,material_id,"
                    "is_control,roi_id,image_path,quality_json) VALUES(?,?,?,?,?,?,?,?)",
                    (item.get("observation_id", f'{capture["capture_id"]}:{item["pot_id"]}'),
                     capture["capture_id"], item["pot_id"], item.get("material_id", ""),
                     int(bool(item.get("is_control"))), item.get("roi_id", item["pot_id"]),
                     str(item["image_path"]), _dump(item.get("quality", {}))),
                )

    def last_capture_at(self) -> float | None:
        row = self.db.execute(
            "SELECT MAX(captured_at) AS value FROM captures WHERE status!='failed'"
        ).fetchone()
        return None if row["value"] is None else float(row["value"])

    def last_success_at(self) -> float | None:
        row = self.db.execute(
            "SELECT MAX(captured_at) AS value FROM captures WHERE status='succeeded'"
        ).fetchone()
        return None if row["value"] is None else float(row["value"])

    def lease_next(self, worker_id: str, *, now: float | None = None,
                   lease_sec: int = 120) -> dict[str, Any] | None:
        timestamp = time.time() if now is None else float(now)
        with self.db:
            self.db.execute(
                "UPDATE captures SET status='retry',lease_owner=NULL,lease_until=NULL "
                "WHERE status='leased' AND lease_until<?", (timestamp,)
            )
            row = self.db.execute(
                "SELECT capture_id FROM captures WHERE status IN ('queued','retry') "
                "AND available_at<=? ORDER BY captured_at LIMIT 1", (timestamp,)
            ).fetchone()
            if row is None:
                return None
            changed = self.db.execute(
                "UPDATE captures SET status='leased',lease_owner=?,lease_until=?,"
                "attempts=attempts+1,updated_at=? WHERE capture_id=? AND status IN ('queued','retry')",
                (worker_id, timestamp + lease_sec, timestamp, row["capture_id"]),
            ).rowcount
            if changed != 1:
                return None
        return self.get_capture(row["capture_id"])

    def mark_succeeded(self, capture_id: str, result: Mapping[str, Any], *, now: float | None = None) -> None:
        timestamp = time.time() if now is None else float(now)
        with self.db:
            self.db.execute(
                "UPDATE captures SET status='succeeded',result_json=?,lease_owner=NULL,"
                "lease_until=NULL,last_error=NULL,updated_at=? WHERE capture_id=?",
                (_dump(result), timestamp, capture_id),
            )
            for item in result.get("observations", []):
                self.db.execute(
                    "UPDATE observations SET analysis_json=? WHERE capture_id=? AND pot_id=?",
                    (_dump(item["analysis"]), capture_id, item["pot_id"]),
                )

    def mark_retry(self, capture_id: str, error: str, *, max_attempts: int = 3,
                   available_at: float | None = None, now: float | None = None) -> str:
        timestamp = time.time() if now is None else float(now)
        row = self.db.execute("SELECT attempts FROM captures WHERE capture_id=?", (capture_id,)).fetchone()
        if row is None:
            raise KeyError(capture_id)
        status = "failed" if row["attempts"] >= max_attempts else "retry"
        self.db.execute(
            "UPDATE captures SET status=?,available_at=?,lease_owner=NULL,lease_until=NULL,"
            "last_error=?,updated_at=? WHERE capture_id=?",
            (status, timestamp + 60 if available_at is None else float(available_at),
             str(error)[:500], timestamp, capture_id),
        )
        return status

    def get_capture(self, capture_id: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT * FROM captures WHERE capture_id=?", (capture_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        raw_result = result.pop("result_json")
        result["result"] = json.loads(raw_result) if raw_result else None
        result["context"] = json.loads(result.pop("context_json"))
        result["observations"] = []
        rows = self.db.execute(
            "SELECT * FROM observations WHERE capture_id=? ORDER BY pot_id", (capture_id,)
        ).fetchall()
        for item in rows:
            value = dict(item)
            value["is_control"] = bool(value["is_control"])
            value["quality"] = json.loads(value.pop("quality_json"))
            raw_analysis = value.pop("analysis_json")
            value["analysis"] = json.loads(raw_analysis) if raw_analysis else None
            result["observations"].append(value)
        return result

    def latest_capture(self, *, succeeded_only: bool = False) -> dict[str, Any] | None:
        where = "WHERE status='succeeded'" if succeeded_only else ""
        row = self.db.execute(
            f"SELECT capture_id FROM captures {where} ORDER BY captured_at DESC LIMIT 1"
        ).fetchone()
        return None if row is None else self.get_capture(row["capture_id"])

    def list_captures(self, *, limit: int = 4, succeeded_only: bool = True) -> list[dict[str, Any]]:
        safe_limit = max(1, min(20, int(limit)))
        where = "WHERE status='succeeded'" if succeeded_only else ""
        rows = self.db.execute(
            f"SELECT capture_id FROM captures {where} ORDER BY captured_at DESC LIMIT ?",
            (safe_limit,),
        ).fetchall()
        return [self.get_capture(row["capture_id"]) for row in rows]

    def import_remote_capture(
        self, capture: Mapping[str, Any], observations: list[Mapping[str, Any]],
        *, overview_path: str | Path, now: float | None = None,
    ) -> None:
        """Idempotently import one validated Pi event into the cloud database."""
        if not observations:
            raise ValueError("a capture requires at least one observation")
        timestamp = time.time() if now is None else float(now)
        captured_at = float(capture["captured_at"])
        result = capture.get("result") or {
            "schema": "vision.capture.v1",
            "capture_id": capture["capture_id"],
            "observations": [
                {"pot_id": item["pot_id"], "analysis": item.get("analysis") or {}}
                for item in observations
            ],
        }
        with self.db:
            self.db.execute(
                "INSERT INTO captures(capture_id,captured_at,cycle_id,overview_path,status,"
                "current_light,required_light,attempts,available_at,result_json,updated_at,context_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(capture_id) DO UPDATE SET "
                "captured_at=excluded.captured_at,cycle_id=excluded.cycle_id,"
                "overview_path=excluded.overview_path,status='succeeded',"
                "current_light=excluded.current_light,required_light=excluded.required_light,"
                "result_json=excluded.result_json,updated_at=excluded.updated_at,"
                "context_json=excluded.context_json",
                (
                    capture["capture_id"], captured_at, capture.get("cycle_id", "unassigned"),
                    str(overview_path), "succeeded", capture.get("current_light"),
                    capture.get("required_light"), 0, captured_at, _dump(result), timestamp,
                    _dump(capture.get("context", {})),
                ),
            )
            for item in observations:
                self.db.execute(
                    "INSERT INTO observations(observation_id,capture_id,pot_id,material_id,"
                    "is_control,roi_id,image_path,quality_json,analysis_json) VALUES(?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(capture_id,pot_id) DO UPDATE SET material_id=excluded.material_id,"
                    "is_control=excluded.is_control,roi_id=excluded.roi_id,image_path=excluded.image_path,"
                    "quality_json=excluded.quality_json,analysis_json=excluded.analysis_json",
                    (
                        item.get("observation_id", f'{capture["capture_id"]}:{item["pot_id"]}'),
                        capture["capture_id"], item["pot_id"], item.get("material_id", ""),
                        int(bool(item.get("is_control"))), item.get("roi_id", item["pot_id"]),
                        str(overview_path), _dump(item.get("quality", {})),
                        _dump(item.get("analysis", {})),
                    ),
                )

    def lease_cloud_sync(self, worker_id: str, *, now: float | None = None,
                         lease_sec: int = 120) -> dict[str, Any] | None:
        """Lease the oldest analyzed capture not yet confirmed by the cloud."""
        timestamp = time.time() if now is None else float(now)
        with self.db:
            self.db.execute(
                "UPDATE cloud_sync SET status='retry',lease_until=NULL,updated_at=? "
                "WHERE status='leased' AND lease_until<?", (timestamp, timestamp),
            )
            row = self.db.execute(
                "SELECT c.capture_id FROM captures c LEFT JOIN cloud_sync s ON s.capture_id=c.capture_id "
                "WHERE c.status='succeeded' AND (s.capture_id IS NULL OR "
                "(s.status='retry' AND s.available_at<=?)) ORDER BY c.captured_at LIMIT 1",
                (timestamp,),
            ).fetchone()
            if row is None:
                return None
            self.db.execute(
                "INSERT INTO cloud_sync(capture_id,status,attempts,available_at,lease_until,updated_at) "
                "VALUES(?,'leased',1,?,?,?) ON CONFLICT(capture_id) DO UPDATE SET "
                "status='leased',attempts=attempts+1,lease_until=excluded.lease_until,"
                "updated_at=excluded.updated_at",
                (row["capture_id"], timestamp, timestamp + lease_sec, timestamp),
            )
        return self.get_capture(row["capture_id"])

    def mark_cloud_synced(self, capture_id: str, *, now: float | None = None) -> None:
        timestamp = time.time() if now is None else float(now)
        self.db.execute(
            "UPDATE cloud_sync SET status='succeeded',lease_until=NULL,last_error=NULL,"
            "synced_at=?,updated_at=? WHERE capture_id=?",
            (timestamp, timestamp, capture_id),
        )

    def mark_cloud_retry(self, capture_id: str, error: str, *, now: float | None = None,
                         max_backoff_sec: int = 3600) -> float:
        timestamp = time.time() if now is None else float(now)
        row = self.db.execute(
            "SELECT attempts FROM cloud_sync WHERE capture_id=?", (capture_id,)
        ).fetchone()
        attempts = int(row["attempts"]) if row else 1
        delay = min(max_backoff_sec, 30 * (2 ** min(attempts - 1, 7)))
        available_at = timestamp + delay
        self.db.execute(
            "UPDATE cloud_sync SET status='retry',available_at=?,lease_until=NULL,last_error=?,"
            "updated_at=? WHERE capture_id=?",
            (available_at, str(error)[:500], timestamp, capture_id),
        )
        return available_at

    def calls_today(self, *, now: float | None = None) -> int:
        timestamp = time.time() if now is None else float(now)
        day_start = timestamp - (timestamp % 86400)
        return int(self.db.execute(
            "SELECT COUNT(*) FROM api_usage WHERE used_at>=?", (day_start,)
        ).fetchone()[0])

    def record_usage(self, capture_id: str, image_bytes: int, *, now: float | None = None) -> None:
        self.db.execute(
            "INSERT INTO api_usage(used_at,capture_id,image_bytes) VALUES(?,?,?)",
            (time.time() if now is None else float(now), capture_id, int(image_bytes)),
        )
