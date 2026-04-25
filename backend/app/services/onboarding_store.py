"""
Хранилище состояния онбординга: file-based JSON или in-memory fallback.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from app.services.onboarding_models import OnboardingState


def _default_path(user_id: Optional[str], session_id: Optional[str]) -> Optional[Path]:
    try:
        base = Path(__file__).resolve().parent.parent.parent / "data" / "users"
        safe_uid = "".join(c if c.isalnum() or c in "-_" else "_" for c in (user_id or "default").strip())[:64] or "default"
        sid = (session_id or "main").strip() or "main"
        safe_sid = "".join(c for c in sid if c.isalnum() or c in "-_")[:40] or "main"
        return base / safe_uid / "onboarding_state.json"
    except Exception:
        return None


class OnboardingStore:
    def __init__(
        self,
        file_path_builder: Optional[Callable[[Optional[str], Optional[str]], Optional[Path]]] = None,
    ):
        self._path_builder = file_path_builder or _default_path
        self._cache: Dict[str, OnboardingState] = {}

    def _key(self, user_id: Optional[str], session_id: Optional[str]) -> str:
        return f"{user_id or 'default'}:{session_id or 'main'}"

    def load(self, user_id: Optional[str], session_id: Optional[str]) -> OnboardingState:
        key = self._key(user_id, session_id)
        path = self._path_builder(user_id, session_id) if self._path_builder else None
        if path and path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                state = OnboardingState.from_dict(data)
                state.user_id = user_id
                state.session_id = session_id
                self._cache[key] = state
                return state
            except Exception:
                pass
        if key in self._cache:
            return self._cache[key]
        return OnboardingState(user_id=user_id, session_id=session_id, is_new_user=True)

    def save(self, state: OnboardingState) -> None:
        if not state:
            return
        key = self._key(state.user_id, state.session_id)
        state.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self._cache[key] = state
        path = self._path_builder(state.user_id, state.session_id) if self._path_builder else None
        if path:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    def mark_step_completed(self, state: OnboardingState, step_id: str) -> OnboardingState:
        if step_id and step_id not in state.completed_steps:
            state.completed_steps = state.completed_steps + [step_id]
        state.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return state

    def mark_step_skipped(self, state: OnboardingState, step_id: str) -> OnboardingState:
        if step_id and step_id not in state.skipped_steps:
            state.skipped_steps = state.skipped_steps + [step_id]
        state.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return state
