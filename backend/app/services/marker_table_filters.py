"""
Фильтры для строк лабораторных таблиц (избежание «мусорных» интегрированных текстов в ячейках).
Вынесено из report.py, чтобы разорвать цикл импорта report ↔ clinical_engine.unified_contract.
"""


def is_junk_marker_narrative(marker: str, comment: str) -> bool:
    """Текст интегрированного вывода не должен попадать в строку лабораторной таблицы."""
    blob = f"{marker} {comment}".strip().lower()
    if len(blob) > 220 and "выявлен" in blob and "направлен" in blob:
        return True
    if "выявлены два основных направления" in blob:
        return True
    if len(marker) > 180:
        return True
    return False
