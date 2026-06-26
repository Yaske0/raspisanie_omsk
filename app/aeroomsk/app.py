# -*- coding: utf-8 -*-
"""
Современное окно с одной кнопкой: «Создать и напечатать».

Тёмно-синяя «авиационная» тема, скруглённые кнопки, бегущий динозаврик
во время работы и меняющаяся подпись под ним.

Все размеры масштабируются под DPI Windows (100/125/150 %), поэтому при
увеличенном масштабе текст не вылезает за кнопки, а окно растёт целиком.
"""

from __future__ import annotations

import os
import sys
import queue
import threading
import datetime as dt
import tkinter as tk

from . import core, printing, shifts
from . import config as cfg

# --- Палитра (тёмно-синяя, авиационная) -----------------------------------
BG_TOP = "#0A1B33"
BG_BOTTOM = "#0E2A4E"
PANEL = "#13355F"
PANEL_LINE = "#1E4A7E"
ACCENT = "#2D9CDB"
ACCENT_HOVER = "#3DAEE9"
ACCENT_PRESS = "#1E7FB8"
TEXT = "#EAF2FB"
TEXT_MUTED = "#9DB4CF"
LOG_BG = "#0C2240"
LOG_FG = "#CFE2F5"
DINO = "#6FCF6A"
DINO_DARK = "#3E8E3A"
CASE = "#C9842B"
BTN_BG = "#0B2039"

FONT_FAMILY = "Segoe UI"
W, H = 820, 660                       # логические размеры (при 100 %)

LOADING_MESSAGES = [
    "Что-то ищем…",
    "Что-то считаю…",
    "Опрашиваю табло…",
    "Собираю рейсы…",
]


def _enable_dpi_awareness():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _round_rect_points(x1, y1, x2, y2, r):
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


class RoundedButton(tk.Canvas):
    """Плоская скруглённая кнопка. Размеры/шрифт приходят уже с учётом масштаба."""

    def __init__(self, master, text, command, kind, width, height, radius, font):
        super().__init__(master, width=width, height=height,
                         bg=BTN_BG, highlightthickness=0, bd=0)
        self.command = command
        self.kind = kind
        self._enabled = True

        if kind == "primary":
            self.c_norm, self.c_hover, self.c_press = ACCENT, ACCENT_HOVER, ACCENT_PRESS
            self.fg, self.outline = "#FFFFFF", ""
        else:
            self.c_norm, self.c_hover, self.c_press = PANEL, PANEL_LINE, "#0F2A4C"
            self.fg, self.outline = TEXT, ACCENT

        inset = max(2, radius // 7)
        pts = _round_rect_points(inset, inset, width - inset, height - inset, radius)
        self.shape = self.create_polygon(
            pts, smooth=True, fill=self.c_norm,
            outline=self.outline, width=1.5 if self.outline else 0)
        self.label = self.create_text(width / 2, height / 2, text=text,
                                      fill=self.fg, font=font)

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _fill(self, color):
        self.itemconfig(self.shape, fill=color)

    def _on_enter(self, _):
        if self._enabled:
            self._fill(self.c_hover); self.configure(cursor="hand2")

    def _on_leave(self, _):
        if self._enabled:
            self._fill(self.c_norm)

    def _on_press(self, _):
        if self._enabled:
            self._fill(self.c_press)

    def _on_release(self, _):
        if self._enabled:
            self._fill(self.c_hover)
            if callable(self.command):
                self.command()

    def set_enabled(self, value: bool):
        self._enabled = value
        if value:
            self._fill(self.c_norm); self.itemconfig(self.label, fill=self.fg)
        else:
            self._fill("#22405F" if self.kind == "primary" else PANEL)
            self.itemconfig(self.label, fill=TEXT_MUTED)


class App(tk.Tk):
    DINO_CX = 410
    DINO_BASE = 372

    def __init__(self):
        super().__init__()
        self.title("Расписание смены — Омск")
        self.configure(bg=BG_TOP)

        self.s = self._detect_scale()          # коэффициент масштаба Windows

        self.cfg = cfg.load()
        self._q: queue.Queue[str] = queue.Queue()
        self._busy = False
        self._msg_idx = 0
        self._msg_after = None
        self._dino_after = None
        self._phase = 0
        self._ground_x = 0
        self._frames = []
        self._gif_idx = 0

        self.geometry(f"{self.px(W)}x{self.px(H)}")
        self.resizable(False, False)

        gif = os.path.join(cfg.app_dir(), "loading.gif")
        if os.path.exists(gif):
            self._load_gif(gif)

        self._build_ui()
        self._refresh_shift_label()
        self._dino_static()
        self.after(120, self._drain_log)

    # --- масштаб -----------------------------------------------------------
    def _detect_scale(self) -> float:
        s = 1.0
        try:
            s = self.winfo_fpixels("1i") / 96.0
        except Exception:
            pass
        if sys.platform == "win32":
            try:
                import ctypes
                self.update_idletasks()
                hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
                dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
                if dpi:
                    s = dpi / 96.0
            except Exception:
                pass
        return min(max(s, 1.0), 3.0)

    def px(self, v) -> int:
        return int(round(v * self.s))

    def _font(self, size, weight=None, slant=None):
        spec = [FONT_FAMILY, -self.px(size)]   # отриц. размер = пиксели (без двойного масштаба)
        if weight:
            spec.append(weight)
        if slant:
            spec.append(slant)
        return tuple(spec)

    # --- масштабирующие обёртки рисования на фоне --------------------------
    def _sc(self, coords):
        return [self.px(c) for c in coords]

    def _cline(self, *c, **kw):
        if "width" in kw:
            kw["width"] = max(1, self.px(kw["width"]))
        return self.bg.create_line(*self._sc(c), **kw)

    def _crect(self, *c, **kw):
        if "width" in kw:
            kw["width"] = max(1, self.px(kw["width"]))
        return self.bg.create_rectangle(*self._sc(c), **kw)

    def _coval(self, *c, **kw):
        if "width" in kw:
            kw["width"] = max(1, self.px(kw["width"]))
        return self.bg.create_oval(*self._sc(c), **kw)

    def _cpoly(self, *c, **kw):
        if "width" in kw:
            kw["width"] = max(1, self.px(kw["width"]))
        return self.bg.create_polygon(*self._sc(c), **kw)

    def _ctext(self, x, y, **kw):
        if "width" in kw:
            kw["width"] = self.px(kw["width"])
        return self.bg.create_text(self.px(x), self.px(y), **kw)

    # --- интерфейс ---------------------------------------------------------
    def _build_ui(self):
        self.bg = tk.Canvas(self, width=self.px(W), height=self.px(H),
                            highlightthickness=0, bd=0)
        self.bg.place(x=0, y=0)
        self._paint_gradient()

        self._ctext(40, 46, anchor="w", text="✈  Расписание смены",
                    fill=TEXT, font=self._font(26, "bold"))
        self._ctext(44, 80, anchor="w", text="Омский аэропорт",
                    fill=TEXT_MUTED, font=self._font(13))
        self._cline(40, 104, 780, 104, fill=PANEL_LINE)

        self._cpoly(*_round_rect_points(40, 122, 780, 178, 16),
                    smooth=True, fill=PANEL, outline=PANEL_LINE)
        self.shift_id = self._ctext(60, 150, anchor="w", text="…", fill=TEXT,
                                    font=self._font(13, "bold"), width=700)

        bf = self._font(13, "bold")
        self.btn_main = RoundedButton(self, "Создать и напечатать",
                                      self.on_create_print, "primary",
                                      self.px(270), self.px(54), self.px(14), bf)
        self.btn_main.place(x=self.px(40), y=self.px(200))
        self.btn_only = RoundedButton(self, "Только создать",
                                      self.on_create_only, "secondary",
                                      self.px(200), self.px(54), self.px(14), bf)
        self.btn_only.place(x=self.px(326), y=self.px(200))
        self.btn_open = RoundedButton(self, "Открыть папку",
                                      self.open_folder, "secondary",
                                      self.px(190), self.px(54), self.px(14), bf)
        self.btn_open.place(x=self.px(542), y=self.px(200))

        self.caption_id = self._ctext(self.DINO_CX, 402, text="", fill=ACCENT,
                                      font=self._font(13, slant="italic"))

        self._ctext(40, 422, anchor="w", text="Журнал",
                    fill=TEXT_MUTED, font=self._font(12, "bold"))
        self.log_box = tk.Text(self, wrap="word", bg=LOG_BG, fg=LOG_FG,
                              insertbackground=LOG_FG, relief="flat", bd=0,
                              padx=self.px(12), pady=self.px(10),
                              font=("Consolas", -self.px(12)))
        self.log_box.place(x=self.px(40), y=self.px(444),
                           width=self.px(740), height=self.px(190))
        self.log_box.configure(state="disabled")

    def _paint_gradient(self):
        h = self.px(H)
        w = self.px(W)
        r1, g1, b1 = self.winfo_rgb(BG_TOP)
        r2, g2, b2 = self.winfo_rgb(BG_BOTTOM)
        for i in range(h):
            r = int(r1 + (r2 - r1) * i / h) >> 8
            g = int(g1 + (g2 - g1) * i / h) >> 8
            b = int(b1 + (b2 - b1) * i / h) >> 8
            self.bg.create_line(0, i, w, i, fill=f"#{r:02x}{g:02x}{b:02x}")

    def _refresh_shift_label(self):
        s = shifts.current_or_next_shift()
        self.bg.itemconfig(self.shift_id,
                           text="Будет напечатано для:  " + s.human())

    # --- динозаврик --------------------------------------------------------
    def _load_gif(self, path):
        try:
            i = 0
            while True:
                self._frames.append(tk.PhotoImage(file=path, format=f"gif -index {i}"))
                i += 1
        except Exception:
            pass

    def _gif_at(self):
        self.bg.delete("dinogif")
        self.bg.create_image(self.px(self.DINO_CX), self.px(self.DINO_BASE - 40),
                            image=self._frames[self._gif_idx], tags="dinogif")

    def _dino_static(self):
        if self._frames:
            self._gif_idx = 0
            self._gif_at()
            return
        self._dino_ground()
        self._dino_draw(0, 0)

    def _dino_ground(self):
        self.bg.delete("ground")
        y = self.DINO_BASE + 14
        x = self.DINO_CX - 150 - (self._ground_x % 40)
        while x < self.DINO_CX + 150:
            self._crect(x, y, x + 22, y + 3, fill="#27497A", outline="", tags="ground")
            x += 40

    def _dino_draw(self, phase, bob):
        self.bg.delete("dino")
        cx = self.DINO_CX - 30
        base = self.DINO_BASE + bob
        top = base - 46
        t = "dino"
        self._cpoly(cx - 26, top + 22, cx - 50, top + 30, cx - 26, top + 34,
                    smooth=True, fill=DINO, outline=DINO_DARK, width=1, tags=t)
        self._coval(cx - 30, top + 8, cx + 26, top + 40,
                    fill=DINO, outline=DINO_DARK, width=1, tags=t)
        self._crect(cx + 14, top - 12, cx + 26, top + 18,
                    fill=DINO, outline=DINO_DARK, width=1, tags=t)
        self._coval(cx + 10, top - 26, cx + 42, top + 2,
                    fill=DINO, outline=DINO_DARK, width=1, tags=t)
        self._crect(cx + 34, top - 18, cx + 50, top - 6,
                    fill=DINO, outline=DINO_DARK, width=1, tags=t)
        self._coval(cx + 30, top - 20, cx + 38, top - 12, fill="#FFFFFF", outline="", tags=t)
        self._coval(cx + 33, top - 18, cx + 37, top - 14, fill="#0A1B33", outline="", tags=t)
        self._cline(cx + 6, top + 20, cx + 16, top + 30, fill=DINO_DARK, width=3, tags=t)
        self._crect(cx + 8, top + 30, cx + 30, top + 44,
                    fill=CASE, outline="#8A5A1E", width=1, tags=t)
        self._crect(cx + 16, top + 27, cx + 22, top + 31, fill="#8A5A1E", outline="", tags=t)
        if phase == 0:
            self._leg(cx - 12, base, -8); self._leg(cx + 10, base, 6)
        else:
            self._leg(cx - 12, base, 6); self._leg(cx + 10, base, -8)

    def _leg(self, x, base, dx):
        self._cline(x, base - 8, x + dx, base, fill=DINO_DARK, width=4,
                    tags="dino", capstyle="round")

    def _dino_start(self):
        if self._dino_after is None:
            self._dino_tick()

    def _dino_stop(self):
        if self._dino_after is not None:
            self.after_cancel(self._dino_after)
            self._dino_after = None
        self._dino_static()

    def _dino_tick(self):
        if self._frames:
            self._gif_idx = (self._gif_idx + 1) % len(self._frames)
            self._gif_at()
            self._dino_after = self.after(90, self._dino_tick)
            return
        self._phase ^= 1
        self._ground_x += 8
        self._dino_ground()
        self._dino_draw(self._phase, -2 if self._phase else 0)
        self._dino_after = self.after(130, self._dino_tick)

    # --- журнал ------------------------------------------------------------
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

    # --- подпись -----------------------------------------------------------
    def _cycle_caption(self):
        self.bg.itemconfig(self.caption_id,
                           text=LOADING_MESSAGES[self._msg_idx % len(LOADING_MESSAGES)])
        self._msg_idx += 1
        self._msg_after = self.after(1100, self._cycle_caption)

    def _stop_caption(self):
        if self._msg_after is not None:
            self.after_cancel(self._msg_after)
            self._msg_after = None
        self.bg.itemconfig(self.caption_id, text="")

    # --- действия ----------------------------------------------------------
    def on_create_print(self):
        self._run(do_print=True)

    def on_create_only(self):
        self._run(do_print=False)

    def _run(self, do_print: bool):
        if self._busy:
            return
        self._busy = True
        self.btn_main.set_enabled(False)
        self.btn_only.set_enabled(False)
        self._dino_start()
        self._cycle_caption()
        self.log("─" * 52)
        self.log(f"Старт: {dt.datetime.now():%d.%m.%Y %H:%M:%S}")
        threading.Thread(target=self._worker, args=(do_print,), daemon=True).start()

    def _worker(self, do_print: bool):
        try:
            path, _ = core.make_document(self.cfg.output_dir, log=self.log)
            if do_print and self.cfg.auto_print:
                self.log("Отправляю на печать…")
                ok = printing.print_docx(path, self.cfg.printer_name or None)
                self.log("Отправлено на принтер." if ok else
                         "Печать не выполнена (см. сообщения выше).")
            self.log("Готово.")
        except Exception as e:
            self.log(f"ОШИБКА: {e}")
        finally:
            self.after(0, self._on_done)

    def _on_done(self):
        self._busy = False
        self._dino_stop()
        self._stop_caption()
        self.btn_main.set_enabled(True)
        self.btn_only.set_enabled(True)
        self._refresh_shift_label()

    def open_folder(self):
        os.makedirs(self.cfg.output_dir, exist_ok=True)
        try:
            os.startfile(self.cfg.output_dir)  # type: ignore[attr-defined]
        except Exception:
            self.log("Папка: " + self.cfg.output_dir)


def main():
    _enable_dpi_awareness()
    App().mainloop()


if __name__ == "__main__":
    main()
