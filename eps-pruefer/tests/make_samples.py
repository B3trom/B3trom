"""Erzeugt kleine Beispiel-EPS-Dateien für die automatischen Tests.

Aufruf:  python tests/make_samples.py [zielordner]
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

HEADER = """%!PS-Adobe-3.0 EPSF-3.0
%%BoundingBox: 0 0 200 100
%%HiResBoundingBox: 0 0 200 100
%%Creator: EPS-Pruefer Testgenerator
{extra}%%EndComments
"""

BACKGROUND_CMYK = "0 0 0 0 setcmykcolor 0 0 200 100 rectfill\n"
TEXT = "/Helvetica findfont 20 scalefont setfont 10 40 moveto (Anzeige) show\n"

# Eingebettete Type-3-Schrift: ihre Glyphen malen intern mit "fill" (verschachtelt)
EMBEDDED_FONT = """%%BeginResource: font Kasten
8 dict begin
/FontType 3 def /FontMatrix [0.001 0 0 0.001 0 0] def /FontBBox [0 0 600 700] def
/Encoding 256 array def 0 1 255 { Encoding exch /box put } for
/BuildChar { pop pop 600 0 0 0 600 700 setcachedevice 50 0 500 700 rectfill } def
currentdict end /Kasten exch definefont pop
%%EndResource
"""
TEXT_EMBEDDED = "/Kasten findfont 20 scalefont setfont 10 40 moveto (Anzeige) show\n"

# Prozeduren wie in Illustrator-Prologen: per bind gebunden
BIND_PROLOG = "/F { fill } bind def /S { stroke } bind def /k { setcmykcolor } bind def\n"


def _image(dpi: float, ncomp: int = 4, px: int = 20) -> str:
    """Bild mit px x px Pixeln, so skaliert, dass die gewünschte Auflösung entsteht."""
    size = px * 72.0 / dpi
    data = ("00" * ncomp * px) + "\n"
    return (
        f"gsave 120 10 translate {size:.4f} {size:.4f} scale\n"
        f"{px} {px} 8 [{px} 0 0 -{px} 0 {px}] currentfile /ASCIIHexDecode filter "
        f"false {ncomp} colorimage\n" + data * px + ">\ngrestore\n"
    )


def _dict_image(dpi: float, px: int = 16) -> str:
    """Level-2-Bild (Dictionary-Form) im aktuellen Farbraum CMYK."""
    size = px * 72.0 / dpi
    return (
        f"gsave /DeviceCMYK setcolorspace 60 70 translate {size:.4f} {size:.4f} scale\n"
        f"<< /ImageType 1 /Width {px} /Height {px} /BitsPerComponent 8 /Decode [0 1 0 1 0 1 0 1]\n"
        f"   /ImageMatrix [{px} 0 0 -{px} 0 {px}]\n"
        f"   /DataSource currentfile /ASCIIHexDecode filter >> image\n"
        + ("20" * 4 * px + "\n") * px + ">\ngrestore\n"
    )


SAMPLES: dict[str, tuple[str, str]] = {
    # name: (zusätzliche Header-Kommentare, Inhalt)
    "ok.eps": (
        "",
        EMBEDDED_FONT + BIND_PROLOG
        + "0 0 0 0 k newpath 0 0 moveto 200 0 lineto 200 100 lineto 0 100 lineto closepath F\n"
        + "0 0 0 1 k " + TEXT_EMBEDDED + _image(100)
        + "gsave 20 60 translate 30 30 scale 8 8 true [8 0 0 -8 0 8] {<ff00ff00ff00ff00>} imagemask grestore\n"
        + _dict_image(140),
    ),
    "muster.eps": (
        "",
        BACKGROUND_CMYK
        + "<< /PatternType 1 /PaintType 1 /TilingType 1 /BBox [0 0 10 10] /XStep 10 /YStep 10\n"
        + "   /PaintProc { pop 0 0 0 setrgbcolor 0 0 5 5 rectfill } >> matrix makepattern setpattern\n"
        + "20 20 50 50 rectfill\n"
        + "<< /ShadingType 2 /ColorSpace /DeviceRGB /Coords [0 0 100 0]\n"
        + "   /Function << /FunctionType 2 /Domain [0 1] /C0 [1 0 0] /C1 [0 0 1] /N 1 >> >> shfill\n",
    ),
    "strichbild_hoch.eps": (
        "",
        BACKGROUND_CMYK + "0 0 0 1 setcmykcolor gsave 20 20 translate 7.2 7.2 scale "
        "60 60 true [60 0 0 -60 0 60] {<" + "ff" * 450 + ">} imagemask grestore\n",
    ),
    "rgb_schwarz.eps": ("", BACKGROUND_CMYK + "0 0 0 setrgbcolor " + TEXT),
    "rgb_farbe.eps": ("", BACKGROUND_CMYK + "1 0 0 setrgbcolor 10 10 20 20 rectfill"),
    "grau_schwarz.eps": ("", BACKGROUND_CMYK + "0 setgray " + TEXT),
    "hochaufgeloest.eps": ("", BACKGROUND_CMYK + _image(300)),
    "rgb_bild.eps": ("", BACKGROUND_CMYK + _image(120, ncomp=3)),
    "ueberdrucken.eps": (
        "",
        BACKGROUND_CMYK + "true setoverprint 0 0 0 1 setcmykcolor 10 10 moveto 50 50 lineto stroke",
    ),
    "ohne_hintergrund.eps": ("", "0 0 0 1 setcmykcolor 10 10 50 50 rectfill\n"),
    "hintergrund_zu_klein.eps": ("", "0.2 0 0 0 setcmykcolor 0 0 150 100 rectfill\n" + TEXT),
    "hintergrund_bild.eps": ("", _image(100) + TEXT),
    "hintergrund_transparent.eps": (
        "",
        "/pdfmark where {pop} {userdict /pdfmark /cleartomark load put} ifelse\n"
        "[ /ca 0.5 /CA 0.5 /SetTransparency pdfmark\n" + BACKGROUND_CMYK,
    ),
    "verknuepft_opi.eps": (
        "",
        BACKGROUND_CMYK + "%%BeginOPI: 2.0\n%%ImageFileName: (Bilder/foto.tif)\n%%EndOPI\n",
    ),
    "hintergrund_pfad.eps": (
        "",
        "0 0.5 1 0 setcmykcolor newpath -5 -5 moveto 205 -5 lineto 205 105 lineto "
        "-5 105 lineto closepath fill\n" + TEXT,
    ),
    "postscript_fehler.eps": ("", BACKGROUND_CMYK + "gibtesnicht\n"),
}


def write_samples(target: Path) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for name, (extra, body) in SAMPLES.items():
        content = HEADER.format(extra=extra) + body + "\n%%EOF\n"
        path = target / name
        path.write_bytes(content.encode("latin-1"))
        written.append(path)

    # DOS-EPS mit (leerer) TIFF-Vorschau
    ps = (HEADER.format(extra="") + BACKGROUND_CMYK + "\n%%EOF\n").encode("latin-1")
    tiff = b"II*\x00" + b"\x00" * 16
    header_len = 30
    header = struct.pack(
        "<4sIIIIIIH",
        b"\xc5\xd0\xd3\xc6",
        header_len,
        len(ps),
        0,
        0,
        header_len + len(ps),
        len(tiff),
        0xFFFF,
    )
    path = target / "dos_header.eps"
    path.write_bytes(header + ps + tiff)
    written.append(path)
    return written


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "beispiele"
    for p in write_samples(out):
        print(p)
