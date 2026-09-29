"""Berichte als Text, CSV und HTML."""

from __future__ import annotations

import csv
import html
import os
from datetime import datetime
from pathlib import Path

from .checks import CHECK_TITLES, FileResult, Settings, Status

CHECK_ORDER = list(CHECK_TITLES)


def display_names(results: list[FileResult]) -> dict:
    """Pfad relativ zum gemeinsamen Ordner (bei Projekten inkl. Unterordner)."""
    if not results:
        return {}
    try:
        base = os.path.commonpath([str(r.path.parent) for r in results])
    except ValueError:  # verschiedene Laufwerke
        return {r.path: r.path.name for r in results}
    return {r.path: os.path.relpath(r.path, base) for r in results}


def text_report(results: list[FileResult]) -> str:
    out = []
    for r in results:
        out.append(f"{r.status.symbol} {r.status.label.upper():8} {r.path}")
        for c in r.checks:
            out.append(f"    {c.status.symbol} {c.title}: {c.message}")
            for d in c.details:
                out.append(f"          · {d}")
        out.append("")
    ok = sum(1 for r in results if r.status <= Status.INFO)
    warn = sum(1 for r in results if r.status == Status.WARN)
    fail = sum(1 for r in results if r.status == Status.FAIL)
    out.append(f"{len(results)} Datei(en): {ok} OK, {warn} mit Warnung, {fail} fehlerhaft")
    return "\n".join(out)


def write_csv(results: list[FileResult], path: str | Path) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["Datei", "Gesamt"] + [CHECK_TITLES[k] for k in CHECK_ORDER]
                   + [CHECK_TITLES[k] + " – Meldung" for k in CHECK_ORDER])
        for r in results:
            checks = [r.check(k) for k in CHECK_ORDER]
            w.writerow(
                [str(r.path), r.status.label]
                + [c.status.label if c else "" for c in checks]
                + [c.message if c else "" for c in checks]
            )


_CSS = """
body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#222;background:#fff}
h1{font-size:20px;margin:0 0 4px} .meta{color:#666;font-size:13px;margin-bottom:16px}
table{border-collapse:collapse;width:100%;font-size:13px;margin-bottom:24px}
th,td{border:1px solid #ddd;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#f3f3f3} .s0{color:#1a7f37} .s1{color:#888} .s2{color:#9a6700} .s3{color:#cf222e}
td.st{text-align:center;font-weight:bold;white-space:nowrap}
h2{font-size:16px;margin:24px 0 6px;border-bottom:1px solid #ddd;padding-bottom:4px}
ul{margin:4px 0 0 18px;padding:0;color:#555} li{margin:1px 0}
.file{word-break:break-all}
"""


def write_html(results: list[FileResult], path: str | Path, settings: Settings) -> None:
    e = html.escape
    names = display_names(results)
    rows = []
    for r in results:
        cells = "".join(
            f'<td class="st s{int(c.status)}" title="{e(c.message)}">{c.status.symbol}</td>'
            if (c := r.check(k)) else "<td></td>"
            for k in CHECK_ORDER
        )
        rows.append(
            f'<tr><td class="file">{e(names[r.path])}</td>'
            f'<td class="st s{int(r.status)}">{r.status.symbol} {e(r.status.label)}</td>{cells}</tr>'
        )
    head = "".join(f"<th>{e(CHECK_TITLES[k])}</th>" for k in CHECK_ORDER)

    sections = []
    for r in results:
        items = []
        for c in r.checks:
            det = "".join(f"<li>{e(d)}</li>" for d in c.details)
            items.append(
                f'<tr><td class="st s{int(c.status)}">{c.status.symbol}</td>'
                f"<td>{e(c.title)}</td><td>{e(c.message)}{f'<ul>{det}</ul>' if det else ''}</td></tr>"
            )
        sections.append(
            f'<h2 class="s{int(r.status)}">{r.status.symbol} {e(names[r.path])}</h2>'
            f'<div class="meta file">{e(str(r.path))}</div>'
            f"<table>{''.join(items)}</table>"
        )

    doc = f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><title>EPS-Prüfbericht</title>
<style>{_CSS}</style></head><body>
<h1>EPS-Prüfbericht</h1>
<div class="meta">Erstellt {datetime.now():%d.%m.%Y %H:%M} · max. Auflösung {settings.max_dpi:g} dpi ·
{len(results)} Datei(en)</div>
<table><tr><th>Datei</th><th>Gesamt</th>{head}</tr>{''.join(rows)}</table>
{''.join(sections)}
</body></html>"""
    Path(path).write_text(doc, encoding="utf-8")
