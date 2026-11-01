"""Vega's circle in the bottom-right corner while she listens or speaks (Ivan, 2026-11-01).

A rainbow circle like Siri's: colours turn once in LOOP seconds, the circle slowly breathes twice
in that time, it is a little see-through. It never takes the keyboard (screen readers keep working)
and lets mouse clicks through. All frames are drawn once at start in this thread, then only swapped
on screen, so a weak 2010s laptop pays about nothing; while the circle is hidden only a cheap timer
runs. Anything that fails here just leaves Vega without the circle.
"""

import math
import sys
import threading
import time
from typing import List, Optional

SIZE = 128
FPS = 12
LOOP = 7.0        # colours turn once; the circle breathes twice (3.5 s per breath)
BREATHS = 2
GROW = 0.06       # the circle is 6 % bigger at the top of a breath
ALPHA = 0.72      # about 30 % see-through
FADE_STEPS = 6
KEY = "#010203"   # the window colour that Windows makes fully transparent around the circle
EDGE = (24, 24, 36)  # outermost ring blends into this instead of KEY, so no coloured fringe shows
COLORS = ((0x3a, 0x7b, 0xff), (0x8f, 0x3d, 0xff), (0xff, 0x4f, 0xa3), (0xff, 0xb5, 0x47), (0x3a, 0xd1, 0xff))
CORE = (245, 240, 255)  # the light in the middle
MARGIN = 12       # pixels between the circle and the screen edges


def palette(steps: int = 360) -> List[tuple]:
    """COLORS around the circle, smoothly blended and closed on itself."""
    result = []
    count = len(COLORS)
    for step in range(steps):
        place = step * count / steps
        low = int(place)
        mix = place - low
        a, b = COLORS[low % count], COLORS[(low + 1) % count]
        mix = (1 - math.cos(mix * math.pi)) / 2  # softer than a straight blend
        result.append(tuple(int(a[i] + (b[i] - a[i]) * mix) for i in range(3)))
    return result


def _hex(color) -> str:
    return "#%02x%02x%02x" % color


def frame_rows(index: int, frames: int, size: int = SIZE, colors: Optional[List[tuple]] = None) -> List[List[str]]:
    """One frame as rows of «#rrggbb»; KEY outside the circle."""
    colors = colors or palette()
    t = index / frames
    turn = int(t * 360)
    breath = (1 - math.cos(2 * math.pi * BREATHS * t)) / 2
    full = size / 2 - 1
    radius = full / (1 + GROW) * (1 + GROW * breath)
    centre = (size - 1) / 2
    hx, hy, hr = centre - radius * 0.2, centre - radius * 0.3, radius * 0.75  # soft highlight, upper left
    rows = []
    for y in range(size):
        row = []
        dy = y - centre
        for x in range(size):
            dx = x - centre
            distance = math.hypot(dx, dy)
            if distance > radius:
                row.append(KEY)
                continue
            angle = int(math.degrees(math.atan2(dy, dx))) + turn
            r, g, b = colors[angle % 360]
            light = max(0.0, 1 - math.hypot(x - hx, y - hy) / hr)
            core = max(0.0, 1 - distance / (radius * 0.55))  # a soft glowing middle instead of a sharp pinwheel point
            light = min(0.85, 0.45 * light * light + 0.8 * core * core)
            r, g, b = r + (CORE[0] - r) * light, g + (CORE[1] - g) * light, b + (CORE[2] - b) * light
            shade = 1 - 0.18 * (distance / radius) ** 4  # slightly deeper colour towards the rim
            r, g, b = r * shade, g * shade, b * shade
            edge = radius - distance
            if edge < 1.5:  # the outermost pixels: blend into a dark rim instead of jagged colour
                keep = edge / 1.5
                r, g, b = (EDGE[0] + (r - EDGE[0]) * keep, EDGE[1] + (g - EDGE[1]) * keep, EDGE[2] + (b - EDGE[2]) * keep)
            row.append(_hex((int(r), int(g), int(b))))
        rows.append(row)
    return rows


class NoOrb:
    """When there is no screen or the circle could not start: the same calls, nothing happens."""

    def keep(self, seconds: float) -> None:
        pass

    def hide(self) -> None:
        pass

    def fade_soon(self, seconds: float) -> None:
        pass


class Orb(NoOrb):
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.visible_until = 0.0
        self.thread = threading.Thread(target=self._run, name="vega-orb", daemon=True)
        self.thread.start()

    def keep(self, seconds: float) -> None:
        """Show the circle (if hidden) and keep it at least this long."""
        self.visible_until = max(self.visible_until, self.clock() + seconds)

    def hide(self) -> None:
        self.visible_until = 0.0

    def fade_soon(self, seconds: float) -> None:
        """The answer is over: no longer kept for the listening time after «Привет, Вега»."""
        self.visible_until = min(self.visible_until, self.clock() + seconds)

    def _run(self) -> None:
        try:
            import tkinter
            root = tkinter.Tk()
        except Exception:
            return
        try:
            self._setup(root, tkinter)
            root.mainloop()
        except Exception:
            try:
                root.destroy()
            except Exception:
                pass

    def _setup(self, root, tkinter) -> None:
        root.withdraw()
        root.overrideredirect(True)
        root.configure(bg=KEY)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.0)
        try:
            root.attributes("-transparentcolor", KEY)
        except tkinter.TclError:
            pass
        left, top, right, bottom = _work_area(root)
        root.geometry("{0}x{0}+{1}+{2}".format(SIZE, right - SIZE - MARGIN, bottom - SIZE - MARGIN))
        label = tkinter.Label(root, bd=0, bg=KEY, highlightthickness=0)
        label.pack()
        _untouchable(root)  # mapped once, see-through at alpha 0 while hidden: showing it never moves focus
        frames: List = []
        state = {"fade": 0, "index": 0}
        colors = palette()
        count = int(LOOP * FPS)

        def draw_next():  # the frames are drawn a few at a time, so the timer below keeps running
            for _ in range(4):
                if len(frames) >= count:
                    return
                image = tkinter.PhotoImage(width=SIZE, height=SIZE)
                image.put(" ".join("{" + " ".join(row) + "}" for row in frame_rows(len(frames), count, colors=colors)))
                frames.append(image)
            root.after(1, draw_next)

        def tick():
            wanted = self.clock() < self.visible_until and len(frames) >= count
            if wanted or state["fade"] > 0:
                state["fade"] = min(FADE_STEPS, state["fade"] + 1) if wanted else state["fade"] - 1
                label.configure(image=frames[state["index"]])
                state["index"] = (state["index"] + 1) % count
                root.attributes("-alpha", ALPHA * state["fade"] / FADE_STEPS)
                root.after(int(1000 / FPS), tick)
            else:
                root.after(100, tick)  # hidden: just look again soon, nothing is drawn

        root.after(1, draw_next)
        root.after(100, tick)


def _work_area(root):
    """The screen without the taskbar, so the circle sits just above it."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
                return rect.left, rect.top, rect.right, rect.bottom
        except Exception:
            pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight() - 48


def _untouchable(root) -> None:
    """Never takes the keyboard from the window the person works in, lets clicks through, no taskbar button."""
    if sys.platform == "win32":
        import ctypes
        root.update_idletasks()
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
        style = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
        # WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOPMOST
        user32.SetWindowLongW(hwnd, -20, style | 0x08000000 | 0x80 | 0x20 | 0x80000 | 0x8)
        user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
    root.deiconify()


ORB = NoOrb()


def start() -> None:
    """Called once when the voice starts on Windows."""
    global ORB
    if sys.platform == "win32" and isinstance(ORB, NoOrb) and type(ORB) is NoOrb:
        ORB = Orb()
