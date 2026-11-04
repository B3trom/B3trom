/*
 * qr_tausch.jsx  –  QR-Code in EPS-Anzeigen per Stapelverarbeitung austauschen
 * Adobe Illustrator (ExtendScript). Start: Datei > Skripte > Anderes Skript …
 *
 * Ablauf pro Anzeige:
 *   1. EPS öffnen, alten QR-Code finden (Objektname "QR" oder automatische Erkennung)
 *   2. Farbe des alten Codes lesen und nach CMYK umrechnen
 *   3. Neuen QR-Code (Vektor-PDF) einfügen, auf die Modulfläche des alten skalieren,
 *      alle Module in der CMYK-Farbe einfärben
 *   4. Alten Code löschen, EPS überschreiben (Sicherung nach _original/)
 *   5. Ergebnis in qr_tausch_log.csv protokollieren
 *
 * Zuordnung Anzeige -> neuer Code (in dieser Reihenfolge):
 *   a) zuordnung.csv im QR-Ordner:  anzeige.eps;qr.pdf   (eine Zeile pro Anzeige)
 *   b) gleicher Dateiname:  Anzeige_123.eps  <->  Anzeige_123.pdf
 *   c) liegt genau EINE PDF im QR-Ordner, gilt sie für alle Anzeigen
 */

#target illustrator

// ---------------------------------------------------------------- Einstellungen
var CFG = {
    BACKUP_ORIGINALE: true,   // Original vor dem Überschreiben nach _original/ kopieren (für die Prüfung nötig)
    MIN_MODULE: 40,           // so viele dunkle Teilpfade muss ein Objekt mindestens haben, um als QR zu gelten
    QUADRAT_TOLERANZ: 0.08,   // max. Abweichung Breite/Höhe (8 %)
    WEISS_IM_NEUEN_LOESCHEN: true, // weiße Flächen (Hintergrund) aus dem neuen Code entfernen
    TROCKENLAUF: false        // true = nichts speichern, nur erkennen und protokollieren
};
// ------------------------------------------------------------------------------

var log = [];

function main() {
    var adFolder = Folder.selectDialog("Ordner mit den EPS-Anzeigen wählen");
    if (!adFolder) return;
    var qrFolder = Folder.selectDialog("Ordner mit den neuen QR-Codes (PDF) wählen");
    if (!qrFolder) return;

    var mapping = readMapping(qrFolder);
    var qrFiles = qrFolder.getFiles(function (f) { return f instanceof File && /\.pdf$/i.test(f.name); });
    var ads = adFolder.getFiles(function (f) { return f instanceof File && /\.eps$/i.test(f.name); });
    if (!ads.length) { alert("Keine EPS-Dateien gefunden."); return; }

    var backupFolder = new Folder(adFolder.fsName + "/_original");
    if (CFG.BACKUP_ORIGINALE && !CFG.TROCKENLAUF && !backupFolder.exists) backupFolder.create();

    var oldUIL = app.userInteractionLevel;
    app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS;

    var ok = 0, fail = 0;
    for (var i = 0; i < ads.length; i++) {
        var res = processAd(ads[i], qrFolder, qrFiles, mapping, backupFolder);
        log.push(res);
        if (res.status === "OK") ok++; else fail++;
    }

    app.userInteractionLevel = oldUIL;
    writeLog(adFolder);
    alert("Fertig.\nOK: " + ok + "\nManuell prüfen / Fehler: " + fail +
          "\n\nProtokoll: " + adFolder.fsName + "/qr_tausch_log.csv");
}

function processAd(adFile, qrFolder, qrFiles, mapping, backupFolder) {
    var r = { datei: decodeURI(adFile.name), qr: "", status: "", grund: "", farbe: "",
              alt_x: "", alt_y: "", alt_b: "", alt_h: "" };
    var doc = null;
    try {
        var qrFile = findQrFor(adFile, qrFolder, qrFiles, mapping);
        if (!qrFile) { r.status = "FEHLER"; r.grund = "kein neuer QR-Code zugeordnet"; return r; }
        r.qr = decodeURI(qrFile.name);

        doc = app.open(adFile);

        var cand = findOldQr(doc);
        if (cand.error) { r.status = "MANUELL"; r.grund = cand.error; doc.close(SaveOptions.DONOTSAVECHANGES); return r; }

        var old = cand.item;
        var darkB = cand.darkBounds; // [l, t, r, b]
        r.alt_x = fmt(darkB[0]); r.alt_y = fmt(darkB[1]);
        r.alt_b = fmt(darkB[2] - darkB[0]); r.alt_h = fmt(darkB[1] - darkB[3]);

        var cmyk = toCMYK(cand.color);
        if (!cmyk) { r.status = "MANUELL"; r.grund = "Farbe des alten Codes nicht lesbar"; doc.close(SaveOptions.DONOTSAVECHANGES); return r; }
        r.farbe = "C" + fmt(cmyk.cyan) + " M" + fmt(cmyk.magenta) + " Y" + fmt(cmyk.yellow) + " K" + fmt(cmyk.black);

        // Ebene ggf. entsperren
        var layer = old.layer, wasLocked = layer.locked, wasHidden = !layer.visible;
        layer.locked = false; layer.visible = true;

        // neuen Code einfügen
        var neu = doc.groupItems.createFromFile(qrFile);
        neu.move(old, ElementPlacement.PLACEBEFORE);

        var whites = [];
        recolor(neu, cmyk, whites);
        if (CFG.WEISS_IM_NEUEN_LOESCHEN) for (var w = whites.length - 1; w >= 0; w--) whites[w].remove();

        var nb = darkBoundsOf(neu);
        if (!nb) { r.status = "FEHLER"; r.grund = "neuer Code enthält keine dunklen Flächen"; doc.close(SaveOptions.DONOTSAVECHANGES); return r; }

        // skalieren: dunkle Fläche neu = dunkle Fläche alt
        var sx = (darkB[2] - darkB[0]) / (nb[2] - nb[0]) * 100;
        var sy = (darkB[1] - darkB[3]) / (nb[1] - nb[3]) * 100;
        neu.resize(sx, sy, true, true, true, true, 100, Transformation.TOPLEFT);
        nb = darkBoundsOf(neu);
        neu.translate(darkB[0] - nb[0], darkB[1] - nb[1]);

        // alten Code entfernen (weißer Hintergrund/Ruhezone des alten bleibt erhalten)
        removeOld(cand);
        neu.name = "QR";

        layer.locked = wasLocked; layer.visible = !wasHidden;

        if (!CFG.TROCKENLAUF) {
            if (CFG.BACKUP_ORIGINALE) {
                var bk = new File(backupFolder.fsName + "/" + adFile.name);
                if (!bk.exists) adFile.copy(bk);   // nie eine bestehende Sicherung überschreiben
            }
            doc.saveAs(adFile, epsOptions());
        }
        doc.close(SaveOptions.DONOTSAVECHANGES);
        r.status = "OK";
        if (cand.hinweis) r.grund = cand.hinweis;
    } catch (e) {
        r.status = "FEHLER"; r.grund = "Skriptfehler: " + e.message + " (Zeile " + e.line + ")";
        try { if (doc) doc.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {}
    }
    return r;
}

// ------------------------------------------------------------ alten QR finden
function findOldQr(doc) {
    // 1) explizit benanntes Objekt "QR"
    for (var i = 0; i < doc.pageItems.length; i++) {
        var it = doc.pageItems[i];
        if (/^qr/i.test(it.name)) {
            var info = analyse(it);
            if (info.count > 0) return { item: it, darkBounds: info.bounds, color: info.color, parts: info, hinweis: "per Objektname gefunden" };
        }
    }
    // 2) automatische Erkennung: kleinstes nahezu quadratisches Objekt mit vielen dunklen Modulen
    var best = null, bestArea = 1e12, rasterHit = false;
    var items = doc.pageItems;
    for (var j = 0; j < items.length; j++) {
        var p = items[j];
        if (p.typename === "RasterItem" || p.typename === "PlacedItem") {
            if (isSquare(p.geometricBounds)) rasterHit = true;
            continue;
        }
        if (p.typename !== "GroupItem" && p.typename !== "CompoundPathItem") continue;
        if (p.hidden) continue;
        var a = analyse(p);
        if (a.count < CFG.MIN_MODULE || !a.bounds || !isSquare(a.bounds)) continue;
        if (!a.uniform) continue; // QR-Module haben genau eine Farbe
        var area = (a.bounds[2] - a.bounds[0]) * (a.bounds[1] - a.bounds[3]);
        // gleiche Fläche (verschachtelte Gruppen): die innere nehmen
        if (area < bestArea - 0.01 || (Math.abs(area - bestArea) < 0.01)) { best = { item: p, darkBounds: a.bounds, color: a.color, parts: a }; bestArea = area; }
    }
    if (best) return best;
    if (rasterHit) return { error: "QR-Code ist vermutlich ein Pixelbild/verknüpfte Datei – bitte manuell" };
    return { error: "kein QR-Code erkannt" };
}

// sammelt dunkle und helle gefüllte Pfade, Bounds der dunklen, Einheitlichkeit der Farbe
function analyse(item) {
    var res = { count: 0, bounds: null, color: null, uniform: true, dark: [], light: [] };
    walk(item, function (path) {
        if (!path.filled || path.clipping) return;
        if (isLight(path.fillColor)) { res.light.push(path); return; }
        res.count++;
        res.dark.push(path);
        var key = colorKey(path.fillColor);
        if (!res.color) { res.color = path.fillColor; res.key = key; }
        else if (key !== res.key) res.uniform = false;
        res.bounds = union(res.bounds, path.geometricBounds);
    });
    return res;
}

function removeOld(cand) {
    var a = cand.parts, it = cand.item;
    // gibt es eine große helle Fläche (Hintergrund/Ruhezone)? -> behalten, nur dunkle Module löschen
    var keepBg = false;
    var db = a.bounds, dArea = (db[2] - db[0]) * (db[1] - db[3]);
    for (var i = 0; i < a.light.length; i++) {
        var b = a.light[i].geometricBounds;
        if ((b[2] - b[0]) * (b[1] - b[3]) >= dArea * 0.8) { keepBg = true; break; }
    }
    if (!keepBg || it.typename === "CompoundPathItem") { it.remove(); return; }
    // nur dunkle Pfade und kleine helle Pfade entfernen
    for (var d = a.dark.length - 1; d >= 0; d--) removePathOrCompound(a.dark[d]);
    for (var l = a.light.length - 1; l >= 0; l--) {
        var lb = a.light[l].geometricBounds;
        if ((lb[2] - lb[0]) * (lb[1] - lb[3]) < dArea * 0.8) removePathOrCompound(a.light[l]);
    }
}

function removePathOrCompound(p) {
    try {
        if (p.parent && p.parent.typename === "CompoundPathItem") p.parent.remove(); else p.remove();
    } catch (e) {} // schon mit dem Compound entfernt
}

// --------------------------------------------------------------- neuer Code
function recolor(item, cmyk, whites) {
    walk(item, function (path) {
        if (path.clipping) return;
        if (path.filled) {
            if (isLight(path.fillColor)) { whites.push(path); return; }
            path.fillColor = cmyk;
        }
        if (path.stroked && !isLight(path.strokeColor)) path.strokeColor = cmyk;
    });
}

function darkBoundsOf(item) {
    var b = null;
    walk(item, function (path) {
        if (path.filled && !path.clipping && !isLight(path.fillColor)) b = union(b, path.geometricBounds);
    });
    return b;
}

// ------------------------------------------------------------------ Farben
function toCMYK(c) {
    if (!c) return null;
    var out = new CMYKColor();
    switch (c.typename) {
        case "CMYKColor":
            out.cyan = c.cyan; out.magenta = c.magenta; out.yellow = c.yellow; out.black = c.black; return out;
        case "SpotColor":
            var base = toCMYK(c.spot.color);
            if (!base) return null;
            var t = c.tint / 100;
            out.cyan = base.cyan * t; out.magenta = base.magenta * t; out.yellow = base.yellow * t; out.black = base.black * t;
            return out;
        case "GrayColor":
            out.cyan = 0; out.magenta = 0; out.yellow = 0; out.black = c.gray; return out;
        case "RGBColor":
            var v = app.convertSampleColor(ImageColorSpace.RGB, [c.red, c.green, c.blue], ImageColorSpace.CMYK, ColorConvertPurpose.defaultpurpose);
            out.cyan = v[0]; out.magenta = v[1]; out.yellow = v[2]; out.black = v[3]; return out;
        case "LabColor":
            var l = app.convertSampleColor(ImageColorSpace.LAB, [c.l, c.a, c.b], ImageColorSpace.CMYK, ColorConvertPurpose.defaultpurpose);
            out.cyan = l[0]; out.magenta = l[1]; out.yellow = l[2]; out.black = l[3]; return out;
    }
    return null; // Verlauf, Muster usw.
}

function isLight(c) {
    if (!c) return true;
    switch (c.typename) {
        case "NoColor": return true;
        case "CMYKColor": return c.cyan + c.magenta + c.yellow + c.black < 3;
        case "GrayColor": return c.gray < 3;
        case "RGBColor": return c.red > 250 && c.green > 250 && c.blue > 250;
        case "SpotColor": return c.tint < 3 || isLight(c.spot.color);
    }
    return false;
}

function colorKey(c) {
    switch (c.typename) {
        case "CMYKColor": return "cmyk" + [r1(c.cyan), r1(c.magenta), r1(c.yellow), r1(c.black)].join(",");
        case "SpotColor": return "spot" + c.spot.name + c.tint;
        case "GrayColor": return "gray" + r1(c.gray);
        case "RGBColor": return "rgb" + [r1(c.red), r1(c.green), r1(c.blue)].join(",");
    }
    return c.typename;
}

// ------------------------------------------------------------------ Helfer
function walk(item, fn) {
    switch (item.typename) {
        case "PathItem": fn(item); break;
        case "CompoundPathItem":
            for (var i = 0; i < item.pathItems.length; i++) fn(item.pathItems[i]);
            break;
        case "GroupItem":
            for (var j = 0; j < item.pageItems.length; j++) walk(item.pageItems[j], fn);
            break;
    }
}

function union(a, b) {
    if (!a) return [b[0], b[1], b[2], b[3]];
    return [Math.min(a[0], b[0]), Math.max(a[1], b[1]), Math.max(a[2], b[2]), Math.min(a[3], b[3])];
}

function isSquare(b) {
    var w = b[2] - b[0], h = b[1] - b[3];
    if (w <= 0 || h <= 0) return false;
    return Math.abs(w / h - 1) <= CFG.QUADRAT_TOLERANZ;
}

function readMapping(qrFolder) {
    var map = {}, f = new File(qrFolder.fsName + "/zuordnung.csv");
    if (!f.exists) return map;
    f.encoding = "UTF-8"; f.open("r");
    while (!f.eof) {
        var line = f.readln().replace(/^﻿/, "");
        var parts = line.split(/[;,\t]/);
        if (parts.length >= 2 && /\.eps\s*$/i.test(parts[0])) map[trim(parts[0]).toLowerCase()] = trim(parts[1]);
    }
    f.close();
    return map;
}

function findQrFor(adFile, qrFolder, qrFiles, mapping) {
    var name = decodeURI(adFile.name);
    var m = mapping[name.toLowerCase()];
    if (m) { var f = new File(qrFolder.fsName + "/" + m); return f.exists ? f : null; }
    var same = new File(qrFolder.fsName + "/" + name.replace(/\.eps$/i, ".pdf"));
    if (same.exists) return same;
    if (qrFiles.length === 1) return qrFiles[0];
    return null;
}

function epsOptions() {
    var o = new EPSSaveOptions();
    o.cmykPostScript = true;
    o.embedAllFonts = true;
    o.embedLinkedFiles = true;
    o.includeDocumentThumbnails = true;
    o.preview = EPSPreview.COLORTIFF;
    o.compatibility = Compatibility.ILLUSTRATOR17; // CC; bei Bedarf anpassen
    o.postScript = EPSPostScriptLevelEnum.LEVEL3;
    return o;
}

function writeLog(folder) {
    var f = new File(folder.fsName + "/qr_tausch_log.csv");
    f.encoding = "UTF-8"; f.open("w");
    f.writeln("﻿datei;qr_datei;status;grund;farbe_cmyk;alt_x_pt;alt_y_pt;alt_breite_pt;alt_hoehe_pt");
    for (var i = 0; i < log.length; i++) {
        var r = log[i];
        f.writeln([r.datei, r.qr, r.status, r.grund, r.farbe, r.alt_x, r.alt_y, r.alt_b, r.alt_h].join(";"));
    }
    f.close();
}

function fmt(n) { return (Math.round(n * 100) / 100).toString().replace(".", ","); }
function r1(n) { return Math.round(n * 10) / 10; }
function trim(s) { return s.replace(/^\s+|\s+$/g, ""); }

main();
