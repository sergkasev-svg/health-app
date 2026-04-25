"""Runtime analytics for complaint, routing, and OpenAI cost visibility."""
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from app.services.release_gate_policy import get_release_gate_policy

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_QUALITY_DIR = _BACKEND_DIR / "data" / "quality"
_EVENTS_FILE = _QUALITY_DIR / "runtime_analytics_events.json"
_KNOWLEDGE_QUEUE_FILE = _QUALITY_DIR / "knowledge_flywheel_queue.json"
_DAY_SECONDS = 86400


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _filter_since(items: list[dict[str, Any]], seconds: int) -> list[dict[str, Any]]:
    cutoff = time.time() - max(0, int(seconds))
    return [it for it in items if float(it.get("created_at") or 0) >= cutoff]


def _simple_rollup(items: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(items)
    llm_calls = sum(1 for it in items if bool(it.get("llm_used")))
    offline_saved = sum(1 for it in items if str(it.get("source") or "") in {"offline_priority", "offline_fallback", "red_flag_guard"})
    estimated_cost = sum(float(it.get("estimated_cost_usd") or 0.0) for it in items)
    prompt_tokens = sum(int(it.get("prompt_tokens") or 0) for it in items)
    completion_tokens = sum(int(it.get("completion_tokens") or 0) for it in items)
    summary = {
        "total_events": total,
        "llm_calls": llm_calls,
        "offline_saved_calls": offline_saved,
        "llm_share": round((llm_calls / total), 3) if total else 0.0,
        "offline_share": round((offline_saved / total), 3) if total else 0.0,
        "estimated_cost_usd_total": round(estimated_cost, 6),
        "prompt_tokens_total": prompt_tokens,
        "completion_tokens_total": completion_tokens,
    }


def _daily_rollup(items: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    now = time.time()
    buckets: dict[str, dict[str, Any]] = {}
    for n in range(max(1, int(days))):
        ts = now - (n * _DAY_SECONDS)
        key = time.strftime("%Y-%m-%d", time.localtime(ts))
        buckets[key] = {"date": key, "llm_calls": 0, "offline_saved_calls": 0, "estimated_cost_usd_total": 0.0}
    for it in items:
        ts = float(it.get("created_at") or 0)
        key = time.strftime("%Y-%m-%d", time.localtime(ts))
        if key not in buckets:
            continue
        if bool(it.get("llm_used")):
            buckets[key]["llm_calls"] += 1
        if str(it.get("source") or "") in {"offline_priority", "offline_fallback", "red_flag_guard"}:
            buckets[key]["offline_saved_calls"] += 1
        buckets[key]["estimated_cost_usd_total"] += float(it.get("estimated_cost_usd") or 0.0)
    out = list(buckets.values())
    out.sort(key=lambda x: x["date"])
    for row in out:
        row["estimated_cost_usd_total"] = round(float(row.get("estimated_cost_usd_total") or 0.0), 6)
    return out


def _complaint_quality_score(*, count: int, llm_calls: int, offline_calls: int, approved_cases: int) -> int:
    if count <= 0:
        return 0
    offline_share = float(offline_calls) / float(count)
    llm_share = float(llm_calls) / float(count)
    offline_component = offline_share * 40.0
    approval_component = min(float(approved_cases), 5.0) / 5.0 * 30.0
    volume_component = min(float(count), 10.0) / 10.0 * 15.0
    independence_component = max(0.0, 1.0 - llm_share) * 15.0
    return int(round(min(100.0, offline_component + approval_component + volume_component + independence_component)))


def _maturity_label(score: int) -> str:
    if score >= 80:
        return "strong"
    if score >= 55:
        return "growing"
    return "weak"


def _build_release_quality_gate(complaint_stats: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    policy = get_release_gate_policy()
    core_targets = set(policy.get("core_targets") or [])
    weak_threshold = int(policy.get("weak_core_quality_threshold") or 40)
    min_events_warn = int(policy.get("min_total_events_warn") or 10)
    llm_share_warn_threshold = float(policy.get("llm_share_warn_threshold") or 0.8)
    stats_map = {str(x.get("complaint") or ""): x for x in complaint_stats}
    missing = sorted([name for name in core_targets if name not in stats_map])
    weak_core = [
        {
            "complaint": name,
            "quality_score": int((stats_map.get(name) or {}).get("quality_score") or 0),
        }
        for name in core_targets
        if name in stats_map and int((stats_map.get(name) or {}).get("quality_score") or 0) < weak_threshold
    ]
    llm_share = float(summary.get("llm_share") or 0.0)
    total_events = int(summary.get("total_events") or 0)

    issues: list[str] = []
    status = "pass"
    if total_events < min_events_warn:
        status = "warn"
        issues.append("Недостаточно данных для уверенного quality gate.")
    if missing:
        status = "warn" if status != "fail" else status
        issues.append("Нет покрытия некоторых ключевых жалоб в аналитике: " + ", ".join(missing))
    if weak_core:
        status = "fail"
        issues.append("Ключевые жалобы с низким quality score: " + ", ".join(x["complaint"] for x in weak_core))
    if llm_share > llm_share_warn_threshold:
        status = "warn" if status != "fail" else status
        issues.append("Слишком высокая зависимость от LLM по общему трафику.")

    return {
        "status": status,
        "issues": issues,
        "core_targets": sorted(core_targets),
        "missing_core_complaints": missing,
        "weak_core_complaints": weak_core,
        "llm_share": llm_share,
        "total_events": total_events,
        "policy": policy,
    }


def record_runtime_event(
    *,
    source: str,
    llm_used: bool,
    model_used: str | None,
    protocol_source: str | None,
    complaint: str | None,
    cluster: str | None,
    severity: str | None,
    prompt_chars: int = 0,
    response_chars: int = 0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    estimated_cost_usd: float = 0.0,
) -> dict[str, Any]:
    data = _read_json(_EVENTS_FILE)
    items = list(data.get("items") or [])
    items.append(
        {
            "created_at": round(time.time(), 2),
            "source": str(source or ""),
            "llm_used": bool(llm_used),
            "model_used": str(model_used or ""),
            "protocol_source": str(protocol_source or ""),
            "complaint": str(complaint or "")[:300],
            "cluster": str(cluster or ""),
            "severity": str(severity or ""),
            "prompt_chars": int(prompt_chars or 0),
            "response_chars": int(response_chars or 0),
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "total_tokens": int(total_tokens or 0),
            "estimated_cost_usd": float(estimated_cost_usd or 0.0),
        }
    )
    data["items"] = items[-5000:]
    _write_json(_EVENTS_FILE, data)
    return data["items"][-1]


def get_runtime_overview(limit: int = 1000) -> dict[str, Any]:
    data = _read_json(_EVENTS_FILE)
    queue = _read_json(_KNOWLEDGE_QUEUE_FILE)
    items = list(data.get("items") or [])[-max(1, int(limit)) :]
    reviewed_cases = list(queue.get("items") or [])
    total = len(items)
    source_counts = Counter()
    model_counts = Counter()
    cluster_counts = Counter()
    cluster_llm_counts = Counter()
    cluster_offline_counts = Counter()
    complaint_counts = Counter()
    severity_counts = Counter()
    complaint_llm_counts = Counter()
    complaint_offline_counts = Counter()
    approved_counts = Counter()
    complaint_cluster_map: dict[str, str] = {}
    llm_calls = 0
    offline_saved = 0
    prompt_chars = 0
    response_chars = 0
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    estimated_cost_usd = 0.0

    for row in reviewed_cases:
        if str(row.get("review_status") or "").strip().lower() == "approved":
            complaint = str(row.get("complaint") or row.get("chief_complaint") or "").strip()
            if complaint:
                approved_counts[complaint] += 1

    for it in items:
        source_counts[str(it.get("source") or "")] += 1
        model = str(it.get("model_used") or "").strip()
        if model:
            model_counts[model] += 1
        cluster = str(it.get("cluster") or "").strip()
        if cluster:
            cluster_counts[cluster] += 1
            if bool(it.get("llm_used")):
                cluster_llm_counts[cluster] += 1
            if str(it.get("source") or "") in {"offline_priority", "offline_fallback", "red_flag_guard"}:
                cluster_offline_counts[cluster] += 1
        complaint = str(it.get("complaint") or "").strip()
        if complaint:
            complaint_counts[complaint] += 1
            if cluster and complaint not in complaint_cluster_map:
                complaint_cluster_map[complaint] = cluster
            if bool(it.get("llm_used")):
                complaint_llm_counts[complaint] += 1
            if str(it.get("source") or "") in {"offline_priority", "offline_fallback", "red_flag_guard"}:
                complaint_offline_counts[complaint] += 1
        severity = str(it.get("severity") or "").strip()
        if severity:
            severity_counts[severity] += 1
        if bool(it.get("llm_used")):
            llm_calls += 1
        if str(it.get("source") or "") in {"offline_priority", "offline_fallback", "red_flag_guard"}:
            offline_saved += 1
        prompt_chars += int(it.get("prompt_chars") or 0)
        response_chars += int(it.get("response_chars") or 0)
        prompt_tokens += int(it.get("prompt_tokens") or 0)
        completion_tokens += int(it.get("completion_tokens") or 0)
        total_tokens += int(it.get("total_tokens") or 0)
        estimated_cost_usd += float(it.get("estimated_cost_usd") or 0.0)

    complaint_stats = []
    for complaint, count in complaint_counts.most_common(20):
        llm = int(complaint_llm_counts.get(complaint) or 0)
        offline = int(complaint_offline_counts.get(complaint) or 0)
        approved = int(approved_counts.get(complaint) or 0)
        score = _complaint_quality_score(
            count=count,
            llm_calls=llm,
            offline_calls=offline,
            approved_cases=approved,
        )
        complaint_stats.append(
            {
                "complaint": complaint,
                "cluster": complaint_cluster_map.get(complaint, ""),
                "count": int(count),
                "llm_calls": llm,
                "offline_calls": offline,
                "offline_share": round((offline / count), 3) if count else 0.0,
                "approved_cases": approved,
                "quality_score": score,
                "maturity": _maturity_label(score),
            }
        )
    weak_complaints = sorted(
        complaint_stats,
        key=lambda x: (
            -(x.get("llm_calls") or 0),
            x.get("offline_share") or 0.0,
            x.get("approved_cases") or 0,
        ),
    )[:10]
    weekly_items = _filter_since(items, 7 * _DAY_SECONDS)
    monthly_items = _filter_since(items, 30 * _DAY_SECONDS)
    cluster_roadmap = []
    for cluster, count in cluster_counts.most_common(12):
        llm = int(cluster_llm_counts.get(cluster) or 0)
        offline = int(cluster_offline_counts.get(cluster) or 0)
        complaints_in_cluster = [x for x in complaint_stats if x.get("cluster") == cluster]
        avg_quality = round(
            sum(int(x.get("quality_score") or 0) for x in complaints_in_cluster) / max(1, len(complaints_in_cluster)),
            1,
        )
        weakest = sorted(complaints_in_cluster, key=lambda x: int(x.get("quality_score") or 0))[:3]
        cluster_roadmap.append(
            {
                "cluster": cluster,
                "count": int(count),
                "llm_calls": llm,
                "offline_calls": offline,
                "offline_share": round((offline / count), 3) if count else 0.0,
                "avg_quality_score": avg_quality,
                "maturity": _maturity_label(int(round(avg_quality))),
                "weakest_complaints": [x.get("complaint") for x in weakest if x.get("complaint")],
            }
        )
    cluster_roadmap.sort(key=lambda x: (float(x.get("avg_quality_score") or 0.0), -(int(x.get("count") or 0))))

    summary = {
        "total_events": total,
        "llm_calls": llm_calls,
        "offline_saved_calls": offline_saved,
        "llm_share": round((llm_calls / total), 3) if total else 0.0,
        "offline_share": round((offline_saved / total), 3) if total else 0.0,
        "source_counts": dict(source_counts),
        "model_counts": dict(model_counts),
        "cluster_counts": dict(cluster_counts.most_common(12)),
        "top_complaints": [{"complaint": k, "count": v} for k, v in complaint_counts.most_common(15)],
        "complaint_stats": complaint_stats,
        "weak_complaints": weak_complaints,
        "top_quality_complaints": sorted(complaint_stats, key=lambda x: int(x.get("quality_score") or 0), reverse=True)[:10],
        "cluster_roadmap": cluster_roadmap,
        "severity_counts": dict(severity_counts),
        "prompt_chars_total": prompt_chars,
        "response_chars_total": response_chars,
        "prompt_tokens_total": prompt_tokens,
        "completion_tokens_total": completion_tokens,
        "total_tokens_total": total_tokens,
        "estimated_cost_usd_total": round(estimated_cost_usd, 6),
        "avg_prompt_tokens": round((prompt_tokens / llm_calls), 1) if llm_calls else 0.0,
        "avg_completion_tokens": round((completion_tokens / llm_calls), 1) if llm_calls else 0.0,
        "avg_estimated_cost_usd_per_llm_call": round((estimated_cost_usd / llm_calls), 6) if llm_calls else 0.0,
        "weekly_rollup": _simple_rollup(weekly_items),
        "monthly_rollup": _simple_rollup(monthly_items),
        "daily_rollup_last_7": _daily_rollup(weekly_items, 7),
        "daily_rollup_last_30": _daily_rollup(monthly_items, 30),
        "proxy_cost_note": "Estimated OpenAI cost uses local model pricing tables and real token usage when available. Treat as product/finance guidance, not invoice truth.",
    }
    summary["release_quality_gate"] = _build_release_quality_gate(complaint_stats, summary)
    return summary


def get_runtime_events(limit: int = 1000, protocol_source: str = "") -> list[dict[str, Any]]:
    data = _read_json(_EVENTS_FILE)
    items = list(data.get("items") or [])[-max(1, int(limit)) :]
    protocol_filter = str(protocol_source or "").strip().lower()
    if protocol_filter:
        items = [it for it in items if str(it.get("protocol_source") or "").strip().lower() == protocol_filter]
    return items
