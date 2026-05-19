"""pytest config: add the app/ folder to sys.path so tests can import directly.

This lets `pytest` run from the project root *or* from app/ without an
editable install. We do NOT use a top-level package layout because PyInstaller
treats launcher.py as a script entrypoint, not a package member.
"""
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
