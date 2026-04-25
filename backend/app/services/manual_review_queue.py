"""
Очередь ручной проверки: провальные кейсы для разбора. push, list_open, mark_resolved, assign.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from app.services.quality_models import FailureCase


def _queue_dir() -> Path:
    try:
        base = Path(__file__).resolve().parent.parent.parent / "data" / "quality"
        base.mkdir(parents=True, exist_ok=True)
        return base
    except Exception:
        return Path("/tmp") / "quality_fallback"


QUEUE_FILE = "manual_review_queue.jsonl"
RESOLVED_FILE = "manual_review_resolved.jsonl"


class ManualReviewQueue:
    def __init__(self, base_dir: Optional[Path] = None):
        self._base = base_dir or _queue_dir()
        self._path = self._base / QUEUE_FILE
        self._resolved_path = self._base / RESOLVED_FILE

    def _read_all(self, path: Path) -> List[Dict[str, Any]]:
        out = []
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                out.append(json.loads(line))
                            except Exception:
                                pass
        except Exception:
            pass
        return out

    def _append(self, path: Path, record: Dict[str, Any]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def push_case(self, failure_case: FailureCase) -> str:
        case_id = failure_case.case_id or f"mr_{uuid.uuid4().hex[:12]}"
        record = failure_case.to_dict()
        record["case_id"] = case_id
        record["resolution_status"] = "open"
        record["assignee"] = None
        self._append(self._path, record)
        return case_id

    def list_open_cases(self, limit: int = 100) -> List[Dict[str, Any]]:
        resolved_ids = {r.get("case_id") for r in self._read_all(self._resolved_path) if r.get("case_id")}
        rows = self._read_all(self._path)
        open_rows = [r for r in rows if r.get("case_id") not in resolved_ids and r.get("resolution_status") != "resolved"]
        return open_rows[-limit:][::-1]

    def mark_case_resolved(self, case_id: str, note: Optional[str] = None) -> bool:
        rows = self._read_all(self._path)
        found = None
        for r in rows:
            if r.get("case_id") == case_id:
                found = r
                break
        if not found:
            return False
        found["resolution_status"] = "resolved"
        found["resolved_note"] = note
        self._append(self._resolved_path, found)
        return True

    def assign_case(self, case_id: str, assignee: str) -> bool:
        rows = self._read_all(self._path)
        for r in rows:
            if r.get("case_id") == case_id:
                r["assignee"] = assignee
                self._append(self._path, {**r, "assignee": assignee})
                return True
        return False
