"""Kommandozeilen-Aufruf: python -m eps_pruefer --cli DATEI|ORDNER ..."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .checks import OPTIONAL_CHECKS, Settings, Status, check_file
from .ghostscript import find_ghostscript
from .report import text_report, write_csv, write_html


EPS_SUFFIXES = (".eps", ".epsf", ".ai")


def folder_files(folder: Path, recursive: bool = True) -> list[Path]:
    """EPS-Dateien eines Ordners, sortiert nach Unterordner und Name."""
    pattern = folder.rglob("*") if recursive else folder.glob("*")
    files = [f for f in pattern if f.is_file() and f.suffix.lower() in EPS_SUFFIXES]
    return sorted(files, key=lambda f: [part.lower() for part in f.relative_to(folder).parts])


def collect_files(paths: list[str], recursive: bool = True) -> list[Path]:
    files: list[Path] = []
    for p in map(Path, paths):
        files += folder_files(p, recursive) if p.is_dir() else [p]
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

    results = [check_file(f, settings) for f in collect_files(args.pfade, not args.ohne_unterordner)]
    print(text_report(results))
    if args.csv:
        write_csv(results, args.csv)
    if args.html:
        write_html(results, args.html, settings)
    return 1 if any(r.status == Status.FAIL for r in results) else 0
