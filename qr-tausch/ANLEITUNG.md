# QR-Code-Tausch in EPS-Anzeigen

Zwei Werkzeuge:

| Datei | Läuft wo | Aufgabe |
|---|---|---|
| `qr_tausch.jsx` | Adobe Illustrator (Mac/Win) | tauscht den QR-Code in allen EPS eines Ordners |
| `pruefen.py` | beliebiger Rechner mit Ghostscript + zbar + Python | prüft jede Datei unabhängig und erstellt einen Bericht |

## 1. Vorbereitung

- Ordner **Anzeigen** mit allen `.eps`.
- Ordner **QR** mit den neuen Codes als Vektor-PDF. Zuordnung, die erste passende gilt:
  1. `zuordnung.csv` im QR-Ordner, eine Zeile pro Anzeige: `Anzeige_123.eps;QR_123.pdf`
  2. gleicher Dateiname: `Anzeige_123.eps` ↔ `Anzeige_123.pdf`
  3. genau **eine** PDF im QR-Ordner: Sie gilt für alle Anzeigen.

## 2. Tausch in Illustrator

1. **Zuerst mit 3 bis 5 Dateien testen**, ggf. mit `TROCKENLAUF: true` oben im Skript (nur erkennen, nichts speichern).
2. Datei › Skripte › Anderes Skript… › `qr_tausch.jsx`, dann Anzeigen-Ordner und QR-Ordner wählen.
3. Das Skript arbeitet pro Datei so:
   - Es findet den alten Code: ein Objekt mit dem Namen „QR…“ oder automatisch das kleinste
     quadratische Objekt mit ≥ 40 gleichfarbigen Modulen.
   - Es liest die Farbe und setzt sie **immer als CMYK** (Volltonfarbe, RGB, Lab und Grau werden umgerechnet).
   - Es fügt den neuen Code als Vektor ein und bringt seine Module exakt auf die Fläche des alten Codes.
     Der weiße Hintergrund (Ruhezone) des alten Codes bleibt erhalten.
   - Es **überschreibt die EPS**. Vorher wird das Original nach `_original/` kopiert, denn die Prüfung braucht es.
     Nach erfolgreicher Prüfung kann der Ordner gelöscht werden.
4. Ergebnis: `qr_tausch_log.csv` im Anzeigen-Ordner, Status `OK`, `MANUELL` oder `FEHLER`.
   `MANUELL` heißt, das Skript hat bewusst nichts verändert, etwa weil der Code ein Pixelbild war
   oder nicht eindeutig gefunden wurde.

EPS-Speicheroptionen stehen in `epsOptions()`, Standard ist Illustrator CC (17), CMYK-PostScript, Schriften eingebettet.
Bitte an Ihre bisherigen Vorgaben anpassen.

## 3. Prüfung

```bash
# einmalig
sudo apt install ghostscript zbar-tools     # macOS: brew install ghostscript zbar
pip install numpy pillow opencv-python-headless

python3 pruefen.py --original Anzeigen/_original --neu Anzeigen --qr QR --bericht Bericht
```

Geprüft wird jede Anzeige:

1. Der neue Code ist lesbar, und sein Inhalt ist identisch mit dem der zugeordneten QR-PDF.
2. Der alte Inhalt ist nicht mehr vorhanden, weder als Code noch als Text in der Datei.
3. Lage und Größe entsprechen dem alten Code (Toleranz 0,3 mm).
4. Die Modulfarbe entspricht der alten (gerenderte CMYK-Werte, Toleranz 2 %).
5. Außerhalb des QR-Bereichs hat sich kein Pixel verändert.
6. Das Format (BoundingBox) ist unverändert.

Ergebnis: `Bericht/bericht.html` (Fehler oben, mit Vorher/Nachher-Vorschau) und `bericht.csv`.

## 4. Freigabe

- Zehn Anzeigen aus dem Bericht stichprobenartig in Illustrator öffnen.
- Einige in Originalgröße drucken und mit mehreren Handys scannen.
