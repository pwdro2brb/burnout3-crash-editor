"""Browse and edit the native USA Crash resources without an emulator connection."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import math
import os
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from editor import theme
from editor.catalog import traffic_catalog
from resources.crash_events import bgd_path, load_crash_events
from resources.model_swap import (
    CANDIDATES, GROUP_LABELS, MAX_MODELS, add_models, budget, can_add, candidates_for, group_of,
    rename_schedule, replace_models, tram_models,
)
from resources.native_edit import export_resources, prepare_changes
from resources.native_iso import export_iso
from resources.native_roads import point_at_distance, read_roads
from resources.native_traffic import read_groups
from resources.traffic_waves import (
    DENSITY_CRASH, DENSITY_WARNING, TRAILER_GROUP, TRAM_GROUP, TRUCK_TYPE, TYPE_NAMES, TrafficWave, WaveLane,
    WaveVehicle, density_warning, lane_speed, loaded_models, read_waves, vehicle_total, vehicle_type_for,
    waves_from_dict, waves_to_dict, with_lane_speed, write_waves,
)

WAVE_HELP = ("A wave loads traffic at a fixed time (wave 1 when the event starts). In each lane, cars "
             "\"on the road\" appear when the wave loads; cars that \"drive in later\" enter at the lane's "
             "entry point at their time.")
LANE_COLOURS = theme.LANE_COLOURS
EMPTY_HINT = ("Select a wave, a lane or a vehicle in the list on the left. "
              "Tip: select a lane and use \"Add several\" to fill it quickly.")
KMH_PER_SPEED_UNIT = 1.609344  # the game's speed values read as miles per hour (nominal)
NOT_LOADED = " — not loaded yet"
PLAY_NOTE = ("To test it, start THIS new ISO in PCSX2 (System → Boot ISO) and enter the event from the "
             "game menu. A savestate made with the original ISO brings the old event back.")


class NativeEventsWindow(tk.Toplevel):
    def __init__(self, parent, current_identity):
        super().__init__(parent)
        theme.apply(self)
        self.title("Burnout 3 — Crash events on the disc (waves, models, goals)")
        self.geometry("1280x900")
        self.minsize(900, 640)
        self.configure(background=theme.PALETTE["bg"])
        self.current_identity = current_identity
        self.game = None
        self.events = {}
        self.event = None
        self.drafts = {}
        self.exported = {}
        self.track = None
        self.track_bytes = None
        self.track_draft = None
        self.roads = {}
        self.schedule = None
        self.swaps = ()
        self.additions = ()
        self.wave_error = ""
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.job = None
        self.progress_state = None
        self.map_view = None
        self.map_focus = None
        self.map_drag = None
        self.picking_lane = False
        self.lane_choices = {}
        self.model_choices = {}
        self.labels = {m["asset_id"]: m["category_label"] for m in traffic_catalog()}
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        bar = ttk.Frame(self, style="Header.TFrame", padding=(16, 10))
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(2, weight=1)
        ttk.Label(bar, text="BURNOUT 3", style="HeaderAccent.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(bar, text="  Crash events on the disc", style="Header.TLabel").grid(row=0, column=1, sticky="w")
        self.source = tk.StringVar(value="Choose the folder that contains DATA and TRACKS.")
        ttk.Label(bar, textvariable=self.source, style="HeaderMuted.TLabel").grid(
            row=0, column=2, sticky="w", padx=(16, 0))
        ttk.Button(bar, text="Open game folder…", style="Header.TButton",
                   command=self.choose_folder).grid(row=0, column=3, padx=(6, 0))
        ttk.Button(bar, text="Find session event", style="Header.TButton",
                   command=self.locate).grid(row=0, column=4, padx=(6, 0))
        pane = ttk.Panedwindow(self, orient="horizontal")
        pane.grid(row=1, column=0, sticky="nsew", padx=12, pady=12)
        left = theme.card(pane, padding=10)
        left.rowconfigure(2, weight=1)
        left.columnconfigure(0, weight=1)
        ttk.Label(left, text="Events", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.query = tk.StringVar()
        ttk.Entry(left, textvariable=self.query).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 6))
        self.event_list = ttk.Treeview(left, columns=("title", "track"), show="headings",
                                       selectmode="browse")
        for key, label, width in (("title", "Event", 160), ("track", "Track", 85)):
            self.event_list.heading(key, text=label)
            self.event_list.column(key, width=width, minwidth=50)
        self.event_list.grid(row=2, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(left, command=self.event_list.yview)
        scroll.grid(row=2, column=1, sticky="ns")
        self.event_list.configure(yscrollcommand=scroll.set)
        ttk.Label(left, text="Type to search by event, track or key.", style="CardMuted.TLabel").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        pane.add(left.outer, weight=1)
        right = ttk.Frame(pane, padding=(10, 0, 0, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        self.heading = tk.StringVar(value="Select an event")
        ttk.Label(right, textvariable=self.heading, style="Title.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6))
        tabs = ttk.Notebook(right)
        tabs.grid(row=1, column=0, sticky="nsew")
        self.tabs = tabs
        self.build_waves_tab(tabs)
        self.build_models_tab(tabs)
        maps = ttk.Frame(tabs, style="Card.TFrame", padding=10)
        tabs.add(maps, text="Track paths")
        self.map_info = tk.StringVar()
        ttk.Label(maps, textvariable=self.map_info, style="CardMuted.TLabel").pack(anchor="w", pady=(0, 6))
        self.canvas = tk.Canvas(maps, background=theme.PALETTE["map_bg"], highlightthickness=0)
        self.canvas.pack(expand=True, fill="both")
        self.canvas.bind("<Configure>", lambda _: self.draw())
        pane.add(right, weight=4)
        footer = theme.card(self, padding=(14, 10), row=2, column=0, sticky="ew", padx=12, pady=(0, 12))
        footer.columnconfigure(0, weight=1)
        self.status = tk.StringVar()
        ttk.Label(footer, textvariable=self.status, style="Card.TLabel", wraplength=760).grid(
            row=0, column=0, sticky="w")
        ttk.Label(footer, text="Edits are tested by booting the new ISO; savestates keep the old event.",
                  style="CardMuted.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Button(footer, text="Export files…", command=lambda: self.export(False)).grid(
            row=0, column=1, rowspan=2)
        ttk.Button(footer, text="Build ISO copy…", style="Accent.TButton",
                   command=lambda: self.export(True)).grid(row=0, column=2, rowspan=2, padx=(6, 0))
        self.event_list.bind("<<TreeviewSelect>>", lambda _: self.select())
        self.query.trace_add("write", lambda *_: self.filter_events())
        self.protocol("WM_DELETE_WINDOW", self.close)
        local = Path(__file__).resolve().parents[3] / "Burnout 3 - Takedown (USA)"
        if (local / "DATA" / "STAGEHED.BIN").is_file():
            self.after_idle(lambda: self.open_game(local))

    # --- models and goals tab ---------------------------------------------------

    def build_models_tab(self, tabs):
        edit = ttk.Frame(tabs, style="Card.TFrame", padding=12)
        edit.columnconfigure(0, weight=1)
        edit.rowconfigure(1, weight=1)
        tabs.add(edit, text="Models and goals")
        self.models_page = edit
        ttk.Label(edit, style="CardMuted.TLabel", wraplength=760, justify="left",
                  text="The game loads these traffic models for the event (12 at most). Replace one with a "
                       "model that other events use in the same group, or add one: the waves can then use "
                       "it, and so can the live editor once you play the edited ISO.").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.models = ttk.Treeview(edit, columns=("group", "slot", "model", "type", "note"),
                                   show="headings", selectmode="extended", height=9)
        for key, label, width in (("group", "Group", 150), ("slot", "#", 30), ("model", "Model", 100),
                                  ("type", "Type", 130), ("note", "Change", 170)):
            self.models.heading(key, text=label)
            self.models.column(key, width=width, minwidth=30)
        self.models.tag_configure("swapped", foreground=theme.PALETTE["accent"])
        self.models.tag_configure("added", foreground=theme.PALETTE["ok"])
        self.models.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(edit, command=self.models.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.models.configure(yscrollcommand=scroll.set)
        self.models.bind("<<TreeviewSelect>>", lambda _: self.model_selected())
        self.model_budget = tk.StringVar()
        ttk.Label(edit, textvariable=self.model_budget, style="Info.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        swap_row = ttk.Frame(edit, style="Card.TFrame")
        swap_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(swap_row, text="Replace selected with", style="Card.TLabel").pack(side="left")
        self.replacement = ttk.Combobox(swap_row, state="readonly", width=30)
        self.replacement.pack(side="left", padx=6)
        self.replace_button = ttk.Button(swap_row, text="Replace model", style="Accent.TButton",
                                         command=self.replace_model)
        self.replace_button.pack(side="left")
        ttk.Button(swap_row, text="Swap order of two (same group)", command=self.swap).pack(side="right")
        add_row = ttk.Frame(edit, style="Card.TFrame")
        add_row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(add_row, text="Add a model to the event", style="Card.TLabel").pack(side="left")
        self.addition = ttk.Combobox(add_row, state="readonly", width=34)
        self.addition.pack(side="left", padx=6)
        ttk.Button(add_row, text="+ Add model", command=self.add_model).pack(side="left")
        ttk.Button(add_row, text="Remove added model", command=self.remove_added_model).pack(side="right")
        limits = theme.card(edit, padding=12, row=5, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Label(limits, text="Goals and Crashbreaker", style="Section.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))
        self.fields = []
        for i, label in enumerate(("Gold ($)", "Silver ($)", "Bronze ($)")):
            limits.columnconfigure(i, weight=1)
            ttk.Label(limits, text=label, style="CardMuted.TLabel").grid(row=1, column=i, sticky="w")
            entry = ttk.Entry(limits, width=10, state="disabled")
            entry.grid(row=2, column=i, sticky="ew", padx=(0, 6))
            self.fields.append(entry)
        ttk.Label(limits, text="Wrecks for Crashbreaker (6–15)", style="CardMuted.TLabel").grid(
            row=1, column=3, sticky="w")
        self.crash_count = ttk.Entry(limits, width=5, state="disabled")
        self.crash_count.grid(row=2, column=3, sticky="w")
        self.limit_note = tk.StringVar()
        ttk.Label(limits, textvariable=self.limit_note, style="CardMuted.TLabel", wraplength=700).grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.crash_note = tk.StringVar()
        ttk.Label(limits, textvariable=self.crash_note, style="Warning.TLabel", wraplength=700).grid(
            row=4, column=0, columnspan=4, sticky="w")

    def _trams(self):
        return tram_models(self.schedule) if self.schedule is not None else ()

    def _model_root(self):
        """The game folder when it holds the model files (sizes are checked), else None."""
        return self.game if self.game is not None and (Path(self.game) / "PVEH").is_dir() else None

    def _refresh_models_controls(self):
        """Budget line and the list of models that can still be added."""
        if not self.event:
            self.model_budget.set("")
            self.addition.configure(values=())
            self.addition.set("")
            return
        room = budget(self.orders, self._trams(), self._model_root())
        size = f" · {room['bytes'] // 1024} of {room['max_bytes'] // 1024} KB" if room["bytes"] is not None else ""
        self.model_budget.set(f"This event loads {room['models']} of {room['max_models']} models{size} "
                              "(the KB limit is the largest set an original event loads).")
        options = []
        for group, names in enumerate(CANDIDATES):
            for model in names:
                if not any(model in loaded for loaded in self.orders):
                    reason = can_add(self.orders, model, self._trams(), self._model_root())
                    options.append(f"{model} · {self.labels.get(model, '?')} · {GROUP_LABELS[group]}"
                                   + ("" if reason is None else " (cannot add)"))
        self.addition.configure(values=options)
        if self.addition.get() not in options:
            self.addition.set(next((o for o in options if not o.endswith("(cannot add)")), ""))

    def model_selected(self):
        rows = self.models.selection()
        if not self.event or len(rows) != 1:
            self.replacement.configure(values=())
            self.replacement.set("")
            return
        group, index = map(int, rows[0].split("/"))
        name = self.orders[group][index]
        options = [f"{model} · {self.labels.get(model, '?')}" for model in candidates_for(self.orders, name)]
        self.replacement.configure(values=options)
        self.replacement.set(options[0] if options else "")

    def _set_models(self, orders, swaps, additions, renames=None):
        """Apply a model change to the draft: groups, schedule names and the draft track."""
        self.orders = tuple(tuple(names) for names in orders)
        self.swaps = tuple(sorted(swaps.items())) if isinstance(swaps, dict) else tuple(swaps)
        self.additions = tuple(additions)
        if self.schedule is not None and renames:
            self.schedule = rename_schedule(self.schedule, renames)
        self._rebuild_draft()
        self.fill_waves()
        self.fill_models()

    def _rebuild_draft(self):
        """The track file as the export will write its model lists, used to check wave edits."""
        if self.track_bytes is None or not self.event:
            self.track_draft = None
            return
        track = self.track_bytes
        if self.swaps:
            track = replace_models(track, self.event.event_offset, dict(self.swaps))
        if self.additions:
            trams = tram_models(read_waves(track, self.event.event_offset))
            track = add_models(track, self.event.event_offset, self.additions, trams=trams)
        self.track_draft = track
        if self.schedule is not None and (self.swaps or self.additions):
            self.schedule = replace(self.schedule, models=read_waves(track, self.event.event_offset).models)

    def replace_model(self):
        rows = self.models.selection()
        if not self.event or len(rows) != 1:
            self.status.set("Select one model row to replace.")
            return
        choice = self.replacement.get().split(" ")[0]
        group, index = map(int, rows[0].split("/"))
        old = self.orders[group][index]
        if not choice or choice not in candidates_for(self.orders, old):
            self.status.set("Choose a replacement from the list (models of the same group in other events).")
            return
        swaps = dict(self.swaps)
        additions = list(self.additions)
        if old in additions:
            additions[additions.index(old)] = choice
        else:
            original = next((k for k, v in swaps.items() if v == old), old)
            if choice == original:
                swaps.pop(original, None)
            else:
                swaps[original] = choice
        orders = [list(names) for names in self.orders]
        orders[group][index] = choice
        try:
            self._set_models(orders, swaps, additions, {old: choice})
        except ValueError as exc:
            self.status.set(str(exc))
            return
        self.models.selection_set(rows[0])
        self.status.set(f"{old} ({self.labels.get(old)}) replaced by {choice} ({self.labels.get(choice)}). "
                        "The waves use the new model. Build an ISO copy to play it.")

    def add_model(self, model=None):
        """Load one more model in the event (its group comes from the other events)."""
        if not self.event:
            return False
        model = model or self.addition.get().split(" ")[0]
        if not model:
            self.status.set("Choose a model to add.")
            return False
        reason = can_add(self.orders, model, self._trams(), self._model_root())
        if reason:
            self.status.set(reason)
            return False
        orders = [list(names) for names in self.orders]
        orders[group_of(model)].append(model)
        try:
            self._set_models(orders, dict(self.swaps), self.additions + (model,))
        except ValueError as exc:
            self.status.set(str(exc))
            return False
        self.status.set(f"{model} ({self.labels.get(model)}) added to the event's models. Use it in the waves; "
                        "build an ISO copy to play it (experimental: needs a play test).")
        return True

    def remove_added_model(self):
        rows = self.models.selection()
        if not self.event or len(rows) != 1:
            self.status.set("Select one added model.")
            return
        group, index = map(int, rows[0].split("/"))
        model = self.orders[group][index]
        if model not in self.additions:
            self.status.set("Only models added here can be removed; original models can be replaced.")
            return
        used = any(model in (v.model, v.trailer) for w in self.schedule.waves for l in w.lanes for v in l.vehicles) \
            if self.schedule is not None else False
        if used:
            self.status.set(f"Some wave vehicles use {model}. Change them first.")
            return
        orders = [list(names) for names in self.orders]
        orders[group].remove(model)
        self._set_models(orders, dict(self.swaps), tuple(m for m in self.additions if m != model))
        self.status.set(f"{model} is no longer added to the event.")

    # --- traffic waves tab ---------------------------------------------------

    def build_waves_tab(self, tabs):
        page = ttk.Frame(tabs, style="Card.TFrame", padding=12)
        page.columnconfigure(0, weight=5)
        page.columnconfigure(1, weight=4)
        tabs.add(page, text="Traffic waves")
        self.waves_page = page
        intro = ttk.Frame(page, style="Card.TFrame")
        intro.grid(row=0, column=0, columnspan=2, sticky="ew")
        intro.columnconfigure(0, weight=1)
        self.wave_help = ttk.Label(intro, text=WAVE_HELP, style="CardMuted.TLabel", wraplength=900, justify="left")
        self.wave_help.grid(row=0, column=0, sticky="w")
        intro.bind("<Configure>", lambda e: self.wave_help.configure(wraplength=max(300, e.width - 10)))
        page.rowconfigure(1, weight=0)
        page.rowconfigure(2, weight=1)
        self.wave_timeline = tk.Canvas(page, height=190, background=theme.PALETTE["surface_alt"],
                                       highlightthickness=1, highlightbackground=theme.PALETTE["border"])
        self.wave_timeline.grid(row=1, column=0, sticky="nsew", pady=(8, 10))
        self.wave_timeline.bind("<Configure>", lambda _: self.draw_timeline())
        self.wave_timeline.bind("<Button-1>", self.timeline_click)
        map_area = ttk.Frame(page, style="Card.TFrame")
        map_area.grid(row=1, column=1, sticky="nsew", padx=(12, 0), pady=(8, 10))
        map_area.columnconfigure(0, weight=1)
        map_area.rowconfigure(1, weight=1)
        map_bar = ttk.Frame(map_area, style="Card.TFrame")
        map_bar.grid(row=0, column=0, sticky="ew")
        self.map_hint = tk.StringVar(value="Wheel: zoom · drag: move")
        ttk.Label(map_bar, textvariable=self.map_hint, style="CardMuted.TLabel").pack(side="left")
        ttk.Button(map_bar, text="Whole track", style="Small.TButton", command=self.map_whole_track).pack(side="right")
        ttk.Button(map_bar, text="Selected", style="Small.TButton", command=self.map_fit_selection).pack(
            side="right", padx=(0, 4))
        self.wave_canvas = tk.Canvas(map_area, background=theme.PALETTE["map_bg"], highlightthickness=1,
                                     highlightbackground=theme.PALETTE["border"], width=320, height=160)
        self.wave_canvas.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        self.wave_canvas.bind("<Configure>", lambda _: self.draw_waves())
        self.wave_canvas.bind("<MouseWheel>", self.map_zoom)
        self.wave_canvas.bind("<ButtonPress-1>", self.map_press)
        self.wave_canvas.bind("<B1-Motion>", self.map_motion)
        self.wave_canvas.bind("<ButtonRelease-1>", self.map_release)
        self.wave_canvas.bind("<Double-Button-1>", lambda _e: self.map_whole_track())
        left = ttk.Frame(page, style="Card.TFrame")
        left.grid(row=2, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.wave_tree = ttk.Treeview(left, columns=("detail", "when"), selectmode="browse", height=10)
        self.wave_tree.heading("#0", text="Wave → lane → vehicle")
        self.wave_tree.heading("detail", text="What")
        self.wave_tree.heading("when", text="Where / when")
        self.wave_tree.column("#0", width=175, minwidth=130)
        self.wave_tree.column("detail", width=140, minwidth=80)
        self.wave_tree.column("when", width=190, minwidth=90)
        self.wave_tree.tag_configure("wave", font=(theme.FAMILY, 10, "bold"))
        self.wave_tree.tag_configure("later", foreground=theme.PALETTE["info"])
        self.wave_tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(left, command=self.wave_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.wave_tree.configure(yscrollcommand=scroll.set)
        self.wave_tree.bind("<<TreeviewSelect>>", lambda _: self.wave_selected())
        tree_buttons = ttk.Frame(left, style="Card.TFrame")
        tree_buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(tree_buttons, text="+ Add wave", command=self.add_wave).pack(side="left")
        ttk.Button(tree_buttons, text="Export waves JSON…", command=self.export_waves_json).pack(side="right")
        ttk.Button(tree_buttons, text="Import waves JSON…", command=self.import_waves_json).pack(
            side="right", padx=(0, 6))
        holder = tk.Frame(page, background=theme.PALETTE["border"])
        holder.grid(row=2, column=1, sticky="nsew", padx=(12, 0))
        area = theme.ScrollArea(holder)
        area.pack(fill="both", expand=True, padx=1, pady=1)
        self.inspector = ttk.Frame(area.inner, style="Card.TFrame", padding=12)
        self.inspector.pack(fill="both", expand=True)
        self.inspector.columnconfigure(0, weight=1)
        self.inspector_title = tk.StringVar(value="Nothing selected")
        self.inspector_text = tk.StringVar(value=EMPTY_HINT)
        ttk.Label(self.inspector, textvariable=self.inspector_title, style="Section.TLabel").grid(
            row=0, column=0, sticky="w")
        self.inspector_label = ttk.Label(self.inspector, textvariable=self.inspector_text, style="CardMuted.TLabel",
                                         wraplength=400, justify="left")
        self.inspector_label.grid(row=1, column=0, sticky="w", pady=(4, 8))
        self.inspector.bind("<Configure>", lambda e: self.inspector_label.configure(
            wraplength=max(200, e.width - 30)))
        self.wave_panel = self._wave_panel(self.inspector)
        self.lane_panel = self._lane_panel(self.inspector)
        self.vehicle_panel = self._vehicle_panel(self.inspector)
        for panel in (self.wave_panel, self.lane_panel, self.vehicle_panel):
            panel.grid(row=2, column=0, sticky="ew")
            panel.grid_remove()
        summary = ttk.Frame(page, style="Card.TFrame")
        summary.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        summary.columnconfigure(0, weight=1)
        self.wave_note = tk.StringVar()
        ttk.Label(summary, textvariable=self.wave_note, style="Card.TLabel", wraplength=900).grid(
            row=0, column=0, sticky="w")
        self.wave_warning = ttk.Label(summary, text="", style="Warning.TLabel", wraplength=900, justify="left")
        self.wave_warning.grid(row=1, column=0, sticky="w", pady=(2, 0))

    def _wave_panel(self, parent):
        panel = ttk.Frame(parent, style="Card.TFrame")
        panel.columnconfigure(1, weight=1)
        ttk.Label(panel, text="Loads at (seconds)", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.wave_start = ttk.Entry(panel, width=8)
        self.wave_start.grid(row=0, column=1, sticky="w", padx=6)
        ttk.Button(panel, text="Apply", command=self.apply_wave).grid(row=0, column=2, sticky="e")
        ttk.Button(panel, text="Remove wave", command=self.remove_wave).grid(row=0, column=3, sticky="e",
                                                                          padx=(6, 0))
        self.wave_speed_note = tk.StringVar()
        ttk.Label(panel, textvariable=self.wave_speed_note, style="CardMuted.TLabel", wraplength=380,
                  justify="left").grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))
        ttk.Label(panel, text="Give this wave traffic on another road lane (the map shows it):",
                  style="CardMuted.TLabel").grid(row=2, column=0, columnspan=4, sticky="w", pady=(10, 2))
        self.new_lane = ttk.Combobox(panel, state="readonly", width=34)
        self.new_lane.grid(row=3, column=0, columnspan=4, sticky="ew")
        self.new_lane.bind("<<ComboboxSelected>>", lambda _e: self._lane_choice_changed())
        self.pick_button = ttk.Button(panel, text="Pick on map", command=self.toggle_pick_lane)
        self.pick_button.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(panel, text="+ Add lane", style="Accent.TButton", command=self.add_lane).grid(
            row=4, column=2, columnspan=2, sticky="e", pady=(6, 0))
        return panel

    def _lane_panel(self, parent):
        panel = ttk.Frame(parent, style="Card.TFrame")
        panel.columnconfigure(3, weight=1)
        ttk.Label(panel, text="Speed", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.lane_speed = ttk.Entry(panel, width=7)
        self.lane_speed.grid(row=0, column=1, sticky="w", padx=6)
        ttk.Button(panel, text="Apply", command=self.apply_lane_speed).grid(row=0, column=2, sticky="w")
        self.lane_speed_note = tk.StringVar()
        ttk.Label(panel, textvariable=self.lane_speed_note, style="CardMuted.TLabel", wraplength=380,
                  justify="left").grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 0))
        ttk.Label(panel, text="Late cars enter at", style="Card.TLabel").grid(row=2, column=0, sticky="w",
                                                                              pady=(8, 0))
        self.lane_entry = ttk.Entry(panel, width=10)
        self.lane_entry.grid(row=2, column=1, sticky="w", padx=6, pady=(8, 0))
        ttk.Button(panel, text="Apply", command=self.apply_lane).grid(row=2, column=2, sticky="w", pady=(8, 0))
        ttk.Button(panel, text="Remove lane", command=self.remove_lane).grid(row=2, column=3, sticky="e",
                                                                          pady=(8, 0))
        quick = ttk.Frame(panel, style="Card.TFrame")
        quick.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        quick.columnconfigure(1, weight=1)
        ttk.Label(quick, text="Add several to this lane", style="Section.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(quick, text="Model", style="CardMuted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.quick_model = ttk.Combobox(quick, state="readonly", width=28)
        self.quick_model.grid(row=1, column=1, columnspan=3, sticky="ew", pady=(4, 0))
        ttk.Label(quick, text="How many", style="CardMuted.TLabel").grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.quick_count = ttk.Spinbox(quick, from_=1, to=30, width=5, command=self.preview_changed)
        self.quick_count.set("3")
        self.quick_count.grid(row=2, column=1, sticky="w", pady=(4, 0))
        self.quick_role = tk.StringVar(value="placed")
        ttk.Radiobutton(quick, text="On the road, every", value="placed", variable=self.quick_role,
                        style="Card.TRadiobutton", command=self.preview_changed).grid(
            row=3, column=0, sticky="w", pady=(4, 0))
        self.quick_spacing = ttk.Entry(quick, width=7)
        self.quick_spacing.insert(0, "15")
        self.quick_spacing.grid(row=3, column=1, sticky="w", pady=(4, 0))
        ttk.Label(quick, text="units behind the last", style="CardMuted.TLabel").grid(
            row=3, column=2, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Radiobutton(quick, text="Drive in from", value="released", variable=self.quick_role,
                        style="Card.TRadiobutton", command=self.preview_changed).grid(
            row=4, column=0, sticky="w", pady=(4, 0))
        self.quick_start = ttk.Entry(quick, width=7)
        self.quick_start.grid(row=4, column=1, sticky="w", pady=(4, 0))
        ttk.Label(quick, text="s, one every", style="CardMuted.TLabel").grid(row=4, column=2, sticky="w", pady=(4, 0))
        self.quick_every = ttk.Entry(quick, width=5)
        self.quick_every.insert(0, "1.5")
        self.quick_every.grid(row=4, column=3, sticky="w", pady=(4, 0))
        for widget in (self.quick_count, self.quick_spacing, self.quick_start, self.quick_every):
            widget.bind("<KeyRelease>", lambda _e: self.preview_changed())
        self.quick_model.bind("<<ComboboxSelected>>", lambda _e: self.preview_changed())
        self.quick_preview = tk.StringVar()
        ttk.Label(quick, textvariable=self.quick_preview, style="Info.TLabel", wraplength=380, justify="left").grid(
            row=5, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Button(quick, text="+ Add", style="Accent.TButton", command=self.add_vehicles_to_lane).grid(
            row=6, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        return panel

    def _vehicle_panel(self, parent):
        panel = ttk.Frame(parent, style="Card.TFrame")
        panel.columnconfigure(1, weight=1)
        panel.columnconfigure(3, weight=1)
        ttk.Label(panel, text="Model", style="CardMuted.TLabel").grid(row=0, column=0, sticky="w")
        self.vehicle_model = ttk.Combobox(panel, state="readonly", width=16)
        self.vehicle_model.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(6, 0))
        ttk.Label(panel, text="Trailer", style="CardMuted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.vehicle_trailer = ttk.Combobox(panel, state="readonly", width=14)
        self.vehicle_trailer.grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(4, 0))
        ttk.Label(panel, text="Colour", style="CardMuted.TLabel").grid(row=1, column=2, sticky="e", pady=(4, 0),
                                                                     padx=(8, 0))
        self.vehicle_colour = ttk.Spinbox(panel, from_=0, to=7, width=4)
        self.vehicle_colour.grid(row=1, column=3, sticky="w", padx=(6, 0), pady=(4, 0))
        self.vehicle_role = tk.StringVar(value="placed")
        ttk.Radiobutton(panel, text="On the road at (units)", value="placed", variable=self.vehicle_role,
                        style="Card.TRadiobutton").grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Radiobutton(panel, text="Drives in at (s)", value="released", variable=self.vehicle_role,
                        style="Card.TRadiobutton").grid(row=3, column=0, columnspan=2, sticky="w")
        self.vehicle_value = ttk.Entry(panel, width=10)
        self.vehicle_value.grid(row=2, column=2, rowspan=2, columnspan=2, sticky="ew", padx=(6, 0))
        buttons = ttk.Frame(panel, style="Card.TFrame")
        buttons.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        ttk.Button(buttons, text="Apply", style="Accent.TButton", command=self.apply_vehicle).pack(side="left")
        for text, command in (("Duplicate", self.duplicate_vehicle), ("Remove", self.remove_vehicle)):
            ttk.Button(buttons, text=text, command=command).pack(side="left", padx=(6, 0))
        order = ttk.Frame(panel, style="Card.TFrame")
        order.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        ttk.Label(order, text="Queue order (cars on the road):", style="CardMuted.TLabel").pack(side="left")
        for text, command in (("▼ Back", lambda: self.move_vehicle(1)), ("▲ Front", lambda: self.move_vehicle(-1))):
            ttk.Button(order, text=text, style="Small.TButton", command=command).pack(side="right", padx=(4, 0))
        return panel

    # --- helpers -----------------------------------------------------------

    def wave_path(self):
        """(wave, lane, vehicle) indices of the selected row; missing levels are None."""
        rows = self.wave_tree.selection()
        if not rows:
            return None, None, None
        parts = [int(p[1:]) for p in rows[0].split("/")]
        return tuple(parts + [None] * (3 - len(parts)))

    def _path_length(self, path_id):
        paths = self.roads.get("paths") or []
        if not 0 <= path_id < len(paths):
            return None
        distances = paths[path_id].get("control_distances") or []
        return distances[-1] if distances else None

    def _model_options(self):
        """Every traffic vehicle model: loaded ones first, then the other events' ones."""
        options = {}
        loaded = loaded_models(self.schedule)["vehicles"] if self.schedule is not None else []
        for model in loaded:
            options[f"{model} · {self.labels.get(model, '?')}"] = model
        for group in range(5):
            for model in CANDIDATES[group]:
                if model not in loaded:
                    options[f"{model} · {self.labels.get(model, '?')}{NOT_LOADED}"] = model
        return options

    def _trailer_options(self):
        loaded = loaded_models(self.schedule)["trailers"] if self.schedule is not None else []
        options = {"": None}
        for model in loaded:
            options[f"{model} · {self.labels.get(model, '?')}"] = model
        for model in CANDIDATES[TRAILER_GROUP]:
            if model not in loaded:
                options[f"{model} · {self.labels.get(model, '?')}{NOT_LOADED}"] = model
        return options

    @staticmethod
    def _choice(text):
        """Model ID from a combobox entry ("COMPCAR14 · Car" or a bare ID)."""
        return text.split(" ")[0] if text else ""

    def _ensure_loaded(self, model):
        """True when the event loads ``model``, adding it to the draft after asking."""
        if not model or self.schedule is None:
            return False
        if model in self.schedule.models:
            return True
        reason = can_add(self.orders, model, self._trams(), self._model_root())
        if reason:
            self.status.set(f"{model} is not loaded by this event. {reason}")
            messagebox.showinfo("Model not loaded", f"{model} ({self.labels.get(model)}) is not loaded by this "
                                f"event.\n\n{reason}\n\nYou can replace a model in Models and goals.", parent=self)
            return False
        room = budget(self.orders, self._trams())
        if not messagebox.askyesno("Add a model to the event",
                                   f"{model} ({self.labels.get(model)}) is not loaded by this event.\n\n"
                                   f"Add it to the event's models? The event will load {room['models'] + 1} of "
                                   f"{MAX_MODELS}. This is experimental and needs a play test.", parent=self):
            return False
        return self.add_model(model)

    # --- tree and panels ---------------------------------------------------

    def fill_waves(self, keep=None):
        tree = self.wave_tree
        if keep is None and tree.selection():
            keep = tree.selection()[0]
        tree.delete(*tree.get_children())
        if self.schedule is None:
            self.wave_note.set(self.wave_error)
            self.draw_waves()
            self.draw_timeline()
            return
        s = self.schedule
        for n, wave in enumerate(s.waves):
            placed = sum(lane.initial for lane in wave.lanes)
            later = sum(len(lane.vehicles) - lane.initial for lane in wave.lanes)
            when = "when the event starts" if n == 0 else f"at {wave.start:g} s"
            wid = f"w{n}"
            tree.insert("", "end", iid=wid, text=f"Wave {n + 1}", open=True, tags=("wave",),
                        values=(f"{placed} on the road · {later} later", when))
            for m, lane in enumerate(wave.lanes):
                lid = f"{wid}/l{m}"
                later_lane = len(lane.vehicles) - lane.initial
                speed = lane_speed(s, n, lane.source, lane.slot)[0]
                speed_text = f" · speed {speed:g}" if speed is not None else ""
                tree.insert(wid, "end", iid=lid, text=f"Lane P{s.lane_path(lane)}", open=n == 0,
                            values=(f"{lane.initial} on road · {later_lane} later",
                                    f"enter {lane.entry:.0f}{speed_text}"))
                for k, vehicle in enumerate(lane.vehicles):
                    name = vehicle.model + (" + " + vehicle.trailer if vehicle.trailer else "")
                    placed_vehicle = k < lane.initial
                    where = (f"on the road at {vehicle.distance:.1f}" if placed_vehicle
                             else f"drives in at {vehicle.time:.2f} s")
                    kind = self.labels.get(vehicle.model) or TYPE_NAMES.get(vehicle.kind, str(vehicle.kind))
                    tree.insert(lid, "end", iid=f"{lid}/v{k}", text=f"{k + 1}. {name}",
                                tags=() if placed_vehicle else ("later",),
                                values=(f"{kind} · colour {vehicle.variant}", where))
        if keep and tree.exists(keep):
            tree.selection_set(keep)
            tree.see(keep)
        self.update_wave_note()
        self.draw_waves()
        self.draw_timeline()

    def show_waves(self):
        """Bring the Traffic waves tab to the front (used by the main window's buttons)."""
        self.tabs.select(self.waves_page)
        self.deiconify()
        self.lift()

    def update_wave_note(self):
        self.wave_warning.configure(text="")
        if self.schedule is None or not self.event:
            return
        placed = sum(l.initial for w in self.schedule.waves for l in w.lanes)
        total = sum(len(l.vehicles) for w in self.schedule.waves for l in w.lanes)
        on_road = vehicle_total(self.schedule)
        self.wave_note.set(f"{len(self.schedule.waves)} waves · {placed} on the road when their wave loads · "
                           f"{total - placed} drive in later · up to {on_road} on the road · "
                           f"{self.free_space_text()}")
        base = self.initial[3] if getattr(self, "initial", None) and self.initial[3] else None
        warning = density_warning(on_road, vehicle_total(base) if base is not None else None)
        style = "Danger.TLabel" if on_road >= DENSITY_CRASH else "Warning.TLabel"
        self.wave_warning.configure(text=("⚠ " + warning) if warning else "", style=style)

    def free_space_text(self):
        try:
            base = self.initial[3]
            used = _layout(self.schedule.waves) - _layout(base.waves)
            return f"about {max(0, base.free_bytes - used) // 32} more vehicles fit"
        except (AttributeError, TypeError, IndexError):
            return ""

    def _show_panel(self, panel, title, text):
        for other in (self.wave_panel, self.lane_panel, self.vehicle_panel):
            if other is panel:
                other.grid()
            else:
                other.grid_remove()
        self.inspector_title.set(title)
        self.inspector_text.set(text)

    def _lane_options(self, wave):
        """Readable road lanes the wave does not use yet, one per path."""
        s = self.schedule
        used_here = {(l.source, l.slot) for l in s.waves[wave].lanes}
        used_paths_here = {s.lane_path(l) for l in s.waves[wave].lanes}
        used_by = {}
        preferred = {}
        for n, w in enumerate(s.waves):
            for lane in w.lanes:
                path = s.lane_path(lane)
                used_by.setdefault(path, set()).add(n + 1)
                preferred.setdefault(path, (lane.source, lane.slot))
        candidates = {}
        for source_index, source in enumerate(s.sources):
            for slot, path in enumerate(source.paths):
                if (source_index, slot) in used_here or path in used_paths_here:
                    continue
                candidates.setdefault(path, []).append((source_index, slot))
        options = {}
        ordered = sorted(candidates, key=lambda p: (p not in used_by, p))
        for path in ordered:
            pairs = candidates[path]
            choice = preferred.get(path) if preferred.get(path) in pairs else pairs[0]
            length = self._path_length(path)
            where = (f"used in wave {', '.join(str(n) for n in sorted(used_by[path]))}" if path in used_by
                     else "not used by any wave")
            size = f" · {length:,.0f} units long" if length else ""
            options[f"P{path} · {where}{size}"] = choice
        return options

    def _lane_choice_changed(self):
        self.map_focus = "candidate"
        self.map_view = None
        self.draw_waves()

    def _candidate_path(self):
        choice = self.lane_choices.get(self.new_lane.get())
        if choice is None or self.schedule is None:
            return None
        return self.schedule.sources[choice[0]].paths[choice[1]]

    def wave_selected(self):
        wave, lane, vehicle = self.wave_path()
        previous = getattr(self, "_last_selection", None)
        self._last_selection = (wave, lane)
        if (wave, lane) != previous:
            self.map_view = None
            self.map_focus = "selection"
        if self.schedule is None or wave is None:
            self._show_panel(None, "Nothing selected", EMPTY_HINT)
            self.draw_waves()
            self.draw_timeline()
            return
        w = self.schedule.waves[wave]
        _set(self.wave_start, f"{w.start:g}")
        self.lane_choices = self._lane_options(wave)
        options = list(self.lane_choices)
        self.new_lane.configure(values=options)
        if options and self.new_lane.get() not in options:
            self.new_lane.set(options[0])
        elif not options:
            self.new_lane.set("")
        self.model_choices = self._model_options()
        labelled = list(self.model_choices)
        self.vehicle_model.configure(values=labelled)
        self.trailer_choices = self._trailer_options()
        self.vehicle_trailer.configure(values=list(self.trailer_choices))
        self.quick_model.configure(values=labelled)
        if self._choice(self.quick_model.get()) not in self.model_choices.values():
            self.quick_model.set(labelled[0] if labelled else "")
        if lane is None:
            when = "when the event starts" if wave == 0 else f"{w.start:g} s after the event starts"
            changes = [f"P{self.schedule.sources[i.source].paths[i.slot]} → {i.speed:g}" for i in w.speeds]
            self.wave_speed_note.set(("Lane speeds this wave sets: " + ", ".join(changes[:8])
                                      + (" …" if len(changes) > 8 else "")) if changes and wave else
                                     ("Wave 1 sets the starting speed of every lane." if wave == 0 else
                                      "This wave changes no lane speed."))
            self._show_panel(self.wave_panel, f"Wave {wave + 1}",
                             f"Loads {when}. It fills {len(w.lanes)} lane(s); select one below it to see "
                             "and add its cars." + ("" if wave else " Wave 1 cannot move or be removed."))
        if lane is not None:
            l = w.lanes[lane]
            _set(self.lane_entry, f"{l.entry:.3f}")
            speed, setter = lane_speed(self.schedule, wave, l.source, l.slot)
            _set(self.lane_speed, f"{speed:g}" if speed is not None else "")
            self.lane_speed_note.set((f"≈ {speed * KMH_PER_SPEED_UNIT:.0f} km/h · set by wave {setter + 1}. "
                                      "Applies to cars that appear after this wave loads.")
                                     if speed is not None else "No speed set for this lane.")
            last = l.vehicles[l.initial - 1].distance if l.initial else l.entry + 50.0
            if not self.quick_start.get().strip() or (wave, lane) != previous:
                later = [v.time for v in l.vehicles[l.initial:]]
                _set(self.quick_start, f"{(max(later) + 1.0) if later else w.start + 1.0:g}")
            if vehicle is None:
                self._show_panel(self.lane_panel, f"Lane P{self.schedule.lane_path(l)} · wave {wave + 1}",
                                 f"{l.initial} car(s) are on the road when the wave loads (the last at "
                                 f"{last:.0f} units) and {len(l.vehicles) - l.initial} drive in later at "
                                 f"{l.entry:.0f} units. Distances grow in the direction of travel (arrow).")
        if vehicle is not None:
            l = w.lanes[lane]
            v = l.vehicles[vehicle]
            self.vehicle_model.set(next((k for k, m in self.model_choices.items() if m == v.model), v.model))
            self.vehicle_trailer.set(next((k for k, m in self.trailer_choices.items() if m == v.trailer and m), ""))
            _set(self.vehicle_colour, str(v.variant))
            placed = vehicle < l.initial
            self.vehicle_role.set("placed" if placed else "released")
            _set(self.vehicle_value, f"{v.distance:.3f}" if placed else f"{v.time:.3f}")
            self._show_panel(self.vehicle_panel, f"{v.model} · {self.labels.get(v.model, 'vehicle')}",
                             ("On the road when wave {0} loads, {1:.0f} units along lane P{2}." if placed else
                              "Drives in at the lane entry {3:.2f} s after the event starts.").format(
                                 wave + 1, v.distance, self.schedule.lane_path(l), v.time)
                             + " Models marked \"not loaded yet\" are added to the event when you apply.")
        self.preview_changed()

    def commit_schedule(self, schedule, keep=None, message="Waves changed. Build an ISO copy to play the edit."):
        """Accept an edit only if the game rules and the free space allow it."""
        try:
            write_waves(self.track_draft if self.track_draft is not None else self.track_bytes,
                        self.event.event_offset, schedule)
        except ValueError as exc:
            self.status.set(str(exc))
            return False
        self.schedule = schedule
        self.fill_waves(keep)
        if keep and self.wave_tree.exists(keep):
            self.wave_selected()
        self.status.set(message)
        return True

    def _need(self, level):
        wave, lane, vehicle = self.wave_path()
        if self.schedule is None:
            self.status.set(self.wave_error or "Select an event first.")
            return None
        picked = (wave, lane, vehicle)[:level + 1]
        if any(p is None for p in picked):
            self.status.set(("Select a wave.", "Select a lane.", "Select a vehicle.")[level])
            return None
        return wave, lane, vehicle

    def _with_wave(self, n, wave):
        waves = list(self.schedule.waves)
        waves[n] = wave
        return replace(self.schedule, waves=tuple(waves))

    def _with_lane(self, n, m, lane):
        lanes = list(self.schedule.waves[n].lanes)
        lanes[m] = lane
        return self._with_wave(n, replace(self.schedule.waves[n], lanes=tuple(lanes)))

    # --- edits -------------------------------------------------------------

    def apply_wave(self):
        picked = self._need(0)
        if picked:
            n = picked[0]
            try:
                start = float(self.wave_start.get())
            except ValueError:
                self.status.set("Type the wave start in seconds.")
                return
            self.commit_schedule(self._with_wave(n, replace(self.schedule.waves[n], start=start)), f"w{n}")

    def add_wave(self):
        if self.schedule is None:
            self.status.set(self.wave_error or "Select an event first.")
            return
        last = self.schedule.waves[-1]
        waves = self.schedule.waves + (TrafficWave(round(last.start + 5.0, 3), ()),)
        n = len(waves) - 1
        self.commit_schedule(replace(self.schedule, waves=waves), f"w{n}",
                             f"Wave {n + 1} added 5 s after the previous one. Add a lane to give it traffic.")

    def remove_wave(self):
        picked = self._need(0)
        if picked:
            n = picked[0]
            if n == 0:
                self.status.set("Wave 1 loads with the event and cannot be removed.")
                return
            waves = self.schedule.waves[:n] + self.schedule.waves[n + 1:]
            self.commit_schedule(replace(self.schedule, waves=waves), f"w{n - 1}")

    def apply_lane(self):
        picked = self._need(1)
        if picked:
            n, m, _ = picked
            try:
                entry = float(self.lane_entry.get())
            except ValueError:
                self.status.set("Type the entry distance as a number.")
                return
            lane = replace(self.schedule.waves[n].lanes[m], entry=entry)
            self.commit_schedule(self._with_lane(n, m, lane), f"w{n}/l{m}")

    def apply_lane_speed(self):
        picked = self._need(1)
        if not picked:
            return
        n, m, _ = picked
        lane = self.schedule.waves[n].lanes[m]
        try:
            speed = float(self.lane_speed.get().replace(",", "."))
            schedule = with_lane_speed(self.schedule, n, lane.source, lane.slot, speed)
        except ValueError as exc:
            self.status.set(str(exc) if "speed" in str(exc) else "Type the lane speed as a number (0 to 240).")
            return
        self.commit_schedule(schedule, f"w{n}/l{m}",
                             f"Lane P{self.schedule.lane_path(lane)} drives at {speed:g} "
                             f"(≈ {speed * KMH_PER_SPEED_UNIT:.0f} km/h) from wave {n + 1} on.")

    def add_lane(self):
        picked = self._need(0)
        if not picked:
            return
        n = picked[0]
        choice = self.lane_choices.get(self.new_lane.get())
        if choice is None:
            parts = self.new_lane.get().split()
            if len(parts) >= 4 and parts[0] == "source":
                choice = (int(parts[1]), int(parts[3]))
        if choice is None:
            self.status.set("Choose a road lane that this wave does not use yet (or pick it on the map).")
            return
        source, slot = choice
        known = [l for w in self.schedule.waves for l in w.lanes if (l.source, l.slot) == (source, slot)]
        entry = known[0].entry if known else 0.0
        car = next((m for m in loaded_models(self.schedule)["vehicles"]
                    if vehicle_type_for(self.schedule, m) == 1), None)
        if car is None:
            self.status.set("This event loads no car model to start the lane with.")
            return
        lane = WaveLane(source, slot, entry, 1, (WaveVehicle(car, distance=entry + 50.0, kind=1),))
        wave = self.schedule.waves[n]
        m = len(wave.lanes)
        self.picking_lane = False
        self.commit_schedule(self._with_wave(n, replace(wave, lanes=wave.lanes + (lane,))), f"w{n}/l{m}",
                             f"Lane P{self.schedule.sources[source].paths[slot]} added with one car 50 units "
                             "after its entry. Use Add several to fill it.")

    def remove_lane(self):
        picked = self._need(1)
        if picked:
            n, m, _ = picked
            wave = self.schedule.waves[n]
            self.commit_schedule(self._with_wave(n, replace(wave, lanes=wave.lanes[:m] + wave.lanes[m + 1:])),
                                 f"w{n}")

    def _quick_plan(self):
        """What "Add several" would add to the selected lane: (vehicles, message) or (None, error)."""
        wave, lane_index, _ = self.wave_path()
        if self.schedule is None or wave is None or lane_index is None:
            return None, "Select a lane."
        lane = self.schedule.waves[wave].lanes[lane_index]
        model = self._choice(self.quick_model.get())
        try:
            count = int(self.quick_count.get())
            if not 1 <= count <= 30:
                raise ValueError
        except ValueError:
            return None, "Add 1 to 30 vehicles at a time."
        try:
            if self.quick_role.get() == "placed":
                spacing = float(self.quick_spacing.get())
                if not spacing > 0:
                    raise ValueError
                placed = lane.vehicles[:lane.initial]
                last = placed[-1].distance if placed else lane.entry + 50.0 + spacing
                distances = [round(last - spacing * (index + 1), 3) for index in range(count)]
                if distances[-1] < 0:
                    return None, "That queue would go before the start of the road. Use fewer cars or less spacing."
                behind = (f"behind {placed[-1].model} at {last:.0f}" if placed else f"from {last - spacing:.0f}")
                shown = ", ".join(f"{d:.0f}" for d in distances[:6]) + (" …" if count > 6 else "")
                return ("placed", model, distances), f"New on the road at {shown} units ({behind})."
            start, every = float(self.quick_start.get()), float(self.quick_every.get())
            if start < 0 or not every >= 0:
                raise ValueError
            times = [round(start + every * index, 3) for index in range(count)]
            shown = ", ".join(f"{t:g}" for t in times[:6]) + (" …" if count > 6 else "")
            return ("released", model, times), f"New: drive in at {shown} s, at the entry ({lane.entry:.0f} units)."
        except ValueError:
            return None, "Use positive numbers for the spacing, start time and interval."

    def preview_changed(self):
        plan, message = self._quick_plan()
        if hasattr(self, "quick_preview"):
            self.quick_preview.set(message if self.wave_path()[1] is not None else "")
        self.draw_waves()
        self.draw_timeline()

    def add_vehicles_to_lane(self):
        """Append a queue on the road, or a stream of cars that drive in later."""
        picked = self._need(1)
        if not picked:
            return
        n, m, _ = picked
        plan, message = self._quick_plan()
        if plan is None:
            self.status.set(message)
            return
        role, model, values = plan
        if not self._ensure_loaded(model):
            if self.schedule is not None and model not in self.schedule.models:
                self.status.set(self.status.get() or "Choose a model that this event loads.")
            return
        kind = vehicle_type_for(self.schedule, model)
        if kind is None:
            self.status.set("Choose a vehicle model (not a trailer).")
            return
        lane = self.schedule.waves[n].lanes[m]
        trailer = (loaded_models(self.schedule)["trailers"] or [None])[0] if kind == TRUCK_TYPE else None
        placed = list(lane.vehicles[:lane.initial])
        timed = list(lane.vehicles[lane.initial:])
        if role == "placed":
            placed += [WaveVehicle(model, trailer=trailer, kind=kind, distance=d) for d in values]
            message = f"{len(values)} {self.labels.get(model, model)} added on the road. " + message
        else:
            timed += [WaveVehicle(model, trailer=trailer, kind=kind, time=t) for t in values]
            timed.sort(key=lambda v: v.time)
            message = (f"{len(values)} {self.labels.get(model, model)} will drive in from {values[0]:g} s, "
                       f"one every {(values[1] - values[0]) if len(values) > 1 else 0:g} s.")
        lane = replace(lane, initial=len(placed), vehicles=tuple(placed + timed))
        if self.commit_schedule(self._with_lane(n, m, lane), f"w{n}/l{m}", message):
            self.wave_tree.item(f"w{n}/l{m}", open=True)

    def _vehicle_from_form(self, old):
        model = self._choice(self.vehicle_model.get())
        if model not in (self.schedule.models if self.schedule is not None else {}):
            if not self._ensure_loaded(model):
                raise ValueError(self.status.get() or "Choose a model that this event loads.")
        kind = vehicle_type_for(self.schedule, model)
        if kind is None:
            raise ValueError("Choose a model that this event loads.")
        trailer = self._choice(self.vehicle_trailer.get()) or None
        if trailer and trailer not in self.schedule.models and kind == TRUCK_TYPE:
            if not self._ensure_loaded(trailer):
                raise ValueError(self.status.get() or "Choose a trailer that this event loads.")
        if kind == TRUCK_TYPE and trailer is None:
            trailer = old.trailer or (loaded_models(self.schedule)["trailers"] or [None])[0]
        if kind != TRUCK_TYPE:
            trailer = None
        try:
            colour = int(self.vehicle_colour.get())
            value = float(self.vehicle_value.get())
        except ValueError as exc:
            raise ValueError("Colour must be 0 to 7 and the distance or time a number.") from exc
        placed = self.vehicle_role.get() == "placed"
        return replace(old, model=model, trailer=trailer, kind=kind, variant=colour,
                       distance=value if placed else 0.0, time=0.0 if placed else value), placed

    def apply_vehicle(self):
        picked = self._need(2)
        if not picked:
            return
        n, m, k = picked
        lane = self.schedule.waves[n].lanes[m]
        try:
            vehicle, placed = self._vehicle_from_form(lane.vehicles[k])
        except ValueError as exc:
            self.status.set(str(exc))
            return
        lane = self.schedule.waves[n].lanes[m]
        lane, index = _rebuild_lane(lane, k, vehicle, placed)
        self.commit_schedule(self._with_lane(n, m, lane), f"w{n}/l{m}/v{index}")

    def duplicate_vehicle(self):
        picked = self._need(2)
        if not picked:
            return
        n, m, k = picked
        lane = self.schedule.waves[n].lanes[m]
        v = lane.vehicles[k]
        if k < lane.initial:
            copy = replace(v, distance=max(0.0, v.distance - 15.0))
            vehicles = lane.vehicles[:k + 1] + (copy,) + lane.vehicles[k + 1:]
            lane, index = replace(lane, initial=lane.initial + 1, vehicles=vehicles), k + 1
        else:
            lane, index = _rebuild_lane(replace(lane, vehicles=lane.vehicles + (v,)), len(lane.vehicles),
                                        replace(v, time=v.time + 1.0), False)
        self.commit_schedule(self._with_lane(n, m, lane), f"w{n}/l{m}/v{index}",
                             "Vehicle duplicated 15 units behind (on the road) or 1 s later (drives in).")

    def remove_vehicle(self):
        picked = self._need(2)
        if picked:
            n, m, k = picked
            lane = self.schedule.waves[n].lanes[m]
            lane = replace(lane, vehicles=lane.vehicles[:k] + lane.vehicles[k + 1:],
                           initial=lane.initial - (1 if k < lane.initial else 0))
            self.commit_schedule(self._with_lane(n, m, lane), f"w{n}/l{m}")

    def move_vehicle(self, step):
        picked = self._need(2)
        if not picked:
            return
        n, m, k = picked
        lane = self.schedule.waves[n].lanes[m]
        other = k + step
        if k >= lane.initial or not 0 <= other < lane.initial:
            self.status.set("Only cars on the road can be reordered; cars that drive in follow their time.")
            return
        vehicles = list(lane.vehicles)
        vehicles[k], vehicles[other] = vehicles[other], vehicles[k]
        self.commit_schedule(self._with_lane(n, m, replace(lane, vehicles=tuple(vehicles))),
                             f"w{n}/l{m}/v{other}")

    def export_waves_json(self):
        if self.schedule is None or not self.event:
            self.status.set(self.wave_error or "Select an event first.")
            return
        dest = filedialog.asksaveasfilename(parent=self, title="Save the traffic waves",
                                            initialfile=f"{self.event.title.strip()}.waves.json",
                                            defaultextension=".json", filetypes=[("Waves JSON", "*.json")])
        if not dest:
            return
        data = waves_to_dict(self.schedule, event_key=self.event.key)
        data["title"] = self.event.title.strip()
        try:
            Path(dest).write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        except OSError as exc:
            self.status.set(str(exc))
            return
        self.status.set(f"Waves saved to {dest}")

    def import_waves_json(self):
        if self.schedule is None or not self.event:
            self.status.set(self.wave_error or "Select an event first.")
            return
        source = filedialog.askopenfilename(parent=self, title="Open a traffic waves file",
                                            filetypes=[("Waves JSON", "*.json")])
        if not source:
            return
        try:
            data = json.loads(Path(source).read_text(encoding="utf-8"))
            if data.get("event") not in (None, self.event.key):
                raise ValueError(f"This file belongs to event {data.get('event')}, not {self.event.key}.")
            base = (read_waves(self.track_draft, self.event.event_offset)
                    if self.track_draft is not None and (self.swaps or self.additions) else self.initial[3])
            schedule = waves_from_dict(data, base)
        except (OSError, ValueError, AttributeError) as exc:
            self.status.set(str(exc))
            return
        self.commit_schedule(schedule, "w0", f"Waves imported from {Path(source).name}. Build an ISO to play them.")

    # --- timeline ----------------------------------------------------------

    def _timeline_scale(self):
        c = self.wave_timeline
        width = max(c.winfo_width(), 200)
        times = [w.start for w in self.schedule.waves] + [v.time for w in self.schedule.waves
                 for l in w.lanes for v in l.vehicles[l.initial:]]
        plan = self._quick_plan()[0] if self.wave_path()[1] is not None else None
        if plan and plan[0] == "released":
            times += list(plan[2])
        end = max(10.0, max(times, default=0) + 3.0)
        left, right = 70, width - 20
        return left, right, end, lambda t: left + (right - left) * max(0.0, t) / end

    def _timeline_lanes(self):
        """Lane rows of the timeline: every source slot that has cars driving in later."""
        rows = []
        for wave in self.schedule.waves:
            for lane in wave.lanes:
                key = (lane.source, lane.slot)
                if key not in rows and len(lane.vehicles) > lane.initial:
                    rows.append(key)
        wave, lane_index, _ = self.wave_path()
        if wave is not None and lane_index is not None:
            lane = self.schedule.waves[wave].lanes[lane_index]
            if (lane.source, lane.slot) not in rows:
                rows.append((lane.source, lane.slot))
        return rows[:6]

    def draw_timeline(self):
        c = self.wave_timeline
        c.delete("all")
        if self.schedule is None or not self.event:
            c.create_text(12, 48, anchor="w", text="Select an event to see when its traffic appears.",
                          fill=theme.PALETTE["muted"])
            return
        left, right, end, x = self._timeline_scale()
        height = max(c.winfo_height(), 120)
        axis = height - 22
        muted, border = theme.PALETTE["muted"], theme.PALETTE["border"]
        c.create_line(left, axis, right, axis, fill=border, width=2)
        step = 5 if end <= 40 else 10 if end <= 90 else 20
        for second in range(0, int(end) + 1, step):
            c.create_line(x(second), 10, x(second), axis + 3, fill="#e3e8ee")
            c.create_text(x(second), axis + 10, text=f"{second} s", fill=muted, font=(theme.FAMILY, 8))
        top = 12
        c.create_text(10, top + 9, anchor="w", text="Waves", fill=muted, font=(theme.FAMILY, 8, "bold"))
        selected, selected_lane, _ = self.wave_path()
        for n, wave in enumerate(self.schedule.waves):
            start = x(wave.start)
            stop = x(self.schedule.waves[n + 1].start) if n + 1 < len(self.schedule.waves) else right
            fill = theme.PALETTE["accent"] if n == selected else theme.PALETTE["header_alt"]
            c.create_rectangle(start, top, max(start + 3, stop - 2), top + 18, fill=fill, outline="",
                               tags=(f"wave{n}",))
            on_road = sum(l.initial for l in wave.lanes)
            c.create_text(start + 6, top + 9, anchor="w", fill="#ffffff", font=(theme.FAMILY, 8, "bold"),
                          text=f"W{n + 1} · {on_road} on road", tags=(f"wave{n}",))
        rows = self._timeline_lanes()
        row_top = top + 30
        row_height = max(14, min(24, (axis - 8 - row_top) / max(1, len(rows))))
        selected_key = None
        if selected is not None and selected_lane is not None:
            lane = self.schedule.waves[selected].lanes[selected_lane]
            selected_key = (lane.source, lane.slot)
        if not rows:
            c.create_text(left, row_top + 10, anchor="w", fill=muted, font=(theme.FAMILY, 8),
                          text="No car drives in later in this event: all traffic is on the road when its wave loads.")
        for r, key in enumerate(rows):
            y = row_top + r * row_height + row_height / 2
            colour = LANE_COLOURS[r % len(LANE_COLOURS)]
            path = self.schedule.sources[key[0]].paths[key[1]]
            weight = "bold" if key == selected_key else "normal"
            c.create_text(10, y, anchor="w", text=f"P{path} drive in", fill=colour, font=(theme.FAMILY, 8, weight))
            c.create_line(left, y, right, y, fill="#e9edf2")
            for n, wave in enumerate(self.schedule.waves):
                for lane in wave.lanes:
                    if (lane.source, lane.slot) != key:
                        continue
                    for v in lane.vehicles[lane.initial:]:
                        px = x(v.time)
                        c.create_oval(px - 4, y - 4, px + 4, y + 4, fill=colour, outline="")
            if key == selected_key:
                plan = self._quick_plan()[0]
                if plan and plan[0] == "released":
                    for t in plan[2]:
                        px = x(t)
                        c.create_oval(px - 5, y - 5, px + 5, y + 5, outline=theme.PALETTE["accent"], width=2)

    def timeline_click(self, event):
        if self.schedule is None:
            return
        _left, _right, _end, x = self._timeline_scale()
        chosen = 0
        for n, wave in enumerate(self.schedule.waves):
            if event.x >= x(wave.start) - 2:
                chosen = n
        self.wave_tree.selection_set(f"w{chosen}")
        self.wave_tree.see(f"w{chosen}")
        self.wave_selected()

    # --- lane map (zoom, pan, pick) ----------------------------------------

    def _focus_points(self):
        """World points the map frames by default for the current selection."""
        paths = self.roads.get("paths") or []
        wave, lane_index, _ = self.wave_path()
        wanted = []
        if self.map_focus == "candidate" and self._candidate_path() is not None:
            wanted = [self._candidate_path()]
        elif self.schedule is not None and wave is not None:
            lanes = self.schedule.waves[wave].lanes
            if lane_index is not None:
                wanted = [self.schedule.lane_path(lanes[lane_index])]
            else:
                wanted = [self.schedule.lane_path(l) for l in lanes]
        points = [p for pid in wanted if 0 <= pid < len(paths) for p in paths[pid]["center"]]
        return points or [p for path in paths for p in path["center"]]

    def _map_frame(self):
        c = self.wave_canvas
        width, height = c.winfo_width(), c.winfo_height()
        if min(width, height) < 24 or not self.roads.get("paths"):
            return None
        if self.map_view is None:
            points = self._focus_points()
            xs, zs = [p[0] for p in points], [p[2] for p in points]
            span = max(max(xs) - min(xs), max(zs) - min(zs), 60.0) * 1.15
            self.map_view = ((min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2, span)
        cx, cz, span = self.map_view
        scale = min(width - 20, height - 20) / span

        def project(p):
            return width / 2 + (p[0] - cx) * scale, height / 2 - (p[2] - cz) * scale
        return project, scale

    def map_whole_track(self):
        paths = self.roads.get("paths") or []
        points = [p for path in paths for p in path["center"]]
        if not points:
            return
        xs, zs = [p[0] for p in points], [p[2] for p in points]
        self.map_view = ((min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2,
                         max(max(xs) - min(xs), max(zs) - min(zs), 60.0) * 1.05)
        self.draw_waves()

    def map_fit_selection(self):
        self.map_view = None
        self.map_focus = "selection"
        self.draw_waves()

    def map_zoom(self, event):
        frame = self._map_frame()
        if frame is None or not event.delta:
            return
        cx, cz, span = self.map_view
        c = self.wave_canvas
        factor = 0.8 if event.delta > 0 else 1.25
        new_span = max(10.0, min(200000.0, span * factor))
        side = min(c.winfo_width() - 20, c.winfo_height() - 20)
        dx, dz = event.x - c.winfo_width() / 2, c.winfo_height() / 2 - event.y
        self.map_view = (cx + dx / side * (span - new_span), cz + dz / side * (span - new_span), new_span)
        self.draw_waves()

    def map_press(self, event):
        self.map_drag = (event.x, event.y, self.map_view, False)

    def map_motion(self, event):
        if not self.map_drag or self.map_drag[2] is None:
            return
        x0, y0, (cx, cz, span), _moved = self.map_drag
        if abs(event.x - x0) + abs(event.y - y0) < 3:
            return
        c = self.wave_canvas
        scale = min(c.winfo_width() - 20, c.winfo_height() - 20) / span
        self.map_view = (cx - (event.x - x0) / scale, cz + (event.y - y0) / scale, span)
        self.map_drag = (x0, y0, (cx, cz, span), True)
        self.draw_waves()

    def map_release(self, event):
        drag, self.map_drag = self.map_drag, None
        if drag and not drag[3] and self.picking_lane:
            self.pick_lane_at(event.x, event.y)

    def toggle_pick_lane(self):
        self.picking_lane = not self.picking_lane
        self.pick_button.configure(text="Click a road on the map…" if self.picking_lane else "Pick on map")
        self.map_hint.set("Click a blue road to choose it." if self.picking_lane else "Wheel: zoom · drag: move")
        if self.picking_lane:
            self.map_whole_track()

    def pick_lane_at(self, px, py):
        """Choose the lane option whose road passes nearest to the click."""
        frame = self._map_frame()
        if frame is None:
            return
        project, _scale = frame
        paths = self.roads.get("paths") or []
        best = None
        by_path = {self.schedule.sources[s].paths[k]: label for label, (s, k) in self.lane_choices.items()}
        for path_id, label in by_path.items():
            if not 0 <= path_id < len(paths):
                continue
            for point in paths[path_id]["center"]:
                x, y = project(point)
                distance = math.hypot(x - px, y - py)
                if best is None or distance < best[0]:
                    best = (distance, label)
        if best is None or best[0] > 14:
            self.status.set("No free road lane there. Click closer to a road, or zoom in.")
            return
        self.new_lane.set(best[1])
        self.toggle_pick_lane()
        self._lane_choice_changed()
        self.status.set(f"{best[1].split(' · ')[0]} chosen. Click + Add lane to give this wave traffic there.")

    def draw_waves(self):
        c = self.wave_canvas
        c.delete("all")
        if not self.event or not self.roads.get("paths"):
            return
        frame = self._map_frame()
        if frame is None:
            return
        project, scale = frame
        paths = self.roads["paths"]
        wave, lane_index, vehicle_index = self.wave_path()
        lanes = []
        if self.schedule is not None and wave is not None:
            lanes = list(enumerate(self.schedule.waves[wave].lanes))
        highlight = {self.schedule.lane_path(l) for _, l in lanes} if lanes else set()
        choices = set()
        if self.picking_lane and self.schedule is not None:
            choices = {self.schedule.sources[s].paths[k] for s, k in self.lane_choices.values()}
        for path in paths:
            coords = [v for p in path["center"] for v in project(p)]
            if len(coords) >= 4:
                strong = path.get("id") in highlight
                pickable = path.get("id") in choices
                c.create_line(*coords, fill="#5b6878" if strong else theme.PALETTE["info"] if pickable else "#c3ccd6",
                              width=2.5 if strong or pickable else 1)
        candidate = self._candidate_path() if lane_index is None and wave is not None else None
        if candidate is not None and 0 <= candidate < len(paths):
            coords = [v for p in paths[candidate]["center"] for v in project(p)]
            if len(coords) >= 4:
                c.create_line(*coords, fill=theme.PALETTE["accent"], width=4, dash=(6, 3))
                self._arrow(c, paths[candidate], project, theme.PALETTE["accent"])
                mid = paths[candidate]["center"][len(paths[candidate]["center"]) // 2]
                x, y = project(mid)
                c.create_text(x + 6, y - 6, anchor="sw", text=f"new lane P{candidate}", fill=theme.PALETTE["accent"],
                              font=(theme.FAMILY, 9, "bold"))
        for m, lane in lanes:
            index = self.schedule.lane_path(lane)
            if index >= len(paths):
                continue
            path = paths[index]
            colour = LANE_COLOURS[m % len(LANE_COLOURS)]
            selected_lane = m == lane_index
            if selected_lane:
                coords = [v for p in path["center"] for v in project(p)]
                if len(coords) >= 4:
                    c.create_line(*coords, fill=colour, width=4)
            self._arrow(c, path, project, colour)
            entry = point_at_distance(path, lane.entry)
            if entry:
                x, y = project(entry)
                c.create_polygon(x, y - 7, x - 6, y + 5, x + 6, y + 5, fill=colour, outline="#ffffff")
            for k, v in enumerate(lane.vehicles[:lane.initial]):
                p = point_at_distance(path, v.distance)
                if p:
                    x, y = project(p)
                    size = 6 if (m, k) == (lane_index, vehicle_index) else 4
                    c.create_oval(x - size, y - size, x + size, y + size, fill=colour,
                                  outline=theme.PALETTE["text"] if size == 6 else "#ffffff")
            mid = path["center"][len(path["center"]) // 2]
            x, y = project(mid)
            c.create_text(x + 6, y + 6, anchor="nw", text=f"P{index}", fill=colour, font=(theme.FAMILY, 9, "bold"))
        plan = self._quick_plan()[0] if lane_index is not None and vehicle_index is None else None
        lane_ids = [self.schedule.lane_path(l) for _m, l in lanes]
        if plan and lane_index is not None and lane_index < len(lane_ids) and lane_ids[lane_index] < len(paths):
            path = paths[lane_ids[lane_index]]
            if plan[0] == "placed":
                for d in plan[2]:
                    p = point_at_distance(path, d)
                    if p:
                        x, y = project(p)
                        c.create_oval(x - 5, y - 5, x + 5, y + 5, outline=theme.PALETTE["accent"], width=2)
            else:
                entry = point_at_distance(path, self.schedule.waves[wave].lanes[lane_index].entry)
                if entry:
                    x, y = project(entry)
                    c.create_oval(x - 10, y - 10, x + 10, y + 10, outline=theme.PALETTE["accent"], width=2)
                    c.create_text(x + 12, y, anchor="w", text=f"+{len(plan[2])}", fill=theme.PALETTE["accent"],
                                  font=(theme.FAMILY, 9, "bold"))
        c.create_text(8, 8, anchor="nw", fill=theme.PALETTE["muted"], font=(theme.FAMILY, 8),
                      text="● on the road   ▲ late cars enter   ○ to be added   → direction")
        marker = min(80, c.winfo_width() / 4)
        c.create_line(10, c.winfo_height() - 12, 10 + marker, c.winfo_height() - 12, fill=theme.PALETTE["muted"])
        c.create_text(10, c.winfo_height() - 16, anchor="sw", fill=theme.PALETTE["muted"], font=(theme.FAMILY, 8),
                      text=f"{marker / scale:.0f} units")

    @staticmethod
    def _arrow(c, path, project, colour):
        distances = path.get("control_distances") or []
        if not distances:
            return
        length = distances[-1]
        a, b = point_at_distance(path, length * 0.55), point_at_distance(path, length * 0.55 + max(8.0, length * 0.03))
        if a and b:
            (x0, y0), (x1, y1) = project(a), project(b)
            if math.hypot(x1 - x0, y1 - y0) > 2:
                c.create_line(x0, y0, x1, y1, arrow=tk.LAST, fill=colour, width=2, arrowshape=(9, 11, 4))

    # --- window lifecycle ----------------------------------------------------

    def close(self):
        if self.job is not None:
            self.status.set("Wait for the current operation to finish.")
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
            return messagebox.askyesno("Native events", "Discard edits that have not been exported?",
                                       parent=self)
        return True

    def run(self, message, action, success, failure=None):
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
                if failure is not None:
                    failure(exc)
                messagebox.showerror("Native events", str(exc), parent=self)
        self.after(80, check)

    def choose_folder(self):
        if self.job is not None:
            return
        selected = filedialog.askdirectory(parent=self, title="Extracted folder with DATA and TRACKS")
        if selected:
            self.open_game(Path(selected))

    def open_game(self, folder):
        def loaded(events):
            if not self.can_discard():
                self.status.set("The current folder and edits were kept.")
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
            self.source.set(f"{len(events)} Crash events · {folder.name}")
            self.status.set("Pick an event. Traffic waves: when and where traffic appears. "
                            "Models and goals: replace or add models, change goals.")
            self.filter_events(key)
        self.run("Reading the Crash catalogue…", lambda: load_crash_events(folder), loaded)

    def focus_event(self, key):
        self.event_list.selection_set(key)
        self.event_list.focus(key)
        self.event_list.see(key)
        self.select()

    def locate(self):
        key = (self.current_identity() or {}).get("event_key")
        if key not in self.events:
            self.status.set("Open the game folder and refresh the session list with the event paused.")
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
        return (self.orders, tuple(entry.get() for entry in self.fields), self.crash_count.get(), self.schedule,
                self.swaps, self.additions)

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
        self.schedule = None
        self.swaps = ()
        self.additions = ()
        self.track_draft = None
        self.map_view = None
        self.picking_lane = False
        self.heading.set("Select an event")
        self.models.delete(*self.models.get_children())
        for entry in (*self.fields, self.crash_count):
            entry.configure(state="normal")
            entry.delete(0, "end")
            entry.configure(state="disabled")
        self.limit_note.set("")
        self.crash_note.set("")
        self.map_info.set("")
        self.wave_note.set("")
        self.wave_tree.delete(*self.wave_tree.get_children())
        self.canvas.delete("all")
        self.wave_canvas.delete("all")
        self.wave_timeline.delete("all")
        self._show_panel(None, "Nothing selected", EMPTY_HINT)

    def select(self):
        rows = self.event_list.selection()
        if not rows or (self.event and self.event.key == rows[0]):
            return
        event = self.events[rows[0]]
        self.clear_event()
        try:
            path = bgd_path(self.game, event.track)
            data = path.read_bytes()
            orders = read_groups(data, event.event_offset)
            if self.track != event.track:
                self.roads = read_roads(path, max_samples_per_path=64)
                self.track = event.track
        except (OSError, ValueError) as exc:
            self.status.set(str(exc))
            return
        try:
            waves = read_waves(data, event.event_offset)
            self.wave_error = ""
        except ValueError as exc:
            waves = None
            self.wave_error = f"Traffic waves are not editable for this event: {exc}"
        self.track_bytes = data
        self.event = event
        wrecks = event.crashbreaker_wrecks
        self.initial = (orders, tuple(format(n, ".9g") for n in event.thresholds),
                        str(wrecks) if wrecks is not None else "", waves, (), ())
        self.orders, fields, count, self.schedule, self.swaps, self.additions = self.drafts.get(event.key, self.initial)
        try:
            self._rebuild_draft()
        except ValueError as exc:
            self.status.set(str(exc))
        self.heading.set(f"{event.title}  ·  {event.track}  ·  {event.key}")
        self.fill_models()
        aligned = event.thresholds == event.bgd_thresholds
        for entry, value in zip(self.fields, fields):
            entry.configure(state="normal")
            entry.insert(0, value)
            entry.configure(state="normal" if aligned else "readonly")
        self.limit_note.set("Type the goals in whole dollars." if aligned else
                            "The track and catalogue goals differ. The original values will be kept.")
        supported = wrecks is not None and 6 <= wrecks <= 15 and wrecks == event.bgd_crashbreaker_wrecks
        self.crash_count.configure(state="normal")
        self.crash_count.insert(0, count)
        self.crash_count.configure(state="normal" if supported else "readonly")
        self.crash_note.set("" if supported else "Wreck count not confirmed by both tables.")
        self.map_info.set(f"{self.roads['path_count']} traffic paths on this track · X/Z view")
        self.fill_waves("w0")
        self.wave_selected()
        self.draw()

    def fill_models(self):
        self.models.delete(*self.models.get_children())
        originals = {new: old for old, new in self.swaps}
        total = sum(len(names) for names in self.orders)
        for g, names in enumerate(self.orders):
            for i, name in enumerate(names):
                note = ("added from other events" if name in self.additions else
                        f"replaces {originals[name]}" if name in originals else "")
                tag = ("added",) if name in self.additions else ("swapped",) if note else ()
                self.models.insert("", "end", iid=f"{g}/{i}", tags=tag,
                                   values=(GROUP_LABELS[g] if g < len(GROUP_LABELS) else g + 1, i + 1, name,
                                           self.labels.get(name, "?"), note))
        if hasattr(self, "replacement"):
            self.model_selected()
            self._refresh_models_controls()
        self.status.set(self.status.get() if self.status.get() else f"{total} models loaded by this event.")

    def swap(self):
        selection = self.models.selection()
        if not self.event or len(selection) != 2:
            self.status.set("Ctrl-select two model rows.")
            return
        (g, a), (other, b) = [map(int, row.split("/")) for row in selection]
        if g != other:
            self.status.set("Pick models with the same group number.")
            return
        rows = [list(row) for row in self.orders]
        rows[g][a], rows[g][b] = rows[g][b], rows[g][a]
        self.orders = tuple(tuple(row) for row in rows)
        self.fill_models()
        self.models.selection_set(selection)
        self.status.set("Order changed for this event. Export to keep the edit.")

    def draw(self):
        self.canvas.delete("all")
        if not self.event or not self.roads:
            return
        project = _frame(self.roads["paths"], self.canvas.winfo_width(), self.canvas.winfo_height())
        if project is None:
            return
        for path in self.roads["paths"]:
            coords = [v for p in path["center"] for v in project(p)]
            self.canvas.create_line(*coords, fill=theme.PALETTE["info"], width=1.5)

    # --- export --------------------------------------------------------------

    def export(self, to_iso):
        if not self.event or self.job is not None:
            return
        event, game = self.event, self.game
        orders, fields, count, schedule, swaps, additions = self.get_draft()
        expected_orders = self.initial[0]
        try:
            goals = tuple(map(int, fields)) if fields != self.initial[1] else None
        except ValueError:
            self.status.set("Use whole numbers for the goals.")
            return
        wrecks = None
        if count != self.initial[2]:
            try:
                wrecks = int(count)
            except ValueError:
                pass
            if wrecks is None or not 6 <= wrecks <= 15:
                self.status.set("Use a whole number from 6 to 15 for the Crashbreaker.")
                return
        if self.initial[3] is not None and (swaps or additions) and self.track_draft is not None:
            draft_base = read_waves(self.track_draft, event.event_offset)
        else:
            draft_base = self.initial[3]
        waves = (schedule if schedule is not None and draft_base is not None and schedule.waves != draft_base.waves
                 else None)
        if (goals is None and wrecks is None and orders == expected_orders and waves is None
                and not swaps and not additions):
            self.status.set("Change a model, a goal, the Crashbreaker wrecks or a traffic wave first.")
            return
        if to_iso:
            source = filedialog.askopenfilename(parent=self, title="Select the ISO that matches the extraction",
                                                initialdir=game.parent, filetypes=[("ISO", "*.iso")])
            if not source:
                return
            dest = filedialog.asksaveasfilename(parent=self, title="Choose a new ISO file", initialdir=game.parent,
                    initialfile=event.title.strip() + " - edited.iso", defaultextension=".iso",
                    filetypes=[("ISO", "*.iso")])
        else:
            dest = filedialog.askdirectory(parent=self, title="Folder that will receive a new subfolder with the edited files")
        if not dest:
            return
        extra = {} if waves is None else {"waves": waves, "expected_waves": self.initial[3].waves}
        if swaps:
            extra["model_swaps"] = dict(swaps)
        if additions:
            extra["model_additions"] = list(additions)
        dialog = ProgressDialog(self, event.title.strip(), to_iso) if to_iso else None
        self.progress_state = None

        def progress(stage, done, total):
            self.progress_state = (stage, done, total)

        def write():
            changes = prepare_changes(game, event, orders, goals, expected_orders=expected_orders,
                                      crashbreaker_wrecks=wrecks, **extra)
            if to_iso:
                export_iso(Path(source), Path(dest), changes, progress=progress)
                return Path(dest)
            return export_resources(game, Path(dest), event, changes)

        def saved(path):
            self.exported[event.key] = (orders, fields, count, schedule, swaps, additions)
            self.status.set(f"{event.title} · verified copy at {path}")
            if dialog is not None:
                dialog.finish(path)
            else:
                messagebox.showinfo("Export finished", f"{event.title}\n\n{path}\n\nBuild an ISO with these files "
                                    "(or use Build ISO copy) to play the edit.", parent=self)

        def failed(_exc):
            if dialog is not None:
                dialog.close()

        if dialog is not None:
            dialog.follow(lambda: self.progress_state, lambda: self.job is not None)
        self.run("Writing and verifying the copy…", write, saved, failed)


class ProgressDialog(tk.Toplevel):
    """Shows the ISO copy being written and read back, then how to test it."""

    STAGES = {"checking": "Checking the original ISO…", "copying": "Writing the new ISO…",
              "verifying": "Verifying the copy on disk…"}

    def __init__(self, parent, title, to_iso):
        super().__init__(parent)
        self.title("Building the ISO copy")
        self.configure(background=theme.PALETTE["surface"])
        self.resizable(False, False)
        self.transient(parent)
        body = ttk.Frame(self, style="Card.TFrame", padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=title, style="Section.TLabel").pack(anchor="w")
        self.stage = tk.StringVar(value="Preparing the edited files…")
        ttk.Label(body, textvariable=self.stage, style="Card.TLabel").pack(anchor="w", pady=(8, 4))
        self.bar = ttk.Progressbar(body, mode="determinate", maximum=100, length=420)
        self.bar.pack(fill="x")
        self.detail = tk.StringVar(value="")
        ttk.Label(body, textvariable=self.detail, style="CardMuted.TLabel").pack(anchor="w", pady=(4, 0))
        self.note = ttk.Label(body, text="", style="Info.TLabel", wraplength=420, justify="left")
        self.note.pack(anchor="w", pady=(10, 0))
        self.buttons = ttk.Frame(body, style="Card.TFrame")
        self.buttons.pack(fill="x", pady=(12, 0))
        self.path = None

    def follow(self, read_state, running):
        """Poll the export thread's latest progress until it finishes."""
        def tick():
            if not self.winfo_exists() or self.path is not None:
                return
            state = read_state()
            if state:
                stage, done, total = state
                share = (done / total) if total else 0
                weight = {"checking": (0, 0.02), "copying": (0.02, 0.6), "verifying": (0.62, 0.38)}.get(stage, (0, 1))
                self.bar.configure(value=100 * (weight[0] + weight[1] * share))
                self.stage.set(self.STAGES.get(stage, stage))
                self.detail.set(f"{done / 2**20:,.0f} of {total / 2**20:,.0f} MB")
            if running():
                self.after(150, tick)
        self.after(150, tick)

    def finish(self, path):
        if not self.winfo_exists():
            return
        self.path = Path(path)
        self.bar.configure(value=100)
        self.stage.set("Done: the new ISO is written and verified.")
        self.detail.set(str(path))
        self.note.configure(text=PLAY_NOTE)
        ttk.Button(self.buttons, text="Open folder", command=self.open_folder).pack(side="left")
        ttk.Button(self.buttons, text="Close", style="Accent.TButton", command=self.close).pack(side="right")

    def open_folder(self):
        if self.path is not None and hasattr(os, "startfile"):
            try:
                os.startfile(self.path.parent)  # Windows only; elsewhere the path is shown above.
            except OSError:
                pass

    def close(self):
        if self.winfo_exists():
            self.destroy()


def _set(entry, text):
    entry.delete(0, "end")
    entry.insert(0, text)


def _layout(waves):
    return sum(((len(w.lanes) * 12 + 15) & ~15) + sum(len(l.vehicles) * 32 for l in w.lanes) for w in waves)


def _rebuild_lane(lane, index, vehicle, placed):
    """Replace vehicle ``index`` and keep placed vehicles first and timed ones by time."""
    placed_list = [v for i, v in enumerate(lane.vehicles[:lane.initial]) if i != index]
    timed = [v for i, v in enumerate(lane.vehicles[lane.initial:], lane.initial) if i != index]
    if placed:
        position = min(index, len(placed_list))
        placed_list.insert(position, vehicle)
        new_index = position
    else:
        timed.append(vehicle)
        timed.sort(key=lambda v: v.time)
        new_index = len(placed_list) + timed.index(vehicle)
    return replace(lane, initial=len(placed_list), vehicles=tuple(placed_list + timed)), new_index


def _frame(paths, width, height):
    """Return a function mapping world X/Z to canvas coordinates for these paths."""
    points = [p for path in paths for p in path["center"]]
    if not points or min(width, height) < 24:
        return None
    x = [p[0] for p in points]
    z = [p[2] for p in points]
    x0, x1, z0, z1 = min(x), max(x), min(z), max(z)
    scale = min((width - 20) / max(1, x1 - x0), (height - 20) / max(1, z1 - z0))
    def project(p):
        return (width / 2 + (p[0] - (x0 + x1) / 2) * scale, height / 2 - (p[2] - (z0 + z1) / 2) * scale)
    return project
