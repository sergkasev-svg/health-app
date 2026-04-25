# Release Day 1 Action Pack

Цель дня: подготовить релиз-кандидат (web/backend + mobile beta) и доказательную базу для инвесторского демо.

## A. Web/Backend (Execution)

### 1) Environment & Ops sanity
- [ ] Проверить production/staging env vars (без секретов в репо).
- [ ] Проверить домены, CORS, callback/webhook URL.
- [ ] Проверить доступность логов и алертов.
- [ ] Подтвердить backup/restore план и владельца операции.

### 2) Clinical quality sequence
Из `backend/`:

```bash
python scripts/drift_debug_run.py
python scripts/run_clinical_release_gate.py --level v1-ci
python scripts/run_clinical_release_gate.py --level v1
python scripts/export_investor_quality_report.py
```

- [ ] `drift_cases=0` или документированное исключение.
- [ ] `v1-ci` PASS.
- [ ] `v1` PASS.
- [ ] investor report PASS.

### 3) Artifacts snapshot
- [ ] Сохранить / проверить актуальность:
  - `backend/tests/clinical/reports/drift_debug_latest.json`
  - `backend/tests/clinical/reports/release_gate_v1_ci_latest.json`
  - `backend/tests/clinical/reports/release_gate_latest.json`
  - `backend/tests/clinical/reports/investor_quality_report_latest.json`
  - `backend/tests/clinical/reports/investor_quality_report_latest.md`

## B. Mobile (Execution)

### 1) Build config sanity
- [ ] Проверить EAS profiles/keys.
- [ ] Проверить production API endpoints в mobile конфиге.
- [ ] Проверить crash/analytics SDK init.

### 2) Beta build targets
- [ ] Android internal build.
- [ ] iOS TestFlight build.
- [ ] Smoke на устройствах (минимум 2 Android, 1 iOS).

### 3) Store prep package
- [ ] Подготовить metadata: app name, description, keywords.
- [ ] Подготовить screenshots/preview.
- [ ] Privacy policy и support URL подтверждены.

## C. Investor prep (Execution)

### 1) Demo env
- [ ] Demo-аккаунты web/mobile готовы.
- [ ] Backup-сценарий (видео/скриншоты) готов.

### 2) Deck draft
- [ ] Заполнить skeleton: `docs/INVESTOR_DECK_SKELETON.md`
- [ ] Вставить свежие метрики из latest artifacts.

## D. End-of-day Definition of Done

- [ ] Web/backend RC criteria выполнены.
- [ ] Mobile beta build(ы) готовы.
- [ ] Investor demo assets собраны в единый пакет.
- [ ] Следующий день запланирован (Day 2: RC hardening + Store submission prep).
