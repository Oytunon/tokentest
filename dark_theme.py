"""Shared dark theme for the tkinter tools in this project."""

import tkinter as tk
from tkinter import ttk

BG = "#1e1e1e"
PANEL_BG = "#252526"
FG = "#e0e0e0"
MUTED_FG = "#a0a0a0"
ENTRY_BG = "#2d2d2d"
SELECT_BG = "#094771"
BTN_BG = "#3c3c3c"
BTN_ACTIVE = "#505050"
ACCENT = "#4fc3f7"

OK_BG = "#14301a"
OK_FG = "#a5d6a7"
FAIL_BG = "#3a1414"
FAIL_FG = "#ef9a9a"
OTHER_BG = "#3a3014"
OTHER_FG = "#fff59d"
RATE_BG = "#3a2414"
RATE_FG = "#ffcc80"


def apply_dark_theme(root: tk.Tk) -> None:
    root.configure(bg=BG)

    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", background=BG, foreground=FG, fieldbackground=ENTRY_BG, borderwidth=1)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=FG)
    style.configure("TLabelframe", background=BG, foreground=FG)
    style.configure("TLabelframe.Label", background=BG, foreground=FG)
    style.configure("TButton", background=BTN_BG, foreground=FG, borderwidth=1)
    style.map(
        "TButton",
        background=[("active", BTN_ACTIVE), ("disabled", "#2a2a2a")],
        foreground=[("disabled", MUTED_FG)],
    )
    style.configure("TCheckbutton", background=BG, foreground=FG)
    style.map("TCheckbutton", background=[("active", BG)])
    style.configure("TEntry", fieldbackground=ENTRY_BG, foreground=FG, insertcolor=FG)
    style.configure("TPanedwindow", background=BG)
    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure("TNotebook.Tab", background=BTN_BG, foreground=FG, padding=[16, 8])
    style.map(
        "TNotebook.Tab",
        background=[("selected", PANEL_BG), ("active", BTN_ACTIVE)],
        foreground=[("selected", ACCENT)],
    )
    style.configure(
        "Horizontal.TProgressbar", background=ACCENT, troughcolor=ENTRY_BG, borderwidth=0
    )


def style_text_widget(widget: tk.Text, bg: str = ENTRY_BG, fg: str = FG) -> None:
    widget.configure(
        bg=bg,
        fg=fg,
        insertbackground=fg,
        selectbackground=SELECT_BG,
        selectforeground=FG,
        highlightthickness=1,
        highlightbackground=BG,
        highlightcolor=ACCENT,
    )


def style_menu(menu: tk.Menu) -> None:
    menu.configure(
        bg=PANEL_BG,
        fg=FG,
        activebackground=SELECT_BG,
        activeforeground=FG,
        borderwidth=0,
    )
