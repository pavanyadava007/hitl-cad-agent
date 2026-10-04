"""Append-only, hash-chained audit log (JSONL).

Each record stores `prev` (sha256 of the previous record line) and `hash`
(sha256 over the canonical JSON of the record without `hash`). Editing,
deleting or reordering any line breaks the chain and `verify` reports where.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

GENESIS = "0" * 64


def _digest(rec: dict) -> str:
    body = {k: v for k, v in rec.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.prev = GENESIS
        self.seq = 0
        if self.path.exists():
            lines = [ln for ln in self.path.read_text().splitlines() if ln.strip()]
            if lines:
                last = json.loads(lines[-1])
                self.prev, self.seq = last["hash"], last["seq"] + 1

    def append(self, event: str, **data) -> dict:
        rec = {"seq": self.seq, "ts": round(time.time(), 3), "event": event, "data": data, "prev": self.prev}
        rec["hash"] = _digest(rec)
        with self.path.open("a") as f:
            f.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
        self.prev, self.seq = rec["hash"], self.seq + 1
        return rec


def verify(path: str | Path) -> tuple[bool, str]:
    prev = GENESIS
    lines = [ln for ln in Path(path).read_text().splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            return False, f"line {i + 1}: not valid JSON"
        if rec.get("seq") != i:
            return False, f"line {i + 1}: sequence number {rec.get('seq')} != {i} (deleted or reordered record)"
        if rec.get("prev") != prev:
            return False, f"line {i + 1}: prev hash does not match previous record"
        if _digest(rec) != rec.get("hash"):
            return False, f"line {i + 1}: record content was modified (hash mismatch)"
        prev = rec["hash"]
    return True, f"ok: {len(lines)} records, chain intact"
