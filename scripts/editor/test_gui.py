"""Headless interface-contract tests; no Tk window, emulator or socket opens."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import queue
import sys
from tempfile import TemporaryDirectory
import types
import unittest
from unittest.mock import Mock, patch

import gui
import run_editor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editor.profile import ProfileError
from editor.pine import PineTransportError


class Var:
    def __init__(self, value=None): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


class Widget:
    def __init__(self): self.options = {}
    def configure(self, **options): self.options.update(options)


class SelectionTable(Widget):
    def __init__(self, rows=(), selected=(), focus=''):
        super().__init__()
        self.rows = dict(rows)
        self.chosen, self.focused = tuple(selected), focus
        self.seen = []
    def selection(self): return self.chosen
    def selection_set(self, items):
        self.chosen = (items,) if isinstance(items, str) else tuple(items)
    def focus(self, item=None):
        if item is not None: self.focused = item
        return self.focused
    def see(self, item): self.seen.append(item)
    def get_children(self): return tuple(self.rows)
    def delete(self, *items):
        for item in items: self.rows.pop(item, None)
        self.chosen = tuple(item for item in self.chosen if item in self.rows)
    def insert(self, _parent, _where, *, iid, values): self.rows[iid] = values


def app_shell(vehicle=None, *, paused=True):
    app = gui.EditorApp.__new__(gui.EditorApp)
    app.busy, app.pending, app.closed = False, False, False
    app.connected, app.core_paused = True, paused
    app.profile_valid = True
    app.selected = lambda: vehicle
    app.selected_vehicles = lambda: [app.selected()] if app.selected() is not None else []
    app.core_text, app.status = Var(), Var()
    for name in ('connect_button', 'refresh_button', 'save_button', 'load_button',
                 'move_button', 'add_button', 'lateral_scale', 'gap_entry',
                 'model_box', 'table'):
        setattr(app, name, Widget())
    return app


def multi_app(vehicles, selected, focus=None):
    app = app_shell()
    app.vehicles = {f'row-{vehicle["id"]}': vehicle for vehicle in vehicles}
    iids = [f'row-{vehicle_id}' for vehicle_id in selected]
    app.table = SelectionTable(app.vehicles.items(), iids, f'row-{focus}' if focus is not None else '')
    app.selected = types.MethodType(gui.EditorApp.selected, app)
    app.selected_vehicles = types.MethodType(gui.EditorApp.selected_vehicles, app)
    return app


def truck_app(*, reference_is_truck=True):
    vehicle = {'id': 7 if reference_is_truck else 9,
               'model_id': 'truck' if reference_is_truck else 'car',
               'editable': not reference_is_truck, 'can_reference': True,
               'native_pair_valid': reference_is_truck,
               'secondary_model_id': 'cargo' if reference_is_truck else None}
    app = app_shell(vehicle)
    app.models = {
        'truck': {'id': 'truck', 'label': 'Cabine', 'kind': 'truck',
                  'eligible': True, 'trailer_model_ids': ['cargo']},
        'cargo': {'id': 'cargo', 'label': 'Carga nativa', 'kind': 'trailer',
                  'eligible': False, 'eligible_as_trailer': True},
        'other': {'id': 'other', 'label': 'Trailer of another truck', 'kind': 'trailer',
                  'eligible': False, 'eligible_as_trailer': True},
    }
    app.model_choices = {'Same model as selected': None, 'Cabine': 'truck'}
    app.model_choice = Var('Same model as selected' if reference_is_truck else 'Cabine')
    app.secondary_choices, app.secondary_choice = {}, Var('Select the trailer')
    app.secondary_box, app.secondary_label = Mock(), Mock()
    app.count_label, app.count_box = Widget(), Widget()
    app.trailer_visible, app.root = False, Mock()
    app.gap, app.count = Var('10'), Var('1')
    return app


class InterfaceContractTests(unittest.TestCase):
    def test_batch_quantity_is_an_integer_between_one_and_eight(self):
        for value in ('0', '9', '-1', '1.0', 'NaN', ''):
            with self.subTest(value=value):
                with self.assertRaises(ValueError): gui.quantity(value)
        self.assertEqual(gui.quantity(' 1 '), 1)
        self.assertEqual(gui.quantity('8'), 8)

    def test_truck_reference_enables_creation_without_enabling_movement(self):
        app = truck_app()
        app._update_secondary_choices()
        app._update_controls()
        self.assertEqual(app.move_button.options['state'], 'disabled')
        self.assertEqual(app.lateral_scale.options['state'], 'disabled')
        self.assertEqual(app.add_button.options['state'], 'normal')
        self.assertEqual(app.count_box.options['state'], 'normal')
        self.assertEqual(app.count_label.options['text'], 'Conjuntos')
        self.assertEqual(app.gap.get(), '30')
        self.assertEqual(set(app.secondary_choices.values()), {None, 'cargo'})
        self.assertEqual(app.secondary_choice.get(), 'Carga nativa')
        app.secondary_box.configure.assert_called_with(state='readonly')

    def test_truck_selected_on_another_reference_requires_explicit_cargo(self):
        app = truck_app(reference_is_truck=False)
        app._update_secondary_choices()
        app._change = Mock()
        with patch.object(gui.messagebox, 'showinfo') as info:
            app.add_behind()
        app._change.assert_not_called()
        self.assertIn('compatible trailer', info.call_args.args[1])

    def test_batch_is_submitted_once_with_explicit_native_pair(self):
        app = truck_app(reference_is_truck=False)
        app._update_secondary_choices()
        app.secondary_choice.set('Carga nativa')
        app.count.set('3')
        app.controller = types.SimpleNamespace(add_many_behind=Mock(return_value={'pending': True}))
        actions = []
        app._change = lambda label, action: actions.append(action)
        app.add_behind()
        self.assertEqual(len(actions), 1)
        actions[0]()
        app.controller.add_many_behind.assert_called_once_with(9, 'truck', 30.0, 3,
                                                              secondary_model_id='cargo')

    def test_pause_buttons_exist_only_for_confirmed_capability_and_work_while_pending(self):
        app = app_shell()
        app.emulator_controls = Mock()
        app.pause_button, app.resume_button = Widget(), Widget()
        app.instructions_text = Var()
        app.emulator_control = False
        app._update_controls()
        app.emulator_controls.grid_remove.assert_called_once()
        self.assertEqual(app.pause_button.options['state'], 'disabled')
        app.emulator_control, app.pending = True, True
        app._update_controls()
        app.emulator_controls.grid.assert_called_once()
        self.assertEqual(app.pause_button.options['state'], 'normal')
        self.assertEqual(app.resume_button.options['state'], 'normal')
        self.assertNotIn('Esc', app.instructions_text.get())

    def test_pause_actions_use_the_controller_worker_path(self):
        app = app_shell()
        app.emulator_control = True
        app.controller = types.SimpleNamespace(pause=Mock(), resume=Mock())
        actions = []
        app._change = lambda label, action: actions.append(action)
        app.pause_emulator()
        app.resume_emulator()
        app.controller.pause.assert_not_called()
        app.controller.resume.assert_not_called()
        self.assertEqual(len(actions), 2)
        actions[0]()
        actions[1]()
        app.controller.pause.assert_called_once()
        app.controller.resume.assert_called_once()

    def test_pause_action_keeps_creation_pending_when_refresh_reports_it(self):
        app = app_shell()
        app.pending = True
        app.controller = types.SimpleNamespace(refresh=Mock(return_value={
            'pending': True, 'core_paused': False}))
        app._snapshot, app._schedule_pending_poll = Mock(), Mock()
        jobs = []
        app._submit = lambda label, work, done: jobs.append((work, done))
        app._change('Retomar', lambda: {'core_paused': False, 'message': 'PCSX2 retomado.'})
        work, done = jobs.pop()
        done(work())
        self.assertTrue(app.pending)
        app._schedule_pending_poll.assert_called_once()

    def test_state_export_requires_capability_idle_and_confirmed_pause(self):
        for capability, paused, pending, busy in [(False, True, False, False),
                                                 (True, False, False, False),
                                                 (True, True, True, False),
                                                 (True, True, False, True),
                                                 (True, True, False, False)]:
            with self.subTest(capability=capability, paused=paused, pending=pending, busy=busy):
                app = app_shell(paused=paused)
                app.state_export, app.pending, app.busy = capability, pending, busy
                app.export_button = Mock()
                app._update_controls()
                expected = 'normal' if capability and paused and not pending and not busy else 'disabled'
                app.export_button.configure.assert_called_with(state=expected)
                if not capability: app.export_button.grid_remove.assert_called_once()

    def test_export_dialog_submits_one_worker_action_and_preserves_result_message(self):
        app = app_shell()
        app.root, app.state_export = Mock(), True
        app.controller = types.SimpleNamespace(export_state=Mock(return_value={'message': 'Estado editado salvo.'}))
        jobs = []
        app._submit = lambda label, work, done: jobs.append((work, done))
        with TemporaryDirectory(prefix='b3-gui-export-') as folder, \
                patch.object(gui, 'EXPORT_DIRECTORY', Path(folder)), \
                patch.object(gui.filedialog, 'asksaveasfilename', return_value='edited.p2s') as dialog:
            app.export_state()
        dialog.assert_called_once()
        self.assertEqual(dialog.call_args.kwargs['defaultextension'], '.p2s')
        app.controller.export_state.assert_not_called()
        work, done = jobs.pop()
        done(work())
        app.controller.export_state.assert_called_once_with(str(Path('edited.p2s')))
        self.assertEqual(app.status.get(), 'Estado editado salvo.')

    def test_pending_export_does_not_open_a_file_dialog(self):
        app = app_shell()
        app.state_export, app.pending = True, True
        with patch.object(gui.filedialog, 'asksaveasfilename') as dialog:
            app.export_state()
        dialog.assert_not_called()

    def test_non_reference_actor_cannot_be_used_for_creation(self):
        app = app_shell({'id': 9, 'editable': True, 'can_reference': False})
        app._update_controls()
        self.assertEqual(app.move_button.options['state'], 'normal')
        self.assertEqual(app.add_button.options['state'], 'disabled')

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
        app.status.set('Car created. Pause the emulator again to finish.')
        app._update_controls()
        app.pending_banner.grid.assert_called_once()
        self.assertIn('before driving', app.pending_text.get())
        self.assertIn('1. Resume', app.pending_text.get())
        self.assertIn('2. Pause', app.pending_text.get())
        self.assertIn('System → Pause', app.pending_text.get())
        self.assertIn(app.status.get(), app.pending_text.get())
        app.pending = False
        app.status.set('Vehicle added and edit finished.')
        app._update_controls()
        app.pending_banner.grid_remove.assert_called_once()

    def test_catalog_exposes_restricted_models_without_enabling_creation(self):
        models = [
            {'id': 'car', 'label': 'COMPCAR14', 'type_label': 'Car', 'eligible': True},
            {'id': 'van', 'label': 'VAN01', 'type_label': 'Van', 'eligible': True},
            {'id': 'bus', 'label': 'BUS01', 'type_label': 'Bus', 'eligible': False},
        ]
        self.assertEqual(gui.catalog_rows(models), [
            ('COMPCAR14', 'Car', 'Available'),
            ('VAN01', 'Van', 'Available'),
            ('BUS01', 'Bus', 'Creation not validated'),
        ])
        app = app_shell()
        app.table, app.catalog_table = Mock(), Mock()
        app.table.get_children.return_value = ()
        app.catalog_table.get_children.return_value = ()
        app.model_choices, app.vehicles = {}, {}
        app.model_choice = Var()
        app._selection_changed = Mock()
        app._snapshot({'models': models, 'vehicles': [
            {'id': 9, 'label': 'Vehicle 9 — Car — COMPCAR14',
             'model_id': 'car', 'type_label': 'Car'}]})
        self.assertEqual(app.catalog_table.insert.call_count, 3)
        self.assertEqual(set(app.model_choices.values()), {None, 'car', 'van'})
        self.assertEqual(app.table.insert.call_args.kwargs['values'],
                         ('Vehicle 9', 'Car', 'car','—'))

    def test_reconnect_clears_finished_pending_state_without_mutation(self):
        app = app_shell()
        app.pending = True
        app.connection_text = Var()
        app.status_label = Widget()
        app._snapshot = Mock()
        app._schedule_pending_poll = Mock()
        snapshot = {'pending': False, 'core_paused': True,
                    'warning': True, 'message': 'The temporary setup was removed.'}
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
        self.assertEqual(app.status.get(), 'Warning: ' + snapshot['message'])

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
        self.assertIn('Connect again', info.call_args.args[1])

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

    def test_expired_creation_warning_survives_final_refresh_and_unblocks_editing(self):
        app = app_shell({'id': 9, 'editable': True})
        app.pending, app.pending_poll_id = True, 'old-timer'
        app.status_label = Widget()
        warning = 'The vehicle already left the reference. The temporary setup was removed.'
        result = {'pending': False, 'core_paused': True, 'warning': True, 'message': warning}
        snapshot = {'pending': False, 'core_paused': True}
        app.controller = types.SimpleNamespace(poll=Mock(return_value=result),
                                               refresh=Mock(return_value=snapshot))
        def display_snapshot(value, selected_id=None):
            app._set_core_state(value)
            app._set_status('Lista atualizada.')
        app._snapshot = Mock(side_effect=display_snapshot)
        jobs = []
        app._submit = lambda label, work, done, **options: jobs.append((work, done))
        app._poll_pending()
        work, done = jobs.pop()
        done(work())
        app._update_controls()
        app.controller.poll.assert_called_once()
        app.controller.refresh.assert_called_once()
        app._snapshot.assert_called_once_with(snapshot, None)
        self.assertFalse(app.pending)
        self.assertTrue(app.core_paused)
        self.assertEqual(app.status.get(), 'Warning: ' + warning)
        self.assertEqual(app.status_label.options['foreground'], '#8a5200')
        self.assertEqual(app.move_button.options['state'], 'normal')
        self.assertEqual(app.add_button.options['state'], 'normal')

    def test_pending_window_growth_uses_widget_request_and_screen_limit(self):
        app = app_shell()
        app.pending, app.root = True, Mock()
        app.root.winfo_height.return_value = 710
        app.root.winfo_width.return_value = 1040
        app.root.winfo_reqheight.return_value = 860
        app.root.winfo_screenheight.return_value = 1080
        app._fit_pending_window()
        app.root.geometry.assert_called_once_with('1040x860')
        app.root.geometry.reset_mock()
        app.root.winfo_screenheight.return_value = 768
        app._fit_pending_window()
        app.root.geometry.assert_not_called()
        app.pending = False
        app.root.winfo_screenheight.return_value = 1080
        app._fit_pending_window()
        app.root.geometry.assert_not_called()

    def test_snapshot_pause_boolean_is_understood(self):
        app = app_shell(paused=None)
        app._set_core_state({'core_paused': True, 'status': 'Lista atualizada.'})
        self.assertTrue(app.core_paused)
        self.assertEqual(app.core_text.get(), 'Game paused')
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
        app.controller = types.SimpleNamespace(refresh=Mock(side_effect=RuntimeError('game resumed')))
        app._snapshot = Mock()
        jobs = []
        app._submit = lambda label, work, done: jobs.append((work, done))
        action = Mock(return_value={'message': 'Position applied.'})
        app._change('Mover', action)
        work, done = jobs.pop()
        done(work())
        action.assert_called_once()
        app.controller.refresh.assert_called_once()
        app._snapshot.assert_not_called()
        self.assertIn('Position applied.', app.status.get())
        self.assertIn('Refresh list', app.status.get())

    def test_invalid_distance_is_not_a_backend_request(self):
        for value in ('NaN', 'Inf', '-Inf', '0', '-2', 'texto'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError): gui.number(value, positive=True)
        self.assertEqual(gui.number(' 10,5 ', positive=True), 10.5)


class RecoveryAndExportTests(unittest.TestCase):
    @staticmethod
    def connection_app(controller):
        app = app_shell()
        app.controller = controller
        app.connection_text = Var()
        app.model_choice = Var('Same model as selected')
        app.models, app.model_choices, app.vehicles = {}, {}, {}
        app.table, app.catalog_table = Mock(), Mock()
        app.table.get_children.return_value = ()
        app.catalog_table.get_children.return_value = ()
        app._selection_changed = Mock()
        app.finalize_button = Widget()
        return app

    def test_connection_with_rejected_profile_skips_second_read_and_allows_finalize(self):
        connection = {'game': 'Burnout 3 USA', 'profile': 'SLUS-21050', 'core_paused': True,
                      'profile_valid': False, 'warning': True, 'models': [], 'vehicles': [],
                      'message': 'The traffic structures did not pass the check.'}
        controller = types.SimpleNamespace(connect=Mock(return_value=connection), refresh=Mock())
        app = self.connection_app(controller)
        jobs = []
        app._submit = lambda label, work, done: jobs.append((work, done))
        app.connect()
        work, done = jobs.pop()
        done(work())
        app._update_controls()
        controller.refresh.assert_not_called()
        self.assertTrue(app.connected)
        self.assertFalse(app.profile_valid)
        self.assertEqual(app.finalize_button.options['state'], 'normal')
        self.assertEqual(app.move_button.options['state'], 'disabled')
        self.assertEqual(app.add_button.options['state'], 'disabled')
        self.assertIn(connection['message'], app.status.get())

    def test_second_read_profile_rejection_preserves_verified_connection(self):
        controller = types.SimpleNamespace(
            connect=Mock(return_value={'game': 'Burnout 3 USA', 'core_paused': True}),
            refresh=Mock(side_effect=ProfileError('perfil rejeitado na segunda leitura')))
        app = self.connection_app(controller)
        jobs = []
        app._submit = lambda label, work, done: jobs.append((work, done))
        app.connect()
        work, done = jobs.pop()
        done(work())
        app._update_controls()
        self.assertTrue(app.connected)
        self.assertFalse(app.profile_valid)
        self.assertEqual(app.finalize_button.options['state'], 'normal')
        self.assertIn('perfil rejeitado na segunda leitura', app.status.get())

    def test_pine_error_during_second_read_is_not_treated_as_profile_rejection(self):
        error = PineTransportError('fake disconnect', may_have_executed=False)
        controller = types.SimpleNamespace(connect=Mock(return_value={'core_paused': True}),
                                           refresh=Mock(side_effect=error))
        app = self.connection_app(controller)
        jobs = []
        app._submit = lambda label, work, done: jobs.append((work, done))
        app.connect()
        work, _done = jobs.pop()
        with self.assertRaises(PineTransportError): work()
        self.assertFalse(app.connected)
        app._update_controls()
        self.assertEqual(app.finalize_button.options['state'], 'disabled')

    def test_identity_failure_is_not_treated_as_profile_rejection(self):
        error = PineTransportError('fake identity failure', may_have_executed=False)
        controller = types.SimpleNamespace(connect=Mock(side_effect=error), refresh=Mock())
        app = self.connection_app(controller)
        jobs = []
        app._submit = lambda label, work, done: jobs.append((work, done))
        app.connect()
        work, _done = jobs.pop()
        with self.assertRaises(PineTransportError): work()
        self.assertFalse(app.connected)
        controller.refresh.assert_not_called()

    def test_finalize_button_does_not_require_selection_profile_or_gui_pending(self):
        for pending in (False, True):
            with self.subTest(pending=pending):
                app = app_shell()
                app.pending, app.profile_valid = pending, False
                app.finalize_button = Widget()
                app._update_controls()
                self.assertEqual(app.finalize_button.options['state'], 'normal')

    def test_finalize_requires_connection_pause_and_free_worker(self):
        for connected, paused, busy, closed in [(False, True, False, False),
                                               (True, False, False, False),
                                               (True, None, False, False),
                                               (True, True, True, False),
                                               (True, True, False, True)]:
            with self.subTest(connected=connected, paused=paused, busy=busy, closed=closed):
                app = app_shell(paused=paused)
                app.connected, app.busy, app.closed = connected, busy, closed
                app.finalize_button, app._change = Widget(), Mock()
                app._update_controls()
                app.finalize_pending()
                self.assertEqual(app.finalize_button.options['state'], 'disabled')
                app._change.assert_not_called()

    def test_finalize_is_one_worker_action_even_when_gui_pending_is_false(self):
        app = app_shell()
        app.controller = types.SimpleNamespace(finalize_pending=Mock(return_value={'pending': False}))
        actions = []
        app._change = lambda label, action: actions.append(action)
        app.finalize_pending()
        app.controller.finalize_pending.assert_not_called()
        self.assertEqual(len(actions), 1)
        actions[0]()
        app.controller.finalize_pending.assert_called_once()

    def test_cleanup_message_and_warning_survive_profile_refresh_failure(self):
        app = app_shell({'id': 9, 'editable': True})
        app.pending = True
        app.status_label, app.finalize_button = Widget(), Widget()
        app.controller = types.SimpleNamespace(
            finalize_pending=Mock(return_value={'pending': False, 'core_paused': True,
                'warning': True, 'message': 'Pending request finished; alignment not confirmed.'}),
            refresh=Mock(side_effect=RuntimeError('invalid profile')))
        jobs = []
        app._submit = lambda label, work, done: jobs.append((work, done))
        app.finalize_pending()
        work, done = jobs.pop()
        done(work())
        app._update_controls()
        self.assertFalse(app.pending)
        self.assertTrue(app.core_paused)
        self.assertFalse(app.profile_valid)
        self.assertIn('Pending request finished; alignment not confirmed.', app.status.get())
        self.assertIn('invalid profile', app.status.get())
        self.assertEqual(app.status_label.options['foreground'], '#8a5200')
        self.assertEqual(app.move_button.options['state'], 'disabled')
        self.assertEqual(app.add_button.options['state'], 'disabled')
        self.assertEqual(app.load_button.options['state'], 'disabled')
        self.assertEqual(app.table.options['selectmode'], 'none')
        self.assertEqual(app.refresh_button.options['state'], 'normal')
        self.assertEqual(app.finalize_button.options['state'], 'normal')
        app.controller.finalize_pending.assert_called_once()

    def test_invalidated_profile_cannot_select_a_cached_map_actor(self):
        app = app_shell()
        app.profile_valid = False
        app.table = Mock()
        app.map_hits = [(20, 30, 'old-actor')]
        app._map_select(types.SimpleNamespace(x=20, y=30))
        app.table.selection_set.assert_not_called()

    def test_valid_snapshot_is_required_to_reenable_editing_after_invalidation(self):
        vehicle = {'id': 9, 'model_id': 'car', 'editable': True}
        app = app_shell(vehicle)
        app._invalidate_profile()
        app.table, app.catalog_table = Mock(), Mock()
        app.table.get_children.return_value = ()
        app.catalog_table.get_children.return_value = ()
        app.model_choices, app.vehicles = {}, {}
        app.model_choice = Var()
        app._selection_changed = Mock()
        app._snapshot({'core_paused': True, 'models': [], 'vehicles': [vehicle]})
        app._update_controls()
        self.assertTrue(app.profile_valid)
        self.assertEqual(app.move_button.options['state'], 'normal')
        app._snapshot({'core_paused': False, 'status': 'Pause antes de atualizar.'})
        self.assertFalse(app.profile_valid)

    def test_autopoll_never_calls_explicit_finalize_recovery(self):
        app = app_shell()
        app.pending, app.pending_poll_id = True, 'timer'
        app.controller = types.SimpleNamespace(
            poll=Mock(return_value={'pending': True, 'core_paused': True}),
            finalize_pending=Mock(), refresh=Mock())
        app._schedule_pending_poll = Mock()
        jobs = []
        app._submit = lambda label, work, done, **options: jobs.append((work, done))
        app._poll_pending()
        work, done = jobs.pop()
        done(work())
        app.controller.poll.assert_called_once()
        app.controller.finalize_pending.assert_not_called()
        app.controller.refresh.assert_not_called()

    def test_export_name_avoids_existing_local_files(self):
        with TemporaryDirectory(prefix='b3-gui-export-') as folder, patch.object(gui, 'datetime') as clock:
            clock.now.return_value.strftime.return_value = '20261113-190000'
            first = gui.export_suggestion(Path(folder))
            first.write_text('preservar', encoding='utf8')
            second = gui.export_suggestion(Path(folder))
            self.assertNotEqual(first, second)
            self.assertEqual(second.suffix, '.p2s')
            self.assertEqual(first.read_text(encoding='utf8'), 'preservar')
        self.assertEqual(gui.EXPORT_DIRECTORY.parts[-2:], ('outputs', 'events'))

    def test_export_dialog_defaults_to_event_folder_and_displays_returned_path(self):
        app = app_shell()
        app.root, app.state_export = Mock(), True
        returned_path = str(Path('backend-result') / 'saved.p2s')
        app.controller = types.SimpleNamespace(export_state=Mock(return_value={
            'message': 'Estado verificado.', 'path': returned_path}))
        jobs = []
        app._submit = lambda label, work, done: jobs.append((work, done))
        with TemporaryDirectory(prefix='b3-gui-export-') as folder, \
                patch.object(gui, 'EXPORT_DIRECTORY', Path(folder) / 'events'), \
                patch.object(gui.filedialog, 'asksaveasfilename', return_value='chosen.p2s') as dialog:
            app.export_state()
            self.assertEqual(dialog.call_args.kwargs['initialdir'], str(Path(folder) / 'events'))
            self.assertTrue((Path(folder) / 'events').is_dir())
            self.assertTrue(dialog.call_args.kwargs['initialfile'].startswith('edited-event-'))
        work, done = jobs.pop()
        done(work())
        self.assertIn('Estado verificado.', app.status.get())
        self.assertIn(returned_path, app.status.get())
        self.assertNotIn('chosen.p2s', app.status.get())

    def test_bus_type_five_uses_large_gap_without_exposing_trailer_controls(self):
        app = truck_app(reference_is_truck=False)
        app.models['bus'] = {'id': 'bus', 'label': 'Bus', 'kind': 'independent', 'type': 5}
        app.model_choices['Bus'], app.model_choice = 'bus', Var('Bus')
        app.gap_hint = Widget()
        app._update_secondary_choices()
        self.assertEqual(app.gap.get(), '30')
        self.assertIn('Bus/truck', app.gap_hint.options['text'])
        self.assertFalse(app.trailer_visible)
        self.assertEqual(app.count_label.options['text'], 'Amount')

    def test_bus_reference_uses_large_gap_and_van_type_three_keeps_small_gap(self):
        for reference_bus in (False, True):
            with self.subTest(reference_bus=reference_bus):
                app = truck_app(reference_is_truck=False)
                app.models['van3'] = {'id': 'van3', 'kind': 'independent', 'type': 3}
                app.model_choices['Van'], app.model_choice = 'van3', Var('Van')
                if reference_bus:
                    app.models['bus'] = {'id': 'bus', 'kind': 'independent', 'type': 5}
                    app.selected()['model_id'] = 'bus'
                app._update_secondary_choices()
                self.assertEqual(app.gap.get(), '30' if reference_bus else '10')


class ExperimentalPlacementTests(unittest.TestCase):
    @staticmethod
    def creation_app(*, experimental=False):
        app = app_shell({'id': 9, 'model_id': 'car', 'editable': True, 'can_reference': True})
        app.root = Mock()
        app.models = {'car': {'id': 'car', 'kind': 'independent', 'type': 1}}
        app.model_choices = {'Same model as selected': None}
        app.model_choice = Var('Same model as selected')
        app.experimental = Var(experimental)
        app.gap, app.count = Var('10'), Var('1')
        app.point_x, app.point_z = Var('100'), Var('200')
        return app

    def test_experimental_quantity_has_finite_pool_bound_without_eight_car_cap(self):
        for text, expected in [('9', 9), ('50', 50), ('253', 253)]:
            with self.subTest(text=text):
                self.assertEqual(gui.quantity(text, experimental=True), expected)
                with self.assertRaises(ValueError): gui.quantity(text)
        for text in ('0', '-1', '254', '9999999', '1.5', 'NaN', 'Inf', ''):
            with self.subTest(text=text), self.assertRaises(ValueError):
                gui.quantity(text, experimental=True)

    def test_recipe_replay_only_receives_experimental_permission_from_explicit_toggle(self):
        for experimental in (False, True):
            with self.subTest(experimental=experimental):
                app = self.creation_app(experimental=experimental)
                app.controller = types.SimpleNamespace(load_preset=Mock())
                actions = []
                app._change = lambda label, action: actions.append(action)
                with patch.object(gui.filedialog, 'askopenfilename', return_value='recipe.json'):
                    app.load_preset()
                app.controller.load_preset.assert_not_called()
                self.assertEqual(len(actions), 1)
                actions[0]()
                expected = {'experimental': True} if experimental else {}
                app.controller.load_preset.assert_called_once_with(str(Path('recipe.json')), **expected)

    def test_experimental_offroad_actor_can_return_to_road_without_becoming_a_reference(self):
        for experimental in (False, True):
            with self.subTest(experimental=experimental):
                vehicle = {'id': 9, 'editable': False, 'experimental_editable': True,
                           'can_reference': False}
                app = app_shell(vehicle)
                app.experimental, app.lateral = Var(experimental), Var(50)
                app._update_controls()
                self.assertEqual(app.move_button.options['state'], 'normal' if experimental else 'disabled')
                self.assertEqual(app.add_button.options['state'], 'disabled')
                if experimental:
                    app.controller = types.SimpleNamespace(move=Mock())
                    actions = []
                    app._change = lambda label, action: actions.append(action)
                    app.move()
                    app.controller.move.assert_not_called()
                    actions[0]()
                    app.controller.move.assert_called_once_with(9, 50, experimental=True)

    def test_experimental_batches_submit_count_and_distance_without_artificial_maximum(self):
        app = self.creation_app(experimental=True)
        app.gap, app.count = Var('500,5'), Var('52')
        app.controller = types.SimpleNamespace(add_many_behind=Mock())
        actions = []
        app._change = lambda label, action: actions.append(action)
        app.add_behind()
        app.controller.add_many_behind.assert_not_called()
        self.assertEqual(len(actions), 1)
        actions[0]()
        app.controller.add_many_behind.assert_called_once_with(9, None, 500.5, 52,
            secondary_model_id=None, experimental=True)

    def test_experimental_small_spacing_is_explicit_and_normal_mode_rejects_it(self):
        for experimental in (False, True):
            with self.subTest(experimental=experimental):
                app = self.creation_app(experimental=experimental)
                app.gap = Var('0,5')
                app.controller = types.SimpleNamespace(add_many_behind=Mock())
                actions = []
                app._change = lambda label, action: actions.append(action)
                with patch.object(gui.messagebox, 'showinfo'):
                    app.add_behind()
                self.assertEqual(len(actions), int(experimental))
                if actions:
                    actions[0]()
                    self.assertEqual(app.controller.add_many_behind.call_args.args[2], .5)
                    self.assertTrue(app.controller.add_many_behind.call_args.kwargs['experimental'])

    def test_experimental_warning_remains_visible_during_pending_and_status_changes(self):
        app = self.creation_app(experimental=True)
        app.experimental_warning, app.experimental_check = Mock(), Widget()
        app.count_box = Widget()
        app._experimental_changed()
        self.assertEqual(app.count_box.options['to'], 253)
        app.status.set('Lote preparado')
        app.pending = True
        app._update_controls()
        self.assertEqual(app.experimental_check.options['state'], 'disabled')
        self.assertEqual(app.experimental_warning.grid.call_count, 2)
        app.experimental_warning.grid_remove.assert_not_called()
        app.pending, app.experimental = False, Var(False)
        app._experimental_changed()
        self.assertEqual(app.count_box.options['to'], 8)
        app.experimental_warning.grid_remove.assert_called_once()

    def test_experimental_truck_does_not_silently_raise_spacing(self):
        app = truck_app(reference_is_truck=False)
        app.experimental, app.gap = Var(True), Var('.5')
        app.gap_hint = Widget()
        app._update_secondary_choices()
        self.assertEqual(app.gap.get(), '.5')
        self.assertIn('Experimental', app.gap_hint.options['text'])
        self.assertIn('capacity', app.gap_hint.options['text'])

    def test_map_world_conversion_matches_displayed_axes_and_rejects_invalid_view(self):
        self.assertEqual(gui.map_to_world((100, 200, 100), 500, 400, 250, 200), (100, 200))
        self.assertEqual(gui.map_to_world((100, 200, 100), 500, 400, 285, 165), (110, 210))
        for view, width, height in [((0, 0, 0), 500, 400), ((0, 0, 10), 40, 400),
                                     ((0, 0, 10), 500, 50), ((float('nan'), 0, 10), 500, 400)]:
            with self.subTest(view=view, width=width, height=height), self.assertRaises(ValueError):
                gui.map_to_world(view, width, height, 20, 20)

    def test_marking_empty_map_records_coordinates_without_selecting_or_adding(self):
        app = self.creation_app()
        app.marking_position, app.map_view, app.map_hits = True, (100, 200, 100), []
        app.map_canvas, app.table, app.mark_button = Mock(), Mock(), Widget()
        app.map_canvas.winfo_width.return_value = 500
        app.map_canvas.winfo_height.return_value = 400
        app._draw_traffic, app._update_controls = Mock(), Mock()
        app.controller = types.SimpleNamespace(add_at=Mock())
        app._map_select(types.SimpleNamespace(x=285, y=165))
        self.assertEqual(app._target_point(), (110, 210))
        self.assertFalse(app.marking_position)
        app.table.selection_set.assert_not_called()
        app.controller.add_at.assert_not_called()
        app._draw_traffic.assert_called_once()

    def test_marking_and_point_creation_remain_blocked_when_simulation_runs(self):
        app = self.creation_app()
        app.core_paused = False
        app.marking_position, app.map_view, app.map_hits = True, (100, 200, 100), []
        app._change = Mock()
        app._map_select(types.SimpleNamespace(x=285, y=165))
        self.assertEqual(app._target_point(), (100, 200))
        app.add_at()
        app._change.assert_not_called()

    def test_point_creation_is_one_worker_action_with_the_chosen_model_and_mode(self):
        for experimental in (False, True):
            with self.subTest(experimental=experimental):
                app = self.creation_app(experimental=experimental)
                app.point_x, app.point_z = Var('-12,5'), Var('987.25')
                app.model_choices['Van'] = 'van'
                app.model_choice.set('Van')
                app.controller = types.SimpleNamespace(add_at=Mock())
                actions = []
                app._change = lambda label, action: actions.append(action)
                app.add_at()
                self.assertEqual(len(actions), 1)
                app.controller.add_at.assert_not_called()
                actions[0]()
                app.controller.add_at.assert_called_once_with(9, 'van', -12.5, 987.25,
                    secondary_model_id=None, experimental=experimental)

    def test_nonfinite_target_never_reaches_backend(self):
        for bad in ('NaN', 'Inf', '-Inf', '', '1e308', '-1e308'):
            with self.subTest(bad=bad):
                app = self.creation_app(experimental=True)
                app.point_x.set(bad)
                app._change = Mock()
                with patch.object(gui.messagebox, 'showinfo') as info:
                    app.add_at()
                app._change.assert_not_called()
                info.assert_called_once()

    def test_point_button_requires_target_reference_and_confirmed_pause(self):
        app = self.creation_app()
        app.add_at_button, app.point_x_entry, app.point_z_entry, app.mark_button = [Widget() for _ in range(4)]
        app._update_controls()
        self.assertEqual(app.add_at_button.options['state'], 'normal')
        app.point_x.set('NaN')
        app._update_controls()
        self.assertEqual(app.add_at_button.options['state'], 'disabled')
        app.point_x.set('100')
        app.selected()['can_reference'] = False
        app._update_controls()
        self.assertEqual(app.add_at_button.options['state'], 'disabled')
        self.assertEqual(app.mark_button.options['state'], 'disabled')

    def test_cancelling_remaining_queue_uses_worker_without_repeating_creation(self):
        app = self.creation_app(experimental=True)
        app.pending, app.core_paused = True, False
        app.cancel_queue_button = Widget()
        app.controller = types.SimpleNamespace(cancel_queue=Mock())
        actions = []
        app._change = lambda label, action: actions.append(action)
        app._update_controls()
        self.assertEqual(app.cancel_queue_button.options['state'], 'normal')
        app.cancel_queue()
        app.controller.cancel_queue.assert_not_called()
        self.assertEqual(len(actions), 1)
        actions[0]()
        app.controller.cancel_queue.assert_called_once()

    def test_capacity_summary_does_not_claim_free_resources_when_unknown(self):
        summary = gui.capacity_summary({'vehicles': [{'initialized': True}, {'initialized': False}]})
        self.assertIn('Active objects: 2', summary)
        self.assertIn('Physics ready: 1', summary)
        self.assertNotIn('Free', summary)
        summary = gui.capacity_summary({'capacity': {'active_objects': 60, 'initialized_objects': 48,
            'free_objects': 194, 'free_nodes': 191, 'queued_operations': 13,
            'physics_warning': 'Some vehicles are not ready.'}})
        self.assertIn('Active objects: 60', summary)
        self.assertIn('Physics ready: 48', summary)
        self.assertIn('Free nodes: 191', summary)
        self.assertIn('Queued: 13', summary)
        self.assertIn('Some vehicles are not ready.', summary)
        crowded = gui.capacity_summary({'vehicles': [{'type': 1}] * 64 + [{'type': 11}] * 5})
        self.assertIn('64 vehicles', crowded)
        self.assertIn('crashed in tests', crowded)


class RouteAndSpeedTests(unittest.TestCase):
    @staticmethod
    def map_app(vehicle=None):
        app=app_shell(vehicle)
        app.map_canvas,app.table=Mock(),Mock()
        app.map_canvas.winfo_width.return_value=500
        app.map_canvas.winfo_height.return_value=400
        app.table.selection.return_value=()
        app.map_view,app.player=None,None
        app.map_hits=[]
        app.point_x,app.point_z=Var(''),Var('')
        app.show_routes,app.map_notice=Var(True),Var()
        app.vehicles={}
        app.routes={'paths':[dict(id=3,left=[[-100,0,-5],[100,0,-5]],
            center=[[-100,0,0],[100,0,0]],right=[[-100,0,5],[100,0,5]],
            arrows=[{'from':[-20,0,0],'to':[20,0,0]}],traffic_direction_verified=True)]}
        return app

    def test_player_is_labelled_and_physics_range_is_drawn_around_it(self):
        app=self.map_app()
        app.player={'position':[10,0,0],'forward':[1,0,0]}
        app._draw_traffic()
        labels=[call.kwargs.get('text','') for call in app.map_canvas.create_text.call_args_list]
        self.assertIn('Player',labels)
        self.assertTrue(any('physics range' in label for label in labels))
        rings=[call for call in app.map_canvas.create_oval.call_args_list if call.kwargs.get('dash')==(4,4)]
        self.assertEqual(len(rings),1)
        x0,_,x1,_=rings[0].args
        self.assertGreater(x1-x0,20)

    def test_route_only_snapshot_fits_and_draws_loaded_ribbon_without_actors(self):
        app=self.map_app()
        app._draw_traffic()
        self.assertEqual(app.map_view,(0,0,240))
        app.map_canvas.create_polygon.assert_called_once()
        self.assertEqual(app.map_canvas.create_oval.call_count,0)
        coordinates=app.map_canvas.create_polygon.call_args.args
        self.assertTrue(all(isinstance(value,(float,int)) for value in coordinates))
        self.assertAlmostEqual(coordinates[0],250-100*350/240)
        self.assertEqual(app.map_hits,[])

    def test_route_arrow_uses_increasing_world_x_and_not_an_inverted_screen_direction(self):
        app=self.map_app()
        app._draw_traffic()
        arrow=next(call for call in app.map_canvas.create_line.call_args_list
                   if call.kwargs.get('arrow')==gui.tk.LAST)
        self.assertLess(arrow.args[0],arrow.args[2])
        self.assertEqual(arrow.args[1],arrow.args[3])
        self.assertNotIn('dash',arrow.kwargs)

    def test_unverified_flow_arrows_are_dashed_and_labelled_as_path_progression(self):
        app=self.map_app()
        app.routes['paths'][0]['traffic_direction_verified']=False
        app._draw_traffic()
        arrow=next(call for call in app.map_canvas.create_line.call_args_list
                   if call.kwargs.get('arrow')==gui.tk.LAST)
        self.assertEqual(arrow.kwargs['dash'],(3,3))
        labels=[call.kwargs.get('text','') for call in app.map_canvas.create_text.call_args_list]
        self.assertTrue(any('path direction' in label for label in labels))

    def test_selected_vehicle_path_is_highlighted_below_the_actor(self):
        vehicle={'id':9,'path':3,'initialized':True,'position':[0,0,0]}
        app=self.map_app(vehicle)
        app.vehicles={'car':vehicle}
        app._draw_traffic()
        self.assertEqual(app.map_canvas.create_polygon.call_args.kwargs['fill'],'#fff0bd')
        names=[call[0] for call in app.map_canvas.mock_calls]
        self.assertLess(names.index('create_polygon'),names.index('create_oval'))

    def test_hiding_routes_refits_to_actors_and_preserves_world_click_axes(self):
        app=self.map_app()
        app.vehicles={'car':{'initialized':True,'position':[1000,0,2000]}}
        app._draw_traffic()
        app.map_canvas.reset_mock()
        app.show_routes.set(False)
        app._routes_changed()
        app.map_canvas.create_polygon.assert_not_called()
        self.assertEqual(app.map_view[:2],(1000,2000))
        self.assertEqual(gui.map_to_world(app.map_view,500,400,250,200),(1000,2000))

    def test_bad_route_vertex_breaks_the_line_instead_of_joining_unknown_geometry(self):
        app=self.map_app()
        app.routes={'paths':[dict(id=3,center=[[0,0,0],[10,0,0],[float('nan'),0,0],[30,0,0]],
                                 arrows=[{'from':None,'to':[2,0,0]}])]}
        app._draw_traffic()
        lines=[call for call in app.map_canvas.create_line.call_args_list if call.kwargs.get('dash')==(5,4)]
        self.assertEqual(len(lines),1)
        self.assertEqual(len(lines[0].args),4)
        app.map_canvas.create_polygon.assert_not_called()

    def test_rejected_profile_clears_cached_route_geometry(self):
        app=self.map_app()
        app._invalidate_profile()
        self.assertEqual(app.routes,{})
        self.assertEqual(app._map_routes(),[])

    def test_nominal_and_internal_speeds_distinguish_zero_from_missing(self):
        nominal={'speed_info':dict(control_value=0,travel_value=0,nominal_target_kmh=0,
                                   nominal_travel_kmh=0)}
        self.assertEqual(gui.speed_summary(nominal),'0.000 / 0.000')
        self.assertIn('Nominal',gui.speed_summary(nominal,detailed=True))
        legacy={'speed_info':dict(control_value=0,travel_value=None,units='internal units')}
        self.assertEqual(gui.speed_summary(legacy),'0.000 / —')
        self.assertIn('internal units',gui.speed_summary(legacy,detailed=True))
        self.assertEqual(gui.speed_summary({}),'—')

    def test_speed_action_converts_nominal_kmh_once_and_runs_on_worker(self):
        vehicle={'id':9,'can_set_speed':True,'editable':True,'can_reference':False}
        app=app_shell(vehicle)
        app.speed_target_kmh,app.root=Var('80,4672'),Mock()
        app.controller=types.SimpleNamespace(set_speed=Mock())
        jobs=[]
        app._change=lambda _label,action:jobs.append(action)
        app.set_speed()
        app.controller.set_speed.assert_not_called()
        self.assertEqual(len(jobs),1)
        jobs[0]()
        self.assertEqual(app.controller.set_speed.call_args.args[0],9)
        self.assertAlmostEqual(app.controller.set_speed.call_args.args[1],50)
        self.assertEqual(app.controller.set_speed.call_args.kwargs,{})
        app.experimental=Var(True)
        app.speed_target_kmh.set('0')
        app.set_speed()
        jobs[1]()
        app.controller.set_speed.assert_called_with(9,0.0,experimental=True)

    def test_speed_controls_allow_stopped_actor_but_require_verified_capability_and_pause(self):
        for can_set,paused,pending,profile_valid in [(True,True,False,True),(False,True,False,True),
                    (True,False,False,True),(True,True,True,True),(True,True,False,False)]:
            with self.subTest(can_set=can_set,paused=paused,pending=pending,profile_valid=profile_valid):
                app=app_shell({'id':9,'can_set_speed':can_set,'can_reference':False,'editable':True},paused=paused)
                app.profile_valid,app.pending=profile_valid,pending
                app.speed_controls,app.speed_entry,app.speed_button=Mock(),Widget(),Widget()
                app._update_controls()
                allowed=can_set and paused and not pending and profile_valid
                self.assertEqual(app.speed_button.options['state'],'normal' if allowed else 'disabled')
                self.assertEqual(app.add_button.options['state'],'disabled')

    def test_invalid_or_out_of_normal_range_speed_never_submits_a_write(self):
        app=app_shell({'id':9,'can_set_speed':True})
        app.root,app._change=Mock(),Mock()
        app.speed_target_kmh=Var()
        with patch.object(gui.messagebox,'showinfo'):
            for text in ('-1','NaN','Inf','400','1e300'):
                app.speed_target_kmh.set(text)
                app.set_speed()
        app._change.assert_not_called()

    def test_normal_maximum_nominal_speed_round_trips_to_exact_control_limit(self):
        app=app_shell({'id':9,'can_set_speed':True})
        app.root,app.speed_target_kmh=Mock(),Var('386,24256')
        app.controller=types.SimpleNamespace(set_speed=Mock())
        jobs=[]
        app._change=lambda _label,action:jobs.append(action)
        with patch.object(gui.messagebox,'showinfo') as info:
            app.set_speed()
        info.assert_not_called()
        jobs[0]()
        self.assertAlmostEqual(app.controller.set_speed.call_args.args[1],240)
        self.assertLessEqual(app.controller.set_speed.call_args.args[1],240)

    def test_multiple_speed_targets_use_one_bulk_worker_action(self):
        app = multi_app([{'id': 9, 'can_set_speed': True},
                         {'id': 12, 'can_set_speed': True}], [9, 12], focus=12)
        app.root, app.speed_target_kmh = Mock(), Var('80,4672')
        app.controller = types.SimpleNamespace(set_speed=Mock(), set_speeds=Mock())
        jobs = []
        app._change = lambda _label, action: jobs.append(action)
        app.set_speed()
        self.assertEqual(len(jobs), 1)
        app.controller.set_speeds.assert_not_called()
        jobs[0]()
        app.controller.set_speeds.assert_called_once_with([9, 12], 50.0)
        app.controller.set_speed.assert_not_called()
        app.experimental = Var(True)
        app.speed_target_kmh.set('0')
        app.set_speed()
        jobs[1]()
        app.controller.set_speeds.assert_called_with([9, 12], 0.0, experimental=True)

    def test_mixed_speed_selection_is_blocked_in_full_without_silently_skipping_cargo(self):
        app = multi_app([{'id': 9, 'can_set_speed': True},
                         {'id': 12, 'can_set_speed': False, 'kind': 'trailer'}], [9, 12], focus=9)
        app.root, app._change = Mock(), Mock()
        app.speed_controls, app.speed_entry, app.speed_button = Mock(), Widget(), Widget()
        app.speed_selection_text = Var()
        app._update_controls()
        self.assertEqual(app.speed_button.options['state'], 'disabled')
        self.assertEqual(app.speed_button.options['text'], 'Apply to the 2 selected')
        self.assertIn('2 selected · 1 eligible · 1 blocked', app.speed_selection_text.get())
        self.assertIn('cab', app.speed_selection_text.get())
        with patch.object(gui.messagebox, 'showinfo') as info:
            app.set_speed()
        app._change.assert_not_called()
        info.assert_called_once()

    def test_bulk_speed_controls_and_action_require_confirmed_idle_pause_and_profile(self):
        for paused, busy, pending, profile, connected, closed in [
                (True, False, False, True, True, False),
                (False, False, False, True, True, False),
                (None, False, False, True, True, False),
                (True, True, False, True, True, False),
                (True, False, True, True, True, False),
                (True, False, False, False, True, False),
                (True, False, False, True, False, False),
                (True, False, False, True, True, True)]:
            with self.subTest(paused=paused, busy=busy, pending=pending, profile=profile,
                              connected=connected, closed=closed):
                app = multi_app([{'id': 9, 'can_set_speed': True},
                                 {'id': 12, 'can_set_speed': True}], [9, 12], focus=9)
                app.core_paused, app.busy, app.pending = paused, busy, pending
                app.profile_valid, app.connected, app.closed = profile, connected, closed
                app.speed_controls, app.speed_entry, app.speed_button = Mock(), Widget(), Widget()
                app.select_speed_button = Widget()
                app.speed_target_kmh, app.root, app._change = Var('40'), Mock(), Mock()
                app._update_controls()
                allowed = paused is True and not busy and not pending and profile and connected and not closed
                self.assertEqual(app.speed_button.options['state'], 'normal' if allowed else 'disabled')
                self.assertEqual(app.select_speed_button.options['state'], 'normal' if allowed else 'disabled')
                app.set_speed()
                self.assertEqual(app._change.call_count, int(allowed))

    def test_focused_selected_actor_remains_primary_for_single_vehicle_actions(self):
        app = multi_app([{'id': 9}, {'id': 12}], [9, 12], focus=12)
        self.assertEqual(app.selected()['id'], 12)
        self.assertEqual([vehicle['id'] for vehicle in app.selected_vehicles()], [9, 12])
        app.table.focus('stale-row')
        self.assertEqual(app.selected()['id'], 9)
        app.table.selection_set([])
        self.assertIsNone(app.selected())

    def test_select_speed_eligible_excludes_trailer_and_inactive_actors_and_preserves_focus(self):
        vehicles = [{'id': 9, 'can_set_speed': True}, {'id': 12, 'can_set_speed': True},
                    {'id': 13, 'can_set_speed': False}, {'id': 14, 'can_set_speed': True, 'active': False}]
        app = multi_app(vehicles, [12, 13], focus=12)
        app._selection_changed = Mock()
        app.select_speed_eligible()
        self.assertEqual([vehicle['id'] for vehicle in app.selected_vehicles()], [9, 12])
        self.assertEqual(app.selected()['id'], 12)
        app._selection_changed.assert_called_once()
        app.pending = True
        app.table.selection_set('row-9')
        app.select_speed_eligible()
        self.assertEqual(app.table.selection(), ('row-9',))

    def test_snapshot_preserves_multi_selection_by_actor_id_across_reorder_and_removal(self):
        vehicles = [{'id': 9}, {'id': 12}, {'id': 13}]
        app = multi_app(vehicles, [9, 12], focus=12)
        app.catalog_table = Mock()
        app.catalog_table.get_children.return_value = ()
        app.model_choices, app.model_choice = {}, Var()
        app._selection_changed = Mock()
        app._snapshot({'models': [], 'vehicles': [vehicles[2], vehicles[1], vehicles[0]]})
        self.assertEqual({vehicle['id'] for vehicle in app.selected_vehicles()}, {9, 12})
        self.assertEqual(app.selected()['id'], 12)
        self.assertEqual(app.table.focus(), 'vehicle-1')
        app._snapshot({'models': [], 'vehicles': [vehicles[0], vehicles[2]]})
        self.assertEqual([vehicle['id'] for vehicle in app.selected_vehicles()], [9])
        self.assertEqual(app.selected()['id'], 9)

    def test_completed_action_cancels_stale_timer_even_if_refresh_retains_old_pending_flag(self):
        app = app_shell({'id': 9, 'editable': True})
        app.root, app._snapshot = Mock(), Mock()
        app.pending, app.pending_poll_id = True, 'pending-timer'
        app.controller = types.SimpleNamespace(refresh=Mock(return_value={'pending': True}))
        jobs = []
        app._submit = lambda _label, work, done: jobs.append((work, done))
        app._change('Finalizar', lambda: {'pending': False, 'message': 'Finalizado.'})
        work, done = jobs.pop()
        done(work())
        self.assertFalse(app.pending)
        self.assertIsNone(app.pending_poll_id)
        app.root.after_cancel.assert_called_once_with('pending-timer')
        app.root.after.assert_not_called()
        app._update_controls()
        self.assertEqual(app.add_button.options['state'], 'normal')

    def test_full_paused_connection_snapshot_avoids_duplicate_network_read(self):
        payload={'game':'Burnout 3 USA','profile':'SLUS-21050','core_paused':True,
                 'profile_valid':True,'vehicles':[],'models':[],'routes':{'paths':[]}}
        controller=types.SimpleNamespace(connect=Mock(return_value=payload),refresh=Mock())
        app=RecoveryAndExportTests.connection_app(controller)
        app._snapshot=Mock()
        jobs=[]
        app._submit=lambda _label,work,done:jobs.append((work,done))
        app.connect()
        work,done=jobs.pop()
        done(work())
        controller.refresh.assert_not_called()
        app._snapshot.assert_called_once_with(payload)
        self.assertTrue(app.connected)

    def test_right_drag_moves_view_without_changing_world_point_or_actor(self):
        app=self.map_app()
        app.map_view=(100,200,100)
        app._draw_traffic=Mock()
        app._map_pan_start(types.SimpleNamespace(x=250,y=200))
        app._map_pan(types.SimpleNamespace(x=285,y=235))
        self.assertEqual(app.map_view,(90,210,100))
        self.assertIsNone(app._target_point())
        self.assertEqual(app.map_hits,[])
        app._map_pan_end()
        self.assertIsNone(app.map_pan_state)
        before=app.map_view
        app._map_pan(types.SimpleNamespace(x=0,y=0))
        self.assertEqual(app.map_view,before)

    def test_selected_path_fit_enables_routes_and_ignores_other_far_routes(self):
        app=self.map_app({'id':9,'path':3})
        app.routes['paths'].append(dict(id=4,center=[[10000,0,10000],[20000,0,20000]]))
        app.show_routes.set(False)
        app._map_selected_path()
        self.assertTrue(app.show_routes.get())
        self.assertEqual(app.map_view,(0,0,240))
        self.assertIn('P3',app.status.get())

    def test_route_budget_warning_remains_visible_in_paused_notice(self):
        app=self.map_app()
        app.routes['warning']='Partial view: path budget reached.'
        app._set_core_state({'core_paused':True})
        self.assertIn('Partial view',app.map_notice.get())
        self.assertIn('heights can overlap',app.map_notice.get())

    def test_unreferenced_descriptor_is_drawn_as_a_candidate_instead_of_active_road(self):
        app=self.map_app()
        app.routes['paths'][0].update(source='descriptor_candidate',reference_observed=False)
        app._draw_traffic()
        self.assertEqual(app.map_canvas.create_polygon.call_args.kwargs['fill'],'#eff2f5')
        labels=[call.kwargs.get('text','') for call in app.map_canvas.create_text.call_args_list]
        self.assertIn('P3?',labels)
        self.assertTrue(any('no associated vehicle' in text for text in labels))

    def test_details_canvas_tracks_full_content_height_without_changing_the_map(self):
        app=app_shell()
        app.details_canvas=Mock()
        app.details_canvas.bbox.return_value=(0,0,350,1200)
        app.map_view=(100,200,50)
        app._details_region()
        app.details_canvas.configure.assert_called_once_with(scrollregion=(0,0,350,1200))
        self.assertEqual(app.map_view,(100,200,50))

    def test_details_width_updates_inner_window_and_wraps_labels(self):
        app=app_shell()
        app.details_canvas,app.details_window=Mock(),17
        app.details_canvas.bbox.return_value=(0,0,280,1000)
        for name in ('selection_label','position_label','speed_label'):
            setattr(app,name,Widget())
        app._details_resize(types.SimpleNamespace(width=280))
        app.details_canvas.itemconfigure.assert_called_once_with(17,width=280)
        self.assertEqual(app.speed_label.options['wraplength'],256)
        app.details_canvas.configure.assert_called_once_with(scrollregion=(0,0,280,1000))
        app.closed=True
        app.details_canvas.reset_mock()
        app._details_resize(types.SimpleNamespace(width=100))
        app.details_canvas.itemconfigure.assert_not_called()


class EventProjectTests(unittest.TestCase):
    @staticmethod
    def app(*, existing=False):
        app=app_shell({'id':9,'editable':True})
        app.root=Mock()
        app.event_projects=True
        app.project=dict(path='event.b3event.json',name='Crossing',scene_revision=2) if existing else None
        app.project_name,app.project_text=Var('Meu cruzamento'),Var()
        for name in ('project_name_entry','new_project_button','open_project_button',
                     'save_project_button','test_project_button','restart_project_button','restore_base_button',
                     'import_project_button','save_project_state_button','confirm_scene_button','confirm_base_button'):
            setattr(app,name,Widget())
        return app

    def test_controls_require_capability_profile_pause_idle_and_active_project(self):
        for blocked in (None,'capability','profile','running','pending','busy','closed','disconnected'):
            for existing in (False,True):
                with self.subTest(blocked=blocked,existing=existing):
                    app=self.app(existing=existing)
                    if blocked=='capability': app.event_projects=False
                    elif blocked=='profile': app.profile_valid=False
                    elif blocked=='running': app.core_paused=False
                    elif blocked=='pending': app.pending=True
                    elif blocked=='busy': app.busy=True
                    elif blocked=='closed': app.closed=True
                    elif blocked=='disconnected': app.connected=False
                    app._update_controls()
                    ready=blocked is None
                    for name in ('new_project_button','open_project_button','project_name_entry',
                                 'import_project_button','confirm_scene_button','confirm_base_button'):
                        self.assertEqual(getattr(app,name).options['state'],'normal' if ready else 'disabled')
                    for name in ('save_project_button','test_project_button','restart_project_button','restore_base_button',
                                 'save_project_state_button'):
                        self.assertEqual(getattr(app,name).options['state'],
                                         'normal' if ready and existing else 'disabled')

    def test_project_context_survives_refresh_and_can_be_explicitly_cleared(self):
        app=self.app()
        project=dict(path='folder/event.b3event.json',name='Avenue',base_path='base.p2s',
                     scene_path='scene.p2s',scene_revision=3)
        app._set_core_state(dict(core_paused=True,event_projects=True,project=project))
        self.assertEqual(app.project,project)
        self.assertEqual(app.project_name.get(),'Avenue')
        self.assertIn('Saved scene 3',app.project_text.get())
        self.assertIn('folder/event.b3event.json',app.project_text.get())
        app._set_core_state(dict(core_paused=False))
        self.assertTrue(app.event_projects)
        self.assertEqual(app.project,project)
        app._set_core_state(dict(core_paused=True,event_projects=False))
        self.assertFalse(app.event_projects)
        self.assertEqual(app.project,project)
        app._set_core_state(dict(project=None))
        self.assertIsNone(app.project)
        self.assertIn('No project open',app.project_text.get())

    def test_create_chooses_parent_and_submits_one_new_child_and_trimmed_name(self):
        app=self.app()
        app.project_name.set('  Minha avenida  ')
        app.controller=types.SimpleNamespace(create_project=Mock())
        actions=[]
        app._change=lambda _label,action:actions.append(action)
        with TemporaryDirectory() as folder, patch.object(gui.filedialog,'askdirectory',return_value=folder) as dialog:
            app.create_project()
            app.controller.create_project.assert_not_called()
            self.assertEqual(len(actions),1)
            actions[0]()
            directory,name=app.controller.create_project.call_args.args
            self.assertEqual(Path(directory).parent,Path(folder))
            self.assertTrue(Path(directory).name.startswith('event-'))
            self.assertFalse(Path(directory).exists(),'Backend owns exclusive directory creation')
            self.assertEqual(name,'Minha avenida')
            self.assertTrue(dialog.call_args.kwargs['mustexist'])

    def test_new_directory_suggestion_avoids_existing_files_and_directories(self):
        clock=Mock()
        clock.now.return_value.strftime.return_value='20261115-120000'
        with TemporaryDirectory() as folder, patch.object(gui,'datetime',clock):
            parent=Path(folder)
            first=gui.project_suggestion(parent)
            first.mkdir()
            second=gui.project_suggestion(parent)
            second.write_text('occupied',encoding='utf8')
            self.assertEqual(gui.project_suggestion(parent).name,'event-20261115-120000-002')

    def test_cancelled_or_invalid_create_does_not_reach_the_controller(self):
        for name in ('','   ','x'*101,'A\nB','Valid'):
            with self.subTest(name=name):
                app=self.app()
                app.project_name.set(name)
                app._change=Mock()
                with patch.object(gui.filedialog,'askdirectory',return_value='') as dialog, \
                     patch.object(gui.messagebox,'showinfo') as info:
                    app.create_project()
                app._change.assert_not_called()
                if name=='Valid':
                    dialog.assert_called_once()
                    info.assert_not_called()
                else:
                    dialog.assert_not_called()
                    info.assert_called_once()

    def test_open_passes_manifest_to_worker_and_invalidates_stale_traffic(self):
        app=self.app(existing=True)
        app.controller=types.SimpleNamespace(open_project=Mock())
        actions=[]
        app._change=lambda _label,action:actions.append(action)
        with patch.object(gui.filedialog,'askopenfilename',return_value='saved.b3event.json') as dialog:
            app.open_project()
        self.assertFalse(app.profile_valid)
        app.controller.open_project.assert_not_called()
        self.assertEqual(dialog.call_args.kwargs['filetypes'],[('Event project','*.b3event.json')])
        actions[0]()
        app.controller.open_project.assert_called_once_with(str(Path('saved.b3event.json')))

    def test_project_actions_use_one_controller_worker_action(self):
        for method in ('save_project','test_project','restart_project','restore_project_base'):
            with self.subTest(method=method):
                app=self.app(existing=True)
                action=Mock()
                app.controller=types.SimpleNamespace(**{method:action})
                actions=[]
                app._change=lambda _label,callback:actions.append(callback)
                getattr(app,method)()
                action.assert_not_called()
                self.assertEqual(len(actions),1)
                self.assertEqual(app.profile_valid,method=='save_project')
                actions[0]()
                action.assert_called_once_with()

    def test_missing_project_or_pending_blocks_every_project_action(self):
        for condition in ('missing','pending','busy','running','invalid_profile','no_capability'):
            with self.subTest(condition=condition):
                app=self.app(existing=condition!='missing')
                if condition=='pending': app.pending=True
                elif condition=='busy': app.busy=True
                elif condition=='running': app.core_paused=False
                elif condition=='invalid_profile': app.profile_valid=False
                elif condition=='no_capability': app.event_projects=False
                app._change=Mock()
                for method in ('save_project','test_project','restart_project','restore_project_base'):
                    getattr(app,method)()
                app._change.assert_not_called()
                if condition!='missing':
                    with patch.object(gui.filedialog,'askdirectory') as directory, \
                         patch.object(gui.filedialog,'askopenfilename') as opening:
                        app.create_project()
                        app.open_project()
                    directory.assert_not_called()
                    opening.assert_not_called()

    def test_test_response_cancels_stale_timer_and_keeps_running_despite_stale_refresh(self):
        app=self.app(existing=True)
        app.pending_poll_id='old-timer'
        project=dict(path='event.b3event.json',name='Crossing',scene_revision=3)
        result=dict(pending=False,core_paused=False,project=project,message='Cena salva. Pode jogar.')
        app.controller=types.SimpleNamespace(test_project=Mock(return_value=result),
            refresh=Mock(return_value=dict(core_paused=True,vehicles=[],models=[])))
        def stale_snapshot(response,selected_id=None):
            app.profile_valid=True
            app._set_core_state(response)
        app._snapshot=Mock(side_effect=stale_snapshot)
        jobs=[]
        app._submit=lambda _label,work,done:jobs.append((work,done))
        app.test_project()
        work,done=jobs.pop()
        done(work())
        app._update_controls()
        self.assertFalse(app.core_paused)
        self.assertFalse(app.profile_valid)
        self.assertIsNone(app.pending_poll_id)
        app.root.after_cancel.assert_called_once_with('old-timer')
        self.assertEqual(app.project,project)
        self.assertEqual(app.project_text.get().splitlines()[0],'Crossing · Saved scene 3')
        self.assertEqual(app.restart_project_button.options['state'],'disabled')
        self.assertEqual(app.move_button.options['state'],'disabled')
        self.assertEqual(app.status.get(),result['message'])

    def test_reconnect_preserves_project_and_accepts_capability(self):
        project=dict(path='event.b3event.json',name='Avenue',scene_revision=4)
        connection=dict(core_paused=True,vehicles=[],models=[],event_projects=True)
        controller=types.SimpleNamespace(connect=Mock(return_value=connection))
        app=RecoveryAndExportTests.connection_app(controller)
        app.event_projects=False
        app.project=project
        app.project_text,app.project_name=Var('Avenue'),Var('Avenue')
        jobs=[]
        app._submit=lambda _label,work,done:jobs.append((work,done))
        app.connect()
        work,done=jobs.pop()
        done(work())
        self.assertTrue(app.event_projects)
        self.assertEqual(app.project,project)
        self.assertEqual(app.project_name.get(),'Avenue')

    def test_manual_import_uses_new_project_location_and_current_state_file(self):
        app=self.app()
        app.controller=types.SimpleNamespace(import_project=Mock())
        app._new_project_location=Mock(return_value=('new-folder','Avenue'))
        actions=[]
        app._change=lambda _label,action:actions.append(action)
        with patch.object(gui.filedialog,'askopenfilename',return_value='manual.p2s') as dialog:
            app.import_project()
        self.assertEqual(dialog.call_args.kwargs['filetypes'],[('PCSX2 state','*.p2s')])
        app.controller.import_project.assert_not_called()
        self.assertEqual(len(actions),1)
        actions[0]()
        app.controller.import_project.assert_called_once_with('new-folder','Avenue',str(Path('manual.p2s')))

    def test_manual_save_scene_requires_existing_project_and_uses_one_worker(self):
        for existing in (False,True):
            with self.subTest(existing=existing):
                app=self.app(existing=existing)
                app.controller=types.SimpleNamespace(save_project_from_state=Mock())
                actions=[]
                app._change=lambda _label,action:actions.append(action)
                with patch.object(gui.filedialog,'askopenfilename',return_value='current.p2s') as dialog:
                    app.save_project_from_state()
                if not existing:
                    dialog.assert_not_called()
                    self.assertEqual(actions,[])
                else:
                    self.assertEqual(len(actions),1)
                    app.controller.save_project_from_state.assert_not_called()
                    actions[0]()
                    app.controller.save_project_from_state.assert_called_once_with(str(Path('current.p2s')))

    def test_manual_confirmation_selects_manifest_and_distinguishes_base_from_scene(self):
        for base in (False,True):
            for existing in (False,True):
                with self.subTest(base=base,existing=existing):
                    app=self.app(existing=existing)
                    app.controller=types.SimpleNamespace(confirm_project=Mock())
                    actions=[]
                    app._change=lambda _label,action:actions.append(action)
                    with patch.object(gui.filedialog,'askopenfilename',return_value='other.b3event.json') as dialog:
                        (app.confirm_project_base if base else app.confirm_project_scene)()
                    self.assertFalse(app.profile_valid)
                    self.assertEqual(dialog.call_args.kwargs['filetypes'],[('Event project','*.b3event.json')])
                    if existing:
                        self.assertEqual(dialog.call_args.kwargs['initialfile'],'event.b3event.json')
                    app.controller.confirm_project.assert_not_called()
                    self.assertEqual(len(actions),1)
                    actions[0]()
                    app.controller.confirm_project.assert_called_once_with(str(Path('other.b3event.json')),base=base)

    def test_cancelled_manual_file_dialogs_do_not_invalidate_or_submit(self):
        for method in ('import_project','save_project_from_state','confirm_project_scene','confirm_project_base'):
            with self.subTest(method=method):
                app=self.app(existing=True)
                app._new_project_location=Mock(return_value=('new-folder','Avenue'))
                app._change=Mock()
                with patch.object(gui.filedialog,'askopenfilename',return_value=''):
                    getattr(app,method)()
                self.assertTrue(app.profile_valid)
                app._change.assert_not_called()

    def test_manual_actions_cannot_open_dialogs_during_unconfirmed_state(self):
        for condition in ('pending','running','busy','invalid_profile','no_capability'):
            with self.subTest(condition=condition):
                app=self.app(existing=True)
                if condition=='pending': app.pending=True
                elif condition=='running': app.core_paused=False
                elif condition=='busy': app.busy=True
                elif condition=='invalid_profile': app.profile_valid=False
                else: app.event_projects=False
                app._new_project_location=Mock()
                app._change=Mock()
                with patch.object(gui.filedialog,'askopenfilename') as dialog:
                    for method in ('import_project','save_project_from_state','confirm_project_scene','confirm_project_base'):
                        getattr(app,method)()
                app._new_project_location.assert_not_called()
                dialog.assert_not_called()
                app._change.assert_not_called()

    def test_project_tab_scrolls_all_controls_and_wraps_to_available_width(self):
        app=self.app()
        app.project_canvas,app.project_window=Mock(),17
        app.project_canvas.bbox.return_value=(0,0,400,1000)
        app.project_help_label,app.project_status_label,app.project_manual_label=Widget(),Widget(),Widget()
        app._project_resize(types.SimpleNamespace(width=300))
        app.project_canvas.itemconfigure.assert_called_once_with(17,width=300)
        app.project_canvas.configure.assert_called_once_with(scrollregion=(0,0,400,1000))
        self.assertEqual(app.project_help_label.options['wraplength'],276)
        self.assertEqual(app.project_status_label.options['wraplength'],276)
        self.assertEqual(app.project_manual_label.options['wraplength'],252)
        app.closed=True
        app.project_canvas.reset_mock()
        app._project_resize(types.SimpleNamespace(width=100))
        app._project_region()
        app.project_canvas.itemconfigure.assert_not_called()
        app.project_canvas.configure.assert_not_called()


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


class AlternatingAndSlotTests(unittest.TestCase):
    @staticmethod
    def mixed_app():
        app=app_shell({'id':9,'model_id':'car','editable':True,'can_reference':True})
        app.root=Mock()
        app.models={
            'car':dict(id='car',label='Car',kind='independent',type=1,eligible=True),
            'van':dict(id='van',label='Van',kind='independent',type=3,eligible=True),
            'bus':dict(id='bus',label='Bus',kind='independent',type=5,eligible=True),
            'truck':dict(id='truck',label='Cabine',kind='truck',type=4,eligible=True),
            'cargo':dict(id='cargo',label='Carga',kind='trailer',type=11,eligible=False),
            'cold':dict(id='cold',kind='independent',type=1,eligible=False)}
        app.model_choice=Var('Same model as selected')
        app.model_choices={'Same model as selected':None}
        app.mixed_model_ids=['van','car']
        app.mixed_text=Var()
        app.spawn_mode=Var('Alternate models')
        app.spawn_color=Var('Original (0)')
        app.gap,app.count=Var('10'),Var('4')
        app.controller=types.SimpleNamespace(add_mixed_behind=Mock(),add_many_behind=Mock())
        return app

    def test_mixed_selection_preserves_order_and_prunes_unavailable_models(self):
        app=self.mixed_app()
        self.assertEqual([model['id'] for model in app._mixed_candidates()],['car','van','bus'])
        app.mixed_model_ids=['van','truck','car','cold','missing']
        app._refresh_mixed_models()
        self.assertEqual(app.mixed_model_ids,['van','car'])
        self.assertIn('Van → Car → repeats',app.mixed_text.get())
        del app.models['van']
        app._refresh_mixed_models()
        self.assertEqual(app.mixed_model_ids,['car'])

    def test_mixed_dispatch_submits_pattern_once_and_cycles_visuals_only_when_selected(self):
        app=self.mixed_app()
        actions=[]
        app._change=lambda _label,action:actions.append(action)
        app.add_behind()
        self.assertEqual(len(actions),1)
        app.controller.add_mixed_behind.assert_not_called()
        actions.pop()()
        app.controller.add_mixed_behind.assert_called_once_with(9,[dict(model_id='van'),dict(model_id='car')],10.,4)
        app.spawn_color.set('Alternate variants (0–7)')
        app.experimental=Var(True)
        app.count.set('20')
        app.add_behind()
        actions.pop()()
        app.controller.add_mixed_behind.assert_called_with(9,[dict(model_id='van'),dict(model_id='car')],10.,20,
                                                         experimental=True,color_mode='cycle')
        app.controller.add_many_behind.assert_not_called()

    def test_single_model_cycle_uses_existing_batch_api(self):
        app=self.mixed_app()
        app.spawn_mode.set('Single model')
        app.spawn_color.set('Alternate variants (0–7)')
        actions=[]
        app._change=lambda _label,action:actions.append(action)
        app.add_behind()
        actions.pop()()
        app.controller.add_many_behind.assert_called_once_with(9,None,10.,4,secondary_model_id=None,color_mode='cycle')
        app.controller.add_mixed_behind.assert_not_called()

    def test_mixed_bus_spacing_is_validated_for_the_whole_pattern(self):
        app=self.mixed_app()
        app.mixed_model_ids=['car','bus']
        app._change=Mock()
        with patch.object(gui.messagebox,'showinfo') as info:
            app.add_behind()
        self.assertIn('30 and 50',info.call_args.args[1])
        app._change.assert_not_called()
        app.gap.set('30')
        app.add_behind()
        self.assertEqual(app._change.call_count,1)

    def test_invalid_pattern_is_not_silently_changed_to_single_model(self):
        app=self.mixed_app()
        app.mixed_model_ids=['car','missing']
        app._change=Mock()
        with patch.object(gui.messagebox,'showinfo') as info:
            app.add_behind()
        self.assertIn('at least two',info.call_args.args[1])
        app._change.assert_not_called()

    def test_creation_action_cannot_bypass_pause_pending_or_reference_guards(self):
        for blocked in ('running','pending','busy','closed','profile','disconnected','reference'):
            with self.subTest(blocked=blocked):
                app=self.mixed_app()
                if blocked=='running': app.core_paused=False
                elif blocked=='pending': app.pending=True
                elif blocked=='busy': app.busy=True
                elif blocked=='closed': app.closed=True
                elif blocked=='profile': app.profile_valid=False
                elif blocked=='disconnected': app.connected=False
                else: app.selected=lambda:dict(id=9,editable=True,can_reference=False)
                app._change=Mock()
                app.add_behind()
                app._change.assert_not_called()

    def test_stopped_ready_reference_does_not_have_a_separate_gui_speed_gate(self):
        app=self.mixed_app()
        app.selected=lambda:dict(id=9,model_id='car',editable=True,can_reference=True,speed=0,travel_speed=0)
        app._change=Mock()
        app.add_behind()
        self.assertEqual(app._change.call_count,1)

    def test_slot_confirmation_names_exact_files_and_rejects_blocked_or_empty_rows(self):
        row=dict(slot=9,occupied=True,paths=['C:/test/a.p2s','C:/test/nested/a.p2s'])
        text=gui.slot_archive_description(row)
        self.assertIn('slot 9',text)
        self.assertIn('C:/test/a.p2s',text)
        self.assertIn('C:/test/nested/a.p2s',text)
        self.assertIn('verified copy',text)
        for change in (dict(slot=True),dict(slot=10),dict(occupied=False),dict(paths=[]),dict(blocked='Link'),dict(paths=[''])):
            with self.subTest(change=change),self.assertRaises(ValueError):
                gui.slot_archive_description({**row,**change})

    def test_archiving_is_serialized_once_after_confirmation_and_can_be_cancelled(self):
        app=EventProjectTests.app()
        app.controller=types.SimpleNamespace(archive_state_slot=Mock(return_value=dict(message='Arquivado',archive_directory='backup')))
        app._set_status,app._set_core_state=Mock(),Mock()
        jobs=[]
        app._submit=lambda _label,work,done:jobs.append((work,done))
        callback=Mock()
        row=dict(slot=7,occupied=True,paths=['C:/test/save.p2s'])
        with patch.object(gui.messagebox,'askyesno',return_value=False):
            app._archive_slot(row,callback)
        self.assertEqual(jobs,[])
        with patch.object(gui.messagebox,'askyesno',return_value=True) as ask:
            app._archive_slot(row,callback)
        self.assertIn('C:/test/save.p2s',ask.call_args.args[1])
        app.controller.archive_state_slot.assert_not_called()
        self.assertEqual(len(jobs),1)
        work,done=jobs.pop()
        response=work()
        app.controller.archive_state_slot.assert_called_once_with(7)
        callback.assert_not_called()
        done(response)
        callback.assert_called_once_with(response)

    def test_archive_confirmation_cannot_reuse_a_state_that_became_busy(self):
        app=EventProjectTests.app()
        app._slot_job=Mock()
        def changed(*_args,**_kwargs):
            app.busy=True
            return True
        with patch.object(gui.messagebox,'askyesno',side_effect=changed):
            app._archive_slot(dict(slot=2,occupied=True,paths=['saved.p2s']),Mock())
        app._slot_job.assert_not_called()

    def test_slot_failure_reaches_dialog_callback_and_never_retries(self):
        app=EventProjectTests.app()
        app._set_status,app._set_core_state=Mock(),Mock()
        jobs=[]
        app._submit=lambda _label,work,done:jobs.append((work,done))
        action,callback=Mock(side_effect=ValueError('Slot mudou')),Mock()
        app._slot_job('Archiving',action,callback)
        work,done=jobs.pop()
        result=work()
        done(result)
        action.assert_called_once()
        callback.assert_called_once_with(dict(error='Slot mudou'))
        self.assertTrue(app._set_status.call_args.kwargs['warning'])
        app._set_core_state.assert_not_called()

    def test_slot_manager_button_requires_the_same_paused_idle_capability(self):
        for blocked in (None,'running','pending','profile','capability'):
            with self.subTest(blocked=blocked):
                app=EventProjectTests.app()
                app.slot_manager_button=Widget()
                if blocked=='running': app.core_paused=False
                elif blocked=='pending': app.pending=True
                elif blocked=='profile': app.profile_valid=False
                elif blocked=='capability': app.event_projects=False
                app._update_controls()
                self.assertEqual(app.slot_manager_button.options['state'],'normal' if blocked is None else 'disabled')

    def test_selection_distinguishes_position_eligibility_from_creation_reference_reason(self):
        row=dict(id=9,editable=True,can_reference=False,path=2,position=[1,2,3],
                 edit_reason='Lateral movement available.',reference_reason='The node no longer belongs to this vehicle.')
        app=app_shell(row)
        app.selection_text,app.position_text,app.lateral=Var(),Var(),Var(50)
        app._lateral_changed,app._update_secondary_choices,app._update_controls,app._draw_traffic=Mock(),Mock(),Mock(),Mock()
        app._selection_changed()
        self.assertIn('Lateral movement available.',app.position_text.get())
        self.assertIn('Add behind: The node no longer belongs to this vehicle.',app.position_text.get())
        row['can_reference']=True
        app._selection_changed()
        self.assertNotIn('Add behind:',app.position_text.get())


if __name__ == '__main__': unittest.main()
