from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConfidenceResult:
    score: int
    level: str
    reasons: list[str]


class ConfidenceEngine:
    """
    Converts evidence density into a simple confidence score.
    Scale:
      0-39   = low
      40-69  = medium
      70-100 = high
    """

    def evaluate(
        self,
        *,
        matched_red_flags: list[str],
        trigger_groups: list[str],
        zone_scores: dict[str, int],
        cluster_scores: dict[str, int],
        cause_scores: dict[str, int],
        evidence_map: dict[str, list[str]],
        repeated_trigger_groups: list[str] | None = None,
        repeated_causes: list[str] | None = None,
    ) -> ConfidenceResult:
        reasons: list[str] = []
        score = 0

        if matched_red_flags:
            return ConfidenceResult(
                score=95,
                level="high",
                reasons=["urgent red flags detected"],
            )

        if trigger_groups:
            score += min(15, len(trigger_groups) * 5)
            reasons.append(f"trigger groups detected: {', '.join(trigger_groups)}")

        if zone_scores:
            best_zone_score = max(zone_scores.values()) if zone_scores else 0
            score += min(15, best_zone_score)
            reasons.append(f"zone signal: {best_zone_score}")

        if cluster_scores:
            best_cluster_score = max(cluster_scores.values()) if cluster_scores else 0
            score += min(20, best_cluster_score)
            reasons.append(f"cluster signal: {best_cluster_score}")

        if cause_scores:
            sorted_scores = sorted(cause_scores.values(), reverse=True)
            top_score = sorted_scores[0]
            gap = top_score - (sorted_scores[1] if len(sorted_scores) > 1 else 0)
            score += min(20, top_score)
            score += min(10, max(gap, 0))
            reasons.append(f"top cause score: {top_score}")
            reasons.append(f"top-vs-next gap: {gap}")

        evidence_points = sum(len(values) for values in evidence_map.values())
        score += min(15, evidence_points)
        reasons.append(f"evidence points: {evidence_points}")

        repeated_trigger_groups = repeated_trigger_groups or []
        repeated_causes = repeated_causes or []

        if repeated_trigger_groups:
            score += 5
            reasons.append(f"repeated triggers: {', '.join(repeated_trigger_groups)}")

        if repeated_causes:
            score += 5
            reasons.append(f"repeated causes: {', '.join(repeated_causes)}")

        score = max(0, min(score, 100))

        if score >= 70:
            level = "high"
        elif score >= 40:
            level = "medium"
        else:
            level = "low"

        return ConfidenceResult(score=score, level=level, reasons=reasons)

