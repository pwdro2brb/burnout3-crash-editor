"""Headless interface-contract tests; no Tk window, emulator or socket opens."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import queue
import types
import unittest
from unittest.mock import Mock, patch

import gui
import run_editor


class Var:
    def __init__(self, value=None): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


class Widget:
    def __init__(self): self.options = {}
    def configure(self, **options): self.options.update(options)


def app_shell(vehicle=None, *, paused=True):
    app = gui.EditorApp.__new__(gui.EditorApp)
    app.busy, app.pending, app.closed = False, False, False
    app.connected, app.core_paused = True, paused
    app.selected = lambda: vehicle
    app.core_text, app.status = Var(), Var()
    for name in ('connect_button', 'refresh_button', 'save_button', 'load_button',
                 'move_button', 'add_button', 'lateral_scale', 'gap_entry',
                 'model_box', 'table'):
        setattr(app, name, Widget())
    return app


class InterfaceContractTests(unittest.TestCase):
    def test_mutations_require_confirmed_core_pause(self):
        for state in (None, False, True):
            with self.subTest(state=state):
                app = app_shell({'id': 9, 'editable': True}, paused=state)
                app._update_controls()
                expected = 'normal' if state is True else 'disabled'
                self.assertEqual(app.move_button.options['state'], expected)
                self.assertEqual(app.add_button.options['state'], expected)
                self.assertEqual(app.load_button.options['state'], expected)

    def test_backend_editability_controls_actions(self):
        for vehicle in ({'id': 9, 'editable': False, 'eligible': True},
                        {'id': 9}, {'id': 9, 'editable': True, 'active': False}, None):
            with self.subTest(vehicle=vehicle):
                app = app_shell(vehicle)
                app._update_controls()
                self.assertEqual(app.move_button.options['state'], 'disabled')
                self.assertEqual(app.add_button.options['state'], 'disabled')

    def test_pending_creation_prevents_duplicate_submission(self):
        app = app_shell({'id': 9, 'editable': True})
        app.pending = True
        app._update_controls()
        for name in ('refresh_button', 'move_button', 'add_button',
                     'save_button', 'load_button'):
            self.assertEqual(getattr(app, name).options['state'], 'disabled', name)
        self.assertEqual(app.connect_button.options['state'], 'normal')
        self.assertEqual(app.table.options['selectmode'], 'none')

    def test_pending_banner_keeps_finalization_visible_until_complete(self):
        app = app_shell()
        app.pending_banner, app.pending_text = Mock(), Var()
        app.pending = True
        app.status.set('Carro criado. Pause o emulador novamente para finalizar.')
        app._update_controls()
        app.pending_banner.grid.assert_called_once()
        self.assertIn('antes de dirigir', app.pending_text.get())
        self.assertIn('1. Retome', app.pending_text.get())
        self.assertIn('2. Pause', app.pending_text.get())
        self.assertIn('Sistema → Pausar', app.pending_text.get())
        self.assertIn(app.status.get(), app.pending_text.get())
        app.pending = False
        app.status.set('Veículo adicionado e edição finalizada.')
        app._update_controls()
        app.pending_banner.grid_remove.assert_called_once()

    def test_catalog_exposes_restricted_models_without_enabling_creation(self):
        models = [
            {'id': 'car', 'label': 'COMPCAR14', 'type_label': 'Car', 'eligible': True},
            {'id': 'van', 'label': 'VAN01', 'type_label': 'Van', 'eligible': True},
            {'id': 'bus', 'label': 'BUS01', 'type_label': 'Bus', 'eligible': False},
        ]
        self.assertEqual(gui.catalog_rows(models), [
            ('COMPCAR14', 'Car', 'Disponível'),
            ('VAN01', 'Van', 'Disponível'),
            ('BUS01', 'Bus', 'Criação não validada'),
        ])
        app = app_shell()
        app.table, app.catalog_table = Mock(), Mock()
        app.table.get_children.return_value = ()
        app.catalog_table.get_children.return_value = ()
        app.model_choices, app.vehicles = {}, {}
        app.model_choice = Var()
        app._selection_changed = Mock()
        app._snapshot({'models': models, 'vehicles': [
            {'id': 9, 'label': 'Veículo 9 — Carro — COMPCAR14',
             'model_id': 'car', 'type_label': 'Carro'}]})
        self.assertEqual(app.catalog_table.insert.call_count, 3)
        self.assertEqual(set(app.model_choices.values()), {None, 'car', 'van'})
        self.assertEqual(app.table.insert.call_args.kwargs['values'],
                         ('Veículo 9', 'Carro', 'car'))

    def test_reconnect_clears_finished_pending_state_without_mutation(self):
        app = app_shell()
        app.pending = True
        app.connection_text = Var()
        app._snapshot = Mock()
        app._schedule_pending_poll = Mock()
        snapshot = {'pending': False, 'core_paused': True}
        app.controller = types.SimpleNamespace(
            connect=Mock(return_value={'game': 'Burnout 3 USA', 'pending': False}),
            refresh=Mock(return_value=snapshot))
        jobs = []
        app._submit = lambda label, work, done: jobs.append((work, done))
        app.connect()
        work, done = jobs.pop()
        done(work())
        self.assertTrue(app.connected)
        self.assertFalse(app.pending)
        app.controller.connect.assert_called_once()
        app.controller.refresh.assert_called_once()
        app._snapshot.assert_called_once_with(snapshot)
        app._schedule_pending_poll.assert_not_called()

    def test_connect_while_running_keeps_editing_disabled(self):
        app = app_shell({'id': 9, 'editable': True})
        app.connection_text = Var()
        app._snapshot = lambda response: app._set_core_state(response)
        app.controller = types.SimpleNamespace(
            connect=Mock(return_value={'core_paused': False}),
            refresh=Mock(return_value={'core_paused': False, 'pending': False}))
        jobs = []
        app._submit = lambda label, work, done: jobs.append((work, done))
        app.connect()
        work, done = jobs.pop()
        done(work())
        app._update_controls()
        self.assertTrue(app.connected)
        self.assertFalse(app.core_paused)
        self.assertEqual(app.move_button.options['state'], 'disabled')
        self.assertEqual(app.add_button.options['state'], 'disabled')

    def test_close_waits_for_pending_creation(self):
        app = app_shell()
        app.pending = True
        app.root = Mock()
        app._submit = Mock()
        with patch.object(gui.messagebox, 'showinfo') as info:
            app.close()
        app._submit.assert_not_called()
        info.assert_called_once()
        self.assertIn('Conectar novamente', info.call_args.args[1])

    def test_top_down_bounds_include_all_valid_positions(self):
        self.assertEqual(gui.xz([10, 99, -4]), (10, -4))
        for position in (None, [], [1], [float('nan'), 0, 4], [1, 0, 'texto']):
            self.assertIsNone(gui.xz(position))
        cx, cz, span = gui.fit_view([(-10, 40), (30, -20), (0, 10)])
        self.assertEqual((cx, cz), (10, 10))
        for x, z in [(-10, 40), (30, -20), (0, 10)]:
            self.assertLess(abs(x - cx), span / 2)
            self.assertLess(abs(z - cz), span / 2)

    def test_top_down_selection_uses_existing_actor_and_respects_pending(self):
        app = app_shell()
        app.table, app._selection_changed = Mock(), Mock()
        app.map_hits = [(20, 30, 'vehicle-7'), (80, 40, 'vehicle-9')]
        app._map_select(types.SimpleNamespace(x=22, y=34))
        app.table.selection_set.assert_called_once_with('vehicle-7')
        app._selection_changed.assert_called_once()
        app.table.reset_mock()
        app.pending = True
        app._map_select(types.SimpleNamespace(x=20, y=30))
        app.table.selection_set.assert_not_called()

    def test_uninitialized_actor_does_not_distort_map_or_become_selectable(self):
        app = app_shell()
        app.map_canvas, app.table = Mock(), Mock()
        app.map_canvas.winfo_width.return_value = 500
        app.map_canvas.winfo_height.return_value = 400
        app.table.selection.return_value = ()
        app.map_view, app.player = None, None
        app.vehicles = {
            'ready': {'initialized': True, 'position': [1000, 10, 2000]},
            'distant': {'initialized': False, 'position': [0, 0, 0]},
        }
        app._draw_traffic()
        self.assertEqual(app.map_view[:2], (1000, 2000))
        self.assertEqual([point[2] for point in app.map_hits], ['ready'])
        app.map_canvas.create_oval.assert_called_once()

    def test_close_releases_controller_on_worker_before_destroying_window(self):
        app = app_shell()
        app.controller = types.SimpleNamespace(close=Mock())
        app._finish_close = Mock()
        jobs = []
        app._submit = lambda label, work, done: jobs.append((work, done))
        app.close()
        app.controller.close.assert_not_called()
        work, done = jobs.pop()
        done(work())
        app.controller.close.assert_called_once()
        app._finish_close.assert_called_once()

    def test_finished_close_does_not_touch_destroyed_widgets(self):
        app = app_shell()
        app.results = queue.Queue()
        app.root, app.progress = Mock(), Mock()
        app._update_controls = Mock()
        app.results.put((lambda _value: setattr(app, 'closed', True), None, None))
        app._poll()
        app.progress.stop.assert_not_called()
        app._update_controls.assert_not_called()
        app.root.after.assert_not_called()

    def test_snapshot_pause_boolean_is_understood(self):
        app = app_shell(paused=None)
        app._set_core_state({'core_paused': True, 'status': 'Lista atualizada.'})
        self.assertTrue(app.core_paused)
        self.assertEqual(app.core_text.get(), 'Jogo pausado')
        app._set_core_state({'core_paused': False})
        self.assertFalse(app.core_paused)
        app._set_core_state({'core_status': 'paused'})
        self.assertTrue(app.core_paused)

    def test_pending_action_does_not_refresh_before_creation(self):
        app = app_shell()
        app.controller = types.SimpleNamespace(refresh=Mock())
        app._schedule_pending_poll = Mock()
        jobs = []
        app._submit = lambda label, work, done: jobs.append((work, done))
        action = Mock(return_value={'pending': True, 'message': 'Retome o jogo.'})
        app._change('Adicionar', action)
        work, done = jobs.pop()
        value = work()
        done(value)
        action.assert_called_once()
        app.controller.refresh.assert_not_called()
        self.assertTrue(app.pending)
        self.assertEqual(app.status.get(), 'Retome o jogo.')
        app._schedule_pending_poll.assert_called_once()

    def test_refresh_failure_does_not_repeat_successful_mutation(self):
        app = app_shell()
        app.controller = types.SimpleNamespace(refresh=Mock(side_effect=RuntimeError('jogo retomado')))
        app._snapshot = Mock()
        jobs = []
        app._submit = lambda label, work, done: jobs.append((work, done))
        action = Mock(return_value={'message': 'Posição aplicada.'})
        app._change('Mover', action)
        work, done = jobs.pop()
        done(work())
        action.assert_called_once()
        app.controller.refresh.assert_called_once()
        app._snapshot.assert_not_called()
        self.assertIn('Posição aplicada.', app.status.get())
        self.assertIn('Atualizar lista', app.status.get())

    def test_invalid_distance_is_not_a_backend_request(self):
        for value in ('NaN', 'Inf', '-Inf', '0', '-2', 'texto'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError): gui.number(value, positive=True)
        self.assertEqual(gui.number(' 10,5 ', positive=True), 10.5)


class LauncherTests(unittest.TestCase):
    def test_help_does_not_import_controller_or_open_window(self):
        with redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as stop:
                run_editor.main(['--help'])
        self.assertEqual(stop.exception.code, 0)
        self.assertIn('--port', output.getvalue())

    def test_port_validation(self):
        for value in ('0', '65536', 'texto'):
            with self.assertRaises(Exception): run_editor.port_number(value)
        self.assertEqual(run_editor.port_number('28011'), 28011)

    def test_launcher_only_constructs_controller_for_gui(self):
        instance = object()
        factory, show = Mock(return_value=instance), Mock()
        modules = {
            'editor.controller': types.SimpleNamespace(EditorController=factory),
            'editor.gui': types.SimpleNamespace(main=show),
        }
        with patch.dict('sys.modules', modules):
            self.assertEqual(run_editor.main(['--port', '28112', '--journal-dir', 'local-journal']), 0)
        factory.assert_called_once_with(port=28112, journal_dir=Path('local-journal'))
        show.assert_called_once_with(instance)


if __name__ == '__main__': unittest.main()
