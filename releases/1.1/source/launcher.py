"""PSD Normalizer launcher — customtkinter GUI (Material Design).

Drives Photoshop in the background. Run `python3 launcher.py` for development;
PyInstaller bundles it as a .app/.exe.
"""
from __future__ import annotations

import datetime
import json
import os
import platform
import queue
import re
import subprocess
import threading
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

import tkinter as tk

import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD

import ps_driver

# PSD thumbnail extraction — lazy import (only needed for the right panel)
try:
    from psd_tools import PSDImage
    from PIL import Image
    _PIL_OK = True
except Exception:
    _PIL_OK = False


# Match the production .jsx log line: "--- (3/8) somefile.psd ---"
PROGRESS_RE = re.compile(r"^---\s*\((\d+)/(\d+)\)\s+(.+?)\s*---\s*$")


PRESETS_PATH = Path.home() / ".tafpsd_presets.json"


def load_presets() -> list:
    """Returns a list of preset dicts. Empty list if file missing/corrupt."""
    try:
        if PRESETS_PATH.exists():
            data = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("presets"), list):
                return data["presets"]
    except Exception:
        pass
    return []


def save_presets(presets: list) -> None:
    try:
        PRESETS_PATH.write_text(
            json.dumps({"presets": presets}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def reveal_folder(path: str) -> None:
    """Open `path` in the OS file manager (Finder on macOS, Explorer on Windows)."""
    if not path or not Path(path).exists():
        return
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["open", path], check=False)
        elif system == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", path], check=False)
    except Exception:
        pass


# Drag-and-drop enabled CTk root (mix CTk + TkinterDnD's DnDWrapper).
class DnDCTk(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.TkdndVersion = TkinterDnD._require(self)


def _parse_dnd_path(data: str) -> str:
    """tkinterdnd2 wraps paths containing spaces in {...}. Strip them and
    return the first path (we accept one drop at a time per field)."""
    s = (data or "").strip()
    # Multi-path drops: take the first one. Path may be {/path/with spaces} or /path/no_spaces.
    if s.startswith("{"):
        end = s.find("}")
        if end > 0:
            return s[1:end]
    # Single path, no braces — but may have spaces if no other paths follow.
    return s

# ---------------------------------------------------------------------------
# Theme — TA-F monochrome (Dark)
# ---------------------------------------------------------------------------

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")  # base; we override colors per widget

M = {
    "bg":          "#000000",   # pure black background
    "surface":     "#111111",   # cards on bg
    "surface_2":   "#1A1A1A",   # inputs / lower contrast
    "divider":     "#2A2A2A",   # subtle separators
    "primary":     "#FFFFFF",   # pure white = primary
    "primary_dk":  "#CCCCCC",   # hover (slightly dimmer white)
    "on_primary":  "#000000",   # text on white button
    "secondary":   "#BBBBBB",   # "in-progress" accent (lighter gray)
    "text_hi":     "#FFFFFF",
    "text_md":     "#AAAAAA",
    "text_lo":     "#666666",
    "ok":          "#22C55E",   # green — success state
    "danger":      "#EF4444",   # red — error state
    "warn":        "#F59E0B",   # amber — kept for future
}

# Logo path resolution (PyInstaller _MEIPASS or dev dir)
import sys
def _find_logo() -> "Path | None":
    candidates = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "assets" / "logo.png")
    here = Path(__file__).resolve().parent
    candidates += [
        here / "assets" / "logo.png",
        here.parent / "Resources" / "assets" / "logo.png",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None

ROBOTO_BOLD   = ("Roboto", 14, "bold")
ROBOTO_REG    = ("Roboto", 12)
ROBOTO_SMALL  = ("Roboto", 11)
ROBOTO_CAPS   = ("Roboto", 11, "bold")
TITLE_FONT    = ("Roboto", 22, "bold")
MONO_FONT     = ("Roboto Mono", 12)


# ---------------------------------------------------------------------------
# Worker thread machinery
# ---------------------------------------------------------------------------

class WorkerJob:
    def __init__(self, q: queue.Queue):
        self.q = q
        self.thread: threading.Thread | None = None

    def start(self, target, *args, **kwargs):
        if self.thread and self.thread.is_alive():
            raise RuntimeError("a job is already running")

        def run():
            try:
                self.q.put(("status", "running…"))
                result = target(*args, **kwargs)
                self.q.put(("done", result))
            except Exception as exc:
                self.q.put(("error", str(exc)))

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive())


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class App:
    def __init__(self, root: ctk.CTk):
        self.root = root
        root.title("TA-F PSD DiffBatch")
        root.geometry("1200x760")
        root.configure(fg_color=M["bg"])
        root.minsize(1080, 680)

        self.q: queue.Queue = queue.Queue()
        self.worker = WorkerJob(self.q)

        # Path vars
        self.after_path  = ctk.StringVar()
        self.before_path = ctk.StringVar()
        self.folder_path = ctk.StringVar()
        self.output_path = ctk.StringVar()

        # Var displayed below the batch folder row: "N PSDs found"
        self.batch_count_var = ctk.StringVar(value="")
        # Track last output folder for the Reveal button
        self.last_output_folder: str | None = None

        # Total + done file counts (for progress bar)
        self._total_files = 0
        self._done_files = 0

        # File-preview state: a generation counter cancels in-flight loads
        # when the folder changes mid-load; file_rows maps name → widget dict
        self._thumb_gen = 0
        self.file_rows: dict = {}

        # Last analysis result (recipe summary + diff) — saved by Save Preset.
        self.last_analysis: dict | None = None

        self._build_ui()

        # Recount batch folder when it changes + populate file preview panel
        self.folder_path.trace_add("write", lambda *_: self._update_batch_count())
        self.folder_path.trace_add("write", lambda *_: self._populate_file_panel())
        self._update_batch_count()  # initial

        # Auto-detect Photoshop
        self.ps_app = ps_driver.find_photoshop_app_name() or "Adobe Photoshop"
        self._set_status(f"Ready · PS: {self.ps_app}", M["text_md"])

        # Bind keyboard shortcuts (bonus, since the cost was tiny)
        self.root.bind_all("<Command-r>", lambda e: self._on_run())
        self.root.bind_all("<Command-l>", lambda e: self._on_analyze())
        self.root.bind_all("<Command-k>", lambda e: self._clear_output())
        self.root.bind_all("<Control-r>", lambda e: self._on_run())
        self.root.bind_all("<Control-l>", lambda e: self._on_analyze())
        self.root.bind_all("<Control-k>", lambda e: self._clear_output())

        self._poll_queue()

    # ---- Right panel: file preview ----

    def _populate_file_panel(self) -> None:
        # Bump generation token so any in-flight thumbnail worker bails out.
        self._thumb_gen += 1
        gen = self._thumb_gen

        # Clear existing rows
        for child in self.file_list.winfo_children():
            child.destroy()
        self.file_rows = {}

        folder = self.folder_path.get()
        if not folder or not Path(folder).is_dir():
            self.file_panel_count.configure(text="—")
            self.file_panel_hint = ctk.CTkLabel(
                self.file_list, text="Pick a batch folder to preview PSDs",
                text_color=M["text_lo"], font=("Roboto", 11), justify="center", wraplength=240,
            )
            self.file_panel_hint.pack(pady=40)
            return

        files = sorted(
            [f for f in Path(folder).iterdir()
             if f.is_file() and f.suffix.lower() == ".psd"],
            key=lambda f: f.name.lower()
        )
        self.file_panel_count.configure(text=f"{len(files)}")
        if not files:
            ctk.CTkLabel(
                self.file_list, text="No PSDs found",
                text_color=M["text_lo"], font=("Roboto", 11),
            ).pack(pady=40)
            return

        # Phase 1: instantly show all rows with placeholders
        for f in files:
            self.file_rows[f.name] = self._make_file_row(f)

        # Phase 2: load thumbnails in background
        if _PIL_OK:
            threading.Thread(
                target=self._thumb_loader, args=([str(f) for f in files], gen),
                daemon=True
            ).start()

    def _make_file_row(self, file_path: Path) -> dict:
        item = ctk.CTkFrame(
            self.file_list, fg_color=M["surface_2"],
            corner_radius=6, height=112,
        )
        item.pack(fill="x", pady=4, padx=2)
        item.pack_propagate(False)

        # Thumbnail container (96×96 placeholder)
        thumb_box = ctk.CTkFrame(item, width=96, height=96, fg_color=M["divider"], corner_radius=4)
        thumb_box.pack(side="left", padx=8, pady=8)
        thumb_box.pack_propagate(False)
        thumb_label = ctk.CTkLabel(thumb_box, text="…", text_color=M["text_lo"], font=("Roboto", 16))
        thumb_label.pack(expand=True)

        # Right-of-thumbnail text block
        text_box = ctk.CTkFrame(item, fg_color="transparent")
        text_box.pack(side="left", fill="both", expand=True, padx=(4, 10), pady=8)

        name_label = ctk.CTkLabel(
            text_box, text=file_path.name,
            text_color=M["text_hi"], font=("Roboto", 11, "bold"),
            anchor="w", justify="left", wraplength=180,
        )
        name_label.pack(anchor="w")

        try:
            size_mb = file_path.stat().st_size / (1024 * 1024)
            size_text = f"{size_mb:.1f} MB"
        except Exception:
            size_text = ""
        size_label = ctk.CTkLabel(
            text_box, text=size_text,
            text_color=M["text_lo"], font=("Roboto", 10), anchor="w",
        )
        size_label.pack(anchor="w", pady=(2, 0))

        # Double-click anywhere on the row → big preview popup
        def on_dclick(_e=None, fp=file_path):
            self._show_preview_popup(fp)
        # Bind on the row + all its children (so click on label/thumb works too)
        for w in (item, thumb_box, thumb_label, text_box, name_label, size_label):
            try: w.bind("<Double-Button-1>", on_dclick)
            except Exception: pass

        return {"item": item, "thumb_box": thumb_box, "thumb_label": thumb_label, "img_ref": None}

    def _show_preview_popup(self, file_path: Path):
        if not _PIL_OK:
            return
        try:
            psd = PSDImage.open(str(file_path))
            thumb = psd.thumbnail()
        except Exception:
            thumb = None
        if thumb is None:
            return

        # Build modal-ish Toplevel
        top = ctk.CTkToplevel(self.root)
        top.title(file_path.name)
        top.configure(fg_color=M["bg"])
        top.transient(self.root)

        # Resize thumbnail to fit 480×480
        img = thumb.copy()
        img.thumbnail((480, 480), Image.LANCZOS)
        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)

        ctk.CTkLabel(top, image=ctk_img, text="").pack(padx=16, pady=16)
        ctk.CTkLabel(
            top, text=file_path.name,
            text_color=M["text_hi"], font=("Roboto", 12, "bold"),
        ).pack(pady=(0, 16), padx=16)

        # Keep image reference to prevent GC
        top._img_ref = ctk_img
        # Close on Esc / click outside is hard in Tk; just give a close button.
        ctk.CTkButton(
            top, text="CLOSE",
            fg_color=M["primary"], text_color=M["on_primary"], hover_color=M["primary_dk"],
            font=ROBOTO_CAPS, corner_radius=4, width=120, height=32,
            command=top.destroy,
        ).pack(pady=(0, 16))
        top.bind("<Escape>", lambda e: top.destroy())

    def _thumb_loader(self, paths: list, gen: int) -> None:
        for p in paths:
            if gen != self._thumb_gen:
                return
            thumb_pil = None
            try:
                psd = PSDImage.open(p)
                thumb_pil = psd.thumbnail()
            except Exception:
                thumb_pil = None
            if gen != self._thumb_gen:
                return
            self.q.put(("thumb", (Path(p).name, thumb_pil, gen)))

    def _apply_thumb(self, name: str, thumb_pil, gen: int) -> None:
        if gen != self._thumb_gen:
            return
        row = self.file_rows.get(name)
        if not row:
            return
        if thumb_pil is None:
            row["thumb_label"].configure(text="—")
            return
        try:
            img = thumb_pil.copy()
            img.thumbnail((96, 96), Image.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            row["thumb_label"].configure(image=ctk_img, text="")
            row["img_ref"] = ctk_img  # keep ref to prevent GC
        except Exception:
            row["thumb_label"].configure(text="!")

    # ---- Batch folder count ----

    def _update_batch_count(self) -> None:
        p = self.folder_path.get()
        if not p:
            self.batch_count_var.set("")
            return
        folder = Path(p)
        if not folder.exists():
            self.batch_count_var.set("(folder not found)")
            return
        if not folder.is_dir():
            self.batch_count_var.set("(not a folder)")
            return
        try:
            n = sum(1 for f in folder.iterdir()
                    if f.is_file() and f.suffix.lower() == ".psd")
            self.batch_count_var.set(f"{n} PSD file{'s' if n != 1 else ''} found")
        except Exception:
            self.batch_count_var.set("")

    # ---- Layout ----

    def _build_ui(self):
        # ===== App Bar — slim, logo + product name =====
        appbar = ctk.CTkFrame(self.root, fg_color=M["bg"], corner_radius=0, height=56)
        appbar.pack(fill="x")
        appbar.pack_propagate(False)

        appbar_inner = ctk.CTkFrame(appbar, fg_color="transparent")
        appbar_inner.pack(side="left", padx=20, pady=10, fill="y")

        logo_path = _find_logo()
        self._logo_img = None
        if logo_path and _PIL_OK:
            try:
                im = Image.open(str(logo_path)).convert("RGBA")
                target_h = 32
                target_w = int(im.width * (target_h / im.height))
                im_resized = im.resize((target_w, target_h), Image.LANCZOS)
                self._logo_img = ctk.CTkImage(
                    light_image=im_resized, dark_image=im_resized,
                    size=(target_w, target_h),
                )
            except Exception:
                self._logo_img = None

        if self._logo_img:
            ctk.CTkLabel(appbar_inner, image=self._logo_img, text="").pack(side="left", anchor="center")
        else:
            ctk.CTkLabel(
                appbar_inner, text="TA-F",
                text_color=M["text_hi"], font=("Roboto", 16, "bold"),
            ).pack(side="left", anchor="center")
        ctk.CTkLabel(
            appbar_inner, text="PSD DiffBatch",
            text_color=M["text_md"], font=("Roboto", 11),
        ).pack(side="left", anchor="center", padx=(14, 0))

        ctk.CTkFrame(self.root, fg_color=M["divider"], height=1, corner_radius=0).pack(fill="x")

        # ===== Main horizontal split (user-resizable) =====
        # Use tk.PanedWindow so the user can drag the sash to resize panels.
        split = tk.PanedWindow(
            self.root, orient="horizontal",
            bg=M["divider"], sashwidth=4, sashrelief="flat",
            showhandle=False, opaqueresize=True,
        )
        split.pack(fill="both", expand=True)

        # Left side: original content (created below, packed first into split)
        content = ctk.CTkFrame(split, fg_color=M["bg"])
        split.add(content, minsize=560, stretch="always", padx=0, pady=0)

        # Right side: file preview panel
        right_panel = ctk.CTkFrame(
            split, fg_color=M["surface"],
            corner_radius=0, border_width=0, width=320,
        )
        split.add(right_panel, minsize=240, stretch="never", padx=0, pady=0)

        # Right-panel header
        right_hdr = ctk.CTkFrame(right_panel, fg_color="transparent")
        right_hdr.pack(fill="x", padx=16, pady=(20, 8))
        ctk.CTkLabel(
            right_hdr, text="BATCH FILES",
            text_color=M["text_md"], font=ROBOTO_CAPS,
        ).pack(side="left")
        self.file_panel_count = ctk.CTkLabel(
            right_hdr, text="—", text_color=M["text_lo"], font=("Roboto", 10),
        )
        self.file_panel_count.pack(side="right")

        # Thin divider under header
        ctk.CTkFrame(right_panel, fg_color=M["divider"], height=1, corner_radius=0).pack(fill="x", padx=12)

        # Scrollable file list
        self.file_list = ctk.CTkScrollableFrame(
            right_panel, fg_color="transparent",
        )
        self.file_list.pack(fill="both", expand=True, padx=8, pady=8)

        # Empty-state hint
        self.file_panel_hint = ctk.CTkLabel(
            self.file_list, text="Drop a folder here\nor pick a Batch folder",
            text_color=M["text_lo"], font=("Roboto", 11), justify="center", wraplength=240,
        )
        self.file_panel_hint.pack(pady=40)

        # Right panel itself accepts folder drops → sets Batch folder field.
        # tkinterdnd2 needs a real tk widget; use the inner canvas of the
        # scrollable frame (which IS a tk widget).
        try:
            target = right_panel  # CTkFrame wraps a tk Frame
            # use the underlying tk widget for DND
            target_tk = target if isinstance(target, tk.Misc) else target.master
            target_tk.drop_target_register(DND_FILES)
            target_tk.dnd_bind("<<DropEnter>>", lambda e: target.configure(fg_color=M["surface_2"]))
            target_tk.dnd_bind("<<DropLeave>>", lambda e: target.configure(fg_color=M["surface"]))
            target_tk.dnd_bind(
                "<<Drop>>",
                lambda e: self._on_drop_folder(e, target),
            )
        except Exception:
            pass

        # Apply inner padding to the content frame (it's already added to the paned split).
        content_inner = ctk.CTkFrame(content, fg_color="transparent")
        content_inner.pack(fill="both", expand=True, padx=20, pady=20)
        content = content_inner  # rest of build uses 'content' below

        # ===== Input card =====
        card = ctk.CTkFrame(
            content, fg_color=M["surface"],
            corner_radius=8, border_width=1, border_color=M["divider"],
        )
        card.pack(fill="x")

        ctk.CTkLabel(
            card, text="INPUTS",
            text_color=M["text_md"], font=ROBOTO_CAPS,
        ).pack(anchor="w", padx=20, pady=(16, 8))

        self._field_row(card, "After PSD",          self.after_path,  is_folder=False)
        self._field_row(card, "Before PSD (opt.)",  self.before_path, is_folder=False)
        self._field_row(card, "Batch folder",       self.folder_path, is_folder=True,
                        sublabel_var=self.batch_count_var)
        self._field_row(card, "Output (opt.)",      self.output_path, is_folder=True)
        ctk.CTkFrame(card, fg_color="transparent", height=12).pack()

        # ===== Action bar =====
        action = ctk.CTkFrame(content, fg_color="transparent")
        action.pack(fill="x", pady=(16, 4))

        self.btn_analyze = ctk.CTkButton(
            action, text="ANALYZE",
            fg_color="transparent", border_color=M["primary"], border_width=1,
            text_color=M["primary"], hover_color=M["surface_2"],
            corner_radius=4, width=120, height=36, font=ROBOTO_CAPS,
            command=self._on_analyze,
        )
        self.btn_analyze.pack(side="left", padx=(0, 8))

        self.btn_run = ctk.CTkButton(
            action, text="RUN BATCH",
            fg_color=M["primary"], hover_color=M["primary_dk"],
            text_color=M["on_primary"],
            corner_radius=4, width=160, height=36, font=ROBOTO_CAPS,
            command=self._on_run,
        )
        self.btn_run.pack(side="left")

        self.btn_presets = ctk.CTkButton(
            action, text="PRESETS",
            fg_color="transparent", border_color=M["divider"], border_width=1,
            text_color=M["text_md"], hover_color=M["surface_2"],
            corner_radius=4, width=100, height=36, font=ROBOTO_CAPS,
            command=self._open_presets_dialog,
        )
        self.btn_presets.pack(side="left", padx=(8, 0))

        self.btn_clear = ctk.CTkButton(
            action, text="CLEAR",
            fg_color="transparent", border_width=0,
            text_color=M["primary"], hover_color=M["surface_2"],
            corner_radius=4, width=80, height=36, font=ROBOTO_CAPS,
            command=self._clear_output,
        )
        self.btn_clear.pack(side="right")

        self.btn_reveal = ctk.CTkButton(
            action, text="REVEAL OUTPUT",
            fg_color="transparent", border_color=M["primary"], border_width=1,
            text_color=M["primary"], hover_color=M["surface_2"],
            corner_radius=4, width=160, height=36, font=ROBOTO_CAPS,
            command=self._reveal_output,
            state="disabled",
        )
        self.btn_reveal.pack(side="right", padx=(0, 8))

        # ===== Status card: dot + text + percentage above a real progress bar =====
        status_card = ctk.CTkFrame(
            content, fg_color=M["surface_2"], corner_radius=6,
        )
        status_card.pack(fill="x", pady=(14, 6))

        sc_inner = ctk.CTkFrame(status_card, fg_color="transparent")
        sc_inner.pack(fill="x", padx=14, pady=10)

        top_row = ctk.CTkFrame(sc_inner, fg_color="transparent")
        top_row.pack(fill="x")

        # State indicator dot (gray idle / white running / green ok / red error)
        self.status_dot = ctk.CTkLabel(
            top_row, text="●",
            text_color=M["text_lo"], font=("Roboto", 16),
        )
        self.status_dot.pack(side="left", padx=(0, 8))

        self.status_var = ctk.StringVar(value="Ready")
        ctk.CTkLabel(
            top_row, textvariable=self.status_var,
            text_color=M["text_hi"], font=("Roboto", 11, "bold"),
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        self.pct_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            top_row, textvariable=self.pct_var,
            text_color=M["text_md"], font=("Roboto", 11, "bold"),
            anchor="e",
        ).pack(side="right")

        # Real CTkProgressBar — reliable updates via .set(frac).
        self.progress_bar = ctk.CTkProgressBar(
            sc_inner, orientation="horizontal",
            fg_color=M["divider"], progress_color=M["primary"],
            height=6, corner_radius=2,
        )
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", pady=(10, 0))

        # ===== Output (collapsible) =====
        self._output_visible = False  # collapsed by default; auto-expands on run

        out_header = ctk.CTkFrame(content, fg_color="transparent")
        out_header.pack(fill="x", pady=(8, 4))

        self._toggle_btn = ctk.CTkButton(
            out_header, text="▸ OUTPUT",
            fg_color="transparent", hover_color=M["surface_2"],
            text_color=M["text_md"], font=ROBOTO_CAPS,
            border_width=0, corner_radius=4, height=24, anchor="w",
            command=self._toggle_output,
        )
        self._toggle_btn.pack(side="left", padx=(0, 0))

        self.out_card = ctk.CTkFrame(
            content, fg_color=M["surface"],
            corner_radius=8, border_width=1, border_color=M["divider"],
        )
        # not packed yet; _show_output() will pack it

        self.output = ctk.CTkTextbox(
            self.out_card,
            fg_color=M["surface_2"],
            text_color=M["text_hi"],
            font=MONO_FONT,
            corner_radius=4,
            border_width=0,
            wrap="word",
        )
        self.output.pack(fill="both", expand=True, padx=12, pady=12)
        self.output.configure(state="disabled")

    def _toggle_output(self):
        if self._output_visible:
            self._hide_output()
        else:
            self._show_output()

    def _show_output(self):
        if self._output_visible: return
        self._output_visible = True
        self.out_card.pack(fill="both", expand=True)
        self._toggle_btn.configure(text="▾ OUTPUT")

    def _hide_output(self):
        if not self._output_visible: return
        self._output_visible = False
        self.out_card.pack_forget()
        self._toggle_btn.configure(text="▸ OUTPUT")

    def _field_row(self, parent, label_text, var, is_folder: bool, sublabel_var=None):
        wrapper = ctk.CTkFrame(parent, fg_color="transparent")
        wrapper.pack(fill="x", padx=20, pady=(6, 2))

        # Label above the input (more horizontal room for the path)
        ctk.CTkLabel(
            wrapper, text=label_text.upper(),
            text_color=M["text_lo"], font=("Roboto", 9, "bold"),
            anchor="w",
        ).pack(fill="x")

        row = ctk.CTkFrame(wrapper, fg_color="transparent")
        row.pack(fill="x", pady=(2, 0))

        entry = ctk.CTkEntry(
            row, textvariable=var,
            fg_color=M["surface_2"], border_color=M["divider"],
            text_color=M["text_hi"], font=ROBOTO_REG, height=32,
            corner_radius=4, border_width=1,
            placeholder_text="Drag here or click Browse",
        )
        entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # Drag-and-drop: register the inner tk widget (CTkEntry wraps it).
        inner = entry._entry  # underlying tk.Entry
        inner.drop_target_register(DND_FILES)
        inner.dnd_bind("<<DropEnter>>", lambda e: entry.configure(border_color=M["primary"]))
        inner.dnd_bind("<<DropLeave>>", lambda e: entry.configure(border_color=M["divider"]))
        inner.dnd_bind(
            "<<Drop>>",
            lambda e, v=var, w=entry: self._on_dnd(e, v, w),
        )

        ctk.CTkButton(
            row, text="Browse",
            fg_color="transparent", hover_color=M["surface_2"],
            text_color=M["primary"], border_color=M["divider"], border_width=1,
            corner_radius=4, width=88, height=34, font=ROBOTO_CAPS,
            command=lambda: self._pick(var, label_text, is_folder),
        ).pack(side="left")

        # Optional sub-label below the input (e.g., "5 PSD files found" for batch).
        if sublabel_var is not None:
            ctk.CTkLabel(
                wrapper, textvariable=sublabel_var,
                text_color=M["text_lo"], font=("Roboto", 10),
                anchor="w",
            ).pack(fill="x", pady=(2, 0))

    def _on_dnd(self, event, var, entry):
        path = _parse_dnd_path(event.data)
        if path:
            var.set(path)
        # Reset border color (DropLeave doesn't always fire after Drop on all platforms)
        try: entry.configure(border_color=M["divider"])
        except Exception: pass

    def _on_drop_folder(self, event, panel_widget):
        """Right-panel drop handler: dropped folder → Batch folder field."""
        path = _parse_dnd_path(event.data)
        try: panel_widget.configure(fg_color=M["surface"])
        except Exception: pass
        if path and Path(path).is_dir():
            self.folder_path.set(path)
        elif path and Path(path).is_file():
            # If user dropped a file, take its parent folder
            self.folder_path.set(str(Path(path).parent))

    # ---- Pickers ----

    def _pick(self, var, label, is_folder: bool):
        if is_folder:
            p = filedialog.askdirectory(title=label)
        else:
            p = filedialog.askopenfilename(
                title=label, filetypes=[("PSD", "*.psd"), ("All", "*.*")]
            )
        if p:
            var.set(p)

    # ---- Output helpers ----

    def _append(self, text):
        self.output.configure(state="normal")
        if self.output.index("end-1c") != "1.0":
            self.output.insert("end", "\n")
        self.output.insert("end", text)
        self.output.see("end")
        self.output.configure(state="disabled")

    def _clear_output(self):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")

    def _set_status(self, msg, color=None):
        self.status_var.set(msg)

    def _set_progress(self, frac: float):
        """0.0–1.0 — drives the real progress bar and the pct label."""
        frac = max(0.0, min(1.0, frac))
        try:
            self.progress_bar.set(frac)
            self.pct_var.set(f"{int(frac * 100)}%" if frac > 0 else "")
        except Exception:
            pass

    def _reset_progress(self):
        self._set_progress(0.0)
        try: self.pct_var.set("")
        except Exception: pass

    def _set_state(self, state: str):
        """state ∈ {'idle', 'running', 'ok', 'error'}. Drives dot + bar color."""
        palette = {
            "idle":    (M["text_lo"], M["primary"]),
            "running": (M["primary"], M["primary"]),
            "ok":      (M["ok"],      M["ok"]),
            "error":   (M["danger"],  M["danger"]),
        }
        dot_color, bar_color = palette.get(state, palette["idle"])
        try: self.status_dot.configure(text_color=dot_color)
        except Exception: pass
        try: self.progress_bar.configure(progress_color=bar_color)
        except Exception: pass

    def _set_buttons_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.btn_analyze.configure(state=state)
        self.btn_run.configure(state=state)

    # ---- Reveal ----

    def _maybe_update_progress(self, line: str):
        m = PROGRESS_RE.match(line)
        if not m: return
        done = int(m.group(1)) - 1   # this file just STARTED, so completed = N-1
        total = int(m.group(2))
        self._done_files = done
        self._total_files = total
        frac = done / total if total else 0
        self._set_progress(frac)
        self._set_status(f"Running · {m.group(1)}/{total} — {m.group(3)}")

    def _reveal_output(self):
        if self.last_output_folder:
            reveal_folder(self.last_output_folder)

    # ---- Presets ----

    def _open_presets_dialog(self):
        dlg = ctk.CTkToplevel(self.root)
        dlg.title("Presets")
        dlg.configure(fg_color=M["bg"])
        dlg.geometry("520x520")
        dlg.transient(self.root)

        # Top header
        ctk.CTkLabel(
            dlg, text="PRESETS",
            text_color=M["text_md"], font=ROBOTO_CAPS,
        ).pack(anchor="w", padx=20, pady=(18, 4))
        ctk.CTkFrame(dlg, fg_color=M["divider"], height=1, corner_radius=0).pack(fill="x", padx=20)

        # Scrollable list
        body = ctk.CTkScrollableFrame(dlg, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=12)

        presets = load_presets()

        if not presets:
            ctk.CTkLabel(
                body, text="No saved presets yet.\nUse «Save current» below.",
                text_color=M["text_lo"], font=("Roboto", 11), justify="center",
            ).pack(pady=40)
        else:
            for idx, p in enumerate(presets):
                self._make_preset_row(body, p, idx, dlg)

        # Bottom action: Save Current
        bottom = ctk.CTkFrame(dlg, fg_color="transparent")
        bottom.pack(fill="x", padx=20, pady=(8, 18))
        ctk.CTkButton(
            bottom, text="SAVE CURRENT AS PRESET…",
            fg_color=M["primary"], text_color=M["on_primary"], hover_color=M["primary_dk"],
            corner_radius=4, height=36, font=ROBOTO_CAPS,
            command=lambda: self._save_current_preset_then_refresh(dlg),
        ).pack(fill="x")

    def _make_preset_row(self, parent, preset: dict, idx: int, dlg):
        row = ctk.CTkFrame(parent, fg_color=M["surface"], corner_radius=6)
        row.pack(fill="x", pady=4)

        # Left text block
        text_block = ctk.CTkFrame(row, fg_color="transparent")
        text_block.pack(side="left", fill="both", expand=True, padx=12, pady=10)

        ctk.CTkLabel(
            text_block, text=preset.get("name", "(unnamed)"),
            text_color=M["text_hi"], font=("Roboto", 12, "bold"),
            anchor="w",
        ).pack(anchor="w")

        ap = preset.get("after_path", "")
        bp = preset.get("before_path", "")
        meta = []
        if ap:
            meta.append(f"after: {Path(ap).name}")
        if bp:
            meta.append(f"before: {Path(bp).name}")
        if preset.get("saved_at"):
            meta.append(preset["saved_at"].split("T")[0])
        ctk.CTkLabel(
            text_block, text="  ·  ".join(meta),
            text_color=M["text_lo"], font=("Roboto", 10),
            anchor="w", wraplength=320, justify="left",
        ).pack(anchor="w", pady=(2, 0))

        # Right buttons
        btn_block = ctk.CTkFrame(row, fg_color="transparent")
        btn_block.pack(side="right", padx=8, pady=10)

        ctk.CTkButton(
            btn_block, text="LOAD",
            fg_color=M["primary"], text_color=M["on_primary"], hover_color=M["primary_dk"],
            corner_radius=4, width=70, height=30, font=ROBOTO_CAPS,
            command=lambda i=idx: self._load_preset(i, dlg),
        ).pack(side="top")

        ctk.CTkButton(
            btn_block, text="DELETE",
            fg_color="transparent", border_color=M["divider"], border_width=1,
            text_color=M["text_md"], hover_color=M["surface_2"],
            corner_radius=4, width=70, height=26, font=("Roboto", 9, "bold"),
            command=lambda i=idx: self._delete_preset(i, dlg),
        ).pack(side="top", pady=(4, 0))

    def _save_current_preset_then_refresh(self, dlg):
        if not self.after_path.get():
            messagebox.showwarning("Cannot save", "Pick an After PSD first.", parent=dlg)
            return
        name = simpledialog.askstring(
            "Save Preset", "Name this preset:", parent=dlg,
        )
        if not name:
            return
        name = name.strip()
        if not name:
            return

        presets = load_presets()
        # Build entry
        entry = {
            "name": name,
            "after_path":  self.after_path.get(),
            "before_path": self.before_path.get(),
            "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        if self.last_analysis:
            entry["summary"] = self.last_analysis.get("recipeSummary", [])
            entry["diff"]    = self.last_analysis.get("diff")
        # Replace if name already exists, else append
        for i, p in enumerate(presets):
            if p.get("name") == name:
                presets[i] = entry
                break
        else:
            presets.append(entry)
        save_presets(presets)

        # Refresh dialog
        dlg.destroy()
        self._open_presets_dialog()

    def _load_preset(self, idx: int, dlg):
        presets = load_presets()
        if idx < 0 or idx >= len(presets):
            return
        p = presets[idx]
        self.after_path.set(p.get("after_path", ""))
        self.before_path.set(p.get("before_path", ""))

        # Show cached analysis summary in Output area, if present
        summary = p.get("summary") or []
        diff    = p.get("diff")
        if summary or diff:
            self._show_output()
            self._clear_output()
            self._append(f"Loaded preset: {p.get('name', '(unnamed)')}")
            if summary:
                self._append("\nRecipe (cached)")
                for line in summary:
                    self._append(f"  {line}")
            if diff:
                self._append("\nDiff (cached)")
                for line in diff:
                    self._append(f"  {line}")
            # Treat the cached analysis as the current one, so user can immediately re-save
            self.last_analysis = {"recipeSummary": summary, "diff": diff}
        self._set_status(f"Preset loaded · {p.get('name', '')}")
        dlg.destroy()

    def _delete_preset(self, idx: int, dlg):
        presets = load_presets()
        if idx < 0 or idx >= len(presets):
            return
        name = presets[idx].get("name", "(unnamed)")
        if not messagebox.askyesno("Delete preset", f"Delete preset «{name}»?", parent=dlg):
            return
        del presets[idx]
        save_presets(presets)
        dlg.destroy()
        self._open_presets_dialog()

    # ---- Button handlers ----

    def _on_analyze(self):
        if not self.after_path.get():
            messagebox.showwarning("Missing input", "Pick the After (reference) PSD.")
            return
        if self.worker.alive():
            return
        self._show_output()
        self._clear_output()
        self._append(f"Analyze · PS: {self.ps_app}")
        self._set_status("Analyzing…")
        self._set_state("running")
        self._set_buttons_enabled(False)
        self.worker.start(
            ps_driver.analyze,
            self.after_path.get(),
            self.before_path.get() or None,
            self.ps_app,
        )

    def _on_run(self):
        if not self.after_path.get():
            messagebox.showwarning("Missing input", "Pick the After (reference) PSD.")
            return
        if not self.folder_path.get():
            messagebox.showwarning("Missing input", "Pick the batch folder.")
            return
        if self.worker.alive():
            return
        self._clear_output()
        self._append(f"Run batch · PS: {self.ps_app}")
        self._set_status("Running batch…")
        self._set_buttons_enabled(False)
        self.btn_reveal.configure(state="disabled")
        self._done_files = 0
        self._total_files = 0
        self._reset_progress()
        self._set_state("running")
        self._show_output()  # auto-expand collapsed output area

        def on_log_line(line: str):
            self.q.put(("log", line))

        self.worker.start(
            ps_driver.run_batch,
            self.after_path.get(),
            self.folder_path.get(),
            self.ps_app,
            on_log_line,
            self.output_path.get() or None,
        )

    # ---- Queue pump ----

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "status":
                    self._set_status(payload, M["secondary"])
                elif kind == "log":
                    self._append(payload)
                    self._maybe_update_progress(payload)
                elif kind == "thumb":
                    name, thumb_pil, gen = payload
                    self._apply_thumb(name, thumb_pil, gen)
                elif kind == "done":
                    self._handle_done(payload)
                elif kind == "error":
                    self._append(f"\nError: {payload}")
                    self._set_status("Error")
                    self._set_state("error")
                    self._set_buttons_enabled(True)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _handle_done(self, result: dict):
        if not isinstance(result, dict):
            self._append(f"\nDone · result: {result}")
            self._set_status("Done", M["ok"])
            self._set_buttons_enabled(True)
            return

        if not result.get("ok"):
            self._append(f"\nFailed: {result.get('error', 'unknown error')}")
            self._set_status("Failed")
            self._set_state("error")
            self._set_buttons_enabled(True)
            return

        if "recipeSummary" in result:
            self._append("\nRecipe (from after)")
            for line in result.get("recipeSummary", []):
                self._append(f"  {line}")
            diff = result.get("diff")
            if diff:
                self._append("\nDiff (before → after)")
                for line in diff:
                    self._append(f"  {line}")
            else:
                self._append("\n(no before file — diff skipped)")
            self._set_status("Analyze complete")
            self._set_state("ok")
            # Remember this analysis so Save Preset can capture it.
            self.last_analysis = {
                "recipeSummary": result.get("recipeSummary", []),
                "diff": result.get("diff"),
            }
        elif "result" in result:
            r = result["result"]
            self._append(
                f"\nBatch finished · {r.get('ok')} ok, "
                f"{r.get('fail')} failed in {r.get('elapsed', 0):.1f}s"
            )
            self._append(f"  Output: {r.get('outFolder')}")
            self._append(f"  Log:    {r.get('logFile')}")
            ok_n = r.get("ok", 0)
            fail_n = r.get("fail", 0)
            self._set_status(
                f"Done · {ok_n} ok, {fail_n} failed · {r.get('elapsed', 0):.1f}s",
            )
            self._set_progress(1.0)
            self._set_state("error" if fail_n > 0 else "ok")
            self.last_output_folder = r.get("outFolder")
            if self.last_output_folder:
                self.btn_reveal.configure(state="normal")
        else:
            self._append(f"\nDone: {result}")
            self._set_status("Done")
            self._set_state("ok")

        self._set_buttons_enabled(True)


def main():
    root = DnDCTk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
