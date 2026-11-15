"""Portuguese Tkinter interface for a controller supplied by the launcher.

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
                        experimental: bool = False) -> dict[str, Any]: ...
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
    def close(self) -> None: ...


def number(text: str, *, positive: bool = False) -> float:
    """Accept either decimal separator while rejecting nonfinite input."""
    try:
        value = float(text.strip().replace(',', '.'))
    except ValueError as exc:
        raise ValueError('Informe um número válido.') from exc
    if not math.isfinite(value):
        raise ValueError('Informe um número finito.')
    if positive and value <= 0:
        raise ValueError('A distância precisa ser maior que zero.')
    return value


def quantity(text: str, experimental: bool = False) -> int:
    maximum = 253 if experimental else 8
    message = f'Use uma quantidade inteira entre 1 e {maximum}.'
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
        raise ValueError('A coordenada excede o intervalo numérico do jogo.')
    return value


def export_suggestion(directory: Path | None = None) -> Path:
    """Suggest a local name without replacing an existing file or link."""
    folder = Path(directory) if directory is not None else EXPORT_DIRECTORY
    stem = 'evento-editado-' + datetime.now().strftime('%Y%m%d-%H%M%S')
    candidate = folder / (stem + '.p2s')
    index = 1
    while candidate.exists() or candidate.is_symlink():
        candidate = folder / f'{stem}-{index:03d}.p2s'
        index += 1
    return candidate


def project_suggestion(parent: Path) -> Path:
    """Use an unused child directory; the backend creates it exclusively."""
    stem = 'evento-' + datetime.now().strftime('%Y%m%d-%H%M%S')
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
    label = str(model.get('label') or f'Modelo sem nome {index + 1}')
    category = str(model.get('type_label') or '').strip()
    if category and category not in label:
        label += f' · {category}'
    if model.get('verified') is False:
        label += ' (nome a confirmar)'
    return label


def catalog_rows(models: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Include restricted models for identification, without enabling creation."""
    return [(str(model.get('label') or model.get('id') or f'Modelo {index + 1}'),
             str(model.get('type_label') or 'Não identificada'),
             'Disponível' if model.get('eligible') is True else
             'Disponível com caminhão' if model.get('eligible_as_trailer') is True else
             'Criação não validada')
            for index, model in enumerate(models)]


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
        return 'Velocidade: não disponível nesta leitura.' if detailed else '—'
    control,travel = speed_value(info.get('control_value')),speed_value(info.get('travel_value'))
    nominal_target,nominal_travel = info.get('nominal_target_kmh'),info.get('nominal_travel_kmh')
    if type(nominal_target) in (int,float) and math.isfinite(nominal_target):
        target_text,travel_text = speed_value(nominal_target),speed_value(nominal_travel)
        if detailed:
            return (f'Alvo nominal: {target_text} km/h · Seguimento nominal: {travel_text} km/h\n'
                    'Escala nominal; o trânsito pode reduzir o avanço.')
        return f'{target_text} / {travel_text}'
    if detailed:
        units = str(info.get('units') or 'unidades internas')
        return f'Controle: {control} · Seguimento: {travel}\n{units}; valores internos não convertidos.'
    return f'{control} / {travel}'


def map_to_world(view: tuple[float, float, float], width: float, height: float,
                 px: float, py: float) -> tuple[float, float]:
    """Invert the displayed X/Z map without assuming a screen origin."""
    cx, cz, span = view
    if (not all(math.isfinite(value) for value in (cx, cz, span, width, height, px, py))
            or span <= 0 or width <= 40 or height <= 50):
        raise ValueError('A vista de cima ainda não está pronta para marcar uma posição.')
    scale = min(width - 40, height - 50) / span
    result = cx + (px - width / 2) / scale, cz + (height / 2 - py) / scale
    if not all(math.isfinite(value) for value in result):
        raise ValueError('A posição marcada não é finita.')
    return result


def capacity_summary(snapshot: dict[str, Any]) -> str:
    vehicles = snapshot.get('vehicles') or []
    counts = snapshot.get('capacity') or snapshot.get('counts') or {}
    active = counts.get('active_objects', len(vehicles))
    ready = counts.get('initialized_objects', sum(v.get('initialized') is True for v in vehicles))
    parts = [f'Objetos ativos: {active}', f'Física pronta: {ready}']
    for key, label in (('free_objects', 'Objetos livres'), ('free_nodes', 'Nós livres')):
        value = counts.get(key)
        if type(value) is int:
            parts.append(f'{label}: {value}')
    queued = counts.get('queued_operations')
    if type(queued) is int:
        parts.append(f'Na fila: {queued}')
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
        self.status = tk.StringVar(value='Conecte ao emulador com um evento carregado.')
        self.pending_text = tk.StringVar(value='')
        self.connection_text = tk.StringVar(value='Desconectado')
        self.core_text = tk.StringVar(value='')
        self.selection_text = tk.StringVar(value='Selecione um veículo na lista.')
        self.position_text = tk.StringVar(value='X: —     Y: —     Z: —')
        self.speed_text = tk.StringVar(value='Velocidade: não disponível nesta leitura.')
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
        self.project_name = tk.StringVar(value='Meu evento de Crash')
        self.project_text = tk.StringVar(value='Nenhum projeto aberto. Conecte e pause o PCSX2 para começar.')
        self.model_choice = tk.StringVar(value='Mesmo modelo do selecionado')
        self.secondary_choice = tk.StringVar(value='Selecione a carga')
        self.map_notice = tk.StringVar(value='Posições dos veículos; sem desenho da pista.')
        self.instructions_text = tk.StringVar(value='Pause com Esc no PCSX2 e atualize a lista antes de editar. As alterações valem para a sessão atual.')
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
        root.title('Burnout 3 — Editor do evento atual')
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
        ttk.Label(header, text='Editor do evento atual',
                  font=('Segoe UI', 19, 'bold')).grid(row=0, column=0, sticky='w')
        ttk.Label(header, text='Experimental · Burnout 3 USA / PCSX2',
                  foreground='#5f6875').grid(row=1, column=0, sticky='w', pady=(4, 0))
        self.connect_button = ttk.Button(header, text='Conectar / nova sessão', command=self.connect)
        self.connect_button.grid(row=0, column=1, rowspan=2, padx=(15, 8))
        self.refresh_button = ttk.Button(header, text='Atualizar lista', command=self.refresh)
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
        self.pause_button = ttk.Button(self.emulator_controls, text='Pausar PCSX2', command=self.pause_emulator)
        self.pause_button.pack(side='left')
        self.resume_button = ttk.Button(self.emulator_controls, text='Retomar', command=self.resume_emulator)
        self.resume_button.pack(side='left', padx=(6, 0))
        self.emulator_controls.grid_remove()
        self.finalize_button = ttk.Button(connection, text='Finalizar pendência',
                                          command=self.finalize_pending)
        self.finalize_button.grid(row=0, column=3, padx=(8, 0))
        self.cancel_queue_button = ttk.Button(connection, text='Cancelar fila', command=self.cancel_queue)
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
            text='Modo experimental: ampliar quantidade e distância',
            variable=self.experimental, command=self._experimental_changed)
        self.experimental_check.grid(row=1, column=0, sticky='w', pady=(6, 0))
        self.experimental_warning = ttk.Label(instructions,
            text='Alto risco de travamento/perda de física. Salve um estado antes de testar. '
                 'A fila usa grupos de até 8; retome e pause para concluir cada grupo.',
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
        lists.add(actors, text='Veículos presentes')
        self.table = ttk.Treeview(actors, columns=('vehicle', 'type', 'model','speed'),
                                  show='headings', selectmode='extended', height=15)
        for key, title, width in [('vehicle', 'Veículo', 140), ('type', 'Categoria', 105),
                                  ('model', 'Modelo', 150),('speed','Nominal km/h A/S',150)]:
            self.table.heading(key, text=title)
            self.table.column(key, width=width, minwidth=70, stretch=True)
        self.table.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(actors, orient='vertical', command=self.table.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.table.configure(yscrollcommand=scroll.set)
        self.table.bind('<<TreeviewSelect>>', self._selection_changed)
        ttk.Label(actors, text='Ctrl: escolher vários · Shift: selecionar um intervalo.',
                  foreground='#5f6875', wraplength=420).grid(row=1, column=0, sticky='w', pady=(6, 0))
        self.select_speed_button = ttk.Button(actors, text='Selecionar aptos para velocidade',
                                              command=self.select_speed_eligible)
        self.select_speed_button.grid(row=2, column=0, sticky='w', pady=(6, 0))
        view = ttk.Frame(lists, padding=(0, 8, 0, 0))
        view.columnconfigure(0, weight=1)
        view.rowconfigure(1, weight=1)
        lists.add(view, text='Vista de cima')
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
        self.mark_button = ttk.Button(map_footer, text='Marcar posição', command=self._mark_position)
        self.mark_button.grid(row=0,column=0,sticky='w')
        self.routes_check = ttk.Checkbutton(map_footer,text='Mostrar vias',variable=self.show_routes,
                                            command=self._routes_changed)
        self.routes_check.grid(row=0,column=1,sticky='w',padx=8)
        ttk.Label(map_footer, text='Roda: zoom · direito: mover', foreground='#5f6875',
                  wraplength=270).grid(row=1,column=0,columnspan=2,sticky='w',pady=(5,0))
        ttk.Button(map_footer, text='Enquadrar', command=self._map_reset).grid(row=0,column=2,sticky='e')
        ttk.Button(map_footer,text='Caminho',command=self._map_selected_path).grid(row=1,column=2,sticky='e',pady=(5,0))
        point_controls = ttk.LabelFrame(view, text='Adicionar no ponto X/Z', padding=8)
        point_controls.grid(row=3, column=0, sticky='ew', pady=(8, 0))
        point_controls.columnconfigure(1, weight=1)
        point_controls.columnconfigure(3, weight=1)
        ttk.Label(point_controls, text='X').grid(row=0, column=0, padx=(0, 5))
        self.point_x_entry = ttk.Entry(point_controls, textvariable=self.point_x, width=12)
        self.point_x_entry.grid(row=0, column=1, sticky='ew')
        ttk.Label(point_controls, text='Z').grid(row=0, column=2, padx=(10, 5))
        self.point_z_entry = ttk.Entry(point_controls, textvariable=self.point_z, width=12)
        self.point_z_entry.grid(row=0, column=3, sticky='ew')
        self.add_at_button = ttk.Button(point_controls, text='Adicionar no ponto', command=self.add_at)
        self.add_at_button.grid(row=1, column=0, columnspan=4, sticky='ew', pady=(7, 0))
        ttk.Label(point_controls,
            text='Usa caminhos com referência móvel verificada e o modelo escolhido ao lado. O ponto pode ser ajustado à via.',
            foreground='#5f6875', wraplength=410).grid(row=2, column=0, columnspan=4, sticky='w', pady=(5, 0))
        catalog = ttk.Frame(lists, padding=(0, 8, 0, 0))
        catalog.columnconfigure(0, weight=1)
        catalog.rowconfigure(0, weight=1)
        lists.add(catalog, text='Catálogo carregado')
        self.catalog_table = ttk.Treeview(catalog,
            columns=('model', 'type', 'availability'), show='headings', selectmode='none', height=15)
        for key, title, width in [('model', 'Modelo', 150), ('type', 'Categoria', 105),
                                  ('availability', 'Criação', 185)]:
            self.catalog_table.heading(key, text=title)
            self.catalog_table.column(key, width=width, minwidth=70, stretch=True)
        self.catalog_table.grid(row=0, column=0, sticky='nsew')
        catalog_scroll = ttk.Scrollbar(catalog, orient='vertical', command=self.catalog_table.yview)
        catalog_scroll.grid(row=0, column=1, sticky='ns')
        self.catalog_table.configure(yscrollcommand=catalog_scroll.set)
        project_container = ttk.Frame(lists)
        project_container.columnconfigure(0, weight=1)
        project_container.rowconfigure(0, weight=1)
        lists.add(project_container, text='Projeto')
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
        ttk.Label(project_tab, text='Nome para novo projeto').grid(row=0, column=0, columnspan=2, sticky='w')
        self.project_name_entry = ttk.Entry(project_tab, textvariable=self.project_name)
        self.project_name_entry.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(5, 10))
        self.new_project_button = ttk.Button(project_tab, text='Criar projeto…', command=self.create_project)
        self.new_project_button.grid(row=2, column=0, sticky='ew', padx=(0, 5))
        self.open_project_button = ttk.Button(project_tab, text='Abrir projeto…', command=self.open_project)
        self.open_project_button.grid(row=2, column=1, sticky='ew', padx=(5, 0))
        self.save_project_button = ttk.Button(project_tab, text='Salvar cena no projeto', command=self.save_project)
        self.save_project_button.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(8, 0))
        self.test_project_button = ttk.Button(project_tab, text='Testar cena', command=self.test_project)
        self.test_project_button.grid(row=4, column=0, sticky='ew', padx=(0, 5), pady=(8, 0))
        self.restart_project_button = ttk.Button(project_tab, text='Voltar ao início', command=self.restart_project)
        self.restart_project_button.grid(row=4, column=1, sticky='ew', padx=(5, 0), pady=(8, 0))
        self.restore_base_button = ttk.Button(project_tab, text='Restaurar base original', command=self.restore_project_base)
        self.restore_base_button.grid(row=5, column=0, columnspan=2, sticky='ew', pady=(8, 0))
        self.project_help_label = ttk.Label(project_tab, text='Testar salva a cena e retoma o jogo. Voltar ao início restaura essa cena salva; '
                  'pause o PCSX2 antes. Restaurar base recupera a referência original do projeto.',
                  wraplength=400, foreground='#5f6875')
        self.project_help_label.grid(row=6, column=0, columnspan=2, sticky='w', pady=(12, 0))
        self.project_status_label = ttk.Label(project_tab, textvariable=self.project_text, wraplength=400,
                  foreground='#305d86')
        self.project_status_label.grid(row=7, column=0, columnspan=2, sticky='w', pady=(12, 0))
        manual_project = ttk.LabelFrame(project_tab, text='Alternativa sem slot livre', padding=10)
        manual_project.grid(row=8, column=0, columnspan=2, sticky='ew', pady=(16, 0))
        manual_project.columnconfigure(0, weight=1)
        manual_project.columnconfigure(1, weight=1)
        self.import_project_button = ttk.Button(manual_project, text='Criar de .p2s…', command=self.import_project)
        self.import_project_button.grid(row=0, column=0, sticky='ew', padx=(0, 4))
        self.save_project_state_button = ttk.Button(manual_project, text='Salvar cena de .p2s…', command=self.save_project_from_state)
        self.save_project_state_button.grid(row=0, column=1, sticky='ew', padx=(4, 0))
        self.confirm_scene_button = ttk.Button(manual_project, text='Conferir cena carregada…', command=self.confirm_project_scene)
        self.confirm_scene_button.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(8, 0))
        self.confirm_base_button = ttk.Button(manual_project, text='Conferir base carregada…', command=self.confirm_project_base)
        self.confirm_base_button.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(8, 0))
        self.project_manual_label = ttk.Label(manual_project,
            text='Sem slot livre: salve/carregue em Sistema → Salvar/Carregar estado → Arquivo… e confira aqui. '
                 'Os arquivos precisam corresponder à cena pausada.', wraplength=360, foreground='#5f6875')
        self.project_manual_label.grid(row=3, column=0, columnspan=2, sticky='w', pady=(10, 0))
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

        movement = ttk.LabelFrame(details, text='Mover o veículo selecionado', padding=12)
        movement.grid(row=2, column=0, sticky='ew')
        movement.columnconfigure(0, weight=1)
        ttk.Label(movement, text='Posição na largura da via').grid(row=0, column=0, sticky='w')
        self.lateral_scale = ttk.Scale(movement, from_=0, to=100, orient='horizontal',
                                       variable=self.lateral, command=self._lateral_changed)
        self.lateral_scale.grid(row=1, column=0, sticky='ew', pady=9)
        ttk.Label(movement, textvariable=self.lateral_text).grid(row=1, column=1, padx=(8, 0))
        ttk.Label(movement, text='A posição longitudinal no caminho é mantida.',
                  wraplength=280, foreground='#5f6875').grid(row=2, column=0, columnspan=2, sticky='w')
        self.move_button = ttk.Button(movement, text='Aplicar posição', command=self.move)
        self.move_button.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(10, 0))
        self.speed_controls = ttk.Frame(movement)
        self.speed_controls.grid(row=4,column=0,columnspan=2,sticky='ew',pady=(12,0))
        self.speed_controls.columnconfigure(1,weight=1)
        ttk.Label(self.speed_controls,text='Alvo nominal (km/h)').grid(row=0,column=0,sticky='w',padx=(0,8))
        self.speed_entry = ttk.Entry(self.speed_controls,textvariable=self.speed_target_kmh,width=10)
        self.speed_entry.grid(row=0,column=1,sticky='ew')
        self.speed_button = ttk.Button(self.speed_controls,text='Aplicar velocidade',command=self.set_speed)
        self.speed_button.grid(row=1,column=0,columnspan=2,sticky='ew',pady=(7,0))
        self.speed_selection_label = ttk.Label(self.speed_controls, textvariable=self.speed_selection_text,
                                                wraplength=300, foreground='#5f6875')
        self.speed_selection_label.grid(row=2,column=0,columnspan=2,sticky='w',pady=(6,0))
        self.speed_controls.grid_remove()

        addition = ttk.LabelFrame(details, text='Adicionar veículos atrás', padding=12)
        addition.grid(row=3, column=0, sticky='ew', pady=(14, 0))
        addition.columnconfigure(0, weight=1)
        ttk.Label(addition, text='Modelo dos novos veículos').grid(row=0, column=0, sticky='w')
        self.model_box = ttk.Combobox(addition, textvariable=self.model_choice,
                                      values=('Mesmo modelo do selecionado',), state='readonly', width=29)
        self.model_box.grid(row=1, column=0, sticky='ew', pady=(5, 9))
        self.model_box.bind('<<ComboboxSelected>>', self._model_changed)
        distance = ttk.Frame(addition)
        distance.grid(row=2, column=0, sticky='ew')
        distance.columnconfigure(1, weight=1)
        ttk.Label(distance, text='Distância atrás').grid(row=0, column=0, sticky='w', padx=(0, 8))
        self.gap_entry = ttk.Entry(distance, textvariable=self.gap, width=10)
        self.gap_entry.grid(row=0, column=1, sticky='ew')
        self.count_label = ttk.Label(distance, text='Quantidade')
        self.count_label.grid(row=0, column=2, padx=(10, 8))
        self.count_box = ttk.Spinbox(distance, from_=1, to=8, textvariable=self.count, width=4)
        self.count_box.grid(row=0, column=3)
        self.gap_hint = ttk.Label(addition, text='De 8 a 50 unidades do jogo.', foreground='#5f6875')
        self.gap_hint.grid(row=3, column=0, sticky='w', pady=(5, 0))
        self.secondary_label = ttk.Label(addition, text='Carga do caminhão')
        self.secondary_label.grid(row=4, column=0, sticky='w', pady=(9, 0))
        self.secondary_box = ttk.Combobox(addition, textvariable=self.secondary_choice,
            values=('Selecione a carga',), state='disabled', width=29)
        self.secondary_box.grid(row=5, column=0, sticky='ew', pady=(5, 0))
        self.secondary_label.grid_remove()
        self.secondary_box.grid_remove()
        self.add_button = ttk.Button(addition, text='Adicionar veículos atrás', command=self.add_behind)
        self.add_button.grid(row=6, column=0, sticky='ew', pady=(11, 0))

        footer = ttk.Frame(container)
        footer.grid(row=4, column=0, sticky='ew', pady=(16, 0))
        footer.columnconfigure(3, weight=1)
        self.save_button = ttk.Button(footer, text='Salvar configuração…', command=self.save_preset)
        self.save_button.grid(row=0, column=0)
        self.load_button = ttk.Button(footer, text='Abrir configuração…', command=self.load_preset)
        self.load_button.grid(row=0, column=1, padx=8)
        self.export_button = ttk.Button(footer, text='Salvar estado…', command=self.export_state)
        self.export_button.grid(row=0, column=2)
        self.export_button.grid_remove()
        ttk.Label(footer, text='A receita JSON e o estado são arquivos separados.',
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
        for name in ('selection_label','position_label','speed_label','speed_selection_label'):
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
            self.selection_text.set('Selecione um veículo na lista.')
            self.position_text.set('X: —     Y: —     Z: —')
        else:
            self.selection_text.set(str(vehicle.get('label') or f"Veículo {vehicle['id']}"))
            if len(selections) > 1:
                self.selection_text.set(f'{len(selections)} selecionados · foco: ' + self.selection_text.get())
            xyz = vehicle.get('position') or []
            self.position_text.set('     '.join(f'{axis}: {coordinate(xyz[i] if i < len(xyz) else None)}'
                                               for i, axis in enumerate('XYZ')))
            path = vehicle.get('path')
            self.position_text.set(self.position_text.get()+
                (f'\nCaminho: P{path}' if type(path) is int else '\nSem caminho de tráfego reconhecido.'))
            if vehicle.get('edit_reason'):
                self.position_text.set(self.position_text.get() + '\n' + str(vehicle['edit_reason']))
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
            self.mark_button.configure(text='Clique no mapa…' if self.marking_position else 'Marcar posição')
        self._set_status('Clique na vista de cima para marcar o ponto de criação.' if self.marking_position
                         else 'Marcação cancelada.')

    def _update_secondary_choices(self) -> None:
        if not hasattr(self, 'secondary_box'):
            return
        preferred = self.secondary_choices.get(self.secondary_choice.get())
        model = self._chosen_model()
        truck = model.get('kind') == 'truck'
        allowed = set(model.get('trailer_model_ids') or []) if truck else set()
        self.secondary_choices = {'Selecione a carga': None}
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
                                         if preferred is not None and model_id == preferred), 'Selecione a carga'))
        self.secondary_box.configure(values=tuple(self.secondary_choices))
        self.count_label.configure(text='Conjuntos' if truck else 'Quantidade')
        self.add_button.configure(text='Adicionar conjuntos atrás' if truck else 'Adicionar veículos atrás')
        reference_model = self.models.get(str(selected.get('model_id')), {})
        compound = (truck or selected.get('kind') == 'truck' or reference_model.get('kind') == 'truck'
                    or model.get('type') == 5 or reference_model.get('type') == 5)
        if hasattr(self, 'gap_hint'):
            hint = ('Experimental: distância positiva, sujeita ao caminho e à capacidade.'
                    if self._experimental_enabled() else
                    'Ônibus/caminhão: 30 a 50 unidades do jogo.' if compound
                    else 'De 8 a 50 unidades do jogo.')
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
            self._set_status('O veículo selecionado não tem geometria de caminho disponível nesta leitura.',warning=True)
            return
        if hasattr(self,'show_routes'):
            self.show_routes.set(True)
        self.map_view = fit_view(points)
        self.map_pan_state = None
        self._draw_traffic()
        self._set_status(f"Caminho P{selected['path']} enquadrado. As setas mostram sua progressão.")

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
                self.mark_button.configure(text='Marcar posição')
            self._point_changed()
            self._set_status(f'Ponto marcado: X {coordinate(x)} · Z {coordinate(z)}. Confira o modelo e adicione.')
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
            canvas.create_text(width / 2, height / 2, text='Conecte com o jogo pausado e atualize a lista.',
                               width=max(100, width - 40), fill='#5f6875')
            return
        if self.map_view is None:
            self.map_view = fit_view([*points.values(),*path_points,
                                     *([player] if player else []),*([target] if target else [])])
        cx, cz, span = self.map_view
        scale = min(max(1, width - 40), max(1, height - 50)) / span
        def project(point):
            return width / 2 + (point[0] - cx) * scale, height / 2 - (point[1] - cz) * scale
        canvas.create_text(10, 10, anchor='nw', text='X →   Z ↑   ·   unidades do jogo', fill='#5f6875')
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
            canvas.create_text(10,28,anchor='nw',text='Vias de tráfego · setas: progressão do caminho',fill='#5f6875')
            if any(path.get('source') == 'descriptor_candidate' for path in paths):
                canvas.create_text(10,44,anchor='nw',width=max(100,width-20),
                    text='P?: via candidata, sem veículo associado; uso atual não confirmado',fill='#7c8994')
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
                    text=str(vehicle.get('label') or 'Selecionado'), fill='#273444')
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
                canvas.create_text(px + 10, py - 9, anchor='sw', text='Criar aqui', fill='#a33922')
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
                    name = str(self.project.get('name') or 'Evento sem nome')
                    revision = self.project.get('scene_revision', 0)
                    self.project_text.set(f'{name} · Cena salva {revision}\n' + str(self.project.get('path') or ''))
                    if hasattr(self, 'project_name'):
                        self.project_name.set(name)
                else:
                    self.project_text.set('Nenhum projeto aberto. Crie um projeto a partir da cena pausada ou abra um existente.')
        paused = response.get('core_paused')
        if isinstance(paused, bool):
            self.core_paused = paused
            self.core_text.set('Jogo pausado' if paused else 'Jogo em execução')
            if hasattr(self, 'map_notice'):
                notice = (('Geometria de vias de tráfego; alturas podem se sobrepor na vista X/Z.'
                    if getattr(self,'routes',{}).get('paths') else 'Posições dos veículos; sem desenho da pista.') if paused else
                    ('Posições da última atualização; clique em Pausar PCSX2 e atualize.'
                     if getattr(self, 'emulator_control', False) else
                     'Posições da última atualização; pause com Esc e atualize.'))
                warning = getattr(self,'routes',{}).get('warning')
                self.map_notice.set(notice+(' '+warning if isinstance(warning,str) and warning else ''))
            return
        state = str(response.get('core_status') or response.get('status') or '').lower()
        if state == 'paused':
            self.core_paused = True
            self.core_text.set('Jogo pausado')
        elif state == 'running':
            self.core_paused = False
            self.core_text.set('Jogo em execução')
        elif state in ('shutdown', 'stopped', 'disconnected'):
            self.core_paused = False
            self.core_text.set('Nenhum jogo carregado')

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
            self.speed_button.configure(text=(f'Aplicar aos {len(selections)} selecionados'
                                              if len(selections) > 1 else 'Aplicar velocidade'))
            if hasattr(self, 'speed_selection_text'):
                note = f'{len(selections)} selecionados · {eligible} aptos · {blocked} bloqueados.'
                if blocked:
                    note += (' Selecione apenas veículos aptos. No caminhão, selecione a cabine; '
                             'a carga acompanha o conjunto.')
                elif len(selections) > 1:
                    note += (' O mesmo alvo será aplicado a todos. Posição e criação usam o veículo em foco.')
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
                'Use Pausar PCSX2 e atualize a lista antes de editar. As alterações valem para a sessão atual.'
                if supported else
                'Pause com Esc no PCSX2 e atualize a lista antes de editar. As alterações valem para a sessão atual.')
        if hasattr(self, 'pending_banner'):
            if self.pending:
                steps = ('1. Clique em Retomar por um instante. 2. Clique em Pausar PCSX2 '
                         'e aguarde a confirmação.' if getattr(self, 'emulator_control', False) else
                         '1. Retome com Esc por um instante. 2. Pause com Esc '
                         '(Sistema → Pausar) e aguarde a confirmação.')
                self.pending_text.set(
                    'CRIAÇÃO PENDENTE — espere a finalização antes de dirigir.\n'
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
        self.status.set(f'Atenção: {message}' if warning else message)
        if hasattr(self, 'status_label'):
            self.status_label.configure(foreground='#8a5200' if warning else '#273444')

    def _invalidate_profile(self) -> None:
        self.profile_valid = False
        self.routes = {}
        if hasattr(self.table, 'selection') and hasattr(self.table, 'selection_remove'):
            self.table.selection_remove(*self.table.selection())
        if hasattr(self, 'selection_text'):
            self.selection_text.set('Atualize a lista antes de editar os veículos.')
            self.position_text.set('X: —     Y: —     Z: —')
        if hasattr(self,'speed_text'):
            self.speed_text.set('Velocidade: atualize a leitura para consultar.')

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
                self._set_status(f'Erro: {error}')
                if self.pending:
                    self._schedule_pending_poll(2000)
                else:
                    messagebox.showerror('Ação não concluída', error, parent=self.root)
            else:
                try:
                    callback(value)
                except Exception as exc:
                    self._set_status(f'Não foi possível exibir a resposta: {exc}')
                    if self.pending:
                        self._schedule_pending_poll(2000)
            if self.closed:
                return
            if not self.pending:
                self.progress.stop()
            self._update_controls()
        self.poll_id = self.root.after(60, self._poll)

    def _snapshot(self, snapshot: dict[str, Any], selected_id: int | None = None) -> None:
        current = self.selected()
        selected_ids = {vehicle['id'] for vehicle in self.selected_vehicles()}
        chosen_model = self.model_choices.get(self.model_choice.get())
        if selected_id is None and current:
            selected_id = current['id']
        if selected_id is not None:
            selected_ids.add(selected_id)
        self.models = {str(model['id']): model for model in snapshot.get('models', [])}
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
        self.model_choices = {'Mesmo modelo do selecionado': None}
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
                                   'Mesmo modelo do selecionado'))
        self.table.delete(*self.table.get_children())
        self.vehicles.clear()
        selected_iids = []
        focused_iid = None
        for index, vehicle in enumerate(snapshot.get('vehicles', [])):
            iid = f'vehicle-{index}'
            self.vehicles[iid] = vehicle
            self.table.insert('', 'end', iid=iid,
                              values=(f"Veículo {vehicle['id']}",
                                      vehicle.get('type_label') or 'Não identificada',
                                      str(vehicle.get('model_id') or 'Modelo sem nome'),speed_summary(vehicle)))
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
        self._set_status(str(snapshot.get('status') or f'{len(self.vehicles)} veículos listados.'))

    def connect(self) -> None:
        self.connected = False
        self.connection_text.set('Conectando…')
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
                message = f'Conectado ao PCSX2, mas a lista não pôde ser validada: {exc}'
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
                                     or 'Confira o resultado antes de continuar.'), warning=True)
            if self.pending:
                self._schedule_pending_poll()
        self._submit('Conectando ao emulador…', work, done)

    def refresh(self) -> None:
        self._submit('Atualizando os veículos…', self.controller.refresh, self._snapshot)

    def pause_emulator(self) -> None:
        if self.connected and self.emulator_control:
            self._change('Pausando o PCSX2…', self.controller.pause)

    def resume_emulator(self) -> None:
        if self.connected and self.emulator_control:
            self._change('Retomando o PCSX2…', self.controller.resume)

    def finalize_pending(self) -> None:
        if (self.closed or self.busy or not self.connected or self.core_paused is not True):
            return
        self._change('Finalizando pendência…', self.controller.finalize_pending)

    def cancel_queue(self) -> None:
        if self.closed or self.busy or not self.connected:
            return
        self._change('Cancelando a fila restante…', self.controller.cancel_queue)

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
            message = str(result.get('message') or 'Alteração aplicada.')
            if refresh_error:
                self._invalidate_profile()
                message += f' A lista não pôde ser atualizada: {refresh_error}. Use Atualizar lista.'
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
                message += f' Use Atualizar lista: {refresh_error}'
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
            messagebox.showinfo('Velocidade', 'A seleção contém veículos sem ajuste de velocidade. '
                'Use Selecionar aptos para velocidade; no caminhão, selecione a cabine.', parent=self.root)
            return
        try:
            nominal = number(self.speed_target_kmh.get())
            control = nominal/NOMINAL_KMH_PER_CONTROL
            if control < 0 or control > 3.4028234663852886e38:
                raise ValueError('Use um alvo nominal não negativo dentro do intervalo do jogo.')
            if not self._experimental_enabled() and control > 240:
                if math.isclose(control,240,rel_tol=1e-12):
                    control = 240.
                else:
                    raise ValueError('No modo normal, use de 0 a 386,24256 km/h nominais.')
        except (TypeError,ValueError) as exc:
            messagebox.showinfo('Velocidade',str(exc),parent=self.root)
            return
        vehicle_ids = [int(vehicle['id']) for vehicle in vehicles]
        options = {'experimental':True} if self._experimental_enabled() else {}
        self._change('Aplicando alvo nominal de velocidade…',
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
                raise ValueError('Escolha uma posição entre 0% e 100%.')
        except ValueError as exc:
            messagebox.showinfo('Posição', str(exc), parent=self.root)
            return
        vehicle_id = int(vehicle['id'])
        options = {'experimental': True} if self._experimental_enabled() else {}
        self._change('Aplicando a posição…',
                     lambda: self.controller.move(vehicle_id, lateral_percent, **options))

    def add_behind(self) -> None:
        vehicle = self.selected()
        if not vehicle:
            return
        try:
            gap = number(self.gap.get(), positive=True)
            experimental = self._experimental_enabled()
            count = quantity(self.count.get(), experimental=experimental)
            chosen = self._chosen_model()
            reference = getattr(self, 'models', {}).get(str(vehicle.get('model_id')), {})
            minimum = 30 if (chosen.get('kind') == 'truck' or reference.get('kind') == 'truck'
                             or chosen.get('type') == 5 or reference.get('type') == 5) else 8
            if not experimental and not minimum <= gap <= 50:
                raise ValueError(f'Use uma distância entre {minimum} e 50 unidades do jogo.')
            secondary_id = None
            if chosen.get('kind') == 'truck':
                secondary_id = self.secondary_choices.get(self.secondary_choice.get())
                if secondary_id is None:
                    raise ValueError('Escolha uma carga compatível para o caminhão.')
        except ValueError as exc:
            messagebox.showinfo('Adicionar veículos', str(exc), parent=self.root)
            return
        vehicle_id = int(vehicle['id'])
        model_id = self.model_choices.get(self.model_choice.get())
        options = {'secondary_model_id': secondary_id}
        if experimental:
            options['experimental'] = True
        self._change('Adicionando os veículos atrás…',
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
                    raise ValueError('Escolha uma carga compatível para o caminhão.')
        except (AttributeError, ValueError) as exc:
            messagebox.showinfo('Adicionar no ponto', str(exc), parent=self.root)
            return
        vehicle_id = int(vehicle['id'])
        model_id = self.model_choices.get(self.model_choice.get())
        experimental = self._experimental_enabled()
        self._change('Preparando o veículo no ponto marcado…',
                     lambda: self.controller.add_at(vehicle_id, model_id, x, z,
                         secondary_model_id=secondary_id, experimental=experimental))

    def save_preset(self) -> None:
        path = filedialog.asksaveasfilename(parent=self.root, title='Salvar configuração',
                    defaultextension='.json', filetypes=[('Configuração JSON', '*.json')])
        if path:
            self._submit('Salvando a configuração…',
                         lambda: self.controller.save_preset(str(Path(path))),
                         lambda result: self._set_status(str(result.get('message') or 'Configuração salva.')))

    def _project_ready(self, *, existing: bool = False) -> bool:
        return bool(not self.closed and not self.busy and not self.pending and self.connected
                    and getattr(self, 'profile_valid', False) and self.core_paused is True
                    and getattr(self, 'event_projects', False)
                    and (not existing or getattr(self, 'project', None)))

    def _new_project_location(self) -> tuple[str, str] | None:
        name = str(self.project_name.get()).strip()
        if not name or len(name) > 100 or any(ord(char) < 32 for char in name):
            messagebox.showinfo('Projeto do evento', 'Informe um nome de 1 a 100 caracteres para o evento.', parent=self.root)
            return None
        parent = filedialog.askdirectory(parent=self.root, title='Escolha onde criar a nova pasta do projeto',
                                        mustexist=True, initialdir=str(PROJECT_DIRECTORY if PROJECT_DIRECTORY.is_dir()
                                            else Path(__file__).resolve().parents[2]))
        if not parent:
            return None
        try:
            directory = project_suggestion(Path(parent))
        except OSError as exc:
            messagebox.showerror('Projeto do evento', f'Não foi possível preparar a pasta do projeto: {exc}', parent=self.root)
            return None
        return str(directory),name

    def create_project(self) -> None:
        if not self._project_ready():
            return
        location=self._new_project_location()
        if location is None:
            return
        directory,name=location
        self._change('Criando o projeto e salvando a referência…',
                     lambda: self.controller.create_project(directory, name))

    def import_project(self) -> None:
        if not self._project_ready():
            return
        location=self._new_project_location()
        if location is None:
            return
        path=filedialog.askopenfilename(parent=self.root, title='Escolha o .p2s da cena pausada',
                                       filetypes=[('Estado PCSX2','*.p2s')])
        if path:
            directory,name=location
            self._change('Conferindo o estado e criando o projeto…',
                         lambda:self.controller.import_project(directory,name,str(Path(path))))

    def save_project_from_state(self) -> None:
        if not self._project_ready(existing=True):
            return
        path=filedialog.askopenfilename(parent=self.root, title='Escolha o .p2s da cena pausada',
                                       filetypes=[('Estado PCSX2','*.p2s')])
        if path:
            self._change('Conferindo e salvando a cena do arquivo…',
                         lambda:self.controller.save_project_from_state(str(Path(path))))

    def _confirm_project(self, *, base: bool) -> None:
        if not self._project_ready():
            return
        current=getattr(self,'project',None) or {}
        options={}
        if current.get('path'):
            options={'initialdir':str(Path(current['path']).parent), 'initialfile':Path(current['path']).name}
        path=filedialog.askopenfilename(parent=self.root,
            title='Conferir base carregada' if base else 'Conferir cena carregada',
            filetypes=[('Projeto de evento','*.b3event.json')],**options)
        if path:
            self._invalidate_profile()
            self._change('Conferindo a cena carregada manualmente…',
                         lambda:self.controller.confirm_project(str(Path(path)),base=base))

    def confirm_project_scene(self) -> None:
        self._confirm_project(base=False)

    def confirm_project_base(self) -> None:
        self._confirm_project(base=True)

    def open_project(self) -> None:
        if not self._project_ready():
            return
        path = filedialog.askopenfilename(parent=self.root, title='Abrir projeto de evento',
                    filetypes=[('Projeto de evento', '*.b3event.json')])
        if path:
            self._invalidate_profile()
            self._change('Abrindo o projeto e restaurando a cena salva…',
                         lambda: self.controller.open_project(str(Path(path))))

    def save_project(self) -> None:
        if self._project_ready(existing=True):
            self._change('Salvando a cena no projeto…', self.controller.save_project)

    def test_project(self) -> None:
        if self._project_ready(existing=True):
            self._invalidate_profile()
            self._change('Salvando a cena e iniciando o teste…', self.controller.test_project)

    def restart_project(self) -> None:
        if self._project_ready(existing=True):
            self._invalidate_profile()
            self._change('Restaurando a cena salva para repetir o teste…', self.controller.restart_project)

    def restore_project_base(self) -> None:
        if self._project_ready(existing=True):
            self._invalidate_profile()
            self._change('Restaurando a referência original do projeto…', self.controller.restore_project_base)

    def load_preset(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, title='Abrir configuração',
                    filetypes=[('Configuração JSON', '*.json')])
        if path:
            options = {'experimental': True} if self._experimental_enabled() else {}
            self._change('Aplicando a configuração ao evento atual…',
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
            messagebox.showerror('Salvar estado', f'Não foi possível preparar a pasta de eventos: {exc}',
                                 parent=self.root)
            return
        path = filedialog.asksaveasfilename(parent=self.root, title='Salvar estado editado',
                    defaultextension='.p2s', initialdir=str(suggested.parent), initialfile=suggested.name,
                    filetypes=[('Estado PCSX2', '*.p2s')])
        if path:
            def done(result):
                message = str(result.get('message') or 'Estado editado salvo.')
                if result.get('path'):
                    message += '\nArquivo: ' + str(result['path'])
                self._set_status(message, warning=bool(result.get('warning')))
            self._submit('Salvando o estado editado…',
                         lambda: self.controller.export_state(str(Path(path))),
                         done)

    def close(self) -> None:
        if self.closed:
            return
        if self.busy:
            messagebox.showinfo('Ação em andamento',
                                'Aguarde esta ação terminar antes de fechar o editor.',
                                parent=self.root)
            return
        if self.pending:
            messagebox.showinfo('Criação em andamento',
                'Finalize a criação antes de fechar. Se a operação falhou, recarregue um '
                'estado limpo no PCSX2 e clique em Conectar novamente.', parent=self.root)
            return
        self._submit('Fechando o editor…', self.controller.close, lambda _value: self._finish_close())

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
    raise SystemExit('Abra o editor pelo inicializador do projeto, que fornece a conexão ao emulador.')
