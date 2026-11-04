# Plan: QR-Code-Austausch in EPS-Anzeigen

Stand: 04.11.2026 · Priorität: dringend

## Ausgangslage

- Mehrere hundert Anzeigen (EPS) enthalten einen QR-Code, der ersetzt werden muss. Das Problem wurde nicht von uns verursacht.
- Die neuen QR-Codes liegen als **vektorisierte PDFs** vor.
- Die Bearbeitung findet in **Adobe Illustrator** statt.

## Festgelegte Vorgaben

| Punkt | Entscheidung |
|---|---|
| Dateiformat Anzeigen | EPS |
| Neue Codes | Vektor-PDF |
| Farbe neuer Code | an den alten Code der jeweiligen Anzeige angepasst, **immer CMYK** |
| Lage/Größe | wie der alte Code |
| Originaldatei | **darf überschrieben werden** (Sicherung nach `_original/` bleibt für die Prüfung) |
| Auswahl der Dateien | über eine **Liste der betroffenen Kunden**. Die Automatik sucht die Ordner selbst. |
| Pfad- und Ausleseregeln | **werden vom Auftraggeber vorgegeben** (noch offen, siehe unten) |

## Ablauf (Zielbild)

### Schritt 1: Suchlauf (verändert nichts)

- **Eingabe:** Kundenliste (Excel/CSV) und Pfad- und Ausleseregeln (Konfigurationsdatei).
- **Verarbeitung:** Für jeden Kunden wird nach den Regeln der Ordnerpfad gebaut. Dann werden die betroffenen EPS und die zugehörige neue QR-PDF gesucht und die nötigen Daten ausgelesen.
- **Ausgabe:** `auftraege.csv` mit Kunde, EPS-Pfad, QR-PDF-Pfad, Soll-URL (falls vorhanden) und Status:
  - `gefunden`
  - `nicht gefunden`: Ordner oder Datei fehlt.
  - `mehrdeutig`: mehrere Treffer oder Regel nicht eindeutig.
- **Freigabe:** Der Mensch sieht die Auftragsliste durch. Nur Zeilen mit `gefunden` werden weiterverarbeitet. Nicht eindeutige Fälle werden nie automatisch bearbeitet.

### Schritt 2: Tausch in Illustrator (`qr_tausch.jsx`)

Das Skript arbeitet die freigegebene `auftraege.csv` Zeile für Zeile ab. Je Datei:

1. EPS öffnen und den alten QR-Code finden: ein Objekt mit dem Namen „QR…“ oder automatisch das kleinste quadratische Objekt mit ≥ 40 gleichfarbigen Modulen.
2. Farbe des alten Codes lesen und nach CMYK umrechnen (Volltonfarbe, RGB, Lab und Grau werden umgerechnet).
3. Neue QR-PDF als Vektor einfügen, auf die Modulfläche des alten Codes skalieren und positionieren, in der CMYK-Farbe einfärben.
4. Alten Code löschen. Ein weißer Hintergrund bzw. eine Ruhezone des alten Codes bleibt erhalten.
5. Original nach `_original/` kopieren und die EPS überschreiben.
6. Status in die Auftragsliste bzw. das Protokoll schreiben: `OK`, `MANUELL` oder `FEHLER`. Bei `MANUELL` bleibt die Datei unverändert, z. B. weil der Code ein Pixelbild ist oder nicht eindeutig gefunden wurde.

Optionen: `TROCKENLAUF` (nur erkennen, nichts speichern), EPS-Speicheroptionen in `epsOptions()`.

### Schritt 3: Prüfung (`pruefen.py`, unabhängig von Illustrator)

Original (`_original/`) und Ergebnis werden mit Ghostscript in CMYK gerendert. Dann wird je Anzeige geprüft:

1. Der neue Code ist lesbar, und sein Inhalt ist identisch mit dem der QR-PDF (bzw. der Soll-URL aus der Liste).
2. Der alte Inhalt ist nicht mehr vorhanden, weder als Code noch als Text in der EPS.
3. Lage und Größe entsprechen dem alten Code (Toleranz 0,3 mm).
4. Die Modulfarbe entspricht der alten (CMYK, Toleranz 2 %).
5. Außerhalb des QR-Bereichs gibt es keine Pixeländerung.
6. Das Format (BoundingBox) ist unverändert.

Ausgabe: `bericht.html` (Vorher/Nachher-Vorschau, Fehler oben) und `bericht.csv`, künftig gruppiert nach Kunde.

### Schritt 4: Freigabe durch Menschen

- Bericht durchsehen und Stichproben in Illustrator öffnen.
- Einige Anzeigen in Originalgröße drucken und mit mehreren Handys scannen.
- Danach kann `_original/` gelöscht werden.

## Stand der Umsetzung

| Baustein | Status |
|---|---|
| `qr_tausch.jsx`: Tausch mit Ordnerauswahl und Zuordnung per Dateiname/`zuordnung.csv` | geschrieben, **noch nicht in Illustrator getestet** |
| `pruefen.py`: unabhängige Prüfung mit HTML/CSV-Bericht | geschrieben, an synthetischen Testdateien getestet: erkennt Verschiebung, falsche Farbe, nicht getauschten Code und Änderungen außerhalb |
| `ANLEITUNG.md`: Bedienung | vorhanden |
| Suchlauf über die Kundenliste (Schritt 1) | **offen**, wartet auf Pfadregeln |
| Umstellung von `qr_tausch.jsx` und `pruefen.py` auf `auftraege.csv` | **offen** |

## Offene Punkte (vom Auftraggeber zu liefern)

1. **Kundenliste:** Format (Excel/CSV), Spalten, Auszug mit einigen Zeilen.
2. **Pfadregel:** Startordner (z. B. `\\server\Kunden\` oder `/Volumes/…`), Aufbau (z. B. `{Kundennr}_{Name}/Anzeigen/{Jahr}/`), wie streng die Regel gilt (exakt oder „beginnt mit Kundennummer“).
3. **Dateiauswahl im Ordner:**
   - alle EPS, bestimmte Namensmuster oder nur die neueste Version
   - Unterordner einbeziehen?
   - Ausschlüsse (z. B. „alt“, „Archiv“)
4. **Neuer QR-Code je Kunde:** Liegt er im Kundenordner, in einem zentralen Ordner mit Kundennummer im Dateinamen oder steht er als Spalte in der Liste?
5. **Weitere auszulesende Daten:** z. B. die Soll-URL aus der Liste, für einen zusätzlichen Abgleich.
6. **Arbeitsplatz:** Mac oder Windows, Illustrator-Version, ist das Kunden-Laufwerk eingebunden?
7. **EPS-Speicheroptionen:** aktuell Illustrator CC (17), CMYK-PostScript, Schriften eingebettet. Gibt es abweichende Vorgaben?
8. **2 bis 3 echte Beispiele:** Kunde, vollständiger Pfad, EPS und QR-PDF, zum Abstimmen der automatischen Erkennung.

## Nächste Schritte

1. Pfad- und Ausleseregeln sowie Beispiele erhalten.
2. Suchlauf bauen, `auftraege.csv` erzeugen und die Trefferquote auswerten. Regeln nachschärfen.
3. `qr_tausch.jsx` und `pruefen.py` auf die Auftragsliste umstellen.
4. Testlauf mit den Beispielen in Illustrator (erst `TROCKENLAUF`, dann echt), danach Prüfung.
5. Gesamtlauf, dann Prüfung, dann Stichprobe mit Testdruck und Scan per Handy.

## Dateien in diesem Ordner

- `PLAN.md`: dieser Plan
- `ANLEITUNG.md`: Bedienungsanleitung
- `qr_tausch.jsx`: Illustrator-Skript (ExtendScript)
- `pruefen.py`: Prüfwerkzeug (Python; benötigt Ghostscript, zbar, numpy, pillow, opencv-python-headless)
