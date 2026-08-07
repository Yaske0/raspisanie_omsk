# -*- coding: utf-8 -*-
"""
Оркестровка: по текущей/ближайшей смене выгрузить нужные табло,
отфильтровать рейсы и собрать документ Word.
"""

from __future__ import annotations

import os
import datetime as dt
from typing import Callable

from . import tablo, builder, shifts, docxgen
from .shifts import Shift


def _day_param(target: dt.date, today: dt.date) -> str | None:
    delta = (target - today).days
    return {-1: tablo.DAY_PREV, 0: tablo.DAY_THIS, 1: tablo.DAY_NEXT}.get(delta)


def _collect(direction: str, dates: list[tuple[dt.date, str]],
             log: Callable[[str], None]) -> list[tablo.Flight]:
    flights: list[tablo.Flight] = []
    for d, param in dates:
        name = "Прилет" if direction == tablo.ARR else "Вылет"
        log(f"  загрузка: {name} за {d:%d.%m} …")
        html = tablo.fetch(direction, param)
        part = tablo.parse_board(html, direction, base_date=d)
        log(f"    получено строк: {len(part)}")
        flights.extend(part)
    return flights


def _detect_site_today(pc_today: dt.date,
                       log: Callable[[str], None]) -> dt.date:
    """
    Определить, какую дату сайт считает «сегодня» (см. tablo.detect_site_today).
    При любой ошибке — тихо возвращаемся к дате компьютера, чтобы программа
    не падала, а просто вела себя как раньше.
    """
    try:
        html = tablo.fetch(tablo.ARR, tablo.DAY_THIS)
        probe = tablo.parse_board(html, tablo.ARR, base_date=pc_today)
        site_today = tablo.detect_site_today(probe)
    except Exception as e:
        log(f"  ! не удалось определить дату сайта, беру дату компьютера: {e}")
        return pc_today

    if site_today is None:
        return pc_today
    if site_today != pc_today:
        log(f"  Часы компьютера показывают {pc_today:%d.%m}, "
           f"а сайт считает «сегодня» {site_today:%d.%m} — ориентируюсь на сайт.")
    return site_today


def build_schedule(now: dt.datetime | None = None,
                   log: Callable[[str], None] = print):
    """
    Вернуть (shift, arr_rows, dep_rows) для текущей/ближайшей смены.
    """
    if now is None:
        now = dt.datetime.now()
    shift: Shift = shifts.current_or_next_shift(now)
    log(f"Смена: {shift.human()}")

    # «сегодня» для выбора вчера/сегодня/завтра на сайте определяем по
    # самому сайту, а не по часам ПК — иначе расхождение часовых поясов
    # (сайт живёт по МСК) может незаметно подсунуть не ту дату.
    today = _detect_site_today(now.date(), log)
    wanted_dates = sorted({shift.start.date(), shift.end.date()})
    date_params: list[tuple[dt.date, str]] = []
    skipped: list[dt.date] = []
    for d in wanted_dates:
        p = _day_param(d, today)
        if p is None:
            log(f"  ! дата {d:%d.%m} вне диапазона табло (вчера/сегодня/завтра) — пропуск")
            skipped.append(d)
            continue
        date_params.append((d, p))

    if not date_params:
        raise RuntimeError("Нужные даты вне диапазона сайта. Запустите ближе к началу смены.")

    arr = _collect(tablo.ARR, date_params, log)
    dep = _collect(tablo.DEP, date_params, log)

    arr_rows = builder.build_rows(arr, shift)
    dep_rows = builder.build_rows(dep, shift)
    log(f"В смену попадает: прилётов {len(arr_rows)}, вылетов {len(dep_rows)}")
    return shift, arr_rows, dep_rows, skipped


def make_document(output_dir: str, now: dt.datetime | None = None,
                  log: Callable[[str], None] = print) -> tuple[str, Shift]:
    shift, arr_rows, dep_rows, skipped = build_schedule(now, log)
    os.makedirs(output_dir, exist_ok=True)
    kind = "день" if shift.kind == shifts.DAY else "ночь"
    fname = f"Расписание_{shift.start:%Y-%m-%d}_{kind}.docx"
    out_path = os.path.join(output_dir, fname)

    if skipped:
        dates_str = ", ".join(f"{d:%d.%m}" for d in skipped)
        log(f"  ! ВНИМАНИЕ: табло за {dates_str} ещё недоступно на сайте "
           f"(показывает только вчера/сегодня/завтра). Часть рейсов "
           f"смены может отсутствовать — запустите программу заново "
           f"позже, ближе к началу смены.")

    docxgen.build_document(arr_rows, dep_rows, out_path, caption=shift.human())
    log(f"Документ сохранён: {out_path}")
    return out_path, shift
