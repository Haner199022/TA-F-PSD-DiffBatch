"""Background worker for the GUI.

Wraps a single thread that runs a job (analyze / run_batch / run_custom_script),
puts the result onto a queue.Queue the GUI thread polls. Only one job at a
time; callers check `.alive()` before starting a new one.
"""
from __future__ import annotations

import queue
import threading


class WorkerJob:
    """Single-slot job runner. Posts ("status", ...), ("done", result), or
    ("error", message) tuples onto the supplied queue."""

    def __init__(self, q: queue.Queue):
        self.q = q
        self.thread: threading.Thread | None = None

    def start(self, target, *args, **kwargs):
        if self.thread and self.thread.is_alive():
            raise RuntimeError("a job is already running")

        def run():
            try:
                self.q.put(("status", "running…"))
                result = target(*args, **kwargs)
                self.q.put(("done", result))
            except Exception as exc:
                self.q.put(("error", str(exc)))

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive())
