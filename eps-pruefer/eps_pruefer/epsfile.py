"""Einlesen von EPS-Dateien und statische Auswertung der DSC-Kommentare."""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

DOS_EPS_MAGIC = b"\xc5\xd0\xd3\xc6"

# Kommentare, die auf nicht eingebettete (verknüpfte) Daten hinweisen
_LINK_PATTERNS = [
    (re.compile(r"^%ALDImageFileName:\s*(.+)$"), "OPI 1.3 Bildverknüpfung"),
    (re.compile(r"^%%ImageFileName:\s*(.+)$"), "OPI 2.0 Bildverknüpfung"),
    (re.compile(r"^%%BeginOPI:\s*(.*)$"), "OPI-Platzhalter (Bild wird erst beim Belichter eingesetzt)"),
    (re.compile(r"^%%IncludeDocument:\s*(.+)$"), "Einzubindendes externes Dokument"),
    (re.compile(r"^%%IncludeFile:\s*(.+)$"), "Einzubindende externe Datei"),
    (re.compile(r"^%%(?:Cyan|Magenta|Yellow|Black)Plate:\s*(.+)$"), "DCS 1.0 externe Farbauszugsdatei"),
]
_PLATEFILE = re.compile(r"^%%PlateFile:\s*(.+)$")
# DSC-Kommentare, deren Werte (inkl. %%+ Fortsetzungszeilen) externe Dateien nennen
_NEEDED_KEYS = ("DocumentNeededFiles", "DocumentFiles", "DocumentNeededResources")
_DSC_KEY = re.compile(r"^%%([A-Za-z]+):\s*(.*)$")
_LINE_SPLIT = re.compile(rb"\r\n|\r|\n")


class EPSReadError(Exception):
    pass


@dataclass
class BBox:
    llx: float
    lly: float
    urx: float
    ury: float

    @property
    def width(self) -> float:
        return self.urx - self.llx

    @property
    def height(self) -> float:
        return self.ury - self.lly

    def __str__(self) -> str:
        return f"{self.llx:g} {self.lly:g} {self.urx:g} {self.ury:g}"


@dataclass
class EPSInfo:
    path: Path
    ps_data: bytes
    has_dos_header: bool = False
    header_line: str = ""
    is_eps_header: bool = False
    bbox: BBox | None = None
    hires_bbox: BBox | None = None
    creator: str = ""
    title: str = ""
    links: list[str] = field(default_factory=list)

    @property
    def effective_bbox(self) -> BBox | None:
        return self.hires_bbox or self.bbox


def _extract_ps(raw: bytes) -> tuple[bytes, bool]:
    """Liefert den PostScript-Teil (bei DOS-EPS ohne TIFF/WMF-Vorschau)."""
    if raw[:4] == DOS_EPS_MAGIC:
        if len(raw) < 30:
            raise EPSReadError("DOS-EPS-Header ist unvollständig")
        ps_start, ps_len = struct.unpack("<II", raw[4:12])
        if ps_start + ps_len > len(raw) or ps_len == 0:
            raise EPSReadError("DOS-EPS-Header verweist außerhalb der Datei")
        return raw[ps_start : ps_start + ps_len], True
    # Manche Programme setzen Müll (z. B. Leerzeilen, ^D) vor den Header
    idx = raw.find(b"%!PS", 0, 1024)
    if idx < 0:
        raise EPSReadError("Keine PostScript-Kennung (%!PS) gefunden – keine EPS-Datei?")
    return raw[idx:], False


def _parse_bbox(value: str) -> BBox | None:
    parts = value.split()
    if len(parts) != 4:
        return None
    try:
        return BBox(*(float(p) for p in parts))
    except ValueError:
        return None


def read_eps(path: str | Path) -> EPSInfo:
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise EPSReadError(f"Datei kann nicht gelesen werden: {exc}") from exc

    ps, dos = _extract_ps(raw)
    info = EPSInfo(path=path, ps_data=ps, has_dos_header=dos)

    lines = _LINE_SPLIT.split(ps)
    info.header_line = lines[0].decode("latin-1", "replace").strip() if lines else ""
    info.is_eps_header = bool(re.match(r"^%!PS-Adobe-\d\.\d\s+EPSF-\d\.\d", info.header_line))

    in_header = True
    bbox_atend = hires_atend = False
    skip_depth = 0  # eingebettete Dokumente (%%BeginDocument) nicht als eigene DSC werten
    current_key = ""

    for raw_line in lines:
        if not raw_line.startswith(b"%"):
            current_key = ""
            continue
        line = raw_line.decode("latin-1", "replace").rstrip()

        if line.startswith("%%BeginDocument"):
            skip_depth += 1
        elif line.startswith("%%EndDocument") and skip_depth:
            skip_depth -= 1

        # Verknüpfungen werden auch in eingebetteten Dokumenten gesucht
        for pattern, label in _LINK_PATTERNS:
            m = pattern.match(line)
            if m:
                info.links.append(f"{label}: {m.group(1).strip()}")
        m = _PLATEFILE.match(line)
        if m and "#" not in m.group(1):
            info.links.append(f"DCS 2.0 externe Farbauszugsdatei: {m.group(1).strip()}")

        # Wert eines DSC-Kommentars bzw. seiner %%+ Fortsetzungszeile
        if line.startswith("%%+"):
            key, value = current_key, line[3:].strip()
        else:
            m = _DSC_KEY.match(line)
            key, value = (m.group(1), m.group(2).strip()) if m else ("", "")
            current_key = key
        if key in _NEEDED_KEYS and value and value != "(atend)":
            if key == "DocumentNeededResources":
                if value.startswith("file "):
                    info.links.append(f"Benötigte externe Datei: {value[5:].strip()}")
            else:
                info.links.append(f"Benötigte externe Datei: {value}")

        if skip_depth:
            continue

        if line.startswith("%%EndComments"):
            in_header = False
        elif line.startswith("%%BoundingBox:"):
            value = line.split(":", 1)[1].strip()
            if value == "(atend)":
                bbox_atend = True
            elif in_header and info.bbox is None or bbox_atend:
                info.bbox = _parse_bbox(value) or info.bbox
        elif line.startswith("%%HiResBoundingBox:"):
            value = line.split(":", 1)[1].strip()
            if value == "(atend)":
                hires_atend = True
            elif in_header and info.hires_bbox is None or hires_atend:
                info.hires_bbox = _parse_bbox(value) or info.hires_bbox
        elif in_header and line.startswith("%%Creator:"):
            info.creator = line.split(":", 1)[1].strip()
        elif in_header and line.startswith("%%Title:"):
            info.title = line.split(":", 1)[1].strip()

    # doppelte Einträge entfernen, Reihenfolge behalten
    info.links = list(dict.fromkeys(info.links))
    return info
