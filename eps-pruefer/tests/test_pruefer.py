"""Automatische Tests. Aufruf im Projektordner:  python -m unittest -v"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eps_pruefer.checks import Settings, Status, check_file  # noqa: E402
from eps_pruefer.epsfile import read_eps  # noqa: E402
from eps_pruefer.ghostscript import find_ghostscript  # noqa: E402
from make_samples import write_samples  # noqa: E402

GS = find_ghostscript()


@unittest.skipUnless(GS, "Ghostscript nicht installiert")
class PruefungTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._tmp.name)
        write_samples(cls.dir)
        cls.settings = Settings(gs_executable=GS)
        cls.cache = {}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def result(self, name):
        if name not in self.cache:
            self.cache[name] = check_file(self.dir / name, self.settings)
        return self.cache[name]

    def status(self, name, key):
        return self.result(name).check(key).status

    def test_ok_datei_besteht_alles(self):
        r = self.result("ok.eps")
        for c in r.checks:
            self.assertEqual(c.status, Status.OK, f"{c.title}: {c.message}")
        self.assertEqual(len(r.analysis.images), 3)

    def test_rgb_schwarz_ist_fehler(self):
        self.assertEqual(self.status("rgb_schwarz.eps", "schwarz"), Status.FAIL)

    def test_rgb_farbe_ist_warnung_oder_fehler(self):
        self.assertEqual(self.status("rgb_farbe.eps", "schwarz"), Status.WARN)
        strict = check_file(self.dir / "rgb_farbe.eps", Settings(gs_executable=GS, rgb_is_error=True))
        self.assertEqual(strict.check("schwarz").status, Status.FAIL)

    def test_graustufen_schwarz_ist_warnung(self):
        self.assertEqual(self.status("grau_schwarz.eps", "schwarz"), Status.WARN)

    def test_rgb_bild_ist_warnung(self):
        self.assertEqual(self.status("rgb_bild.eps", "schwarz"), Status.WARN)

    def test_rgb_im_muster_wird_gefunden(self):
        self.assertEqual(self.status("muster.eps", "schwarz"), Status.FAIL)

    def test_aufloesung(self):
        self.assertEqual(self.status("hochaufgeloest.eps", "aufloesung"), Status.FAIL)
        self.assertEqual(self.status("strichbild_hoch.eps", "aufloesung"), Status.FAIL)
        self.assertEqual(self.status("rgb_bild.eps", "aufloesung"), Status.OK)
        img = self.result("hochaufgeloest.eps").analysis.images[0]
        self.assertAlmostEqual(img.dpi, 300, delta=0.5)

    def test_mindestaufloesung(self):
        r = self.result("niedrigaufgeloest.eps")
        self.assertEqual(r.check("aufloesung").status, Status.FAIL)
        self.assertIn("unter 80 dpi", r.check("aufloesung").message)
        lax = check_file(self.dir / "niedrigaufgeloest.eps", Settings(gs_executable=GS, min_dpi=50))
        self.assertEqual(lax.check("aufloesung").status, Status.OK)

    def test_aufloesung_grenzwert_einstellbar(self):
        r = check_file(self.dir / "ok.eps", Settings(gs_executable=GS, max_dpi=120))
        self.assertEqual(r.check("aufloesung").status, Status.FAIL)

    def test_verknuepfung(self):
        self.assertEqual(self.status("verknuepft_opi.eps", "eingebettet"), Status.FAIL)
        self.assertEqual(self.status("ok.eps", "eingebettet"), Status.OK)

    def test_ueberdrucken(self):
        self.assertEqual(self.status("ueberdrucken.eps", "ueberdrucken"), Status.FAIL)

    def test_hintergrund(self):
        # Fläche muss nicht die ganze BoundingBox füllen
        for name in ("hintergrund_pfad.eps", "hintergrund_zu_klein.eps", "hintergrund_teilflaeche.eps", "ok.eps"):
            with self.subTest(name=name):
                self.assertEqual(self.status(name, "hintergrund"), Status.OK)
        self.assertIn("75 %", " ".join(self.result("hintergrund_zu_klein.eps").check("hintergrund").details))
        # Warnung: keine Fläche unten bzw. Fläche mit Transparenz
        for name in ("hintergrund_bild.eps", "hintergrund_transparent.eps", "ohne_flaeche.eps"):
            with self.subTest(name=name):
                self.assertEqual(self.status(name, "hintergrund"), Status.WARN)

    def test_postscript_fehler(self):
        self.assertEqual(self.status("postscript_fehler.eps", "datei"), Status.FAIL)

    def test_nicht_eingebettete_schrift(self):
        r = self.result("rgb_schwarz.eps")
        self.assertIn("Helvetica", r.analysis.missing_fonts)
        self.assertEqual(r.check("schriften").status, Status.FAIL)
        self.assertEqual(self.status("ok.eps", "schriften"), Status.OK)

    def test_kriterien_abwaehlen(self):
        s = Settings(gs_executable=GS, enabled=frozenset({"aufloesung"}))
        r = check_file(self.dir / "rgb_schwarz.eps", s)
        self.assertEqual([c.key for c in r.checks], ["datei", "aufloesung"])
        self.assertEqual(r.status, Status.OK)  # RGB-Schwarz und Schrift wurden nicht geprüft

    def test_dos_eps(self):
        r = self.result("dos_header.eps")
        self.assertTrue(r.info.has_dos_header)
        self.assertEqual(r.status, Status.OK)


class OrdnerTest(unittest.TestCase):
    def test_ordner_mit_und_ohne_unterordner(self):
        from eps_pruefer.cli import collect_files

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "Seite_2").mkdir()
            for name in ("b.eps", "A.EPS", "notiz.txt", "Seite_2/c.eps"):
                (root / name).write_text("%!PS-Adobe-3.0 EPSF-3.0\n")
            alle = [f.relative_to(root).as_posix() for f in collect_files([d])]
            self.assertEqual(alle, ["A.EPS", "b.eps", "Seite_2/c.eps"])
            flach = [f.name for f in collect_files([d], recursive=False)]
            self.assertEqual(flach, ["A.EPS", "b.eps"])
            einzeln = collect_files([str(root / "b.eps")])
            self.assertEqual(einzeln, [root / "b.eps"])


class EpsFileTest(unittest.TestCase):
    def test_bbox_atend_und_verknuepfungen(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.eps"
            p.write_bytes(
                b"%!PS-Adobe-3.0 EPSF-3.0\r%%BoundingBox: (atend)\r"
                b"%%DocumentSuppliedResources: procset Test\r%%+ file eingebettet.eps\r"
                b"%%DocumentNeededResources: font Helvetica\r%%+ file extern.tif\r"
                b"%%EndComments\r%%Trailer\r%%BoundingBox: 1 2 3 4\r%%EOF\r"
            )
            info = read_eps(p)
            self.assertEqual(str(info.bbox), "1 2 3 4")
            self.assertEqual(info.links, ["Benötigte externe Datei: extern.tif"])


if __name__ == "__main__":
    unittest.main()
