"""Top bar: server address, API key, connect, and the RE worker environment.

Takes the place of ScriptRunner's "Base folder path" bar.
"""

import tkinter as tk
from tkinter import ttk

from planrunner.controllers.connection import ConnectionForm, ConnectionHandlers
from planrunner.status_text import Tone
from planrunner.ui.widgets import set_enabled

_STATES = {
    "disconnected": ("○ Not connected", Tone.WARN),
    "connecting": ("… Connecting", Tone.BUSY),
    "connected": ("● Connected", Tone.GOOD),
    "unreachable": ("⚠ Unreachable", Tone.BAD),
}


class ConnectionBar:
    def __init__(self, parent: tk.Misc) -> None:
        self.frame = ttk.Frame(parent, relief="groove", borderwidth=1)
        self.frame.grid_columnconfigure(1, weight=1)
        self._uri = tk.StringVar()
        self._api_key = tk.StringVar()

        ttk.Label(self.frame, text="Server:").grid(row=0, column=0, padx=5, pady=5)
        self._uri_entry = ttk.Entry(self.frame, textvariable=self._uri)
        self._uri_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=5)
        ttk.Label(self.frame, text="API key:").grid(row=0, column=2, padx=(10, 5), pady=5)
        ttk.Entry(self.frame, textvariable=self._api_key, show="•", width=18).grid(
            row=0, column=3, padx=5, pady=5
        )
        self._connect = ttk.Button(self.frame, text="Connect")
        self._connect.grid(row=0, column=4, padx=5, pady=5)
        self._disconnect = ttk.Button(self.frame, text="Disconnect")
        self._disconnect.grid(row=0, column=5, padx=(0, 5), pady=5)
        self._indicator = ttk.Label(self.frame, width=15)
        self._indicator.grid(row=0, column=6, padx=5, pady=5)

        ttk.Separator(self.frame, orient="vertical").grid(row=0, column=7, sticky="ns", padx=5)
        ttk.Label(self.frame, text="Environment:").grid(row=0, column=8, padx=5, pady=5)
        self._open_env = ttk.Button(self.frame, text="Open")
        self._open_env.grid(row=0, column=9, padx=(0, 5), pady=5)
        self._close_env = ttk.Button(self.frame, text="Close")
        self._close_env.grid(row=0, column=10, padx=(0, 5), pady=5)

    def set_handlers(self, handlers: ConnectionHandlers) -> None:
        self._connect.configure(command=handlers.on_connect)
        self._disconnect.configure(command=handlers.on_disconnect)
        self._open_env.configure(command=handlers.on_open_environment)
        self._close_env.configure(command=handlers.on_close_environment)
        self._uri_entry.bind("<Return>", lambda _: handlers.on_connect())

    def read_form(self) -> ConnectionForm:
        return ConnectionForm(uri=self._uri.get(), api_key=self._api_key.get())

    def fill_form(self, form: ConnectionForm) -> None:
        self._uri.set(form.uri)
        self._api_key.set(form.api_key)

    def show_connection(self, state: str) -> None:
        text, tone = _STATES[state]
        self._indicator.configure(text=text, style=f"{tone.value}.Status.TLabel")
        set_enabled(self._connect, state != "connecting")
        set_enabled(self._disconnect, state in ("connected", "unreachable"))

    def enable_environment_buttons(self, can_open: bool, can_close: bool) -> None:
        set_enabled(self._open_env, can_open)
        set_enabled(self._close_env, can_close)
