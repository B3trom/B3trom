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
              include=("anzeigensatz",), exclude=("rollups", "rollup")),
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


def in_scope(path: Path, root: Path, scope: Scope | str) -> bool:
    """Liegt `path` (Datei im Projekt `root`) im Prüfbereich?

    Verglichen werden die Ordnernamen zwischen Projekt und Datei. Der Projektordner
    selbst zählt mit – wer direkt den Ordner „Anzeigensatz“ wählt, bekommt bei
    „Intern“ also dessen Inhalt (ohne Rollups).
    """
    scope = SCOPES[scope] if isinstance(scope, str) else scope
    try:
        rel_dirs = path.relative_to(root).parent.parts
    except ValueError:
        rel_dirs = path.parent.parts
    folders = {_norm(p) for p in (root.name, *rel_dirs)}
    if folders & set(scope.exclude):
        return False
    return not scope.include or bool(folders & set(scope.include))


def filter_scope(files: list[Path], root: Path, scope: Scope | str) -> list[Path]:
    return [f for f in files if in_scope(f, root, scope)]
