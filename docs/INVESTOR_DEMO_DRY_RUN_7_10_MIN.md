# Investor Demo Dry-Run Script (7-10 min)

## Goal

Показать инвестору, что продукт не только выглядит хорошо, но и управляется как quality-driven release process: web + mobile + clinical evidence.

## Total Timing

- Target duration: `8:30` (допуск 7-10 мин)
- Backup version: `5:00` (если время урезали)

## Demo Flow

### 0:00-0:45 — Opening

- One-liner:
  - "Мы строим AI-first медицинский ассистент с контролем качества на уровне релиз-гейтов."
- Что покажем:
  - web путь пользователя
  - mobile готовность
  - clinical evidence (v1-ci/v1 PASS)

### 0:45-2:45 — Web Product Walkthrough

- Вход в web-продукт и быстрый пользовательский сценарий:
  - ввод симптома
  - структурированный ответ
  - аккуратная следующая рекомендация
- Подчеркнуть:
  - не просто чат, а маршрут с клиническим контролем
  - ответы не пустые, есть контроль тона и drift

### 2:45-4:15 — Mobile Release Readiness

- Показать mobile экран(ы) / flow.
- Подчеркнуть:
  - mobile идет как production-channel, не только demo
  - подготовлен Day 3 checklist для build/smoke/store prep

### 4:15-6:45 — Quality & Safety Evidence

- Коротко вывести факты:
  - `drift_debug`: expect_cases `52`, drift_cases `0`
  - `v1-ci`: `PASS` (52 cases)
  - `v1`: `PASS` (1040 cases)
  - `investor_quality_report`: `PASS`
- Смысл для инвестора:
  - качество измеряется регулярно, а не вручную "по ощущениям"
  - есть repeatable release discipline

### 6:45-8:00 — Execution Discipline & Roadmap

- Что уже сделано:
  - Day 1/Day 2/Day 3 артефакты
  - release checklists + go/no-go контур
- Что дальше:
  - RC hardening
  - mobile candidate builds
  - staged launch + post-release monitoring

### 8:00-8:30 — Ask / Close

- "Мы готовы масштабировать выпуск и go-to-market при сохранении quality-контроля."
- Переход к вопросам.

## Backup Plan (if live demo fails)

1. Показать заранее подготовленные скриншоты/видео web+mobile flow.
2. Показать свежий `investor_quality_report_latest.md`.
3. Закрыть блок метриками и roadmap.

## Q&A Quick Answers

- Почему вам можно доверять по качеству?
  - "У нас repeatable gate-процесс: drift + v1-ci + v1 + investor report."
- Как избегаете регрессий?
  - "Через expect-pack и CI-level preflight перед релизными шагами."
- Что главный риск?
  - "Скорость product delivery vs quality bar; решаем через staged execution checklist."
