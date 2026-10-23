"""Kommandozeilen-Aufruf: python -m eps_pruefer --cli DATEI|ORDNER ..."""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .checks import OPTIONAL_CHECKS, Settings, Status, check_file
from .ghostscript import find_ghostscript
from .report import text_report, write_csv, write_html
from .paths import long_path, short_path
from .scopes import DEFAULT_SCOPE, SCOPES, filter_scope


EPS_SUFFIXES = (".eps", ".epsf", ".ai")


DOS_EPS_MAGIC = b"\xc5\xd0\xd3\xc6"


@dataclass
class FolderScan:
    """Ergebnis einer Ordnersuche inkl. Diagnose, falls nichts gefunden wird."""
    files: list[Path] = field(default_factory=list)
    folders: int = 0
    other_types: Counter = field(default_factory=Counter)  # Endung -> Anzahl
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.errors and not self.folders:
            return f"Ordner nicht lesbar: {self.errors[0]}"
        parts = [f"{len(self.files)} EPS", f"{self.folders} Ordner durchsucht"]
        if self.other_types:
            top = ", ".join(f"{n}× {ext}" for ext, n in self.other_types.most_common(6))
            parts.append(f"andere Dateien: {top}")
        if self.errors:
            parts.append(f"{len(self.errors)} Ordner nicht lesbar")
        return " · ".join(parts)


def _looks_like_eps(path: str) -> bool:
    """Datei ohne Endung (z. B. vom Mac): am Dateianfang erkennen."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(4)
    except OSError:
        return False
    return head.startswith(b"%!PS") or head == DOS_EPS_MAGIC


def scan_folder(folder: Path, recursive: bool = True) -> FolderScan:
    """Sucht EPS-Dateien (auch ohne Endung) und merkt sich, was sonst gefunden wurde.

    Unlesbare Unterordner werden übersprungen statt die Suche abzubrechen, und
    Mac-Begleitdateien ("._name.eps" auf Netzlaufwerken) werden ignoriert.
    """
    scan = FolderScan()

    def walk(start: str) -> None:
        for dirpath, dirnames, filenames in os.walk(start, onerror=lambda e: scan.errors.append(str(e))):
            scan.folders += 1
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            base = Path(short_path(dirpath))
            for name in filenames:
                if name.startswith("._") or name.startswith("."):
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext in EPS_SUFFIXES or (not ext and _looks_like_eps(os.path.join(dirpath, name))):
                    scan.files.append(base / name)
                else:
                    scan.other_types[ext or "(ohne Endung)"] += 1
            if not recursive:
                break

    start = long_path(folder)
    walk(start)
    if not scan.folders and start != str(folder):  # Langpfad-Präfix gescheitert: normal versuchen
        scan.errors.clear()
        walk(os.path.abspath(str(folder)))
    scan.files.sort(key=lambda f: [part.lower() for part in f.relative_to(folder).parts])
    return scan


def folder_files(folder: Path, recursive: bool = True) -> list[Path]:
    """EPS-Dateien eines Ordners, sortiert nach Unterordner und Name."""
    return scan_folder(folder, recursive).files


def collect_files(paths: list[str], recursive: bool = True, scope: str = DEFAULT_SCOPE) -> list[Path]:
    """Dateien bleiben, wie angegeben; Ordner werden nach dem Prüfbereich gefiltert."""
    files: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            files += filter_scope(folder_files(p, recursive or scope != DEFAULT_SCOPE), p, scope)
        else:
            files.append(p)
    return files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="eps_pruefer", description="Prüft EPS-Dateien für Druck und Anzeigensatz.")
    ap.add_argument("--cli", action="store_true", help="ohne Oberfläche prüfen")
    ap.add_argument("pfade", nargs="+", help="EPS-Dateien oder Ordner")
    ap.add_argument("--min-dpi", type=float, default=80.0)
    ap.add_argument("--max-dpi", type=float, default=150.0)
    ap.add_argument("--rgb-fehler", action="store_true", help="alle RGB-Farben als Fehler werten")
    ap.add_argument("--grau-fehler", action="store_true", help="Graustufen-Schwarz als Fehler werten")
    ap.add_argument("--ohne-unterordner", action="store_true", help="bei Ordnern keine Unterordner durchsuchen")
    ap.add_argument("--bereich", choices=list(SCOPES), default=DEFAULT_SCOPE,
                    help="Prüfbereich bei Ordnern: " + "; ".join(f"{k} = {v.description}" for k, v in SCOPES.items()))
    kriterien = ", ".join(OPTIONAL_CHECKS)
    ap.add_argument("--nur", help=f"nur diese Kriterien prüfen, kommagetrennt ({kriterien})")
    ap.add_argument("--ohne", help=f"diese Kriterien nicht prüfen, kommagetrennt ({kriterien})")
    ap.add_argument("--gs", help="Pfad zu gswin64c.exe / gs")
    ap.add_argument("--csv", help="CSV-Bericht schreiben")
    ap.add_argument("--html", help="HTML-Bericht schreiben")
    args = ap.parse_args(argv)

    def keys(text):
        chosen = {k.strip().lower() for k in text.split(",") if k.strip()}
        unknown = chosen - set(OPTIONAL_CHECKS)
        if unknown:
            ap.error(f"unbekannte Kriterien: {', '.join(sorted(unknown))} (möglich: {kriterien})")
        return chosen

    enabled = keys(args.nur) if args.nur else set(OPTIONAL_CHECKS)
    if args.ohne:
        enabled -= keys(args.ohne)

    gs = find_ghostscript(args.gs)
    if not gs:
        print("WARNUNG: Ghostscript nicht gefunden – es werden nur Verknüpfungen geprüft.", file=sys.stderr)
    settings = Settings(min_dpi=args.min_dpi, max_dpi=args.max_dpi, rgb_is_error=args.rgb_fehler,
                        gray_black_is_error=args.grau_fehler, gs_executable=gs or "",
                        enabled=frozenset(enabled))

    files = collect_files(args.pfade, not args.ohne_unterordner, args.bereich)
    if not files:
        for p in map(Path, args.pfade):
            if p.is_dir():
                print(f"Keine Dateien im Bereich „{SCOPES[args.bereich].title}“ in {p}: "
                      f"{scan_folder(p).summary()}", file=sys.stderr)
            elif not p.exists():
                print(f"Nicht gefunden: {p}", file=sys.stderr)
    results = [check_file(f, settings) for f in files]
    print(text_report(results))
    if args.csv:
        write_csv(results, args.csv)
    if args.html:
        write_html(results, args.html, settings)
    return 1 if any(r.status == Status.FAIL for r in results) else 0
