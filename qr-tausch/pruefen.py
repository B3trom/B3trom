#!/usr/bin/env python3
"""
pruefen.py – prüft die Ergebnisse von qr_tausch.jsx unabhängig von Illustrator.

    python3 pruefen.py --original ANZEIGEN/_original --neu ANZEIGEN --qr QR_ORDNER --bericht BERICHT

Pro Anzeige (Original aus _original/ gegen überschriebene Datei):
  1. Neuer Code lesbar und Inhalt == Inhalt der zugeordneten QR-PDF
  2. Alter Inhalt nirgends mehr: weder als Code noch als Text in der EPS
  3. Lage/Größe des neuen Codes == alter Code (Toleranz 0,3 mm)
  4. Farbe der Module (gerenderte CMYK-Werte) == alte Farbe (Toleranz 2 %)
  5. Außerhalb des QR-Bereichs keine Veränderung (Pixelvergleich, CMYK)
  6. Format (BoundingBox) unverändert
Ergebnis: bericht.html (mit Vorschau) und bericht.csv

Benötigt: Ghostscript (gs), zbarimg, Python: numpy, pillow, opencv-python-headless
"""
import argparse, csv, html, os, re, subprocess, sys, tempfile
from pathlib import Path

import numpy as np
from PIL import Image

DPI = 300
MM = DPI / 25.4
POS_TOL_MM = 0.3
COLOR_TOL = 0.02 * 255
DIFF_MARGIN_MM = 1.5
INK_THRESHOLD = 60   # Summe CMYK (0..1020), ab der ein Pixel als "Farbe" zählt


# ------------------------------------------------------------------ Rendern
def render_cmyk(path: Path, out: Path) -> np.ndarray:
    args = ["gs", "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-dNOINTERPOLATE",
            "-sDEVICE=tiff32nc", f"-r{DPI}", f"-sOutputFile={out}"]
    if path.suffix.lower() == ".eps":
        args.insert(4, "-dEPSCrop")
    else:
        args.insert(4, "-dFirstPage=1"); args.insert(5, "-dLastPage=1")
    subprocess.run(args + [str(path)], check=True, capture_output=True)
    return np.array(Image.open(out).convert("CMYK"))


def cmyk_to_gray(a: np.ndarray) -> np.ndarray:
    ink = a.astype(np.int32)
    lum = 255 - np.clip(ink[..., 3] + (ink[..., 0] * 0.3 + ink[..., 1] * 0.59 + ink[..., 2] * 0.11), 0, 255)
    return lum.astype(np.uint8)


# ------------------------------------------------------------------ QR lesen
def decode(gray: np.ndarray, tmp: Path):
    """liefert Liste (text, (x0, y0, x1, y1)) in Pixeln"""
    import cv2
    found = []
    det = cv2.QRCodeDetector()
    for img in (gray, cv2.resize(gray, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)):
        scale = gray.shape[1] / img.shape[1]
        ok, texts, pts, _ = det.detectAndDecodeMulti(img)
        if ok:
            for t, p in zip(texts, pts):
                if t:
                    p = p * scale
                    found.append((t, (p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max())))
        if found:
            break
    # zbar als zweite Meinung (findet auch Codes, die OpenCV nicht liest)
    png = tmp / "z.png"
    Image.fromarray(gray).save(png)
    r = subprocess.run(["zbarimg", "-q", "--xml", "--set", "*.enable=0", "--set", "qrcode.enable=1", str(png)],
                       capture_output=True, text=True)
    for m in re.finditer(r"<symbol[^>]*>.*?<data[^>]*><!\[CDATA\[(.*?)\]\]></data>.*?</symbol>", r.stdout, re.S):
        sym = m.group(0)
        txt = m.group(1)
        pm = re.search(r"points=['\"]([^'\"]+)['\"]", sym)
        pts = [tuple(float(v) for v in p.split(",")) for p in pm.group(1).split()] if pm else []
        if not any(f[0] == txt for f in found):
            if pts:
                xs, ys = zip(*pts)
                found.append((txt, (min(xs), min(ys), max(xs), max(ys))))
            else:
                found.append((txt, None))
    return found


def module_bbox(cmyk: np.ndarray, box):
    """exakte Außenkante der farbigen Module innerhalb der (groben) Decoderbox"""
    h, w = cmyk.shape[:2]
    pad = int(4 * MM)
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)
    region = cmyk[y0:y1, x0:x1].astype(np.int32).sum(axis=2) > INK_THRESHOLD
    # nur Spalten/Zeilen, die zum Code gehören: Finder-Pattern liegen an den Ecken der Decoderbox
    ys, xs = np.nonzero(region)
    if not len(xs):
        return None
    inner = (xs >= (box[0] - x0) - pad / 2) & (xs <= (box[2] - x0) + pad / 2) & \
            (ys >= (box[1] - y0) - pad / 2) & (ys <= (box[3] - y0) + pad / 2)
    xs, ys = xs[inner], ys[inner]
    return (x0 + xs.min(), y0 + ys.min(), x0 + xs.max() + 1, y0 + ys.max() + 1)


def module_color(cmyk: np.ndarray, bb):
    x0, y0, x1, y1 = [int(v) for v in bb]
    reg = cmyk[y0:y1, x0:x1].reshape(-1, 4).astype(np.int32)
    inked = reg[reg.sum(axis=1) > INK_THRESHOLD]
    if not len(inked):
        return None
    return np.median(inked, axis=0)


def eps_bbox(path: Path):
    with open(path, "rb") as f:
        head = f.read(200_000)
    m = re.search(rb"%%HiResBoundingBox:\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", head) or \
        re.search(rb"%%BoundingBox:\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", head)
    return tuple(float(v) for v in m.groups()) if m else None


def text_contains(path: Path, needle: str) -> bool:
    if not needle:
        return False
    data = path.read_bytes().lower()
    n = needle.lower().encode()
    variants = {n, n.replace(b"https://", b""), n.replace(b"http://", b"")}
    return any(v and v in data for v in variants)


# ------------------------------------------------------------------ Zuordnung
def read_mapping(qr_dir: Path):
    m = {}
    f = qr_dir / "zuordnung.csv"
    if f.exists():
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            parts = re.split(r"[;,\t]", line)
            if len(parts) >= 2 and parts[0].strip().lower().endswith(".eps"):
                m[parts[0].strip().lower()] = parts[1].strip()
    return m


def qr_for(ad: Path, qr_dir: Path, mapping, pdfs):
    if ad.name.lower() in mapping:
        p = qr_dir / mapping[ad.name.lower()]
        return p if p.exists() else None
    p = qr_dir / (ad.stem + ".pdf")
    if p.exists():
        return p
    return pdfs[0] if len(pdfs) == 1 else None


# ------------------------------------------------------------------ Prüfung
def check(orig: Path, new: Path, qrpdf: Path, tmp: Path, thumbs: Path, qr_cache: dict):
    r = {"datei": new.name, "qr_datei": qrpdf.name if qrpdf else "", "ergebnis": "BESTANDEN", "fehler": [],
         "alt_inhalt": "", "neu_inhalt": "", "soll_inhalt": "", "pos_abw_mm": "", "farbe_alt": "", "farbe_neu": "",
         "pixel_geaendert_ausserhalb": ""}
    fail = r["fehler"].append

    if not qrpdf:
        fail("keine QR-PDF zugeordnet")
    else:
        if qrpdf not in qr_cache:
            g = cmyk_to_gray(render_cmyk(qrpdf, tmp / "q.tif"))
            d = decode(g, tmp)
            qr_cache[qrpdf] = d[0][0] if d else None
        r["soll_inhalt"] = qr_cache[qrpdf] or ""
        if not qr_cache[qrpdf]:
            fail("QR-PDF selbst nicht lesbar")

    a = render_cmyk(orig, tmp / "a.tif")
    b = render_cmyk(new, tmp / "b.tif")
    da, db = decode(cmyk_to_gray(a), tmp), decode(cmyk_to_gray(b), tmp)

    if not da:
        fail("im Original kein QR-Code lesbar")
    else:
        r["alt_inhalt"] = da[0][0]
    if not db:
        fail("neuer QR-Code nicht lesbar")
    else:
        r["neu_inhalt"] = " | ".join(t for t, _ in db)

    # 1 Inhalt
    if db and r["soll_inhalt"] and not any(t == r["soll_inhalt"] for t, _ in db):
        fail("Inhalt des neuen Codes stimmt nicht mit der QR-PDF überein")
    # 2 alter Inhalt weg
    if da:
        old = da[0][0]
        if old != r["soll_inhalt"]:
            if any(t == old for t, _ in db):
                fail("alter QR-Code noch vorhanden")
            if text_contains(new, old):
                fail("alte URL steht noch als Text in der Datei")
        else:
            fail("Original enthält bereits den neuen Inhalt (doppelt verarbeitet?)")
    # 6 Format
    if a.shape != b.shape or (eps_bbox(orig) and eps_bbox(new) and
                              max(abs(x - y) for x, y in zip(eps_bbox(orig), eps_bbox(new))) > 0.5):
        fail(f"Format/BoundingBox geändert ({a.shape[1]}x{a.shape[0]} -> {b.shape[1]}x{b.shape[0]} px)")

    bb_a = module_bbox(a, da[0][1]) if da and da[0][1] else None
    hit = [x for x in db if x[0] == r["soll_inhalt"]] or db
    bb_b = module_bbox(b, hit[0][1]) if hit and hit[0][1] else None

    # 3 Lage/Größe
    if bb_a and bb_b:
        dev = max(abs(x - y) for x, y in zip(bb_a, bb_b)) / MM
        r["pos_abw_mm"] = f"{dev:.2f}"
        if dev > POS_TOL_MM:
            fail(f"Lage/Größe weicht um {dev:.2f} mm ab")
    # 4 Farbe
    if bb_a and bb_b:
        ca, cb = module_color(a, bb_a), module_color(b, bb_b)
        if ca is not None and cb is not None:
            r["farbe_alt"] = "C{:.0f} M{:.0f} Y{:.0f} K{:.0f}".format(*(ca / 2.55))
            r["farbe_neu"] = "C{:.0f} M{:.0f} Y{:.0f} K{:.0f}".format(*(cb / 2.55))
            if np.abs(ca - cb).max() > COLOR_TOL:
                fail("Farbe des neuen Codes weicht ab")
    # 5 Rest unverändert
    if a.shape == b.shape:
        mask = np.ones(a.shape[:2], bool)
        m = int(DIFF_MARGIN_MM * MM)
        for bb in (bb_a, bb_b):
            if bb:
                x0, y0, x1, y1 = [int(v) for v in bb]
                mask[max(0, y0 - m):y1 + m, max(0, x0 - m):x1 + m] = False
        changed = (np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2) > 8) & mask
        n = int(changed.sum())
        r["pixel_geaendert_ausserhalb"] = str(n)
        if n > 20:
            fail(f"{n} Pixel außerhalb des QR-Bereichs verändert")
    else:
        changed = None

    # Vorschaubilder
    stem = re.sub(r"[^\w.-]", "_", new.stem)
    for tag, arr, bb in (("alt", a, bb_a), ("neu", b, bb_b)):
        rgb = Image.fromarray(arr, "CMYK").convert("RGB")
        t = rgb.copy(); t.thumbnail((420, 420)); t.save(thumbs / f"{stem}_{tag}.jpg", quality=80)
        if bb:
            pad = int(3 * MM)
            crop = rgb.crop((max(0, bb[0] - pad), max(0, bb[1] - pad), bb[2] + pad, bb[3] + pad))
            crop.thumbnail((220, 220)); crop.save(thumbs / f"{stem}_{tag}_qr.png")
    if changed is not None and changed.any():
        Image.fromarray((changed * 255).astype(np.uint8)).convert("RGB").resize(
            (min(420, a.shape[1]), int(min(420, a.shape[1]) * a.shape[0] / a.shape[1]))).save(thumbs / f"{stem}_diff.png")
    r["stem"] = stem

    if r["fehler"]:
        r["ergebnis"] = "FEHLER"
    return r


# ------------------------------------------------------------------ Bericht
def write_report(rows, out: Path):
    cols = ["datei", "qr_datei", "ergebnis", "fehler", "soll_inhalt", "neu_inhalt", "alt_inhalt",
            "pos_abw_mm", "farbe_alt", "farbe_neu", "pixel_geaendert_ausserhalb"]
    with open(out / "bericht.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(cols)
        for r in rows:
            w.writerow([" / ".join(r[c]) if c == "fehler" else r[c] for c in cols])

    ok = sum(r["ergebnis"] == "BESTANDEN" for r in rows)
    e = html.escape
    cards = []
    for r in sorted(rows, key=lambda r: (r["ergebnis"] == "BESTANDEN", r["datei"])):
        s = r.get("stem", "")
        img = lambda n: f'<img src="vorschau/{s}_{n}" loading="lazy">' if (out / "vorschau" / f"{s}_{n}").exists() else ""
        cards.append(f"""
<article class="{'ok' if r['ergebnis'] == 'BESTANDEN' else 'bad'}">
  <h2>{e(r['datei'])} <span>{e(r['ergebnis'])}</span></h2>
  {'<ul class="err">' + ''.join(f'<li>{e(x)}</li>' for x in r['fehler']) + '</ul>' if r['fehler'] else ''}
  <div class="imgs"><figure>{img('alt.jpg')}<figcaption>vorher</figcaption></figure>
    <figure>{img('neu.jpg')}<figcaption>nachher</figcaption></figure>
    <figure>{img('alt_qr.png')}<figcaption>QR alt</figcaption></figure>
    <figure>{img('neu_qr.png')}<figcaption>QR neu</figcaption></figure>
    {('<figure>' + img('diff.png') + '<figcaption>Änderungen außerhalb</figcaption></figure>') if img('diff.png') else ''}</div>
  <dl><dt>Soll</dt><dd>{e(r['soll_inhalt'])}</dd><dt>Gelesen</dt><dd>{e(r['neu_inhalt'])}</dd>
      <dt>Alt</dt><dd>{e(r['alt_inhalt'])}</dd>
      <dt>Lageabweichung</dt><dd>{e(r['pos_abw_mm'])} mm</dd>
      <dt>Farbe alt → neu</dt><dd>{e(r['farbe_alt'])} → {e(r['farbe_neu'])}</dd>
      <dt>Pixel verändert (außerhalb QR)</dt><dd>{e(r['pixel_geaendert_ausserhalb'])}</dd></dl>
</article>""")
    (out / "bericht.html").write_text(f"""<!doctype html><html lang="de"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>QR-Prüfbericht</title>
<style>
:root{{--bg:#f6f6f4;--fg:#1d1d1b;--card:#fff;--ok:#1f7a3a;--bad:#b3261e;--line:#ddd}}
@media (prefers-color-scheme:dark){{:root{{--bg:#161615;--fg:#eee;--card:#222;--line:#333;--ok:#5cc27a;--bad:#ff7a70}}}}
body{{font:15px/1.45 system-ui,sans-serif;background:var(--bg);color:var(--fg);margin:0;padding:16px;max-width:1200px;margin:auto}}
.sum{{font-size:18px;margin:8px 0 20px}} article{{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--ok);border-radius:8px;padding:12px 16px;margin:0 0 14px}}
article.bad{{border-left-color:var(--bad)}} h2{{font-size:16px;margin:0 0 8px;display:flex;gap:10px;flex-wrap:wrap}}
h2 span{{color:var(--ok)}} .bad h2 span,.err{{color:var(--bad)}} .imgs{{display:flex;gap:10px;flex-wrap:wrap}}
figure{{margin:0}} img{{max-width:100%;max-height:260px;border:1px solid var(--line);background:#fff}} figcaption{{font-size:12px;opacity:.7}}
dl{{display:grid;grid-template-columns:max-content 1fr;gap:2px 12px;font-size:13px;margin:10px 0 0;word-break:break-all}} dt{{opacity:.7}}
</style>
<h1>QR-Prüfbericht</h1>
<p class="sum"><b>{ok}</b> von <b>{len(rows)}</b> Anzeigen bestanden · <b>{len(rows) - ok}</b> manuell prüfen</p>
{''.join(cards)}
</html>""", encoding="utf-8")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--original", required=True, type=Path, help="Ordner mit den Originalen (_original)")
    ap.add_argument("--neu", required=True, type=Path, help="Ordner mit den bearbeiteten EPS")
    ap.add_argument("--qr", required=True, type=Path, help="Ordner mit den neuen QR-PDFs (+ zuordnung.csv)")
    ap.add_argument("--bericht", default=Path("bericht"), type=Path)
    a = ap.parse_args()

    a.bericht.mkdir(parents=True, exist_ok=True)
    thumbs = a.bericht / "vorschau"; thumbs.mkdir(exist_ok=True)
    mapping = read_mapping(a.qr)
    pdfs = sorted(a.qr.glob("*.pdf")) + sorted(a.qr.glob("*.PDF"))
    ads = sorted(p for p in a.neu.iterdir() if p.suffix.lower() == ".eps")
    rows, cache = [], {}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for i, new in enumerate(ads, 1):
            orig = a.original / new.name
            print(f"[{i}/{len(ads)}] {new.name}", file=sys.stderr)
            if not orig.exists():
                rows.append({"datei": new.name, "qr_datei": "", "ergebnis": "FEHLER", "fehler": ["kein Original in _original"],
                             **{k: "" for k in ["alt_inhalt", "neu_inhalt", "soll_inhalt", "pos_abw_mm", "farbe_alt",
                                                "farbe_neu", "pixel_geaendert_ausserhalb"]}})
                continue
            try:
                rows.append(check(orig, new, qr_for(new, a.qr, mapping, pdfs), tmp, thumbs, cache))
            except Exception as ex:  # eine kaputte Datei darf den Lauf nicht stoppen
                rows.append({"datei": new.name, "qr_datei": "", "ergebnis": "FEHLER", "fehler": [f"Prüfung abgebrochen: {ex}"],
                             **{k: "" for k in ["alt_inhalt", "neu_inhalt", "soll_inhalt", "pos_abw_mm", "farbe_alt",
                                                "farbe_neu", "pixel_geaendert_ausserhalb"]}})
    ok = write_report(rows, a.bericht)
    print(f"\n{ok}/{len(rows)} bestanden. Bericht: {a.bericht / 'bericht.html'}")
    sys.exit(0 if ok == len(rows) else 1)


if __name__ == "__main__":
    main()
