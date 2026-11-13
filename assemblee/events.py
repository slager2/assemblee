"""Append-only run event log (contract: docs/events.md)."""
import json
import threading
import time
from pathlib import Path


class EventLog:
    def __init__(self, run_dir: Path):
        self.dir = Path(run_dir)
        (self.dir / "frames").mkdir(parents=True, exist_ok=True)
        (self.dir / "output").mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "events.jsonl"
        self.seq = 0
        if self.path.exists():
            self.seq = sum(1 for _ in self.path.open(encoding="utf-8"))
        self.lock = threading.Lock()

    def emit(self, type_, **data):
        with self.lock:
            self.seq += 1
            line = json.dumps({"seq": self.seq, "ts": round(time.time(), 3), "type": type_, "data": data}, ensure_ascii=False, default=str)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        return self.seq

    def rel(self, path) -> str:
        return str(Path(path).resolve().relative_to(self.dir.resolve()))
