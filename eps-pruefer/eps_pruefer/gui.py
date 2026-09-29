"""Desktop-Oberfläche (Tkinter)."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .checks import CHECK_TITLES, FileResult, Settings, Status, check_file
from .cli import collect_files
from .ghostscript import find_ghostscript, ghostscript_version
from .report import CHECK_ORDER, text_report, write_csv, write_html

APP_TITLE = "EPS-Prüfer – Druck & Anzeigensatz"
EPS_TYPES = [("EPS-Dateien", "*.eps *.epsf *.EPS *.ai"), ("Alle Dateien", "*.*")]

ROW_COLORS = {
    Status.OK: "#e6f4ea",
    Status.INFO: "#f2f2f2",
    Status.WARN: "#fff4ce",
    Status.FAIL: "#fde2e1",
}
COLUMN_TITLES = {
    "datei": "Datei/PostScript",
    "schwarz": "Schwarz CMYK",
    "eingebettet": "Eingebettet",
    "aufloesung": "Auflösung",
    "ueberdrucken": "Überdrucken",
    "hintergrund": "Hintergrund",
}
TEXT_COLORS = {
    Status.OK: "#1a7f37",
    Status.INFO: "#666666",
    Status.WARN: "#9a6700",
    Status.FAIL: "#cf222e",
}


def _config_path() -> Path:
    base = os.environ.get("APPDATA") or os.path.join(Path.home(), ".config")
    return Path(base) / "EPS-Pruefer" / "config.json"


def load_config() -> dict:
    try:
        return json.loads(_config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    try:
        p = _config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


class App:
    def __init__(self, root: tk.Tk, initial_paths: list[str]):
        self.root = root
        self.cfg = load_config()
        self.files: list[Path] = []
        self.results: dict[Path, FileResult] = {}
        self.queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel = threading.Event()

        self.var_dpi = tk.DoubleVar(value=self.cfg.get("max_dpi", 150))
        self.var_rgb = tk.BooleanVar(value=self.cfg.get("rgb_is_error", False))
        self.var_gray = tk.BooleanVar(value=self.cfg.get("gray_black_is_error", False))
        self.gs_path = find_ghostscript(self.cfg.get("gs_executable"))
        self.var_gs = tk.StringVar()
        self.var_status = tk.StringVar(value="Dateien hinzufügen und „Prüfen“ klicken.")

        root.title(APP_TITLE)
        root.geometry(self.cfg.get("geometry", "1150x720"))
        root.minsize(800, 500)
        self._build()
        self._update_gs_label()
        self._enable_drop()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        if initial_paths:
            self.add_paths(initial_paths)
            root.after(300, self.start_check)
        elif not self.gs_path:
            root.after(300, self._warn_no_gs)

    # ------------------------------------------------------------------ UI
    def _build(self):
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Treeview", rowheight=24)
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

        bar = ttk.Frame(self.root, padding=(8, 8, 8, 4))
        bar.pack(fill="x")
        ttk.Button(bar, text="Dateien hinzufügen …", command=self.ask_files).pack(side="left")
        ttk.Button(bar, text="Ordner hinzufügen …", command=self.ask_folder).pack(side="left", padx=4)
        ttk.Button(bar, text="Entfernen", command=self.remove_selected).pack(side="left")
        ttk.Button(bar, text="Liste leeren", command=self.clear).pack(side="left", padx=4)
        self.btn_check = ttk.Button(bar, text="▶  Prüfen", style="Accent.TButton", command=self.start_check)
        self.btn_check.pack(side="left", padx=(16, 4))
        ttk.Button(bar, text="Bericht speichern …", command=self.save_report).pack(side="left")
        ttk.Button(bar, text="?", width=3, command=self.show_help).pack(side="right")

        opts = ttk.LabelFrame(self.root, text="Einstellungen", padding=(8, 4))
        opts.pack(fill="x", padx=8, pady=4)
        ttk.Label(opts, text="Max. Auflösung Pixeldaten:").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(opts, from_=36, to=2400, increment=1, width=6, textvariable=self.var_dpi).grid(
            row=0, column=1, sticky="w", padx=(4, 2))
        ttk.Label(opts, text="dpi").grid(row=0, column=2, sticky="w", padx=(0, 20))
        ttk.Checkbutton(opts, text="Alle RGB-Farben/-Bilder als Fehler werten",
                        variable=self.var_rgb).grid(row=0, column=3, sticky="w", padx=(0, 20))
        ttk.Checkbutton(opts, text="Schwarz als Graustufe als Fehler werten",
                        variable=self.var_gray).grid(row=0, column=4, sticky="w")
        ttk.Label(opts, text="Ghostscript:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(opts, textvariable=self.var_gs).grid(row=1, column=1, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Button(opts, text="Ändern …", command=self.ask_gs).grid(row=1, column=4, sticky="w", pady=(4, 0))

        paned = ttk.PanedWindow(self.root, orient="vertical")
        paned.pack(fill="both", expand=True, padx=8, pady=4)

        table = ttk.Frame(paned)
        cols = ["gesamt"] + CHECK_ORDER
        self.tree = ttk.Treeview(table, columns=cols, selectmode="extended")
        self.tree.heading("#0", text="Datei", anchor="w")
        self.tree.column("#0", width=280, stretch=True)
        self.tree.heading("gesamt", text="Gesamt")
        self.tree.column("gesamt", width=90, anchor="center", stretch=False)
        for key in CHECK_ORDER:
            self.tree.heading(key, text=COLUMN_TITLES[key])
            self.tree.column(key, width=118, anchor="center", stretch=False)
        for st, color in ROW_COLORS.items():
            self.tree.tag_configure(f"s{int(st)}", background=color)
        sb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_details())
        self.tree.bind("<Double-1>", lambda e: self.open_in_explorer())
        self.tree.bind("<Delete>", lambda e: self.remove_selected())
        paned.add(table, weight=3)

        detail = ttk.Frame(paned)
        self.text = tk.Text(detail, wrap="word", height=12, font=("Segoe UI", 10), relief="flat",
                            padx=8, pady=6, background="#ffffff")
        dsb = ttk.Scrollbar(detail, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=dsb.set, state="disabled")
        self.text.pack(side="left", fill="both", expand=True)
        dsb.pack(side="right", fill="y")
        self.text.tag_configure("h1", font=("Segoe UI", 12, "bold"))
        self.text.tag_configure("path", foreground="#666666")
        self.text.tag_configure("title", font=("Segoe UI", 10, "bold"))
        self.text.tag_configure("detail", foreground="#444444", lmargin1=28, lmargin2=40)
        for st, color in TEXT_COLORS.items():
            self.text.tag_configure(f"c{int(st)}", foreground=color, font=("Segoe UI", 10, "bold"))
        paned.add(detail, weight=2)

        status = ttk.Frame(self.root, padding=(8, 2, 8, 6))
        status.pack(fill="x")
        self.progress = ttk.Progressbar(status, length=220, mode="determinate")
        self.progress.pack(side="right")
        ttk.Label(status, textvariable=self.var_status).pack(side="left")

    def _enable_drop(self):
        """Drag & Drop aus dem Explorer, falls tkinterdnd2 installiert ist."""
        try:
            from tkinterdnd2 import DND_FILES  # type: ignore
        except ImportError:
            return
        try:
            self.tree.drop_target_register(DND_FILES)
            self.tree.dnd_bind("<<Drop>>", lambda e: self.add_paths(self.root.tk.splitlist(e.data)))
        except (AttributeError, tk.TclError):
            pass

    def _update_gs_label(self):
        if self.gs_path:
            ver = ghostscript_version(self.gs_path)
            self.var_gs.set(f"{self.gs_path}  (Version {ver})" if ver else self.gs_path)
        else:
            self.var_gs.set("NICHT GEFUNDEN – bitte Ghostscript installieren oder Pfad angeben")

    def _warn_no_gs(self):
        messagebox.showwarning(
            APP_TITLE,
            "Ghostscript wurde nicht gefunden.\n\n"
            "Der EPS-Prüfer benötigt die kostenlose Ghostscript-Kommandozeile "
            "(gswin64c.exe), um die Dateien auszuwerten.\n\n"
            "Download: https://ghostscript.com/releases/gsdnld.html\n\n"
            "Nach der Installation das Programm neu starten oder über "
            "„Ändern …“ den Pfad zu gswin64c.exe angeben.",
        )

    # ------------------------------------------------------------ Dateien
    def ask_files(self):
        paths = filedialog.askopenfilenames(title="EPS-Dateien wählen", filetypes=EPS_TYPES,
                                            initialdir=self.cfg.get("last_dir"))
        if paths:
            self.cfg["last_dir"] = str(Path(paths[0]).parent)
            self.add_paths(paths)

    def ask_folder(self):
        folder = filedialog.askdirectory(title="Ordner mit EPS-Dateien wählen",
                                         initialdir=self.cfg.get("last_dir"))
        if folder:
            self.cfg["last_dir"] = folder
            self.add_paths([folder])

    def ask_gs(self):
        ftypes = [("Ghostscript", "gswin64c.exe gswin32c.exe gs"), ("Programme", "*.exe"), ("Alle", "*.*")]
        path = filedialog.askopenfilename(title="Ghostscript-Kommandozeile wählen (gswin64c.exe)",
                                          filetypes=ftypes)
        if path:
            self.gs_path = path
            self.cfg["gs_executable"] = path
            self._update_gs_label()

    def add_paths(self, paths):
        known = set(self.files)
        added = 0
        for f in collect_files(list(paths)):
            f = f.resolve()
            if f not in known:
                self.files.append(f)
                known.add(f)
                self.tree.insert("", "end", iid=str(f), text=f.name,
                                 values=["offen"] + [""] * len(CHECK_ORDER))
                added += 1
        self.var_status.set(f"{added} Datei(en) hinzugefügt, {len(self.files)} in der Liste.")

    def remove_selected(self):
        if self._busy():
            return
        for iid in self.tree.selection():
            p = Path(iid)
            self.tree.delete(iid)
            self.files.remove(p)
            self.results.pop(p, None)
        self.show_details()

    def clear(self):
        if self._busy():
            return
        self.tree.delete(*self.tree.get_children())
        self.files.clear()
        self.results.clear()
        self.show_details()
        self.var_status.set("Liste geleert.")

    def open_in_explorer(self):
        sel = self.tree.selection()
        if not sel:
            return
        path = sel[0]
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except OSError:
            pass

    # -------------------------------------------------------------- Prüfen
    def _busy(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def _settings(self) -> Settings:
        try:
            dpi = float(self.var_dpi.get())
        except (tk.TclError, ValueError):
            dpi = 150.0
        return Settings(max_dpi=dpi, rgb_is_error=self.var_rgb.get(),
                        gray_black_is_error=self.var_gray.get(), gs_executable=self.gs_path or "")

    def start_check(self):
        if self._busy():
            self.cancel.set()
            self.var_status.set("Wird abgebrochen …")
            return
        if not self.files:
            messagebox.showinfo(APP_TITLE, "Bitte zuerst EPS-Dateien oder einen Ordner hinzufügen.")
            return
        if not self.gs_path:
            self._warn_no_gs()
        settings = self._settings()
        files = list(self.files)
        self.cancel.clear()
        self.progress.configure(maximum=len(files), value=0)
        self.btn_check.configure(text="■  Abbrechen")
        for f in files:
            self.tree.item(str(f), values=["…"] + [""] * len(CHECK_ORDER), tags=())

        def work():
            for i, f in enumerate(files):
                if self.cancel.is_set():
                    break
                self.queue.put(("progress", i, f))
                try:
                    res = check_file(f, settings)
                except Exception as exc:  # unerwarteter Fehler: Datei markieren, weiterprüfen
                    from .checks import CheckResult

                    res = FileResult(path=f, checks=[CheckResult(
                        "datei", CHECK_TITLES["datei"], Status.FAIL, f"Interner Fehler: {exc}")])
                self.queue.put(("result", i, res))
            self.queue.put(("done", None, None))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()
        self.root.after(50, self._poll)

    def _poll(self):
        try:
            while True:
                kind, i, payload = self.queue.get_nowait()
                if kind == "progress":
                    self.var_status.set(f"Prüfe {i + 1}/{len(self.files)}: {payload.name}")
                elif kind == "result":
                    self._show_result(payload)
                    self.progress.configure(value=i + 1)
                elif kind == "done":
                    self._finished()
                    return
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _show_result(self, res: FileResult):
        self.results[res.path] = res
        iid = str(res.path)
        if not self.tree.exists(iid):
            return
        vals = [f"{res.status.symbol} {res.status.label}"]
        for key in CHECK_ORDER:
            c = res.check(key)
            vals.append(f"{c.status.symbol} {c.status.label}" if c else "")
        self.tree.item(iid, values=vals, tags=(f"s{int(res.status)}",))
        sel = self.tree.selection()
        if not sel or sel[0] == iid:
            if not sel:
                self.tree.selection_set(iid)
            self.show_details()

    def _finished(self):
        self.btn_check.configure(text="▶  Prüfen")
        res = list(self.results.values())
        ok = sum(1 for r in res if r.status <= Status.INFO)
        warn = sum(1 for r in res if r.status == Status.WARN)
        fail = sum(1 for r in res if r.status == Status.FAIL)
        prefix = "Abgebrochen. " if self.cancel.is_set() else "Fertig. "
        self.var_status.set(f"{prefix}{len(res)} geprüft: {ok} OK, {warn} mit Warnung, {fail} fehlerhaft")

    # -------------------------------------------------------------- Details
    def show_details(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        sel = self.tree.selection()
        res = self.results.get(Path(sel[0])) if sel else None
        if sel and res is None:
            self.text.insert("end", Path(sel[0]).name + "\n", "h1")
            self.text.insert("end", "Noch nicht geprüft.\n", "path")
        elif res:
            self.text.insert("end", f"{res.status.symbol} ", f"c{int(res.status)}")
            self.text.insert("end", res.path.name + "\n", "h1")
            self.text.insert("end", str(res.path) + "\n\n", "path")
            for c in res.checks:
                self.text.insert("end", f"{c.status.symbol} {c.status.label:8}  ", f"c{int(c.status)}")
                self.text.insert("end", c.title + ": ", "title")
                self.text.insert("end", c.message + "\n")
                for d in c.details:
                    self.text.insert("end", "• " + d + "\n", "detail")
                self.text.insert("end", "\n")
        self.text.configure(state="disabled")

    # --------------------------------------------------------------- Bericht
    def save_report(self):
        results = [self.results[f] for f in self.files if f in self.results]
        if not results:
            messagebox.showinfo(APP_TITLE, "Es liegen noch keine Prüfergebnisse vor.")
            return
        path = filedialog.asksaveasfilename(
            title="Prüfbericht speichern",
            defaultextension=".html",
            initialfile="EPS-Pruefbericht.html",
            initialdir=self.cfg.get("last_dir"),
            filetypes=[("HTML-Bericht", "*.html"), ("CSV (Excel)", "*.csv"), ("Text", "*.txt")],
        )
        if not path:
            return
        try:
            ext = Path(path).suffix.lower()
            if ext == ".csv":
                write_csv(results, path)
            elif ext == ".txt":
                Path(path).write_text(text_report(results), encoding="utf-8")
            else:
                write_html(results, path, self._settings())
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Bericht konnte nicht gespeichert werden:\n{exc}")
            return
        self.var_status.set(f"Bericht gespeichert: {path}")
        if sys.platform == "win32" and Path(path).suffix.lower() == ".html":
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except OSError:
                pass

    def show_help(self):
        messagebox.showinfo(
            f"{APP_TITLE} {__version__}",
            "Geprüft wird:\n\n"
            "• Schwarz in CMYK – Schwarz darf nicht als RGB angelegt sein "
            "(weitere RGB-Farben/-Bilder und Graustufen-Schwarz: Warnung)\n"
            "• Pixeldaten eingebettet – keine OPI-/DCS-/Datei-Verknüpfungen\n"
            "• Auflösung – effektive Auflösung aller Bilder ≤ Grenzwert\n"
            "• Kein Überdrucken – kein Objekt auf Überdrucken gestellt\n"
            "• Hintergrundfläche – das unterste Objekt ist eine deckende "
            "Farbfläche (100 % Deckkraft), die die ganze BoundingBox abdeckt\n\n"
            "Zusätzlich: PostScript-Fehler und nicht eingebettete Schriften.\n\n"
            "Doppelklick auf eine Zeile öffnet den Ordner der Datei.",
        )

    def _on_close(self):
        self.cancel.set()
        self.cfg.update(
            max_dpi=self._settings().max_dpi,
            rgb_is_error=self.var_rgb.get(),
            gray_black_is_error=self.var_gray.get(),
            geometry=self.root.geometry(),
        )
        if self.gs_path:
            self.cfg["gs_executable"] = self.gs_path
        save_config(self.cfg)
        self.root.destroy()


def main(argv: list[str] | None = None) -> int:
    if sys.platform == "win32":
        try:  # scharfe Darstellung auf HiDPI-Bildschirmen
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    try:
        from tkinterdnd2 import TkinterDnD  # type: ignore

        root = TkinterDnD.Tk()
    except ImportError:
        root = tk.Tk()
    App(root, [a for a in (argv or []) if not a.startswith("-")])
    root.mainloop()
    return 0
