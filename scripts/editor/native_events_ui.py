"""Browse and edit the native USA Crash resources without an emulator connection."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from editor.catalog import traffic_catalog
from resources.crash_events import bgd_path, load_crash_events
from resources.native_edit import export_resources, prepare_changes
from resources.native_iso import export_iso
from resources.native_roads import point_at_distance, read_roads
from resources.native_traffic import read_groups
from resources.traffic_waves import (
    DENSITY_CRASH, DENSITY_WARNING, TRUCK_TYPE, TYPE_NAMES, TrafficWave, WaveLane, WaveVehicle,
    density_warning, loaded_models, read_waves, vehicle_total, vehicle_type_for, waves_from_dict,
    waves_to_dict, write_waves,
)

WAVE_HELP = ("Wave 1 loads with the event. Each later wave loads when the event clock reaches its start "
             "time. Placed vehicles appear at their distance on the lane's road path as soon as their wave "
             "loads; the others enter one by one at the lane entry distance when the clock reaches their time.")
LANE_COLOURS = ("#c0392b", "#2471a3", "#1e8449", "#b9770e", "#7d3c98", "#148f77")


class NativeEventsWindow(tk.Toplevel):
    def __init__(self, parent, current_identity):
        super().__init__(parent)
        self.title("Burnout 3 — Native Crash events")
        self.geometry("1040x680")
        self.minsize(760, 520)
        self.current_identity = current_identity
        self.game = None
        self.events = {}
        self.event = None
        self.drafts = {}
        self.exported = {}
        self.track = None
        self.track_bytes = None
        self.roads = {}
        self.schedule = None
        self.wave_error = ""
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.job = None
        self.labels = {m["asset_id"]: m["category_label"] for m in traffic_catalog()}
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        bar = ttk.Frame(self, padding=8)
        bar.grid(row=0, column=0, sticky="ew")
        ttk.Button(bar, text="Open game folder…", command=self.choose_folder).pack(side="left")
        ttk.Button(bar, text="Find session event", command=self.locate).pack(side="left", padx=6)
        self.source = tk.StringVar(value="Choose the folder that contains DATA and TRACKS.")
        ttk.Label(bar, textvariable=self.source).pack(side="left", padx=6)
        pane = ttk.Panedwindow(self, orient="horizontal")
        pane.grid(row=1, column=0, sticky="nsew", padx=8)
        left = ttk.Frame(pane)
        left.rowconfigure(2, weight=1)
        left.columnconfigure(0, weight=1)
        ttk.Label(left, text="Search event or track").grid(row=0, column=0, sticky="w")
        self.query = tk.StringVar()
        ttk.Entry(left, textvariable=self.query).grid(row=1, column=0, sticky="ew", pady=(3, 5))
        self.event_list = ttk.Treeview(left, columns=("title", "track"), show="headings",
                                       selectmode="browse")
        for key, label, width in (("title", "Event", 160), ("track", "Track", 85)):
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
        self.heading = tk.StringVar(value="Select an event")
        ttk.Label(right, textvariable=self.heading).grid(row=0, column=0, sticky="w", pady=(0, 5))
        tabs = ttk.Notebook(right)
        tabs.grid(row=1, column=0, sticky="nsew")
        self.tabs = tabs
        edit = ttk.Frame(tabs, padding=8)
        edit.columnconfigure(0, weight=1)
        edit.rowconfigure(0, weight=1)
        tabs.add(edit, text="Models and goals")
        self.models = ttk.Treeview(edit, columns=("group", "slot", "type", "model"),
                                   show="headings", selectmode="extended", height=7)
        for key, label, width in (("group", "Group", 42), ("slot", "Order", 45),
                                 ("type", "Type", 142), ("model", "Model", 90)):
            self.models.heading(key, text=label)
            self.models.column(key, width=width, minwidth=35)
        self.models.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(edit, command=self.models.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.models.configure(yscrollcommand=scroll.set)
        ttk.Button(edit, text="Swap two models of the same group", command=self.swap).grid(
            row=1, column=0, sticky="w", pady=5)
        limits = ttk.Frame(edit)
        limits.grid(row=2, column=0, sticky="ew", pady=(5, 0))
        self.fields = []
        for i, label in enumerate(("Gold ($)", "Silver ($)", "Bronze ($)")):
            limits.columnconfigure(i, weight=1)
            ttk.Label(limits, text=label).grid(row=0, column=i, sticky="w")
            entry = ttk.Entry(limits, width=10, state="disabled")
            entry.grid(row=1, column=i, sticky="ew", padx=(0, 4))
            self.fields.append(entry)
        self.limit_note = tk.StringVar()
        ttk.Label(edit, textvariable=self.limit_note, wraplength=440).grid(row=3, column=0, sticky="w")
        breaker = ttk.Frame(edit)
        breaker.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(breaker, text="Wrecks to unlock the Crashbreaker (6 to 15)").pack(side="left")
        self.crash_count = ttk.Entry(breaker, width=5, state="disabled")
        self.crash_count.pack(side="left", padx=6)
        self.crash_note = tk.StringVar()
        ttk.Label(edit, textvariable=self.crash_note, wraplength=440).grid(row=5, column=0, sticky="w")
        self.build_waves_tab(tabs)
        maps = ttk.Frame(tabs)
        tabs.add(maps, text="Track paths")
        self.map_info = tk.StringVar()
        ttk.Label(maps, textvariable=self.map_info, padding=5).pack(anchor="w")
        self.canvas = tk.Canvas(maps, background="#f4f6f7", highlightthickness=0)
        self.canvas.pack(expand=True, fill="both")
        self.canvas.bind("<Configure>", lambda _: self.draw())
        pane.add(right, weight=3)
        footer = ttk.Frame(self, padding=8)
        footer.grid(row=2, column=0, sticky="ew")
        self.status = tk.StringVar()
        ttk.Label(footer, textvariable=self.status, wraplength=520).pack(side="left", fill="x", expand=True)
        ttk.Button(footer, text="Export files…", command=lambda: self.export(False)).pack(side="left")
        ttk.Button(footer, text="Build ISO copy…", command=lambda: self.export(True)).pack(side="left", padx=(6, 0))
        self.event_list.bind("<<TreeviewSelect>>", lambda _: self.select())
        self.query.trace_add("write", lambda *_: self.filter_events())
        self.protocol("WM_DELETE_WINDOW", self.close)
        local = Path(__file__).resolve().parents[3] / "Burnout 3 - Takedown (USA)"
        if (local / "DATA" / "STAGEHED.BIN").is_file():
            self.after_idle(lambda: self.open_game(local))

    # --- traffic waves tab ---------------------------------------------------

    def build_waves_tab(self, tabs):
        page = ttk.Frame(tabs, padding=8)
        page.columnconfigure(0, weight=3)
        page.columnconfigure(1, weight=2)
        page.rowconfigure(1, weight=1)
        tabs.add(page, text="Traffic waves")
        self.waves_page = page
        ttk.Label(page, text=WAVE_HELP, wraplength=640, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        tree_frame = ttk.Frame(page)
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        self.wave_tree = ttk.Treeview(tree_frame, columns=("detail", "when"), selectmode="browse", height=12)
        self.wave_tree.heading("#0", text="Wave / lane / vehicle")
        self.wave_tree.heading("detail", text="Details")
        self.wave_tree.heading("when", text="Where / when")
        self.wave_tree.column("#0", width=190, minwidth=120)
        self.wave_tree.column("detail", width=150, minwidth=80)
        self.wave_tree.column("when", width=120, minwidth=80)
        self.wave_tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(tree_frame, command=self.wave_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.wave_tree.configure(yscrollcommand=scroll.set)
        self.wave_tree.bind("<<TreeviewSelect>>", lambda _: self.wave_selected())
        self.wave_canvas = tk.Canvas(page, background="#f4f6f7", highlightthickness=0, width=260, height=220)
        self.wave_canvas.grid(row=1, column=1, sticky="nsew", padx=(8, 0))
        self.wave_canvas.bind("<Configure>", lambda _: self.draw_waves())
        form = ttk.Frame(page)
        form.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        for column in range(8):
            form.columnconfigure(column, weight=1 if column in (1, 3, 5) else 0)
        ttk.Label(form, text="Wave start (s)").grid(row=0, column=0, sticky="w")
        self.wave_start = ttk.Entry(form, width=8)
        self.wave_start.grid(row=0, column=1, sticky="w", padx=4)
        ttk.Button(form, text="Apply", command=self.apply_wave).grid(row=0, column=2, sticky="w")
        ttk.Button(form, text="Add wave", command=self.add_wave).grid(row=0, column=3, sticky="w", padx=4)
        ttk.Button(form, text="Remove wave", command=self.remove_wave).grid(row=0, column=4, sticky="w")
        ttk.Label(form, text="Lane entry distance").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.lane_entry = ttk.Entry(form, width=8)
        self.lane_entry.grid(row=1, column=1, sticky="w", padx=4, pady=(4, 0))
        ttk.Button(form, text="Apply", command=self.apply_lane).grid(row=1, column=2, sticky="w", pady=(4, 0))
        self.new_lane = ttk.Combobox(form, state="readonly", width=26)
        self.new_lane.grid(row=1, column=3, sticky="ew", padx=4, pady=(4, 0))
        ttk.Button(form, text="Add lane", command=self.add_lane).grid(row=1, column=4, sticky="w", pady=(4, 0))
        ttk.Button(form, text="Remove lane", command=self.remove_lane).grid(row=1, column=5, sticky="w",
                                                                         padx=4, pady=(4, 0))
        ttk.Label(form, text="Vehicle").grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.vehicle_model = ttk.Combobox(form, state="readonly", width=16)
        self.vehicle_model.grid(row=2, column=1, sticky="ew", padx=4, pady=(4, 0))
        ttk.Label(form, text="Trailer").grid(row=2, column=2, sticky="e", pady=(4, 0))
        self.vehicle_trailer = ttk.Combobox(form, state="readonly", width=14)
        self.vehicle_trailer.grid(row=2, column=3, sticky="ew", padx=4, pady=(4, 0))
        ttk.Label(form, text="Colour").grid(row=2, column=4, sticky="e", pady=(4, 0))
        self.vehicle_colour = ttk.Spinbox(form, from_=0, to=7, width=4)
        self.vehicle_colour.grid(row=2, column=5, sticky="w", padx=4, pady=(4, 0))
        self.vehicle_role = tk.StringVar(value="placed")
        ttk.Radiobutton(form, text="Placed at distance", value="placed", variable=self.vehicle_role).grid(
            row=3, column=0, sticky="w")
        ttk.Radiobutton(form, text="Enters at time (s)", value="released", variable=self.vehicle_role).grid(
            row=3, column=1, sticky="w")
        self.vehicle_value = ttk.Entry(form, width=10)
        self.vehicle_value.grid(row=3, column=2, sticky="w")
        buttons = ttk.Frame(form)
        buttons.grid(row=3, column=3, columnspan=5, sticky="w", padx=4)
        for text, command in (("Apply", self.apply_vehicle), ("Duplicate", self.duplicate_vehicle),
                              ("Remove", self.remove_vehicle), ("Up", lambda: self.move_vehicle(-1)),
                              ("Down", lambda: self.move_vehicle(1))):
            ttk.Button(buttons, text=text, command=command).pack(side="left", padx=(0, 3))
        self.wave_warning = ttk.Label(page, text="", wraplength=640, justify="left")
        self.wave_warning.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        files = ttk.Frame(page)
        files.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.wave_note = tk.StringVar()
        ttk.Label(files, textvariable=self.wave_note, wraplength=520).pack(side="left", fill="x", expand=True)
        ttk.Button(files, text="Export waves JSON…", command=self.export_waves_json).pack(side="left")
        ttk.Button(files, text="Import waves JSON…", command=self.import_waves_json).pack(side="left", padx=(6, 0))

    def wave_path(self):
        """(wave, lane, vehicle) indices of the selected row; missing levels are None."""
        rows = self.wave_tree.selection()
        if not rows:
            return None, None, None
        parts = [int(p[1:]) for p in rows[0].split("/")]
        return tuple(parts + [None] * (3 - len(parts)))

    def fill_waves(self, keep=None):
        tree = self.wave_tree
        tree.delete(*tree.get_children())
        if self.schedule is None:
            self.wave_note.set(self.wave_error)
            self.draw_waves()
            return
        s = self.schedule
        for n, wave in enumerate(s.waves):
            placed = sum(lane.initial for lane in wave.lanes)
            later = sum(len(lane.vehicles) - lane.initial for lane in wave.lanes)
            when = "event start" if n == 0 else f"at {wave.start:g} s"
            wid = f"w{n}"
            tree.insert("", "end", iid=wid, text=f"Wave {n + 1}", open=True,
                        values=(f"{placed} placed, {later} later", when))
            for m, lane in enumerate(wave.lanes):
                lid = f"{wid}/l{m}"
                tree.insert(wid, "end", iid=lid, text=f"Lane P{s.lane_path(lane)}", open=n == 0,
                            values=(f"source {lane.source} · slot {lane.slot}", f"entry {lane.entry:.1f}"))
                for k, vehicle in enumerate(lane.vehicles):
                    name = vehicle.model + (" + " + vehicle.trailer if vehicle.trailer else "")
                    where = (f"placed at {vehicle.distance:.1f}" if k < lane.initial
                             else f"enters at {vehicle.time:.2f} s")
                    kind = TYPE_NAMES.get(vehicle.kind, str(vehicle.kind))
                    tree.insert(lid, "end", iid=f"{lid}/v{k}", text=f"{k + 1}. {name}",
                                values=(f"{kind} · colour {vehicle.variant}", where))
        if keep and tree.exists(keep):
            tree.selection_set(keep)
            tree.see(keep)
        self.update_wave_note()
        self.draw_waves()

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
        self.wave_note.set(f"{len(self.schedule.waves)} waves · {placed} placed · {total - placed} timed · "
                           f"up to {on_road} on the road · {self.free_space_text()}")
        base = self.initial[3] if getattr(self, "initial", None) and self.initial[3] else None
        warning = density_warning(on_road, vehicle_total(base) if base is not None else None)
        colour = "#b03a2e" if on_road >= DENSITY_CRASH else "#9a6700"
        self.wave_warning.configure(text=("⚠ " + warning) if warning else "", foreground=colour)

    def free_space_text(self):
        try:
            base = self.initial[3]
            used = _layout(self.schedule.waves) - _layout(base.waves)
            return f"about {max(0, base.free_bytes - used) // 32} more vehicles fit"
        except (AttributeError, TypeError, IndexError):
            return ""

    def wave_selected(self):
        wave, lane, vehicle = self.wave_path()
        if self.schedule is None or wave is None:
            return
        w = self.schedule.waves[wave]
        _set(self.wave_start, f"{w.start:g}")
        used = {(l.source, l.slot) for l in w.lanes}
        options = [f"source {i} slot {k} · path P{p}" for i, src in enumerate(self.schedule.sources)
                   for k, p in enumerate(src.paths) if (i, k) not in used]
        self.new_lane.configure(values=options)
        if options and self.new_lane.get() not in options:
            self.new_lane.set(options[0])
        if lane is not None:
            _set(self.lane_entry, f"{w.lanes[lane].entry:.3f}")
        models = loaded_models(self.schedule)
        self.vehicle_model.configure(values=models["vehicles"])
        self.vehicle_trailer.configure(values=[""] + models["trailers"])
        if vehicle is not None:
            l = w.lanes[lane]
            v = l.vehicles[vehicle]
            self.vehicle_model.set(v.model)
            self.vehicle_trailer.set(v.trailer or "")
            _set(self.vehicle_colour, str(v.variant))
            placed = vehicle < l.initial
            self.vehicle_role.set("placed" if placed else "released")
            _set(self.vehicle_value, f"{v.distance:.3f}" if placed else f"{v.time:.3f}")
        self.draw_waves()

    def commit_schedule(self, schedule, keep=None, message="Waves changed. Export to keep the edit."):
        """Accept an edit only if the game rules and the free space allow it."""
        try:
            write_waves(self.track_bytes, self.event.event_offset, schedule)
        except ValueError as exc:
            self.status.set(str(exc))
            return False
        self.schedule = schedule
        self.fill_waves(keep)
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
                             f"Wave {n + 1} added. Add a lane to give it vehicles.")

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

    def add_lane(self):
        picked = self._need(0)
        if not picked:
            return
        n = picked[0]
        choice = self.new_lane.get().split()
        if len(choice) < 4:
            self.status.set("Choose a source lane that this wave does not use yet.")
            return
        source, slot = int(choice[1]), int(choice[3])
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
        self.commit_schedule(self._with_wave(n, replace(wave, lanes=wave.lanes + (lane,))), f"w{n}/l{m}",
                             "Lane added with one car 50 units after its entry. Adjust it as needed.")

    def remove_lane(self):
        picked = self._need(1)
        if picked:
            n, m, _ = picked
            wave = self.schedule.waves[n]
            self.commit_schedule(self._with_wave(n, replace(wave, lanes=wave.lanes[:m] + wave.lanes[m + 1:])),
                                 f"w{n}")

    def _vehicle_from_form(self, old):
        model = self.vehicle_model.get()
        kind = vehicle_type_for(self.schedule, model)
        if kind is None:
            raise ValueError("Choose a model that this event loads.")
        trailer = self.vehicle_trailer.get() or None
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
                             "Vehicle duplicated 15 units behind (placed) or 1 s later (timed).")

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
            self.status.set("Only placed vehicles can be reordered; timed vehicles follow their time.")
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
            schedule = waves_from_dict(data, self.initial[3])
        except (OSError, ValueError, AttributeError) as exc:
            self.status.set(str(exc))
            return
        self.commit_schedule(schedule, "w0", f"Waves imported from {Path(source).name}. Export to keep them.")

    def draw_waves(self):
        c = self.wave_canvas
        c.delete("all")
        if not self.event or not self.roads.get("paths"):
            return
        frame = _frame(self.roads["paths"], c.winfo_width(), c.winfo_height())
        if frame is None:
            return
        project = frame
        wave, lane_index, vehicle_index = self.wave_path()
        lanes = []
        if self.schedule is not None and wave is not None:
            lanes = list(enumerate(self.schedule.waves[wave].lanes))
        highlight = {self.schedule.lane_path(l) for _, l in lanes} if lanes else set()
        for path in self.roads["paths"]:
            coords = [v for p in path["center"] for v in project(p)]
            if len(coords) >= 4:
                strong = path.get("id") in highlight
                c.create_line(*coords, fill="#7f8c8d" if not strong else "#34495e", width=2.5 if strong else 1)
        for m, lane in lanes:
            paths = self.roads["paths"]
            index = self.schedule.lane_path(lane)
            if index >= len(paths):
                continue
            path = paths[index]
            colour = LANE_COLOURS[m % len(LANE_COLOURS)]
            entry = point_at_distance(path, lane.entry)
            if entry:
                x, y = project(entry)
                c.create_polygon(x, y - 6, x - 5, y + 4, x + 5, y + 4, fill=colour, outline="")
            for k, v in enumerate(lane.vehicles[:lane.initial]):
                p = point_at_distance(path, v.distance)
                if p:
                    x, y = project(p)
                    size = 5 if (m, k) == (lane_index, vehicle_index) else 3
                    c.create_oval(x - size, y - size, x + size, y + size, fill=colour,
                                  outline="black" if size == 5 else "")

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
            self.status.set("Ctrl-select two models of the same group to swap their order, "
                            "or open the Traffic waves tab.")
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
        return self.orders, tuple(entry.get() for entry in self.fields), self.crash_count.get(), self.schedule

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
                        str(wrecks) if wrecks is not None else "", waves)
        self.orders, fields, count, self.schedule = self.drafts.get(event.key, self.initial)
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
        self.draw()

    def fill_models(self):
        self.models.delete(*self.models.get_children())
        for g, names in enumerate(self.orders):
            for i, name in enumerate(names):
                self.models.insert("", "end", iid=f"{g}/{i}", values=(g + 1, i + 1, self.labels[name], name))

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
            self.canvas.create_line(*coords, fill="#396a78", width=1.5)

    def export(self, to_iso):
        if not self.event or self.job is not None:
            return
        event, game = self.event, self.game
        orders, fields, count, schedule = self.get_draft()
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
        waves = schedule if schedule is not None and schedule != self.initial[3] else None
        if goals is None and wrecks is None and orders == expected_orders and waves is None:
            self.status.set("Change the model order, a goal, the Crashbreaker wrecks or a traffic wave first.")
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
        def write():
            changes = prepare_changes(game, event, orders, goals, expected_orders=expected_orders,
                                      crashbreaker_wrecks=wrecks, **extra)
            if to_iso:
                export_iso(Path(source), Path(dest), changes)
                return Path(dest)
            return export_resources(game, Path(dest), event, changes)
        def saved(path):
            self.exported[event.key] = (orders, fields, count, schedule)
            self.status.set(f"{event.title} · verified copy at {path}")
            messagebox.showinfo("Export finished", f"{event.title}\n\n{path}", parent=self)
        self.run("Writing and verifying the copy…", write, saved)


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
