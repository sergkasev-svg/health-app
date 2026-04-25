# Investor Deck Draft — Day 1 (2026-04-25)

Черновик для быстрой сборки презентации на 8-12 слайдов.  
Все цифры взяты из latest clinical artifacts.

## Slide 1 — Title / One-liner
- Zazdorovie: AI-first triage and clinical guidance assistant.
- Web + Mobile channel strategy.

## Slide 2 — Problem
- Пользователю нужен быстрый и понятный первичный ориентир по симптомам.
- Ключевой риск рынка: недоверие к качеству и безопасности ответов.

## Slide 3 — Product
- Web и mobile каналы в едином клиническом quality-контуре.
- Параллельный релизный трек: продукт + quality evidence.

## Slide 4 — Why Now
- Стабилизирован clinical harness с масштабом `1040` кейсов.
- Введен lightweight CI-level gate (`v1-ci`) для быстрой проверки регрессий.

## Slide 5 — Quality & Safety Evidence
- `v1-ci` gate: **PASS**
  - cases: `54`
  - drift: `0.0`
  - redflag recall: `0.8125`
  - human tone: `0.963`
- `v1` gate: **PASS**
  - cases: `1040`
  - loop rate: `0.0`
  - drift: `0.0`
  - redflag recall: `0.875`
  - non-empty response rate: `1.0`
  - human tone: `0.977`

## Slide 6 — Operational Discipline
- CI workflow включает clinical gate + artifact upload.
- Есть выделенные релизные checklists для web/mobile и Go/No-Go.

## Slide 7 — Mobile Release Readiness
- Подготовлен Day 1 checklist по build/smoke/distribution/store metadata.
- Цель: Android internal + iOS TestFlight в одном релизном цикле.

## Slide 8 — Next 30 Days
- RC hardening, store submission prep, staged rollout.
- Замер post-release reliability + feedback loop в quality harness.

## Slide 9 — Funding Ask (Draft)
- Инвестиция на ускорение go-to-market и мобильного масштабирования.
- Use of funds: product delivery, reliability, growth experiments.

## Slide 10 — Appendix / Evidence Links
- `backend/tests/clinical/reports/release_gate_v1_ci_latest.json`
- `backend/tests/clinical/reports/release_gate_latest.json`
- `backend/tests/clinical/reports/drift_debug_latest.json`
- `backend/tests/clinical/reports/investor_quality_report_latest.md`
