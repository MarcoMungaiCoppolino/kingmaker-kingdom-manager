"""Keeping the launcher's windows inside the screen.

A Tk window takes the size its content asks for, and Windows lets it run past
the bottom of the screen. The launcher's windows asked for up to 850 px, and
a laptop has 720 or less to give once the taskbar is counted (1366 × 768, or
1920 × 1080 at 150 %): the lower part of the window — the log, the links, the
buttons of the set-up wizards — went where nothing could reach it.

So every window of the launcher is built the same way: its content in a
`Scrolled` frame, which is as tall as the content and grows a scroll bar
only when the window is shorter; the buttons that close a dialog outside it,
pinned at the bottom; and `settle`, which keeps the window no larger than the
work area and entirely inside it. A `Scrolled` calls `settle` by itself
whenever its content changes size; a window without one calls it once built.
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

# The title bar and the borders around the client area, (width, height),
# for as long as the window is not on screen to be measured.
DECOR = (16, 39)
# A panel or a dock somewhere, where the work area cannot be asked for.
PANEL = 48
# Room for the scroll bar, which appears once the window is cut short.
BAR = 20
# Pixels per notch of the wheel. The canvas scrolls by single pixels: any
# coarser step rounds the position, and the last few pixels of the content
# could never be reached.
WHEEL = 48
# Widgets that scroll themselves: the wheel over them is theirs.
OWN_WHEEL = {"Text", "Listbox", "TCombobox", "TSpinbox", "Spinbox"}


def work_area(win: tk.Misc) -> tuple[int, int, int, int]:
    """(x, y, width, height) of the screen `win` is on, less the taskbar."""
    if sys.platform == "win32":
        for widget in (win, win.master):
            area = _windows_work_area(widget)
            if area is not None:
                return area
    return 0, 0, win.winfo_screenwidth(), win.winfo_screenheight() - PANEL


def _windows_work_area(widget: tk.Misc | None) -> tuple[int, int, int, int] | None:
    """The work area of the monitor holding `widget`'s window, or of the
    primary one when the window is not on screen yet."""
    try:
        import ctypes
        from ctypes import wintypes

        class MonitorInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        user32 = ctypes.windll.user32
        rect = None
        if widget is not None and widget.winfo_ismapped():
            hwnd = int(widget.winfo_toplevel().wm_frame(), 16)
            monitor = user32.MonitorFromWindow(wintypes.HWND(hwnd), 2)   # MONITOR_DEFAULTTONEAREST
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(MonitorInfo)
            if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                rect = info.rcWork
        elif widget is None:
            return None
        if rect is None:
            rect = wintypes.RECT()
            if not user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):   # SPI_GETWORKAREA
                return None
        return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
    except (AttributeError, OSError, ValueError, tk.TclError):
        return None


def decor(win: tk.Misc) -> tuple[int, int]:
    """What the title bar and the borders add to the client area."""
    if win.winfo_ismapped():
        left, top = win.winfo_rootx() - win.winfo_x(), win.winfo_rooty() - win.winfo_y()
        if left >= 0 and top > 0:
            return 2 * left, top + left
    return DECOR


def room(win: tk.Misc) -> tuple[int, int]:
    """How much wider and taller `win` could grow and still fit its work
    area, content as it is now."""
    win.update_idletasks()
    for scrolled in _scrolled_in(win):
        scrolled.refit(settle_after=False)
    win.update_idletasks()
    _x, _y, width, height = work_area(win)
    extra_w, extra_h = decor(win)
    return width - extra_w - win.winfo_reqwidth(), height - extra_h - win.winfo_reqheight()


def settle(win: tk.Misc) -> None:
    """Keeps `win` no larger than its work area and entirely inside it.

    Too tall for it, the window is given the height there is, and the
    content scrolls; back to fitting, it takes its own size again. A window
    not yet on screen is centred on its parent, or on the screen."""
    try:
        if not win.winfo_exists() or win.state() in ("iconic", "zoomed"):
            return
    except tk.TclError:
        return
    win.update_idletasks()
    area_x, area_y, area_w, area_h = work_area(win)
    extra_w, extra_h = decor(win)
    most_w, most_h = area_w - extra_w, area_h - extra_h
    want_w, want_h = win.winfo_reqwidth(), win.winfo_reqheight()
    mapped = win.winfo_ismapped()
    if want_w <= most_w and want_h <= most_h:
        if getattr(win, "_km_capped", False):
            win.geometry("")
            win._km_capped = False          # type: ignore[attr-defined]
            width, height = want_w, want_h
        elif mapped:
            width, height = win.winfo_width(), win.winfo_height()
        else:
            width, height = want_w, want_h
    else:
        width = min(want_w + (BAR if want_h > most_h else 0), most_w)
        height = min(want_h, most_h)
        win.geometry(f"{width}x{height}")
        win._km_capped = True               # type: ignore[attr-defined]
    low_w, low_h = win.minsize()
    if low_w > most_w or low_h > most_h:
        win.minsize(min(low_w, most_w), min(low_h, most_h))

    if mapped:
        x, y = win.winfo_x(), win.winfo_y()
    else:
        parent = win.master.winfo_toplevel() if win.master is not None else None
        if parent is not None and parent is not win and parent.winfo_ismapped():
            x = parent.winfo_x() + (parent.winfo_width() - width) // 2
            y = parent.winfo_y() + (parent.winfo_height() - height) // 3
        else:
            x = area_x + (area_w - width - extra_w) // 2
            y = area_y + (area_h - height - extra_h) // 3
    new_x = max(area_x, min(x, area_x + area_w - width - extra_w))
    new_y = max(area_y, min(y, area_y + area_h - height - extra_h))
    if not mapped or (new_x, new_y) != (x, y):
        win.geometry(f"+{new_x}+{new_y}")


def present(win: tk.Misc, grab: bool = False) -> None:
    """Shows a window built withdrawn, already sized and placed: withdrawn
    right after it was made, because the first layout pass would otherwise
    put it on screen wherever the system chooses, before `settle` could."""
    settle(win)
    win.deiconify()
    if grab:
        win.wait_visibility()
        win.grab_set()


def settle_soon(win: tk.Misc) -> None:
    """`settle` once the current burst of layout is over."""
    if getattr(win, "_km_settling", False):
        return
    win._km_settling = True                 # type: ignore[attr-defined]

    def run() -> None:
        win._km_settling = False            # type: ignore[attr-defined]
        settle(win)

    win.after_idle(run)


class Scrolled(ttk.Frame):
    """A frame whose content scrolls up and down when the window is
    shorter than it: the content goes in `inner`. Until then it is exactly
    as tall as the content, and has no scroll bar."""

    def __init__(self, parent: tk.Misc, **options) -> None:
        super().__init__(parent, **options)
        background = ttk.Style(self).lookup("TFrame", "background") or None
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, background=background,
                                width=1, height=1, yscrollincrement=1)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = ttk.Frame(self.canvas)
        self.item = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda _e: self.refit(), add="+")
        self.canvas.bind("<Configure>", lambda _e: self.follow(), add="+")
        root = self._root()
        if not getattr(root, "_km_scrolled", False):
            # Once per Tk: the wheel and the focus of any widget find the
            # Scrolled that holds it, walking up from the widget.
            root._km_scrolled = True        # type: ignore[attr-defined]
            for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                root.bind_all(sequence, _wheel, add="+")
            root.bind_all("<FocusIn>", _focused, add="+")

    def refit(self, settle_after: bool = True) -> None:
        """The canvas asks for the size of the content, and the window
        follows as far as `settle` lets it."""
        width, height = self.inner.winfo_reqwidth(), self.inner.winfo_reqheight()
        if (int(self.canvas.cget("width")), int(self.canvas.cget("height"))) != (width, height):
            self.canvas.configure(width=width, height=height)
        self.follow()
        if settle_after:
            settle_soon(self.winfo_toplevel())

    def follow(self) -> None:
        """The content as wide as the canvas; the bar when it is taller."""
        width = self.canvas.winfo_width()
        if width > 1 and int(self.canvas.itemcget(self.item, "width") or 0) != width:
            self.canvas.itemconfigure(self.item, width=width)
        height = self.inner.winfo_reqheight()
        self.canvas.configure(scrollregion=(0, 0, max(width, 1), height))
        needed = self.canvas.winfo_height() > 1 and height > self.canvas.winfo_height()
        if needed and not self.bar.winfo_ismapped():
            self.bar.pack(side="right", fill="y", before=self.canvas)
        elif not needed and self.bar.winfo_ismapped():
            self.bar.pack_forget()
            self.canvas.yview_moveto(0)

    def scrolling(self) -> bool:
        return self.inner.winfo_reqheight() > self.canvas.winfo_height() > 1

    def to_top(self) -> None:
        self.canvas.yview_moveto(0)

    def see(self, widget: tk.Misc) -> None:
        """Scrolls just enough for `widget` to be in view."""
        if not self.scrolling():
            return
        top = widget.winfo_rooty() - self.inner.winfo_rooty()
        bottom = top + widget.winfo_height()
        total = self.inner.winfo_reqheight()
        view_top = self.canvas.canvasy(0)
        view_bottom = view_top + self.canvas.winfo_height()
        if top < view_top:
            self.canvas.yview_moveto(top / total)
        elif bottom > view_bottom:
            self.canvas.yview_moveto((bottom - self.canvas.winfo_height()) / total)


def _holder(widget) -> Scrolled | None:
    while widget is not None:
        if isinstance(widget, Scrolled):
            return widget
        widget = getattr(widget, "master", None)
    return None


def _scrolled_in(win: tk.Misc) -> list[Scrolled]:
    found, stack = [], [win]
    while stack:
        widget = stack.pop()
        if isinstance(widget, Scrolled):
            found.append(widget)
        stack.extend(widget.winfo_children())
    return found


def _wheel(event) -> None:
    widget = event.widget
    if isinstance(widget, str) or widget.winfo_class() in OWN_WHEEL:
        return
    scrolled = _holder(widget)
    if scrolled is None or not scrolled.scrolling():
        return
    if event.num == 4 or getattr(event, "delta", 0) > 0:
        scrolled.canvas.yview_scroll(-WHEEL, "units")
    elif event.num == 5 or getattr(event, "delta", 0) < 0:
        scrolled.canvas.yview_scroll(WHEEL, "units")


def _focused(event) -> None:
    """Tab onto a field or a button out of view brings it into view."""
    widget = event.widget
    if isinstance(widget, str):
        return
    scrolled = _holder(widget)
    if scrolled is not None and widget is not scrolled.canvas:
        scrolled.see(widget)
