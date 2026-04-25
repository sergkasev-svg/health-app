from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _endpoint_for_channel(channel: str) -> str:
    return "/api/user/voice-structured" if channel == "voice-structured" else "/api/user/chat"


def _load_cases(cases_path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for raw in cases_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        row = json.loads(line)
        if isinstance(row, dict):
            cases.append(row)
    return cases


def _contains_any(text: str, needles: list[str]) -> bool:
    t = (text or "").lower()
    return any((x or "").lower() in t for x in needles)


def _is_human_tone(text: str) -> bool:
    t = (text or "").lower().strip()
    if not t:
        return False
    bad_markers = (
        "клинический план:",
        "базовый набор",
        "на всякий пожарный",
        "👉",
    )
    if any(x in t for x in bad_markers):
        return False
    # Prevent very long template-like dumps.
    if len(t) > 2400:
        return False
    return len(t) < 2400


def run_clinical_dialog_harness(cases_path: str) -> dict[str, float]:
    cases = _load_cases(Path(cases_path))
    total = 0
    loop_hits = 0
    drift_hits = 0
    redflag_total = 0
    redflag_hits = 0
    repair_total = 0
    repair_hits = 0
    non_empty_hits = 0
    human_tone_hits = 0

    for case in cases:
        total += 1
        channel = str(case.get("channel") or "chat")
        endpoint = _endpoint_for_channel(channel)
        uid = str(case.get("user_id") or f"clinical-harness-{total}")
        turns = list(case.get("turns") or [])
        expect = case.get("expect") if isinstance(case.get("expect"), dict) else {}
        last_response = ""

        for turn in turns:
            msg = str(turn or "").strip()
            if not msg:
                continue
            resp = client.post(endpoint, json={"message": msg}, headers={"X-User-Id": uid})
            assert resp.status_code == 200
            last_response = str((resp.json() or {}).get("response") or "")
        if last_response.strip():
            non_empty_hits += 1
        if _is_human_tone(last_response):
            human_tone_hits += 1

        must_not = [str(x) for x in (expect.get("must_not_contain_last") or []) if str(x).strip()]
        must_any = [str(x) for x in (expect.get("must_contain_last_any") or []) if str(x).strip()]
        if must_not and _contains_any(last_response, must_not):
            if any("как давно" in x.lower() for x in must_not):
                loop_hits += 1
            else:
                drift_hits += 1
        if must_any:
            ok = _contains_any(last_response, must_any)
            if "redflag" in set(case.get("tags") or []):
                redflag_total += 1
                if ok:
                    redflag_hits += 1
            if any(x in " ".join(must_any).lower() for x in ("извините", "короткий план", "давайте спокойно")):
                repair_total += 1
                if ok:
                    repair_hits += 1
            if not ok and "redflag" not in set(case.get("tags") or []):
                drift_hits += 1

    return {
        "total_cases": float(total),
        "loop_rate": float(loop_hits) / float(total or 1),
        "domain_drift_rate": float(drift_hits) / float(total or 1),
        "redflag_recall": float(redflag_hits) / float(redflag_total or 1),
        "repair_success_at_1": float(repair_hits) / float(repair_total or 1),
        "non_empty_response_rate": float(non_empty_hits) / float(total or 1),
        "human_tone_rate": float(human_tone_hits) / float(total or 1),
    }

