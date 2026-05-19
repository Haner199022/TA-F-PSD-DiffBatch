"""Unified user-facing error entry point.

Every place in the launcher that used to call ``messagebox.showerror`` should
go through :func:`show_error` instead. Three benefits:

    1. The full traceback lands in ``app.log`` automatically — no more lost
       stack traces when a colleague closes the dialog.
    2. Users see a short message plus the log file path, so they know where
       to look (or what to copy via Help → Copy diagnostic info).
    3. Optional retry callback wraps the standard "Retry / Cancel" dialog so
       transient failures (NAS hiccup, locked PSD) are one click away.

Microcopy follows §4.1 of the optimization plan: what happened + where + what
to do next.
"""
from __future__ import annotations

import logging
import traceback
from tkinter import messagebox
from typing import Callable, Optional

import logging_setup

log = logging.getLogger(__name__)


def show_error(parent,
               title: str,
               exc: BaseException,
               *,
               retry: Optional[Callable[[], None]] = None,
               hint: Optional[str] = None) -> None:
    """Display ``exc`` to the user and write a full traceback to app.log.

    Args:
        parent: Tk widget to anchor the dialog to (or None).
        title: dialog title; short, e.g. "Update failed".
        exc: the caught exception.
        retry: if provided, dialog becomes "Retry / Cancel"; clicking Retry
            invokes this callable.
        hint: optional extra line shown to the user (Chinese OK), e.g.
            "请手动关闭 Photoshop 后重试。"
    """
    # Format the stack trace from the exception object so callers don't have
    # to be inside an `except` block. format_exception is safe even when no
    # exception is currently propagating.
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    log.error("%s: %s\n%s", title, exc, tb)

    # Read LOG_FILE dynamically so the user always sees the path that
    # setup_logging actually settled on (may be %TEMP% if fallback fired).
    log_file = logging_setup.LOG_FILE

    short = str(exc) if str(exc) else exc.__class__.__name__
    body_lines = [short]
    if hint:
        body_lines.append("")
        body_lines.append(hint)
    body_lines.append("")
    body_lines.append(f"详细日志：{log_file}")
    body_lines.append("可点击 Help → Copy diagnostic info 一键拷贝诊断信息。")
    body = "\n".join(body_lines)

    if retry is not None:
        if messagebox.askretrycancel(title, body, parent=parent):
            try:
                retry()
            except Exception as retry_exc:
                # Don't recurse forever — log and surface as a fresh error.
                log.error("retry handler raised: %s", retry_exc, exc_info=True)
                messagebox.showerror(
                    title,
                    f"重试也失败了：{retry_exc}\n\n详细日志：{log_file}",
                    parent=parent,
                )
    else:
        messagebox.showerror(title, body, parent=parent)


def show_warning(parent, title: str, message: str) -> None:
    """Logged warning dialog. Use when the user did something we can't honor
    but the app state is fine (e.g. "Pick the batch folder")."""
    log.warning("%s: %s", title, message)
    messagebox.showwarning(title, message, parent=parent)
