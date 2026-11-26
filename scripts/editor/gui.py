"""Tkinter interface for a controller supplied by the launcher.

The controller owns emulator/profile validation and all mutations. Its methods
are called only on one background worker; this module touches Tk only on the
main thread. See Controller for the small interface expected by EditorApp.
"""
from __future__ import annotations

from datetime import datetime
import math
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Protocol


EXPORT_DIRECTORY = Path(__file__).resolve().parents[2] / 'outputs' / 'events'
PROJECT_DIRECTORY = Path(__file__).resolve().parents[2] / 'outputs' / 'projects'
NOMINAL_KMH_PER_CONTROL = 1.609344


class Controller(Protocol):
    def connect(self) -> dict[str, Any]: ...
    def refresh(self) -> dict[str, Any]: ...
    def move(self, vehicle_id: int, lateral_percent: float) -> dict[str, Any]: ...
    def add_behind(self, vehicle_id: int, model_id: str | None,
                   gap: float) -> dict[str, Any]: ...
    def add_many_behind(self, vehicle_id: int, model_id: str | None, gap: float,
                        count: int, secondary_model_id: str | None = None,
                        experimental: bool = False, color_mode: str = 'original') -> dict[str, Any]: ...
    def add_mixed_behind(self, vehicle_id: int, choices: list[dict[str, Any]], gap: float,
                         count: int, *, experimental: bool = False,
                         color_mode: str = 'original') -> dict[str, Any]: ...
    def add_at(self, vehicle_id: int, model_id: str | None, x: float, z: float,
               secondary_model_id: str | None = None,
               experimental: bool = False) -> dict[str, Any]: ...
    def save_preset(self, path: str) -> dict[str, Any]: ...
    def load_preset(self, path: str, *, experimental: bool = False) -> dict[str, Any]: ...
    def poll(self) -> dict[str, Any]: ...
    def pause(self) -> dict[str, Any]: ...
    def resume(self) -> dict[str, Any]: ...
    def export_state(self, path: str) -> dict[str, Any]: ...
    def finalize_pending(self) -> dict[str, Any]: ...
    def cancel_queue(self) -> dict[str, Any]: ...
    def set_speed(self, vehicle_id: int, control_value: float,
                  experimental: bool = False) -> dict[str, Any]: ...
    def set_speeds(self, vehicle_ids: list[int], control_value: float,
                   experimental: bool = False) -> dict[str, Any]: ...
    def create_project(self, directory: str, name: str) -> dict[str, Any]: ...
    def open_project(self, path: str) -> dict[str, Any]: ...
    def save_project(self) -> dict[str, Any]: ...
    def test_project(self) -> dict[str, Any]: ...
    def restart_project(self) -> dict[str, Any]: ...
    def restore_project_base(self) -> dict[str, Any]: ...
    def import_project(self, directory: str, name: str, state_path: str) -> dict[str, Any]: ...
    def save_project_from_state(self, state_path: str) -> dict[str, Any]: ...
    def confirm_project(self, path: str, *, base: bool = False) -> dict[str, Any]: ...
    def list_state_slots(self) -> dict[str, Any]: ...
    def archive_state_slot(self, slot: int) -> dict[str, Any]: ...
    def close(self) -> None: ...


def number(text: str, *, positive: bool = False) -> float:
    """Accept either decimal separator while rejecting nonfinite input."""
    try:
        value = float(text.strip().replace(',', '.'))
    except ValueError as exc:
        raise ValueError('Enter a valid number.') from exc
    if not math.isfinite(value):
        raise ValueError('Enter a finite number.')
    if positive and value <= 0:
        raise ValueError('The distance must be greater than zero.')
    return value


def quantity(text: str, experimental: bool = False) -> int:
    maximum = 253 if experimental else 8
    message = f'Use a whole number between 1 and {maximum}.'
    try:
        value = int(text.strip())
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(message) from exc
    if not 1 <= value <= maximum:
        raise ValueError(message)
    return value


def world_coordinate(text: str) -> float:
    value = number(text)
    if abs(value) > 3.402823466e38:
        raise ValueError("The coordinate exceeds the game's numeric range.")
    return value


def export_suggestion(directory: Path | None = None) -> Path:
    """Suggest a local name without replacing an existing file or link."""
    folder = Path(directory) if directory is not None else EXPORT_DIRECTORY
    stem = 'edited-event-' + datetime.now().strftime('%Y%m%d-%H%M%S')
    candidate = folder / (stem + '.p2s')
    index = 1
    while candidate.exists() or candidate.is_symlink():
        candidate = folder / f'{stem}-{index:03d}.p2s'
        index += 1
    return candidate


def project_suggestion(parent: Path) -> Path:
    """Use an unused child directory; the backend creates it exclusively."""
    stem = 'event-' + datetime.now().strftime('%Y%m%d-%H%M%S')
    candidate = Path(parent) / stem
    index = 1
    while candidate.exists() or candidate.is_symlink():
        candidate = Path(parent) / f'{stem}-{index:03d}'
        index += 1
    return candidate


def coordinate(value: Any) -> str:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return '—'
    return f'{result:.3f}'.replace('.', ',') if math.isfinite(result) else '—'


def model_label(model: dict[str, Any], index: int) -> str:
    label = str(model.get('label') or f'Unnamed model {index + 1}')
    category = str(model.get('type_label') or '').strip()
    if category and category not in label:
        label += f' · {category}'
    if model.get('verified') is False:
        label += ' (name to be confirmed)'
    return label


def catalog_rows(models: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Include restricted models for identification, without enabling creation."""
    return [(str(model.get('label') or model.get('id') or f'Model {index + 1}'),
             str(model.get('type_label') or 'Unidentified'),
             'Available' if model.get('eligible') is True else
             'Available with truck' if model.get('eligible_as_trailer') is True else
             'Creation not validated')
            for index, model in enumerate(models)]


def slot_archive_description(row: dict[str,Any]) -> str:
    slot,paths = row.get('slot'),row.get('paths')
    if (type(slot) is not int or not 0 <= slot <= 9 or row.get('occupied') is not True
            or row.get('blocked') or not isinstance(paths,list) or not paths
            or any(not isinstance(path,str) or not path for path in paths)):
        raise ValueError('Select an occupied slot that can be archived.')
    return (f'Archive the files of slot {slot}?\n\n' + '\n'.join(paths)
            + '\n\nA verified copy will stay in the editor backups folder. '
              'After the check, these files will leave the slots to free the space. '
              'The other slots are kept.')


def xz(position: Any) -> tuple[float, float] | None:
    """Read public world positions without treating invalid values as origin."""
    try:
        result = float(position[0]), float(position[2])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    return result if all(math.isfinite(value) for value in result) else None


def fit_view(points: list[tuple[float, float]]) -> tuple[float, float, float]:
    if not points:
        return 0, 0, 20
    xs, zs = zip(*points)
    span = max(max(xs) - min(xs), max(zs) - min(zs), 20) * 1.2
    return (min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2, span


def route_points(network: Any) -> list[tuple[float,float]]:
    """Finite public route vertices for fitting; no geometry is inferred here."""
    if not isinstance(network,dict) or not isinstance(network.get('paths'),list):
        return []
    return [point for path in network['paths'] if isinstance(path,dict)
            for key in ('left','center','right') for raw in
            (path.get(key) if isinstance(path.get(key),list) else [])
            if (point := xz(raw)) is not None]


def speed_value(value: Any) -> str:
    if type(value) not in (int,float) or not math.isfinite(value):
        return '—'
    return f'{value:.3f}'.replace('.',',')


def speed_summary(vehicle: dict[str,Any] | None, *, detailed=False) -> str:
    info = (vehicle or {}).get('speed_info')
    if not isinstance(info,dict):
        return 'Speed: not available in this read.' if detailed else '—'
    control,travel = speed_value(info.get('control_value')),speed_value(info.get('travel_value'))
    nominal_target,nominal_travel = info.get('nominal_target_kmh'),info.get('nominal_travel_kmh')
    if type(nominal_target) in (int,float) and math.isfinite(nominal_target):
        target_text,travel_text = speed_value(nominal_target),speed_value(nominal_travel)
        if detailed:
            return (f'Nominal target: {target_text} km/h · Nominal follow: {travel_text} km/h\n'
                    'Nominal scale; traffic can reduce progress.')
        return f'{target_text} / {travel_text}'
    if detailed:
        units = str(info.get('units') or 'internal units')
        return f'Control: {control} · Follow: {travel}\n{units}; internal values not converted.'
    return f'{control} / {travel}'


def map_to_world(view: tuple[float, float, float], width: float, height: float,
                 px: float, py: float) -> tuple[float, float]:
    """Invert the displayed X/Z map without assuming a screen origin."""
    cx, cz, span = view
    if (not all(math.isfinite(value) for value in (cx, cz, span, width, height, px, py))
            or span <= 0 or width <= 40 or height <= 50):
        raise ValueError('The top view is not ready to mark a position yet.')
    scale = min(width - 40, height - 50) / span
    result = cx + (px - width / 2) / scale, cz + (height / 2 - py) / scale
    if not all(math.isfinite(value) for value in result):
        raise ValueError('The marked position is not finite.')
    return result


def capacity_summary(snapshot: dict[str, Any]) -> str:
    vehicles = snapshot.get('vehicles') or []
    counts = snapshot.get('capacity') or snapshot.get('counts') or {}
    active = counts.get('active_objects', len(vehicles))
    ready = counts.get('initialized_objects', sum(v.get('initialized') is True for v in vehicles))
    parts = [f'Active objects: {active}', f'Physics ready: {ready}']
    for key, label in (('free_objects', 'Free objects'), ('free_nodes', 'Free nodes')):
        value = counts.get(key)
        if type(value) is int:
            parts.append(f'{label}: {value}')
    queued = counts.get('queued_operations')
    if type(queued) is int:
        parts.append(f'Queued: {queued}')
    warning = counts.get('physics_warning')
    if isinstance(warning, str) and warning:
        parts.append(warning)
    return ' · '.join(parts)


class EditorApp:
    def __init__(self, root: tk.Tk, controller: Controller):
        self.root = root
        self.controller = controller
        self.connected = False
        self.profile_valid = False
        self.emulator_control = False
        self.state_export = False
        self.event_projects = False
        self.project: dict[str, Any] | None = None
        self.busy = False
        self.pending = False
        self.pending_sized = False
        self.pending_poll_id: str | None = None
        self.core_paused: bool | None = None
        self.closed = False
        self.vehicles: dict[str, dict[str, Any]] = {}
        self.models: dict[str, dict[str, Any]] = {}
        self.model_choices: dict[str, str | None] = {}
        self.secondary_choices: dict[str, str | None] = {}
        self.trailer_visible = False
        self.map_view: tuple[float, float, float] | None = None
        self.map_pan_state = None
        self.map_hits: list[tuple[float, float, str]] = []
        self.routes: dict[str,Any] = {}
        self.marking_position = False
        self.player: dict[str, Any] | None = None
        self.jobs: queue.Queue[Any] = queue.Queue()
        self.results: queue.Queue[Any] = queue.Queue()
        self.status = tk.StringVar(value='Connect to the emulator with an event loaded.')
        self.pending_text = tk.StringVar(value='')
        self.connection_text = tk.StringVar(value='Desconectado')
        self.core_text = tk.StringVar(value='')
        self.selection_text = tk.StringVar(value='Select a vehicle in the list.')
        self.position_text = tk.StringVar(value='X: —     Y: —     Z: —')
        self.speed_text = tk.StringVar(value='Speed: not available in this read.')
        self.speed_target_kmh = tk.StringVar(value='')
        self.speed_selection_text = tk.StringVar(value='')
        self.speed_controls_visible = False
        self.show_routes = tk.BooleanVar(value=True)
        self.lateral = tk.DoubleVar(value=50)
        self.lateral_text = tk.StringVar(value='50,0%')
        self.gap = tk.StringVar(value='10')
        self.count = tk.StringVar(value='1')
        self.experimental = tk.BooleanVar(value=False)
        self.point_x = tk.StringVar(value='')
        self.point_z = tk.StringVar(value='')
        self.capacity_text = tk.StringVar(value='')
        self.project_name = tk.StringVar(value='My Crash event')
        self.project_text = tk.StringVar(value='No project open. Connect and pause PCSX2 to start.')
        self.model_choice = tk.StringVar(value='Same model as selected')
        self.secondary_choice = tk.StringVar(value='Select the trailer')
        self.spawn_mode = tk.StringVar(value='Single model')
        self.spawn_color = tk.StringVar(value='Original (0)')
        self.mixed_model_ids: list[str] = []
        self.mixed_text = tk.StringVar(value='Choose at least two loaded models to alternate.')
        self.map_notice = tk.StringVar(value='Vehicle positions; no track drawing.')
        self.instructions_text = tk.StringVar(value='Pause PCSX2 with Esc and refresh the list before editing. Changes apply to the current session.')
        self._build()
        for variable in (self.point_x, self.point_z):
            variable.trace_add('write', self._point_changed)
        self.worker = threading.Thread(target=self._work, daemon=True,
                                       name='Burnout3EditorController')
        self.worker.start()
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.poll_id = self.root.after(60, self._poll)
        self._update_controls()

    def _build(self) -> None:
        root = self.root
        root.title('Burnout 3 — Current event editor')
        root.geometry('1040x710')
        root.minsize(850, 600)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        container = ttk.Frame(root, padding=18)
        container.grid(row=0, column=0, sticky='nsew')
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)

        header = ttk.Frame(container)
        header.grid(row=0, column=0, sticky='ew')
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text='Current event editor',
                  font=('Segoe UI', 19, 'bold')).grid(row=0, column=0, sticky='w')
        ttk.Label(header, text='Experimental · Burnout 3 USA / PCSX2',
                  foreground='#5f6875').grid(row=1, column=0, sticky='w', pady=(4, 0))
        self.connect_button = ttk.Button(header, text='Connect / new session', command=self.connect)
        self.connect_button.grid(row=0, column=1, rowspan=2, padx=(15, 8))
        self.refresh_button = ttk.Button(header, text='Refresh list', command=self.refresh)
        self.refresh_button.grid(row=0, column=2, rowspan=2)
        connection = ttk.Frame(container)
        connection.grid(row=1, column=0, sticky='ew', pady=(15, 4))
        connection.columnconfigure(0, weight=1)
        ttk.Label(connection, textvariable=self.connection_text,
                  foreground='#305d86').grid(row=0, column=0, sticky='w')
        ttk.Label(connection, textvariable=self.core_text,
                  foreground='#305d86').grid(row=0, column=1, sticky='e')
        self.emulator_controls = ttk.Frame(connection)
        self.emulator_controls.grid(row=0, column=2, padx=(12, 0))
        self.pause_button = ttk.Button(self.emulator_controls, text='Pause PCSX2', command=self.pause_emulator)
        self.pause_button.pack(side='left')
        self.resume_button = ttk.Button(self.emulator_controls, text='Resume', command=self.resume_emulator)
        self.resume_button.pack(side='left', padx=(6, 0))
        self.emulator_controls.grid_remove()
        self.finalize_button = ttk.Button(connection, text='Finish pending request',
                                          command=self.finalize_pending)
        self.finalize_button.grid(row=0, column=3, padx=(8, 0))
        self.cancel_queue_button = ttk.Button(connection, text='Cancel queue', command=self.cancel_queue)
        self.cancel_queue_button.grid(row=0, column=4, padx=(6, 0))
        ttk.Label(connection, textvariable=self.capacity_text,
                  foreground='#5f6875', wraplength=920).grid(row=1, column=0, columnspan=5, sticky='w', pady=(5, 0))
        instructions = ttk.Frame(container)
        instructions.grid(row=2, column=0, sticky='ew', pady=(0, 12))
        instructions.columnconfigure(0, weight=1)
        ttk.Label(instructions,
                  textvariable=self.instructions_text,
                  foreground='#5f6875').grid(row=0, column=0, sticky='w')
        self.experimental_check = ttk.Checkbutton(instructions,
            text='Experimental mode: larger amounts and distances',
            variable=self.experimental, command=self._experimental_changed)
        self.experimental_check.grid(row=1, column=0, sticky='w', pady=(6, 0))
        self.experimental_warning = ttk.Label(instructions,
            text='High risk of freezes/lost physics. Save a state before testing. '
                 'The queue uses groups of up to 8; resume and pause to finish each group.',
            foreground='#a33922', wraplength=850)
        self.experimental_warning.grid(row=2, column=0, sticky='w', pady=(4, 0))
        self.experimental_warning.grid_remove()
        self.pending_banner = tk.Label(instructions, textvariable=self.pending_text,
            background='#fff0b3', foreground='#574100', font=('Segoe UI', 10, 'bold'),
            anchor='w', justify='left', padx=12, pady=10, wraplength=780)
        self.pending_banner.grid(row=3, column=0, sticky='ew', pady=(10, 0))
        self.pending_banner.grid_remove()

        pane = ttk.Panedwindow(container, orient=tk.HORIZONTAL)
        pane.grid(row=3, column=0, sticky='nsew')
        list_frame = ttk.Frame(pane)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        lists = ttk.Notebook(list_frame)
        lists.grid(row=0, column=0, sticky='nsew')
        actors = ttk.Frame(lists, padding=(0, 8, 0, 0))
        actors.columnconfigure(0, weight=1)
        actors.rowconfigure(0, weight=1)
        lists.add(actors, text='Vehicles present')
        self.table = ttk.Treeview(actors, columns=('vehicle', 'type', 'model','speed'),
                                  show='headings', selectmode='extended', height=15)
        for key, title, width in [('vehicle', 'Vehicle', 140), ('type', 'Category', 105),
                                  ('model', 'Model', 150),('speed','Nominal km/h A/S',150)]:
            self.table.heading(key, text=title)
            self.table.column(key, width=width, minwidth=70, stretch=True)
        self.table.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(actors, orient='vertical', command=self.table.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.table.configure(yscrollcommand=scroll.set)
        self.table.bind('<<TreeviewSelect>>', self._selection_changed)
        ttk.Label(actors, text='Ctrl: pick several · Shift: select a range.',
                  foreground='#5f6875', wraplength=420).grid(row=1, column=0, sticky='w', pady=(6, 0))
        self.select_speed_button = ttk.Button(actors, text='Select speed-eligible',
                                              command=self.select_speed_eligible)
        self.select_speed_button.grid(row=2, column=0, sticky='w', pady=(6, 0))
        view = ttk.Frame(lists, padding=(0, 8, 0, 0))
        view.columnconfigure(0, weight=1)
        view.rowconfigure(1, weight=1)
        lists.add(view, text='Top view')
        ttk.Label(view, textvariable=self.map_notice, wraplength=420,
                  foreground='#5f6875').grid(row=0, column=0, sticky='w', pady=(0, 6))
        self.map_canvas = tk.Canvas(view, background='#f5f7f9', highlightthickness=0,
                                    width=450, height=350)
        self.map_canvas.grid(row=1, column=0, sticky='nsew')
        self.map_canvas.bind('<Configure>', lambda _event: self._draw_traffic())
        self.map_canvas.bind('<Button-1>', self._map_select)
        self.map_canvas.bind('<MouseWheel>', self._map_zoom)
        self.map_canvas.bind('<ButtonPress-3>',self._map_pan_start)
        self.map_canvas.bind('<B3-Motion>',self._map_pan)
        self.map_canvas.bind('<ButtonRelease-3>',self._map_pan_end)
        map_footer = ttk.Frame(view)
        map_footer.grid(row=2, column=0, sticky='ew', pady=(6, 0))
        map_footer.columnconfigure(1,weight=1)
        self.mark_button = ttk.Button(map_footer, text='Mark position', command=self._mark_position)
        self.mark_button.grid(row=0,column=0,sticky='w')
        self.routes_check = ttk.Checkbutton(map_footer,text='Show lanes',variable=self.show_routes,
                                            command=self._routes_changed)
        self.routes_check.grid(row=0,column=1,sticky='w',padx=8)
        ttk.Label(map_footer, text='Wheel: zoom · right button: pan', foreground='#5f6875',
                  wraplength=270).grid(row=1,column=0,columnspan=2,sticky='w',pady=(5,0))
        ttk.Button(map_footer, text='Fit', command=self._map_reset).grid(row=0,column=2,sticky='e')
        ttk.Button(map_footer,text='Path',command=self._map_selected_path).grid(row=1,column=2,sticky='e',pady=(5,0))
        point_controls = ttk.LabelFrame(view, text='Add at point X/Z', padding=8)
        point_controls.grid(row=3, column=0, sticky='ew', pady=(8, 0))
        point_controls.columnconfigure(1, weight=1)
        point_controls.columnconfigure(3, weight=1)
        ttk.Label(point_controls, text='X').grid(row=0, column=0, padx=(0, 5))
        self.point_x_entry = ttk.Entry(point_controls, textvariable=self.point_x, width=12)
        self.point_x_entry.grid(row=0, column=1, sticky='ew')
        ttk.Label(point_controls, text='Z').grid(row=0, column=2, padx=(10, 5))
        self.point_z_entry = ttk.Entry(point_controls, textvariable=self.point_z, width=12)
        self.point_z_entry.grid(row=0, column=3, sticky='ew')
        self.add_at_button = ttk.Button(point_controls, text='Add at point', command=self.add_at)
        self.add_at_button.grid(row=1, column=0, columnspan=4, sticky='ew', pady=(7, 0))
        ttk.Label(point_controls,
            text='Uses a reference with verified path and physics and the model chosen beside it. The point may be snapped to the lane.',
            foreground='#5f6875', wraplength=410).grid(row=2, column=0, columnspan=4, sticky='w', pady=(5, 0))
        catalog = ttk.Frame(lists, padding=(0, 8, 0, 0))
        catalog.columnconfigure(0, weight=1)
        catalog.rowconfigure(0, weight=1)
        lists.add(catalog, text='Loaded catalogue')
        self.catalog_table = ttk.Treeview(catalog,
            columns=('model', 'type', 'availability'), show='headings', selectmode='none', height=15)
        for key, title, width in [('model', 'Model', 150), ('type', 'Category', 105),
                                  ('availability', 'Creation', 185)]:
            self.catalog_table.heading(key, text=title)
            self.catalog_table.column(key, width=width, minwidth=70, stretch=True)
        self.catalog_table.grid(row=0, column=0, sticky='nsew')
        catalog_scroll = ttk.Scrollbar(catalog, orient='vertical', command=self.catalog_table.yview)
        catalog_scroll.grid(row=0, column=1, sticky='ns')
        self.catalog_table.configure(yscrollcommand=catalog_scroll.set)
        project_container = ttk.Frame(lists)
        project_container.columnconfigure(0, weight=1)
        project_container.rowconfigure(0, weight=1)
        lists.add(project_container, text='Project')
        self.project_canvas = tk.Canvas(project_container, highlightthickness=0, height=200,
            background=ttk.Style(root).lookup('TFrame','background') or root.cget('background'))
        self.project_canvas.grid(row=0, column=0, sticky='nsew')
        project_scroll = ttk.Scrollbar(project_container, orient='vertical', command=self.project_canvas.yview)
        project_scroll.grid(row=0, column=1, sticky='ns')
        self.project_canvas.configure(yscrollcommand=project_scroll.set)
        project_tab = ttk.Frame(self.project_canvas, padding=12)
        self.project_window = self.project_canvas.create_window(0,0,window=project_tab,anchor='nw')
        project_tab.bind('<Configure>',self._project_region)
        self.project_canvas.bind('<Configure>',self._project_resize)
        project_tab.columnconfigure(0, weight=1)
        project_tab.columnconfigure(1, weight=1)
        ttk.Label(project_tab, text='Name for a new project').grid(row=0, column=0, sticky='w')
        ttk.Button(project_tab, text='Native events…', command=self.open_native_events).grid(
            row=0, column=1, sticky='e')
        self.project_name_entry = ttk.Entry(project_tab, textvariable=self.project_name)
        self.project_name_entry.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(5, 10))
        self.new_project_button = ttk.Button(project_tab, text='Create project…', command=self.create_project)
        self.new_project_button.grid(row=2, column=0, sticky='ew', padx=(0, 5))
        self.open_project_button = ttk.Button(project_tab, text='Open project…', command=self.open_project)
        self.open_project_button.grid(row=2, column=1, sticky='ew', padx=(5, 0))
        self.save_project_button = ttk.Button(project_tab, text='Save scene to project', command=self.save_project)
        self.save_project_button.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(8, 0))
        self.test_project_button = ttk.Button(project_tab, text='Test scene', command=self.test_project)
        self.test_project_button.grid(row=4, column=0, sticky='ew', padx=(0, 5), pady=(8, 0))
        self.restart_project_button = ttk.Button(project_tab, text='Back to start', command=self.restart_project)
        self.restart_project_button.grid(row=4, column=1, sticky='ew', padx=(5, 0), pady=(8, 0))
        self.restore_base_button = ttk.Button(project_tab, text='Restore original base', command=self.restore_project_base)
        self.restore_base_button.grid(row=5, column=0, columnspan=2, sticky='ew', pady=(8, 0))
        self.project_help_label = ttk.Label(project_tab, text='Test saves the scene and resumes the game. Back to start restores that saved scene; '
                  "pause PCSX2 first. Restore base brings back the project's original reference.",
                  wraplength=400, foreground='#5f6875')
        self.project_help_label.grid(row=6, column=0, columnspan=2, sticky='w', pady=(12, 0))
        self.project_status_label = ttk.Label(project_tab, textvariable=self.project_text, wraplength=400,
                  foreground='#305d86')
        self.project_status_label.grid(row=7, column=0, columnspan=2, sticky='w', pady=(12, 0))
        manual_project = ttk.LabelFrame(project_tab, text='Alternative without a free slot', padding=10)
        manual_project.grid(row=8, column=0, columnspan=2, sticky='ew', pady=(16, 0))
        manual_project.columnconfigure(0, weight=1)
        manual_project.columnconfigure(1, weight=1)
        self.import_project_button = ttk.Button(manual_project, text='Create from .p2s…', command=self.import_project)
        self.import_project_button.grid(row=0, column=0, sticky='ew', padx=(0, 4))
        self.save_project_state_button = ttk.Button(manual_project, text='Save scene from .p2s…', command=self.save_project_from_state)
        self.save_project_state_button.grid(row=0, column=1, sticky='ew', padx=(4, 0))
        self.confirm_scene_button = ttk.Button(manual_project, text='Check loaded scene…', command=self.confirm_project_scene)
        self.confirm_scene_button.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(8, 0))
        self.confirm_base_button = ttk.Button(manual_project, text='Check loaded base…', command=self.confirm_project_base)
        self.confirm_base_button.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(8, 0))
        self.project_manual_label = ttk.Label(manual_project,
            text='No free slot: save/load with System → Save/Load state → File… and check it here. '
                 'The files must match the paused scene.', wraplength=360, foreground='#5f6875')
        self.project_manual_label.grid(row=3, column=0, columnspan=2, sticky='w', pady=(10, 0))
        self.slot_manager_button = ttk.Button(project_tab, text='Manage slots…', command=self.manage_slots)
        self.slot_manager_button.grid(row=9, column=0, columnspan=2, sticky='ew', pady=(14, 0))
        pane.add(list_frame, weight=3)

        details_panel = ttk.Frame(pane)
        details_panel.columnconfigure(0,weight=1)
        details_panel.rowconfigure(0,weight=1)
        self.details_canvas = tk.Canvas(details_panel,width=360,height=200,highlightthickness=0,
            background=ttk.Style(root).lookup('TFrame','background') or root.cget('background'))
        self.details_canvas.grid(row=0,column=0,sticky='nsew')
        self.details_scroll = ttk.Scrollbar(details_panel,orient='vertical',command=self.details_canvas.yview)
        self.details_scroll.grid(row=0,column=1,sticky='ns')
        self.details_canvas.configure(yscrollcommand=self.details_scroll.set)
        details = ttk.Frame(self.details_canvas, padding=(18,0,6,12))
        self.details_window = self.details_canvas.create_window(0,0,window=details,anchor='nw')
        details.bind('<Configure>',self._details_region)
        self.details_canvas.bind('<Configure>',self._details_resize)
        details.columnconfigure(0, weight=1)
        pane.add(details_panel, weight=2)
        self.selection_label = ttk.Label(details,textvariable=self.selection_text,
                                        font=('Segoe UI',11,'bold'),wraplength=320)
        self.selection_label.grid(row=0,column=0,sticky='w')
        position = ttk.Frame(details)
        position.grid(row=1,column=0,sticky='ew',pady=(7,14))
        self.position_label = ttk.Label(position,textvariable=self.position_text,wraplength=320)
        self.position_label.grid(row=0,column=0,sticky='w')
        self.speed_label = ttk.Label(position,textvariable=self.speed_text,wraplength=320,foreground='#5f6875')
        self.speed_label.grid(row=1,column=0,sticky='w',pady=(5,0))

        movement = ttk.LabelFrame(details, text='Move the selected vehicle', padding=12)
        movement.grid(row=2, column=0, sticky='ew')
        movement.columnconfigure(0, weight=1)
        ttk.Label(movement, text='Position across the lane width').grid(row=0, column=0, sticky='w')
        self.lateral_scale = ttk.Scale(movement, from_=0, to=100, orient='horizontal',
                                       variable=self.lateral, command=self._lateral_changed)
        self.lateral_scale.grid(row=1, column=0, sticky='ew', pady=9)
        ttk.Label(movement, textvariable=self.lateral_text).grid(row=1, column=1, padx=(8, 0))
        ttk.Label(movement, text='The position along the path is kept.',
                  wraplength=280, foreground='#5f6875').grid(row=2, column=0, columnspan=2, sticky='w')
        self.move_button = ttk.Button(movement, text='Apply position', command=self.move)
        self.move_button.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(10, 0))
        self.speed_controls = ttk.Frame(movement)
        self.speed_controls.grid(row=4,column=0,columnspan=2,sticky='ew',pady=(12,0))
        self.speed_controls.columnconfigure(1,weight=1)
        ttk.Label(self.speed_controls,text='Nominal target (km/h)').grid(row=0,column=0,sticky='w',padx=(0,8))
        self.speed_entry = ttk.Entry(self.speed_controls,textvariable=self.speed_target_kmh,width=10)
        self.speed_entry.grid(row=0,column=1,sticky='ew')
        self.speed_button = ttk.Button(self.speed_controls,text='Apply speed',command=self.set_speed)
        self.speed_button.grid(row=1,column=0,columnspan=2,sticky='ew',pady=(7,0))
        self.speed_selection_label = ttk.Label(self.speed_controls, textvariable=self.speed_selection_text,
                                                wraplength=300, foreground='#5f6875')
        self.speed_selection_label.grid(row=2,column=0,columnspan=2,sticky='w',pady=(6,0))
        self.speed_controls.grid_remove()

        addition = ttk.LabelFrame(details, text='Add vehicles behind', padding=12)
        addition.grid(row=3, column=0, sticky='ew', pady=(14, 0))
        addition.columnconfigure(0, weight=1)
        ttk.Label(addition, text='Model of the new vehicles').grid(row=0, column=0, sticky='w')
        self.model_box = ttk.Combobox(addition, textvariable=self.model_choice,
                                      values=('Same model as selected',), state='readonly', width=29)
        self.model_box.grid(row=1, column=0, sticky='ew', pady=(5, 9))
        self.model_box.bind('<<ComboboxSelected>>', self._model_changed)
        distance = ttk.Frame(addition)
        distance.grid(row=2, column=0, sticky='ew')
        distance.columnconfigure(1, weight=1)
        ttk.Label(distance, text='Distance behind').grid(row=0, column=0, sticky='w', padx=(0, 8))
        self.gap_entry = ttk.Entry(distance, textvariable=self.gap, width=10)
        self.gap_entry.grid(row=0, column=1, sticky='ew')
        self.count_label = ttk.Label(distance, text='Amount')
        self.count_label.grid(row=0, column=2, padx=(10, 8))
        self.count_box = ttk.Spinbox(distance, from_=1, to=8, textvariable=self.count, width=4)
        self.count_box.grid(row=0, column=3)
        self.gap_hint = ttk.Label(addition, text='From 8 to 50 game units.', foreground='#5f6875')
        self.gap_hint.grid(row=3, column=0, sticky='w', pady=(5, 0))
        self.secondary_label = ttk.Label(addition, text='Truck trailer')
        self.secondary_label.grid(row=4, column=0, sticky='w', pady=(9, 0))
        self.secondary_box = ttk.Combobox(addition, textvariable=self.secondary_choice,
            values=('Select the trailer',), state='disabled', width=29)
        self.secondary_box.grid(row=5, column=0, sticky='ew', pady=(5, 0))
        self.secondary_label.grid_remove()
        self.secondary_box.grid_remove()
        self.add_button = ttk.Button(addition, text='Add vehicles behind', command=self.add_behind)
        self.spawn_mode_box = ttk.Combobox(addition, textvariable=self.spawn_mode,
            values=('Single model','Alternate models'),state='readonly',width=29)
        self.spawn_mode_box.grid(row=6,column=0,sticky='ew',pady=(10,0))
        self.spawn_mode_box.bind('<<ComboboxSelected>>',self._spawn_options_changed)
        self.mixed_button = ttk.Button(addition,text='Choose alternating models…',command=self.choose_mixed_models)
        self.mixed_button.grid(row=7,column=0,sticky='ew',pady=(6,0))
        self.mixed_label = ttk.Label(addition,textvariable=self.mixed_text,wraplength=300,foreground='#5f6875')
        self.mixed_label.grid(row=8,column=0,sticky='w',pady=(5,0))
        self.spawn_color_label = ttk.Label(addition,text='Batches: experimental visual variation (colour to be confirmed)',
            wraplength=300,foreground='#5f6875')
        self.spawn_color_label.grid(row=9,column=0,sticky='w',pady=(10,0))
        self.spawn_color_box = ttk.Combobox(addition,textvariable=self.spawn_color,
            values=('Original (0)','Alternate variants (0–7)'),state='readonly',width=29)
        self.spawn_color_box.grid(row=10,column=0,sticky='ew',pady=(5,0))
        self.add_button.grid(row=11, column=0, sticky='ew', pady=(11, 0))

        footer = ttk.Frame(container)
        footer.grid(row=4, column=0, sticky='ew', pady=(16, 0))
        footer.columnconfigure(3, weight=1)
        self.save_button = ttk.Button(footer, text='Save configuration…', command=self.save_preset)
        self.save_button.grid(row=0, column=0)
        self.load_button = ttk.Button(footer, text='Open configuration…', command=self.load_preset)
        self.load_button.grid(row=0, column=1, padx=8)
        self.export_button = ttk.Button(footer, text='Save state…', command=self.export_state)
        self.export_button.grid(row=0, column=2)
        self.export_button.grid_remove()
        ttk.Label(footer, text='The JSON recipe and the state are separate files.',
                  foreground='#5f6875', wraplength=260).grid(row=0, column=3, sticky='e', padx=(10, 0))
        self.progress = ttk.Progressbar(container, mode='indeterminate')
        self.progress.grid(row=5, column=0, sticky='ew', pady=(13, 6))
        self.status_label = ttk.Label(container, textvariable=self.status,
                                      foreground='#273444', wraplength=950)
        self.status_label.grid(row=6, column=0, sticky='ew')

    def selected(self) -> dict[str, Any] | None:
        selected = self.table.selection()
        if not selected:
            return None
        focused = self.table.focus()
        return self.vehicles.get(focused if focused in selected else selected[0])

    def selected_vehicles(self) -> list[dict[str, Any]]:
        """Return every selected actor; the focused actor remains the primary."""
        return [self.vehicles[iid] for iid in self.table.selection() if iid in self.vehicles]

    def select_speed_eligible(self) -> None:
        if (self.closed or self.busy or self.pending or not self.connected
                or not getattr(self, 'profile_valid', True) or self.core_paused is not True):
            return
        iids = [iid for iid, vehicle in self.vehicles.items()
                if vehicle.get('can_set_speed') is True and vehicle.get('active', True)]
        self.table.selection_set(iids)
        if iids:
            if self.table.focus() not in iids:
                self.table.focus(iids[0])
            self.table.see(self.table.focus())
        self._selection_changed()

    def _project_region(self, _event: Any = None) -> None:
        if hasattr(self, 'project_canvas') and not self.closed:
            self.project_canvas.configure(scrollregion=self.project_canvas.bbox('all') or (0,0,1,1))

    def _project_resize(self, event: Any) -> None:
        if self.closed or not hasattr(self, 'project_canvas'):
            return
        width=max(1,int(event.width))
        self.project_canvas.itemconfigure(self.project_window, width=width)
        for name in ('project_help_label', 'project_status_label'):
            label=getattr(self,name,None)
            if label is not None:
                label.configure(wraplength=max(100,width-24))
        if hasattr(self, 'project_manual_label'):
            self.project_manual_label.configure(wraplength=max(100,width-48))
        self._project_region()

    def _details_region(self,_event: Any = None) -> None:
        """Keep controls reachable through a local scrollbar on short windows."""
        if hasattr(self,'details_canvas') and not self.closed:
            self.details_canvas.configure(scrollregion=self.details_canvas.bbox('all') or (0,0,1,1))

    def _details_resize(self,event: Any) -> None:
        if self.closed or not hasattr(self,'details_canvas'):
            return
        width=max(1,int(event.width))
        self.details_canvas.itemconfigure(self.details_window,width=width)
        for name in ('selection_label','position_label','speed_label','speed_selection_label',
                     'mixed_label','spawn_color_label'):
            label=getattr(self,name,None)
            if label is not None:
                label.configure(wraplength=max(100,width-24))
        self._details_region()

    def _selection_changed(self, _event: Any = None) -> None:
        vehicle = self.selected()
        selections = self.selected_vehicles()
        if hasattr(self,'speed_text'):
            self.speed_text.set(speed_summary(vehicle,detailed=True))
        if hasattr(self,'speed_target_kmh'):
            info = (vehicle or {}).get('speed_info') or {}
            target = info.get('nominal_target_kmh')
            if type(target) not in (int,float) and type(info.get('control_value')) in (int,float):
                target = info['control_value']*NOMINAL_KMH_PER_CONTROL
            self.speed_target_kmh.set(f'{target:.9g}'.replace('.',',')
                if type(target) in (int,float) and math.isfinite(target) else '')
        if vehicle is None:
            self.selection_text.set('Select a vehicle in the list.')
            self.position_text.set('X: —     Y: —     Z: —')
        else:
            self.selection_text.set(str(vehicle.get('label') or f"Vehicle {vehicle['id']}"))
            if len(selections) > 1:
                self.selection_text.set(f'{len(selections)} selected · focus: ' + self.selection_text.get())
            xyz = vehicle.get('position') or []
            self.position_text.set('     '.join(f'{axis}: {coordinate(xyz[i] if i < len(xyz) else None)}'
                                               for i, axis in enumerate('XYZ')))
            path = vehicle.get('path')
            self.position_text.set(self.position_text.get()+
                (f'\nPath: P{path}' if type(path) is int else '\nNo recognized traffic path.'))
            if vehicle.get('edit_reason'):
                self.position_text.set(self.position_text.get() + '\n' + str(vehicle['edit_reason']))
            reference_reason = vehicle.get('reference_reason')
            if (reference_reason and not vehicle.get('can_reference',vehicle.get('editable',False))
                    and reference_reason != vehicle.get('edit_reason')):
                self.position_text.set(self.position_text.get() + '\nAdd behind: ' + str(reference_reason))
            try:
                lateral = float(vehicle.get('lateral_percent', 50))
                if not math.isfinite(lateral):
                    raise ValueError
                self.lateral.set(max(0, min(100, lateral)))
            except (TypeError, ValueError):
                self.lateral.set(50)
            self._lateral_changed()
        self._update_secondary_choices()
        self._update_controls()
        self._draw_traffic()

    def _chosen_model(self) -> dict[str, Any]:
        selected = self.selected() or {}
        model_id = (getattr(self, 'model_choices', {}).get(self.model_choice.get())
                    if hasattr(self, 'model_choice') else None)
        model_id = model_id or selected.get('model_id')
        return getattr(self, 'models', {}).get(str(model_id), {})

    def _model_changed(self, _event: Any = None) -> None:
        self._update_secondary_choices()
        self._update_controls()

    def _experimental_enabled(self) -> bool:
        variable = getattr(self, 'experimental', None)
        return variable is not None and variable.get() is True

    def _alternating_models(self) -> bool:
        variable = getattr(self,'spawn_mode',None)
        return variable is not None and variable.get() == 'Alternate models'

    def _creation_ready(self) -> bool:
        vehicle = self.selected()
        return bool(not self.closed and not self.busy and not self.pending and self.connected
                    and getattr(self,'profile_valid',True) and self.core_paused is True
                    and vehicle and vehicle.get('active',True)
                    and vehicle.get('can_reference',vehicle.get('editable',False)))

    def _mixed_candidates(self) -> list[dict[str,Any]]:
        return [model for model in getattr(self,'models',{}).values()
                if model.get('eligible') is True and model.get('kind') not in ('truck','trailer')
                and model.get('type') in (1,2,3,5)]

    def _refresh_mixed_models(self) -> None:
        candidates = {str(model['id']):model for model in self._mixed_candidates()}
        self.mixed_model_ids = [model_id for model_id in getattr(self,'mixed_model_ids',[])
                                if model_id in candidates]
        if hasattr(self,'mixed_text'):
            names = [str(candidates[model_id].get('label') or model_id)
                     for model_id in self.mixed_model_ids]
            self.mixed_text.set((' → '.join(names) + ' → repeats. Trucks with trailers use Single model.')
                if names else 'Choose at least two loaded models to alternate.')

    def _spawn_options_changed(self, _event=None) -> None:
        self._refresh_mixed_models()
        self._update_controls()

    def choose_mixed_models(self) -> None:
        if not self._creation_ready():
            return
        candidates = self._mixed_candidates()
        if len(candidates) < 2:
            messagebox.showinfo('Alternating models','This read needs at least two '
                'independent models available. Trucks with trailers stay in Single model mode.',parent=self.root)
            return
        dialog = tk.Toplevel(self.root)
        dialog.title('Alternating models')
        dialog.transient(self.root)
        dialog.geometry('440x360')
        dialog.columnconfigure(0,weight=1)
        dialog.rowconfigure(1,weight=1)
        ttk.Label(dialog,text='Select the models with Ctrl/Shift. The list order repeats in the batch.',
                  wraplength=400).grid(row=0,column=0,sticky='w',padx=14,pady=12)
        listing = tk.Listbox(dialog,selectmode='extended',exportselection=False,height=10)
        listing.grid(row=1,column=0,sticky='nsew',padx=14)
        for index,model in enumerate(candidates):
            listing.insert('end',str(model.get('label') or model['id']))
            if str(model['id']) in getattr(self,'mixed_model_ids',[]):
                listing.selection_set(index)
        def accept():
            if not self._creation_ready():
                dialog.destroy()
                return
            indexes = listing.curselection()
            if len(indexes) < 2:
                messagebox.showinfo('Alternating models','Choose at least two models.',parent=dialog)
                return
            self.mixed_model_ids = [str(candidates[index]['id']) for index in indexes]
            self.spawn_mode.set('Alternate models')
            self._refresh_mixed_models()
            self._update_controls()
            dialog.destroy()
        ttk.Button(dialog,text='Use selection',command=accept).grid(row=2,column=0,sticky='ew',padx=14,pady=12)
        dialog.grab_set()

    def _experimental_changed(self) -> None:
        if hasattr(self, 'count_box'):
            self.count_box.configure(to=253 if self._experimental_enabled() else 8)
        self._update_secondary_choices()
        self._update_controls()

    def _target_point(self) -> tuple[float, float] | None:
        try:
            return world_coordinate(self.point_x.get()), world_coordinate(self.point_z.get())
        except (AttributeError, TypeError, ValueError):
            return None

    def _point_changed(self, *_args: Any) -> None:
        self._update_controls()
        self._draw_traffic()

    def _mark_position(self) -> None:
        if (self.closed or self.busy or self.pending or not self.connected
                or not getattr(self, 'profile_valid', True) or self.core_paused is not True):
            return
        self.marking_position = not getattr(self, 'marking_position', False)
        if hasattr(self, 'mark_button'):
            self.mark_button.configure(text='Click the map…' if self.marking_position else 'Mark position')
        self._set_status('Click the top view to mark the creation point.' if self.marking_position
                         else 'Marking cancelled.')

    def _update_secondary_choices(self) -> None:
        if not hasattr(self, 'secondary_box'):
            return
        preferred = self.secondary_choices.get(self.secondary_choice.get())
        model = self._chosen_model()
        truck = model.get('kind') == 'truck'
        allowed = set(model.get('trailer_model_ids') or []) if truck else set()
        self.secondary_choices = {'Select the trailer': None}
        for index, secondary in enumerate(self.models.values()):
            if (secondary.get('kind') != 'trailer' or secondary.get('eligible_as_trailer') is not True
                    or secondary['id'] not in allowed):
                continue
            label = model_label(secondary, index)
            self.secondary_choices[label] = secondary['id']
        if preferred not in self.secondary_choices.values():
            preferred = None
        selected = self.selected() or {}
        if preferred is None and selected.get('model_id') == model.get('id') and selected.get('native_pair_valid') is True:
            native = selected.get('secondary_model_id')
            if native in self.secondary_choices.values():
                preferred = native
        self.secondary_choice.set(next((label for label, model_id in self.secondary_choices.items()
                                         if preferred is not None and model_id == preferred), 'Select the trailer'))
        self.secondary_box.configure(values=tuple(self.secondary_choices))
        self.count_label.configure(text='Conjuntos' if truck else 'Amount')
        self.add_button.configure(text='Add sets behind' if truck else 'Add vehicles behind')
        reference_model = self.models.get(str(selected.get('model_id')), {})
        compound = (truck or selected.get('kind') == 'truck' or reference_model.get('kind') == 'truck'
                    or model.get('type') == 5 or reference_model.get('type') == 5)
        if hasattr(self, 'gap_hint'):
            hint = ('Experimental: positive distance, limited by the path and the capacity.'
                    if self._experimental_enabled() else
                    'Bus/truck: 30 to 50 game units.' if compound
                    else 'From 8 to 50 game units.')
            self.gap_hint.configure(text=hint)
        if compound and not self._experimental_enabled():
            try:
                if number(self.gap.get()) < 30:
                    self.gap.set('30')
            except ValueError:
                pass
        if truck:
            self.secondary_label.grid()
            self.secondary_box.grid()
            if not self.trailer_visible:
                self.root.after_idle(self._fit_pending_window)
        else:
            self.secondary_label.grid_remove()
            self.secondary_box.grid_remove()
        self.trailer_visible = truck

    def _map_reset(self) -> None:
        self.map_view = None
        self.map_pan_state = None
        self._draw_traffic()

    def _routes_enabled(self) -> bool:
        variable = getattr(self,'show_routes',None)
        return variable is None or variable.get() is True

    def _routes_changed(self) -> None:
        self.map_view = None
        self.map_pan_state = None
        self._draw_traffic()

    def _map_selected_path(self) -> None:
        selected = self.selected() or {}
        network = getattr(self,'routes',{})
        paths = network.get('paths',[]) if isinstance(network,dict) else []
        paths = paths if isinstance(paths,list) else []
        route = next((path for path in paths if isinstance(path,dict)
                      and type(selected.get('path')) is int and path.get('id')==selected['path']),None)
        points = route_points({'paths':[route]}) if route is not None else []
        if not points or not getattr(self,'profile_valid',True):
            self._set_status('The selected vehicle has no path geometry in this read.',warning=True)
            return
        if hasattr(self,'show_routes'):
            self.show_routes.set(True)
        self.map_view = fit_view(points)
        self.map_pan_state = None
        self._draw_traffic()
        self._set_status(f"Path P{selected['path']} framed. The arrows show its direction of travel.")

    def _map_pan_start(self,event: Any) -> None:
        if self.map_view is not None:
            self.map_pan_state = event.x,event.y,self.map_view

    def _map_pan(self,event: Any) -> None:
        state = getattr(self,'map_pan_state',None)
        if state is None:
            return
        px,py,(cx,cz,span) = state
        width,height = self.map_canvas.winfo_width(),self.map_canvas.winfo_height()
        if width <= 40 or height <= 50 or span <= 0:
            return
        scale = min(width-40,height-50)/span
        self.map_view = cx-(event.x-px)/scale,cz+(event.y-py)/scale,span
        self._draw_traffic()

    def _map_pan_end(self,_event: Any = None) -> None:
        self.map_pan_state = None

    def _map_routes(self) -> list[dict[str,Any]]:
        network = getattr(self,'routes',{})
        if (not self._routes_enabled() or not getattr(self,'profile_valid',True)
                or not isinstance(network,dict) or not isinstance(network.get('paths'),list)):
            return []
        return [path for path in network['paths'] if isinstance(path,dict)]

    def _map_zoom(self, event: Any) -> None:
        if self.map_view is None or not event.delta:
            return
        cx, cz, span = self.map_view
        self.map_pan_state = None
        factor = 0.8 if event.delta > 0 else 1.25
        new_span = max(2, min(100000, span * factor))
        width, height = self.map_canvas.winfo_width(), self.map_canvas.winfo_height()
        side = min(max(1, width - 40), max(1, height - 50))
        dx, dz = event.x - width / 2, height / 2 - event.y
        self.map_view = (cx + dx / side * (span - new_span),
                         cz + dz / side * (span - new_span), new_span)
        self._draw_traffic()

    def _map_select(self, event: Any) -> None:
        if self.busy or self.pending or not getattr(self, 'profile_valid', True):
            return
        if getattr(self, 'marking_position', False):
            if not self.connected or self.core_paused is not True or self.map_view is None:
                return
            try:
                x, z = map_to_world(self.map_view, self.map_canvas.winfo_width(),
                                   self.map_canvas.winfo_height(), event.x, event.y)
            except ValueError as exc:
                self._set_status(str(exc), warning=True)
                return
            self.point_x.set(f'{x:.6f}')
            self.point_z.set(f'{z:.6f}')
            self.marking_position = False
            if hasattr(self, 'mark_button'):
                self.mark_button.configure(text='Mark position')
            self._point_changed()
            self._set_status(f'Point marked: X {coordinate(x)} · Z {coordinate(z)}. Check the model and add.')
            return
        if not self.map_hits:
            return
        px, py, iid = min(self.map_hits, key=lambda point:
                          (point[0] - event.x) ** 2 + (point[1] - event.y) ** 2)
        if math.hypot(px - event.x, py - event.y) <= 12:
            self.table.selection_set(iid)
            self.table.focus(iid)
            self.table.see(iid)
            self._selection_changed()

    def _draw_traffic(self) -> None:
        if not hasattr(self, 'map_canvas') or self.closed:
            return
        canvas = self.map_canvas
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 5 or height < 5:
            return
        canvas.delete('all')
        self.map_hits = []
        points = {iid: point for iid, vehicle in self.vehicles.items()
                  if vehicle.get('initialized') is True
                  and (point := xz(vehicle.get('position'))) is not None}
        player = xz(self.player.get('position')) if self.player else None
        target = self._target_point()
        paths = self._map_routes()
        path_points = route_points({'paths':paths})
        if not points and player is None and target is None and not path_points:
            canvas.create_text(width / 2, height / 2, text='Connect with the game paused and refresh the list.',
                               width=max(100, width - 40), fill='#5f6875')
            return
        if self.map_view is None:
            self.map_view = fit_view([*points.values(),*path_points,
                                     *([player] if player else []),*([target] if target else [])])
        cx, cz, span = self.map_view
        scale = min(max(1, width - 40), max(1, height - 50)) / span
        def project(point):
            return width / 2 + (point[0] - cx) * scale, height / 2 - (point[1] - cz) * scale
        canvas.create_text(10, 10, anchor='nw', text='X →   Z ↑   ·   game units', fill='#5f6875')
        selected_vehicle = self.selected() or {}
        selected_path = selected_vehicle.get('path')
        for path in paths:
            highlight = type(selected_path) is int and path.get('id') == selected_path
            candidate = path.get('source') == 'descriptor_candidate'
            color = '#bd871b' if highlight else '#b1bcc5' if candidate else '#9baab6'
            fill = '#fff0bd' if highlight else '#eff2f5' if candidate else '#e5ebf0'
            lines = {}
            for key in ('left','center','right'):
                raw = path.get(key)
                lines[key] = [xz(point) for point in raw] if isinstance(raw,list) else []
            left,right = lines['left'],lines['right']
            if (len(left) >= 2 and len(left) == len(right)
                    and all(point is not None for point in left+right)):
                polygon = [coordinate for point in left+list(reversed(right)) for coordinate in project(point)]
                canvas.create_polygon(*polygon,fill=fill,outline='')
            for key,line in lines.items():
                segment = []
                for point in [*line,None]:
                    if point is not None:
                        segment.extend(project(point))
                    else:
                        if len(segment) >= 4:
                            canvas.create_line(*segment,fill=color,width=2 if highlight else 1,
                                               **({'dash':(5,4)} if key == 'center' else
                                                  {'dash':(2,4)} if candidate else {}))
                        segment = []
            for arrow in path.get('arrows',[]) if isinstance(path.get('arrows'),list) else []:
                if not isinstance(arrow,dict):
                    continue
                start,end = xz(arrow.get('from')),xz(arrow.get('to'))
                if start is None or end is None or start == end:
                    continue
                canvas.create_line(*project(start),*project(end),arrow=tk.LAST,fill=color,
                                   width=2,**({} if path.get('traffic_direction_verified') is True else {'dash':(3,3)}))
            center = [point for point in lines['center'] if point is not None]
            if center and (highlight or len(paths) <= 32):
                px,py = project(center[len(center)//2])
                canvas.create_text(px+5,py-8,anchor='sw',
                    text=f"P{path.get('id','?')}"+('?' if candidate else ''),fill=color)
        if paths:
            canvas.create_text(10,28,anchor='nw',text='Traffic lanes · arrows: path direction',fill='#5f6875')
            if any(path.get('source') == 'descriptor_candidate' for path in paths):
                canvas.create_text(10,44,anchor='nw',width=max(100,width-20),
                    text='P?: candidate lane with no associated vehicle; current use not confirmed',fill='#7c8994')
        colors = {'Car': '#2c70b6', 'Van': '#7752a3', 'Bus': '#23846c'}
        selected = self.table.selection()
        for iid, point in points.items():
            px, py = project(point)
            if not -8 <= px <= width + 8 or not -8 <= py <= height + 8:
                continue
            vehicle = self.vehicles[iid]
            category = str(vehicle.get('type_label') or '')
            color = colors.get(category, '#71808f')
            outline = '#e4a400' if iid in selected else '#ffffff'
            canvas.create_oval(px - 5, py - 5, px + 5, py + 5, fill=color,
                               outline=outline, width=3 if iid in selected else 1)
            self.map_hits.append((px, py, iid))
            if iid in selected:
                canvas.create_text(px + 9, py - 10, anchor='sw',
                    text=str(vehicle.get('label') or 'Selected'), fill='#273444')
        if player is not None:
            px, py = project(player)
            forward = xz(self.player.get('forward'))
            if forward is not None and math.hypot(*forward) > 0.001:
                length = math.hypot(*forward)
                canvas.create_line(px, py, px + forward[0] / length * 23,
                                   py - forward[1] / length * 23, arrow=tk.LAST,
                                   fill='#b43c39', width=3)
            canvas.create_oval(px - 5, py - 5, px + 5, py + 5,
                               fill='#b43c39', outline='#ffffff', width=1)
            canvas.create_text(px + 9, py + 10, anchor='nw', text='Jogador', fill='#b43c39')
        if target is not None:
            px, py = project(target)
            if -8 <= px <= width + 8 and -8 <= py <= height + 8:
                canvas.create_line(px - 8, py, px + 8, py, fill='#a33922', width=2)
                canvas.create_line(px, py - 8, px, py + 8, fill='#a33922', width=2)
                canvas.create_text(px + 10, py - 9, anchor='sw', text='Create here', fill='#a33922')
        marker = min(80, width / 4)
        canvas.create_line(15, height - 20, 15 + marker, height - 20, fill='#5f6875', width=2)
        canvas.create_text(15, height - 25, anchor='sw', text=f'{marker / scale:.1f} un.', fill='#5f6875')

    def _lateral_changed(self, _value: Any = None) -> None:
        self.lateral_text.set(f'{self.lateral.get():.1f}%'.replace('.', ','))

    def _set_core_state(self, response: dict[str, Any]) -> None:
        if 'event_projects' in response:
            self.event_projects = response['event_projects'] is True
        if 'project' in response:
            project = response['project']
            self.project = dict(project) if isinstance(project, dict) else None
            if hasattr(self, 'project_text'):
                if self.project:
                    name = str(self.project.get('name') or 'Unnamed event')
                    revision = self.project.get('scene_revision', 0)
                    self.project_text.set(f'{name} · Saved scene {revision}\n' + str(self.project.get('path') or ''))
                    if hasattr(self, 'project_name'):
                        self.project_name.set(name)
                else:
                    self.project_text.set('No project open. Create a project from the paused scene or open an existing one.')
        paused = response.get('core_paused')
        if isinstance(paused, bool):
            self.core_paused = paused
            self.core_text.set('Game paused' if paused else 'Game running')
            if hasattr(self, 'map_notice'):
                notice = (('Traffic lane geometry; heights can overlap in the X/Z view.'
                    if getattr(self,'routes',{}).get('paths') else 'Vehicle positions; no track drawing.') if paused else
                    ('Positions from the last refresh; click Pause PCSX2 and refresh.'
                     if getattr(self, 'emulator_control', False) else
                     'Positions from the last refresh; pause with Esc and refresh.'))
                warning = getattr(self,'routes',{}).get('warning')
                self.map_notice.set(notice+(' '+warning if isinstance(warning,str) and warning else ''))
            return
        state = str(response.get('core_status') or response.get('status') or '').lower()
        if state == 'paused':
            self.core_paused = True
            self.core_text.set('Game paused')
        elif state == 'running':
            self.core_paused = False
            self.core_text.set('Game running')
        elif state in ('shutdown', 'stopped', 'disconnected'):
            self.core_paused = False
            self.core_text.set('No game loaded')

    def _update_controls(self) -> None:
        idle = not self.busy and not self.pending and not self.closed
        profile_valid = getattr(self, 'profile_valid', True)
        selected = self.selected()
        selections = self.selected_vehicles()
        available = bool(idle and self.connected and profile_valid and selected and selected.get('active', True)
                         and self.core_paused is True)
        editable = bool(available and (selected.get('editable', selected.get('eligible', False))
                        or (self._experimental_enabled() and selected.get('experimental_editable') is True)))
        can_reference = bool(available and selected.get('can_reference',
                              selected.get('editable', selected.get('eligible', False))))
        if hasattr(self,'speed_controls'):
            eligible = sum(vehicle.get('can_set_speed') is True and vehicle.get('active', True)
                           for vehicle in selections)
            blocked = len(selections) - eligible
            visible = bool(selections)
            if visible:
                self.speed_controls.grid()
                if not getattr(self,'speed_controls_visible',False) and hasattr(self,'root'):
                    self.root.after_idle(self._fit_pending_window)
            else:
                self.speed_controls.grid_remove()
            self.speed_controls_visible = visible
            can_set_speed = bool(available and selections and not blocked)
            for widget in (self.speed_entry,self.speed_button):
                widget.configure(state='normal' if can_set_speed else 'disabled')
            self.speed_button.configure(text=(f'Apply to the {len(selections)} selected'
                                              if len(selections) > 1 else 'Apply speed'))
            if hasattr(self, 'speed_selection_text'):
                note = f'{len(selections)} selected · {eligible} eligible · {blocked} blocked.'
                if blocked:
                    note += (' Select only eligible vehicles. For a truck, select the cab; '
                             'the trailer follows the set.')
                elif len(selections) > 1:
                    note += (' The same target will be applied to all. Position and creation use the focused vehicle.')
                self.speed_selection_text.set(note)
        if hasattr(self, 'select_speed_button'):
            speed_available = any(vehicle.get('can_set_speed') is True and vehicle.get('active', True)
                                  for vehicle in self.vehicles.values())
            self.select_speed_button.configure(state='normal' if idle and self.connected and profile_valid
                and self.core_paused is True and speed_available else 'disabled')
        # A failed finalization can require a clean-state reload and reconnect.
        # Reconnection is serialized on the same worker and never retries a mutation.
        self.connect_button.configure(state='normal' if not self.busy and not self.closed else 'disabled')
        for widget in (self.refresh_button, self.save_button):
            widget.configure(state='normal' if idle and self.connected else 'disabled')
        self.load_button.configure(state='normal' if idle and self.connected
                                   and profile_valid and self.core_paused is True else 'disabled')
        if hasattr(self, 'finalize_button'):
            self.finalize_button.configure(state='normal' if self.connected and not self.busy
                and not self.closed and self.core_paused is True else 'disabled')
        if hasattr(self, 'cancel_queue_button'):
            self.cancel_queue_button.configure(state='normal' if self.connected and not self.busy
                and not self.closed else 'disabled')
        if hasattr(self, 'export_button'):
            export_available = bool(self.connected and self.state_export and not self.closed)
            if export_available:
                self.export_button.grid()
            else:
                self.export_button.grid_remove()
            self.export_button.configure(state='normal' if export_available and idle and profile_valid
                                         and self.core_paused is True else 'disabled')
        if hasattr(self, 'new_project_button'):
            project_ready = bool(idle and self.connected and profile_valid and self.core_paused is True
                                 and getattr(self, 'event_projects', False))
            for widget in (self.new_project_button, self.open_project_button, self.project_name_entry):
                widget.configure(state='normal' if project_ready else 'disabled')
            for widget in (self.save_project_button, self.test_project_button,
                           self.restart_project_button, self.restore_base_button):
                widget.configure(state='normal' if project_ready and getattr(self, 'project', None) else 'disabled')
            if hasattr(self, 'import_project_button'):
                for widget in (self.import_project_button, self.confirm_scene_button, self.confirm_base_button):
                    widget.configure(state='normal' if project_ready else 'disabled')
                self.save_project_state_button.configure(state='normal' if project_ready
                    and getattr(self, 'project', None) else 'disabled')
            if hasattr(self,'slot_manager_button'):
                self.slot_manager_button.configure(state='normal' if project_ready else 'disabled')
        for widget in (self.move_button, self.lateral_scale):
            widget.configure(state='normal' if editable else 'disabled')
        for widget in (self.add_button, self.gap_entry):
            widget.configure(state='normal' if can_reference else 'disabled')
        if hasattr(self, 'count_box'):
            self.count_box.configure(state='normal' if can_reference else 'disabled')
        for name in ('point_x_entry', 'point_z_entry', 'mark_button'):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.configure(state='normal' if can_reference else 'disabled')
        if hasattr(self, 'add_at_button'):
            self.add_at_button.configure(state='normal' if can_reference and self._target_point() is not None
                                          else 'disabled')
        if hasattr(self, 'experimental_check'):
            self.experimental_check.configure(state='normal' if idle else 'disabled')
        if hasattr(self, 'experimental_warning'):
            if self._experimental_enabled():
                self.experimental_warning.grid()
            else:
                self.experimental_warning.grid_remove()
        self.model_box.configure(state='readonly' if can_reference else 'disabled')
        if hasattr(self,'spawn_mode_box'):
            self.spawn_mode_box.configure(state='readonly' if can_reference else 'disabled')
            self.spawn_color_box.configure(state='readonly' if can_reference else 'disabled')
            mixed = self._alternating_models()
            self.mixed_button.configure(state='normal' if can_reference and mixed else 'disabled')
            if mixed:
                self.mixed_button.grid()
                self.mixed_label.grid()
            else:
                self.mixed_button.grid_remove()
                self.mixed_label.grid_remove()
        if hasattr(self, 'secondary_box'):
            self.secondary_box.configure(state='readonly' if can_reference
                and self._chosen_model().get('kind') == 'truck' else 'disabled')
        self.table.configure(selectmode='extended' if idle and profile_valid else 'none')
        if hasattr(self, 'emulator_controls'):
            supported = bool(self.connected and self.emulator_control and not self.closed)
            if supported:
                self.emulator_controls.grid()
            else:
                self.emulator_controls.grid_remove()
            for widget in (self.pause_button, self.resume_button):
                widget.configure(state='normal' if supported and not self.busy else 'disabled')
            self.instructions_text.set(
                'Use Pause PCSX2 and refresh the list before editing. Changes apply to the current session.'
                if supported else
                'Pause PCSX2 with Esc and refresh the list before editing. Changes apply to the current session.')
        if hasattr(self, 'pending_banner'):
            if self.pending:
                steps = ('1. Click Resume for a moment. 2. Click Pause PCSX2 '
                         'and wait for the confirmation.' if getattr(self, 'emulator_control', False) else
                         '1. Resume with Esc for a moment. 2. Pause with Esc '
                         '(System → Pause) and wait for the confirmation.')
                self.pending_text.set(
                    'CREATION PENDING — wait for it to finish before driving.\n'
                    + steps + '\n' + self.status.get())
                self.pending_banner.grid()
                if not getattr(self, 'pending_sized', False) and hasattr(self, 'root'):
                    self.pending_sized = True
                    self.root.after_idle(self._fit_pending_window)
            else:
                self.pending_banner.grid_remove()
                self.pending_sized = False

    def _fit_pending_window(self) -> None:
        """Keep pending instructions or cargo controls within the measured window."""
        if self.closed or not (self.pending or getattr(self, 'trailer_visible', False)
                               or getattr(self,'speed_controls_visible',False)):
            return
        height = min(max(820, self.root.winfo_reqheight()),
                     max(1, self.root.winfo_screenheight() - 80))
        if self.root.winfo_height() < height:
            self.root.geometry(f'{self.root.winfo_width()}x{height}')

    def _set_status(self, message: str, *, warning: bool = False) -> None:
        self.status.set(f'Warning: {message}' if warning else message)
        if hasattr(self, 'status_label'):
            self.status_label.configure(foreground='#8a5200' if warning else '#273444')

    def _invalidate_profile(self) -> None:
        self.profile_valid = False
        self.native_identity = None
        self.routes = {}
        if hasattr(self.table, 'selection') and hasattr(self.table, 'selection_remove'):
            self.table.selection_remove(*self.table.selection())
        if hasattr(self, 'selection_text'):
            self.selection_text.set('Refresh the list before editing the vehicles.')
            self.position_text.set('X: —     Y: —     Z: —')
        if hasattr(self,'speed_text'):
            self.speed_text.set('Speed: refresh the read to check it.')

    def _submit(self, label: str, action: Callable[[], Any],
                callback: Callable[[Any], None], *, quiet: bool = False) -> None:
        if self.busy or self.closed:
            return
        self.busy = True
        if not quiet:
            self._set_status(label)
        if not self.pending:
            self.progress.start(12)
        self._update_controls()
        self.jobs.put((action, callback))

    def _work(self) -> None:
        while True:
            job = self.jobs.get()
            if job is None:
                return
            action, callback = job
            try:
                result = action()
            except Exception as exc:
                self.results.put((callback, None, str(exc).strip() or type(exc).__name__))
            else:
                self.results.put((callback, result, None))

    def _poll(self) -> None:
        if self.closed:
            return
        try:
            callback, value, error = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            if error:
                self._set_status(f'Error: {error}')
                if self.pending:
                    self._schedule_pending_poll(2000)
                else:
                    messagebox.showerror('Action not completed', error, parent=self.root)
            else:
                try:
                    callback(value)
                except Exception as exc:
                    self._set_status(f'Could not show the response: {exc}')
                    if self.pending:
                        self._schedule_pending_poll(2000)
            if self.closed:
                return
            if not self.pending:
                self.progress.stop()
            self._update_controls()
        self.poll_id = self.root.after(60, self._poll)

    def _snapshot(self, snapshot: dict[str, Any], selected_id: int | None = None) -> None:
        self.native_identity = snapshot.get('native_identity')
        current = self.selected()
        selected_ids = {vehicle['id'] for vehicle in self.selected_vehicles()}
        chosen_model = self.model_choices.get(self.model_choice.get())
        if selected_id is None and current:
            selected_id = current['id']
        if selected_id is not None:
            selected_ids.add(selected_id)
        self.models = {str(model['id']): model for model in snapshot.get('models', [])}
        self._refresh_mixed_models()
        self.profile_valid = (snapshot.get('profile_valid') is not False
                              and isinstance(snapshot.get('vehicles'), list)
                              and isinstance(snapshot.get('models'), list))
        if 'emulator_control' in snapshot:
            self.emulator_control = snapshot['emulator_control'] is True
        if 'state_export' in snapshot:
            self.state_export = snapshot['state_export'] is True
        self.player = snapshot.get('player')
        self.routes = snapshot.get('routes') if self.profile_valid and isinstance(snapshot.get('routes'),dict) else {}
        if hasattr(self, 'capacity_text'):
            self.capacity_text.set(capacity_summary(snapshot))
        self.map_view = None
        self.map_pan_state = None
        self._set_core_state(snapshot)
        self.catalog_table.delete(*self.catalog_table.get_children())
        for row in catalog_rows(snapshot.get('models', [])):
            self.catalog_table.insert('', 'end', values=row)
        self.model_choices = {'Same model as selected': None}
        for index, model in enumerate(snapshot.get('models', [])):
            if model.get('eligible') is not True or model.get('kind') == 'trailer':
                continue
            base = model_label(model, index)
            label, suffix = base, 2
            while label in self.model_choices:
                label = f'{base} [{suffix}]'
                suffix += 1
            self.model_choices[label] = str(model['id'])
        self.model_box.configure(values=tuple(self.model_choices))
        self.model_choice.set(next((label for label, model_id in self.model_choices.items()
                                    if chosen_model is not None and model_id == chosen_model),
                                   'Same model as selected'))
        self.table.delete(*self.table.get_children())
        self.vehicles.clear()
        selected_iids = []
        focused_iid = None
        for index, vehicle in enumerate(snapshot.get('vehicles', [])):
            iid = f'vehicle-{index}'
            self.vehicles[iid] = vehicle
            self.table.insert('', 'end', iid=iid,
                              values=(f"Vehicle {vehicle['id']}",
                                      vehicle.get('type_label') or 'Unidentified',
                                      str(vehicle.get('model_id') or 'Unnamed model'),speed_summary(vehicle)))
            if vehicle['id'] in selected_ids:
                selected_iids.append(iid)
            if vehicle['id'] == selected_id:
                focused_iid = iid
        self.table.selection_set(selected_iids)
        if focused_iid is None and selected_iids:
            focused_iid = selected_iids[0]
        if focused_iid is not None:
            self.table.focus(focused_iid)
            self.table.see(focused_iid)
        self._selection_changed()
        self._set_status(str(snapshot.get('status') or f'{len(self.vehicles)} vehicles listed.'))

    def connect(self) -> None:
        self.connected = False
        self.connection_text.set('Connecting…')
        def work():
            connection = self.controller.connect()
            if connection.get('profile_valid') is False:
                return connection, connection
            if (connection.get('core_paused') is True and isinstance(connection.get('vehicles'),list)
                    and isinstance(connection.get('models'),list)):
                return connection,connection
            from editor.profile import ProfileError
            try:
                snapshot = self.controller.refresh()
            except ProfileError as exc:
                # Identity/transport errors remain connection failures. Only a
                # rejected traffic profile permits the explicit recovery action.
                message = f'Connected to PCSX2, but the list could not be validated: {exc}'
                snapshot = {**connection, 'profile_valid': False, 'warning': True,
                            'models': [], 'vehicles': [], 'status': message, 'message': message}
            return connection, snapshot
        def done(value):
            connection, snapshot = value
            self.connected = True
            self.emulator_control = connection.get('emulator_control') is True
            self.state_export = connection.get('state_export') is True
            self._set_pending(bool(snapshot.get('pending', connection.get('pending', False))))
            parts = [str(connection.get(key) or '') for key in ('game', 'profile')]
            self.connection_text.set(' · '.join(part for part in parts if part) or 'Conectado')
            self._set_core_state(connection)
            self._snapshot(snapshot)
            if snapshot.get('warning'):
                self._set_status(str(snapshot.get('message') or snapshot.get('status')
                                     or 'Check the result before continuing.'), warning=True)
            if self.pending:
                self._schedule_pending_poll()
        self._submit('Connecting to the emulator…', work, done)

    def refresh(self) -> None:
        self._submit('Refreshing the vehicles…', self.controller.refresh, self._snapshot)

    def pause_emulator(self) -> None:
        if self.connected and self.emulator_control:
            self._change('Pausing PCSX2…', self.controller.pause)

    def resume_emulator(self) -> None:
        if self.connected and self.emulator_control:
            self._change('Resuming PCSX2…', self.controller.resume)

    def finalize_pending(self) -> None:
        if (self.closed or self.busy or not self.connected or self.core_paused is not True):
            return
        self._change('Finishing the pending request…', self.controller.finalize_pending)

    def cancel_queue(self) -> None:
        if self.closed or self.busy or not self.connected:
            return
        self._change('Cancelling the rest of the queue…', self.controller.cancel_queue)

    def _change(self, label: str, action: Callable[[], dict[str, Any]]) -> None:
        def work():
            result = action()
            if result.get('pending'):
                return result, None, None
            try:
                snapshot = self.controller.refresh()
            except Exception as exc:
                return result, None, str(exc).strip() or type(exc).__name__
            return result, snapshot, None
        def done(value):
            result, snapshot, refresh_error = value
            self._set_pending(bool(result.get('pending') if 'pending' in result else
                                   snapshot.get('pending') if snapshot is not None else False))
            self._set_core_state(result)
            if snapshot is not None:
                self._snapshot(snapshot, result.get('new_vehicle_id'))
            if result.get('core_paused') is False:
                # A successful Test resumes simulation; never reuse a stale
                # paused snapshot for any later edit, even if refresh raced.
                self._set_core_state(result)
                self._invalidate_profile()
            message = str(result.get('message') or 'Change applied.')
            if refresh_error:
                self._invalidate_profile()
                message += f' The list could not be refreshed: {refresh_error}. Use Refresh list.'
            self._set_status(message, warning=bool(result.get('warning') or refresh_error))
            if self.pending:
                self._schedule_pending_poll()
        self._submit(label, work, done)

    def _set_pending(self, pending: bool) -> None:
        self.pending = pending
        timer = getattr(self, 'pending_poll_id', None)
        if not pending and timer is not None:
            self.pending_poll_id = None
            try:
                self.root.after_cancel(timer)
            except tk.TclError:
                pass

    def _schedule_pending_poll(self, delay: int = 500) -> None:
        if self.closed or not self.pending or self.pending_poll_id is not None:
            return
        self.pending_poll_id = self.root.after(delay, self._poll_pending)

    def _poll_pending(self) -> None:
        self.pending_poll_id = None
        if self.closed or not self.pending:
            return
        if self.busy:
            self._schedule_pending_poll()
            return
        def work():
            result = self.controller.poll()
            snapshot, refresh_error = None, None
            if not result.get('pending'):
                try:
                    snapshot = self.controller.refresh()
                except Exception as exc:
                    refresh_error = str(exc).strip() or type(exc).__name__
            return result, snapshot, refresh_error
        def done(value):
            result, snapshot, refresh_error = value
            self._set_pending(bool(result.get('pending')))
            self._set_core_state(result)
            if snapshot is not None:
                self._snapshot(snapshot, result.get('new_vehicle_id'))
            message = str(result.get('message') or '')
            if refresh_error:
                self._invalidate_profile()
                message += f' Use Refresh list: {refresh_error}'
            if message:
                self._set_status(message, warning=bool(result.get('warning') or refresh_error))
            if self.pending:
                self._schedule_pending_poll()
        self._submit('', work, done, quiet=True)

    def set_speed(self) -> None:
        vehicles = self.selected_vehicles()
        if (self.closed or self.busy or self.pending or not self.connected
                or not getattr(self,'profile_valid',True) or self.core_paused is not True
                or not vehicles):
            return
        if any(vehicle.get('can_set_speed') is not True or not vehicle.get('active', True)
               for vehicle in vehicles):
            messagebox.showinfo('Speed', 'The selection contains vehicles without a speed setting. '
                'Use Select speed-eligible; for a truck, select the cab.', parent=self.root)
            return
        try:
            nominal = number(self.speed_target_kmh.get())
            control = nominal/NOMINAL_KMH_PER_CONTROL
            if control < 0 or control > 3.4028234663852886e38:
                raise ValueError("Use a non-negative nominal target within the game's range.")
            if not self._experimental_enabled() and control > 240:
                if math.isclose(control,240,rel_tol=1e-12):
                    control = 240.
                else:
                    raise ValueError('In normal mode, use 0 to 386.24256 nominal km/h.')
        except (TypeError,ValueError) as exc:
            messagebox.showinfo('Speed',str(exc),parent=self.root)
            return
        vehicle_ids = [int(vehicle['id']) for vehicle in vehicles]
        options = {'experimental':True} if self._experimental_enabled() else {}
        self._change('Applying the nominal speed target…',
                     (lambda:self.controller.set_speed(vehicle_ids[0],control,**options))
                     if len(vehicle_ids) == 1 else
                     (lambda:self.controller.set_speeds(vehicle_ids,control,**options)))

    def move(self) -> None:
        vehicle = self.selected()
        if not vehicle:
            return
        try:
            lateral_percent = self.lateral.get()
            if not math.isfinite(lateral_percent) or not 0 <= lateral_percent <= 100:
                raise ValueError('Choose a position between 0% and 100%.')
        except ValueError as exc:
            messagebox.showinfo('Position', str(exc), parent=self.root)
            return
        vehicle_id = int(vehicle['id'])
        options = {'experimental': True} if self._experimental_enabled() else {}
        self._change('Applying the position…',
                     lambda: self.controller.move(vehicle_id, lateral_percent, **options))

    def add_behind(self) -> None:
        vehicle = self.selected()
        if not self._creation_ready() or not vehicle:
            return
        try:
            gap = number(self.gap.get(), positive=True)
            experimental = self._experimental_enabled()
            count = quantity(self.count.get(), experimental=experimental)
            chosen = self._chosen_model()
            mixed = self._alternating_models()
            choices = []
            if mixed:
                self._refresh_mixed_models()
                if len(self.mixed_model_ids) < 2:
                    raise ValueError('Choose at least two loaded models to alternate.')
                choices = [{'model_id':model_id} for model_id in self.mixed_model_ids]
            color_mode = ('cycle' if getattr(self,'spawn_color',None) is not None
                          and self.spawn_color.get() == 'Alternate variants (0–7)' else 'original')
            reference = getattr(self, 'models', {}).get(str(vehicle.get('model_id')), {})
            minimum = 30 if (chosen.get('kind') == 'truck' or reference.get('kind') == 'truck'
                             or chosen.get('type') == 5 or reference.get('type') == 5) else 8
            if mixed:
                minimum = 30 if (reference.get('kind') == 'truck' or reference.get('type') == 5
                                or any(self.models[item['model_id']].get('type') == 5 for item in choices)) else 8
            if not experimental and not minimum <= gap <= 50:
                raise ValueError(f'Use a distance between {minimum} and 50 game units.')
            secondary_id = None
            if not mixed and chosen.get('kind') == 'truck':
                secondary_id = self.secondary_choices.get(self.secondary_choice.get())
                if secondary_id is None:
                    raise ValueError('Choose a compatible trailer for the truck.')
        except ValueError as exc:
            messagebox.showinfo('Add vehicles', str(exc), parent=self.root)
            return
        vehicle_id = int(vehicle['id'])
        model_id = self.model_choices.get(self.model_choice.get())
        options = {'secondary_model_id': secondary_id}
        if experimental:
            options['experimental'] = True
        if color_mode != 'original':
            options['color_mode'] = color_mode
        if mixed:
            mixed_options = {key:value for key,value in options.items() if key != 'secondary_model_id'}
            self._change('Adding the alternating models behind…',
                         lambda:self.controller.add_mixed_behind(vehicle_id,choices,gap,count,**mixed_options))
            return
        self._change('Adding the vehicles behind…',
                     lambda: self.controller.add_many_behind(vehicle_id, model_id, gap, count,
                                                              **options))

    def add_at(self) -> None:
        if (self.closed or self.busy or self.pending or not self.connected
                or not getattr(self, 'profile_valid', True) or self.core_paused is not True):
            return
        vehicle = self.selected()
        if not vehicle or not vehicle.get('can_reference', vehicle.get('editable', False)):
            return
        try:
            x, z = world_coordinate(self.point_x.get()), world_coordinate(self.point_z.get())
            secondary_id = None
            if self._chosen_model().get('kind') == 'truck':
                secondary_id = self.secondary_choices.get(self.secondary_choice.get())
                if secondary_id is None:
                    raise ValueError('Choose a compatible trailer for the truck.')
        except (AttributeError, ValueError) as exc:
            messagebox.showinfo('Add at point', str(exc), parent=self.root)
            return
        vehicle_id = int(vehicle['id'])
        model_id = self.model_choices.get(self.model_choice.get())
        experimental = self._experimental_enabled()
        self._change('Preparing the vehicle at the marked point…',
                     lambda: self.controller.add_at(vehicle_id, model_id, x, z,
                         secondary_model_id=secondary_id, experimental=experimental))

    def save_preset(self) -> None:
        path = filedialog.asksaveasfilename(parent=self.root, title='Save configuration',
                    defaultextension='.json', filetypes=[('JSON configuration', '*.json')])
        if path:
            self._submit('Saving the configuration…',
                         lambda: self.controller.save_preset(str(Path(path))),
                         lambda result: self._set_status(str(result.get('message') or 'Configuration saved.')))

    def _project_ready(self, *, existing: bool = False) -> bool:
        return bool(not self.closed and not self.busy and not self.pending and self.connected
                    and getattr(self, 'profile_valid', False) and self.core_paused is True
                    and getattr(self, 'event_projects', False)
                    and (not existing or getattr(self, 'project', None)))

    def _slot_job(self,label,action,callback) -> None:
        if not self._project_ready():
            return
        def work():
            try:
                return {'result':action()}
            except Exception as error:
                return {'error':str(error).strip() or type(error).__name__}
        def done(response):
            if response.get('error'):
                self._set_status('Could not finish: '+response['error'],warning=True)
            else:
                result=response['result']
                self._set_core_state(result)
                if result.get('message'):
                    self._set_status(str(result['message']),warning=bool(result.get('warning')))
            callback(response)
        self._submit(label,work,done)

    def _archive_slot(self,row,callback,*,parent=None) -> None:
        if not self._project_ready():
            return
        try:
            description=slot_archive_description(row)
        except ValueError as error:
            messagebox.showinfo('Manage slots',str(error),parent=parent or self.root)
            return
        if not messagebox.askyesno('Archive and free slot',description,parent=parent or self.root):
            return
        # Do not use an old confirmation after the emulator changed pause or
        # the editor entered another action. The controller rechecks ownership.
        if not self._project_ready():
            return
        self._slot_job('Archiving the slot with a verified copy…',
                       lambda:self.controller.archive_state_slot(row['slot']),callback)

    def manage_slots(self) -> None:
        if not self._project_ready():
            return
        previous=getattr(self,'slot_dialog',None)
        if previous is not None:
            try:
                if previous.winfo_exists():
                    previous.lift()
                    return
            except tk.TclError:
                pass
        dialog=tk.Toplevel(self.root)
        self.slot_dialog=dialog
        dialog.title('Manage PCSX2 slots')
        dialog.transient(self.root)
        dialog.geometry('660x410')
        dialog.columnconfigure(0,weight=1)
        dialog.rowconfigure(1,weight=1)
        ttk.Label(dialog,text='Archiving keeps a verified copy and frees the slot; it does not permanently delete the save.',
                  wraplength=610).grid(row=0,column=0,sticky='w',padx=14,pady=12)
        table=ttk.Treeview(dialog,columns=('slot','state','size'),show='headings',selectmode='browse',height=10)
        for key,label,width in (('slot','Slot',55),('state','State',340),('size','Tamanho',120)):
            table.heading(key,text=label)
            table.column(key,width=width,stretch=key=='state')
        table.grid(row=1,column=0,sticky='nsew',padx=14)
        status=tk.StringVar(value='Reading the slots…')
        ttk.Label(dialog,textvariable=status,wraplength=610).grid(row=2,column=0,sticky='w',padx=14,pady=10)
        buttons=ttk.Frame(dialog)
        buttons.grid(row=3,column=0,sticky='ew',padx=14,pady=(0,12))
        state={'alive':True,'rows':{},'loading':False}
        refresh=ttk.Button(buttons,text='Refresh slots')
        archive=ttk.Button(buttons,text='Archive and free selected')
        refresh.pack(side='left')
        archive.pack(side='left',padx=8)
        def selected():
            selection=table.selection()
            return state['rows'].get(selection[0]) if selection else None
        def enable(_event=None):
            ready=state['alive'] and not state['loading'] and self._project_ready()
            refresh.configure(state='normal' if ready else 'disabled')
            row=selected()
            archive.configure(state='normal' if ready and row and row.get('occupied')
                              and not row.get('blocked') else 'disabled')
        def loaded(response):
            if not state['alive']:
                return
            state['loading']=False
            table.delete(*table.get_children())
            state['rows']={}
            if response.get('error'):
                status.set(response['error'])
            else:
                for row in response['result'].get('slots',[]):
                    iid=f"slot-{row['slot']}"
                    state['rows'][iid]=row
                    text=('Blocked: '+str(row.get('blocked')) if row.get('blocked') else
                          'Occupied' if row.get('occupied') else 'Free')
                    size=row.get('total_bytes',0)
                    table.insert('','end',iid=iid,values=(row['slot'],text,f'{size/1048576:.2f} MiB'))
                status.set('Select an occupied slot to see its files before archiving.')
            enable()
        def load():
            if not self._project_ready() or not state['alive']:
                return
            state['loading']=True
            enable()
            self._slot_job('Reading the PCSX2 slots…',self.controller.list_state_slots,loaded)
        def archived(response):
            if not state['alive']:
                return
            state['loading']=False
            if response.get('error'):
                status.set(response['error'])
                state['rows']={}
                table.delete(*table.get_children())
                enable()
            else:
                result=response['result']
                messagebox.showinfo('Slot archived',str(result.get('message') or 'Slot archived.')
                    +'\n\nBackup: '+str(result.get('archive_directory') or ''),parent=dialog)
                load()
        def submit_archive():
            row=selected()
            if row and not state['loading']:
                self._archive_slot(row,archived,parent=dialog)
                if self.busy:
                    state['loading']=True
                    enable()
        def close():
            state['alive']=False
            self.slot_dialog=None
            dialog.destroy()
        refresh.configure(command=load)
        archive.configure(command=submit_archive)
        table.bind('<<TreeviewSelect>>',enable)
        ttk.Button(buttons,text='Close',command=close).pack(side='right')
        dialog.protocol('WM_DELETE_WINDOW',close)
        dialog.grab_set()
        load()

    def _new_project_location(self) -> tuple[str, str] | None:
        name = str(self.project_name.get()).strip()
        if not name or len(name) > 100 or any(ord(char) < 32 for char in name):
            messagebox.showinfo('Event project', 'Enter a name of 1 to 100 characters for the event.', parent=self.root)
            return None
        parent = filedialog.askdirectory(parent=self.root, title='Choose where to create the new project folder',
                                        mustexist=True, initialdir=str(PROJECT_DIRECTORY if PROJECT_DIRECTORY.is_dir()
                                            else Path(__file__).resolve().parents[2]))
        if not parent:
            return None
        try:
            directory = project_suggestion(Path(parent))
        except OSError as exc:
            messagebox.showerror('Event project', f'Could not prepare the project folder: {exc}', parent=self.root)
            return None
        return str(directory),name

    def create_project(self) -> None:
        if not self._project_ready():
            return
        location=self._new_project_location()
        if location is None:
            return
        directory,name=location
        self._change('Creating the project and saving the reference…',
                     lambda: self.controller.create_project(directory, name))

    def import_project(self) -> None:
        if not self._project_ready():
            return
        location=self._new_project_location()
        if location is None:
            return
        path=filedialog.askopenfilename(parent=self.root, title='Choose the .p2s of the paused scene',
                                       filetypes=[('PCSX2 state','*.p2s')])
        if path:
            directory,name=location
            self._change('Checking the state and creating the project…',
                         lambda:self.controller.import_project(directory,name,str(Path(path))))

    def save_project_from_state(self) -> None:
        if not self._project_ready(existing=True):
            return
        path=filedialog.askopenfilename(parent=self.root, title='Choose the .p2s of the paused scene',
                                       filetypes=[('PCSX2 state','*.p2s')])
        if path:
            self._change('Checking and saving the scene from the file…',
                         lambda:self.controller.save_project_from_state(str(Path(path))))

    def _confirm_project(self, *, base: bool) -> None:
        if not self._project_ready():
            return
        current=getattr(self,'project',None) or {}
        options={}
        if current.get('path'):
            options={'initialdir':str(Path(current['path']).parent), 'initialfile':Path(current['path']).name}
        path=filedialog.askopenfilename(parent=self.root,
            title='Check loaded base' if base else 'Check loaded scene',
            filetypes=[('Event project','*.b3event.json')],**options)
        if path:
            self._invalidate_profile()
            self._change('Checking the manually loaded scene…',
                         lambda:self.controller.confirm_project(str(Path(path)),base=base))

    def confirm_project_scene(self) -> None:
        self._confirm_project(base=False)

    def confirm_project_base(self) -> None:
        self._confirm_project(base=True)

    def open_native_events(self) -> None:
        from editor.native_events_ui import NativeEventsWindow
        window = getattr(self, 'native_window', None)
        if window is None or not window.winfo_exists():
            self.native_window = NativeEventsWindow(
                self.root, lambda: getattr(self, 'native_identity', None)
                if self.connected and self.profile_valid and self.core_paused is True else None)
        else:
            window.lift()
            window.focus_set()

    def open_project(self) -> None:
        if not self._project_ready():
            return
        path = filedialog.askopenfilename(parent=self.root, title='Open event project',
                    filetypes=[('Event project', '*.b3event.json')])
        if path:
            self._invalidate_profile()
            self._change('Opening the project and restoring the saved scene…',
                         lambda: self.controller.open_project(str(Path(path))))

    def save_project(self) -> None:
        if self._project_ready(existing=True):
            self._change('Saving the scene to the project…', self.controller.save_project)

    def test_project(self) -> None:
        if self._project_ready(existing=True):
            self._invalidate_profile()
            self._change('Saving the scene and starting the test…', self.controller.test_project)

    def restart_project(self) -> None:
        if self._project_ready(existing=True):
            self._invalidate_profile()
            self._change('Restoring the saved scene to repeat the test…', self.controller.restart_project)

    def restore_project_base(self) -> None:
        if self._project_ready(existing=True):
            self._invalidate_profile()
            self._change("Restoring the project's original reference…", self.controller.restore_project_base)

    def load_preset(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, title='Open configuration',
                    filetypes=[('JSON configuration', '*.json')])
        if path:
            options = {'experimental': True} if self._experimental_enabled() else {}
            self._change('Applying the configuration to the current event…',
                         lambda: self.controller.load_preset(str(Path(path)), **options))

    def export_state(self) -> None:
        if (self.closed or self.busy or self.pending or not self.connected
                or not self.state_export or not getattr(self, 'profile_valid', True)
                or self.core_paused is not True):
            return
        try:
            EXPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
            suggested = export_suggestion()
        except OSError as exc:
            messagebox.showerror('Save state', f'Could not prepare the events folder: {exc}',
                                 parent=self.root)
            return
        path = filedialog.asksaveasfilename(parent=self.root, title='Save edited state',
                    defaultextension='.p2s', initialdir=str(suggested.parent), initialfile=suggested.name,
                    filetypes=[('PCSX2 state', '*.p2s')])
        if path:
            def done(result):
                message = str(result.get('message') or 'Edited state saved.')
                if result.get('path'):
                    message += '\nFile: ' + str(result['path'])
                self._set_status(message, warning=bool(result.get('warning')))
            self._submit('Saving the edited state…',
                         lambda: self.controller.export_state(str(Path(path))),
                         done)

    def close(self) -> None:
        if self.closed:
            return
        if self.busy:
            messagebox.showinfo('Action in progress',
                                'Wait for this action to finish before closing the editor.',
                                parent=self.root)
            return
        if self.pending:
            messagebox.showinfo('Creation in progress',
                'Finish the creation before closing. If the operation failed, reload a '
                'clean state in PCSX2 and click Connect again.', parent=self.root)
            return
        window = getattr(self, 'native_window', None)
        if window is not None and window.winfo_exists() and not window.close():
            return
        self._submit('Closing the editor…', self.controller.close, lambda _value: self._finish_close())

    def _finish_close(self) -> None:
        self.closed = True
        self.jobs.put(None)
        self.root.after_cancel(self.poll_id)
        if self.pending_poll_id is not None:
            self.root.after_cancel(self.pending_poll_id)
        self.root.destroy()


def main(controller: Controller) -> None:
    root = tk.Tk()
    EditorApp(root, controller)
    root.mainloop()


if __name__ == '__main__':
    raise SystemExit('Open the editor through the project launcher, which provides the emulator connection.')
