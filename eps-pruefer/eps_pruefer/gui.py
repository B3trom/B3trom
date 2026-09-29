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
from .cli import folder_files
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
        self.var_recursive = tk.BooleanVar(value=self.cfg.get("recursive", True))
        self.run_files: list[Path] = []
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

        top = ttk.Frame(self.root, padding=(8, 8, 8, 0))
        top.pack(fill="x")

        src = ttk.LabelFrame(top, text="Was soll geprüft werden?", padding=(8, 4))
        src.pack(side="left", fill="y")
        ttk.Button(src, text="Einzelne Dateien …", command=self.ask_files).grid(row=0, column=0)
        ttk.Button(src, text="Ganzer Ordner / Projekt …", command=self.ask_folder).grid(
            row=0, column=1, padx=(6, 0))
        ttk.Checkbutton(src, text="inkl. Unterordner", variable=self.var_recursive).grid(
            row=0, column=2, padx=(6, 12))
        ttk.Button(src, text="Entfernen", command=self.remove_selected).grid(row=0, column=3)
        ttk.Button(src, text="Liste leeren", command=self.clear).grid(row=0, column=4, padx=(6, 0))

        run = ttk.LabelFrame(top, text="Prüfen", padding=(8, 4))
        run.pack(side="left", fill="y", padx=8)
        self.btn_check = ttk.Button(run, text="▶  Alle prüfen", style="Accent.TButton",
                                    command=self.start_check)
        self.btn_check.grid(row=0, column=0)
        self.btn_check_sel = ttk.Button(run, text="▶  Auswahl prüfen",
                                        command=lambda: self.start_check(selection_only=True))
        self.btn_check_sel.grid(row=0, column=1, padx=(6, 0))
        ttk.Button(run, text="Bericht speichern …", command=self.save_report).grid(
            row=0, column=2, padx=(12, 0))

        ttk.Button(top, text="?", width=3, command=self.show_help).pack(side="right", anchor="n", pady=(8, 0))

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
        self.tree.column("#0", width=300, stretch=True)
        self.tree.heading("gesamt", text="Gesamt")
        self.tree.column("gesamt", width=90, anchor="center", stretch=False)
        for key in CHECK_ORDER:
            self.tree.heading(key, text=COLUMN_TITLES[key])
            self.tree.column(key, width=118, anchor="center", stretch=False)
        for st, color in ROW_COLORS.items():
            self.tree.tag_configure(f"s{int(st)}", background=color)
        self.tree.tag_configure("group", font=("Segoe UI", 10, "bold"))
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

    @staticmethod
    def _group_iid(folder: Path) -> str:
        return "dir:" + str(folder)

    def _is_group(self, iid: str) -> bool:
        return iid.startswith("dir:")

    def _insert_file(self, f: Path, parent: str, label: str):
        self.files.append(f)
        self.tree.insert(parent, "end", iid=str(f), text=label,
                         values=["offen"] + [""] * len(CHECK_ORDER))

    def add_paths(self, paths):
        """Einzelne Dateien landen oben in der Liste, Ordner als Projekt-Knoten."""
        known = set(self.files)
        recursive = self.var_recursive.get()
        added, empty = 0, []
        for p in (Path(x).resolve() for x in paths):
            if p.is_dir():
                gid = self._group_iid(p)
                if not self.tree.exists(gid):
                    self.tree.insert("", "end", iid=gid, text=p.name or str(p), open=True,
                                     values=["offen"] + [""] * len(CHECK_ORDER), tags=("group",))
                for f in folder_files(p, recursive):
                    rel = str(f.relative_to(p))
                    f = f.resolve()
                    if f not in known:
                        known.add(f)
                        self._insert_file(f, gid, rel)
                        added += 1
                if not self.tree.get_children(gid):
                    self.tree.delete(gid)
                    empty.append(str(p))
                else:
                    self._update_group(gid)
            elif p not in known:
                known.add(p)
                self._insert_file(p, "", p.name)
                added += 1
        msg = f"{added} Datei(en) hinzugefügt, {len(self.files)} in der Liste."
        if empty:
            msg += "  Keine EPS-Dateien in: " + ", ".join(empty)
        self.var_status.set(msg)

    def _files_of(self, iids) -> list[Path]:
        """Dateien zu Listeneinträgen; ein Projekt-Knoten steht für alle seine Dateien."""
        wanted: set[Path] = set()
        for iid in iids:
            if self._is_group(iid):
                wanted.update(Path(c) for c in self.tree.get_children(iid))
            else:
                wanted.add(Path(iid))
        return [f for f in self.files if f in wanted]  # Listenreihenfolge beibehalten

    def remove_selected(self):
        if self._busy():
            return
        for f in self._files_of(self.tree.selection()):
            parent = self.tree.parent(str(f))
            self.tree.delete(str(f))
            self.files.remove(f)
            self.results.pop(f, None)
            if parent and self.tree.exists(parent):
                if self.tree.get_children(parent):
                    self._update_group(parent)
                else:
                    self.tree.delete(parent)
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
        if self._is_group(path):
            path = path[4:]
        try:
            if sys.platform == "win32":
                if os.path.isdir(path):
                    os.startfile(path)  # type: ignore[attr-defined]
                else:
                    subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                subprocess.Popen(["xdg-open", path if os.path.isdir(path) else os.path.dirname(path)])
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

    def start_check(self, selection_only: bool = False):
        if self._busy():
            self.cancel.set()
            self.var_status.set("Wird abgebrochen …")
            return
        if not self.files:
            messagebox.showinfo(APP_TITLE, "Bitte zuerst einzelne EPS-Dateien oder einen Ordner hinzufügen.")
            return
        files = self._files_of(self.tree.selection()) if selection_only else list(self.files)
        if not files:
            messagebox.showinfo(APP_TITLE, "Bitte in der Liste zuerst Dateien oder einen Ordner markieren "
                                           "(mehrere mit Strg- bzw. Umschalt-Klick).")
            return
        if not self.gs_path:
            self._warn_no_gs()
        settings = self._settings()
        self.run_files = files
        self.cancel.clear()
        self.progress.configure(maximum=len(files), value=0)
        self.btn_check.configure(text="■  Abbrechen")
        self.btn_check_sel.state(["disabled"])
        groups = set()
        for f in files:
            self.results.pop(f, None)
            self.tree.item(str(f), values=["…"] + [""] * len(CHECK_ORDER), tags=())
            groups.add(self.tree.parent(str(f)))
        for gid in groups - {""}:
            self._update_group(gid)

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
                    self.var_status.set(f"Prüfe {i + 1}/{len(self.run_files)}: {payload.name}")
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
        parent = self.tree.parent(iid)
        if parent:
            self._update_group(parent)
        sel = self.tree.selection()
        if not sel:
            self.tree.selection_set(iid)
        elif sel[0] in (iid, parent):
            self.show_details()

    def _update_group(self, gid: str):
        """Sammelstatus eines Projekt-Knotens: je Prüfung die Zahl der Dateien mit Befund."""
        files = [Path(c) for c in self.tree.get_children(gid)]
        done = [self.results[f] for f in files if f in self.results]
        name = Path(gid[4:]).name or gid[4:]
        self.tree.item(gid, text=f"{name}   ({len(files)} Dateien)")
        if not done:
            self.tree.item(gid, values=["offen"] + [""] * len(CHECK_ORDER), tags=("group",))
            return
        worst = max(r.status for r in done)
        n_ok = sum(1 for r in done if r.status <= Status.INFO)
        vals = [f"{worst.symbol} {n_ok}/{len(files)} OK"]
        for key in CHECK_ORDER:
            stats = [c.status for r in done if (c := r.check(key))]
            bad = sum(1 for st in stats if st >= Status.WARN)
            top = max(stats, default=Status.INFO)
            vals.append(f"{top.symbol} {bad}" if bad else (f"{top.symbol} OK" if stats else ""))
        tags = ("group",) if len(done) < len(files) else ("group", f"s{int(worst)}")
        self.tree.item(gid, values=vals, tags=tags)

    def _finished(self):
        self.btn_check.configure(text="▶  Alle prüfen")
        self.btn_check_sel.state(["!disabled"])
        res = [self.results[f] for f in self.run_files if f in self.results]
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
        if sel and self._is_group(sel[0]):
            self._show_group_details(sel[0])
            self.text.configure(state="disabled")
            return
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

    def _show_group_details(self, gid: str):
        folder = Path(gid[4:])
        files = [Path(c) for c in self.tree.get_children(gid)]
        done = [self.results[f] for f in files if f in self.results]
        t = self.text
        if done:
            worst = max(r.status for r in done)
            t.insert("end", f"{worst.symbol} ", f"c{int(worst)}")
        t.insert("end", f"Projekt {folder.name}\n", "h1")
        t.insert("end", str(folder) + "\n\n", "path")
        ok = sum(1 for r in done if r.status <= Status.INFO)
        warn = sum(1 for r in done if r.status == Status.WARN)
        fail = sum(1 for r in done if r.status == Status.FAIL)
        t.insert("end", f"{len(files)} EPS-Datei(en), {len(done)} geprüft:  ")
        t.insert("end", f"{ok} OK", "c0")
        t.insert("end", ",  ")
        t.insert("end", f"{warn} mit Warnung", "c2")
        t.insert("end", ",  ")
        t.insert("end", f"{fail} fehlerhaft\n\n", "c3")
        if not done:
            t.insert("end", "Noch nicht geprüft – „Alle prüfen“ oder „Auswahl prüfen“ klicken.\n", "path")
            return
        for key in CHECK_ORDER:
            stats = [c.status for r in done if (c := r.check(key))]
            n_fail = stats.count(Status.FAIL)
            n_warn = stats.count(Status.WARN)
            top = max(stats, default=Status.OK)
            t.insert("end", f"{top.symbol} ", f"c{int(top)}")
            t.insert("end", CHECK_TITLES[key] + ": ", "title")
            parts = ([f"{n_fail} Fehler"] if n_fail else []) + ([f"{n_warn} Warnung(en)"] if n_warn else [])
            t.insert("end", (", ".join(parts) if parts else "alle OK") + "\n")
        problems = [r for r in done if r.status >= Status.WARN]
        if problems:
            t.insert("end", "\nDateien mit Befund:\n", "title")
            for r in sorted(problems, key=lambda r: -r.status):
                t.insert("end", f"{r.status.symbol} ", f"c{int(r.status)}")
                t.insert("end", f"{r.path.relative_to(folder)}\n")
                for c in r.checks:
                    if c.status >= Status.WARN:
                        t.insert("end", f"• {c.title}: {c.message}\n", "detail")

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
            "Auswahl:\n"
            "• „Einzelne Dateien …“ fügt gezielt gewählte EPS hinzu.\n"
            "• „Ganzer Ordner / Projekt …“ fügt alle EPS eines Ordners als Projekt "
            "hinzu (wahlweise inkl. Unterordner) – mit Sammelstatus.\n"
            "• „Alle prüfen“ prüft die ganze Liste, „Auswahl prüfen“ nur die markierten "
            "Dateien bzw. Projekte.\n\n"
            "Doppelklick auf eine Zeile öffnet den Ordner der Datei.",
        )

    def _on_close(self):
        self.cancel.set()
        self.cfg.update(
            max_dpi=self._settings().max_dpi,
            rgb_is_error=self.var_rgb.get(),
            gray_black_is_error=self.var_gray.get(),
            recursive=self.var_recursive.get(),
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
