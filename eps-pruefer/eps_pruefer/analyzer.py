"""Führt eine EPS-Datei mit dem Prüf-Prolog in Ghostscript aus und wertet das Protokoll aus."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from . import probe
from .epsfile import BBox, EPSInfo
from .ghostscript import _no_window_flag


class AnalysisError(Exception):
    pass


@dataclass
class PaintEvent:
    kind: str  # "PAINT" oder "IMAGE"
    op: str
    nested: bool  # innerhalb eines Musters / Type3-Zeichens
    first: bool  # erstes (unterstes) gemaltes Objekt
    cs_family: str
    cs_detail: str
    color: list[float]
    overprint: bool
    alpha: float
    box: BBox | None
    clip: BBox | None
    # nur bei Bildern
    width: int = 0
    height: int = 0
    dpi_x: float = 0.0
    dpi_y: float = 0.0

    @property
    def visible_box(self) -> BBox | None:
        """Tatsächlich bemalte Fläche = Pfad geschnitten mit Beschneidungspfad."""
        if self.box is None:
            return None
        if self.clip is None:
            return self.box
        return BBox(
            max(self.box.llx, self.clip.llx),
            max(self.box.lly, self.clip.lly),
            min(self.box.urx, self.clip.urx),
            min(self.box.ury, self.clip.ury),
        )

    @property
    def dpi(self) -> float:
        return max(self.dpi_x, self.dpi_y)


@dataclass
class TransparencyEvent:
    before_first_paint: bool
    args: str


@dataclass
class Analysis:
    gs_revision: str = ""
    events: list[PaintEvent] = field(default_factory=list)
    transparency: list[TransparencyEvent] = field(default_factory=list)
    ps_error: str = ""
    completed: bool = False
    paint_count: int = 0
    image_count: int = 0
    stderr: str = ""
    missing_fonts: list[str] = field(default_factory=list)

    @property
    def images(self) -> list[PaintEvent]:
        return [e for e in self.events if e.kind == "IMAGE"]

    @property
    def first_paint(self) -> PaintEvent | None:
        return next((e for e in self.events if e.first), None)


def _parse_bbox(text: str) -> BBox | None:
    parts = text.split()
    if len(parts) != 4:
        return None
    try:
        return BBox(*(float(p) for p in parts))
    except ValueError:
        return None


def _parse_color(text: str) -> list[float]:
    text = text.strip().strip("[]")
    values = []
    for part in text.split():
        try:
            values.append(float(part))
        except ValueError:
            pass
    return values


def _to_float(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        return 0.0


def parse_output(stdout: str) -> Analysis:
    result = Analysis()
    for line in stdout.splitlines():
        if not line.startswith("@@EPS|"):
            continue
        parts = line.split("|")
        tag = parts[1] if len(parts) > 1 else ""
        if tag == "START":
            result.gs_revision = parts[2] if len(parts) > 2 else ""
        elif tag in ("PAINT", "IMAGE") and len(parts) >= 12:
            ev = PaintEvent(
                kind=tag,
                op=parts[2],
                nested=parts[3] == "1",
                first=parts[4] == "1",
                cs_family=parts[5],
                cs_detail=parts[6],
                color=_parse_color(parts[7]),
                overprint=parts[8] == "true",
                alpha=_to_float(parts[9]) if parts[9] else 1.0,
                box=_parse_bbox(parts[10]),
                clip=_parse_bbox(parts[11]),
            )
            if tag == "IMAGE" and len(parts) >= 16:
                ev.width = int(_to_float(parts[12]))
                ev.height = int(_to_float(parts[13]))
                ev.dpi_x = _to_float(parts[14])
                ev.dpi_y = _to_float(parts[15])
            result.events.append(ev)
        elif tag == "FONT" and len(parts) >= 3:
            result.missing_fonts.append(parts[2].strip())
        elif tag == "TRANSP" and len(parts) >= 4:
            result.transparency.append(TransparencyEvent(parts[2] == "1", parts[3].strip()))
        elif tag == "ERROR":
            result.ps_error = " ".join(p for p in parts[2:] if p).strip() or "unbekannter Fehler"
        elif tag == "END":
            result.completed = True
            if len(parts) >= 4:
                result.paint_count = int(_to_float(parts[2]))
                result.image_count = int(_to_float(parts[3]))
    return result


def analyze(info: EPSInfo, gs_executable: str, timeout: int = 180) -> Analysis:
    """Startet Ghostscript mit dem Prüf-Prolog und liefert das ausgewertete Protokoll."""
    job = probe.build_job(info.ps_data)
    cmd = [
        gs_executable,
        "-q",
        "-dNOPAUSE",
        "-dBATCH",
        "-dSAFER",
        "-sDEVICE=bbox",
        "-r72",
        f"-dDEVICEWIDTHPOINTS={probe.PAGE_POINTS}",
        f"-dDEVICEHEIGHTPOINTS={probe.PAGE_POINTS}",
        "-dFIXEDMEDIA",
        "-",
    ]
    try:
        proc = subprocess.run(
            cmd,
            input=job,
            capture_output=True,
            timeout=timeout,
            creationflags=_no_window_flag(),
        )
    except subprocess.TimeoutExpired as exc:
        raise AnalysisError(f"Ghostscript hat nach {timeout} s nicht geantwortet") from exc
    except OSError as exc:
        raise AnalysisError(f"Ghostscript konnte nicht gestartet werden: {exc}") from exc

    stdout = proc.stdout.decode("latin-1", "replace")
    result = parse_output(stdout)
    result.stderr = proc.stderr.decode("latin-1", "replace").strip()
    if not result.gs_revision:
        raise AnalysisError(
            "Ghostscript lieferte kein Prüfprotokoll.\n" + (result.stderr or stdout)[-2000:]
        )
    return result
