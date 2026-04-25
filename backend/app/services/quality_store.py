"""
Хранилище качества: JSONL-файлы, safe fallback при ошибках. Не падать в проде.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from app.services.quality_models import (
    AdminDashboardSnapshot,
    ClinicalQualityEvent,
    FailureCase,
    FunnelMetric,
)


def _quality_dir() -> Path:
    try:
        base = Path(__file__).resolve().parent.parent.parent / "data" / "quality"
        base.mkdir(parents=True, exist_ok=True)
        return base
    except Exception:
        return Path(os.environ.get("TEMP", "/tmp")) / "quality_fallback"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class QualityStore:
    EVENTS_FILE = "clinical_events.jsonl"
    FAILURES_FILE = "failure_cases.jsonl"
    FUNNEL_FILE = "funnel_metrics.jsonl"

    def __init__(self, base_dir: Optional[Path] = None):
        self._base = base_dir or _quality_dir()
        self._events_path = self._base / self.EVENTS_FILE
        self._failures_path = self._base / self.FAILURES_FILE
        self._funnel_path = self._base / self.FUNNEL_FILE

    def _append_jsonl(self, path: Path, record: Dict[str, Any]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def log_clinical_event(self, event: ClinicalQualityEvent) -> None:
        if not event:
            return
        try:
            self._append_jsonl(self._events_path, event.to_dict())
        except Exception:
            pass

    def log_failure_case(self, failure: FailureCase) -> None:
        if not failure:
            return
        try:
            self._append_jsonl(self._failures_path, failure.to_dict())
        except Exception:
            pass

    def log_funnel_metric(self, metric: FunnelMetric) -> None:
        if not metric:
            return
        try:
            self._append_jsonl(self._funnel_path, metric.to_dict())
        except Exception:
            pass

    def _read_jsonl(self, path: Path, limit: int, filters: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            if not path.exists():
                return []
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if filters:
                            ok = True
                            for k, v in filters.items():
                                if obj.get(k) != v:
                                    ok = False
                                    break
                            if not ok:
                                continue
                        out.append(obj)
                        if len(out) >= limit:
                            break
                    except Exception:
                        continue
            out.reverse()
            return out[:limit]
        except Exception:
            return []

    def get_events(self, limit: int = 100, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        return self._read_jsonl(self._events_path, limit, filters)

    def get_failures(self, limit: int = 100, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        return self._read_jsonl(self._failures_path, limit, filters)

    def get_funnel_metrics(self, limit: int = 1000, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        return self._read_jsonl(self._funnel_path, limit, filters)


def _generate_id(prefix: str = "ev") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
