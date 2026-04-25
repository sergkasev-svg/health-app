"""
Числовые ориентиры приоритетов P1/P2 (документация; основная сортировка в pattern_ranker).
"""
from __future__ import annotations

# P1: клинически значимые паттерны
PRIORITY_P1_HEMATOLOGY_IRON = 90
PRIORITY_P1_LIPID_ATHEROGENIC = 80
PRIORITY_P1_VITAMIN_D_INSUFFICIENCY = 45

# P2: контекст / «спокойные системы»
PRIORITY_P2_GLUCOSE_NO_SIGNAL = 15
PRIORITY_P2_INFLAMMATION_NO_SIGNAL = 10
