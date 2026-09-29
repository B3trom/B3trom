"""Prüfregeln für Druck-/Anzeigen-EPS."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

from .analyzer import Analysis, AnalysisError, PaintEvent, analyze
from .epsfile import EPSInfo, EPSReadError, read_eps

# Farbwerte (0..1), bis zu denen ein RGB- bzw. Graustufen-Wert als "Schwarz" gilt
BLACK_THRESHOLD = 0.2
# Rundungstoleranz für die Auflösung
DPI_TOLERANCE = 0.5
MAX_DETAILS = 25


class Status(IntEnum):
    OK = 0
    INFO = 1  # nicht anwendbar / nur Hinweis
    WARN = 2
    FAIL = 3

    @property
    def label(self) -> str:
        return {0: "OK", 1: "–", 2: "Warnung", 3: "Fehler"}[self.value]

    @property
    def symbol(self) -> str:
        return {0: "✔", 1: "–", 2: "⚠", 3: "✖"}[self.value]


@dataclass
class CheckResult:
    key: str
    title: str
    status: Status
    message: str
    details: list[str] = field(default_factory=list)


@dataclass
class Settings:
    min_dpi: float = 80.0
    max_dpi: float = 150.0
    rgb_is_error: bool = False  # auch nicht-schwarze RGB-Farben/-Bilder als Fehler werten
    gray_black_is_error: bool = False  # Schwarz als Graustufe (statt CMYK) als Fehler werten
    gs_executable: str = ""
    timeout: int = 180


@dataclass
class FileResult:
    path: Path
    checks: list[CheckResult] = field(default_factory=list)
    info: EPSInfo | None = None
    analysis: Analysis | None = None

    @property
    def status(self) -> Status:
        return max((c.status for c in self.checks), default=Status.FAIL)

    def check(self, key: str) -> CheckResult | None:
        return next((c for c in self.checks if c.key == key), None)


CHECK_TITLES = {
    "datei": "Datei / PostScript",
    "schwarz": "Schwarz in CMYK",
    "eingebettet": "Pixeldaten eingebettet",
    "aufloesung": "Auflösung",
    "ueberdrucken": "Kein Überdrucken",
    "hintergrund": "Hintergrundfläche",
}


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _fmt_color(ev: PaintEvent) -> str:
    model = _color_model(ev.cs_family, ev.cs_detail)
    c = ev.color
    if model == "cmyk" and len(c) == 4:
        return "CMYK " + " ".join(f"{n}{round(v * 100)}" for n, v in zip("CMYK", c))
    if model == "rgb" and len(c) == 3 and ev.cs_family != "Lab":
        return "RGB " + " ".join(f"{n}{round(v * 255)}" for n, v in zip("RGB", c))
    if model == "gray" and len(c) == 1:
        return f"Graustufe {round((1 - c[0]) * 100)} % Schwarz"
    fam = ev.cs_family + (f" {ev.cs_detail}" if ev.cs_detail else "")
    if ev.cs_family == "Separation" and len(c) == 1:
        return f"Sonderfarbe {ev.cs_detail} {round(c[0] * 100)} %"
    if not c:
        return {"cmyk": "CMYK", "rgb": "RGB", "gray": "Graustufe"}.get(model, fam)
    return f"{fam} " + " ".join(f"{v:g}" for v in c)


def _fmt_box(ev: PaintEvent) -> str:
    if ev.nested:
        return " (innerhalb eines Musters bzw. einer Schrift)"
    box = ev.visible_box
    if box is None or box.width > 10000 or box.height > 10000:
        return ""
    return f" bei x={box.llx:.1f} y={box.lly:.1f} ({box.width:.1f} × {box.height:.1f} pt)"


def _color_model(family: str, detail: str) -> str:
    """Ordnet einen PostScript-Farbraum 'cmyk', 'rgb', 'gray', 'spot' oder 'other' zu."""
    if family == "Indexed":
        base, _, n = detail.partition("/")
        return _color_model(base, n)
    if family in ("DeviceCMYK", "CIEBasedDEFG"):
        return "cmyk"
    if family in ("DeviceRGB", "CIEBasedABC", "CalRGB", "Lab", "CIEBasedDEF"):
        return "rgb"
    if family in ("DeviceGray", "CIEBasedA", "CalGray"):
        return "gray"
    if family == "ICCBased":
        return {"1": "gray", "3": "rgb", "4": "cmyk"}.get(detail, "other")
    if family in ("Separation", "DeviceN"):
        return "spot"
    return "other"


def _is_black(model: str, color: list[float]) -> bool:
    if model == "rgb" and len(color) == 3:
        return max(color) <= BLACK_THRESHOLD
    if model == "gray" and len(color) == 1:
        return color[0] <= BLACK_THRESHOLD
    return False


# ---------------------------------------------------------------------------
# Einzelprüfungen
# ---------------------------------------------------------------------------

def check_black(an: Analysis, s: Settings) -> CheckResult:
    rgb_black, gray_black, rgb_other, rgb_images = [], [], [], []
    for ev in an.events:
        model = _color_model(ev.cs_family, ev.cs_detail)
        if ev.kind == "IMAGE" and ev.op != "imagemask":
            if model == "rgb":
                rgb_images.append(f"RGB-Bild {ev.width}×{ev.height} px{_fmt_box(ev)}")
            continue
        where = f"{ev.op}: {_fmt_color(ev)}{_fmt_box(ev)}"
        if _is_black(model, ev.color):
            (rgb_black if model == "rgb" else gray_black).append(where)
        elif model == "rgb":
            rgb_other.append(where)

    details: list[str] = []
    status = Status.OK
    parts = []
    if rgb_black:
        status = Status.FAIL
        parts.append(f"{len(rgb_black)}× Schwarz als RGB")
        details += ["Schwarz in RGB – " + d for d in rgb_black[:MAX_DETAILS]]
    if gray_black:
        status = max(status, Status.FAIL if s.gray_black_is_error else Status.WARN)
        parts.append(f"{len(gray_black)}× Schwarz als Graustufe (nicht CMYK)")
        details += ["Schwarz als Graustufe – " + d for d in gray_black[:MAX_DETAILS]]
    if rgb_other:
        status = max(status, Status.FAIL if s.rgb_is_error else Status.WARN)
        parts.append(f"{len(rgb_other)}× weitere RGB-Farbe")
        details += ["RGB-Farbe – " + d for d in rgb_other[:MAX_DETAILS]]
    if rgb_images:
        status = max(status, Status.FAIL if s.rgb_is_error else Status.WARN)
        parts.append(f"{len(rgb_images)}× RGB-Bild")
        details += rgb_images[:MAX_DETAILS]

    message = ", ".join(parts) if parts else "Keine RGB- oder Graustufen-Schwarzwerte gefunden"
    return CheckResult("schwarz", CHECK_TITLES["schwarz"], status, message, details)


def check_embedded(info: EPSInfo, an: Analysis | None) -> CheckResult:
    n_img = len(an.images) if an else 0
    if info.links:
        return CheckResult(
            "eingebettet",
            CHECK_TITLES["eingebettet"],
            Status.FAIL,
            f"{len(info.links)} Verknüpfung(en) auf externe Daten gefunden",
            info.links[:MAX_DETAILS],
        )
    if an is None:
        return CheckResult("eingebettet", CHECK_TITLES["eingebettet"], Status.INFO,
                           "Keine Verknüpfungen gefunden (Bilder nicht analysiert)")
    if n_img == 0:
        return CheckResult("eingebettet", CHECK_TITLES["eingebettet"], Status.OK,
                           "Keine Pixeldaten enthalten, keine Verknüpfungen")
    return CheckResult("eingebettet", CHECK_TITLES["eingebettet"], Status.OK,
                       f"{n_img} Bild(er) vollständig eingebettet")


def resolution_title(s: Settings) -> str:
    return f"{CHECK_TITLES['aufloesung']} {s.min_dpi:g}–{s.max_dpi:g} dpi"


def check_resolution(an: Analysis, s: Settings) -> CheckResult:
    title = resolution_title(s)
    images = an.images
    if not images:
        return CheckResult("aufloesung", title, Status.OK, "Keine Pixeldaten enthalten")
    measured = [ev for ev in images if ev.dpi > 0]
    too_high = [ev for ev in measured if ev.dpi > s.max_dpi + DPI_TOLERANCE]
    too_low = [ev for ev in measured if min(ev.dpi_x, ev.dpi_y) < s.min_dpi - DPI_TOLERANCE]
    details = []
    for ev in images[: MAX_DETAILS * 2]:
        mark = "ZU HOCH – " if ev in too_high else "ZU NIEDRIG – " if ev in too_low else ""
        model = _color_model(ev.cs_family, ev.cs_detail)
        kind = ("Strichbild (1 Bit)" if ev.op == "imagemask"
                else {"cmyk": "CMYK", "rgb": "RGB", "gray": "Graustufe"}.get(model, ev.cs_family))
        dpi = (f"{ev.dpi_x:.0f} dpi" if abs(ev.dpi_x - ev.dpi_y) < 1
               else f"{ev.dpi_x:.0f} × {ev.dpi_y:.0f} dpi")
        details.append(f"{mark}{dpi}, {ev.width}×{ev.height} px, {kind}{_fmt_box(ev)}")
    span = ""
    if measured:
        lo = min(min(ev.dpi_x, ev.dpi_y) for ev in measured)
        hi = max(ev.dpi for ev in measured)
        span = f"{lo:.0f} dpi" if round(lo) == round(hi) else f"{lo:.0f}–{hi:.0f} dpi"
    problems = []
    if too_high:
        problems.append(f"{len(too_high)} über {s.max_dpi:g} dpi")
    if too_low:
        problems.append(f"{len(too_low)} unter {s.min_dpi:g} dpi")
    if problems:
        return CheckResult(
            "aufloesung", title, Status.FAIL,
            f"{' und '.join(problems)} (von {len(images)} Bild(ern), {span})", details,
        )
    return CheckResult("aufloesung", title, Status.OK, f"{len(images)} Bild(er), {span}", details)


def check_overprint(an: Analysis) -> CheckResult:
    hits = [ev for ev in an.events if ev.overprint]
    if not hits:
        return CheckResult("ueberdrucken", CHECK_TITLES["ueberdrucken"], Status.OK,
                           "Kein Objekt ist auf Überdrucken gestellt")
    details = [f"{ev.op}: {_fmt_color(ev)}{_fmt_box(ev)}" for ev in hits[:MAX_DETAILS]]
    return CheckResult("ueberdrucken", CHECK_TITLES["ueberdrucken"], Status.FAIL,
                       f"{len(hits)} Objekt(e) auf Überdrucken gestellt", details)


AREA_OPS = ("fill", "eofill", "rectfill", "shfill")


def _coverage(info: EPSInfo, ev: PaintEvent) -> str:
    """Info-Text, wie viel der BoundingBox die Fläche abdeckt (keine Bewertung)."""
    bbox, box = info.effective_bbox, ev.visible_box
    if bbox is None or box is None or bbox.width <= 0 or bbox.height <= 0:
        return ""
    w = max(0.0, min(box.urx, bbox.urx) - max(box.llx, bbox.llx))
    h = max(0.0, min(box.ury, bbox.ury) - max(box.lly, bbox.lly))
    share = 100 * w * h / (bbox.width * bbox.height)
    return f"Fläche deckt ca. {share:.0f} % der BoundingBox ab"


def check_background(info: EPSInfo, an: Analysis) -> CheckResult:
    """Unterstes Objekt soll eine deckende Farbfläche sein (Größe egal).

    Warnung nur, wenn dort keine Fläche liegt oder die Fläche Transparenz hat.
    """
    key, title = "hintergrund", CHECK_TITLES["hintergrund"]
    first = an.first_paint
    if first is None:
        return CheckResult(key, title, Status.WARN, "Keine Farbfläche vorhanden – die Datei malt keine Objekte")

    details = [f"Unterstes Objekt: {first.op}, {_fmt_color(first)}{_fmt_box(first)}"]
    if first.kind == "IMAGE" or first.op not in AREA_OPS:
        what = ("ein Bild" if first.kind == "IMAGE"
                else "eine Kontur" if first.op in ("stroke", "rectstroke") else "Text")
        return CheckResult(key, title, Status.WARN,
                           f"Keine Farbfläche als unterstes Objekt (dort liegt {what})", details)

    transparency = []
    if first.alpha < 1.0:
        transparency.append(f"Deckkraft nur {first.alpha * 100:.0f} %")
    if any(t.before_first_paint for t in an.transparency):
        transparency.append("Vor der Fläche wird Transparenz gesetzt (pdfmark SetTransparency)")
    if cover := _coverage(info, first):
        details.append(cover)
    if transparency:
        return CheckResult(key, title, Status.WARN, "Farbfläche mit Transparenz: " + transparency[0],
                           details + transparency)
    return CheckResult(key, title, Status.OK, f"Deckende Farbfläche vorhanden ({_fmt_color(first)})", details)


# ---------------------------------------------------------------------------
# Gesamtprüfung einer Datei
# ---------------------------------------------------------------------------

def check_file(path: str | Path, settings: Settings) -> FileResult:
    result = FileResult(path=Path(path))
    try:
        info = read_eps(path)
    except EPSReadError as exc:
        result.checks.append(CheckResult("datei", CHECK_TITLES["datei"], Status.FAIL, str(exc)))
        return result
    result.info = info

    file_details = [
        f"Kopfzeile: {info.header_line}",
        f"Erstellt mit: {info.creator or 'unbekannt'}",
        f"BoundingBox: {info.bbox}" + (f"  (HiRes: {info.hires_bbox})" if info.hires_bbox else ""),
    ]
    if info.has_dos_header:
        file_details.append("DOS-EPS mit Vorschaubild")

    if not settings.gs_executable:
        result.checks.append(CheckResult(
            "datei", CHECK_TITLES["datei"], Status.FAIL,
            "Ghostscript nicht gefunden – nur Verknüpfungen geprüft", file_details))
        result.checks.append(check_embedded(info, None))
        return result

    try:
        an = analyze(info, settings.gs_executable, settings.timeout)
    except AnalysisError as exc:
        result.checks.append(CheckResult("datei", CHECK_TITLES["datei"], Status.FAIL,
                                         str(exc), file_details))
        result.checks.append(check_embedded(info, None))
        return result
    result.analysis = an

    status, message = Status.OK, f"{an.paint_count} Objekte, {an.image_count} Bild(er) analysiert"
    if an.ps_error:
        status, message = Status.FAIL, f"PostScript-Fehler: {an.ps_error} (Prüfung unvollständig)"
    elif not an.completed:
        status, message = Status.FAIL, "PostScript-Ausführung wurde abgebrochen (Prüfung unvollständig)"
    elif not info.is_eps_header:
        status, message = Status.WARN, "Kopfzeile ist keine gültige EPSF-Kennung"
    elif info.bbox is None:
        status, message = Status.WARN, "Keine %%BoundingBox angegeben"
    if an.missing_fonts:
        file_details.append("Nicht eingebettete Schrift(en): " + ", ".join(an.missing_fonts[:MAX_DETAILS]))
        if status == Status.OK:
            status, message = Status.WARN, (
                f"{len(an.missing_fonts)} Schrift(en) nicht eingebettet: "
                + ", ".join(an.missing_fonts[:3]) + (" …" if len(an.missing_fonts) > 3 else "")
            )
    result.checks.append(CheckResult("datei", CHECK_TITLES["datei"], status, message, file_details))

    result.checks.append(check_black(an, settings))
    result.checks.append(check_embedded(info, an))
    result.checks.append(check_resolution(an, settings))
    result.checks.append(check_overprint(an))
    result.checks.append(check_background(info, an))
    return result
