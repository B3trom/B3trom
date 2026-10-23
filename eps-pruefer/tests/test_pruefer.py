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

    def test_rgb_schwarz_nach_vielen_objekten(self):
        # früher füllten Graustufen-Objekte das Protokoll, bevor das RGB-Schwarz kam
        self.assertEqual(self.status("rgb_schwarz_spaet.eps", "schwarz"), Status.FAIL)

    def test_umgerechnetes_rgb_schwarz(self):
        self.assertEqual(self.status("schwarz_umgerechnet.eps", "schwarz"), Status.WARN)
        strict = check_file(self.dir / "schwarz_umgerechnet.eps", Settings(gs_executable=GS, rgb_is_error=True))
        self.assertEqual(strict.check("schwarz").status, Status.FAIL)
        self.assertIn("Mischschwarz", strict.check("schwarz").message)
        self.assertEqual(self.status("tiefschwarz.eps", "schwarz"), Status.OK)

    def test_rgb_ursprungsdokument(self):
        r = self.result("ai_rgb_dokument.eps")
        self.assertEqual(r.check("schwarz").status, Status.FAIL)
        self.assertIn("RGB-Farbmodus", r.check("schwarz").message)


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


class BereichTest(unittest.TestCase):
    STRUKTUR = (
        "01_Anzeigensatz/a1.eps",
        "01_Anzeigensatz/Seite_3/a2.EPS",
        "01_Anzeigensatz/Rollups/r1.eps",
        "01_Anzeigensatz/Seite_3/Roll-ups KW42/r2.eps",
        "01_Anzeigensatz/._a1.eps",  # Mac-Begleitdatei vom Netzlaufwerk
        "02 - Arbeitsdaten/w1.eps",
        "Freie Anzeigen 2026/f1.eps",
        "Anzeigenarchiv/x.eps",  # enthält "Anzeigen…", ist aber kein gesuchter Ordner
        "03_Produktionsvorbereitung/p1.eps",
        "Sonstiges/s1.eps",
        "lose.eps",
    )

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Ausgabe_42"
        for rel in self.STRUKTUR:
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text("%!PS-Adobe-3.0 EPSF-3.0\n")

    def tearDown(self):
        self._tmp.cleanup()

    def names(self, scope, root=None):
        from eps_pruefer.cli import collect_files

        return sorted(f.name for f in collect_files([str(root or self.root)], scope=scope))

    def test_bereiche(self):
        self.assertEqual(self.names("intern"), ["a1.eps", "a2.EPS"])
        self.assertEqual(self.names("extern"), ["f1.eps", "w1.eps"])
        self.assertEqual(self.names("produktion"), ["p1.eps"])
        self.assertEqual(len(self.names("komplett")), len(self.STRUKTUR) - 1)  # ohne ._-Datei

    def test_unterordner_von_anzeigensatz_gewaehlt(self):
        # Pfad wie Z:\01_PROJEKTE\05_CAR\P26-…_Feld\Anzeigensatz\Anzeigen – gewählt wird "Anzeigen"
        projekt = Path(self._tmp.name) / "P26-501113_Münchberg_ev. Kinder- und Jugendhilfe_Feld"
        for rel in ("Anzeigensatz/Anzeigen/heck.eps", "Anzeigensatz/Anzeigen/Rollups/r.eps"):
            (projekt / rel).parent.mkdir(parents=True, exist_ok=True)
            (projekt / rel).write_text("%!PS-Adobe-3.0 EPSF-3.0\n")
        anzeigen = projekt / "Anzeigensatz" / "Anzeigen"
        self.assertEqual(self.names("intern", anzeigen), ["heck.eps"])
        self.assertEqual(self.names("komplett", anzeigen), ["heck.eps", "r.eps"])
        self.assertEqual(self.names("extern", anzeigen), [])

    def test_ordner_direkt_gewaehlt(self):
        # wer direkt den Ordner "Anzeigensatz" wählt, bekommt bei "Intern" dessen Inhalt ohne Rollups
        self.assertEqual(self.names("intern", self.root / "01_Anzeigensatz"), ["a1.eps", "a2.EPS"])
        self.assertEqual(self.names("extern", self.root / "01_Anzeigensatz"), [])


class OrdnersucheTest(unittest.TestCase):
    def test_diagnose_und_dateien_ohne_endung(self):
        from eps_pruefer.cli import scan_folder

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "Anzeigen").mkdir()
            (root / "Anzeigen" / "mac_ohne_endung").write_bytes(b"%!PS-Adobe-3.0 EPSF-3.0\n")
            (root / "Anzeigen" / "notiz").write_bytes(b"kein EPS")
            (root / "Anzeigen" / "heck.pdf").write_bytes(b"%PDF-1.4")
            (root / "Anzeigen" / "._heck.eps").write_bytes(b"\x00")
            scan = scan_folder(root)
            self.assertEqual([f.name for f in scan.files], ["mac_ohne_endung"])
            self.assertEqual(scan.other_types[".pdf"], 1)
            self.assertIn("1× .pdf", scan.summary())
            self.assertIn("nicht lesbar", scan_folder(root / "gibt_es_nicht").summary())


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
