"""Prediction ledger: append-only SQLite store written off the hot path.

Best-effort telemetry, not an audit log. Writes go through a bounded queue drained by a
background thread; if the queue is full the record is dropped and counted, so a prediction is
never delayed by persistence. The default store is ``:memory:`` (lost on restart): point
``CASCADE_LEDGER`` at a file for durability. ``close()`` waits briefly; queued rows can be lost.
"""

from __future__ import annotations

import json
import queue
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, shipment_id TEXT, as_of REAL, model_version TEXT,
  checkpoint INTEGER, lane_id TEXT, delay_p10 REAL, delay_p50 REAL, delay_p90 REAL, p_late REAL,
  degraded INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_pred_ship ON predictions(shipment_id, as_of);
CREATE TABLE IF NOT EXISTS alerts (
  alert_id TEXT PRIMARY KEY, shipment_id TEXT, rule TEXT, severity TEXT, created_at REAL,
  message TEXT, status TEXT DEFAULT 'open');
CREATE TABLE IF NOT EXISTS promises (
  shipment_id TEXT, promise_h REAL, set_at REAL, reason TEXT, changes INTEGER);
CREATE TABLE IF NOT EXISTS actuals (shipment_id TEXT PRIMARY KEY, total_delay_h REAL);
"""


@dataclass
class LedgerStats:
    written: int = 0
    dropped: int = 0


class Ledger:
    def __init__(self, path: Path | str = ":memory:", max_queue: int = 10_000):
        self.path = str(path)
        self._q: queue.Queue = queue.Queue(maxsize=max_queue)
        self.stats = LedgerStats()
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._drain, daemon=True, name="ledger-writer")
        self._thread.start()

    # ---- writes (non-blocking) -------------------------------------------------------
    def submit(self, table: str, row: dict) -> bool:
        try:
            self._q.put_nowait((table, row))
            return True
        except queue.Full:
            self.stats.dropped += 1
            return False

    def _drain(self) -> None:
        while not self._stop.is_set() or not self._q.empty():
            try:
                table, row = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            cols = ",".join(row)
            marks = ",".join("?" for _ in row)
            verb = "INSERT OR REPLACE" if table in ("alerts", "actuals") else "INSERT"
            with self._lock:
                self._conn.execute(
                    f"{verb} INTO {table} ({cols}) VALUES ({marks})",
                    [json.dumps(v) if isinstance(v, dict | list) else v for v in row.values()],
                )
                self._conn.commit()
            self.stats.written += 1

    def flush(self, timeout: float = 5.0) -> None:
        import time

        t0 = time.time()
        while not self._q.empty() and time.time() - t0 < timeout:
            time.sleep(0.01)
        time.sleep(0.05)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._conn.close()

    # ---- reads -------------------------------------------------------------------------
    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def open_alerts(self, limit: int = 200) -> list[dict]:
        return self.query(
            "SELECT * FROM alerts WHERE status='open' ORDER BY "
            "CASE severity WHEN 'critical' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END, created_at DESC LIMIT ?",
            (limit,),
        )

    def accuracy(self) -> list[dict]:
        """Live accuracy: join every logged prediction to the realised delay."""
        return self.query(
            "SELECT p.checkpoint AS checkpoint, COUNT(*) AS n, "
            "AVG(ABS(p.delay_p50 - a.total_delay_h)) AS mae, "
            "AVG(CASE WHEN a.total_delay_h BETWEEN p.delay_p10 AND p.delay_p90 THEN 1.0 ELSE 0.0 END) AS coverage "
            "FROM predictions p JOIN actuals a USING (shipment_id) GROUP BY p.checkpoint ORDER BY p.checkpoint"
        )

    def lane_trust(self) -> list[dict]:
        return self.query(
            "SELECT p.lane_id AS lane_id, COUNT(*) AS n, AVG(ABS(p.delay_p50 - a.total_delay_h)) AS mae "
            "FROM predictions p JOIN actuals a USING (shipment_id) GROUP BY p.lane_id"
        )
