# -*- coding: utf-8 -*-
"""
Логика рабочих смен.

Цикл повторяется каждые 4 дня, считая от «якорной» дневной смены:
    День 0 — ДНЕВНАЯ   07:45–19:45
    День 1 — НОЧНАЯ    19:45 (этого дня) → 07:45 (следующего дня)
    День 2 — выходной
    День 3 — выходной
    День 4 — снова ДНЕВНАЯ … и так по кругу.

Якорь по умолчанию: 25.06.2026 — дневная смена (задан пользователем).
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

# --- Настройки смены (можно менять) ---------------------------------------
ANCHOR_DAY_SHIFT = date(2026, 6, 25)   # дата, когда точно была ДНЕВНАЯ смена
DAY_START = time(7, 45)
DAY_END = time(19, 45)
NIGHT_START = time(19, 45)
NIGHT_END = time(7, 45)                # уже на следующий день
# --------------------------------------------------------------------------

DAY = "ДЕНЬ"
NIGHT = "НОЧЬ"


@dataclass
class Shift:
    kind: str          # DAY | NIGHT
    start: datetime    # начало смены
    end: datetime      # конец смены (для ночной — на следующие сутки)

    @property
    def title_date(self) -> date:
        """Дата, под которой смена «числится» (дата начала)."""
        return self.start.date()

    def human(self) -> str:
        if self.kind == DAY:
            return f"Дневная смена {self.start:%d.%m.%Y} {DAY_START:%H:%M}–{DAY_END:%H:%M}"
        return (f"Ночная смена с {self.start:%d.%m.%Y} {NIGHT_START:%H:%M} "
                f"до {self.end:%d.%m.%Y} {NIGHT_END:%H:%M}")


def _phase(d: date) -> int:
    """Положение даты в 4-дневном цикле: 0=день,1=ночь,2/3=выходной."""
    return (d - ANCHOR_DAY_SHIFT).days % 4


def shift_starting_on(d: date) -> Shift | None:
    """Смена, НАЧИНАЮЩАЯСЯ в дату d (или None, если это выходной)."""
    p = _phase(d)
    if p == 0:
        return Shift(DAY, datetime.combine(d, DAY_START), datetime.combine(d, DAY_END))
    if p == 1:
        return Shift(NIGHT,
                     datetime.combine(d, NIGHT_START),
                     datetime.combine(d + timedelta(days=1), NIGHT_END))
    return None


def current_or_next_shift(now: datetime | None = None) -> Shift:
    """
    Смена «для печати»: если сейчас идёт смена — она; иначе ближайшая будущая.
    Смотрим окно от вчера до +5 дней, берём первую, которая ещё не закончилась.
    """
    if now is None:
        now = datetime.now()
    candidates: list[Shift] = []
    for delta in range(-1, 6):
        s = shift_starting_on(now.date() + timedelta(days=delta))
        if s is not None:
            candidates.append(s)
    candidates.sort(key=lambda s: s.start)
    for s in candidates:
        if now < s.end:          # смена ещё не завершилась
            return s
    return candidates[-1]


if __name__ == "__main__":
    # быстрый самоконтроль по примеру пользователя
    print("Проверка цикла от якоря 25.06.2026 (дневная):")
    for off in range(0, 9):
        d = ANCHOR_DAY_SHIFT + timedelta(days=off)
        s = shift_starting_on(d)
        print(f"  {d:%d.%m} -> {s.human() if s else 'выходной'}")
