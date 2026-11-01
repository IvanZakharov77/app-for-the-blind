"""Vega's equalizer in the bottom-right corner while she listens or speaks (Ivan, 2026-11-01).

White rounded bars with a dark rim and shadow, so they show on light and dark windows alike.
While Vega speaks the bars jump like a music player's equalizer; while she only listens they
breathe low and calm. Straight bars are drawn crisply by old Windows (the earlier rainbow circle
came out jagged there). Only a few rectangle coordinates change per frame, so a weak laptop pays
about nothing; while hidden only a cheap timer runs. The window never takes the keyboard (screen
readers keep working) and lets mouse clicks through. Anything that fails here just leaves Vega
without the equalizer.
"""

import math
import random
import sys
import threading
import time

BARS = 7
BAR = 8           # bar width, pixels
GAP = 6
LOW = 0.12        # share of the full height a resting bar keeps
LISTEN = 0.28     # how high bars breathe while Vega only listens
WIDTH = BARS * BAR + (BARS - 1) * GAP + 8
HEIGHT = 72
FPS = 20
EASE = 0.3        # how quickly a bar reaches its new height each frame
ALPHA = 0.92
FADE_STEPS = 6
KEY = "#010203"   # the window colour that Windows makes fully transparent around the bars
WHITE = "#ffffff"
RIM = "#2b2b33"   # thin dark rim around each bar
SHADOW = "#18181e"
SHADOW_SHIFT = 2
MARGIN = 14       # pixels between the equalizer and the screen edges


def next_heights(heights, talking: bool, t: float, rng=random):
    """The bars' heights (0..1) one frame later."""
    result = []
    for index, height in enumerate(heights):
        if talking:
            goal = LOW + (1 - LOW) * rng.random() * (0.6 + 0.4 * math.sin(t * 3 + index))
            if rng.random() > 0.35:  # not every bar jumps every frame: looks like real sound
                goal = height
        else:
            goal = LOW + (LISTEN - LOW) * (1 + math.sin(t * 2.2 - index * 0.6)) / 2
        result.append(height + (goal - height) * EASE)
    return result


def bar_box(index: int, height: float):
    """(x0, y0, x1, y1) of a bar, centred vertically, inside the window without its shadow."""
    full = HEIGHT - 8 - SHADOW_SHIFT
    size = max(BAR, full * height)
    x0 = 4 + index * (BAR + GAP)
    y0 = (HEIGHT - SHADOW_SHIFT - size) / 2
    return x0, y0, x0 + BAR, y0 + size


class NoOrb:
    """When there is no screen or the equalizer could not start: the same calls, nothing happens."""

    def keep(self, seconds: float) -> None:
        pass

    def talk(self, seconds: float) -> None:
        pass

    def hide(self) -> None:
        pass

    def fade_soon(self, seconds: float) -> None:
        pass


class Orb(NoOrb):
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.visible_until = 0.0
        self.talking_until = 0.0
        self.thread = threading.Thread(target=self._run, name="vega-equalizer", daemon=True)
        self.thread.start()

    def keep(self, seconds: float) -> None:
        """Show the equalizer (if hidden) and keep it at least this long."""
        self.visible_until = max(self.visible_until, self.clock() + seconds)

    def talk(self, seconds: float) -> None:
        """Vega is speaking: the bars jump."""
        self.keep(seconds)
        self.talking_until = self.clock() + 0.3

    def hide(self) -> None:
        self.visible_until = 0.0
        self.talking_until = 0.0

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
        root.geometry("{}x{}+{}+{}".format(WIDTH, HEIGHT, right - WIDTH - MARGIN, bottom - HEIGHT - MARGIN))
        canvas = tkinter.Canvas(root, width=WIDTH, height=HEIGHT, bg=KEY, bd=0, highlightthickness=0)
        canvas.pack()
        shadows, bars = [], []
        for _ in range(BARS):  # round ends: a thick line with round caps
            shadows.append(canvas.create_line(0, 0, 0, 0, width=BAR + 2, fill=SHADOW, capstyle="round"))
        for _ in range(BARS):
            bars.append(canvas.create_line(0, 0, 0, 0, width=BAR + 2, fill=RIM, capstyle="round"))
            bars.append(canvas.create_line(0, 0, 0, 0, width=BAR - 1, fill=WHITE, capstyle="round"))
        _untouchable(root)  # mapped once, see-through at alpha 0 while hidden: showing it never moves focus
        state = {"fade": 0, "heights": [LOW] * BARS}
        started = self.clock()

        def place():
            for index, height in enumerate(state["heights"]):
                x0, y0, x1, y1 = bar_box(index, height)
                middle, cap = (x0 + x1) / 2, BAR / 2  # the round caps add half a bar at each end
                ends = (middle, y0 + cap, middle, max(y0 + cap, y1 - cap))
                canvas.coords(shadows[index], ends[0] + SHADOW_SHIFT, ends[1] + SHADOW_SHIFT,
                              ends[2] + SHADOW_SHIFT, ends[3] + SHADOW_SHIFT)
                canvas.coords(bars[2 * index], *ends)
                canvas.coords(bars[2 * index + 1], *ends)

        def tick():
            now = self.clock()
            wanted = now < self.visible_until
            if wanted or state["fade"] > 0:
                state["fade"] = min(FADE_STEPS, state["fade"] + 1) if wanted else state["fade"] - 1
                state["heights"] = next_heights(state["heights"], now < self.talking_until, now - started)
                place()
                root.attributes("-alpha", ALPHA * state["fade"] / FADE_STEPS)
                root.after(int(1000 / FPS), tick)
            else:
                state["heights"] = [LOW] * BARS
                root.after(100, tick)  # hidden: just look again soon, nothing is drawn

        place()
        root.after(100, tick)


def _work_area(root):
    """The screen without the taskbar, so the equalizer sits just above it."""
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
    if sys.platform == "win32" and type(ORB) is NoOrb:
        ORB = Orb()
