# Briefing: Automatisierte Einladungsvorlage (InDesign)

Übergabe für eine neue Session. Projekt-Beispiel: *P25-600726 Overath, GC Der Lüderich, Terminal OF2025* (Sports2B).

## Ziel

Die bisherige Einladung bekommt eine neue, optisch sehr hochwertige und elegante Version. Daraus wird eine Vorlage, die für jedes neue Projekt halbautomatisch befüllt wird:

- Nur wenige Texte werden über eine **Eingabemaske** ausgetauscht.
- Der **QR-Code** wird per Dateiauswahl ausgetauscht.
- Die **Kundenlogos** (10 bis 80 Stück) werden auf **Seite 3 und 4** automatisch aus dem Kundenordner platziert, angeordnet und optisch angeglichen.

## Rahmenbedingungen

| Punkt | Vorgabe |
|---|---|
| Programm | Adobe InDesign |
| Ergebnis | eine `.indd` zum Weiterbearbeiten und eine **Druck-PDF mit allen Marken** (Schnitt-, Passer- und Anschnittmarken) |
| Druck | Papier, **CMYK** |
| Logos | 10 bis 80 pro Einladung, verteilt auf Seite 3 und 4, **keine** Hervorhebungen, alle gleichwertig |
| Wechselnde Texte | Titel, Datum, Ort, Uhrzeit, Ablauf, Kontakt |
| Markierung | In `VORLAGE.indd` sind alle austauschbaren Textstellen in **100 % Magenta** markiert. |
| QR-Code | austauschbar über eine Dateiauswahl |

## Dateien, die in die neue Session gehören

Lokal liegen sie unter `C:\ZWISCHENSPEICHER\Claude\Projekte\Einladungen`.

- [ ] `VORLAGE.indd`
- [ ] **`VORLAGE.idml`** (InDesign: Datei → Exportieren → InDesign Markup). Diese Datei kann Claude lesen und erzeugen, eine `.indd` dagegen nicht.
- [ ] `VORLAGE.pdf` als Ansicht
- [ ] die bisherige Einladung (PDF) als Referenz
- [ ] ein Beispiel-Kundenordner mit Logos, möglichst gemischt (quer, hoch, quadratisch, farbig, schwarz-weiß, Vektor und Pixel)
- [ ] CI-Vorgaben: Schriften, Farben, Logo von Sports2B bzw. dem Golfclub
- [ ] optional ein Titelbild (Golfplatz) mit geklärten Nutzungsrechten
- [ ] optional ein vorhandenes PDF-Preset der Druckerei

**Zugriff:** Läuft die neue Session als Claude Code lokal auf dem PC (Desktop-App), kann Claude den Ordner direkt lesen. Läuft sie in der Cloud, müssen die Dateien vorher hochgeladen werden, z. B. ins Repo `B3trom` unter `Einladungen/`.

## Vorgehen

### Phase 1: Analyse

- Bisherige Einladung und VORLAGE auswerten: Format, Seitenzahl, Raster, Typografie, Farben, Magenta-Stellen
- Feste und wechselnde Bestandteile trennen
- Logo-Bestand prüfen: Dateiformate, Auflösung, Farbraum (RGB oder CMYK), Weißraum

### Phase 2: Drei Designrichtungen zur Auswahl (vor jeder Umsetzung)

Jeweils mit Titelseite und einer Logo-Seite:

- **A – „Classic Club“:** Serifenschrift, viel Weißraum, feine Linien, gedecktes Grün mit Gold
- **B – „Modern Minimal“:** große Groteskschrift, klares Raster, eine Akzentfarbe
- **C – „Editorial Premium“:** großformatiges Bild, Typografie wie in einem Magazin, dunkle Logo-Seite mit hellen Logos

Erst nach Freigabe einer Richtung wird umgesetzt.

### Phase 3: Umsetzung als InDesign-Skript (`.jsx`) mit Eingabedialog

1. **Eingabemaske (ScriptUI)**
   - ein Feld je Magenta-Textstelle; das Skript findet die Stelle, ersetzt den Text und setzt die Farbe auf die richtige Textfarbe zurück
   - Dateiauswahl für den QR-Code (PDF, EPS, SVG oder PNG), platziert in einem benannten Rahmen
   - Ordnerauswahl für die Kundenlogos
2. **Logo-Satz auf Seite 3 und 4**
   - fest angelegte Raster für 10 bis 80 Logos, gestaffelt (z. B. 4×3 bis 8×10); das passende Raster wird automatisch gewählt und auf beide Seiten verteilt
   - eine unvollständige letzte Reihe wird mittig ausgerichtet
   - einheitlicher Schutzraum je Logo; Weißraum wird automatisch abgeschnitten
   - **Größe nach optischem Gewicht (Fläche)**, nicht nach Breite, damit breite und hohe Logos gleich stark wirken
   - Reihenfolge alphabetisch nach Dateinamen
3. **Ausgabe auf Knopfdruck**
   - `.indd` speichern, z. B. `P25-xxxxxx_Einladung.indd`
   - Druck-PDF als **PDF/X-4, CMYK**, 3 mm Anschnitt, Schnitt-, Passer- und Anschnittmarken
4. **Prüfbericht**: fehlende oder zu gering aufgelöste Logos (unter 300 ppi), RGB-Logos, übrig gebliebene Magenta-Stellen

### Phase 4: Test und Übergabe

- Test mit echten Kundenordnern (10, 40 und 80 Logos, auch mit problematischen Dateien)
- kurze Anleitung für das Team

## Voraussetzungen und offene Punkte

- [ ] InDesign-Version auf den Arbeitsplätzen (ideal: CC 2023 oder neuer)
- [ ] 100 % Magenta darf in der VORLAGE **nur** an den Textstellen zum Austauschen vorkommen.
- [ ] Anschnittzugabe und Marken laut Druckerei (Standard: 3 mm)
- [ ] fester Name für den Logo-Unterordner in jedem Projekt, z. B. `…\Einladung\Logos\`
- [ ] möglichst Vektor-Logos (SVG, PDF, EPS); Pixel-Logos mit mindestens 300 ppi in der Endgröße
- [ ] lizenzierte Schriften für alle Arbeitsplätze
- [ ] Sollen die Logos einheitlich eingefärbt werden (z. B. alle Grau oder Weiß) oder im Original farbig bleiben? Das hängt von der gewählten Designrichtung ab.

## Startanweisung für die neue Session

> Lies `Einladungen/BRIEFING_Einladungsvorlage.md`. Die Dateien liegen in `<Pfad>`. Starte mit Phase 1 (Analyse) und zeige mir danach die drei Designrichtungen zur Auswahl, bevor du etwas umsetzt.
