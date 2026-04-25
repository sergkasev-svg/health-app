# Day 3 Execution Checklist (2026-04-26)

Цель дня: перейти от стабилизации quality-гейтов к релизному исполнению (RC hardening + mobile submission readiness + investor demo rehearsal).

## 1) Web/Backend RC Hardening

- [ ] Зафиксировать RC baseline commit/tag для `main`.
- [ ] Проверить production env matrix (API keys, domains, CORS, callbacks, alerts).
- [ ] Выполнить smoke-сценарии на staging/prod-candidate:
  - [ ] auth/session
  - [ ] core user flow
  - [ ] critical API endpoints
- [ ] Перепроверить clinical gates (контрольный прогон):
  - [ ] `python backend/scripts/drift_debug_run.py`
  - [ ] `python backend/scripts/run_clinical_release_gate.py --level v1-ci`
  - [ ] `python backend/scripts/run_clinical_release_gate.py --level v1`

## 2) Mobile Release Readiness

- [ ] Проверить production mobile config (API URL, keys, feature flags).
- [ ] Сформировать candidate builds:
  - [ ] Android internal
  - [ ] iOS TestFlight
- [ ] Прогнать smoke на устройствах:
  - [ ] launch + auth
  - [ ] critical user journey
  - [ ] crash/analytics sanity
- [ ] Подготовить store package:
  - [ ] screenshots
  - [ ] descriptions/keywords
  - [ ] privacy/support links
  - [ ] release notes

## 3) Investor Demo Rehearsal

- [ ] Обновить deck из `docs/INVESTOR_DECK_DRAFT_DAY1_2026-04-25.md`:
  - [ ] заменить на финальные PASS-метрики из latest artifacts
  - [ ] добавить slide с Day 2.1 stabilization outcome
- [ ] Провести dry-run 7-10 минут:
  - [ ] сценарий web части
  - [ ] сценарий mobile части
  - [ ] fallback (видео/скриншоты)
- [ ] Подготовить Q&A ответы:
  - [ ] clinical quality controls
  - [ ] release risk mitigation
  - [ ] go-to-market next 90 days

## 4) Go/No-Go Prep

- [ ] Обновить `docs/GO_NO_GO_CHECKLIST.md` реальным статусом пунктов.
- [ ] Назначить owners и даты на P0/P1 пункты.
- [ ] Сформировать короткий decision memo: `GO` / `NO-GO` + причины.

## 5) End-of-Day Deliverables

- [ ] Обновленный RC status note.
- [ ] Mobile candidate build links (Android/iOS).
- [ ] Investor deck v1 (presentable).
- [ ] Go/No-Go draft decision ready for review.
