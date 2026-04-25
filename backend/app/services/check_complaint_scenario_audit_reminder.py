from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _state_file() -> Path:
    return Path("./quality_artifacts/complaint_scenario_audit_state.json")


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def main() -> None:
    path = _state_file()
    if not path.exists():
        print("REMINDER_DUE | reason=no_previous_run | now=" + _now_iso())
        return

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        print("REMINDER_DUE | reason=state_read_failed | now=" + _now_iso())
        return

    last_run_raw = str(payload.get("last_run_at") or "").strip()
    if not last_run_raw:
        print("REMINDER_DUE | reason=missing_last_run | now=" + _now_iso())
        return

    try:
        last_run = datetime.fromisoformat(last_run_raw)
    except Exception:
        print("REMINDER_DUE | reason=invalid_last_run | now=" + _now_iso())
        return

    next_due = last_run + timedelta(days=3)
    now = datetime.now(tz=timezone.utc)
    if now >= next_due:
        print(f"REMINDER_DUE | last_run={last_run.isoformat()} | next_due={next_due.isoformat()}")
        return
    print(f"REMINDER_NOT_DUE | last_run={last_run.isoformat()} | next_due={next_due.isoformat()} | now={now.isoformat()}")


if __name__ == "__main__":
    main()

