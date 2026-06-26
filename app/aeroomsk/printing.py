# -*- coding: utf-8 -*-
"""
Печать готового .docx на принтер Windows без диалогов.

Порядок попыток:
  1. Через Word (COM) — самый предсказуемый результат и точные шрифты;
     можно указать конкретный принтер, иначе печатает на принтер по умолчанию.
  2. ShellExecute "print" — системная печать ассоциированным приложением.
  3. os.startfile(path, "print") — крайний случай.

Всё работает только на Windows. На других ОС функция просто вернёт False.
"""

from __future__ import annotations

import os
import sys
import time


def print_docx(path: str, printer_name: str | None = None) -> bool:
    if sys.platform != "win32":
        print("Печать доступна только на Windows — файл сформирован, но не отправлен на принтер.")
        return False

    if _print_via_word(path, printer_name):
        return True
    if _print_via_shell(path):
        return True
    try:
        os.startfile(path, "print")  # type: ignore[attr-defined]
        return True
    except Exception as e:
        print("Не удалось отправить на печать:", e)
        return False


def _print_via_word(path: str, printer_name: str | None) -> bool:
    try:
        import win32com.client  # из пакета pywin32
        import pythoncom
        pythoncom.CoInitialize()
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = False
        try:
            if printer_name:
                try:
                    word.ActivePrinter = printer_name
                except Exception:
                    pass
            doc = word.Documents.Open(os.path.abspath(path), ReadOnly=True)
            doc.PrintOut(Background=False)
            time.sleep(1.5)  # дать заданию уйти в очередь
            doc.Close(SaveChanges=False)
            return True
        finally:
            word.Quit()
    except Exception as e:
        print("Word-печать недоступна:", e)
        return False


def _print_via_shell(path: str) -> bool:
    try:
        import win32api
        win32api.ShellExecute(0, "print", os.path.abspath(path), None, ".", 0)
        return True
    except Exception as e:
        print("ShellExecute-печать недоступна:", e)
        return False
