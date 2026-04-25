# Go / No-Go Checklist (Web + Mobile)

Решение принимается только при закрытии всех блоков `P0`.

## P0 — Must Pass

### Product & Quality
- [x] `v1-ci` gate PASS.
- [x] `v1` full gate PASS.
- [x] `drift_debug_run.py`: `drift_cases=0` или принятое исключение задокументировано.
- [ ] Smoke tests пройдены на web и mobile.

### Reliability & Operations
- [ ] Мониторинг и алерты активны.
- [ ] Логи доступны и проверены.
- [ ] Backup/restore сценарий подтвержден.
- [ ] Rollback plan готов и протестирован минимум на dry-run.

### Security & Compliance
- [ ] Secrets не в репозитории, env корректно настроен.
- [ ] Privacy policy / support контакты актуальны.
- [ ] Mobile permissions обоснованы в store metadata.

### Release Controls
- [ ] Финальный commit/tag зафиксирован.
- [ ] Release notes подготовлены.
- [ ] Ответственные на первые 24–48ч после релиза назначены.

## P1 — Should Have

- [ ] Investor deck обновлен под финальные метрики.
- [ ] Demo script репетирован 1+ раз.
- [ ] Post-release analytics dashboard подготовлен.

## Decision

- Go / No-Go: `[выбрать]`
- Дата/время: `[заполнить]`
- Approvers:
  - Product: `[имя]`
  - Tech: `[имя]`
  - QA: `[имя]`
  - Ops: `[имя]`

## Notes

- [свободные заметки и риски]
