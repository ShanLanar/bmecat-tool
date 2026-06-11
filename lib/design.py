# lib/design.py – Design-System für BMEcat Download-Tool
#
# Zentrale Design-Tokens, Widget-Factories und Hover-Helfer.
# Wird von main.py und allen Tab-Klassen verwendet.

import tkinter as tk
from tkinter import ttk

# ── Typografie ────────────────────────────────────────────────────────────────

FONT_UI     = ("Segoe UI",          10)
FONT_UI_SM  = ("Segoe UI",           8)
FONT_UI_MED = ("Segoe UI",          11)
FONT_HEAD   = ("Segoe UI Semibold", 12)
FONT_HEAD_L = ("Segoe UI Semibold", 14)
FONT_CAP    = ("Segoe UI",           7)   # Gruppenüberschriften
FONT_MONO   = ("Consolas",           9)
FONT_MONO_SM= ("Consolas",           8)

# ── Farb-Helfer ───────────────────────────────────────────────────────────────

def lighten(hex_color: str, amount: int = 20) -> str:
    """Hellt eine Hex-Farbe um amount (0–255) auf."""
    r = min(255, int(hex_color[1:3], 16) + amount)
    g = min(255, int(hex_color[3:5], 16) + amount)
    b = min(255, int(hex_color[5:7], 16) + amount)
    return f"#{r:02x}{g:02x}{b:02x}"


def darken(hex_color: str, amount: int = 20) -> str:
    """Dunkelt eine Hex-Farbe um amount ab."""
    r = max(0, int(hex_color[1:3], 16) - amount)
    g = max(0, int(hex_color[3:5], 16) - amount)
    b = max(0, int(hex_color[5:7], 16) - amount)
    return f"#{r:02x}{g:02x}{b:02x}"


def add_hover(widget, normal_bg: str, hover_bg: str,
              normal_fg: str = None, hover_fg: str = None):
    """Fügt Hover-Effekt zu einem Widget hinzu."""
    def on_enter(_): 
        widget.config(bg=hover_bg)
        if hover_fg: widget.config(fg=hover_fg)
    def on_leave(_):
        widget.config(bg=normal_bg)
        if normal_fg: widget.config(fg=normal_fg)
    widget.bind("<Enter>", on_enter)
    widget.bind("<Leave>", on_leave)


# ── Themes ────────────────────────────────────────────────────────────────────

THEMES = {
    # ── Professional Dark (GitHub-Stil) ──────────────────────────────────────
    "Classic": {
        # Hintergründe
        "BG":           "#0d1117",   # Haupt-Hintergrund: fast schwarz
        "BG2":          "#161b22",   # Karten / Panels / Sidebar
        "BG3":          "#1c2128",   # Inputs / Treeview
        "BG_HEADER":    "#161b22",   # identisch mit BG2
        # Akzent & Zustand
        "ACCENT":       "#7c6af7",   # Primär-Akzent: Indigo
        "ACCENT_H":     "#9580ff",   # Hover
        "GREEN":        "#3fb950",
        "RED":          "#f85149",
        "YELLOW":       "#d29922",
        "ORANGE":       "#db6d28",
        # Schrift
        "FG":           "#e6edf3",   # Primär
        "FG_DIM":       "#7d8590",   # Sekundär / Labels
        "FG_INPUT":     "#e6edf3",   # Text in Inputs
        "FG_BODY":      "#e6edf3",   # Alias = FG (hier alles dunkel)
        "FG_DIM_BODY":  "#7d8590",
        # Log
        "LOG_BG":       "#0d1117",
        "LOG_FG":       "#e6edf3",
        # Rahmen
        "BORDER":       "#21262d",
        "BORDER_L":     "#30363d",
    },
    # ── Professional Light (ABE Corporate) ───────────────────────────────────
    "ABE": {
        # Hintergründe
        "BG":           "#f0f4f8",   # Körper: weiches Blaugrau
        "BG2":          "#1a2035",   # Navy: Sidebar + Header
        "BG3":          "#ffffff",   # Inputs / Treeview: reinweiß
        "BG_HEADER":    "#1a2035",
        # Akzent & Zustand
        "ACCENT":       "#F39200",   # ABE Orange
        "ACCENT_H":     "#e08500",   # Hover (dunkler)
        "GREEN":        "#15803d",
        "RED":          "#dc2626",
        "YELLOW":       "#b45309",
        "ORANGE":       "#F39200",
        # Schrift auf dunklen Flächen (Header/Sidebar)
        "FG":           "#f0f4ff",
        "FG_DIM":       "#94a3b8",
        # Schrift auf hellen Flächen (Body)
        "FG_INPUT":     "#1e293b",
        "FG_BODY":      "#1e293b",
        "FG_DIM_BODY":  "#64748b",
        # Log (dunkel für Code-Ausgabe)
        "LOG_BG":       "#1a2035",
        "LOG_FG":       "#e2e8f0",
        # Rahmen
        "BORDER":       "#cbd5e1",
        "BORDER_L":     "#e2e8f0",
    },
}


# ── Widget-Factories ──────────────────────────────────────────────────────────

def make_button(parent, text: str, command, c: dict,
                variant: str = "primary",
                small: bool = False) -> tk.Button:
    """
    Erstellt einen gestylten Button mit Hover-Effekt.
    variant: 'primary' | 'secondary' | 'danger' | 'ghost'
    """
    font = FONT_UI_SM if small else FONT_UI
    padx = (8, 8)   if small else (14, 14)
    pady = (4, 4)   if small else ( 6,  6)

    if variant == "primary":
        bg, fg  = c["ACCENT"], "#ffffff"
        bg_h    = c["ACCENT_H"]
        fg_h    = "#ffffff"
    elif variant == "danger":
        bg, fg  = c["RED"], "#ffffff"
        bg_h    = lighten(c["RED"], 15)
        fg_h    = "#ffffff"
    elif variant == "secondary":
        bg, fg  = c["BG3"], c["FG_INPUT"]
        bg_h    = lighten(c["BG3"], 10) if c["BG3"] != "#ffffff" else "#f0f4f8"
        fg_h    = c["FG_INPUT"]
    else:   # ghost
        bg, fg  = c["BG2"], c["FG"]
        bg_h    = lighten(c["BG2"], 12)
        fg_h    = c["FG"]

    btn = tk.Button(
        parent, text=text, command=command,
        font=font, bg=bg, fg=fg,
        activebackground=bg_h, activeforeground=fg_h,
        relief="flat", bd=0, cursor="hand2",
        padx=padx[0], pady=pady[0])
    add_hover(btn, bg, bg_h, fg, fg_h)
    return btn


def make_separator(parent, c: dict, orient: str = "h",
                   color_key: str = "BORDER") -> tk.Frame:
    """Erstellt eine dünne Trennlinie."""
    color = c.get(color_key, c["BORDER"])
    if orient == "h":
        return tk.Frame(parent, bg=color, height=1)
    return tk.Frame(parent, bg=color, width=1)


def make_card(parent, c: dict, padx: int = 12,
              pady: int = 10) -> tk.Frame:
    """Erstellt einen Card-Container (BG2 auf BG)."""
    return tk.Frame(parent, bg=c["BG2"], padx=padx, pady=pady)


def apply_notebook_style(notebook: ttk.Notebook, c: dict,
                         style_name: str = "BME.TNotebook"):
    """Wendet professionelles Notebook-Styling an."""
    s = ttk.Style()
    s.theme_use("default")
    s.configure(style_name,
                background=c["BG2"],
                borderwidth=0, tabmargins=[0, 4, 0, 0])
    s.configure(f"{style_name}.Tab",
                background=c["BG2"],
                foreground=c["FG_DIM"],
                padding=[18, 8],
                font=FONT_UI)
    s.map(f"{style_name}.Tab",
          background=[("selected", c["BG"]),
                      ("active",   lighten(c["BG2"], 8))],
          foreground=[("selected", c["FG"]),
                      ("active",   c["FG"])])
    notebook.configure(style=style_name)


def apply_treeview_style(c: dict, style_name: str = "BME.Treeview"):
    """Wendet professionelles Treeview-Styling an."""
    s = ttk.Style()
    s.configure(style_name,
                background=c["BG3"],
                foreground=c["FG_INPUT"],
                fieldbackground=c["BG3"],
                rowheight=22,
                font=FONT_UI,
                borderwidth=0)
    s.configure(f"{style_name}.Heading",
                background=c["BG2"],
                foreground=c["FG"],
                font=("Segoe UI Semibold", 9),
                relief="flat")
    s.map(style_name,
          background=[("selected", c["ACCENT"])],
          foreground=[("selected", "#ffffff")])
    s.map(f"{style_name}.Heading",
          background=[("active", lighten(c["BG2"], 8))])
