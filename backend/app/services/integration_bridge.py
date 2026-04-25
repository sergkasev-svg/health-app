from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_PROJECT_ROOT = _BACKEND_ROOT.parent
_ROOT_BRIDGE_FILE = _PROJECT_ROOT / "integration_bridge.py"


def _load_root_bridge_module():
    if not _ROOT_BRIDGE_FILE.is_file():
        return None
    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))
    spec = importlib.util.spec_from_file_location("_root_integration_bridge", _ROOT_BRIDGE_FILE)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def get_bridge():
    module = _load_root_bridge_module()
    if module is None:
        return None
    bridge_factory = getattr(module, "get_bridge", None)
    if bridge_factory is None:
        return None
    try:
        return bridge_factory()
    except Exception:
        return None


def build_bridge_complaint_protocol(query: str, *, top_k: int = 3) -> dict[str, Any] | None:
    bridge = get_bridge()
    if bridge is None:
        return None
    try:
        routed = bridge.search(query, top_k=top_k) or {}
    except Exception:
        return None
    top_matches = routed.get("top_matches") or []
    if not isinstance(top_matches, list) or not top_matches:
        return None
    best = top_matches[0] if isinstance(top_matches[0], dict) else {}
    if not best:
        return None
    case_id = str(best.get("case_id") or "").strip()
    v2_case: dict[str, Any] = {}
    if case_id:
        try:
            v2_case = bridge.get_v2_case(case_id) or {}
        except Exception:
            v2_case = {}
    complaint = str(best.get("title") or v2_case.get("title") or "").strip()
    if not complaint:
        return None
    questions = [str(x).strip() for x in (best.get("questions") or []) if str(x).strip()]
    actions = [str(x).strip() for x in (best.get("actions") or []) if str(x).strip()]
    emergency = [str(x).strip() for x in (best.get("emergency") or []) if str(x).strip()]
    tests = [str(x).strip() for x in (v2_case.get("tests") or []) if str(x).strip()]
    return {
        "id": case_id or f"bridge_{complaint.lower().replace(' ', '_')[:40]}",
        "complaint": complaint,
        "name": complaint,
        "category": str(best.get("category") or v2_case.get("category") or "Общая медицина").strip(),
        "description": str(best.get("reason") or v2_case.get("reason") or "").strip(),
        "anamnesis_questions": questions,
        "must_ask_questions": questions[:3],
        "optional_questions": questions[3:],
        "red_flags": emergency,
        "red_flags_specific": emergency,
        "suggested_labs": tests,
        "likely_labs": tests,
        "first_line_non_drug_steps": actions,
        "source": "clinical_engine_bridge",
        "urgency_level": "urgent" if emergency else "",
        "bridge_route": routed,
    }


def bridge_status() -> dict[str, Any]:
    bridge = get_bridge()
    if bridge is None:
        return {"enabled": False}
    try:
        status = bridge.status() or {}
    except Exception:
        status = {}
    status["enabled"] = True
    return status

