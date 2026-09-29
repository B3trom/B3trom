"""Auffinden der Ghostscript-Kommandozeilenversion."""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys

_WINDOWS_NAMES = ("gswin64c.exe", "gswin32c.exe")


def _version_key(path: str) -> tuple:
    m = re.search(r"gs(\d+)\.(\d+)(?:\.(\d+))?", path.replace("\\", "/"))
    return tuple(int(x or 0) for x in m.groups()) if m else (0,)


def find_ghostscript(preferred: str | None = None) -> str | None:
    """Sucht gswin64c/gswin32c bzw. gs. Liefert den Pfad oder None."""
    if preferred and os.path.isfile(preferred):
        return preferred

    names = _WINDOWS_NAMES + ("gs",) if sys.platform == "win32" else ("gs",)
    for name in names:
        found = shutil.which(name)
        if found:
            return found

    if sys.platform == "win32":
        candidates: list[str] = []
        roots = {
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("ProgramW6432", r"C:\Program Files"),
        }
        for root in roots:
            for exe in _WINDOWS_NAMES:
                candidates += glob.glob(os.path.join(root, "gs", "gs*", "bin", exe))
        # Portable Ablage direkt neben dem Programm (z. B. .\ghostscript\bin)
        base = os.path.dirname(os.path.abspath(sys.argv[0]))
        for exe in _WINDOWS_NAMES:
            candidates += glob.glob(os.path.join(base, "ghostscript", "**", exe), recursive=True)
        if candidates:
            return sorted(candidates, key=_version_key)[-1]
    return None


def ghostscript_version(executable: str) -> str:
    try:
        out = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=_no_window_flag(),
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _no_window_flag() -> int:
    """Unter Windows kein Konsolenfenster für Ghostscript aufpoppen lassen."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)
