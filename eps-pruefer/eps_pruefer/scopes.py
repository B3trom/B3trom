"""Prüfbereiche: welche Unterordner eines Projekts geprüft werden."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Scope:
    key: str
    title: str
    description: str
    include: tuple[str, ...] = ()  # leer = alle Ordner
    exclude: tuple[str, ...] = ()


SCOPES: dict[str, Scope] = {
    s.key: s
    for s in (
        Scope("intern", "Intern", "Anzeigensatz ohne Rollups",
              include=("anzeigensatz",), exclude=("rollups", "rollup", "roll ups", "roll up")),
        Scope("extern", "Extern", "Arbeitsdaten + Freie Anzeigen",
              include=("arbeitsdaten", "freie anzeigen")),
        Scope("produktion", "Produktion", "Produktionsvorbereitung",
              include=("produktionsvorbereitung",)),
        Scope("komplett", "Komplett", "ganzer Ordner + Unterordner"),
    )
}
DEFAULT_SCOPE = "komplett"


def _norm(name: str) -> str:
    """Ordnernamen vergleichbar machen: Groß/klein, _ und - wie Leerzeichen."""
    return re.sub(r"[\s_\-]+", " ", name).strip().lower()


def _contains(folder: str, keyword: str) -> bool:
    """Kommt der Begriff als ganzes Wort im (normalisierten) Ordnernamen vor?

    So passen auch "01_Anzeigensatz", "Anzeigensatz KW42" oder "02 - Arbeitsdaten".
    """
    return re.search(rf"(?<![a-z0-9äöüß]){re.escape(keyword)}(?![a-z0-9äöüß])", folder) is not None


def in_scope(path: Path, root: Path, scope: Scope | str) -> bool:
    """Liegt `path` (Datei im Projekt `root`) im Prüfbereich?

    Verglichen werden alle Ordnernamen im Pfad – auch die oberhalb des gewählten
    Ordners. Wer also direkt „…\\Anzeigensatz\\Anzeigen“ wählt, bekommt bei „Intern“
    dessen Inhalt (ohne Rollups).
    """
    scope = SCOPES[scope] if isinstance(scope, str) else scope
    try:
        rel_dirs = path.relative_to(root).parent.parts
    except ValueError:
        rel_dirs = path.parent.parts
    above = [p for p in root.parts if p != root.anchor]  # gewählter Ordner + übergeordnete
    folders = [_norm(p) for p in (*above, *rel_dirs)]
    if any(_contains(f, kw) for f in folders for kw in scope.exclude):
        return False
    return not scope.include or any(_contains(f, kw) for f in folders for kw in scope.include)


def filter_scope(files: list[Path], root: Path, scope: Scope | str) -> list[Path]:
    return [f for f in files if in_scope(f, root, scope)]


def empty_scope_hint(files: list[Path], root: Path, scope: Scope | str) -> str:
    """Erklärt, warum ein Bereich keine Dateien enthält (für die Statusmeldung)."""
    scope = SCOPES[scope] if isinstance(scope, str) else scope
    if not files:
        return "keine EPS-Dateien im Ordner"
    wanted = " oder ".join(f"„{kw.title()}“" for kw in scope.include) or "–"
    folders = sorted({f.relative_to(root).parts[0] for f in files if len(f.relative_to(root).parts) > 1})
    found = ", ".join(folders[:6]) + (" …" if len(folders) > 6 else "") if folders else "keine Unterordner"
    return (f"0 von {len(files)} EPS im Bereich {scope.title} – gesucht wird ein Ordner {wanted} "
            f"(gefunden: {found})")


def best_scope(files: list[Path], root: Path, current: str) -> tuple[str, int]:
    """Bereich (außer dem aktuellen), in dem die meisten Dateien liegen; sonst „Komplett“."""
    counts = {key: len(filter_scope(files, root, key))
              for key in SCOPES if key not in (current, DEFAULT_SCOPE)}
    key = max(counts, key=counts.get) if counts else DEFAULT_SCOPE
    if not counts or counts[key] == 0:
        return DEFAULT_SCOPE, len(files)
    return key, counts[key]
