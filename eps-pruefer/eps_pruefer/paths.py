"""Pfad-Hilfen für Windows (lange Pfade auf Netzlaufwerken)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def long_path(path: Path | str) -> str:
    """Unter Windows Pfade über 260 Zeichen erlauben (\\\\?\\-Präfix)."""
    p = os.path.abspath(str(path))
    if sys.platform != "win32" or p.startswith("\\\\?\\"):
        return p
    return "\\\\?\\UNC\\" + p[2:] if p.startswith("\\\\") else "\\\\?\\" + p


def short_path(path: str) -> str:
    """Präfix aus long_path() für die Anzeige wieder entfernen."""
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    return path[4:] if path.startswith("\\\\?\\") else path
