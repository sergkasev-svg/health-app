from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TriggerEvent:
    trigger_groups: list[str]
    ranked_causes: list[str]
    zone: str
    cluster: str
    user_text: str


@dataclass
class TriggerMemoryState:
    events: list[TriggerEvent] = field(default_factory=list)

    def add_event(
        self,
        *,
        trigger_groups: list[str],
        ranked_causes: list[str],
        zone: str,
        cluster: str,
        user_text: str,
    ) -> None:
        self.events.append(
            TriggerEvent(
                trigger_groups=trigger_groups,
                ranked_causes=ranked_causes,
                zone=zone,
                cluster=cluster,
                user_text=user_text,
            )
        )

    def count_trigger_group(self, trigger_group: str) -> int:
        return sum(1 for event in self.events if trigger_group in event.trigger_groups)

    def count_cause(self, cause_id: str) -> int:
        return sum(1 for event in self.events if cause_id in event.ranked_causes)

    def repeated_trigger_groups(self, min_count: int = 2) -> list[str]:
        all_groups: set[str] = set()
        for event in self.events:
            all_groups.update(event.trigger_groups)

        repeated: list[str] = []
        for group in all_groups:
            if self.count_trigger_group(group) >= min_count:
                repeated.append(group)
        return sorted(repeated)

    def repeated_causes(self, min_count: int = 2) -> list[str]:
        all_causes: set[str] = set()
        for event in self.events:
            all_causes.update(event.ranked_causes)

        repeated: list[str] = []
        for cause_id in all_causes:
            if self.count_cause(cause_id) >= min_count:
                repeated.append(cause_id)
        return sorted(repeated)

    def summary(self) -> dict[str, Any]:
        return {
            "events_count": len(self.events),
            "repeated_trigger_groups": self.repeated_trigger_groups(),
            "repeated_causes": self.repeated_causes(),
        }

