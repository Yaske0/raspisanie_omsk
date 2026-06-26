# -*- coding: utf-8 -*-
"""
Окно с одной кнопкой: «Создать и напечатать».

Логика:
  нажатие -> определить смену -> выгрузить табло -> собрать Word -> печать.
Тяжёлая работа идёт в отдельном потоке, чтобы окно не «зависало».
"""

from __future__ import annotations

import os
import queue
import threading
import datetime as dt
import tkinter as tk
from tkinter import ttk, scrolledtext

from . import core, printing, shifts
from . import config as cfg


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Расписание смены — Омск")
        self.geometry("640x460")
        self.minsize(560, 420)

        self.cfg = cfg.load()
        self._q: queue.Queue[str] = queue.Queue()
        self._busy = False

        self._build_ui()
        self._refresh_shift_label()
        self.after(120, self._drain_log)

    # --- интерфейс ---------------------------------------------------------
    def _build_ui(self):
        pad = dict(padx=14, pady=6)

        self.shift_var = tk.StringVar(value="…")
        ttk.Label(self, textvariable=self.shift_var,
                  font=("Segoe UI", 11, "bold"), wraplength=600,
                  justify="left").pack(anchor="w", **pad)

        btns = ttk.Frame(self)
        btns.pack(fill="x", **pad)
        self.btn_main = ttk.Button(btns, text="Создать и напечатать",
                                   command=self.on_create_print)
        self.btn_main.pack(side="left", ipady=8, ipadx=10)
        self.btn_only = ttk.Button(btns, text="Только создать",
                                   command=self.on_create_only)
        self.btn_only.pack(side="left", padx=8)
        self.btn_open = ttk.Button(btns, text="Открыть папку",
                                   command=self.open_folder)
        self.btn_open.pack(side="left")

        ttk.Label(self, text="Журнал:").pack(anchor="w", padx=14)
        self.log_box = scrolledtext.ScrolledText(self, height=16, wrap="word",
                                                 font=("Consolas", 9))
        self.log_box.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self.log_box.configure(state="disabled")

    def _refresh_shift_label(self):
        s = shifts.current_or_next_shift()
        self.shift_var.set("Будет напечатано для: " + s.human())

    # --- журнал (поток-безопасно через очередь) ---------------------------
    def log(self, msg: str):
        self._q.put(msg)

    def _drain_log(self):
        try:
            while True:
                msg = self._q.get_nowait()
                self.log_box.configure(state="normal")
                self.log_box.insert("end", msg + "\n")
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(120, self._drain_log)

    # --- действия ----------------------------------------------------------
    def on_create_print(self):
        self._run(do_print=True)

    def on_create_only(self):
        self._run(do_print=False)

    def _run(self, do_print: bool):
        if self._busy:
            return
        self._busy = True
        self.btn_main.configure(state="disabled")
        self.btn_only.configure(state="disabled")
        self.log("─" * 50)
        self.log(f"Старт: {dt.datetime.now():%d.%m.%Y %H:%M:%S}")
        threading.Thread(target=self._worker, args=(do_print,), daemon=True).start()

    def _worker(self, do_print: bool):
        try:
            path, _ = core.make_document(self.cfg.output_dir, log=self.log)
            self._last_path = path
            if do_print and self.cfg.auto_print:
                self.log("Отправляю на печать…")
                ok = printing.print_docx(path, self.cfg.printer_name or None)
                self.log("Отправлено на принтер." if ok else
                         "Печать не выполнена (см. сообщения выше).")
            self.log("Готово.")
        except Exception as e:
            self.log(f"ОШИБКА: {e}")
        finally:
            self._busy = False
            self.btn_main.configure(state="normal")
            self.btn_only.configure(state="normal")
            self._refresh_shift_label()

    def open_folder(self):
        os.makedirs(self.cfg.output_dir, exist_ok=True)
        try:
            os.startfile(self.cfg.output_dir)  # type: ignore[attr-defined]
        except Exception:
            self.log("Папка: " + self.cfg.output_dir)


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
