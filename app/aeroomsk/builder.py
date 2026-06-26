# -*- coding: utf-8 -*-
"""
Отбор рейсов под конкретную смену и формирование строк для документа.

Правила (согласованы с пользователем):
  • рейс попадает в смену, если его ФАКТИЧЕСКОЕ/ОЖИДАЕМОЕ время внутри окна смены —
    значит «прилетевший раньше, но задержанный в мою смену» автоматически попадает;
  • рейс, который должен был быть в смену, но задержан за её конец — убираем;
  • задержанные с НЕизвестным новым временем, чьё расписание было незадолго до
    начала смены, тоже показываем (со словом ЗАДЕРЖАН).

В последней колонке документа:
  • известно новое время  -> печатаем новое время (ЧЧ:ММ);
  • задержан, нового времени нет -> слово «ЗАДЕРЖАН»;
  • всё по плану -> пусто.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .shifts import Shift
from .tablo import Flight

GRACE_BEFORE_START = dt.timedelta(hours=4)   # «дотягиваем» задержанных без ETA
DELAY_THRESHOLD = dt.timedelta(minutes=5)    # с какого сдвига считаем рейс задержанным


def _status_upper(f: Flight) -> str:
    return (f.status or "").upper()


def is_delayed(f: Flight) -> bool:
    if "ЗАДЕРЖ" in _status_upper(f):
        return True
    ref = f.expected or f.actual
    return ref is not None and (ref - f.sched) >= DELAY_THRESHOLD


def delayed_no_eta(f: Flight) -> bool:
    """Задержан, но нового времени ещё нет (повод написать «ЗАДЕРЖАН»)."""
    return ("ЗАДЕРЖ" in _status_upper(f)) and f.expected is None and not f.completed


def status_cell(f: Flight) -> str:
    """Текст последней колонки документа."""
    if delayed_no_eta(f):
        return "ЗАДЕРЖАН"
    if f.expected is not None and is_delayed(f):
        return f"{f.expected:%H:%M}"
    return ""


def in_shift(f: Flight, shift: Shift) -> bool:
    # уже состоялся до начала смены — не наш
    if f.completed and f.actual is not None and f.actual < shift.start:
        return False
    eff = f.effective
    if shift.start <= eff < shift.end:
        return True
    # задержан без ETA, расписание было незадолго до начала смены
    if (delayed_no_eta(f)
            and shift.start - GRACE_BEFORE_START <= f.sched < shift.start):
        return True
    return False


@dataclass
class Row:
    date: str       # ДД.ММ
    city: str
    flight_no: str
    airline: str
    sched: str      # ЧЧ:ММ
    status: str     # новое время / ЗАДЕРЖАН / пусто


def build_rows(flights: list[Flight], shift: Shift) -> list[Row]:
    picked = [f for f in flights if in_shift(f, shift)]
    # сортировка как в образце — по плановому времени
    picked.sort(key=lambda f: f.sched)
    rows = []
    seen = set()
    for f in picked:
        key = (f.flight_no, f"{f.sched:%Y%m%d%H%M}")
        if key in seen:
            continue
        seen.add(key)
        rows.append(Row(
            date=f"{f.sched:%d.%m}",
            city=f.city,
            flight_no=f.flight_no,
            airline=f.airline,
            sched=f"{f.sched:%H:%M}",
            status=status_cell(f),
        ))
    return rows
