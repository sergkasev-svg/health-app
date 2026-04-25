from __future__ import annotations

from typing import Any, Dict, List


def _dedup(items: List[str], limit: int = 999) -> List[str]:
    out: List[str] = []
    seen = set()
    for x in items or []:
        s = str(x or "").strip()
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def empty_report(report_type: str = "auto", group: str = "mixed") -> Dict[str, Any]:
    return {
        "report_type": report_type,
        "group": group,
        "summary": [],
        "findings": [],
        "interpretation": [],
        "hypotheses": [],
        "risks": [],
        "what_to_add": [],
        "plan": {"priority_1": [], "priority_2": [], "tests": []},
        "avoid": [],
        "treatment_directions": [],
        "supplements": [],
        "nutrition": [],
        "activity": [],
        "red_flags": [],
    }


def finalize_report(report: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(report)
    for key in (
        "summary",
        "findings",
        "interpretation",
        "risks",
        "what_to_add",
        "avoid",
        "treatment_directions",
        "supplements",
        "nutrition",
        "activity",
        "red_flags",
    ):
        out[key] = _dedup(out.get(key) or [], limit=30)
    plan = out.get("plan") or {}
    out["plan"] = {
        "priority_1": _dedup(plan.get("priority_1") or [], limit=20),
        "priority_2": _dedup(plan.get("priority_2") or [], limit=20),
        "tests": _dedup(plan.get("tests") or [], limit=25),
    }
    # hypotheses: dedup by id/label
    unique_h = []
    seen_h = set()
    for h in out.get("hypotheses") or []:
        if not isinstance(h, dict):
            continue
        key = (str(h.get("id") or "").strip().lower(), str(h.get("label") or "").strip().lower())
        if key in seen_h:
            continue
        seen_h.add(key)
        unique_h.append(h)
    out["hypotheses"] = unique_h[:20]
    return out


def _merge_autolink_enhance(report: Dict[str, Any], knowledge_autolink: Dict[str, Any]) -> Dict[str, Any]:
    auto = knowledge_autolink if isinstance(knowledge_autolink, dict) else {}
    enhance = auto.get("brain_enhance") if isinstance(auto.get("brain_enhance"), dict) else {}
    if not enhance:
        return report

    out = dict(report)
    out["knowledge_sources"] = _dedup([str(x) for x in (auto.get("knowledge_sources") or [])], limit=20)
    out["knowledge_topics"] = _dedup([str(x) for x in (auto.get("knowledge_topics") or [])], limit=30)

    # Priority: autolink hints go first in interpretation/what_to_add, then scenario data.
    out["interpretation"] = _dedup(
        [str(x) for x in (enhance.get("interpretation") or [])]
        + [str(x) for x in (out.get("interpretation") or [])],
        limit=30,
    )
    out["what_to_add"] = _dedup(
        [str(x) for x in (enhance.get("what_to_add") or [])]
        + [str(x) for x in (out.get("what_to_add") or [])],
        limit=30,
    )

    for key in ("nutrition", "supplements", "activity", "red_flags"):
        out[key] = _dedup(
            [str(x) for x in (out.get(key) or [])] + [str(x) for x in (enhance.get(key) or [])],
            limit=30,
        )

    # Promote autolink additions into plan with controlled limits.
    plan = out.get("plan") or {}
    out["plan"] = {
        "priority_1": _dedup(
            [str(x) for x in (enhance.get("interpretation") or [])[:2]]
            + [str(x) for x in (plan.get("priority_1") or [])],
            limit=20,
        ),
        "priority_2": _dedup(
            [str(x) for x in (plan.get("priority_2") or [])]
            + [str(x) for x in (enhance.get("activity") or [])[:2]],
            limit=20,
        ),
        "tests": _dedup(
            [str(x) for x in (enhance.get("what_to_add") or [])]
            + [str(x) for x in (plan.get("tests") or [])],
            limit=25,
        ),
    }

    # Convert autolink hypothesis hints into canonical hypothesis objects.
    hyp = list(out.get("hypotheses") or [])
    auto_h = [str(x or "").strip() for x in (enhance.get("hypotheses") or []) if str(x or "").strip()]
    for i, label in enumerate(auto_h):
        hyp.append({"id": f"autolink_h_{i+1}", "label": label, "confidence": "moderate"})
    out["hypotheses"] = hyp
    return out


def build_full_report(
    scenarios: List[Dict[str, Any]],
    knowledge_autolink: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    report = empty_report("auto", "mixed")
    for s in scenarios or []:
        report["summary"] += s.get("summary", []) or []
        report["findings"] += s.get("summary", []) or []
        report["interpretation"] += s.get("interpretation", []) or []
        report["hypotheses"] += s.get("hypotheses", []) or []
        report["what_to_add"] += s.get("what_to_add", []) or []
        report["risks"] += s.get("risks", []) or []
        report["avoid"] += s.get("avoid", []) or []
        report["treatment_directions"] += s.get("treatment_directions", []) or []
        report["supplements"] += s.get("supplements", []) or []
        report["nutrition"] += s.get("nutrition", []) or []
        report["activity"] += s.get("activity", []) or []
        report["red_flags"] += s.get("red_flags", []) or []
        if "plan" in s and isinstance(s["plan"], dict):
            report["plan"]["priority_1"] += s["plan"].get("priority_1", []) or []
            report["plan"]["priority_2"] += s["plan"].get("priority_2", []) or []
            report["plan"]["tests"] += s["plan"].get("tests", []) or []
    if knowledge_autolink:
        report = _merge_autolink_enhance(report, knowledge_autolink)
    return finalize_report(report)
