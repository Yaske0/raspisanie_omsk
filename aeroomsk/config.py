# -*- coding: utf-8 -*-
"""
Необязательный файл настроек config.json рядом с программой.

Пример содержимого:
{
    "anchor_day_shift": "2026-06-25",
    "printer_name": "",
    "auto_print": true,
    "output_dir": ""
}

Если файла нет — берутся значения по умолчанию из shifts.py.
Менять config.json можно блокнотом, пересобирать программу не нужно.
"""

from __future__ import annotations

import json
import os
import sys
import datetime as dt
from dataclasses import dataclass

from . import shifts


def app_dir() -> str:
    """Папка, где лежит exe (или скрипт)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass
class Config:
    anchor_day_shift: dt.date
    printer_name: str
    auto_print: bool
    output_dir: str


def load() -> Config:
    path = os.path.join(app_dir(), "config.json")
    data = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print("config.json прочитать не удалось, беру значения по умолчанию:", e)

    anchor = shifts.ANCHOR_DAY_SHIFT
    if data.get("anchor_day_shift"):
        try:
            anchor = dt.date.fromisoformat(data["anchor_day_shift"])
        except Exception:
            pass
    # применим якорь к модулю смен
    shifts.ANCHOR_DAY_SHIFT = anchor

    out = data.get("output_dir") or os.path.join(app_dir(), "Расписания")
    return Config(
        anchor_day_shift=anchor,
        printer_name=data.get("printer_name", "") or "",
        auto_print=bool(data.get("auto_print", True)),
        output_dir=out,
    )
