# EPS-Prüfer – Druckproduktion & Anzeigensatz

Desktop-Programm für Windows, das EPS-Dateien vor der Druckproduktion bzw. dem
Anzeigensatz prüft. Die Dateien werden wirklich ausgeführt (mit Ghostscript) und
jeder Malvorgang wird protokolliert. Das Programm liest also nicht nur die Kommentare
im Dateikopf aus.

| Prüfung | Fehler, wenn … |
|---|---|
| **Schwarz in CMYK** | ein schwarzer Wert als RGB angelegt ist (R, G und B ≤ 20 %), in Flächen, Konturen, Texten, Mustern, Verläufen oder Strichbildern |
| **Pixeldaten eingebettet** | die Datei Bilder nur verknüpft (OPI `%%ImageFileName`/`%ALDImageFileName`, DCS-Farbauszugsdateien, `%%IncludeFile`, `%%DocumentNeededFiles` …) |
| **Auflösung ≤ 150 dpi** | ein Bild eine effektive Auflösung über dem Grenzwert hat (Pixel ÷ platzierte Größe, Skalierung und Drehung sind berücksichtigt) |
| **Kein Überdrucken** | irgendein Objekt beim Malen auf Überdrucken steht (`setoverprint true`) |
| **Hintergrundfläche** | das unterste gemalte Objekt keine Farbfläche ist, nicht die ganze BoundingBox abdeckt, auf Überdrucken steht oder weniger als 100 % Deckkraft hat |

Zusätzlich gibt es **Warnungen** für andere RGB-Farben, RGB-Bilder, Schwarz als
Graustufe (statt CMYK), nicht eingebettete Schriften, PostScript-Fehler und fehlende
BoundingBox. In den Einstellungen kann man RGB-Farben und Graustufen-Schwarz
auch als Fehler werten lassen. Der dpi-Grenzwert ist dort ebenfalls einstellbar.

---

## Installation (einmalig)

1. **Projekt ablegen** unter `C:\ZWISCHENSPEICHER\Claude\Projekte\eps-pruefer`.
   Zwei Möglichkeiten:
   ```bat
   cd /d C:\ZWISCHENSPEICHER\Claude\Projekte
   git clone -b claude/eps-validierung-druck-iuo8wi https://github.com/B3trom/B3trom.git B3trom
   ```
   Der Ordner `B3trom\eps-pruefer` ist dann das Programm. Alternativ lädt man das
   Repository auf GitHub als ZIP herunter und kopiert den Ordner `eps-pruefer` dorthin.
2. **Python 3.10 oder neuer** installieren: <https://www.python.org/downloads/>.
   Dabei „Add python.exe to PATH“ anhaken. Weitere Python-Pakete sind nicht nötig.
3. **Ghostscript** (kostenlos) installieren: <https://ghostscript.com/releases/gsdnld.html>,
   „Ghostscript AGPL Release“ für Windows 64 bit. Der Prüfer findet `gswin64c.exe`
   unter `C:\Program Files\gs\…` automatisch. Liegt es woanders, gibt man den Pfad
   im Programm unter *Einstellungen → Ghostscript → Ändern …* an.

## Benutzung

- **Doppelklick auf `start.bat`** öffnet das Programm.
- EPS-Dateien oder ganze Ordner über die Schaltflächen hinzufügen. Man kann sie auch
  im Explorer direkt **auf `start.bat` ziehen**, dann wird sofort geprüft.
- **▶ Prüfen** startet die Prüfung. Grün heißt OK, gelb Warnung, rot Fehler.
- Ein Klick auf eine Zeile zeigt unten die Details mit Farbwerten und Positionen
  (in Punkt, vom Ursprung der EPS aus).
- Ein Doppelklick öffnet den Ordner der Datei im Explorer.
- **Bericht speichern …** schreibt einen HTML-Bericht (z. B. für den Kunden), eine
  CSV-Datei (Excel) oder eine Textdatei.

Optional: Mit `py -m pip install tkinterdnd2` kann man Dateien auch direkt in die
Liste ziehen.

### Kommandozeile / Stapelbetrieb

```bat
pruefen_cli.bat "D:\Anzeigen\KW40" --html bericht.html --csv bericht.csv
pruefen_cli.bat anzeige.eps --max-dpi 200 --rgb-fehler
```
Bei Fehlern ist der Rückgabewert 1, sonst 0. Das eignet sich z. B. für Hotfolder-Skripte.

### Als eigenständige .exe

`build_exe.bat` baut mit PyInstaller die Datei `dist\EPS-Pruefer.exe`. Sie läuft
ohne Python-Installation. Ghostscript muss auf dem Zielrechner trotzdem
installiert sein.

---

## So wird geprüft

Die EPS wird nicht direkt, sondern hinter einem eigenen PostScript-Prolog
(`eps_pruefer/probe.py`) in Ghostscript ausgeführt. Der Prolog ersetzt alle malenden
Operatoren (`fill`, `stroke`, `show`, `image`, `colorimage`, `imagemask`, `shfill`,
`rectfill` …). Vor jedem Malvorgang schreibt er Farbraum, Farbwerte, Überdrucken,
Deckkraft, Ausdehnung und bei Bildern die effektive Auflösung ins Protokoll.

- Das funktioniert auch mit den per `bind` gebundenen Prologen von Illustrator,
  FreeHand, QuarkXPress usw.
- Objekte innerhalb von Mustern und Type-3-Schriften werden mitgeprüft, zählen
  aber nicht als „unterstes Objekt“.
- DOS-EPS mit TIFF/WMF-Vorschau werden unterstützt.
- Ghostscript läuft im abgesicherten Modus (`-dSAFER`). Die Daten gehen über die
  Standardeingabe an Ghostscript, daher sind Umlaute in Pfaden kein Problem.

### Grenzen, die man kennen sollte

- **Deckkraft:** PostScript/EPS kennt keine echte Transparenz. Programme wie
  Illustrator reduzieren Transparenz beim EPS-Export. Geprüft wird deshalb:
  unterstes Objekt ist eine Fläche, nicht auf Überdrucken, kein
  `SetTransparency`-pdfmark davor, Ghostscript-Alpha = 100 %.
- **Abdeckung der Hintergrundfläche:** Verglichen wird das umschließende Rechteck
  der Fläche (geschnitten mit dem Beschneidungspfad) mit der (HiRes-)BoundingBox,
  Toleranz 1 pt. Hat eine Fläche ein Loch (Even-Odd-Füllung), gibt es eine Warnung.
- **RGB-Bilder:** Die einzelnen Pixel werden nicht auf Schwarz untersucht. Ein
  RGB-Bild wird als Ganzes gemeldet (Warnung bzw. Fehler, je nach Einstellung).
- **Schwarz-Schwelle:** Als „Schwarz“ gilt RGB, wenn alle Kanäle ≤ 20 % (≤ 51 von 255)
  sind, bzw. Grau mit ≤ 20 % Helligkeit. Einstellbar in `eps_pruefer/checks.py`
  (`BLACK_THRESHOLD`).

## Entwicklung

```bat
py -m unittest discover -s tests -v
py tests\make_samples.py tests\beispiele
```
`make_samples.py` erzeugt Beispieldateien für jeden Fehlerfall, zum Ausprobieren
in der Oberfläche.

Aufbau:

| Datei | Inhalt |
|---|---|
| `eps_pruefer/probe.py` | PostScript-Prolog (Protokollierung in Ghostscript) |
| `eps_pruefer/epsfile.py` | EPS einlesen, DOS-Header, DSC-Kommentare, Verknüpfungen |
| `eps_pruefer/analyzer.py` | Ghostscript-Aufruf und Auswertung des Protokolls |
| `eps_pruefer/checks.py` | Prüfregeln und Grenzwerte |
| `eps_pruefer/gui.py` | Oberfläche (Tkinter) |
| `eps_pruefer/report.py` | HTML-/CSV-/Text-Bericht |
| `eps_pruefer/cli.py` | Kommandozeile |
