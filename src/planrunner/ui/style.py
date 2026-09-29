"""Look and feel, carried over from ScriptRunner (``scriptrunner/lib/utilities.py``)."""

import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from planrunner.status_text import Tone

FONT_FAMILY = "Segoe UI" if os.name == "nt" else "Helvetica"
FONT_SIZE = 12
PARAM_FONT_SIZE = 11
CONSOLE_FONT = ("Courier New", 10)
TTK_THEME = "clam"
MAIN_WINDOW_RATIO = 0.85

BG_OUTPUT = "#f0f0f0"
FG_OUTPUT = "black"
LIST_SELECT_BG = "#cce8ff"
LIST_SELECT_FG = "black"
ACCENT = "#0055aa"
HELP_FG = "#555555"
ERROR_FG = "#c00000"
RUNNING_BG = "#dff5e1"

TONE_COLORS = {
    Tone.NORMAL: "#222222",
    Tone.GOOD: "#1a7f37",
    Tone.BUSY: "#0055aa",
    Tone.WARN: "#b35900",
    Tone.BAD: "#c00000",
}


def apply_style(root: tk.Tk) -> ttk.Style:
    style = ttk.Style(root)
    style.theme_use(TTK_THEME)
    default_font = tkfont.nametofont("TkDefaultFont")
    default_font.configure(family=FONT_FAMILY, size=FONT_SIZE)
    root.option_add("*Font", default_font)
    style.configure("TButton", padding=5)
    style.configure("TEntry", padding=5)
    style.configure("TLabelframe", padding=5)
    style.configure("TLabelframe.Label", font=(FONT_FAMILY, FONT_SIZE), foreground="#333")
    style.configure("Path.TLabel", foreground=ACCENT, font=(FONT_FAMILY, FONT_SIZE, "italic"))
    style.configure("Title.TLabel", foreground=ACCENT, font=(FONT_FAMILY, FONT_SIZE + 1, "bold"))
    style.configure("Help.TLabel", foreground=HELP_FG, font=(FONT_FAMILY, PARAM_FONT_SIZE))
    style.configure("Error.TLabel", foreground=ERROR_FG, font=(FONT_FAMILY, PARAM_FONT_SIZE))
    style.configure("Param.TLabel", font=(FONT_FAMILY, PARAM_FONT_SIZE))
    style.configure("Required.TLabel", font=(FONT_FAMILY, PARAM_FONT_SIZE, "bold"))
    style.configure("Type.TLabel", foreground=ACCENT, font=(FONT_FAMILY, PARAM_FONT_SIZE))
    style.configure("Treeview", rowheight=25)
    style.configure("Toggle.TButton", font=(FONT_FAMILY, 11))
    style.configure("Small.TButton", padding=2, font=(FONT_FAMILY, 9))
    style.configure("StatusName.TLabel", foreground="#666", font=(FONT_FAMILY, 10))
    for tone, color in TONE_COLORS.items():
        style.configure(f"{tone.value}.Status.TLabel", foreground=color,
                        font=(FONT_FAMILY, 11, "bold"))
    return style
