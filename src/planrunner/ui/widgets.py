"""Small reusable Tk building blocks."""

import tkinter as tk
from tkinter import ttk


class ScrollableFrame:
    """A frame whose content scrolls vertically (canvas + scrollbar + inner frame).

    Put widgets in ``content``; place ``frame`` in the layout.
    """

    def __init__(self, parent: tk.Misc) -> None:
        self.frame = ttk.Frame(parent)
        background = ttk.Style().lookup("TFrame", "background")
        self._canvas = tk.Canvas(self.frame, highlightthickness=0, bg=background)
        scrollbar = ttk.Scrollbar(self.frame, orient="vertical", command=self._canvas.yview)
        self.content = ttk.Frame(self._canvas)
        window = self._canvas.create_window((0, 0), window=self.content, anchor="nw")

        self.content.bind(
            "<Configure>",
            lambda _: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        self._canvas.bind(
            "<Configure>", lambda e: self._canvas.itemconfigure(window, width=e.width)
        )
        self._canvas.configure(yscrollcommand=scrollbar.set)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=5)
        self._canvas.bind("<Enter>", lambda _: self._bind_wheel())
        self._canvas.bind("<Leave>", lambda _: self._unbind_wheel())

    def clear(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()
        self._canvas.yview_moveto(0)

    def _bind_wheel(self) -> None:
        self._canvas.bind_all("<MouseWheel>", self._on_wheel)
        self._canvas.bind_all("<Button-4>", self._on_wheel)
        self._canvas.bind_all("<Button-5>", self._on_wheel)

    def _unbind_wheel(self) -> None:
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self._canvas.unbind_all(sequence)

    def _on_wheel(self, event: tk.Event) -> None:
        if event.num == 4:
            step = -1
        elif event.num == 5:
            step = 1
        else:
            step = -1 if event.delta > 0 else 1
        self._canvas.yview_scroll(step, "units")


class ReadOnlyText:
    """A disabled ``Text`` with a scrollbar, for details panes."""

    def __init__(self, parent: tk.Misc, height: int = 6) -> None:
        self.frame = ttk.Frame(parent)
        self._text = tk.Text(self.frame, height=height, wrap="word", state=tk.DISABLED,
                             bd=0, highlightthickness=0, padx=5, pady=5)
        scrollbar = ttk.Scrollbar(self.frame, orient="vertical", command=self._text.yview)
        self._text.configure(yscrollcommand=scrollbar.set)
        self._text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def set(self, text: str) -> None:
        self._text.configure(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        self._text.insert("1.0", text)
        self._text.configure(state=tk.DISABLED)


def set_enabled(widget: ttk.Widget, enabled: bool) -> None:
    widget.state(["!disabled"] if enabled else ["disabled"])
