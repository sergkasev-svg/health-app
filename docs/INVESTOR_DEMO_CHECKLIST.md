# Investor Demo Checklist (v1)

Цель: показать не только продукт, но и зрелость release-процесса.

## 1) Demo Narrative (7–10 min)

- [ ] Проблема и целевая аудитория (1 мин)
- [ ] Решение: Web flow (2–3 мин)
- [ ] Решение: Mobile flow (2–3 мин)
- [ ] Качество/безопасность: clinical harness + CI gate (1–2 мин)
- [ ] Go-to-market и next milestones (1 мин)

## 2) Mandatory Artifacts

- [ ] Clinical release gate latest:
  - `backend/tests/clinical/reports/release_gate_latest.json`
- [ ] Clinical CI gate latest:
  - `backend/tests/clinical/reports/release_gate_v1_ci_latest.json`
- [ ] Drift debug:
  - `backend/tests/clinical/reports/drift_debug_latest.json`
- [ ] Investor quality latest:
  - `backend/tests/clinical/reports/investor_quality_report_latest.json`
  - `backend/tests/clinical/reports/investor_quality_report_latest.md`
- [ ] Release slice:
  - `backend/tests/clinical/RELEASE_SLICE_2026-04-25.md`

## 3) Proof Points To Show

- [ ] `drift_cases=0` на expect-наборе.
- [ ] `v1-ci` gate в CI + downloadable artifacts.
- [ ] `v1` full gate PASS на полном pack.
- [ ] Threshold tightening history (без регрессии качества).
- [ ] Тег эталонного состояния (`v1-harness-2026-04-25`).

## 4) Demo Environment Readiness

- [ ] Подготовлен demo-аккаунт (web).
- [ ] Подготовлен demo-аккаунт (mobile).
- [ ] Стабильный интернет + backup hotspot.
- [ ] Backup запись видео демо (на случай сетевого сбоя).
- [ ] План B: скриншоты ключевых этапов.

## 5) Slide Pack (8–12 slides)

- [ ] 1: Problem / Why now
- [ ] 2: Product overview
- [ ] 3: Web flow
- [ ] 4: Mobile flow
- [ ] 5: Clinical quality metrics
- [ ] 6: Release discipline (CI + gates + artifacts)
- [ ] 7: Market / GTM
- [ ] 8: Traction (если есть)
- [ ] 9: Roadmap 2–3 квартала
- [ ] 10: Ask / use of funds

## 6) Q&A Prep (high-probability)

- [ ] Medical safety / liability boundaries.
- [ ] Data privacy / security controls.
- [ ] Why this team can execute.
- [ ] Defensibility and moat.
- [ ] Unit economics assumptions.
- [ ] Release cadence and operational maturity.

## 7) Final Dry Run

- [ ] Прогон demo по таймеру (<=10 мин).
- [ ] Прогон Q&A (>=20 мин).
- [ ] Проверка всех ссылок/артефактов перед встречей.
