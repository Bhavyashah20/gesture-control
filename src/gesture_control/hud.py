from __future__ import annotations

import tkinter as tk
from typing import Callable

from .state_machine import State

_LABELS = {
    State.DISARMED: "disarmed",
    State.ARMED_IDLE: "armed",
    State.TRACKING: "tracking",
    State.DRAG: "drag",
    State.SCROLL: "scroll",
}

_COLORS = {
    State.DISARMED: "#5F5E5A",
    State.ARMED_IDLE: "#185FA5",
    State.TRACKING: "#0F6E56",
    State.DRAG: "#993C1D",
    State.SCROLL: "#534AB7",
}


def state_label(state: State, present: bool) -> str:
    label = _LABELS[state]
    if state is not State.DISARMED and not present:
        return f"{label} (no hand)"
    return label


class Hud:
    """Always-on-top state pill that also drives the pipeline via after()."""

    def __init__(self, on_tick: Callable[[], None], tick_ms: int = 10) -> None:
        self._on_tick = on_tick
        self._tick_ms = tick_ms
        self._running = False

        self._root = tk.Tk()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", 0.88)
        self._root.geometry("+40+40")
        self._label = tk.Label(
            self._root, text="disarmed", fg="white", bg="#5F5E5A",
            font=("Helvetica", 13), padx=14, pady=6,
        )
        self._label.pack()
        self._root.bind_all("<Escape>", lambda _e: self.stop())

    def set_state(self, state: State, present: bool) -> None:
        self._label.config(text=state_label(state, present), bg=_COLORS[state])

    def _tick(self) -> None:
        if not self._running:
            return
        self._on_tick()
        self._root.after(self._tick_ms, self._tick)

    def run(self) -> None:
        self._running = True
        self._root.after(self._tick_ms, self._tick)
        self._root.mainloop()

    def stop(self) -> None:
        self._running = False
        try:
            self._root.destroy()
        except tk.TclError:
            pass
