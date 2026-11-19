"""Browse and edit the native USA Crash resources without an emulator connection."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from editor.catalog import traffic_catalog
from resources.crash_events import bgd_path, load_crash_events
from resources.native_edit import export_resources, prepare_changes
from resources.native_iso import export_iso
from resources.native_roads import read_roads
from resources.native_traffic import read_groups


class NativeEventsWindow(tk.Toplevel):
    def __init__(self, parent, current_identity):
        super().__init__(parent)
        self.title("Burnout 3 — Eventos nativos de Crash")
        self.geometry("940x600")
        self.minsize(730, 480)
        self.current_identity = current_identity
        self.game = None
        self.events = {}
        self.event = None
        self.drafts = {}
        self.exported = {}
        self.track = None
        self.roads = {}
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.job = None
        self.labels = {m["asset_id"]: m["category_label"] for m in traffic_catalog()}
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        bar = ttk.Frame(self, padding=8)
        bar.grid(row=0, column=0, sticky="ew")
        ttk.Button(bar, text="Abrir pasta do jogo…", command=self.choose_folder).pack(side="left")
        ttk.Button(bar, text="Localizar evento da sessão", command=self.locate).pack(side="left", padx=6)
        self.source = tk.StringVar(value="Escolha a pasta que contém DATA e TRACKS.")
        ttk.Label(bar, textvariable=self.source).pack(side="left", padx=6)
        pane = ttk.Panedwindow(self, orient="horizontal")
        pane.grid(row=1, column=0, sticky="nsew", padx=8)
        left = ttk.Frame(pane)
        left.rowconfigure(2, weight=1)
        left.columnconfigure(0, weight=1)
        ttk.Label(left, text="Buscar evento ou pista").grid(row=0, column=0, sticky="w")
        self.query = tk.StringVar()
        ttk.Entry(left, textvariable=self.query).grid(row=1, column=0, sticky="ew", pady=(3, 5))
        self.event_list = ttk.Treeview(left, columns=("title", "track"), show="headings",
                                       selectmode="browse")
        for key, label, width in (("title", "Evento", 160), ("track", "Pista", 85)):
            self.event_list.heading(key, text=label)
            self.event_list.column(key, width=width, minwidth=50)
        self.event_list.grid(row=2, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(left, command=self.event_list.yview)
        scroll.grid(row=2, column=1, sticky="ns")
        self.event_list.configure(yscrollcommand=scroll.set)
        pane.add(left, weight=2)
        right = ttk.Frame(pane, padding=(10, 0, 0, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        self.heading = tk.StringVar(value="Selecione um evento")
        ttk.Label(right, textvariable=self.heading).grid(row=0, column=0, sticky="w", pady=(0, 5))
        tabs = ttk.Notebook(right)
        tabs.grid(row=1, column=0, sticky="nsew")
        edit = ttk.Frame(tabs, padding=8)
        edit.columnconfigure(0, weight=1)
        edit.rowconfigure(0, weight=1)
        tabs.add(edit, text="Tráfego e metas")
        self.models = ttk.Treeview(edit, columns=("group", "slot", "type", "model"),
                                   show="headings", selectmode="extended", height=7)
        for key, label, width in (("group", "Grupo", 42), ("slot", "Ordem", 45),
                                 ("type", "Tipo", 142), ("model", "Modelo", 90)):
            self.models.heading(key, text=label)
            self.models.column(key, width=width, minwidth=35)
        self.models.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(edit, command=self.models.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.models.configure(yscrollcommand=scroll.set)
        ttk.Button(edit, text="Trocar dois modelos do mesmo grupo", command=self.swap).grid(
            row=1, column=0, sticky="w", pady=5)
        limits = ttk.Frame(edit)
        limits.grid(row=2, column=0, sticky="ew", pady=(5, 0))
        self.fields = []
        for i, label in enumerate(("Ouro ($)", "Prata ($)", "Bronze ($)")):
            limits.columnconfigure(i, weight=1)
            ttk.Label(limits, text=label).grid(row=0, column=i, sticky="w")
            entry = ttk.Entry(limits, width=10, state="disabled")
            entry.grid(row=1, column=i, sticky="ew", padx=(0, 4))
            self.fields.append(entry)
        self.limit_note = tk.StringVar()
        ttk.Label(edit, textvariable=self.limit_note, wraplength=440).grid(row=3, column=0, sticky="w")
        breaker = ttk.Frame(edit)
        breaker.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(breaker, text="Batidas para o Crashbreaker (6 a 15)").pack(side="left")
        self.crash_count = ttk.Entry(breaker, width=5, state="disabled")
        self.crash_count.pack(side="left", padx=6)
        self.crash_note = tk.StringVar()
        ttk.Label(edit, textvariable=self.crash_note, wraplength=440).grid(row=5, column=0, sticky="w")
        maps = ttk.Frame(tabs)
        tabs.add(maps, text="Caminhos da pista")
        self.map_info = tk.StringVar()
        ttk.Label(maps, textvariable=self.map_info, padding=5).pack(anchor="w")
        self.canvas = tk.Canvas(maps, background="#f4f6f7", highlightthickness=0)
        self.canvas.pack(expand=True, fill="both")
        self.canvas.bind("<Configure>", lambda _: self.draw())
        pane.add(right, weight=3)
        footer = ttk.Frame(self, padding=8)
        footer.grid(row=2, column=0, sticky="ew")
        self.status = tk.StringVar()
        ttk.Label(footer, textvariable=self.status, wraplength=440).pack(side="left", fill="x", expand=True)
        ttk.Button(footer, text="Exportar arquivos…", command=lambda: self.export(False)).pack(side="left")
        ttk.Button(footer, text="Gerar cópia ISO…", command=lambda: self.export(True)).pack(side="left", padx=(6, 0))
        self.event_list.bind("<<TreeviewSelect>>", lambda _: self.select())
        self.query.trace_add("write", lambda *_: self.filter_events())
        self.protocol("WM_DELETE_WINDOW", self.close)
        local = Path(__file__).resolve().parents[3] / "Burnout 3 - Takedown (USA)"
        if (local / "DATA" / "STAGEHED.BIN").is_file():
            self.after_idle(lambda: self.open_game(local))

    def close(self):
        if self.job is not None:
            self.status.set("Aguarde a conclusão da operação em andamento.")
            self.lift()
            return False
        if not self.can_discard():
            return False
        self.worker.shutdown(wait=False)
        self.destroy()
        return True

    def can_discard(self):
        self.remember_draft()
        if any(draft != self.exported.get(key) for key, draft in self.drafts.items()):
            return messagebox.askyesno("Eventos nativos", "Descartar as edições que ainda não foram exportadas?",
                                       parent=self)
        return True

    def run(self, message, action, success):
        if self.job is not None:
            return
        self.status.set(message)
        self.job = self.worker.submit(action)
        def check():
            if not self.job.done():
                self.after(80, check)
                return
            job, self.job = self.job, None
            try:
                success(job.result())
            except Exception as exc:
                self.status.set(str(exc))
                messagebox.showerror("Eventos nativos", str(exc), parent=self)
        self.after(80, check)

    def choose_folder(self):
        if self.job is not None:
            return
        selected = filedialog.askdirectory(parent=self, title="Pasta extraída com DATA e TRACKS")
        if selected:
            self.open_game(Path(selected))

    def open_game(self, folder):
        def loaded(events):
            if not self.can_discard():
                self.status.set("A pasta e as edições atuais foram mantidas.")
                return
            self.game = folder
            self.event = self.track = None
            self.events.clear()
            if self.query.get():
                self.query.set("")
            self.drafts.clear()
            self.exported.clear()
            self.events = {e.key: e for e in events}
            active = self.current_identity() or {}
            key = active.get("event_key")
            if key not in self.events:
                key = next((e.key for e in events if e.title == "Grand Slam"), events[0].key)
            self.source.set(f"{len(events)} eventos de Crash · {folder.name}")
            self.status.set("Selecione dois modelos do mesmo grupo com Ctrl para trocar a ordem.")
            self.filter_events(key)
        self.run("Lendo o catálogo de Crash…", lambda: load_crash_events(folder), loaded)

    def focus_event(self, key):
        self.event_list.selection_set(key)
        self.event_list.focus(key)
        self.event_list.see(key)
        self.select()

    def locate(self):
        key = (self.current_identity() or {}).get("event_key")
        if key not in self.events:
            self.status.set("Abra a pasta do jogo e atualize a lista da sessão com o evento pausado.")
            return
        self.query.set("")
        self.focus_event(key)

    def filter_events(self, preferred=None):
        word = self.query.get().strip().casefold()
        self.event_list.delete(*self.event_list.get_children())
        for key, event in self.events.items():
            if word in f"{event.title} {event.track} {key}".casefold():
                self.event_list.insert("", "end", iid=key, values=(event.title, event.track))
        if preferred and self.event_list.exists(preferred):
            self.focus_event(preferred)
        elif self.event and self.event_list.exists(self.event.key):
            self.event_list.selection_set(self.event.key)
        elif self.event_list.get_children():
            self.focus_event(self.event_list.get_children()[0])
        else:
            self.clear_event()

    def get_draft(self):
        return self.orders, tuple(entry.get() for entry in self.fields), self.crash_count.get()

    def remember_draft(self):
        if self.event:
            draft = self.get_draft()
            if draft != self.initial:
                self.drafts[self.event.key] = draft
            else:
                self.drafts.pop(self.event.key, None)

    def clear_event(self):
        self.remember_draft()
        self.event = None
        self.heading.set("Selecione um evento")
        self.models.delete(*self.models.get_children())
        for entry in (*self.fields, self.crash_count):
            entry.configure(state="normal")
            entry.delete(0, "end")
            entry.configure(state="disabled")
        self.limit_note.set("")
        self.crash_note.set("")
        self.map_info.set("")
        self.canvas.delete("all")

    def select(self):
        rows = self.event_list.selection()
        if not rows or (self.event and self.event.key == rows[0]):
            return
        event = self.events[rows[0]]
        self.clear_event()
        try:
            path = bgd_path(self.game, event.track)
            orders = read_groups(path.read_bytes(), event.event_offset)
            if self.track != event.track:
                self.roads = read_roads(path, max_samples_per_path=64)
                self.track = event.track
        except (OSError, ValueError) as exc:
            self.status.set(str(exc))
            return
        self.event = event
        wrecks = event.crashbreaker_wrecks
        self.initial = orders, tuple(format(n, ".9g") for n in event.thresholds), str(wrecks) if wrecks is not None else ""
        self.orders, fields, count = self.drafts.get(event.key, self.initial)
        self.heading.set(f"{event.title}  ·  {event.track}  ·  {event.key}")
        self.fill_models()
        aligned = event.thresholds == event.bgd_thresholds
        for entry, value in zip(self.fields, fields):
            entry.configure(state="normal")
            entry.insert(0, value)
            entry.configure(state="normal" if aligned else "readonly")
        self.limit_note.set("Digite as metas em dólares inteiros." if aligned else
                            "As metas da pista e do catálogo divergem. Os valores originais serão preservados.")
        supported = wrecks is not None and 6 <= wrecks <= 15 and wrecks == event.bgd_crashbreaker_wrecks
        self.crash_count.configure(state="normal")
        self.crash_count.insert(0, count)
        self.crash_count.configure(state="normal" if supported else "readonly")
        self.crash_note.set("" if supported else "Contagem de batidas sem confirmação nas duas tabelas.")
        self.map_info.set(f"{self.roads['path_count']} caminhos de tráfego da pista · vista X/Z")
        self.draw()

    def fill_models(self):
        self.models.delete(*self.models.get_children())
        for g, names in enumerate(self.orders):
            for i, name in enumerate(names):
                self.models.insert("", "end", iid=f"{g}/{i}", values=(g + 1, i + 1, self.labels[name], name))

    def swap(self):
        selection = self.models.selection()
        if not self.event or len(selection) != 2:
            self.status.set("Selecione duas linhas de modelos com Ctrl.")
            return
        (g, a), (other, b) = [map(int, row.split("/")) for row in selection]
        if g != other:
            self.status.set("Escolha modelos com o mesmo número de grupo.")
            return
        rows = [list(row) for row in self.orders]
        rows[g][a], rows[g][b] = rows[g][b], rows[g][a]
        self.orders = tuple(tuple(row) for row in rows)
        self.fill_models()
        self.models.selection_set(selection)
        self.status.set("Ordem alterada neste evento. Exporte para guardar a edição.")

    def draw(self):
        self.canvas.delete("all")
        if not self.event or not self.roads:
            return
        lines = [p["center"] for p in self.roads["paths"]]
        x = [p[0] for line in lines for p in line]
        z = [p[2] for line in lines for p in line]
        x0, x1, z0, z1 = min(x), max(x), min(z), max(z)
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if min(w, h) < 24:
            return
        scale = min((w - 20) / max(1, x1 - x0), (h - 20) / max(1, z1 - z0))
        for line in lines:
            coords = []
            for px, _, pz in line:
                coords.extend((w / 2 + (px - (x0 + x1) / 2) * scale,
                               h / 2 - (pz - (z0 + z1) / 2) * scale))
            self.canvas.create_line(*coords, fill="#396a78", width=1.5)

    def export(self, to_iso):
        if not self.event or self.job is not None:
            return
        event, game = self.event, self.game
        orders, fields, count = self.get_draft()
        expected_orders = self.initial[0]
        try:
            goals = tuple(map(int, fields)) if fields != self.initial[1] else None
        except ValueError:
            self.status.set("Use números inteiros para as metas.")
            return
        wrecks = None
        if count != self.initial[2]:
            try:
                wrecks = int(count)
            except ValueError:
                pass
            if wrecks is None or not 6 <= wrecks <= 15:
                self.status.set("Use um número inteiro de 6 a 15 para o Crashbreaker.")
                return
        if goals is None and wrecks is None and orders == expected_orders:
            self.status.set("Altere a ordem dos modelos, uma meta ou as batidas para o Crashbreaker.")
            return
        if to_iso:
            source = filedialog.askopenfilename(parent=self, title="Selecione a ISO correspondente à extração",
                                                initialdir=game.parent, filetypes=[("ISO", "*.iso")])
            if not source:
                return
            dest = filedialog.asksaveasfilename(parent=self, title="Escolha um novo arquivo ISO", initialdir=game.parent,
                    initialfile=event.title + " - editado.iso", defaultextension=".iso", filetypes=[("ISO", "*.iso")])
        else:
            dest = filedialog.askdirectory(parent=self, title="Pasta para receber uma nova subpasta com os arquivos editados")
        if not dest:
            return
        def write():
            changes = prepare_changes(game, event, orders, goals, expected_orders=expected_orders,
                                      crashbreaker_wrecks=wrecks)
            if to_iso:
                export_iso(Path(source), Path(dest), changes)
                return Path(dest)
            return export_resources(game, Path(dest), event, changes)
        def saved(path):
            self.exported[event.key] = (orders, fields, count)
            self.status.set(f"{event.title} · cópia verificada em {path}")
            messagebox.showinfo("Exportação concluída", f"{event.title}\n\n{path}", parent=self)
        self.run("Gravando e verificando a cópia…", write, saved)
