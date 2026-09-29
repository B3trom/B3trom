"""Oberfläche v2: Kacheldesign mit 3D-Effekt, Hell-/Dunkelmodus und Prüfliste.

Reines Tkinter (keine Zusatzpakete). Kacheln werden auf Canvas gezeichnet:
mehrstufiger weicher Schatten, Lichtkante oben, beim Überfahren hebt sich die
Kachel an, beim Klicken wird sie eingedrückt.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from . import __version__
from .checks import CHECK_TITLES, CheckResult, FileResult, Settings, Status, check_file
from .cli import folder_files
from .ghostscript import find_ghostscript, ghostscript_version
from .gui import EPS_TYPES, load_config, save_config
from .report import CHECK_ORDER, text_report, write_csv, write_html

APP_TITLE = "EPS-Prüfer"
FONT = "Segoe UI"


# ---------------------------------------------------------------------------
# Farben
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Theme:
    name: str
    bg: str
    surface: str
    surface2: str
    text: str
    muted: str
    border: str
    shadow: str
    highlight: str
    accent: str
    on_accent: str
    ok: str
    warn: str
    fail: str
    info: str


LIGHT = Theme(
    name="light", bg="#e9edf2", surface="#ffffff", surface2="#f4f6f9", text="#1c2128",
    muted="#5f6b7a", border="#d5dbe3", shadow="#8a96a8", highlight="#ffffff",
    accent="#2f6fed", on_accent="#ffffff", ok="#1f8a3f", warn="#b27c00", fail="#d1242f", info="#8c959f",
)
DARK = Theme(
    name="dark", bg="#13161b", surface="#1e232b", surface2="#262c36", text="#e6edf3",
    muted="#8d98a5", border="#323a46", shadow="#000000", highlight="#3a4350",
    accent="#4d8dff", on_accent="#ffffff", ok="#3fb950", warn="#d9a21b", fail="#f85149", info="#6e7681",
)


def mix(c1: str, c2: str, t: float) -> str:
    """Farbe zwischen c1 (t=0) und c2 (t=1)."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def status_color(t: Theme, st: Status | None) -> str:
    return {Status.OK: t.ok, Status.WARN: t.warn, Status.FAIL: t.fail}.get(st, t.info)


STATUS_GLYPH = {Status.OK: "✓", Status.WARN: "!", Status.FAIL: "✕", Status.INFO: "–", None: "○"}


def system_prefers_dark() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def round_rect(c: tk.Canvas, x1, y1, x2, y2, r, **kw):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, splinesteps=16, **kw)


# ---------------------------------------------------------------------------
# Kacheln
# ---------------------------------------------------------------------------

class Tile(tk.Canvas):
    """Klickbare 3D-Kachel (Aktion) oder Kennzahl-Kachel (ohne command)."""

    RADIUS = 14

    def __init__(self, master, theme: Theme, *, title: str, subtitle: str = "", icon: str = "",
                 command=None, primary: bool = False, value: str = "", value_color: str | None = None,
                 width: int | None = None, height: int = 84):
        if width is None:  # Breite an die Beschriftung anpassen
            w_title = tkfont.Font(master, family=FONT, size=11, weight="bold").measure(title)
            w_sub = tkfont.Font(master, family=FONT, size=9).measure(subtitle)
            width = max(w_title, w_sub) + (52 if icon else 16) + 30
        super().__init__(master, width=width, height=height, highlightthickness=0, bd=0, bg=theme.bg)
        self.t = theme
        self.title, self.subtitle, self.icon = title, subtitle, icon
        self.command, self.primary = command, primary
        self.value, self.value_color = value, value_color
        self.state_ = "normal"
        self.enabled = True
        self.bind("<Configure>", lambda e: self.draw())
        if command:
            self.configure(cursor="hand2")
            self.bind("<Enter>", lambda e: self._set("hover"))
            self.bind("<Leave>", lambda e: self._set("normal"))
            self.bind("<ButtonPress-1>", lambda e: self._set("pressed"))
            self.bind("<ButtonRelease-1>", self._release)

    def _set(self, state: str):
        if self.enabled:
            self.state_ = state
            self.draw()

    def _release(self, e):
        inside = 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height()
        self._set("hover" if inside else "normal")
        if inside and self.enabled and self.command:
            self.command()

    def set_enabled(self, enabled: bool):
        self.enabled = enabled
        self.state_ = "normal"
        self.configure(cursor="hand2" if enabled and self.command else "")
        self.draw()

    def update_value(self, value: str, color: str | None = None, subtitle: str | None = None):
        self.value = value
        if color:
            self.value_color = color
        if subtitle is not None:
            self.subtitle = subtitle
        self.draw()

    def update_title(self, title: str, icon: str | None = None):
        self.title = title
        if icon is not None:
            self.icon = icon
        self.draw()

    def draw(self):
        t = self.t
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20 or h < 20:
            return
        lift = {"normal": 0, "hover": -2, "pressed": 2}[self.state_]
        depth = {"normal": 6, "hover": 9, "pressed": 2}[self.state_]
        x1, y1, x2, y2 = 6, 4 + lift, w - 6, h - 12 + lift
        r = self.RADIUS
        strength = 0.55 if t.name == "dark" else 0.35

        # weicher Schatten: von außen (hell) nach innen (dunkel)
        for i in range(depth, 0, -1):
            f = strength * (1 - i / (depth + 1)) ** 1.6
            round_rect(self, x1 - i * 0.35, y1 + i, x2 + i * 0.35, y2 + i, r + i * 0.4,
                       fill=mix(t.bg, t.shadow, f), outline="")

        if self.primary and self.enabled:
            face = mix(t.accent, "#ffffff", 0.08) if self.state_ == "hover" else t.accent
            edge = mix(t.accent, "#000000", 0.18)
            fg, sub, icon_fg = t.on_accent, mix(t.on_accent, t.accent, 0.25), t.on_accent
            light = mix(t.accent, "#ffffff", 0.35)
        else:
            face = mix(t.surface, t.surface2, 0.6) if self.state_ == "pressed" else t.surface
            edge = t.border
            fg = t.text if self.enabled else t.muted
            sub, icon_fg = t.muted, (t.accent if self.enabled else t.muted)
            light = t.highlight
        round_rect(self, x1, y1, x2, y2, r, fill=face, outline=edge)
        # Lichtkante oben (Bevel)
        self.create_line(x1 + r * 0.7, y1 + 1.5, x2 - r * 0.7, y1 + 1.5, fill=light, width=1)

        cy = (y1 + y2) / 2
        if self.command is None:  # Kennzahl-Kachel
            self.create_text(x1 + 16, cy - 9, text=self.value, anchor="w",
                             font=(FONT, 20, "bold"), fill=self.value_color or t.text)
            self.create_text(x1 + 16, cy + 16, text=self.title, anchor="w",
                             font=(FONT, 9), fill=t.muted)
            return
        tx = x1 + 16
        if self.icon:
            self.create_text(x1 + 26, cy, text=self.icon, font=(FONT, 20), fill=icon_fg)
            tx = x1 + 52
        if self.subtitle:
            self.create_text(tx, cy - 9, text=self.title, anchor="w", font=(FONT, 11, "bold"), fill=fg)
            self.create_text(tx, cy + 11, text=self.subtitle, anchor="w", font=(FONT, 9), fill=sub)
        else:
            self.create_text(tx, cy, text=self.title, anchor="w", font=(FONT, 11, "bold"), fill=fg)


class Badge(tk.Canvas):
    """Runder Status-Knopf mit Symbol und leichtem Glanz."""

    def __init__(self, master, theme: Theme, status: Status | None, bg: str, size: int = 30):
        super().__init__(master, width=size, height=size, highlightthickness=0, bd=0, bg=bg)
        s = size
        if status is None:  # noch nicht geprüft: schlichter Ring
            self.create_oval(3, 3, s - 3, s - 3, outline=theme.border, width=2)
            return
        col = status_color(theme, status)
        self.create_oval(2, 3, s - 2, s - 1, fill=mix(bg, "#000000", 0.18), outline="")
        self.create_oval(2, 1, s - 2, s - 3, fill=col, outline="")
        self.create_oval(6, 3, s - 6, s / 2 - 1, fill=mix(col, "#ffffff", 0.25), outline="")
        self.create_text(s / 2, s / 2 - 1, text=STATUS_GLYPH[status], fill="#ffffff",
                         font=(FONT, int(s * 0.42), "bold"))


def card(parent, t: Theme, stripe: str | None = None, pad=(14, 10)):
    """Karte mit Kante unten (Schatten) und optionalem farbigem Streifen links."""
    outer = tk.Frame(parent, bg=mix(t.bg, t.shadow, 0.45 if t.name == "dark" else 0.22))
    body = tk.Frame(outer, bg=t.surface, highlightthickness=1, highlightbackground=t.border)
    body.pack(fill="both", expand=True, pady=(0, 3))
    if stripe:
        tk.Frame(body, bg=stripe, width=5).pack(side="left", fill="y")
    inner = tk.Frame(body, bg=t.surface, padx=pad[0], pady=pad[1])
    inner.pack(side="left", fill="both", expand=True)
    return outer, inner


# ---------------------------------------------------------------------------
# Anwendung
# ---------------------------------------------------------------------------

CHECK_DESCRIPTIONS = {
    "datei": "EPS lesbar, PostScript fehlerfrei, Schriften eingebettet",
    "schwarz": "Schwarz ist CMYK-Schwarz, nicht RGB",
    "eingebettet": "Alle Pixeldaten sind eingebettet, keine Verknüpfungen",
    "aufloesung": "Bilder liegen zwischen {min} und {max} dpi",
    "ueberdrucken": "Kein Objekt steht auf Überdrucken",
    "hintergrund": "Unterstes Objekt ist eine deckende Farbfläche (ohne Transparenz)",
}


class App:
    def __init__(self, root: tk.Tk, initial_paths: list[str]):
        self.root = root
        self.cfg = load_config()
        mode = self.cfg.get("theme") or ("dark" if system_prefers_dark() else "light")
        self.t = DARK if mode == "dark" else LIGHT

        # Datenmodell: Reihenfolge der Einträge ("g", Ordner) bzw. ("f", Datei)
        self.order: list[tuple[str, Path]] = []
        self.groups: dict[Path, list[Path]] = {}
        self.results: dict[Path, FileResult] = {}
        self.run_files: list[Path] = []
        self.queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel = threading.Event()

        self.var_min = tk.DoubleVar(value=self.cfg.get("min_dpi", 80))
        self.var_max = tk.DoubleVar(value=self.cfg.get("max_dpi", 150))
        self.var_rgb = tk.BooleanVar(value=self.cfg.get("rgb_is_error", False))
        self.var_gray = tk.BooleanVar(value=self.cfg.get("gray_black_is_error", False))
        self.var_recursive = tk.BooleanVar(value=self.cfg.get("recursive", True))
        self.gs_path = find_ghostscript(self.cfg.get("gs_executable"))
        self.gs_version = ghostscript_version(self.gs_path) if self.gs_path else ""
        self.status_text = "Einzelne Dateien oder einen Ordner hinzufügen, dann „Alle prüfen“."
        self.selected: str | None = None

        root.title(f"{APP_TITLE} {__version__}")
        root.geometry(self.cfg.get("geometry_v2", "1320x860"))
        root.minsize(1060, 680)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.build()
        self._enable_drop()

        if initial_paths:
            self.add_paths(initial_paths)
            root.after(300, self.start_check)
        elif not self.gs_path:
            root.after(400, self._warn_no_gs)

    # ------------------------------------------------------------------ Aufbau
    def build(self):
        """Baut die komplette Oberfläche im aktuellen Farbschema (auch beim Umschalten)."""
        t = self.t
        for w in self.root.winfo_children():
            w.destroy()
        self.root.configure(bg=t.bg)
        self._style()
        self._dark_titlebar()

        # Kopfzeile
        head = tk.Frame(self.root, bg=t.bg, padx=18, pady=8)
        head.pack(fill="x")
        logo = tk.Canvas(head, width=40, height=40, bg=t.bg, highlightthickness=0)
        logo.pack(side="left")
        round_rect(logo, 2, 4, 38, 40, 10, fill=mix(t.bg, t.shadow, 0.3), outline="")
        round_rect(logo, 2, 2, 38, 37, 10, fill=t.accent, outline="")
        logo.create_text(20, 19, text="EPS", fill=t.on_accent, font=(FONT, 10, "bold"))
        titles = tk.Frame(head, bg=t.bg)
        titles.pack(side="left", padx=12)
        tk.Label(titles, text="EPS-Prüfer", font=(FONT, 17, "bold"), bg=t.bg, fg=t.text).pack(anchor="w")
        tk.Label(titles, text="Druckproduktion & Anzeigensatz", font=(FONT, 9), bg=t.bg,
                 fg=t.muted).pack(anchor="w")
        Tile(head, t, title="Hilfe", icon="?", command=self.show_help, height=78).pack(side="right")
        dark = t.name == "dark"
        Tile(head, t, title="Hell" if dark else "Dunkel", icon="☀" if dark else "☾",
             command=self.toggle_theme, height=78).pack(side="right", padx=(8, 0))
        tk.Frame(head, bg=t.bg, width=24).pack(side="right")
        self.stat_tiles = {}
        for key, label, color in (("fail", "Fehler", t.fail), ("warn", "Warnungen", t.warn),
                                  ("ok", "OK", t.ok), ("files", "Dateien", t.text)):
            tile = Tile(head, t, title=label, value="0", value_color=color, width=108, height=78)
            tile.pack(side="right", padx=4)
            self.stat_tiles[key] = tile

        # Kachelreihe: Aktionen + Kennzahlen
        tiles = tk.Frame(self.root, bg=t.bg, padx=12)
        tiles.pack(fill="x")
        Tile(tiles, t, title="Einzelne Dateien", subtitle="EPS gezielt wählen", icon="＋",
             command=self.ask_files).pack(side="left", padx=6)
        Tile(tiles, t, title="Ordner / Projekt", subtitle="alle EPS im Ordner", icon="▤",
             command=self.ask_folder).pack(side="left", padx=6)
        self.tile_all = Tile(tiles, t, title="Alle prüfen", subtitle="Prüfung stoppen", icon="▶",
                             command=self.start_check, primary=True)
        self.tile_all.pack(side="left", padx=6)
        self.tile_sel = Tile(tiles, t, title="Auswahl prüfen", subtitle="nur markierte", icon="▷",
                             command=lambda: self.start_check(selection_only=True))
        self.tile_sel.pack(side="left", padx=6)
        Tile(tiles, t, title="Bericht speichern", subtitle="HTML · CSV · Text", icon="⤓",
             command=self.save_report).pack(side="left", padx=6)

        # Hauptbereich
        main = tk.Frame(self.root, bg=t.bg, padx=18, pady=8)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=5, uniform="m")
        main.columnconfigure(1, weight=4, uniform="m")
        main.rowconfigure(0, weight=1)

        left = tk.Frame(main, bg=t.bg)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self._build_filelist(left)
        self._build_settings(left)

        right = tk.Frame(main, bg=t.bg)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self._build_checklist(right)

        # Statuszeile
        foot = tk.Frame(self.root, bg=t.bg, padx=18, pady=10)
        foot.pack(fill="x")
        self.progress = ttk.Progressbar(foot, style="Tile.Horizontal.TProgressbar", length=260,
                                        mode="determinate")
        self.progress.pack(side="right")
        self.lbl_status = tk.Label(foot, text=self.status_text, bg=t.bg, fg=t.muted, font=(FONT, 9))
        self.lbl_status.pack(side="left")

        self.populate_tree()
        self._update_stats()
        busy = self._busy()
        self._set_running(busy)
        if busy:
            self.root.after(80, self._poll)

    def _style(self):
        t = self.t
        st = ttk.Style(self.root)
        st.theme_use("clam")
        st.configure(".", background=t.surface, foreground=t.text, font=(FONT, 10),
                     bordercolor=t.border, lightcolor=t.surface, darkcolor=t.surface,
                     troughcolor=t.surface2, focuscolor=t.accent)
        st.configure("Treeview", background=t.surface, fieldbackground=t.surface, foreground=t.text,
                     rowheight=30, borderwidth=0, font=(FONT, 10))
        st.map("Treeview", background=[("selected", mix(t.surface, t.accent, 0.28))],
               foreground=[("selected", t.text)])
        st.configure("Treeview.Heading", background=t.surface2, foreground=t.muted, relief="flat",
                     font=(FONT, 9, "bold"), borderwidth=0, padding=(8, 6))
        st.map("Treeview.Heading", background=[("active", t.surface2)])
        st.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        st.configure("Vertical.TScrollbar", background=t.surface2, troughcolor=t.surface,
                     bordercolor=t.surface, arrowcolor=t.muted, lightcolor=t.surface2, darkcolor=t.surface2)
        st.map("Vertical.TScrollbar", background=[("active", t.border)])
        st.configure("Tile.Horizontal.TProgressbar", background=t.accent, troughcolor=t.surface2,
                     bordercolor=t.bg, lightcolor=t.accent, darkcolor=t.accent, thickness=10)
        st.configure("TCheckbutton", background=t.surface, foreground=t.text, indicatorbackground=t.surface2,
                     indicatorforeground=t.accent, focuscolor=t.surface)
        st.map("TCheckbutton", background=[("active", t.surface)],
               indicatorbackground=[("selected", t.surface2), ("active", t.surface2)])
        st.configure("TSpinbox", fieldbackground=t.surface2, foreground=t.text, background=t.surface2,
                     arrowcolor=t.muted, bordercolor=t.border, insertcolor=t.text)
        st.configure("Link.TButton", background=t.surface2, foreground=t.text, borderwidth=1,
                     bordercolor=t.border, padding=(10, 3))
        st.map("Link.TButton", background=[("active", mix(t.surface2, t.accent, 0.15))])

    def _dark_titlebar(self):
        if sys.platform != "win32":
            return
        try:
            import ctypes

            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            val = ctypes.c_int(1 if self.t.name == "dark" else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), ctypes.sizeof(val))
        except (AttributeError, OSError):
            pass

    def _section_title(self, parent, text: str, extra: str = ""):
        t = self.t
        row = tk.Frame(parent, bg=t.bg)
        row.pack(fill="x", pady=(0, 6))
        tk.Label(row, text=text, font=(FONT, 12, "bold"), bg=t.bg, fg=t.text).pack(side="left")
        if extra:
            tk.Label(row, text=extra, font=(FONT, 9), bg=t.bg, fg=t.muted).pack(side="left", padx=8)
        return row

    def _build_filelist(self, parent):
        t = self.t
        row = self._section_title(parent, "Dateien", "Doppelklick öffnet den Ordner · Entf entfernt")
        tk.Label(row, text="Liste leeren", font=(FONT, 9, "underline"), bg=t.bg, fg=t.accent,
                 cursor="hand2").pack(side="right")
        row.winfo_children()[-1].bind("<Button-1>", lambda e: self.clear())
        rm = tk.Label(row, text="Entfernen", font=(FONT, 9, "underline"), bg=t.bg, fg=t.accent, cursor="hand2")
        rm.pack(side="right", padx=12)
        rm.bind("<Button-1>", lambda e: self.remove_selected())

        outer, inner = card(parent, t, pad=(2, 2))
        outer.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(inner, columns=("ergebnis", "befund"), selectmode="extended")
        self.tree.heading("#0", text="DATEI", anchor="w")
        self.tree.heading("ergebnis", text="ERGEBNIS", anchor="w")
        self.tree.heading("befund", text="BEFUNDE", anchor="w")
        self.tree.column("#0", width=240, stretch=True)
        self.tree.column("ergebnis", width=105, stretch=False)
        self.tree.column("befund", width=235, stretch=False)
        for st in Status:
            self.tree.tag_configure(f"s{int(st)}", background=mix(t.surface, status_color(t, st), 0.10),
                                    foreground=t.text)
        self.tree.tag_configure("group", font=(FONT, 10, "bold"))
        sb = ttk.Scrollbar(inner, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_select())
        self.tree.bind("<Double-1>", lambda e: self.open_in_explorer())
        self.tree.bind("<Delete>", lambda e: self.remove_selected())

        self.empty_hint = tk.Label(inner, bg=t.surface, fg=t.muted, font=(FONT, 10), justify="center",
                                   text="Noch keine Dateien.\n\n„Einzelne Dateien“ oder „Ordner / Projekt“ "
                                        "wählen –\noder EPS auf start.bat ziehen.")

    def _build_settings(self, parent):
        t = self.t
        tk.Frame(parent, bg=t.bg, height=14).pack(fill="x")
        self._section_title(parent, "Einstellungen")
        outer, inner = card(parent, t, pad=(14, 10))
        outer.pack(fill="x")

        def label(text, r, c, **kw):
            tk.Label(inner, text=text, bg=t.surface, fg=t.muted, font=(FONT, 9)).grid(
                row=r, column=c, sticky="w", **kw)

        label("AUFLÖSUNG PIXELDATEN", 0, 0, columnspan=2)
        dpi = tk.Frame(inner, bg=t.surface)
        dpi.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 8))
        ttk.Spinbox(dpi, from_=1, to=2400, width=5, textvariable=self.var_min).pack(side="left")
        tk.Label(dpi, text="  bis  ", bg=t.surface, fg=t.text).pack(side="left")
        ttk.Spinbox(dpi, from_=36, to=2400, width=5, textvariable=self.var_max).pack(side="left")
        tk.Label(dpi, text="  dpi", bg=t.surface, fg=t.text).pack(side="left")

        label("ORDNER", 0, 2, padx=(24, 0))
        ttk.Checkbutton(inner, text="inkl. Unterordner", variable=self.var_recursive).grid(
            row=1, column=2, sticky="w", padx=(24, 0), pady=(2, 8))

        label("STRENGE", 2, 0, columnspan=3)
        ttk.Checkbutton(inner, text="Alle RGB-Farben/-Bilder als Fehler", variable=self.var_rgb).grid(
            row=3, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(inner, text="Graustufen-Schwarz als Fehler", variable=self.var_gray).grid(
            row=3, column=2, sticky="w", padx=(24, 0))

        label("GHOSTSCRIPT", 4, 0, columnspan=3, pady=(10, 0))
        gs = tk.Frame(inner, bg=t.surface)
        gs.grid(row=5, column=0, columnspan=3, sticky="we", pady=(2, 0))
        if self.gs_path:
            txt, col = f"● {self.gs_path}" + (f"   (Version {self.gs_version})" if self.gs_version else ""), t.ok
        else:
            txt, col = "● nicht gefunden – bitte installieren oder Pfad wählen", t.fail
        tk.Label(gs, text=txt, bg=t.surface, fg=col, font=(FONT, 9)).pack(side="left")
        ttk.Button(gs, text="Ändern …", style="Link.TButton", command=self.ask_gs).pack(side="right")
        inner.columnconfigure(2, weight=1)

    def _build_checklist(self, parent):
        t = self.t
        self._section_title(parent, "Prüfliste")
        outer, inner = card(parent, t, pad=(0, 0))
        outer.pack(fill="both", expand=True)
        self.cl_canvas = tk.Canvas(inner, bg=t.surface, highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(inner, orient="vertical", command=self.cl_canvas.yview)
        self.cl_canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.cl_canvas.pack(side="left", fill="both", expand=True)
        self.cl_frame = tk.Frame(self.cl_canvas, bg=t.surface, padx=14, pady=12)
        self.cl_window = self.cl_canvas.create_window(0, 0, window=self.cl_frame, anchor="nw")
        self.cl_frame.bind("<Configure>",
                           lambda e: self.cl_canvas.configure(scrollregion=self.cl_canvas.bbox("all")))
        self.cl_canvas.bind("<Configure>", self._on_checklist_resize)
        self.wrap_labels: list[tk.Label] = []

        def wheel(e):
            delta = -1 if (getattr(e, "delta", 0) > 0 or getattr(e, "num", 0) == 4) else 1
            self.cl_canvas.yview_scroll(delta * 3, "units")

        for w in (self.cl_canvas, self.cl_frame):
            w.bind("<Enter>", lambda e: (self.root.bind_all("<MouseWheel>", wheel),
                                         self.root.bind_all("<Button-4>", wheel),
                                         self.root.bind_all("<Button-5>", wheel)))
            w.bind("<Leave>", lambda e: (self.root.unbind_all("<MouseWheel>"),
                                         self.root.unbind_all("<Button-4>"),
                                         self.root.unbind_all("<Button-5>")))

    def _on_checklist_resize(self, e):
        self.cl_canvas.itemconfigure(self.cl_window, width=e.width)
        for lbl in self.wrap_labels:
            if lbl.winfo_exists():
                lbl.configure(wraplength=max(200, e.width - 110))

    def _enable_drop(self):
        try:
            from tkinterdnd2 import DND_FILES  # type: ignore

            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", lambda e: self.add_paths(self.root.tk.splitlist(e.data)))
        except (ImportError, AttributeError, tk.TclError):
            pass

    def toggle_theme(self):
        self.t = LIGHT if self.t.name == "dark" else DARK
        self.cfg["theme"] = self.t.name
        sel = self.selected
        self.build()
        if sel and self.tree.exists(sel):
            self.tree.selection_set(sel)
            self.tree.see(sel)

    # ----------------------------------------------------------------- Status
    def set_status(self, text: str):
        self.status_text = text
        if self.lbl_status.winfo_exists():
            self.lbl_status.configure(text=text)

    def _set_running(self, running: bool):
        self.tile_all.update_title("Abbrechen" if running else "Alle prüfen", "■" if running else "▶")
        self.tile_all.subtitle = "Prüfung stoppen" if running else "ganze Liste"
        self.tile_all.draw()
        self.tile_sel.set_enabled(not running)

    def _update_stats(self):
        res = list(self.results.values())
        self.stat_tiles["files"].update_value(str(len(self.all_files())))
        self.stat_tiles["ok"].update_value(str(sum(1 for r in res if r.status <= Status.INFO)))
        self.stat_tiles["warn"].update_value(str(sum(1 for r in res if r.status == Status.WARN)))
        self.stat_tiles["fail"].update_value(str(sum(1 for r in res if r.status == Status.FAIL)))

    # ----------------------------------------------------------------- Modell
    def all_files(self) -> list[Path]:
        files: list[Path] = []
        for kind, p in self.order:
            files += self.groups[p] if kind == "g" else [p]
        return files

    @staticmethod
    def _gid(folder: Path) -> str:
        return "dir:" + str(folder)

    def _files_of(self, iids) -> list[Path]:
        wanted: set[Path] = set()
        for iid in iids:
            if iid.startswith("dir:"):
                wanted.update(self.groups.get(Path(iid[4:]), []))
            else:
                wanted.add(Path(iid))
        return [f for f in self.all_files() if f in wanted]

    def add_paths(self, paths):
        known = set(self.all_files())
        added, empty = 0, []
        for p in (Path(x).resolve() for x in paths):
            if p.is_dir():
                new = []
                for f in folder_files(p, self.var_recursive.get()):
                    f = f.resolve()
                    if f not in known:
                        known.add(f)
                        new.append(f)
                if not new and p not in self.groups:
                    empty.append(str(p))
                    continue
                if p not in self.groups:
                    self.groups[p] = []
                    self.order.append(("g", p))
                self.groups[p] += new
                added += len(new)
            elif p not in known:
                known.add(p)
                self.order.append(("f", p))
                added += 1
        self.populate_tree()
        self._update_stats()
        msg = f"{added} Datei(en) hinzugefügt, {len(self.all_files())} in der Liste."
        if empty:
            msg += "  Keine EPS-Dateien in: " + ", ".join(empty)
        self.set_status(msg)

    def remove_selected(self):
        if self._busy():
            return
        gone = set(self._files_of(self.tree.selection()))
        if not gone:
            return
        for folder in list(self.groups):
            self.groups[folder] = [f for f in self.groups[folder] if f not in gone]
        self.order = [(k, p) for k, p in self.order
                      if (k == "g" and self.groups[p]) or (k == "f" and p not in gone)]
        self.groups = {p: fs for p, fs in self.groups.items() if fs}
        for f in gone:
            self.results.pop(f, None)
        self.selected = None
        self.populate_tree()
        self._update_stats()

    def clear(self):
        if self._busy():
            return
        self.order.clear()
        self.groups.clear()
        self.results.clear()
        self.selected = None
        self.populate_tree()
        self._update_stats()
        self.set_status("Liste geleert.")

    # ------------------------------------------------------------ Dateiliste
    def populate_tree(self):
        tree = self.tree
        tree.delete(*tree.get_children())
        for kind, p in self.order:
            if kind == "g":
                gid = self._gid(p)
                tree.insert("", "end", iid=gid, text=f"▤  {p.name or p}", open=True, tags=("group",))
                for f in self.groups[p]:
                    tree.insert(gid, "end", iid=str(f), text=str(f.relative_to(p)))
                    self._refresh_row(f)
                self._refresh_group(p)
            else:
                tree.insert("", "end", iid=str(p), text=p.name)
                self._refresh_row(p)
        if self.order:
            self.empty_hint.place_forget()
        else:
            self.empty_hint.place(relx=0.5, rely=0.45, anchor="center")
        if self.selected and tree.exists(self.selected):
            tree.selection_set(self.selected)
        else:
            self.show_checklist()

    @staticmethod
    def _findings(res: FileResult) -> str:
        n_fail = sum(1 for c in res.checks if c.status == Status.FAIL)
        n_warn = sum(1 for c in res.checks if c.status == Status.WARN)
        parts = ([f"{n_fail} Fehler"] if n_fail else []) + ([f"{n_warn} Warnung(en)"] if n_warn else [])
        return " · ".join(parts) if parts else "alles in Ordnung"

    def _refresh_row(self, f: Path, pending: bool = False):
        iid = str(f)
        if not self.tree.exists(iid):
            return
        res = self.results.get(f)
        if res is None:
            self.tree.item(iid, values=("…  läuft" if pending else "○  offen", ""), tags=())
            return
        self.tree.item(iid, values=(f"{STATUS_GLYPH[res.status]}  {res.status.label}", self._findings(res)),
                       tags=(f"s{int(res.status)}",))

    def _refresh_group(self, folder: Path):
        gid = self._gid(folder)
        if not self.tree.exists(gid):
            return
        files = self.groups.get(folder, [])
        done = [self.results[f] for f in files if f in self.results]
        if not done:
            self.tree.item(gid, values=("○  offen", f"{len(files)} Dateien"), tags=("group",))
            return
        worst = max(r.status for r in done)
        n_ok = sum(1 for r in done if r.status <= Status.INFO)
        n_warn = sum(1 for r in done if r.status == Status.WARN)
        n_fail = sum(1 for r in done if r.status == Status.FAIL)
        info = f"{n_ok}/{len(files)} OK" + (f" · {n_fail} Fehler" if n_fail else "") + (
            f" · {n_warn} Warn." if n_warn else "")
        tags = ("group", f"s{int(worst)}") if len(done) == len(files) else ("group",)
        self.tree.item(gid, values=(f"{STATUS_GLYPH[worst]}  {worst.label}", info), tags=tags)

    def _on_select(self):
        sel = self.tree.selection()
        self.selected = sel[0] if sel else None
        self.show_checklist()

    def open_in_explorer(self):
        if not self.selected:
            return
        path = self.selected[4:] if self.selected.startswith("dir:") else self.selected
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

    # --------------------------------------------------------------- Prüfliste
    def _clear_checklist(self):
        for w in self.cl_frame.winfo_children():
            w.destroy()
        self.wrap_labels = []
        self.cl_canvas.yview_moveto(0)

    def _wrap(self, lbl: tk.Label) -> tk.Label:
        lbl.configure(wraplength=max(200, self.cl_canvas.winfo_width() - 110), justify="left")
        self.wrap_labels.append(lbl)
        return lbl

    def _header(self, title: str, subtitle: str, status: Status | None, summary: str = ""):
        t = self.t
        box = tk.Frame(self.cl_frame, bg=t.surface)
        box.pack(fill="x", pady=(0, 12))
        Badge(box, t, status, t.surface, size=40).pack(side="left", padx=(0, 12))
        txt = tk.Frame(box, bg=t.surface)
        txt.pack(side="left", fill="x", expand=True)
        self._wrap(tk.Label(txt, text=title, font=(FONT, 13, "bold"), bg=t.surface, fg=t.text,
                            anchor="w")).pack(fill="x")
        if subtitle:
            self._wrap(tk.Label(txt, text=subtitle, font=(FONT, 9), bg=t.surface, fg=t.muted,
                                anchor="w")).pack(fill="x")
        if summary:
            tk.Label(txt, text=summary, font=(FONT, 10, "bold"), bg=t.surface,
                     fg=status_color(t, status) if status is not None else t.muted,
                     anchor="w").pack(fill="x", pady=(4, 0))

    def _check_card(self, number: int, title: str, message: str, status: Status | None,
                    details: list[str], max_details: int = 6):
        t = self.t
        stripe = status_color(t, status) if status is not None else t.border
        outer, inner = card(self.cl_frame, t, stripe=stripe, pad=(12, 9))
        outer.pack(fill="x", pady=(0, 8))
        Badge(inner, t, status, t.surface).pack(side="left", anchor="n", padx=(0, 12))
        col = tk.Frame(inner, bg=t.surface)
        col.pack(side="left", fill="x", expand=True)
        head = tk.Frame(col, bg=t.surface)
        head.pack(fill="x")
        tk.Label(head, text=f"{number:02d}", font=(FONT, 9, "bold"), bg=t.surface,
                 fg=t.muted).pack(side="left", padx=(0, 8))
        tk.Label(head, text=title, font=(FONT, 11, "bold"), bg=t.surface, fg=t.text).pack(side="left")
        if status is not None:
            tk.Label(head, text=status.label.upper(), font=(FONT, 8, "bold"),
                     bg=mix(t.surface, stripe, 0.16), fg=stripe, padx=8, pady=1).pack(side="right")
        self._wrap(tk.Label(col, text=message, font=(FONT, 10), bg=t.surface, fg=t.text,
                            anchor="w")).pack(fill="x", pady=(3, 0))
        if details:
            box = tk.Frame(col, bg=t.surface)
            box.pack(fill="x", pady=(4, 0))
            self._details(box, details, max_details)

    def _details(self, box: tk.Frame, details: list[str], limit: int):
        t = self.t
        for w in box.winfo_children():
            w.destroy()
        for d in details[:limit]:
            self._wrap(tk.Label(box, text="•  " + d, font=(FONT, 9), bg=t.surface, fg=t.muted,
                                anchor="w")).pack(fill="x")
        rest = len(details) - limit
        if rest > 0:
            more = tk.Label(box, text=f"▸  {rest} weitere anzeigen", font=(FONT, 9, "underline"),
                            bg=t.surface, fg=t.accent, cursor="hand2", anchor="w")
            more.pack(fill="x", pady=(2, 0))
            more.bind("<Button-1>", lambda e: self._details(box, details, len(details)))

    def show_checklist(self):
        if not hasattr(self, "cl_frame") or not self.cl_frame.winfo_exists():
            return
        self._clear_checklist()
        sel = self.selected
        if sel and sel.startswith("dir:"):
            self._checklist_group(Path(sel[4:]))
        elif sel and Path(sel) in self.results:
            self._checklist_file(self.results[Path(sel)])
        else:
            self._checklist_empty(Path(sel) if sel else None)

    def _checklist_empty(self, f: Path | None):
        s = self._settings()
        if f:
            self._header(f.name, str(f), None, "Noch nicht geprüft")
        else:
            self._header("Prüfkriterien", "Datei oder Projekt in der Liste wählen, um das Ergebnis zu sehen.",
                         None)
        for i, key in enumerate(CHECK_ORDER, 1):
            desc = CHECK_DESCRIPTIONS[key].format(min=f"{s.min_dpi:g}", max=f"{s.max_dpi:g}")
            self._check_card(i, CHECK_TITLES[key], desc, None, [])

    def _checklist_file(self, res: FileResult):
        n_fail = sum(1 for c in res.checks if c.status == Status.FAIL)
        n_warn = sum(1 for c in res.checks if c.status == Status.WARN)
        summary = {Status.FAIL: f"{n_fail} von {len(res.checks)} Prüfungen nicht bestanden",
                   Status.WARN: f"Bestanden mit {n_warn} Warnung(en)"}.get(res.status, "Alle Prüfungen bestanden")
        self._header(res.path.name, str(res.path), res.status, summary)
        by_key = {c.key: c for c in res.checks}
        for i, key in enumerate(CHECK_ORDER, 1):
            c = by_key.get(key)
            if c:
                self._check_card(i, c.title, c.message, c.status, c.details)
            else:
                self._check_card(i, CHECK_TITLES[key], "Nicht geprüft (Datei nicht auswertbar)", None, [])

    def _checklist_group(self, folder: Path):
        files = self.groups.get(folder, [])
        done = [self.results[f] for f in files if f in self.results]
        worst = max((r.status for r in done), default=None)
        n_ok = sum(1 for r in done if r.status <= Status.INFO)
        summary = (f"{len(done)} von {len(files)} geprüft · {n_ok} OK · "
                   f"{sum(1 for r in done if r.status == Status.WARN)} Warnung · "
                   f"{sum(1 for r in done if r.status == Status.FAIL)} Fehler") if done else "Noch nicht geprüft"
        self._header(f"Projekt {folder.name}", f"{folder}  ·  {len(files)} EPS-Datei(en)", worst, summary)
        s = self._settings()
        for i, key in enumerate(CHECK_ORDER, 1):
            checks = [(r, c) for r in done if (c := r.check(key))]
            if not checks:
                desc = CHECK_DESCRIPTIONS[key].format(min=f"{s.min_dpi:g}", max=f"{s.max_dpi:g}")
                self._check_card(i, CHECK_TITLES[key], desc, None, [])
                continue
            n_fail = sum(1 for _, c in checks if c.status == Status.FAIL)
            n_warn = sum(1 for _, c in checks if c.status == Status.WARN)
            top = max(c.status for _, c in checks)
            parts = ([f"{n_fail} Datei(en) mit Fehler"] if n_fail else []) + (
                [f"{n_warn} mit Warnung"] if n_warn else [])
            msg = ", ".join(parts) if parts else f"Alle {len(checks)} Dateien in Ordnung"
            details = [f"{STATUS_GLYPH[c.status]}  {r.path.relative_to(folder)} – {c.message}"
                       for r, c in sorted(checks, key=lambda rc: -rc[1].status) if c.status >= Status.WARN]
            self._check_card(i, checks[0][1].title, msg, top, details)

    # ------------------------------------------------------------------ Prüfen
    def _busy(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def _settings(self) -> Settings:
        def num(var, default):
            try:
                return float(var.get())
            except (tk.TclError, ValueError):
                return default

        return Settings(min_dpi=num(self.var_min, 80.0), max_dpi=num(self.var_max, 150.0),
                        rgb_is_error=self.var_rgb.get(), gray_black_is_error=self.var_gray.get(),
                        gs_executable=self.gs_path or "")

    def start_check(self, selection_only: bool = False):
        if self._busy():
            self.cancel.set()
            self.set_status("Wird abgebrochen …")
            return
        if not self.order:
            messagebox.showinfo(APP_TITLE, "Bitte zuerst einzelne EPS-Dateien oder einen Ordner hinzufügen.")
            return
        files = self._files_of(self.tree.selection()) if selection_only else self.all_files()
        if not files:
            messagebox.showinfo(APP_TITLE, "Bitte in der Liste zuerst Dateien oder ein Projekt markieren "
                                           "(mehrere mit Strg- bzw. Umschalt-Klick).")
            return
        if not self.gs_path:
            self._warn_no_gs()
        settings = self._settings()
        self.run_files = files
        self.cancel.clear()
        for f in files:
            self.results.pop(f, None)
            self._refresh_row(f, pending=True)
        for folder in self.groups:
            self._refresh_group(folder)
        self._update_stats()
        self.show_checklist()
        self.progress.configure(maximum=len(files), value=0)
        self._set_running(True)

        def work():
            for i, f in enumerate(files):
                if self.cancel.is_set():
                    break
                self.queue.put(("progress", i, f))
                try:
                    res = check_file(f, settings)
                except Exception as exc:  # unerwarteter Fehler: Datei markieren, weiterprüfen
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
                    self.set_status(f"Prüfe {i + 1}/{len(self.run_files)}: {payload.name}")
                elif kind == "result":
                    self._on_result(payload)
                    self.progress.configure(value=i + 1)
                elif kind == "done":
                    self._finished()
                    return
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _on_result(self, res: FileResult):
        self.results[res.path] = res
        self._refresh_row(res.path)
        parent = self.tree.parent(str(res.path)) if self.tree.exists(str(res.path)) else ""
        if parent:
            self._refresh_group(Path(parent[4:]))
        self._update_stats()
        if self.selected is None:
            self.tree.selection_set(str(res.path))
        elif self.selected in (str(res.path), parent):
            self.show_checklist()

    def _finished(self):
        self._set_running(False)
        res = [self.results[f] for f in self.run_files if f in self.results]
        ok = sum(1 for r in res if r.status <= Status.INFO)
        warn = sum(1 for r in res if r.status == Status.WARN)
        fail = sum(1 for r in res if r.status == Status.FAIL)
        prefix = "Abgebrochen. " if self.cancel.is_set() else "Fertig. "
        self.set_status(f"{prefix}{len(res)} geprüft: {ok} OK, {warn} mit Warnung, {fail} fehlerhaft")

    # ------------------------------------------------------------ Dialoge etc.
    def ask_files(self):
        paths = filedialog.askopenfilenames(title="EPS-Dateien wählen", filetypes=EPS_TYPES,
                                            initialdir=self.cfg.get("last_dir"))
        if paths:
            self.cfg["last_dir"] = str(Path(paths[0]).parent)
            self.add_paths(paths)

    def ask_folder(self):
        folder = filedialog.askdirectory(title="Ordner / Projekt mit EPS-Dateien wählen",
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
            self.gs_version = ghostscript_version(path)
            self.cfg["gs_executable"] = path
            self.build()

    def _warn_no_gs(self):
        messagebox.showwarning(
            APP_TITLE,
            "Ghostscript wurde nicht gefunden.\n\n"
            "Der EPS-Prüfer benötigt die kostenlose Ghostscript-Kommandozeile (gswin64c.exe).\n\n"
            "Download: https://ghostscript.com/releases/gsdnld.html\n\n"
            "Nach der Installation neu starten oder unter Einstellungen → Ghostscript → „Ändern …“ "
            "den Pfad angeben.",
        )

    def save_report(self):
        results = [self.results[f] for f in self.all_files() if f in self.results]
        if not results:
            messagebox.showinfo(APP_TITLE, "Es liegen noch keine Prüfergebnisse vor.")
            return
        path = filedialog.asksaveasfilename(
            title="Prüfbericht speichern", defaultextension=".html", initialfile="EPS-Pruefbericht.html",
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
        self.set_status(f"Bericht gespeichert: {path}")
        if sys.platform == "win32" and path.lower().endswith(".html"):
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except OSError:
                pass

    def show_help(self):
        s = self._settings()
        messagebox.showinfo(
            f"{APP_TITLE} {__version__}",
            "Prüfliste:\n"
            "01  Datei / PostScript – lesbar, fehlerfrei, Schriften eingebettet\n"
            "02  Schwarz in CMYK – Schwarz darf nicht RGB sein\n"
            "03  Pixeldaten eingebettet – keine OPI-/DCS-/Datei-Verknüpfungen\n"
            f"04  Auflösung – alle Bilder zwischen {s.min_dpi:g} und {s.max_dpi:g} dpi\n"
            "05  Kein Überdrucken\n"
            "06  Hintergrundfläche – unterstes Objekt ist eine deckende Farbfläche (Warnung, wenn sie fehlt oder transparent ist)\n\n"
            "Bedienung:\n"
            "• „Einzelne Dateien“ oder „Ordner / Projekt“ hinzufügen\n"
            "• „Alle prüfen“ oder nur die markierten Einträge mit „Auswahl prüfen“\n"
            "• Klick auf Datei/Projekt zeigt rechts die Prüfliste\n"
            "• ☾/☀ schaltet zwischen Dunkel- und Hellmodus um",
        )

    def _on_close(self):
        self.cancel.set()
        s = self._settings()
        self.cfg.update(min_dpi=s.min_dpi, max_dpi=s.max_dpi, rgb_is_error=s.rgb_is_error,
                        gray_black_is_error=s.gray_black_is_error, recursive=self.var_recursive.get(),
                        theme=self.t.name, geometry_v2=self.root.geometry())
        if self.gs_path:
            self.cfg["gs_executable"] = self.gs_path
        save_config(self.cfg)
        self.root.destroy()


def main(argv: list[str] | None = None) -> int:
    if sys.platform == "win32":
        try:
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
