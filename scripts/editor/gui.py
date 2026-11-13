"""Portuguese Tkinter interface for a controller supplied by the launcher.

The controller owns emulator/profile validation and all mutations. Its methods
are called only on one background worker; this module touches Tk only on the
main thread. See Controller for the small interface expected by EditorApp.
"""
from __future__ import annotations

import math
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Protocol


class Controller(Protocol):
    def connect(self) -> dict[str, Any]: ...
    def refresh(self) -> dict[str, Any]: ...
    def move(self, vehicle_id: int, lateral_percent: float) -> dict[str, Any]: ...
    def add_behind(self, vehicle_id: int, model_id: str | None,
                   gap: float) -> dict[str, Any]: ...
    def save_preset(self, path: str) -> dict[str, Any]: ...
    def load_preset(self, path: str) -> dict[str, Any]: ...
    def poll(self) -> dict[str, Any]: ...
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
             'Disponível' if model.get('eligible') is True else 'Criação não validada')
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


class EditorApp:
    def __init__(self, root: tk.Tk, controller: Controller):
        self.root = root
        self.controller = controller
        self.connected = False
        self.busy = False
        self.pending = False
        self.pending_sized = False
        self.pending_poll_id: str | None = None
        self.core_paused: bool | None = None
        self.closed = False
        self.vehicles: dict[str, dict[str, Any]] = {}
        self.models: dict[str, dict[str, Any]] = {}
        self.model_choices: dict[str, str | None] = {}
        self.map_view: tuple[float, float, float] | None = None
        self.map_hits: list[tuple[float, float, str]] = []
        self.player: dict[str, Any] | None = None
        self.jobs: queue.Queue[Any] = queue.Queue()
        self.results: queue.Queue[Any] = queue.Queue()
        self.status = tk.StringVar(value='Conecte ao emulador com um evento carregado.')
        self.pending_text = tk.StringVar(value='')
        self.connection_text = tk.StringVar(value='Desconectado')
        self.core_text = tk.StringVar(value='')
        self.selection_text = tk.StringVar(value='Selecione um veículo na lista.')
        self.position_text = tk.StringVar(value='X: —     Y: —     Z: —')
        self.lateral = tk.DoubleVar(value=50)
        self.lateral_text = tk.StringVar(value='50,0%')
        self.gap = tk.StringVar(value='10')
        self.model_choice = tk.StringVar(value='Mesmo modelo do selecionado')
        self.map_notice = tk.StringVar(value='Posições dos veículos; sem desenho da pista.')
        self._build()
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
        instructions = ttk.Frame(container)
        instructions.grid(row=2, column=0, sticky='ew', pady=(0, 12))
        instructions.columnconfigure(0, weight=1)
        ttk.Label(instructions,
                  text='Pause com Esc no PCSX2 e atualize a lista antes de editar. As alterações valem para a sessão atual.',
                  foreground='#5f6875').grid(row=0, column=0, sticky='w')
        self.pending_banner = tk.Label(instructions, textvariable=self.pending_text,
            background='#fff0b3', foreground='#574100', font=('Segoe UI', 10, 'bold'),
            anchor='w', justify='left', padx=12, pady=10, wraplength=780)
        self.pending_banner.grid(row=1, column=0, sticky='ew', pady=(10, 0))
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
        self.table = ttk.Treeview(actors, columns=('vehicle', 'type', 'model'),
                                  show='headings', selectmode='browse', height=15)
        for key, title, width in [('vehicle', 'Veículo', 140), ('type', 'Categoria', 105),
                                  ('model', 'Modelo', 190)]:
            self.table.heading(key, text=title)
            self.table.column(key, width=width, minwidth=70, stretch=True)
        self.table.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(actors, orient='vertical', command=self.table.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.table.configure(yscrollcommand=scroll.set)
        self.table.bind('<<TreeviewSelect>>', self._selection_changed)
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
        map_footer = ttk.Frame(view)
        map_footer.grid(row=2, column=0, sticky='ew', pady=(6, 0))
        ttk.Label(map_footer, text='Clique em um ponto para selecionar. Roda: zoom.',
                  foreground='#5f6875').pack(side='left')
        ttk.Button(map_footer, text='Enquadrar', command=self._map_reset).pack(side='right')
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
        pane.add(list_frame, weight=3)

        details = ttk.Frame(pane, padding=(18, 0, 0, 0))
        details.columnconfigure(0, weight=1)
        pane.add(details, weight=2)
        ttk.Label(details, textvariable=self.selection_text,
                  font=('Segoe UI', 11, 'bold'), wraplength=320).grid(row=0, column=0, sticky='w')
        ttk.Label(details, textvariable=self.position_text,
                  wraplength=320).grid(row=1, column=0, sticky='w', pady=(7, 14))

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

        addition = ttk.LabelFrame(details, text='Adicionar um veículo atrás', padding=12)
        addition.grid(row=3, column=0, sticky='ew', pady=(14, 0))
        addition.columnconfigure(0, weight=1)
        ttk.Label(addition, text='Modelo do novo veículo').grid(row=0, column=0, sticky='w')
        self.model_box = ttk.Combobox(addition, textvariable=self.model_choice,
                                      values=('Mesmo modelo do selecionado',), state='readonly', width=29)
        self.model_box.grid(row=1, column=0, sticky='ew', pady=(5, 9))
        distance = ttk.Frame(addition)
        distance.grid(row=2, column=0, sticky='ew')
        distance.columnconfigure(1, weight=1)
        ttk.Label(distance, text='Distância atrás').grid(row=0, column=0, sticky='w', padx=(0, 8))
        self.gap_entry = ttk.Entry(distance, textvariable=self.gap, width=10)
        self.gap_entry.grid(row=0, column=1, sticky='ew')
        ttk.Label(addition, text='De 8 a 50 unidades do jogo.', foreground='#5f6875').grid(
            row=3, column=0, sticky='w', pady=(5, 0))
        self.add_button = ttk.Button(addition, text='Adicionar atrás', command=self.add_behind)
        self.add_button.grid(row=4, column=0, sticky='ew', pady=(11, 0))

        footer = ttk.Frame(container)
        footer.grid(row=4, column=0, sticky='ew', pady=(16, 0))
        footer.columnconfigure(2, weight=1)
        self.save_button = ttk.Button(footer, text='Salvar configuração…', command=self.save_preset)
        self.save_button.grid(row=0, column=0)
        self.load_button = ttk.Button(footer, text='Abrir configuração…', command=self.load_preset)
        self.load_button.grid(row=0, column=1, padx=8)
        ttk.Label(footer, text='A configuração não substitui os arquivos do evento.',
                  foreground='#5f6875', wraplength=350).grid(row=0, column=2, sticky='e')
        self.progress = ttk.Progressbar(container, mode='indeterminate')
        self.progress.grid(row=5, column=0, sticky='ew', pady=(13, 6))
        self.status_label = ttk.Label(container, textvariable=self.status,
                                      foreground='#273444', wraplength=950)
        self.status_label.grid(row=6, column=0, sticky='ew')

    def selected(self) -> dict[str, Any] | None:
        selected = self.table.selection()
        return self.vehicles.get(selected[0]) if selected else None

    def _selection_changed(self, _event: Any = None) -> None:
        vehicle = self.selected()
        if vehicle is None:
            self.selection_text.set('Selecione um veículo na lista.')
            self.position_text.set('X: —     Y: —     Z: —')
        else:
            self.selection_text.set(str(vehicle.get('label') or f"Veículo {vehicle['id']}"))
            xyz = vehicle.get('position') or []
            self.position_text.set('     '.join(f'{axis}: {coordinate(xyz[i] if i < len(xyz) else None)}'
                                               for i, axis in enumerate('XYZ')))
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
        self._update_controls()
        self._draw_traffic()

    def _map_reset(self) -> None:
        self.map_view = None
        self._draw_traffic()

    def _map_zoom(self, event: Any) -> None:
        if self.map_view is None or not event.delta:
            return
        cx, cz, span = self.map_view
        factor = 0.8 if event.delta > 0 else 1.25
        new_span = max(2, min(100000, span * factor))
        width, height = self.map_canvas.winfo_width(), self.map_canvas.winfo_height()
        side = min(max(1, width - 40), max(1, height - 50))
        dx, dz = event.x - width / 2, height / 2 - event.y
        self.map_view = (cx + dx / side * (span - new_span),
                         cz + dz / side * (span - new_span), new_span)
        self._draw_traffic()

    def _map_select(self, event: Any) -> None:
        if self.busy or self.pending or not self.map_hits:
            return
        px, py, iid = min(self.map_hits, key=lambda point:
                          (point[0] - event.x) ** 2 + (point[1] - event.y) ** 2)
        if math.hypot(px - event.x, py - event.y) <= 12:
            self.table.selection_set(iid)
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
        if not points and player is None:
            canvas.create_text(width / 2, height / 2, text='Conecte com o jogo pausado e atualize a lista.',
                               width=max(100, width - 40), fill='#5f6875')
            return
        if self.map_view is None:
            self.map_view = fit_view([*points.values(), *([player] if player else [])])
        cx, cz, span = self.map_view
        scale = min(max(1, width - 40), max(1, height - 50)) / span
        def project(point):
            return width / 2 + (point[0] - cx) * scale, height / 2 - (point[1] - cz) * scale
        canvas.create_text(10, 10, anchor='nw', text='X →   Z ↑   ·   unidades do jogo', fill='#5f6875')
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
        marker = min(80, width / 4)
        canvas.create_line(15, height - 20, 15 + marker, height - 20, fill='#5f6875', width=2)
        canvas.create_text(15, height - 25, anchor='sw', text=f'{marker / scale:.1f} un.', fill='#5f6875')

    def _lateral_changed(self, _value: Any = None) -> None:
        self.lateral_text.set(f'{self.lateral.get():.1f}%'.replace('.', ','))

    def _set_core_state(self, response: dict[str, Any]) -> None:
        paused = response.get('core_paused')
        if isinstance(paused, bool):
            self.core_paused = paused
            self.core_text.set('Jogo pausado' if paused else 'Jogo em execução')
            if hasattr(self, 'map_notice'):
                self.map_notice.set('Posições dos veículos; sem desenho da pista.' if paused else
                    'Posições da última atualização; pause com Esc e atualize.')
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
        selected = self.selected()
        editable = bool(idle and self.connected and selected and selected.get('active', True)
                        and selected.get('editable', selected.get('eligible', False))
                        and self.core_paused is True)
        # A failed finalization can require a clean-state reload and reconnect.
        # Reconnection is serialized on the same worker and never retries a mutation.
        self.connect_button.configure(state='normal' if not self.busy and not self.closed else 'disabled')
        for widget in (self.refresh_button, self.save_button):
            widget.configure(state='normal' if idle and self.connected else 'disabled')
        self.load_button.configure(state='normal' if idle and self.connected
                                   and self.core_paused is True else 'disabled')
        for widget in (self.move_button, self.add_button, self.lateral_scale, self.gap_entry):
            widget.configure(state='normal' if editable else 'disabled')
        self.model_box.configure(state='readonly' if editable else 'disabled')
        self.table.configure(selectmode='browse' if idle else 'none')
        if hasattr(self, 'pending_banner'):
            if self.pending:
                self.pending_text.set(
                    'CRIAÇÃO PENDENTE — espere a finalização antes de dirigir.\n'
                    '1. Retome com Esc por um instante. 2. Pause com Esc '
                    '(Sistema → Pausar) e aguarde a confirmação.\n' + self.status.get())
                self.pending_banner.grid()
                if not getattr(self, 'pending_sized', False) and hasattr(self, 'root'):
                    self.pending_sized = True
                    self.root.after_idle(self._fit_pending_window)
            else:
                self.pending_banner.grid_remove()
                self.pending_sized = False

    def _fit_pending_window(self) -> None:
        """Keep the pending instructions visible using Tk's measured request."""
        if self.closed or not self.pending:
            return
        height = min(max(820, self.root.winfo_reqheight()),
                     max(1, self.root.winfo_screenheight() - 80))
        if self.root.winfo_height() < height:
            self.root.geometry(f'{self.root.winfo_width()}x{height}')

    def _set_status(self, message: str, *, warning: bool = False) -> None:
        self.status.set(f'Atenção: {message}' if warning else message)
        if hasattr(self, 'status_label'):
            self.status_label.configure(foreground='#8a5200' if warning else '#273444')

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
        chosen_model = self.model_choices.get(self.model_choice.get())
        if selected_id is None and current:
            selected_id = current['id']
        self.models = {str(model['id']): model for model in snapshot.get('models', [])}
        self.player = snapshot.get('player')
        self.map_view = None
        self._set_core_state(snapshot)
        self.catalog_table.delete(*self.catalog_table.get_children())
        for row in catalog_rows(snapshot.get('models', [])):
            self.catalog_table.insert('', 'end', values=row)
        self.model_choices = {'Mesmo modelo do selecionado': None}
        for index, model in enumerate(snapshot.get('models', [])):
            if model.get('eligible') is not True:
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
        for index, vehicle in enumerate(snapshot.get('vehicles', [])):
            iid = f'vehicle-{index}'
            self.vehicles[iid] = vehicle
            self.table.insert('', 'end', iid=iid,
                              values=(f"Veículo {vehicle['id']}",
                                      vehicle.get('type_label') or 'Não identificada',
                                      str(vehicle.get('model_id') or 'Modelo sem nome')))
            if vehicle['id'] == selected_id:
                self.table.selection_set(iid)
                self.table.see(iid)
        self._selection_changed()
        self._set_status(str(snapshot.get('status') or f'{len(self.vehicles)} veículos listados.'))

    def connect(self) -> None:
        self.connected = False
        self.connection_text.set('Conectando…')
        def work():
            connection = self.controller.connect()
            return connection, self.controller.refresh()
        def done(value):
            connection, snapshot = value
            self.connected = True
            self.pending = bool(snapshot.get('pending', connection.get('pending', False)))
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
            self.pending = bool(result.get('pending'))
            self._set_core_state(result)
            if snapshot is not None:
                self._snapshot(snapshot, result.get('new_vehicle_id'))
            message = str(result.get('message') or 'Alteração aplicada.')
            if refresh_error:
                message += f' A lista não pôde ser atualizada: {refresh_error}. Use Atualizar lista.'
            self._set_status(message, warning=bool(result.get('warning') or refresh_error))
            if self.pending:
                self._schedule_pending_poll()
        self._submit(label, work, done)

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
            self.pending = bool(result.get('pending'))
            self._set_core_state(result)
            if snapshot is not None:
                self._snapshot(snapshot, result.get('new_vehicle_id'))
            message = str(result.get('message') or '')
            if refresh_error:
                message += f' Use Atualizar lista: {refresh_error}'
            if message:
                self._set_status(message, warning=bool(result.get('warning') or refresh_error))
            if self.pending:
                self._schedule_pending_poll()
        self._submit('', work, done, quiet=True)

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
        self._change('Aplicando a posição…',
                     lambda: self.controller.move(vehicle_id, lateral_percent))

    def add_behind(self) -> None:
        vehicle = self.selected()
        if not vehicle:
            return
        try:
            gap = number(self.gap.get(), positive=True)
        except ValueError as exc:
            messagebox.showinfo('Distância', str(exc), parent=self.root)
            return
        vehicle_id = int(vehicle['id'])
        model_id = self.model_choices.get(self.model_choice.get())
        self._change('Adicionando um veículo atrás…',
                     lambda: self.controller.add_behind(vehicle_id, model_id, gap))

    def save_preset(self) -> None:
        path = filedialog.asksaveasfilename(parent=self.root, title='Salvar configuração',
                    defaultextension='.json', filetypes=[('Configuração JSON', '*.json')])
        if path:
            self._submit('Salvando a configuração…',
                         lambda: self.controller.save_preset(str(Path(path))),
                         lambda result: self._set_status(str(result.get('message') or 'Configuração salva.')))

    def load_preset(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, title='Abrir configuração',
                    filetypes=[('Configuração JSON', '*.json')])
        if path:
            self._change('Aplicando a configuração ao evento atual…',
                         lambda: self.controller.load_preset(str(Path(path))))

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
