"""TA-F monochrome palette + font tokens.

Two palettes (M_DARK / M_LIGHT) and the `C(key)` helper that returns the
(light, dark) tuple CTk auto-resolves per appearance mode. For non-CTk widgets
(tk.PanedWindow, tk.Listbox, etc.) that don't accept tuples, callers read
`current_palette()[key]` and reconfigure on theme change.
"""
from __future__ import annotations

import customtkinter as ctk

# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------

M_DARK = {
    "bg":          "#000000",   # pure black background
    "surface":     "#111111",   # cards on bg
    "surface_2":   "#1A1A1A",   # inputs / lower contrast
    "divider":     "#2A2A2A",   # subtle separators
    "primary":     "#FFFFFF",   # pure white = primary
    "primary_dk":  "#CCCCCC",   # hover (slightly dimmer white)
    "on_primary":  "#000000",   # text on white button
    "secondary":   "#BBBBBB",   # in-progress accent (lighter gray)
    "text_hi":     "#FFFFFF",
    "text_md":     "#AAAAAA",
    "text_lo":     "#666666",
    "ok":          "#22C55E",
    "danger":      "#EF4444",
    "warn":        "#F59E0B",
}

M_LIGHT = {
    "bg":          "#FFFFFF",   # pure white background
    "surface":     "#FFFFFF",   # cards = bg (separated by border)
    "surface_2":   "#F5F5F5",   # inputs / lower contrast
    "divider":     "#E0E0E0",
    "primary":     "#000000",   # pure black = primary
    "primary_dk":  "#333333",
    "on_primary":  "#FFFFFF",
    "secondary":   "#444444",
    "text_hi":     "#000000",
    "text_md":     "#555555",
    "text_lo":     "#999999",
    "ok":          "#16A34A",   # deeper green for white bg
    "danger":      "#DC2626",
    "warn":        "#D97706",
}


def C(key: str) -> tuple:
    """Return (light, dark) tuple — CTk's fg_color/text_color args auto-pick
    by appearance mode."""
    return (M_LIGHT[key], M_DARK[key])


def current_palette() -> dict:
    """Return the active palette dict (for non-CTk widgets like tk.PanedWindow
    that don't accept CTk's (light, dark) tuple form)."""
    mode = ctk.get_appearance_mode()  # returns "Light" or "Dark" (resolves "System")
    return M_LIGHT if mode == "Light" else M_DARK


# ---------------------------------------------------------------------------
# Font tokens
# ---------------------------------------------------------------------------

ROBOTO_BOLD   = ("Roboto", 14, "bold")
ROBOTO_REG    = ("Roboto", 12)
ROBOTO_SMALL  = ("Roboto", 11)
ROBOTO_CAPS   = ("Roboto", 11, "bold")
TITLE_FONT    = ("Roboto", 22, "bold")
MONO_FONT     = ("Roboto Mono", 12)
