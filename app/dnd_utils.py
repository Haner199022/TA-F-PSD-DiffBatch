"""Drag-and-drop helpers for the customtkinter GUI.

Bridges customtkinter + tkinterdnd2: CTk widgets don't natively register as
drop targets, so we reach into ._entry (CTkEntry) or treat the widget itself
as a tk.Widget.
"""
from __future__ import annotations

import sys
from pathlib import Path

import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD


class DnDCTk(ctk.CTk, TkinterDnD.DnDWrapper):
    """CTk root that also accepts file drops. Mixes CTk's CTk with
    TkinterDnD's DnDWrapper so we get a single Tk root that does both."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.TkdndVersion = TkinterDnD._require(self)


def parse_dnd_path(data: str) -> str:
    """tkinterdnd2 wraps paths containing spaces in {...}. Strip them and
    return the first path (we accept one drop at a time per field)."""
    s = (data or "").strip()
    if s.startswith("{"):
        end = s.find("}")
        if end > 0:
            first = s[1:end]
            rest = s[end + 1:].strip()
            if rest:
                print(f"[dnd] multi-path drop detected, using first: {first}", file=sys.stderr)
            return first
        return s
    # No braces — may be a single path with no spaces, or several space-separated paths.
    if " " in s and not Path(s).exists():
        parts = s.split()
        if len(parts) > 1 and Path(parts[0]).exists():
            print(f"[dnd] multi-path drop detected, using first: {parts[0]}", file=sys.stderr)
            return parts[0]
    return s


def register_drop_target(ctk_widget, on_enter, on_leave, on_drop) -> None:
    """Attach DnD callbacks to a CTk widget. Falls back to ._entry for CTkEntry
    (which wraps a tk.Entry), and to the widget itself for everything else."""
    target = getattr(ctk_widget, "_entry", ctk_widget)
    target.drop_target_register(DND_FILES)
    target.dnd_bind("<<DropEnter>>", on_enter)
    target.dnd_bind("<<DropLeave>>", on_leave)
    target.dnd_bind("<<Drop>>", on_drop)
