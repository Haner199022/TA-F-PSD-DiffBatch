"""PSD Normalizer launcher — customtkinter GUI (Windows-only).

Drives Photoshop via COM in the background. Run `python launcher.py` for
development; PyInstaller bundles it as an .exe.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import queue
import re
import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

import tkinter as tk

import customtkinter as ctk

import ps_driver
from diagnostics import DiagnosticContext, build_report
from errors import show_error
from logging_setup import setup_logging
from persistence import (
    PRESETS_PATH,
    add_muted_warning,
    is_warning_muted,
    load_presets,
    save_presets,
    load_user_scripts_dirs,
    save_user_scripts_dirs,
    load_appearance_mode,
    save_appearance_mode,
)
from theme import (
    M_DARK, M_LIGHT, C,
    current_palette as _current_palette,
    ROBOTO_BOLD, ROBOTO_REG, ROBOTO_SMALL, ROBOTO_CAPS, TITLE_FONT, MONO_FONT,
)
from dnd_utils import (
    DnDCTk,
    parse_dnd_path as _parse_dnd_path,
    register_drop_target as _register_drop_target,
)
from worker import WorkerJob
import updater

log = logging.getLogger(__name__)

# Version is the single source of truth in _version.py. version_info.txt
# and installer.iss derive from it via tools/render_version.py + build.bat
# env injection — see _version.py docstring for the full chain.
from _version import __version__ as APP_VERSION

# Windows named-mutex used by Inno Setup's AppMutex directive to detect a
# running instance during update install. Must match installer.iss:
#     #define MutexName "TA-F_PSD_DiffBatch_Mutex"
# No spaces: Windows kernel object names with spaces survive most APIs but
# are an avoidable parsing hazard in some command-line invocations.
APP_MUTEX_NAME = "TA-F_PSD_DiffBatch_Mutex"

# PSD thumbnail extraction — lazy import (only needed for the right panel).
# Logged at WARNING because losing thumbnails is a real (if minor) feature
# degradation — colleagues seeing "no previews" should land in app.log.
try:
    from psd_tools import PSDImage
    from PIL import Image
    _PIL_OK = True
except Exception as _pil_exc:  # noqa: BLE001
    logging.getLogger(__name__).warning(
        "PSD thumbnail extraction unavailable (psd_tools/PIL import failed): %s",
        _pil_exc,
    )
    _PIL_OK = False


# Match the production .jsx log line: "--- (3/8) somefile.psd ---"
PROGRESS_RE = re.compile(r"^---\s*\((\d+)/(\d+)\)\s+(.+?)\s*---\s*$")


def reveal_folder(path: str) -> None:
    """Open `path` in Windows Explorer."""
    if not path or not Path(path).exists():
        return
    try:
        os.startfile(path)  # type: ignore[attr-defined]
    except Exception as exc:
        log.warning("reveal: startfile failed: %s", exc)


# ---------------------------------------------------------------------------
# Theme & DnD utilities now live in theme.py / dnd_utils.py.
# ---------------------------------------------------------------------------

# Load saved appearance mode early — must run before CTk widgets are built.
ctk.set_appearance_mode(load_appearance_mode())
ctk.set_default_color_theme("dark-blue")  # base; we override colors per widget

# Logo path resolution (PyInstaller _MEIPASS or dev dir)
def _find_logo() -> "Path | None":
    candidates = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "assets" / "logo.png")
    candidates.append(Path(__file__).resolve().parent / "assets" / "logo.png")
    for c in candidates:
        if c.exists():
            return c
    return None


def _find_bundled_scripts_dir() -> "Path | None":
    """Locate the bundled `scripts/` folder (PyInstaller _MEIPASS or alongside
    this script in dev mode)."""
    candidates = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "scripts")
    candidates.append(Path(__file__).resolve().parent / "scripts")
    for c in candidates:
        if c.exists() and c.is_dir():
            return c
    return None

# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
#
# The App class is intentionally long in v1.5.0; v1.5.1 will split it into
# `ui/` submodules per `plan/2026-05-19-v1.5-optimization-plan.md §9.2`.
# Until then, the file is navigable via the `# REGION:` banners below — each
# one groups methods that share a single concern and would land in the same
# split file. Order matches the proposed `ui/` layout so the future split is
# a mechanical move, not a redesign.
#
# Region inventory:
#   1.  App lifecycle (__init__)
#   2.  Auto-update flow
#   3.  Right-panel file preview + batch count
#   4.  Layout & UI build (_build_ui)
#   5.  Normalizer tab
#   6.  Script Runner tab + queue
#   7.  Output panel toggle + DnD pickers + field row
#   8.  Status / progress / output text helpers
#   9.  Help menu + diagnostics
#   10. Theme switch + progress mapping + reveal
#   11. Toast banner
#   12. Presets dialog
#   13. Action handlers + queue pump + result dispatch
#   14. (module-level) AppMutex + main entry
# ---------------------------------------------------------------------------


class App:
    def __init__(self, root: ctk.CTk):
        self.root = root
        root.title("TA-F PSD DiffBatch")
        root.geometry("1200x760")
        root.configure(fg_color=C("bg"))
        root.minsize(1080, 680)

        self.q: queue.Queue = queue.Queue()
        self.worker = WorkerJob(self.q)
        # Cancel signal: set by CANCEL button, polled by ps_driver's watcher thread
        self._cancel_event = threading.Event()
        # Tracked so we can refresh-in-place on preset undo
        self._presets_dlg = None
        # Transient banner (toast) — used for the undo-delete flow
        self._toast = None
        self._toast_after_id = None

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
        # Script-queue progress (0 means single-script run, not queue mode)
        self._queue_total = 0
        self._queue_index = 0

        # File-preview state: a generation counter cancels in-flight loads
        # when the folder changes mid-load; file_rows maps name → widget dict
        self._thumb_gen = 0
        self.file_rows: dict = {}

        # Last analysis result (recipe summary + diff) — saved by Save Preset.
        self.last_analysis: dict | None = None

        # Script Runner state (Tab 2)
        self.script_path: ctk.StringVar = ctk.StringVar()        # abs path of selected .jsx
        self.script_display_var: ctk.StringVar = ctk.StringVar() # value shown in dropdown
        self.output_mode_var: ctk.StringVar = ctk.StringVar(value="Save to output")
        self._scripts_index: dict = {}  # display label → abs path
        # Run queue: list of (label, abs_path) tuples, executed in order
        self.script_queue: list = []

        self._build_ui()

        # Recount batch folder when it changes + populate file preview panel
        self.folder_path.trace_add("write", lambda *_: self._update_batch_count())
        self.folder_path.trace_add("write", lambda *_: self._populate_file_panel())
        self._update_batch_count()  # initial

        # Auto-detect Photoshop
        self.ps_app = ps_driver.find_photoshop_app_name() or "Photoshop"
        self._set_status(f"Ready · PS: {self.ps_app}", C("text_md"))

        # Keyboard shortcuts (Windows-only since v1.5.0)
        self.root.bind_all("<Control-r>", lambda e: self._on_run())
        self.root.bind_all("<Control-l>", lambda e: self._on_analyze())
        self.root.bind_all("<Control-k>", lambda e: self._clear_output())
        self.root.bind_all("<Control-period>", lambda e: self._on_cancel())

        # Background NAS update check — never blocks startup.
        self._update_dlg = None
        updater.check_async(APP_VERSION, self._on_update_check_done)

        self._poll_queue()

    # ---- Auto-update ----

    # NAS warning key — persisted in muted_warnings list. Tests assert
    # this constant so any rename breaks loud.
    NAS_UNREACHABLE_WARNING_KEY = "nas_unreachable"


# ============================================================================
# REGION 2: Auto-update flow
# ----------------------------------------------------------------------------
# Background check → dialog → download (worker thread) → /SILENT installer.
# All NAS access is best-effort; an unreachable share never blocks the GUI.
# Future split target: ui/update_dialog.py
# ============================================================================

    def _on_update_check_done(self, result):
        """Callback from updater thread. Hand back to the GUI thread via the queue.

        Receives a CheckResult (v1.5.0+). Three outcomes:
          - newer version available  → enqueue update dialog
          - NAS unreachable + !muted → enqueue one-time toast
          - otherwise                  → stay silent
        """
        if result.info is not None:
            self.q.put(("update_available", result.info))
            return
        if (not result.nas_reachable
                and not is_warning_muted(self.NAS_UNREACHABLE_WARNING_KEY)):
            self.q.put(("nas_unreachable", None))

    def _show_update_dialog(self, info):
        """Non-modal dialog: shows version + changelog + three actions."""
        if self._update_dlg is not None:
            try: self._update_dlg.destroy()
            except Exception: pass

        dlg = ctk.CTkToplevel(self.root)
        self._update_dlg = dlg
        dlg.title("Update available")
        dlg.configure(fg_color=C("bg"))
        dlg.geometry("480x340")
        dlg.transient(self.root)

        ctk.CTkLabel(
            dlg, text=f"UPDATE AVAILABLE — v{info.version}",
            text_color=C("text_md"), font=ROBOTO_CAPS,
        ).pack(anchor="w", padx=20, pady=(20, 4))
        ctk.CTkLabel(
            dlg, text=f"Current: v{APP_VERSION}   →   New: v{info.version}",
            text_color=C("text_hi"), font=("Roboto", 12, "bold"),
        ).pack(anchor="w", padx=20, pady=(0, 8))

        # Changelog (scrollable)
        cl_box = ctk.CTkTextbox(
            dlg, fg_color=C("surface_2"), text_color=C("text_hi"),
            font=MONO_FONT, corner_radius=4, border_width=0, wrap="word",
            height=140,
        )
        cl_box.pack(fill="both", expand=True, padx=20, pady=(0, 12))
        cl_box.insert("end", info.changelog or "(no changelog)")
        cl_box.configure(state="disabled")

        # Action row
        actions = ctk.CTkFrame(dlg, fg_color="transparent")
        actions.pack(fill="x", padx=20, pady=(0, 18))

        ctk.CTkButton(
            actions, text="UPDATE",
            fg_color=C("primary"), text_color=C("on_primary"), hover_color=C("primary_dk"),
            corner_radius=4, height=34, font=ROBOTO_CAPS,
            command=lambda: self._start_update_download(info),
        ).pack(side="left", expand=True, fill="x", padx=(0, 6))

        if not info.mandatory:
            ctk.CTkButton(
                actions, text="LATER",
                fg_color="transparent", border_color=C("divider"), border_width=1,
                text_color=C("text_md"), hover_color=C("surface_2"),
                corner_radius=4, height=34, font=ROBOTO_CAPS,
                command=self._dismiss_update_dialog,
            ).pack(side="left", expand=True, fill="x", padx=6)

            ctk.CTkButton(
                actions, text="MUTE THIS VERSION",
                fg_color="transparent", border_color=C("divider"), border_width=1,
                text_color=C("text_md"), hover_color=C("surface_2"),
                corner_radius=4, height=34, font=("Roboto", 9, "bold"),
                command=lambda v=info.version: self._mute_update(v),
            ).pack(side="left", expand=True, fill="x", padx=(6, 0))

    def _dismiss_update_dialog(self):
        if self._update_dlg is not None:
            try: self._update_dlg.destroy()
            except Exception: pass
            self._update_dlg = None

    def _mute_update(self, version: str):
        updater.mute_version(version)
        self._dismiss_update_dialog()
        self._show_toast(f"Muted v{version}. Future versions will still notify you.")

    def _show_nas_unreachable_toast(self):
        """One-time toast when the auto-update NAS share couldn't be reached
        on startup. Includes a "Don't show again" action that persists the
        mute via persistence.add_muted_warning. After mute, future startups
        with unreachable NAS stay silent.
        """
        nas_path = updater.DEFAULT_NAS_ROOT

        def _mute():
            add_muted_warning(self.NAS_UNREACHABLE_WARNING_KEY)

        self._show_toast(
            f"自动更新源不可达（{nas_path}）。可继续使用本地版本；连上公司网络/VPN 后会自动检测更新。",
            action_label="不再提醒",
            action_cb=_mute,
            duration_ms=12000,
        )

    def _start_update_download(self, info):
        """Convert the dialog into a progress UI, then download + apply in a thread."""
        # Wipe dialog body and re-use the window for progress.
        if self._update_dlg is None:
            return
        for child in list(self._update_dlg.winfo_children()):
            try: child.destroy()
            except Exception: pass

        ctk.CTkLabel(
            self._update_dlg, text=f"DOWNLOADING v{info.version}",
            text_color=C("text_md"), font=ROBOTO_CAPS,
        ).pack(anchor="w", padx=20, pady=(20, 8))

        pct_var = ctk.StringVar(value="0%")
        ctk.CTkLabel(
            self._update_dlg, textvariable=pct_var,
            text_color=C("text_hi"), font=("Roboto", 22, "bold"),
        ).pack(pady=(0, 8))

        bar = ctk.CTkProgressBar(
            self._update_dlg, fg_color=C("divider"), progress_color=C("primary"),
            height=6, corner_radius=2,
        )
        bar.set(0)
        bar.pack(fill="x", padx=20, pady=(0, 18))

        def on_progress(frac: float):
            self.q.put(("update_progress", (frac, pct_var, bar)))

        def worker():
            try:
                installer = updater.download_update(info, on_progress=on_progress)
            except Exception as exc:
                log.error("update download failed: %s", exc, exc_info=True)
                self.q.put(("update_error", str(exc)))
                return
            self.q.put(("update_ready", installer))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_update_now(self, installer):
        """Final step: relaunch via installer. Does not return on success."""
        try:
            updater.apply_update(installer)
        except Exception as exc:
            self._dismiss_update_dialog()
            show_error(
                self.root, "Update failed", exc,
                hint=f"无法启动安装包：{installer}\n请手动运行该安装包，或重启工具再试。",
            )


# ============================================================================
# REGION 3: Right-panel file preview + batch folder count
# ----------------------------------------------------------------------------
# Scrollable list of PSDs in the batch folder. Thumbnails load lazily in a
# worker thread; a generation token cancels in-flight loads when the folder
# changes. Bottom of the region holds the small "N PSDs found" counter that
# also drives status text on folder pick.
# Future split target: ui/file_preview.py
# ============================================================================

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
                text_color=C("text_lo"), font=("Roboto", 11), justify="center", wraplength=240,
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
                text_color=C("text_lo"), font=("Roboto", 11),
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
            self.file_list, fg_color=C("surface_2"),
            corner_radius=6, height=112,
        )
        item.pack(fill="x", pady=4, padx=2)
        item.pack_propagate(False)

        # Thumbnail container (96×96 placeholder)
        thumb_box = ctk.CTkFrame(item, width=96, height=96, fg_color=C("divider"), corner_radius=4)
        thumb_box.pack(side="left", padx=8, pady=8)
        thumb_box.pack_propagate(False)
        thumb_label = ctk.CTkLabel(thumb_box, text="…", text_color=C("text_lo"), font=("Roboto", 16))
        thumb_label.pack(expand=True)

        # Right-of-thumbnail text block
        text_box = ctk.CTkFrame(item, fg_color="transparent")
        text_box.pack(side="left", fill="both", expand=True, padx=(4, 10), pady=8)

        name_label = ctk.CTkLabel(
            text_box, text=file_path.name,
            text_color=C("text_hi"), font=("Roboto", 11, "bold"),
            anchor="w", justify="left", wraplength=180,
        )
        name_label.pack(anchor="w")

        try:
            size_mb = file_path.stat().st_size / (1024 * 1024)
            size_text = f"{size_mb:.1f} MB"
        except Exception as exc:
            log.warning("file size stat failed for %s: %s", file_path, exc)
            size_text = ""
        size_label = ctk.CTkLabel(
            text_box, text=size_text,
            text_color=C("text_lo"), font=("Roboto", 10), anchor="w",
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
        except Exception as exc:
            log.warning("psd thumbnail preview failed for %s: %s", file_path, exc)
            thumb = None
        if thumb is None:
            return

        # Build modal-ish Toplevel
        top = ctk.CTkToplevel(self.root)
        top.title(file_path.name)
        top.configure(fg_color=C("bg"))
        top.transient(self.root)

        # Resize thumbnail to fit 480×480
        img = thumb.copy()
        img.thumbnail((480, 480), Image.LANCZOS)
        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)

        ctk.CTkLabel(top, image=ctk_img, text="").pack(padx=16, pady=16)
        ctk.CTkLabel(
            top, text=file_path.name,
            text_color=C("text_hi"), font=("Roboto", 12, "bold"),
        ).pack(pady=(0, 16), padx=16)

        # Keep image reference to prevent GC
        top._img_ref = ctk_img
        # Close on Esc / click outside is hard in Tk; just give a close button.
        ctk.CTkButton(
            top, text="CLOSE",
            fg_color=C("primary"), text_color=C("on_primary"), hover_color=C("primary_dk"),
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
            except Exception as exc:
                log.warning("psd thumbnail load failed for %s: %s", p, exc)
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
        except Exception as exc:
            log.warning("thumbnail render failed for %s: %s", name, exc)
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
        except Exception as exc:
            log.warning("batch folder iterdir failed for %s: %s", folder, exc)
            self.batch_count_var.set("")


# ============================================================================
# REGION 4: Layout & UI build
# ----------------------------------------------------------------------------
# Single 240-line method that assembles every widget. Split into appbar,
# horizontal pane (content + right panel), tabview, status card, output
# textbox. Subsequent regions (5, 6) own the tab-content builders that this
# region delegates to.
# Future split target: ui/app_window.py (the shell) + ui/file_preview.py
# (the right panel pull-out, already region 3)
# ============================================================================

    def _build_ui(self):
        # ===== App Bar — slim, logo + product name =====
        appbar = ctk.CTkFrame(self.root, fg_color=C("bg"), corner_radius=0, height=56)
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
            except Exception as exc:
                log.warning("logo load failed (%s): %s", logo_path, exc)
                self._logo_img = None

        if self._logo_img:
            ctk.CTkLabel(appbar_inner, image=self._logo_img, text="").pack(side="left", anchor="center")
        else:
            ctk.CTkLabel(
                appbar_inner, text="TA-F",
                text_color=C("text_hi"), font=("Roboto", 16, "bold"),
            ).pack(side="left", anchor="center")
        ctk.CTkLabel(
            appbar_inner, text="PSD DiffBatch",
            text_color=C("text_md"), font=("Roboto", 11),
        ).pack(side="left", anchor="center", padx=(14, 0))

        # Theme switcher (right side of appbar) — live switch via CTk's
        # set_appearance_mode("Light"/"Dark"/"System"). All widgets created
        # with (light, dark) tuples re-render automatically.
        appbar_right = ctk.CTkFrame(appbar, fg_color="transparent")
        appbar_right.pack(side="right", padx=20, pady=10, fill="y")
        # Use the saved preset choice for the SegmentedButton — not
        # ctk.get_appearance_mode(), which resolves "System" to "Dark" / "Light"
        # and would lose the user's intent.
        self.theme_var = ctk.StringVar(value=load_appearance_mode())
        self.theme_seg = ctk.CTkSegmentedButton(
            appbar_right,
            values=["Dark", "Light", "System"],
            variable=self.theme_var,
            command=self._on_theme_change,
            fg_color=C("surface_2"),
            selected_color=C("primary"),
            selected_hover_color=C("primary_dk"),
            unselected_color=C("surface_2"),
            unselected_hover_color=C("divider"),
            text_color=C("on_primary"),
            corner_radius=4,
            font=("Roboto", 10, "bold"), height=28,
        )
        self.theme_seg.pack(side="right", anchor="center")

        # Help button (left of the theme switcher). Single-click opens a small
        # popup with Onboarding / About / Copy diagnostic.
        ctk.CTkButton(
            appbar_right, text="?",
            fg_color="transparent", border_color=C("divider"), border_width=1,
            text_color=C("text_md"), hover_color=C("surface_2"),
            corner_radius=14, width=28, height=28,
            font=("Roboto", 13, "bold"),
            command=self._open_help_menu,
        ).pack(side="right", anchor="center", padx=(0, 8))

        ctk.CTkFrame(self.root, fg_color=C("divider"), height=1, corner_radius=0).pack(fill="x")

        # ===== Main horizontal split (user-resizable) =====
        # Use tk.PanedWindow so the user can drag the sash to resize panels.
        # tk.PanedWindow doesn't accept CTk's (light, dark) tuple — pass a
        # plain hex and reconfigure on theme change.
        self.split = tk.PanedWindow(
            self.root, orient="horizontal",
            bg=_current_palette()["divider"], sashwidth=4, sashrelief="flat",
            showhandle=False, opaqueresize=True,
        )
        self.split.pack(fill="both", expand=True)
        split = self.split  # local alias for the rest of this method

        # Left side: original content (created below, packed first into split)
        content = ctk.CTkFrame(split, fg_color=C("bg"))
        split.add(content, minsize=560, stretch="always", padx=0, pady=0)

        # Right side: file preview panel
        right_panel = ctk.CTkFrame(
            split, fg_color=C("surface"),
            corner_radius=0, border_width=0, width=320,
        )
        split.add(right_panel, minsize=240, stretch="never", padx=0, pady=0)

        # Right-panel header
        right_hdr = ctk.CTkFrame(right_panel, fg_color="transparent")
        right_hdr.pack(fill="x", padx=16, pady=(20, 8))
        ctk.CTkLabel(
            right_hdr, text="BATCH FILES",
            text_color=C("text_md"), font=ROBOTO_CAPS,
        ).pack(side="left")
        self.file_panel_count = ctk.CTkLabel(
            right_hdr, text="—", text_color=C("text_lo"), font=("Roboto", 10),
        )
        self.file_panel_count.pack(side="right")

        # Thin divider under header
        ctk.CTkFrame(right_panel, fg_color=C("divider"), height=1, corner_radius=0).pack(fill="x", padx=12)

        # Scrollable file list
        self.file_list = ctk.CTkScrollableFrame(
            right_panel, fg_color="transparent",
        )
        self.file_list.pack(fill="both", expand=True, padx=8, pady=8)

        # Empty-state hint
        self.file_panel_hint = ctk.CTkLabel(
            self.file_list, text="Drop a folder here\nor pick a Batch folder",
            text_color=C("text_lo"), font=("Roboto", 11), justify="center", wraplength=240,
        )
        self.file_panel_hint.pack(pady=40)

        # Right panel itself accepts folder drops → sets Batch folder field.
        try:
            _register_drop_target(
                right_panel,
                on_enter=lambda e: right_panel.configure(fg_color=C("surface_2")),
                on_leave=lambda e: right_panel.configure(fg_color=C("surface")),
                on_drop=lambda e: self._on_drop_folder(e, right_panel),
            )
        except Exception as exc:
            log.warning("dnd: right-panel registration failed: %s", exc)

        # Apply inner padding to the content frame (it's already added to the paned split).
        content_inner = ctk.CTkFrame(content, fg_color="transparent")
        content_inner.pack(fill="both", expand=True, padx=20, pady=20)
        content = content_inner  # rest of build uses 'content' below

        # ===== Tabs: Normalizer / Script Runner =====
        self.tabview = ctk.CTkTabview(
            content,
            fg_color=C("surface"),
            segmented_button_fg_color=C("surface_2"),
            segmented_button_selected_color=C("primary"),
            segmented_button_selected_hover_color=C("primary_dk"),
            segmented_button_unselected_color=C("surface_2"),
            segmented_button_unselected_hover_color=C("divider"),
            text_color=C("on_primary"),
            text_color_disabled=C("text_lo"),
            corner_radius=8,
            border_width=1,
            border_color=C("divider"),
        )
        self.tabview.pack(fill="x")
        self.tabview.add("Normalizer")
        self.tabview.add("Script Runner")

        self._build_normalizer_tab(self.tabview.tab("Normalizer"))
        self._build_script_runner_tab(self.tabview.tab("Script Runner"))

        # ===== Status card: dot + text + percentage above a real progress bar =====
        status_card = ctk.CTkFrame(
            content, fg_color=C("surface_2"), corner_radius=6,
        )
        status_card.pack(fill="x", pady=(14, 6))

        sc_inner = ctk.CTkFrame(status_card, fg_color="transparent")
        sc_inner.pack(fill="x", padx=14, pady=10)

        top_row = ctk.CTkFrame(sc_inner, fg_color="transparent")
        top_row.pack(fill="x")

        # State indicator dot (gray idle / white running / green ok / red error)
        self.status_dot = ctk.CTkLabel(
            top_row, text="●",
            text_color=C("text_lo"), font=("Roboto", 16),
        )
        self.status_dot.pack(side="left", padx=(0, 8))

        self.status_var = ctk.StringVar(value="Ready")
        ctk.CTkLabel(
            top_row, textvariable=self.status_var,
            text_color=C("text_hi"), font=("Roboto", 11, "bold"),
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        self.pct_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            top_row, textvariable=self.pct_var,
            text_color=C("text_md"), font=("Roboto", 11, "bold"),
            anchor="e",
        ).pack(side="right")

        # Real CTkProgressBar — reliable updates via .set(frac).
        self.progress_bar = ctk.CTkProgressBar(
            sc_inner, orientation="horizontal",
            fg_color=C("divider"), progress_color=C("primary"),
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
            fg_color="transparent", hover_color=C("surface_2"),
            text_color=C("text_md"), font=ROBOTO_CAPS,
            border_width=0, corner_radius=4, height=24, anchor="w",
            command=self._toggle_output,
        )
        self._toggle_btn.pack(side="left", padx=(0, 0))

        self.out_card = ctk.CTkFrame(
            content, fg_color=C("surface"),
            corner_radius=8, border_width=1, border_color=C("divider"),
        )
        # not packed yet; _show_output() will pack it

        self.output = ctk.CTkTextbox(
            self.out_card,
            fg_color=C("surface_2"),
            text_color=C("text_hi"),
            font=MONO_FONT,
            corner_radius=4,
            border_width=0,
            wrap="word",
        )
        self.output.pack(fill="both", expand=True, padx=12, pady=12)
        self.output.configure(state="disabled")


# ============================================================================
# REGION 5: Normalizer tab
# ----------------------------------------------------------------------------
# Tab 1: After/Before PSD pickers + batch folder + ANALYZE / RUN BATCH /
# CANCEL / PRESETS / CLEAR / REVEAL OUTPUT action bar. Action handlers
# themselves live in region 13.
# Future split target: ui/normalizer_tab.py
# ============================================================================

    def _build_normalizer_tab(self, parent):
        """Build the original PSD Normalizer inputs card + action bar inside `parent`."""
        # Inputs
        ctk.CTkLabel(
            parent, text="INPUTS",
            text_color=C("text_md"), font=ROBOTO_CAPS,
        ).pack(anchor="w", padx=4, pady=(4, 8))

        self._field_row(parent, "After PSD",          self.after_path,  is_folder=False)
        self._field_row(parent, "Before PSD (opt.)",  self.before_path, is_folder=False)
        self._field_row(parent, "Batch folder",       self.folder_path, is_folder=True,
                        sublabel_var=self.batch_count_var)
        self._field_row(parent, "Output (opt.)",      self.output_path, is_folder=True)
        ctk.CTkFrame(parent, fg_color="transparent", height=12).pack()

        # Action bar
        action = ctk.CTkFrame(parent, fg_color="transparent")
        action.pack(fill="x", padx=4, pady=(8, 4))

        self.btn_analyze = ctk.CTkButton(
            action, text="ANALYZE",
            fg_color="transparent", border_color=C("primary"), border_width=1,
            text_color=C("primary"), hover_color=C("surface_2"),
            corner_radius=4, width=120, height=36, font=ROBOTO_CAPS,
            command=self._on_analyze,
        )
        self.btn_analyze.pack(side="left", padx=(0, 8))

        self.btn_run = ctk.CTkButton(
            action, text="RUN BATCH",
            fg_color=C("primary"), hover_color=C("primary_dk"),
            text_color=C("on_primary"),
            corner_radius=4, width=160, height=36, font=ROBOTO_CAPS,
            command=self._on_run,
        )
        self.btn_run.pack(side="left")

        self.btn_cancel = ctk.CTkButton(
            action, text="CANCEL",
            fg_color="transparent", border_color=C("danger"), border_width=1,
            text_color=C("danger"), hover_color=C("surface_2"),
            corner_radius=4, width=100, height=36, font=ROBOTO_CAPS,
            command=self._on_cancel, state="disabled",
        )
        self.btn_cancel.pack(side="left", padx=(8, 0))

        self.btn_presets = ctk.CTkButton(
            action, text="PRESETS",
            fg_color="transparent", border_color=C("divider"), border_width=1,
            text_color=C("text_md"), hover_color=C("surface_2"),
            corner_radius=4, width=100, height=36, font=ROBOTO_CAPS,
            command=self._open_presets_dialog,
        )
        self.btn_presets.pack(side="left", padx=(8, 0))

        self.btn_clear = ctk.CTkButton(
            action, text="CLEAR",
            fg_color="transparent", border_width=0,
            text_color=C("primary"), hover_color=C("surface_2"),
            corner_radius=4, width=80, height=36, font=ROBOTO_CAPS,
            command=self._clear_output,
        )
        self.btn_clear.pack(side="right")

        self.btn_reveal = ctk.CTkButton(
            action, text="REVEAL OUTPUT",
            fg_color="transparent", border_color=C("primary"), border_width=1,
            text_color=C("primary"), hover_color=C("surface_2"),
            corner_radius=4, width=160, height=36, font=ROBOTO_CAPS,
            command=self._reveal_output,
            state="disabled",
        )
        self.btn_reveal.pack(side="right", padx=(0, 8))


# ============================================================================
# REGION 6: Script Runner tab + queue
# ----------------------------------------------------------------------------
# Tab 2: dropdown of bundled + user-added .jsx scripts, optional run-queue
# (multi-script back-to-back), output mode segmented control, and the
# multi-pass orchestrator `_run_script_queue`. This is the largest region
# (~400 lines) and is the first target for physical split in v1.5.1.
# Future split target: ui/script_runner_tab.py
# ============================================================================

    def _build_script_runner_tab(self, parent):
        ctk.CTkLabel(
            parent, text="SCRIPT",
            text_color=C("text_md"), font=ROBOTO_CAPS,
        ).pack(anchor="w", padx=4, pady=(4, 8))

        # Script row: dropdown + Browse + manage button
        sr_wrap = ctk.CTkFrame(parent, fg_color="transparent")
        sr_wrap.pack(fill="x", padx=4, pady=(0, 4))

        ctk.CTkLabel(
            sr_wrap, text="SCRIPT (.jsx)",
            text_color=C("text_lo"), font=("Roboto", 9, "bold"),
            anchor="w",
        ).pack(fill="x")

        sr_row = ctk.CTkFrame(sr_wrap, fg_color="transparent")
        sr_row.pack(fill="x", pady=(2, 0))

        self.script_dropdown = ctk.CTkOptionMenu(
            sr_row,
            variable=self.script_display_var,
            values=["(no scripts found)"],
            command=self._on_script_selected,
            fg_color=C("surface_2"),
            button_color=C("surface_2"),
            button_hover_color=C("divider"),
            text_color=C("text_hi"),
            dropdown_fg_color=C("surface"),
            dropdown_text_color=C("text_hi"),
            dropdown_hover_color=C("surface_2"),
            font=ROBOTO_REG,
            height=32, corner_radius=4,
        )
        self.script_dropdown.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            sr_row, text="+ Add",
            fg_color=C("primary"), hover_color=C("primary_dk"),
            text_color=C("on_primary"),
            corner_radius=4, width=72, height=34, font=ROBOTO_CAPS,
            command=self._add_to_queue,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            sr_row, text="Browse",
            fg_color="transparent", hover_color=C("surface_2"),
            text_color=C("primary"), border_color=C("divider"), border_width=1,
            corner_radius=4, width=80, height=34, font=ROBOTO_CAPS,
            command=self._browse_script,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            sr_row, text="+ Dir",
            fg_color="transparent", hover_color=C("surface_2"),
            text_color=C("text_md"), border_color=C("divider"), border_width=1,
            corner_radius=4, width=72, height=34, font=ROBOTO_CAPS,
            command=self._add_user_scripts_dir,
        ).pack(side="left")

        # Selected-script hint (full path, small text)
        self.script_path_hint = ctk.CTkLabel(
            sr_wrap, textvariable=self.script_path,
            text_color=C("text_lo"), font=("Roboto", 10),
            anchor="w", wraplength=560, justify="left",
        )
        self.script_path_hint.pack(fill="x", pady=(2, 0))

        # Run queue display
        q_wrap = ctk.CTkFrame(parent, fg_color="transparent")
        q_wrap.pack(fill="x", padx=4, pady=(8, 4))

        q_hdr = ctk.CTkFrame(q_wrap, fg_color="transparent")
        q_hdr.pack(fill="x")
        ctk.CTkLabel(
            q_hdr, text="RUN QUEUE",
            text_color=C("text_lo"), font=("Roboto", 9, "bold"),
            anchor="w",
        ).pack(side="left")
        self.queue_count_label = ctk.CTkLabel(
            q_hdr, text="(empty — uses the script above)",
            text_color=C("text_lo"), font=("Roboto", 9),
            anchor="e",
        )
        self.queue_count_label.pack(side="right")
        ctk.CTkButton(
            q_hdr, text="Clear",
            fg_color="transparent", hover_color=C("surface_2"),
            text_color=C("text_md"), border_width=0,
            corner_radius=4, width=60, height=22, font=("Roboto", 10),
            command=self._clear_queue,
        ).pack(side="right", padx=(0, 8))

        self.queue_list = ctk.CTkScrollableFrame(
            q_wrap, fg_color=C("surface_2"),
            height=120, corner_radius=4,
        )
        self.queue_list.pack(fill="x", pady=(2, 0))

        # Batch folder (shared with Normalizer via self.folder_path)
        self._field_row(parent, "Batch folder", self.folder_path, is_folder=True,
                        sublabel_var=self.batch_count_var)

        # Output folder (shared)
        self._field_row(parent, "Output (opt.)", self.output_path, is_folder=True)

        # Output mode segmented control
        om_wrap = ctk.CTkFrame(parent, fg_color="transparent")
        om_wrap.pack(fill="x", padx=4, pady=(6, 2))
        ctk.CTkLabel(
            om_wrap, text="OUTPUT MODE",
            text_color=C("text_lo"), font=("Roboto", 9, "bold"),
            anchor="w",
        ).pack(fill="x")
        self.output_mode_seg = ctk.CTkSegmentedButton(
            om_wrap,
            values=["Save to output", "Overwrite", "Don't save"],
            variable=self.output_mode_var,
            fg_color=C("surface_2"),
            selected_color=C("primary"),
            selected_hover_color=C("primary_dk"),
            unselected_color=C("surface_2"),
            unselected_hover_color=C("divider"),
            text_color=C("on_primary"),
            corner_radius=4,
            font=ROBOTO_REG, height=32,
        )
        self.output_mode_seg.pack(fill="x", pady=(2, 0))

        ctk.CTkFrame(parent, fg_color="transparent", height=12).pack()

        # Action bar (script runner)
        sr_action = ctk.CTkFrame(parent, fg_color="transparent")
        sr_action.pack(fill="x", padx=4, pady=(8, 4))

        self.btn_run_script = ctk.CTkButton(
            sr_action, text="RUN SCRIPT",
            fg_color=C("primary"), hover_color=C("primary_dk"),
            text_color=C("on_primary"),
            corner_radius=4, width=160, height=36, font=ROBOTO_CAPS,
            command=self._on_run_custom_script,
        )
        self.btn_run_script.pack(side="left")

        self.btn_cancel_script = ctk.CTkButton(
            sr_action, text="CANCEL",
            fg_color="transparent", border_color=C("danger"), border_width=1,
            text_color=C("danger"), hover_color=C("surface_2"),
            corner_radius=4, width=100, height=36, font=ROBOTO_CAPS,
            command=self._on_cancel, state="disabled",
        )
        self.btn_cancel_script.pack(side="left", padx=(8, 0))

        # Populate dropdown + empty queue UI now that all widgets exist
        self._refresh_script_list()
        self._refresh_queue_ui()

    # ---- Script Runner helpers ----

    def _refresh_script_list(self):
        """Re-scan bundled + user dirs, repopulate dropdown."""
        items = []  # list[(label, abs_path)]
        bundled = _find_bundled_scripts_dir()
        if bundled:
            for p in sorted(bundled.glob("*.jsx")):
                items.append((f"(builtin) {p.name}", str(p)))
        for d in load_user_scripts_dirs():
            dp = Path(d)
            if dp.exists() and dp.is_dir():
                for p in sorted(dp.glob("*.jsx")):
                    items.append((f"{dp.name}/{p.name}", str(p)))

        if not items:
            self._scripts_index = {}
            self.script_dropdown.configure(values=["(no scripts found)"])
            self.script_display_var.set("(no scripts found)")
            return

        self._scripts_index = {label: path for label, path in items}
        labels = list(self._scripts_index.keys())
        self.script_dropdown.configure(values=labels)

        # Keep current selection if still valid, otherwise pick first
        current = self.script_display_var.get()
        if current not in self._scripts_index:
            self.script_display_var.set(labels[0])
            self.script_path.set(self._scripts_index[labels[0]])
        else:
            self.script_path.set(self._scripts_index[current])

    def _on_script_selected(self, label: str):
        path = self._scripts_index.get(label)
        if path:
            self.script_path.set(path)

    def _browse_script(self):
        p = filedialog.askopenfilename(
            title="Select .jsx",
            filetypes=[("ExtendScript", "*.jsx *.js"), ("All", "*.*")],
        )
        if not p:
            return
        # Direct one-off pick: not from a registered dir. Add a synthetic entry.
        label = f"(picked) {Path(p).name}"
        self._scripts_index[label] = p
        self.script_dropdown.configure(values=list(self._scripts_index.keys()))
        self.script_display_var.set(label)
        self.script_path.set(p)

    def _add_user_scripts_dir(self):
        d = filedialog.askdirectory(title="Add scripts directory")
        if not d:
            return
        dirs = load_user_scripts_dirs()
        if d not in dirs:
            dirs.append(d)
            save_user_scripts_dirs(dirs)
        self._refresh_script_list()

    # ---- Run queue ----

    def _add_to_queue(self):
        """Append the currently selected dropdown script to the run queue."""
        path = self.script_path.get()
        label = self.script_display_var.get()
        if not path or label == "(no scripts found)":
            messagebox.showwarning("Empty selection", "Pick a script first.")
            return
        self.script_queue.append((label, path))
        self._refresh_queue_ui()

    def _remove_from_queue(self, index: int):
        if 0 <= index < len(self.script_queue):
            self.script_queue.pop(index)
            self._refresh_queue_ui()

    def _clear_queue(self):
        self.script_queue.clear()
        self._refresh_queue_ui()

    def _refresh_queue_ui(self):
        """Rebuild the queue list rows in place."""
        for child in self.queue_list.winfo_children():
            child.destroy()

        n = len(self.script_queue)
        if n == 0:
            self.queue_count_label.configure(text="(empty — uses the script above)")
            ctk.CTkLabel(
                self.queue_list, text="Click + Add to queue scripts.",
                text_color=C("text_lo"), font=("Roboto", 10),
            ).pack(pady=12)
            return

        self.queue_count_label.configure(text=f"{n} script{'s' if n != 1 else ''}")
        for i, (label, _path) in enumerate(self.script_queue):
            row = ctk.CTkFrame(self.queue_list, fg_color="transparent")
            row.pack(fill="x", padx=4, pady=2)
            ctk.CTkLabel(
                row, text=f"{i + 1}.",
                text_color=C("text_lo"), font=("Roboto", 10, "bold"),
                width=24, anchor="w",
            ).pack(side="left")
            ctk.CTkLabel(
                row, text=label,
                text_color=C("text_hi"), font=ROBOTO_REG,
                anchor="w",
            ).pack(side="left", fill="x", expand=True)
            ctk.CTkButton(
                row, text="×",
                fg_color="transparent", hover_color=C("surface"),
                text_color=C("danger"), border_width=0,
                corner_radius=4, width=24, height=22, font=("Roboto", 14, "bold"),
                command=lambda idx=i: self._remove_from_queue(idx),
            ).pack(side="right")

    def _on_run_custom_script(self):
        # Resolve scripts: queue takes priority, dropdown selection is fallback
        if self.script_queue:
            scripts = list(self.script_queue)  # copy [(label, path), ...]
        elif self.script_path.get():
            scripts = [(self.script_display_var.get(), self.script_path.get())]
        else:
            messagebox.showwarning("Missing input", "Pick a .jsx script or add some to the queue.")
            return
        if not self.folder_path.get():
            messagebox.showwarning("Missing input", "Pick the batch folder.")
            return
        if self.worker.alive():
            return

        mode_map = {
            "Save to output": "save_to_output",
            "Overwrite":      "overwrite",
            "Don't save":     "no_save",
        }
        mode = mode_map.get(self.output_mode_var.get(), "save_to_output")

        self._clear_output()
        n = len(scripts)
        if n == 1:
            self._append(f"Run script · PS: {self.ps_app}")
            self._append(f"Script: {scripts[0][1]}")
        else:
            self._append(f"Run queue · {n} scripts · PS: {self.ps_app}")
            for i, (label, _) in enumerate(scripts):
                self._append(f"  {i + 1}. {label}")
        self._append(f"Mode: {self.output_mode_var.get()}")
        self._set_status("Running script…" if n == 1 else f"Running queue · 0/{n}")
        self._set_buttons_enabled(False)
        self.btn_cancel.configure(state="normal")
        self.btn_cancel_script.configure(state="normal")
        self.btn_reveal.configure(state="disabled")
        self._cancel_event.clear()
        self._done_files = 0
        self._total_files = 0
        self._queue_total = n if n > 1 else 0  # 0 means single-script (no compositing)
        self._queue_index = 0
        self._reset_progress()
        self._set_state("running")
        self._show_output()

        def on_log_line(line: str):
            self.q.put(("log", line))

        self.worker.start(
            self._run_script_queue,
            scripts,
            self.folder_path.get(),
            mode,
            self.output_path.get() or None,
            self.ps_app,
            on_log_line,
            self._cancel_event,
        )

    def _run_script_queue(self, scripts, batch_folder, output_mode, output_folder,
                          ps_app, on_log_line, cancel_event):
        """Worker thread target: run each script in turn over the same batch folder.
        Aggregates the per-script results into a single dict for _handle_done."""
        n = len(scripts)
        total_processed = 0
        total_failed = 0
        all_errors = []
        last_out = None
        per_script = []

        for i, (label, path) in enumerate(scripts):
            if cancel_event is not None and cancel_event.is_set():
                break
            # Tell UI which script we're on (drives composite progress + status)
            self.q.put(("queue_progress", (i, n, label)))
            if n > 1:
                on_log_line(f">>> Script {i + 1}/{n}: {label}")
            try:
                result = ps_driver.run_custom_script(
                    path, batch_folder, output_mode, output_folder,
                    ps_app, on_log_line, cancel_event,
                )
            except Exception as exc:
                log.error("script %s crashed: %s", label, exc, exc_info=True)
                on_log_line(f"!!! Script {label} crashed: {exc}")
                per_script.append({"label": label, "error": str(exc)})
                continue

            proc = int(result.get("processed", 0))
            fail = int(result.get("failed", 0))
            errs = result.get("errors", []) or []
            out  = result.get("outputFolder")
            total_processed += proc
            total_failed += fail
            for e in errs:
                tagged = dict(e)
                tagged["script"] = label
                all_errors.append(tagged)
            if out:
                last_out = out
            per_script.append({"label": label, "processed": proc, "failed": fail})
            if n > 1:
                on_log_line(f"<<< Script {i + 1}/{n} done: {proc} ok, {fail} failed")

        # Mark queue end (drives progress bar to 100%)
        self.q.put(("queue_progress", (n, n, "done")))

        return {
            "ok": True,
            "queue": n > 1,
            "scripts": per_script,
            "processed": total_processed,
            "failed": total_failed,
            "errors": all_errors,
            "outputFolder": last_out,
        }


# ============================================================================
# REGION 7: Output panel + field row + DnD pickers
# ----------------------------------------------------------------------------
# Collapsible output textbox toggle + the `_field_row` helper that builds
# every "label + entry + Browse" row + DnD entry/folder handlers + the
# filedialog pick wrapper. Concerns share the "user picks a file/folder
# and we react" pattern.
# Future split target: stays in ui/app_window.py (cross-tab helpers).
# ============================================================================

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
            text_color=C("text_lo"), font=("Roboto", 9, "bold"),
            anchor="w",
        ).pack(fill="x")

        row = ctk.CTkFrame(wrapper, fg_color="transparent")
        row.pack(fill="x", pady=(2, 0))

        entry = ctk.CTkEntry(
            row, textvariable=var,
            fg_color=C("surface_2"), border_color=C("divider"),
            text_color=C("text_hi"), font=ROBOTO_REG, height=32,
            corner_radius=4, border_width=1,
            placeholder_text="Drag here or click Browse",
        )
        entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        _register_drop_target(
            entry,
            on_enter=lambda e: entry.configure(border_color=C("primary")),
            on_leave=lambda e: entry.configure(border_color=C("divider")),
            on_drop=lambda e, v=var, w=entry: self._on_dnd(e, v, w),
        )

        ctk.CTkButton(
            row, text="Browse",
            fg_color="transparent", hover_color=C("surface_2"),
            text_color=C("primary"), border_color=C("divider"), border_width=1,
            corner_radius=4, width=88, height=34, font=ROBOTO_CAPS,
            command=lambda: self._pick(var, label_text, is_folder),
        ).pack(side="left")

        # Optional sub-label below the input (e.g., "5 PSD files found" for batch).
        if sublabel_var is not None:
            ctk.CTkLabel(
                wrapper, textvariable=sublabel_var,
                text_color=C("text_lo"), font=("Roboto", 10),
                anchor="w",
            ).pack(fill="x", pady=(2, 0))

    def _on_dnd(self, event, var, entry):
        path = _parse_dnd_path(event.data)
        if path:
            var.set(path)
        # Reset border color (DropLeave doesn't always fire after Drop on all platforms)
        try: entry.configure(border_color=C("divider"))
        except Exception: pass

    def _on_drop_folder(self, event, panel_widget):
        """Right-panel drop handler: dropped folder → Batch folder field."""
        path = _parse_dnd_path(event.data)
        try: panel_widget.configure(fg_color=C("surface"))
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


# ============================================================================
# REGION 8: Status / progress / output text helpers
# ----------------------------------------------------------------------------
# Single-purpose mutators for the status bar, progress bar, and output
# textbox. Every "tell the user something is happening" call ends up here.
# Future split target: stays in ui/app_window.py.
# ============================================================================

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
            "idle":    (C("text_lo"), C("primary")),
            "running": (C("primary"), C("primary")),
            "ok":      (C("ok"),      C("ok")),
            "error":   (C("danger"),  C("danger")),
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
        # Script Runner buttons (may not exist if called very early)
        if hasattr(self, "btn_run_script"):
            self.btn_run_script.configure(state=state)
        if enabled:
            # Back to idle — cancel has nothing to act on
            self.btn_cancel.configure(state="disabled")
            if hasattr(self, "btn_cancel_script"):
                self.btn_cancel_script.configure(state="disabled")


# ============================================================================
# REGION 9: Help menu + diagnostics
# ----------------------------------------------------------------------------
# Appbar "?" popup: Onboarding (NAS) / About / Copy diagnostic info. The
# diagnostic path delegates to `diagnostics.build_report` so the GUI here
# only handles clipboard + toast.
# Future split target: ui/help_menu.py
# ============================================================================

    def _open_help_menu(self):
        """Small Toplevel near the appbar with three actions."""
        popup = ctk.CTkToplevel(self.root)
        popup.title("Help")
        popup.configure(fg_color=C("bg"))
        popup.geometry("280x180")
        popup.transient(self.root)
        popup.attributes("-topmost", True)

        # Position near the top-right of the main window
        try:
            x = self.root.winfo_rootx() + self.root.winfo_width() - 300
            y = self.root.winfo_rooty() + 56
            popup.geometry(f"+{x}+{y}")
        except Exception:
            pass

        def _btn(text, command):
            ctk.CTkButton(
                popup, text=text,
                fg_color="transparent", hover_color=C("surface_2"),
                text_color=C("text_hi"), border_color=C("divider"), border_width=1,
                corner_radius=4, height=34, anchor="w", font=ROBOTO_REG,
                command=lambda: (popup.destroy(), command()),
            ).pack(fill="x", padx=12, pady=4)

        _btn("Open Onboarding (NAS)", self._open_onboarding)
        _btn("About this version", self._show_about)
        _btn("Copy diagnostic info", self._copy_diagnostic_info)

    def _open_onboarding(self):
        """Open the team README on the NAS in the user's default app."""
        readme = Path(updater.DEFAULT_NAS_ROOT) / "README.md"
        if not readme.exists():
            messagebox.showinfo(
                "Onboarding not available",
                f"Couldn't reach the NAS share at:\n\n{updater.DEFAULT_NAS_ROOT}\n\n"
                "Check that you're on the office network or VPN.",
            )
            return
        try:
            os.startfile(str(readme))  # type: ignore[attr-defined]
        except Exception as exc:
            show_error(
                self.root, "Failed to open", exc,
                hint=f"无法打开 NAS 上的 README：{readme}",
            )

    def _show_about(self):
        messagebox.showinfo(
            "About",
            f"TA-F PSD DiffBatch v{APP_VERSION}\n"
            f"Photoshop: {self.ps_app}\n"
            f"Python: {sys.version.split()[0]}\n\n"
            f"Auto-update source: {updater._manifest_path()}",
        )

    def _copy_diagnostic_info(self):
        """Build a paste-ready diagnostic block and copy to clipboard.

        Pulls from three log sources via diagnostics.build_report so the
        maintainer sees the same context the user does:
          - GUI output panel (last 50 lines)
          - app.log (last 200 — structured logging from all modules)
          - normalize_log.txt + script_run_log.txt (last 100 each — the
            ExtendScript layer where most real PS failures show up)
        """
        try:
            gui_lines = self.output.get("1.0", "end").splitlines()
        except Exception as exc:
            log.warning("could not read GUI output for diagnostic: %s", exc)
            gui_lines = []

        ctx = DiagnosticContext(
            version=APP_VERSION,
            ps_app=self.ps_app,
            after_path=self.after_path.get(),
            before_path=self.before_path.get(),
            folder_path=self.folder_path.get(),
            output_path=self.output_path.get(),
            last_output_folder=self.last_output_folder,
        )
        report = build_report(ctx, gui_lines)

        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(report)
            self.root.update()
            self._show_toast("Diagnostic info copied. Paste into chat to send.")
        except Exception as exc:
            show_error(
                self.root, "Clipboard error", exc,
                hint="无法写入剪贴板。请改用 Help → About 复制版本信息后手动粘贴。",
            )


# ============================================================================
# REGION 10: Theme switch + progress mapping + reveal
# ----------------------------------------------------------------------------
# Theme segmented-button callback (Dark/Light/System), the regex-driven
# progress-line parser that maps ExtendScript "(3/8) foo.psd" lines onto
# the progress bar, and the Reveal-in-Explorer trigger.
# Future split target: ui/app_window.py (live-app helpers).
# ============================================================================

    def _on_theme_change(self, mode: str):
        """Segmented-button callback. Live-applies the chosen appearance mode."""
        if mode not in ("Dark", "Light", "System"):
            return
        ctk.set_appearance_mode(mode)
        # tk.PanedWindow doesn't accept (light, dark) tuples — patch by hand.
        try:
            self.split.configure(bg=_current_palette()["divider"])
        except Exception as exc:
            log.warning("theme: PanedWindow reconfigure failed: %s", exc)
        save_appearance_mode(mode)

    # ---- Reveal ----

    def _maybe_update_progress(self, line: str):
        m = PROGRESS_RE.match(line)
        if not m: return
        done = int(m.group(1)) - 1   # this file just STARTED, so completed = N-1
        total = int(m.group(2))
        self._done_files = done
        self._total_files = total
        internal_frac = done / total if total else 0
        if self._queue_total > 1:
            overall = (self._queue_index + internal_frac) / self._queue_total
            self._set_progress(overall)
            self._set_status(
                f"Script {self._queue_index + 1}/{self._queue_total} · "
                f"{m.group(1)}/{total} — {m.group(3)}"
            )
        else:
            self._set_progress(internal_frac)
            self._set_status(f"Running · {m.group(1)}/{total} — {m.group(3)}")

    def _reveal_output(self):
        if self.last_output_folder:
            reveal_folder(self.last_output_folder)


# ============================================================================
# REGION 11: Toast banner
# ----------------------------------------------------------------------------
# Bottom-center transient message strip used by preset delete-undo, mute
# confirmation, and the NAS-unreachable first-launch warning.
# Future split target: ui/app_window.py (toast is window-scope).
# ============================================================================

    def _show_toast(self, message: str, action_label: str | None = None,
                    action_cb=None, duration_ms: int = 8000) -> None:
        """Bottom-center transient banner on the main window. Optional action button."""
        self._dismiss_toast()

        toast = ctk.CTkFrame(
            self.root, fg_color=C("surface_2"),
            corner_radius=8, border_width=1, border_color=C("divider"),
        )
        ctk.CTkLabel(
            toast, text=message,
            text_color=C("text_hi"), font=("Roboto", 12),
        ).pack(side="left", padx=14, pady=10)

        if action_label and action_cb:
            def _on_action():
                try:
                    action_cb()
                finally:
                    self._dismiss_toast()
            ctk.CTkButton(
                toast, text=action_label,
                fg_color="transparent", border_color=C("primary"), border_width=1,
                text_color=C("primary"), hover_color=C("surface"),
                corner_radius=4, width=70, height=28, font=ROBOTO_CAPS,
                command=_on_action,
            ).pack(side="left", padx=(4, 10), pady=8)

        toast.place(relx=0.5, rely=0.96, anchor="s")
        toast.lift()  # float above panes

        self._toast = toast
        self._toast_after_id = self.root.after(duration_ms, self._dismiss_toast)

    def _dismiss_toast(self) -> None:
        after_id = self._toast_after_id
        if after_id is not None:
            try: self.root.after_cancel(after_id)
            except Exception: pass
            self._toast_after_id = None
        if self._toast is not None:
            try: self._toast.destroy()
            except Exception: pass
            self._toast = None


# ============================================================================
# REGION 12: Presets dialog
# ----------------------------------------------------------------------------
# Modal dialog with list + Save-current + per-row Load/Delete + undo-delete
# via toast. Persists via persistence.save_presets (atomic write since v1.5).
# Future split target: ui/presets_dialog.py
# ============================================================================

    def _close_presets_dlg(self) -> None:
        dlg = self._presets_dlg
        self._presets_dlg = None
        if dlg is not None:
            try: dlg.destroy()
            except Exception: pass

    def _open_presets_dialog(self):
        # Replace any existing preset dialog (so callers can use this for refresh).
        self._close_presets_dlg()

        dlg = ctk.CTkToplevel(self.root)
        dlg.title("Presets")
        dlg.configure(fg_color=C("bg"))
        dlg.geometry("520x520")
        dlg.transient(self.root)
        self._presets_dlg = dlg
        dlg.protocol("WM_DELETE_WINDOW", self._close_presets_dlg)

        # Top header
        ctk.CTkLabel(
            dlg, text="PRESETS",
            text_color=C("text_md"), font=ROBOTO_CAPS,
        ).pack(anchor="w", padx=20, pady=(18, 4))
        ctk.CTkFrame(dlg, fg_color=C("divider"), height=1, corner_radius=0).pack(fill="x", padx=20)

        # Scrollable list
        body = ctk.CTkScrollableFrame(dlg, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=12)

        presets = load_presets()

        if not presets:
            ctk.CTkLabel(
                body, text="No saved presets yet.\nUse «Save current» below.",
                text_color=C("text_lo"), font=("Roboto", 11), justify="center",
            ).pack(pady=40)
        else:
            for idx, p in enumerate(presets):
                self._make_preset_row(body, p, idx, dlg)

        # Bottom action: Save Current
        bottom = ctk.CTkFrame(dlg, fg_color="transparent")
        bottom.pack(fill="x", padx=20, pady=(8, 18))
        ctk.CTkButton(
            bottom, text="SAVE CURRENT AS PRESET…",
            fg_color=C("primary"), text_color=C("on_primary"), hover_color=C("primary_dk"),
            corner_radius=4, height=36, font=ROBOTO_CAPS,
            command=lambda: self._save_current_preset_then_refresh(dlg),
        ).pack(fill="x")

    def _make_preset_row(self, parent, preset: dict, idx: int, dlg):
        row = ctk.CTkFrame(parent, fg_color=C("surface"), corner_radius=6)
        row.pack(fill="x", pady=4)

        # Left text block
        text_block = ctk.CTkFrame(row, fg_color="transparent")
        text_block.pack(side="left", fill="both", expand=True, padx=12, pady=10)

        ctk.CTkLabel(
            text_block, text=preset.get("name", "(unnamed)"),
            text_color=C("text_hi"), font=("Roboto", 12, "bold"),
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
            text_color=C("text_lo"), font=("Roboto", 10),
            anchor="w", wraplength=320, justify="left",
        ).pack(anchor="w", pady=(2, 0))

        # Right buttons
        btn_block = ctk.CTkFrame(row, fg_color="transparent")
        btn_block.pack(side="right", padx=8, pady=10)

        ctk.CTkButton(
            btn_block, text="LOAD",
            fg_color=C("primary"), text_color=C("on_primary"), hover_color=C("primary_dk"),
            corner_radius=4, width=70, height=30, font=ROBOTO_CAPS,
            command=lambda i=idx: self._load_preset(i, dlg),
        ).pack(side="top")

        ctk.CTkButton(
            btn_block, text="DELETE",
            fg_color="transparent", border_color=C("divider"), border_width=1,
            text_color=C("text_md"), hover_color=C("surface_2"),
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

        # Refresh dialog (close-and-reopen handled inside)
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
        self._close_presets_dlg()

    def _delete_preset(self, idx: int, dlg):
        presets = load_presets()
        if idx < 0 or idx >= len(presets):
            return
        deleted = presets[idx]
        name = deleted.get("name", "(unnamed)")
        del presets[idx]
        save_presets(presets)
        self._open_presets_dialog()  # refresh-in-place (closes old, opens new)
        # Undo banner — snapshots the deleted entry so it can be re-inserted
        self._show_toast(
            f"Deleted «{name}»",
            action_label="UNDO",
            action_cb=lambda d=deleted, i=idx: self._undo_delete_preset(d, i),
        )

    def _undo_delete_preset(self, deleted: dict, orig_idx: int):
        presets = load_presets()
        # Drop duplicate by name (in case user re-saved one with same name in between)
        presets = [p for p in presets if p.get("name") != deleted.get("name")]
        idx = max(0, min(orig_idx, len(presets)))
        presets.insert(idx, deleted)
        save_presets(presets)
        if self._presets_dlg is not None:
            self._open_presets_dialog()
        self._show_toast(f"Restored «{deleted.get('name', '')}»", duration_ms=3000)


# ============================================================================
# REGION 13: Action handlers + queue pump + result dispatch
# ----------------------------------------------------------------------------
# `_on_analyze` / `_on_run` / `_on_cancel` kick off background work via
# WorkerJob; `_poll_queue` drains messages from the worker every 100 ms;
# `_handle_done` switches on result shape (analyze recipe vs batch result
# vs script-runner aggregate) and updates UI accordingly.
# Future split target: ui/app_window.py — these are the main-window orchestration
# core.
# ============================================================================

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
        self.btn_cancel.configure(state="normal")
        self.btn_reveal.configure(state="disabled")
        self._cancel_event.clear()
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
            cancel_event=self._cancel_event,
        )

    def _on_cancel(self):
        if not self.worker.alive():
            return
        if self._cancel_event.is_set():
            return
        self._cancel_event.set()
        self._set_status("Cancelling… (will stop after current PSD)")
        self.btn_cancel.configure(state="disabled")
        if hasattr(self, "btn_cancel_script"):
            self.btn_cancel_script.configure(state="disabled")

    # ---- Queue pump ----

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "status":
                    self._set_status(payload, C("secondary"))
                elif kind == "log":
                    self._append(payload)
                    self._maybe_update_progress(payload)
                elif kind == "queue_progress":
                    idx, total, _label = payload
                    self._queue_index = idx
                    self._queue_total = total if total > 1 else 0
                    if total > 1:
                        # Update bar between scripts even before any log lines arrive
                        frac = idx / total if total else 0
                        self._set_progress(frac)
                elif kind == "thumb":
                    name, thumb_pil, gen = payload
                    self._apply_thumb(name, thumb_pil, gen)
                elif kind == "update_available":
                    self._show_update_dialog(payload)
                elif kind == "nas_unreachable":
                    self._show_nas_unreachable_toast()
                elif kind == "update_progress":
                    frac, pct_var, bar = payload
                    try:
                        pct_var.set(f"{int(frac * 100)}%")
                        bar.set(frac)
                    except Exception:
                        pass
                elif kind == "update_ready":
                    self._apply_update_now(payload)
                elif kind == "update_error":
                    self._dismiss_update_dialog()
                    messagebox.showerror(
                        "Update failed",
                        f"Could not download the update:\n\n{payload}",
                    )
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
            self._set_status("Done", C("ok"))
            self._set_buttons_enabled(True)
            return

        if not result.get("ok"):
            self._append(f"\nFailed: {result.get('error', 'unknown error')}")
            self._set_status("Failed")
            self._set_state("error")
            self._set_buttons_enabled(True)
            return

        # Script Runner result: has processed/failed/errors but no recipeSummary or nested result
        if "processed" in result and "recipeSummary" not in result:
            is_queue  = bool(result.get("queue"))
            processed = int(result.get("processed", 0))
            failed    = int(result.get("failed", 0))
            errors    = result.get("errors", []) or []
            out_dir   = result.get("outputFolder")
            per_script = result.get("scripts", []) or []

            if is_queue:
                self._append(
                    f"\nQueue done · {len(per_script)} scripts · "
                    f"{processed} ok, {failed} failed total"
                )
                for entry in per_script:
                    if "error" in entry:
                        self._append(f"  ✗ {entry['label']}: {entry['error']}")
                    else:
                        self._append(
                            f"  · {entry['label']}: "
                            f"{entry.get('processed', 0)} ok, {entry.get('failed', 0)} failed"
                        )
            else:
                total_n = int(result.get("total", 0))
                self._append(
                    f"\nScript run · {processed} ok, {failed} failed (of {total_n})"
                )
            if out_dir:
                self._append(f"  Output: {out_dir}")
            if errors:
                self._append("\nErrors:")
                for e in errors[:20]:  # cap to keep the panel readable
                    tag = f"[{e.get('script')}] " if e.get('script') else ""
                    self._append(f"  {tag}{e.get('file')}: {e.get('message')}")
                if len(errors) > 20:
                    self._append(f"  … and {len(errors) - 20} more (see log)")

            self._set_progress(1.0)
            self._set_state("error" if failed > 0 else "ok")
            label = "Queue done" if is_queue else "Script done"
            self._set_status(f"{label} · {processed} ok, {failed} failed")
            self.last_output_folder = out_dir
            if self.last_output_folder:
                self.btn_reveal.configure(state="normal")
            self._queue_total = 0  # reset so next single-script run isn't compositied
            self._queue_index = 0
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
            ok_n = r.get("ok", 0)
            fail_n = r.get("fail", 0)
            total_n = r.get("total", ok_n + fail_n)
            cancelled = bool(r.get("cancelled"))
            skipped = max(0, total_n - ok_n - fail_n)

            if cancelled:
                self._append(
                    f"\nBatch cancelled · {ok_n} ok, {fail_n} failed, "
                    f"{skipped} skipped in {r.get('elapsed', 0):.1f}s"
                )
            else:
                self._append(
                    f"\nBatch finished · {ok_n} ok, "
                    f"{fail_n} failed in {r.get('elapsed', 0):.1f}s"
                )
            self._append(f"  Output: {r.get('outFolder')}")
            self._append(f"  Log:    {r.get('logFile')}")

            if cancelled:
                self._set_status(
                    f"Cancelled · {ok_n}/{total_n} processed · {r.get('elapsed', 0):.1f}s"
                )
                self._set_state("error")  # use red dot for cancelled — distinct from ok
                # Show partial progress instead of jumping to 100%
                self._set_progress((ok_n + fail_n) / total_n if total_n else 0)
            else:
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


# ============================================================================
# REGION 14: AppMutex + main entry
# ----------------------------------------------------------------------------
# Module-scope. The named-mutex acquisition lets Inno Setup's
# CloseApplications detect the running launcher during update install;
# `main()` is the PyInstaller / `python launcher.py` entrypoint.
# ============================================================================


def _acquire_app_mutex():
    """Create the named Windows mutex Inno Setup's AppMutex looks for.

    Inno's update flow (``CloseApplications=yes``) checks this mutex to
    decide whether the running instance needs to be closed before replacing
    the .exe. The name MUST match ``MutexName`` in installer.iss exactly —
    see :data:`APP_MUTEX_NAME` for the source of truth.

    Returns the handle (caller must keep a reference for the whole app
    lifetime; the OS releases it on process exit) or ``None`` when pywin32
    isn't available (dev mode on Mac/Linux). Returning None is fine for
    dev — the updater flow only matters on Windows installs.

    Note: ``CreateMutex`` on an already-existing name returns a handle to
    the existing object. We deliberately do not check ``ERROR_ALREADY_EXISTS``
    and exit — a stale mutex left over from a crashed instance should not
    lock the user out of starting the app.
    """
    try:
        import win32event  # type: ignore
        import win32api    # type: ignore  # noqa: F401 (kept for explicit dep)
        return win32event.CreateMutex(None, False, APP_MUTEX_NAME)
    except ImportError:
        return None  # dev mode without pywin32; updater flow still works


def main():
    # Wire logging FIRST so every subsequent import/init goes to app.log.
    setup_logging()
    log.info("launcher.main() · APP_VERSION=%s", APP_VERSION)
    # Keep mutex handle alive for the entire app lifetime.
    _mutex_handle = _acquire_app_mutex()  # noqa: F841 — held by reference
    try:
        root = DnDCTk()
        App(root)
        root.mainloop()
    except Exception:
        log.exception("launcher crashed in mainloop")
        raise
    finally:
        log.info("launcher.main() exiting")


if __name__ == "__main__":
    main()
