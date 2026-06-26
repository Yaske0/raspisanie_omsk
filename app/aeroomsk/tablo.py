# -*- coding: utf-8 -*-
"""
Загрузка и разбор онлайн-табло Омского аэропорта.

Эндпоинты (фоновые запросы сайта):
    Вылет:  https://www.aeroomsk.ru/?type=DEP&day=THIS&AjaxTablo=ajax
    Прилет: https://www.aeroomsk.ru/?type=ARR&day=THIS&AjaxTablo=ajax
    day = PREV (вчера) | THIS (сегодня) | NEXT (завтра)

Колонки различаются:
    DEP:  Дата | Аэропорт назначения | № рейса | Авиакомпания | Конец регистрации |
          Отправление по расписанию | Время отправления | Статус рейса | Задержан до
    ARR:  Дата | Аэропорт вылета | № рейса | Авиакомпания |
          Прилет по расписанию | Ожидается | Прилет | Статус рейса
"""

from __future__ import annotations

import io
import re
import datetime as dt
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import requests

BASE_URL = "https://www.aeroomsk.ru/"
ARR, DEP = "ARR", "DEP"
DAY_PREV, DAY_THIS, DAY_NEXT = "PREV", "THIS", "NEXT"

_DATE_RE = re.compile(r"^\s*(\d{2})\.(\d{2})\s*$")
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


@dataclass
class Flight:
    direction: str                 # ARR | DEP
    city: str
    flight_no: str
    airline: str
    sched: dt.datetime             # время по расписанию
    expected: Optional[dt.datetime]  # ARR: "Ожидается"; DEP: "Задержан до"
    actual: Optional[dt.datetime]    # ARR: "Прилет"; DEP: "Время отправления"
    status: str

    @property
    def effective(self) -> dt.datetime:
        """Когда рейс реально будет: ожидаемое → фактическое → плановое."""
        return self.expected or self.actual or self.sched

    @property
    def completed(self) -> bool:
        """Рейс уже состоялся (прибыл/вылетел)."""
        s = self.status.upper()
        return ("ПРИБЫЛ" in s or "ВЫЛЕТЕЛ" in s) and self.actual is not None


# --------------------------------------------------------------------------
# Загрузка
# --------------------------------------------------------------------------
def fetch(direction: str, day: str, timeout: int = 20) -> str:
    params = {"type": direction, "day": day, "AjaxTablo": "ajax"}
    headers = {"User-Agent": "Mozilla/5.0 (schedule-bot)"}
    r = requests.get(BASE_URL, params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    # Сайт отдаёт UTF-8. Авто-угадывание кодировки ломает кириллицу,
    # поэтому декодируем явно как UTF-8.
    return r.content.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------
# Разбор
# --------------------------------------------------------------------------
def _find_col(columns, *needles) -> Optional[int]:
    for i, c in enumerate(columns):
        cl = str(c).lower()
        if all(n.lower() in cl for n in needles):
            return i
    return None


def _mk_time(base: dt.date, raw, ref: Optional[dt.datetime]) -> Optional[dt.datetime]:
    """HH:MM + дата. Если есть опорное время ref и пересекли полночь — поправим дату."""
    if raw is None:
        return None
    m = _TIME_RE.search(str(raw))
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    dt_ = dt.datetime.combine(base, dt.time(hh, mm))
    if ref is not None:
        # подобрать дату в пределах ±12 ч от опорного времени (учёт перехода через 00:00)
        best = dt_
        for shift_days in (-1, 0, 1):
            cand = dt_ + dt.timedelta(days=shift_days)
            if abs((cand - ref).total_seconds()) < abs((best - ref).total_seconds()):
                best = cand
        dt_ = best
    return dt_


def parse_board(html: str, direction: str, base_date: dt.date,
                year: Optional[int] = None) -> list[Flight]:
    """Вернуть список рейсов с одного табло."""
    year = year or base_date.year
    tables = pd.read_html(io.StringIO(html), keep_default_na=False)

    SCHED_KEY = "по расписанию"

    header = None
    data_rows = None
    for t in tables:
        col_names = [str(c) for c in t.columns]
        values = t.values.tolist()
        # Вариант A: pandas увёл шапку в имена столбцов (таблица с <thead>)
        if any(SCHED_KEY in c.lower() for c in col_names):
            header = col_names
            data_rows = values
            break
        # Вариант B: шапка осталась обычной строкой в данных
        hidx = next((i for i, row in enumerate(values)
                     if any(SCHED_KEY in str(c).lower() for c in row)), None)
        if hidx is not None:
            header = [str(c) for c in values[hidx]]
            data_rows = values[hidx + 1:]
            break

    if header is None or data_rows is None:
        return []

    ci_city = _find_col(header, "аэропорт")
    ci_flight = _find_col(header, "рейс")
    ci_air = _find_col(header, "авиакомпания")
    ci_sched = _find_col(header, "по расписанию")
    ci_status = _find_col(header, "статус")
    if direction == ARR:
        ci_exp = _find_col(header, "ожидается")
        ci_act = _find_col(header, "прилет") or _find_col(header, "прилёт")
        # колонка "Прилет по расписанию" тоже содержит "прилет" — исключим её
        if ci_act == ci_sched:
            ci_act = None
            for i, c in enumerate(header):
                cl = str(c).lower()
                if ("прилет" in cl or "прилёт" in cl) and "распис" not in cl:
                    ci_act = i
                    break
    else:
        ci_exp = _find_col(header, "задержан")
        ci_act = _find_col(header, "время", "отправлен")

    out: list[Flight] = []

    def cell(row, idx):
        if idx is None or idx >= len(row):
            return None
        v = str(row[idx]).strip()
        return v if v and v.lower() != "nan" else None

    for row in data_rows:
        first = str(row[0]).strip()
        m = _DATE_RE.match(first)
        if not m:                      # строки "О самолете…" и пустые — пропускаем
            continue
        dd, mo = int(m.group(1)), int(m.group(2))
        rdate = dt.date(year, mo, dd)

        sched = _mk_time(rdate, cell(row, ci_sched), None)
        if sched is None:
            continue
        expected = _mk_time(rdate, cell(row, ci_exp), sched)
        actual = _mk_time(rdate, cell(row, ci_act), sched)

        out.append(Flight(
            direction=direction,
            city=(cell(row, ci_city) or "").strip(),
            flight_no=(cell(row, ci_flight) or "").strip(),
            airline=(cell(row, ci_air) or "").strip(),
            sched=sched,
            expected=expected,
            actual=actual,
            status=(cell(row, ci_status) or "").strip(),
        ))
    return out
