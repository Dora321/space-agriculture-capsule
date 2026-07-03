"""Non-blocking latest-value bridge from the UART loop to SQLite."""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Mapping


class TelemetrySink:
    def __init__(self, store: Any, *, clock=time.time):
        self.store = store
        self.clock = clock
        self.queue: queue.Queue[tuple[dict[str, Any], float] | None] = queue.Queue(maxsize=1)
        self.thread = threading.Thread(target=self._run, name="vision-telemetry", daemon=True)
        self.thread.start()

    def submit(self, report: Mapping[str, Any]) -> None:
        item = (dict(report), self.clock())
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
            self.queue.put_nowait(item)

    def _run(self) -> None:
        while True:
            item = self.queue.get()
            if item is None:
                return
            report, received_at = item
            try:
                self.store.save_telemetry(report, received_at=received_at)
            except Exception as exc:
                print("[GW] vision telemetry save failed:", exc)

    def close(self) -> None:
        try:
            self.queue.put_nowait(None)
        except queue.Full:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
            self.queue.put_nowait(None)
        self.thread.join(timeout=2)
