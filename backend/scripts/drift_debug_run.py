from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient
BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
from app.main import app

CASES = BACKEND / "tests" / "clinical" / "cases_clinical_v1.jsonl"
OUT = BACKEND / "tests" / "clinical" / "reports" / "drift_debug_latest.json"


def _endpoint(channel: str) -> str:
    return "/api/user/voice-structured" if channel == "voice-structured" else "/api/user/chat"


def _contains_any(text: str, needles: list[str]) -> bool:
    t = (text or "").lower()
    return any((n or "").lower() in t for n in needles)


def main() -> int:
    rows = [json.loads(x) for x in CASES.read_text(encoding="utf-8").splitlines() if x.strip()]
    client = TestClient(app)
    out: list[dict] = []
    for case in rows:
        expect = case.get("expect") if isinstance(case.get("expect"), dict) else {}
        if not expect:
            continue
        uid = str(case.get("user_id") or case.get("id") or "debug")
        ep = _endpoint(str(case.get("channel") or "chat"))
        last = ""
        for turn in case.get("turns") or []:
            msg = str(turn).strip()
            if not msg:
                continue
            resp = client.post(ep, json={"message": msg}, headers={"X-User-Id": uid})
            resp.raise_for_status()
            last = str((resp.json() or {}).get("response") or "")

        must_not = [str(x) for x in (expect.get("must_not_contain_last") or []) if str(x).strip()]
        must_any = [str(x) for x in (expect.get("must_contain_last_any") or []) if str(x).strip()]
        tags = set(case.get("tags") or [])
        drift = False
        reasons: list[str] = []
        if must_not and _contains_any(last, must_not):
            drift = True
            reasons.append("must_not_hit")
        if must_any:
            ok = _contains_any(last, must_any)
            if not ok and "redflag" not in tags:
                drift = True
                reasons.append("must_any_miss_non_redflag")
            if not ok and "redflag" in tags:
                reasons.append("redflag_miss")
        out.append({"id": case["id"], "drift": drift, "reasons": reasons, "last": last})

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    drift_ids = [x["id"] for x in out if x["drift"]]
    print("expect_cases", len(out))
    print("drift_cases", len(drift_ids))
    print("drift_ids", drift_ids)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
