# Release Plan: Web + Mobile (v1)

Статус: `in_progress`  
Горизонт: ближайшие 7–10 дней  
Релиз-ветка: `main`  
Критерий готовности: `Go/No-Go` checklist полностью закрыт.

## 1) Scope Freeze

Цель: зафиксировать содержимое релиза и исключить фиче-дрифт.

- Входит в v1:
  - Backend + Web в production-конфигурации.
  - Mobile app как production-канал (не только beta/demo).
  - Clinical quality gates (`v1-ci`, `v1`) и release artifacts.
- Не входит:
  - Новые крупные продуктовые фичи вне критических фиксов.
  - Рефакторинги без влияния на релизные риски.

## 2) Web/Backend Release Track

### Этап A: Pre-Prod readiness
- [ ] Проверить production env (секреты, CORS, платежи, домены, SMTP/webhooks).
- [ ] Убедиться, что мониторинг/алерты и логирование включены.
- [ ] Проверить backup/restore сценарий БД.

### Этап B: Release candidate
- [ ] Собрать RC и развернуть на staging/prod-candidate.
- [ ] Пройти smoke-кейсы:
  - [ ] auth/session
  - [ ] основные пользовательские сценарии
  - [ ] billing/paywall (если включено)
  - [ ] critical API endpoints
- [ ] Пройти clinical gates:
  - [ ] `python backend/scripts/drift_debug_run.py`
  - [ ] `python backend/scripts/run_clinical_release_gate.py --level v1-ci`
  - [ ] `python backend/scripts/run_clinical_release_gate.py --level v1`

### Этап C: Launch
- [ ] Подготовить rollback инструкции.
- [ ] Выполнить Go/No-Go.
- [ ] Выпустить релиз, включить post-release мониторинг 24–48ч.

## 3) Mobile Release Track

### Этап A: Build & config
- [ ] Подтвердить EAS профили (`dev`/`staging`/`prod`) и секреты.
- [ ] Проверить release-билд на iOS/Android.
- [ ] Убедиться, что API endpoints/keys в mobile соответствуют production.

### Этап B: QA & beta
- [ ] Smoke на физ. устройствах (минимум 2 Android, 1 iOS).
- [ ] Проверить:
  - [ ] login/onboarding
  - [ ] ключевой user flow
  - [ ] аналитика/ивенты
  - [ ] crash-free базовые сценарии
- [ ] Запустить TestFlight/Internal testing.

### Этап C: Store submission
- [ ] Store metadata:
  - [ ] app name/subtitle
  - [ ] icons/splash
  - [ ] screenshots
  - [ ] privacy policy/support URL
  - [ ] permissions justification
- [ ] Отправить в review.
- [ ] Подготовить staged rollout.

## 4) Investor Parallel Track

- [ ] Обновить investor artifacts:
  - [ ] `investor_quality_report_latest.json`
  - [ ] `investor_quality_report_latest.md`
- [ ] Сформировать demo script (7–10 мин).
- [ ] Сформировать deck (8–12 слайдов) с опорой на фактические метрики.
- [ ] Подготовить Q&A по рискам и roadmap.

## 5) Current Baseline (already done)

- Clinical harness стабилизирован, drift debug доведен до `drift_cases=0`.
- Выпущен tag: `v1-harness-2026-04-25`.
- Включен lightweight CI gate:
  - `.github/workflows/clinical-v1-ci.yml`
  - `--level v1-ci` + upload artifacts.
- Порог `max_domain_drift_rate` ужесточен до `0.18` для v1.

## 6) Owners / Dates (fill-in)

- Release owner: `[назначить]`
- Backend/Web owner: `[назначить]`
- Mobile owner: `[назначить]`
- QA owner: `[назначить]`
- Investor owner: `[назначить]`
- Target launch date: `[дата]`

## 7) Day 1 Execution Artifacts

- `docs/RELEASE_DAY1_ACTION_PACK.md`
- `docs/MOBILE_RELEASE_CHECKLIST_DAY1.md`
- `docs/INVESTOR_DECK_SKELETON.md`
