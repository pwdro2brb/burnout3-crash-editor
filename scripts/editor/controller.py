"""Guarded controller for the experimental USA current-event editor.

Game memory is accessed through loopback PINE. Optional native pause controls
bind to that connection's emulator; state export copies a new emulator save.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import secrets
import struct
import tempfile
import time

from .pine import PineClient, Status, Patch, PineError, PineNotPaused, PineTransportError, PineRemoteError
from . import native_identity, profile, spawncode, routes, speed


class EditorError(ValueError):
    pass


@dataclass
class Pending:
    scratch: bytes
    hook: bytes
    model_id: str
    model_hash: int
    type_code: int
    path: int
    lateral: float
    old_ids: set[int]
    target_ref: dict
    gap: float
    created_key: int
    staged_at: float
    nonce: str


def _word(data: bytes) -> int:
    return int.from_bytes(data, 'little')


def _fingerprint(snapshot) -> str:
    # Recipes intentionally require the same initial state, rather than guessing
    # actor correspondence after restarting/driving through a different event.
    actors = [(i, v['model_id'], v['type'], v['path'], v['progress'],
               v['lateral'], v['position']) for i, v in sorted(snapshot.vehicles.items())]
    data = json.dumps(actors, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(data.encode('utf8')).hexdigest()


def _state_digest(snapshot) -> str:
    """Recovery proof includes anchors/whole records, not only visible XYZ."""
    return hashlib.sha256(snapshot.memory.read_bytes(0x539C10, 0x55B900-0x539C10)
                          + snapshot.memory.read_bytes(0x55D720, 0xE0)).hexdigest()


class EditorController:
    def __init__(self, port: int = 28011, journal_dir: Path | None = None, *, client=None, pause_control=None):
        self.client = client or PineClient(port=port, allow_writes=True)
        self.journal_dir = Path(journal_dir) if journal_dir else None
        self.identity = None
        self.pending: Pending | None = None
        self.unsafe = False
        self.baseline: str | None = None
        self.recipe: list[dict] = []
        self.actor_keys: dict[int, int] = {}
        self.replay_ids: dict[int, int] = {}
        self.replay_queue: list[dict] = []
        self.next_key = 1
        self.recovery_digest: str | None = None
        self.baseline_refs: dict[int, tuple] = {}
        self.journal_warning = False
        self.port = port
        self.pause_control = pause_control
        self.emulator_control = False
        self.completion_tokens: set[int] = set()
        self.physics_history = {}
        self.project: dict | None = None

    def finalize_pending(self):
        self._paused()
        if self.pending:
            pending = self.pending
            try:
                result = self.poll()
            except profile.ProfileError:
                # Explicit user action may release completed owned code even
                # when traffic structures no longer permit alignment.
                if not getattr(pending,'batch',False):
                    raise
                result = {'pending':True,'core_paused':True}
            if (self.pending is not pending or not getattr(pending,'batch',False)
                    or not result.get('pending')):
                return result
            if not hasattr(pending,'probes'):
                # Restored legacy metadata is not in-memory ownership proof;
                # require the canonical payload plus matching local journal.
                from .recovery import finalize_restored
                return finalize_restored(self)
            # A poll may finalize one group and stage the next. Only the same
            # request may be released here, after its native code has retired.
            if (self.client.status() is not Status.PAUSED
                    or self.client.read_many([(p,4) for p in pending.probes]) != [2]*len(pending.probes)
                    or self.client.read_bytes(spawncode.HOOK,8) != spawncode.ORIGINAL
                    or self.client.read_many([(pending.completion_address,4)])[0] != pending.completion_token):
                return result
            self._paused()
            self._cleanup_completed_request(pending,'batch_not_finalized',reason='manual_physics_release')
            return {'pending':False,'core_paused':True,'warning':True,
                'message':'Finished request cleared. The vehicles created by the game were kept; '
                          'alignment and recipe of this batch were not confirmed. The rest of the queue was cancelled.'}
        from .recovery import finalize_restored
        return finalize_restored(self)

    def _journal(self, event: str, **fields):
        if self.journal_dir is None:
            return
        try:
            self.journal_dir.mkdir(parents=True, exist_ok=True)
            row = {'time_utc': datetime.now(timezone.utc).isoformat(), 'event': event, **fields}
            with (self.journal_dir / 'editor-actions.jsonl').open('a', encoding='utf8') as stream:
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
        except OSError:
            # An optional log failure must not turn a confirmed allocation into
            # an apparent failure and invite a duplicate click.
            self.journal_warning = True

    def _identity(self):
        result = self.client.identity()
        serial = ''.join(c for c in result['game_id'].upper() if c.isalnum())
        crc = result['game_crc'].upper().removeprefix('0X')
        if serial != 'SLUS21050' or crc != 'BEBF8793':
            raise EditorError('This editor only accepts Burnout 3 USA, SLUS-21050 / BEBF8793.')
        if '1.7.2521' not in result['version']:
            raise EditorError('This experimental version was prepared for PCSX2 1.7.2521.')
        if self.identity and result != self.identity:
            raise EditorError('The emulator or the game changed. Reconnect before editing.')
        self.identity = result
        return result

    def _control_available(self):
        if self.pause_control is None:
            from .emulator_control import WindowPauseControl
            self.pause_control = WindowPauseControl(self.client,self.port)
        self.emulator_control = self.pause_control.supports()
        return self.emulator_control

    def pause(self):
        self._identity()
        if not self._control_available():
            raise EditorError('The pause button could not find the emulator window of this connection.')
        self.pause_control.set_paused(True)
        result = self.poll() if self.pending else self.refresh()
        result.setdefault('pending', self.pending is not None)
        result.setdefault('message','PCSX2 paused. You can edit the event.')
        result['emulator_control'] = True
        return result

    def export_state(self, destination):
        self._ready()
        if (self.client.read_bytes(spawncode.HOOK,8) != spawncode.ORIGINAL
                or self.client.read_bytes(spawncode.CAVE,4096) not in (bytes(4096),spawncode.clean_batch_scratch())):
            raise EditorError('Finish the creation before saving an edited state.')
        if not self._control_available():
            raise EditorError('Could not identify the portable installation of this connection.')
        from .state_store import export_state
        result = export_state(self.client,self.pause_control.emulator_root(),Path(destination))
        result.update(pending=False,core_paused=self.client.status() is Status.PAUSED)
        self._journal('state_export_finished',path=result['path'],sha256=result['sha256'])
        return result

    def list_state_slots(self):
        self._project_ready()
        from .slot_archive import list_slots
        slots = list_slots(self.pause_control.emulator_root())
        return {'slots':slots,'pending':False,'core_paused':True,
            'message':'Choose a slot to archive. The copies are kept before the slot is freed.'}

    def archive_state_slot(self,slot):
        self._project_ready()
        from .slot_archive import archive_slot
        result = archive_slot(self.pause_control.emulator_root(),slot,guard=self._paused)
        self._journal('state_slot_archived',slot=slot,archive_directory=result['archive_directory'])
        return {**result,'pending':False,'core_paused':self.client.status() is Status.PAUSED}

    def _project_info(self):
        if self.project is None:
            return None
        from .event_project import public_info
        return public_info(self.project)

    def _project_ready(self):
        snap = self._ready()
        if (self.client.read_bytes(spawncode.HOOK,8) != spawncode.ORIGINAL
                or self.client.read_bytes(spawncode.CAVE,4096) not in
                   (bytes(4096),spawncode.clean_batch_scratch())):
            raise EditorError('Finish the pending request before working with the event project.')
        if not self._control_available():
            raise EditorError('The project needs the portable PCSX2 installation of this connection.')
        return snap

    @staticmethod
    def _scene_summary(snap):
        return {'active_objects':len(snap.vehicles),
                'models':sorted({row['model_id'] for row in snap.vehicles.values()}),
                'initialized_objects':sum(bool(row.get('initialized')) for row in snap.vehicles.values())}

    def _reset_scene_tracking(self,snap):
        self.baseline = None
        self.recipe.clear()
        self.actor_keys.clear()
        self.replay_ids.clear()
        self.replay_queue.clear()
        self.baseline_refs.clear()
        self.physics_history.clear()
        self.completion_tokens.clear()
        self.next_key = 1
        self._start_recipe(snap)
        self.recovery_digest = _state_digest(snap)

    def _capture_project_state(self):
        # Preserve a failed capture for inspection. Only a successfully committed
        # project's verified staging copy is removed, never user snapshots.
        folder = Path(tempfile.mkdtemp(prefix='burnout3-event-'))
        source = folder/'capture.p2s'
        try:
            capture = self.export_state(source)
        except Exception as error:
            raise EditorError(f'Could not capture the project. Files already created were kept in {folder}. {error}') from error
        return source,capture

    @staticmethod
    def _remove_project_capture(source,capture):
        from .state_store import _regular_file,_sha256
        try:
            if _regular_file(source) and _sha256(source) == capture['sha256']:
                source.unlink()
                source.parent.rmdir()
        except OSError:
            pass

    @staticmethod
    def _project_destination(directory,name):
        if (not isinstance(name,str) or not name.strip() or len(name.strip()) > 100
                or any(ord(char) < 32 or ord(char) == 127 for char in name)):
            raise EditorError('Enter an event name of up to 100 characters.')
        target = Path(directory)
        if target.exists() or target.is_symlink():
            raise EditorError('Choose a new folder for the project; existing files are kept.')
        return target

    def create_project(self,directory: str,name: str):
        from . import event_project
        snap = self._project_ready()
        target = self._project_destination(directory,name)
        source,capture = self._capture_project_state()
        try:
            project = event_project.create(target,name,source,summary=self._scene_summary(snap),
                                           expected_source_sha256=capture['sha256'])
        except Exception as error:
            raise EditorError(f'The project was not created. The capture was kept in {source}. {error}') from error
        self.project = project
        self._reset_scene_tracking(snap)
        self._remove_project_capture(source,capture)
        self._journal('event_project_created',path=project['path'],name=project['name'])
        return {'pending':False,'core_paused':True,'event_projects':True,'project':self._project_info(),
            'message':'Project created. The base was kept; edit the event and use Test to save the scene and play.'}

    def import_project(self,directory: str,name: str,state_path: str):
        from . import event_project,state_restore
        self._project_ready()
        target = self._project_destination(directory,name)
        verified = state_restore.verify_current_state(self.client,Path(state_path))
        snap = self._snapshot()
        project = event_project.create(target,name,Path(verified['path']),summary=self._scene_summary(snap),
                                       expected_source_sha256=verified['sha256'])
        self.project = project
        self._reset_scene_tracking(snap)
        self._journal('event_project_imported',path=project['path'],sha256=verified['sha256'])
        return {'pending':False,'core_paused':True,'event_projects':True,'project':self._project_info(),
            'message':'Project created from the checked state. The base was copied; the original file was kept.'}

    def _current_project(self):
        if self.project is None:
            raise EditorError('Create or open an event project before saving the scene.')
        from .event_project import load
        current = load(Path(self.project['path']))
        if current['_manifest_sha256'] != self.project['_manifest_sha256']:
            raise EditorError('The project changed in another session. Open it again before saving.')
        return current

    def save_project(self):
        from . import event_project
        snap = self._project_ready()
        # Validate the existing manifest and snapshots before asking the emulator
        # for a new state. save_scene also rejects a concurrent/stale revision.
        self._current_project()
        source,capture = self._capture_project_state()
        try:
            project = event_project.save_scene(self.project,source,summary=self._scene_summary(snap),
                                               expected_source_sha256=capture['sha256'])
        except Exception as error:
            raise EditorError(f'The scene was not recorded in the project. The capture was kept in {source}. {error}') from error
        self.project = project
        self._remove_project_capture(source,capture)
        self._journal('event_project_saved',path=project['path'],scene=project['scene'])
        return {'pending':False,'core_paused':True,'event_projects':True,'project':self._project_info(),
            'message':'Event scene saved and verified. Back to start will restore this version.'}

    def save_project_from_state(self,state_path: str):
        from . import event_project,state_restore
        self._project_ready()
        self._current_project()
        verified = state_restore.verify_current_state(self.client,Path(state_path))
        snap = self._snapshot()
        project = event_project.save_scene(self.project,Path(verified['path']),summary=self._scene_summary(snap),
                                           expected_source_sha256=verified['sha256'])
        self.project = project
        self._journal('event_project_scene_imported',path=project['path'],sha256=verified['sha256'])
        return {'pending':False,'core_paused':True,'event_projects':True,'project':self._project_info(),
            'message':'Scene saved to the project from the checked state. The chosen file was kept.'}

    def confirm_project(self,path: str,*,base=False):
        if type(base) is not bool:
            raise EditorError("Choose the saved scene or the project's original base.")
        from . import event_project,state_restore
        self._project_ready()
        project = event_project.load(Path(path))
        source = Path(project['base_path'] if base else project['scene_path'])
        verified = state_restore.verify_current_state(self.client,source,
            expected_sha256=project['base' if base else 'scene']['sha256'])
        snap = self._snapshot()
        self._reset_scene_tracking(snap)
        self.project = project
        self._journal('event_project_manual_state_confirmed',path=project['path'],base=base,sha256=verified['sha256'])
        return {'pending':False,'core_paused':True,'event_projects':True,'project':self._project_info(),
            'message':('Base loaded from the menu checked. The project is ready to edit.' if base else
                       'Scene loaded from the menu checked. The project is ready to edit or test.')}

    def test_project(self):
        saved = self.save_project()
        try:
            result = self.resume()
        except Exception as error:
            try:
                paused = self.client.status() is Status.PAUSED
            except PineError:
                paused = None
            return {**saved,'core_paused':paused,'warning':True,
                'message':f'The scene was saved, but resuming could not be confirmed. {error}'}
        return {**saved,**result,'project':self._project_info(),
            'message':'Scene saved and PCSX2 resumed. To repeat, pause and use Back to start.'}

    def _restore_project(self,project,*,base=False):
        from . import state_restore
        snap = self._project_ready()
        self.recovery_digest = _state_digest(snap)
        source = Path(project['base_path'] if base else project['scene_path'])
        try:
            restored = state_restore.restore_state(self.client,self.pause_control.emulator_root(),source,
                expected_sha256=project['base' if base else 'scene']['sha256'])
        except state_restore.RestoreError as error:
            if error.uncertain:
                self.unsafe = True
                self._journal('event_project_restore_unconfirmed',path=project['path'],base=base)
            raise EditorError(str(error)) from error
        try:
            self._identity()
            loaded = self._snapshot()
            self._reset_scene_tracking(loaded)
        except Exception as error:
            self.unsafe = True
            self._journal('event_project_restore_profile_rejected',path=project['path'],base=base)
            raise EditorError('The state was loaded, but the profile did not confirm an editable scene. '
                              'Reload a clean reference before editing.') from error
        self.project = project
        self._journal('event_project_restored',path=project['path'],base=base,sha256=restored['sha256'])
        return {**restored,'pending':False,'core_paused':True,'event_projects':True,
            'project':self._project_info(),
            'message':("Original base restored and checked. The project's saved scene was kept." if base else
                       'Saved scene restored and checked. You can edit or resume to repeat the event.')}

    def open_project(self,path: str):
        from .event_project import load
        return self._restore_project(load(Path(path)))

    def restart_project(self):
        if self.project is None:
            raise EditorError('Create or open a project before going back to start.')
        from .event_project import load
        return self._restore_project(load(Path(self.project['path'])))

    def restore_project_base(self):
        if self.project is None:
            raise EditorError('Create or open a project before restoring the base.')
        from .event_project import load
        return self._restore_project(load(Path(self.project['path'])),base=True)

    def resume(self):
        self._identity()
        if not self._control_available():
            raise EditorError('The resume button could not find the emulator window of this connection.')
        self.pause_control.set_paused(False)
        return {'pending':self.pending is not None,'core_paused':False,'emulator_control':True,
                'message':'PCSX2 retomado. '+('Pause again to finish the batch before driving.'
                                             if self.pending else 'You can test the event.')}

    def _paused(self):
        self._identity()
        if self.client.status() is not Status.PAUSED:
            raise EditorError('Use Pause PCSX2 in the editor or System → Pause in the emulator before editing.')
        if self.unsafe:
            raise EditorError('The last write could not be confirmed. Reload a clean state and reconnect.')

    def _snapshot(self, *, pending=False):
        self._paused()
        try:
            return profile.snapshot(self.client, require_paused=True, allow_editor_hook=pending)
        except profile.ProfileError as error:
            # Keep a bounded, read-only explanation of a rejection. An unknown
            # hook must not be treated as pool exhaustion or silently restored.
            details = {'message': str(error), 'pending_request': self.pending is not None}
            try:
                details.update(core_status=int(self.client.status()),
                    epilogue_hex=self.client.read_bytes(profile.EPILOGUE, 8).hex(),
                    probe_hex=self.client.read_bytes(spawncode.DATA, 12).hex(),
                    request_marker_hex=self.client.read_bytes(spawncode.MAGIC_ADDRESS, 24).hex())
            except PineError as diagnostic_error:
                details['diagnostic_error'] = type(diagnostic_error).__name__
            self._journal('profile_rejected', **details)
            raise

    def connect(self):
        try:
            self.client.connect()
            identity = self._identity()
        except PineTransportError:
            raise EditorError('Could not connect. Open the test session with PINE enabled and load the game.')
        except PineRemoteError:
            raise EditorError('The emulator has not made the game available yet. Finish loading and try again.')
        if self.unsafe:
            # Recovery never guesses whether an ambiguous allocation ran.
            clean = (self.client.read_bytes(spawncode.HOOK, 8) == spawncode.ORIGINAL
                     and self.client.read_bytes(spawncode.CAVE, 4096) in (bytes(4096),spawncode.clean_batch_scratch()))
            if not clean:
                raise EditorError('Reload a state without a pending edit before reconnecting.')
            if self.client.status() is not Status.PAUSED:
                raise EditorError('Pause PCSX2 after reloading the reference state.')
            recovered = profile.snapshot(self.client, require_paused=True)
            if not self.recovery_digest or _state_digest(recovered) != self.recovery_digest:
                raise EditorError('The previous reference was not recovered. Reload it and reopen the editor.')
            self.pending = None
            self.replay_queue.clear()
            self.unsafe = False
        if self.pending is None:
            self.physics_history.clear()
            self.baseline = None
            self.recipe.clear()
            self.actor_keys.clear()
            self.replay_ids.clear()
            self.baseline_refs.clear()
            self.replay_queue.clear()
        paused = self.client.status() is Status.PAUSED
        result = {'status': 'Connected. Pause PCSX2 to list and edit the vehicles.',
                  'game': 'Burnout 3 USA', 'profile': 'SLUS-21050',
                  'core_paused': paused, 'pending': self.pending is not None, **identity}
        # Fake/in-memory clients used by offline tools never resolve native UI.
        if self.pause_control is not None or type(self.client) is PineClient:
            result['emulator_control'] = self._control_available()
            result['state_export'] = result['emulator_control']
            result['event_projects'] = result['emulator_control']
        result['project'] = self._project_info()
        if paused and self.pending is None:
            try:
                result.update(self.refresh())
            except profile.ProfileError as error:
                result.update(profile_valid=False,vehicles=[],models=[],warning=True,
                    message=f'{error} Use Finish pending request to check an old request; '
                            'if it is not recognized, reload a clean state.')
        return result

    def refresh(self):
        if self.pending:
            return self.poll()
        self._identity()
        if self.client.status() is not Status.PAUSED:
            return {'status': 'Use Pause PCSX2 to refresh the list.', 'core_paused': False}
        snap = self._snapshot()
        public = snap.public()
        for row in public['vehicles']:
            info = speed.summarize(snap.vehicles[row['id']])
            row.update(speed_info=info,can_set_speed=info['can_set_speed'])
        public['routes'] = routes.build_network(snap)
        public['native_identity'] = native_identity.read_identity(snap.memory)
        if self.client.status() is not Status.PAUSED:
            return {'status':'PCSX2 was resumed during the read. Pause and refresh again.',
                    'core_paused':False,'pending':False}
        history = {(i,v['model_hash'],v['node'],v['type']):v['initialized'] for i,v in snap.vehicles.items()}
        lost = sum(not ready and self.physics_history.get(key,False) for key,ready in history.items())
        self.physics_history = history
        capacity = dict(snap.inspection['counts'])
        capacity.update(initialized_objects=sum(v['initialized'] for v in snap.vehicles.values()),
            queued_operations=len(self.replay_queue),
            physics_warning=(f'{lost} vehicle(s) no longer have initialized physics in this reference.' if lost else ''))
        return {**public,'pending':False,'capacity':capacity,'project':self._project_info()}

    @staticmethod
    def _selected(snap, vehicle_id, *, experimental=False):
        if type(vehicle_id) is not int or vehicle_id not in snap.vehicles:
            raise EditorError('Select an active vehicle in the refreshed list.')
        row = snap.vehicles[vehicle_id]
        if not row.get('editable', False) and not (experimental and profile.can_move_experimental(snap.vehicles,row)):
            raise EditorError('Choose an independent car or van whose physics is already initialized.')
        return row

    def _ready(self):
        if self.pending:
            raise EditorError('Finish the pending creation before starting another edit.')
        return self._snapshot()

    def _start_recipe(self, snap):
        if self.baseline is None:
            self.baseline = _fingerprint(snap)
            self.baseline_refs = {i:(v['model_id'],v['path']) for i,v in snap.vehicles.items()}

    def _reference(self, row):
        if row['id'] in self.actor_keys:
            return {'kind': 'created', 'key': self.actor_keys[row['id']]}
        if self.baseline_refs.get(row['id']) != (row['model_id'],row['path']):
            # Late natural traffic and native allocations whose alignment was
            # not confirmed can still be edited after normal live validation.
            # Their appearance cannot be replayed from our original baseline.
            return {'kind':'observed','id':row['id'],'model_id':row['model_id'],'path':row['path']}
        return {'kind': 'initial', 'id': row['id'], 'model_id': row['model_id'], 'path': row['path']}

    def _resolve(self, reference, snap, *, for_creation=False, experimental=False, for_speed=False):
        if for_speed:
            select = self._speed_selected
        elif for_creation:
            from .batch import reference as select
        else:
            select = lambda state, index: self._selected(state,index,experimental=experimental)
        if reference.get('kind') == 'created':
            vehicle_id = self.replay_ids.get(reference.get('key'))
        elif reference.get('kind') == 'initial':
            vehicle_id = reference.get('id')
            row = select(snap, vehicle_id)
            if row['model_id'] != reference.get('model_id') or row['path'] != reference.get('path'):
                raise EditorError("The preset's vehicle does not match the current event.")
        else:
            raise EditorError('Invalid vehicle reference in the preset.')
        select(snap, vehicle_id)
        return vehicle_id

    @staticmethod
    def _speed_selected(snap,vehicle_id):
        row = snap.vehicles.get(vehicle_id) if type(vehicle_id) is int else None
        if row is None or not speed.can_set_speed(row):
            raise EditorError('Select a vehicle or cab whose speed control is ready.')
        return row

    def set_speed(self,vehicle_id,value,*,experimental=False):
        return self.set_speeds([vehicle_id],value,experimental=experimental)

    def set_speeds(self,vehicle_ids,value,*,experimental=False):
        snap = self._ready()
        patches = speed.patches_many(snap,vehicle_ids,value,experimental=experimental)
        rows = [self._speed_selected(snap,index) for index in vehicle_ids]
        control = speed.validate_control(value,experimental=experimental)
        self._start_recipe(snap)
        targets = [self._reference(row) for row in rows]
        self.recovery_digest = _state_digest(snap)
        try:
            # PINE preflights all expected words. A transport/write failure can
            # still be partial, so it always blocks further edits until recovery.
            self.client.apply_patch(patches)
        except PineError as error:
            self.unsafe = True
            self._journal('speed_unconfirmed',vehicle_ids=list(vehicle_ids))
            raise EditorError('The speeds could not be confirmed. Reload a clean reference before repeating.') from error
        for row,target in zip(rows,targets):
            operation = dict(op='set_speed',target=target,control_value=control)
            if experimental:
                operation['experimental'] = True
            self.recipe.append(operation)
            self._journal('set_speed',vehicle_id=row['id'],operation=operation,
                previous_control=row['speed'],previous_advance=row['travel_speed'])
        return {'pending':False,'core_paused':True,
            'message':f'Target speed updated on {len(rows)} vehicle(s). '
                      'When resumed, the game recomputes progress according to traffic.'}

    def move(self, vehicle_id: int, lateral_percent: float, *, experimental=False):
        if type(experimental) is not bool:
            raise EditorError('Invalid experimental mode.')
        snap = self._ready()
        row = self._selected(snap, vehicle_id,experimental=experimental)
        patches = profile.lateral_patches(snap, vehicle_id, lateral_percent,**({'experimental':True} if experimental else {}))
        self._start_recipe(snap)
        reference = self._reference(row)
        self.recovery_digest = _state_digest(snap)
        try:
            self.client.apply_patch(patches)
        except PineError:
            self.unsafe = True
            raise EditorError('The position could not be confirmed. Reload a clean state before repeating.')
        operation = {'op': 'move_lateral', 'target': reference,
                     'lateral_percent': float(lateral_percent)}
        if experimental:
            operation['experimental'] = True
        self.recipe.append(operation)
        self._journal('move', vehicle_id=vehicle_id, operation=operation)
        return {'message': 'Position applied. Resume the game with Esc to check it.',
                'core_paused': True, 'pending': False}

    def add_behind(self, vehicle_id: int, model_id: str | None, gap: float):
        return self.add_many_behind(vehicle_id, model_id, gap, 1)

    def add_many_behind(self, vehicle_id, model_id, gap, count, secondary_model_id=None, *, experimental=False,
                        color_mode='original'):
        if color_mode != 'original':
            return self.add_mixed_behind(vehicle_id,[dict(model_id=model_id,secondary_model_id=secondary_model_id)],
                gap,count,experimental=experimental,color_mode=color_mode)
        if (type(experimental) is not bool or type(count) is not int
                or not 1 <= count <= (253 if experimental else 8)):
            raise EditorError('Use an amount from 1 to 8, or enable experimental mode to ask for up to the traffic capacity.')
        from . import batch
        options = {'experimental':True} if experimental else {}
        if count > 8:
            options['reserve_count'] = count
        result = batch.stage(self,vehicle_id,model_id,gap,min(count,8),secondary_model_id,**options)
        if count > 8:
            pending = self.pending
            first_key = pending.created_keys[-1]
            self.replay_queue.extend(dict(op='add_behind',target={'kind':'created','key':first_key+i},
                model_id=pending.model_id,gap=float(gap),created_key=first_key+i+1,experimental=True,
                **({'secondary_model_id':secondary_model_id} if secondary_model_id is not None else {}))
                for i in range(count-8))
            result['message'] += f' Queue: {count-8} left, in groups of up to eight; resume and pause for each group.'
        return result

    def add_mixed_behind(self,vehicle_id,choices,gap,count,*,experimental=False,color_mode='original'):
        if (type(experimental) is not bool or type(count) is not int
                or not 1 <= count <= (253 if experimental else 8)):
            raise EditorError('Use an amount from 1 to 8, or enable experimental mode to ask for up to the traffic capacity.')
        if color_mode not in ('original','cycle'):
            raise EditorError('Choose the original look or alternating visual variants.')
        if (type(choices) not in (list,tuple) or not 1 <= len(choices) <= 12
                or any(not isinstance(item,dict) or set(item)-{'model_id','secondary_model_id'} for item in choices)):
            raise EditorError('Choose 1 to 12 loaded models for the alternating sequence.')
        from . import batch
        snap = self._ready()
        target = batch.reference(snap,vehicle_id)
        prepared = []
        for choice in choices:
            model_id = choice.get('model_id') or target['model_id']
            secondary = choice.get('secondary_model_id')
            batch.model_pair(snap,model_id,secondary)
            prepared.append(dict(model_id=model_id,secondary_model_id=secondary))
        items = [{**prepared[index%len(prepared)],'variant':index%8 if color_mode == 'cycle' else 0}
                 for index in range(count)]
        options = dict(experimental=experimental,spawn_items=items[:8],reserve_items=items,reserve_count=count)
        result = batch.stage(self,vehicle_id,items[0]['model_id'],gap,min(count,8),
            items[0]['secondary_model_id'],**options)
        if count > 8:
            first_key = self.pending.created_keys[-1]
            for offset,item in enumerate(items[8:]):
                operation = dict(op='add_behind',target={'kind':'created','key':first_key+offset},
                    model_id=item['model_id'],gap=float(gap),created_key=first_key+offset+1,experimental=True)
                if item['secondary_model_id'] is not None:
                    operation['secondary_model_id'] = item['secondary_model_id']
                if item['variant']:
                    operation['variant'] = item['variant']
                self.replay_queue.append(operation)
            result['message'] += f' Alternating queue: {count-8} left; resume and pause for each group.'
        if color_mode == 'cycle':
            result['message'] += ' Visual variants 0–7: the effect on colour depends on the model and still needs confirmation.'
        return result

    def add_at(self, vehicle_id, model_id, x, z, secondary_model_id=None, *, experimental=False):
        from . import batch
        return batch.stage(self,vehicle_id,model_id,10,1,secondary_model_id,
                           experimental=experimental,at_point=(x,z))

    def cancel_queue(self):
        count = len(self.replay_queue)
        self.replay_queue.clear()
        self._journal('queue_cancelled',remaining=count)
        return {'pending':self.pending is not None,'core_paused':self.client.status() is Status.PAUSED,
                'message':f'Queue cancelled ({count} operations). '+
                    ('Finish the batch already prepared; it will not be repeated.' if self.pending else 'No creation was repeated.')}

    def _add_behind(self, vehicle_id, model_id, gap, *, created_key=None):
        snap = self._ready()
        target = self._selected(snap, vehicle_id)
        if not isinstance(gap, (int, float)) or isinstance(gap, bool) or not math.isfinite(gap) or not 8 <= gap <= 50:
            raise EditorError('Use a distance between 8 and 50 game units.')
        model_id = model_id or target['model_id']
        model = snap.models.get(model_id)
        if not model or not model.get('eligible') or model.get('type') not in (1, 2):
            raise EditorError('Choose a loaded car or van that is compatible with this version.')
        if snap.memory.u8(0x527440 + 0x363BE):
            raise EditorError('The game is blocking new instances right now.')
        if snap.inspection['counts']['free_objects'] < 2 or snap.inspection['counts']['free_nodes'] < 1:
            raise EditorError('There is not enough free space for another vehicle.')
        progression = profile.behind_progress(snap.memory, target['path'], target['progress'],
                                             target['lateral'], float(gap), node=target['node'])
        candidate = profile.lane(snap.memory, target['path'], progression, target['lateral'])['point']
        origin = profile.lane(snap.memory, target['path'], target['progress'], target['lateral'])['point']
        center = [candidate[k] + target['position'][k] - origin[k] for k in range(3)]
        for peer_id, peer in snap.vehicles.items():
            if peer_id != vehicle_id and peer.get('independent') and peer.get('initialized') and peer['path'] == target['path']:
                if math.dist(center, peer['position']) < 6:
                    raise EditorError('That stretch already has a vehicle. Increase the distance or choose another target.')
        if self.client.read_bytes(spawncode.HOOK, 8) != spawncode.ORIGINAL:
            raise EditorError("The event's code changed. Reload a clean state.")
        if self.client.read_bytes(spawncode.CAVE, 4096) != bytes(4096):
            raise EditorError('There is an unfinished edit in memory. Reload a clean state.')
        key = self.next_key if created_key is None else created_key
        if type(key) is not int or not 1 <= key <= 10000:
            raise EditorError('Invalid creation identifier.')
        self.next_key = max(self.next_key, key + 1)
        nonce = secrets.token_hex(16)
        payload = spawncode.build_spawn(manager=0x527440, type_code=model['type'],
            model_hash=model['model_hash'], path_descriptor=0x52288C + target['path'] * 0x4C,
            progression=progression, speed=snap.memory.read(target['node'], '<f')[0],
            spacing=snap.memory.read(target['node'] + 0x24, '<f')[0], variant=0,
            nonce=bytes.fromhex(nonce))
        self._start_recipe(snap)
        self.recovery_digest = _state_digest(snap)
        self.pending = Pending(payload['scratch_bytes'], payload['hook_bytes'], model_id,
            model['model_hash'], model['type'], target['path'], target['lateral'],
            set(snap.vehicles), self._reference(target), float(gap), key, time.monotonic(), nonce)
        try:
            # The code/data area is prepared and read back before the jump is installed.
            self.client.write_bytes(spawncode.CAVE, payload['scratch_bytes'])
            if self.client.read_bytes(spawncode.CAVE, 4096) != payload['scratch_bytes']:
                raise EditorError('The creation setup did not check out.')
            self.client.apply_patch([
                Patch(spawncode.HOOK, 4, _word(spawncode.ORIGINAL[:4]), _word(payload['hook_bytes'][:4])),
                Patch(spawncode.HOOK+4, 4, _word(spawncode.ORIGINAL[4:]), _word(payload['hook_bytes'][4:]))])
        except Exception:
            self.unsafe = True
            self._journal('stage_unconfirmed', nonce=nonce)
            raise EditorError('The setup could not be confirmed. Reload a clean state before repeating.')
        self._journal('spawn_staged', nonce=nonce, model_id=model_id, gap=float(gap),
                      path=target['path'], progression=progression)
        return {'pending': True, 'core_paused': True,
                'message': 'Prepared. Resume the emulator with Esc, then pause again with Esc to finish.'}

    @staticmethod
    def _validate_pending_bytes(pending: Pending, live_hook: bytes, live_scratch: bytes):
        """Accept only this request's hook and immutable code/data/nonce bytes."""
        if live_hook not in getattr(pending,'allowed_hooks',(pending.hook,)):
            raise EditorError('The code changed during the creation. Reload a clean state before continuing.')
        if len(live_scratch) != len(pending.scratch):
            raise EditorError('The work area read was incomplete. No cleanup was applied.')
        expected = bytearray(pending.scratch)
        probe = spawncode.DATA - spawncode.CAVE
        # The routine changes only these three publication words. The nonce,
        # signature, instructions and constructor arguments must remain exact.
        offsets = getattr(pending, 'probe_offsets', (probe,probe+4,probe+8))
        for offset in offsets:
            expected[offset:offset+4] = live_scratch[offset:offset+4]
        if bytes(expected) != live_scratch:
            raise EditorError('The work area changed unexpectedly. It was not cleaned automatically.')

    def _check_pending(self, pending: Pending):
        hook = self.client.read_bytes(spawncode.HOOK,8)
        self._validate_pending_bytes(pending,
            hook,
            self.client.read_bytes(spawncode.CAVE, 4096))
        if (getattr(pending,'batch',False) and (hook != spawncode.ORIGINAL
                or self.client.read_many([(pending.completion_address,4)])[0] != pending.completion_token)):
            raise EditorError('The batch routine has not finished yet. Resume briefly and pause.')

    def _clean(self, pending: Pending):
        # Re-read after alignment; never clean an area changed since preflight.
        self._check_pending(pending)
        if getattr(pending,'batch',False):
            # DONE is published only after leaving removable code, with the
            # original entry restored. Retain the permanent landing in case
            # the paused EE has not executed its final jump yet.
            if (self.client.read_bytes(spawncode.HOOK,8) != spawncode.ORIGINAL
                    or self.client.read_many([(pending.completion_address,4)])[0] != pending.completion_token):
                raise EditorError('The batch routine has not finished yet. Resume briefly and pause.')
            self.client.write_bytes(spawncode.CAVE,pending.clean_scratch)
            if self.client.read_bytes(spawncode.CAVE,4096) != pending.clean_scratch:
                raise EditorError('The work area cleanup did not check out.')
            return
        self.client.apply_patch([
            Patch(spawncode.HOOK+4, 4, _word(pending.hook[4:]), _word(spawncode.ORIGINAL[4:])),
            Patch(spawncode.HOOK, 4, _word(pending.hook[:4]), _word(spawncode.ORIGINAL[:4]))])
        self.client.write_bytes(spawncode.CAVE, bytes(4096))
        if self.client.read_bytes(spawncode.CAVE, 4096) != bytes(4096):
            raise EditorError('The work area cleanup did not check out.')

    def _cleanup_completed_request(self, pending: Pending, event: str, **fields):
        """Remove only our completed request; never repair or move its actor."""
        try:
            self._clean(pending)
        except Exception:
            self.unsafe = True
            self._journal('cleanup_unconfirmed', nonce=pending.nonce, **fields)
            raise EditorError('The cleanup could not be confirmed. Reload a clean state before continuing.')
        self.pending = None
        self.replay_queue.clear()
        self._journal(event, nonce=pending.nonce, **fields)

    def poll(self):
        pending = self.pending
        if getattr(pending, 'batch', False):
            from . import batch
            return batch.poll(self)
        if pending is None:
            return {'pending': False, 'message': 'No pending creation.',
                    'core_paused': self.client.status() is Status.PAUSED}
        if self.unsafe:
            raise EditorError('Reload a clean state and reconnect; the previous operation will not be repeated.')
        self._identity()
        state = self.client.status()
        if state is Status.SHUTDOWN:
            raise EditorError('The game was closed. The creation will not be repeated automatically.')
        flag, object_ptr, node_ptr = self.client.read_many([(spawncode.DATA+i, 4) for i in (0,4,8)])
        waiting_message = ('Waiting for the traffic update. Resume PCSX2 and, '
                           'if it is at Continue/menu, start the event.')
        if state is not Status.PAUSED:
            message = ('Vehicle created. Pause PCSX2 now to finish before driving.' if flag == 2
                       else waiting_message)
            return {'pending': True, 'message': message, 'core_paused': False}
        live_hook = self.client.read_bytes(spawncode.HOOK, 8)
        scratch = self.client.read_bytes(spawncode.CAVE, 4096)
        if live_hook == spawncode.ORIGINAL and scratch == bytes(4096):
            self.pending = None
            self.replay_queue.clear()
            self._journal('spawn_interrupted', nonce=pending.nonce)
            return {'pending': False, 'core_paused': True,
                    'message': 'The state was reloaded. The pending creation was cancelled, without automatic repetition.'}
        self._validate_pending_bytes(pending, live_hook, scratch)
        if flag != 2:
            return {'pending': True, 'core_paused': True,
                    'message': waiting_message}
        if object_ptr == 0:
            self._cleanup_completed_request(pending, 'spawn_refused',
                reason='allocator_returned_null', object_pointer=object_ptr, node_pointer=node_ptr)
            raise EditorError('The game refused to create the vehicle. The temporary edit was removed.')
        snap = self._snapshot(pending=True)
        new_id = (object_ptr - 0x539C10) // 0x180
        row = snap.vehicles.get(new_id)
        mismatch = None
        if object_ptr != 0x539C10 + new_id*0x180:
            mismatch = 'unaligned_object_pointer'
        elif new_id in pending.old_ids:
            mismatch = 'previously_active_object'
        elif not row:
            mismatch = 'object_no_longer_active'
        elif row['node'] != node_ptr:
            mismatch = 'node_changed'
        elif row['model_hash'] != pending.model_hash:
            mismatch = 'model_changed'
        elif row['path'] != pending.path:
            mismatch = 'path_changed'
        elif row['type'] != pending.type_code:
            mismatch = 'type_changed'
        elif not row['independent']:
            mismatch = 'object_no_longer_independent'
        if mismatch:
            self._cleanup_completed_request(pending, 'spawn_not_finalized', reason=mismatch,
                object_pointer=object_ptr, node_pointer=node_ptr)
            return {'pending': False, 'core_paused': True, 'warning': True,
                    'message': 'Creation ran, but the vehicle changed or left the scene. '
                               'Temporary code removed. Alignment not confirmed.'}
        if not row['initialized']:
            return {'pending': True, 'core_paused': True,
                    'message': 'Physics is still initializing. Resume for a moment and pause again.'}
        # Snapshot reads take time: confirm the request again before touching
        # even the newly created actor, not only before restoring the hook.
        self._check_pending(pending)
        try:
            self.client.apply_patch(profile.lateral_patches(snap, new_id, pending.lateral * 100))
            self._clean(pending)
        except Exception:
            self.unsafe = True
            self._journal('finalize_unconfirmed', nonce=pending.nonce)
            raise EditorError('The finish could not be confirmed. Reload a clean state before repeating.')
        self.pending = None
        self.actor_keys[new_id] = pending.created_key
        self.replay_ids[pending.created_key] = new_id
        operation = {'op': 'add_behind', 'target': pending.target_ref, 'model_id': pending.model_id,
                     'gap': pending.gap, 'created_key': pending.created_key}
        self.recipe.append(operation)
        self._journal('spawn_finished', nonce=pending.nonce, new_vehicle_id=new_id, operation=operation)
        if self.replay_queue:
            result = self._continue_recipe()
            result.setdefault('new_vehicle_id', new_id)
            return result
        return {'pending': False, 'core_paused': True, 'new_vehicle_id': new_id,
                'message': 'Vehicle added and edit finished. Resume with Esc to test.'}

    def save_preset(self, path: str):
        if self.pending or not self.recipe or not self.baseline:
            raise EditorError('Finish at least one edit before saving a preset.')
        if any(op.get('target',{}).get('kind') == 'observed' for op in self.recipe):
            raise EditorError('Some edits are on vehicles that appeared after the initial reference and cannot be '
                              'recreated by this recipe. Use Save state… (.p2s) to keep the scene, '
                              'or reconnect to start a recipe with the current scene.')
        destination = Path(path)
        payload = {'format': 'burnout3-current-event-recipe', 'version': 1,
                   'profile': 'SLUS-21050/BEBF8793', 'baseline': self.baseline,
                   'operations': self.recipe}
        text = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
        if len(text.encode('utf8')) > 131072 or len(self.recipe) > 256:
            raise EditorError('The preset exceeds the limit of this version.')
        destination.write_text(text, encoding='utf8')
        return {'message': 'Preset saved. It needs the same initial state to be reapplied.'}

    def load_preset(self, path: str, *, experimental=False):
        if type(experimental) is not bool:
            raise EditorError('Invalid experimental mode.')
        allow_experimental = experimental
        snap = self._ready()
        source = Path(path)
        if source.stat().st_size > 131072:
            raise EditorError('Preset grande demais.')
        try:
            data = json.loads(source.read_text(encoding='utf8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise EditorError('The file does not contain a valid JSON preset.')
        if (not isinstance(data, dict) or data.get('format') != 'burnout3-current-event-recipe'
                or type(data.get('version')) is not int or data.get('version') != 1
                or data.get('profile') != 'SLUS-21050/BEBF8793'):
            raise EditorError('Incompatible preset format.')
        if data.get('baseline') != _fingerprint(snap):
            raise EditorError('Reload the same initial state used to create this preset.')
        operations = data.get('operations')
        if not isinstance(operations, list) or not 1 <= len(operations) <= 256:
            raise EditorError('Invalid list of operations.')
        # Validate every operation before making the first mutation.
        created = set()
        created_models = {}
        for op in operations:
            if not isinstance(op, dict) or op.get('op') not in ('move_lateral','add_behind','add_at','set_speed'):
                raise EditorError('Operation not supported in the preset.')
            experimental = op.get('experimental',False)
            if type(experimental) is not bool:
                raise EditorError('Invalid experimental mode in the preset.')
            if experimental and not allow_experimental:
                raise EditorError('This recipe uses experimental mode. Enable the mode and read the warning before loading it.')
            ref = op.get('target')
            if not isinstance(ref, dict): raise EditorError('Invalid target in the preset.')
            if ref.get('kind') == 'created':
                if type(ref.get('key')) is not int or ref.get('key') not in created:
                    raise EditorError('Reference out of order in the preset.')
            else:
                self._resolve(ref,snap,for_creation=op['op'] in ('add_behind','add_at'),
                    experimental=experimental,for_speed=op['op']=='set_speed')
            if op['op'] == 'set_speed':
                try:
                    speed.validate_control(op.get('control_value'),experimental=experimental)
                except profile.ProfileError as error:
                    raise EditorError(f'Invalid speed in the preset: {error}') from error
            elif op['op'] == 'move_lateral':
                value = op.get('lateral_percent')
                if (type(value) not in (int,float) or not math.isfinite(value)
                        or (not experimental and not 0 <= value <= 100)):
                    raise EditorError('Invalid position in the preset.')
                try:
                    profile._lane_fraction_word(value/100)
                except profile.ProfileError as error:
                    raise EditorError('Position outside the float32 range in the preset.') from error
            else:
                model_id = op.get('model_id')
                if type(op.get('variant',0)) is not int or not 0 <= op.get('variant',0) <= 7:
                    raise EditorError('Invalid visual variant in the preset.')
                if not isinstance(model_id, str): raise EditorError('Invalid model in the preset.')
                model = snap.models.get(model_id)
                from .batch import model_pair
                _primary, secondary = model_pair(snap,model_id,op.get('secondary_model_id'))
                gap, key = op.get('gap'), op.get('created_key')
                reference_is_truck = (snap.models.get(created_models.get(ref.get('key')),{}).get('type') in (4,5)
                    if ref.get('kind') == 'created' else
                    (snap.vehicles[ref['id']].get('native_pair_valid',False)
                     or snap.vehicles[ref['id']].get('type') == 5))
                if (op['op'] == 'add_behind' and not experimental and
                        (secondary is not None or reference_is_truck or model.get('type') == 5)
                        and (type(gap) not in (int,float) or gap < 30)):
                    raise EditorError('Use a distance of 30 to 50 units for buses or cab-and-trailer sets.')
                if (not model or not model.get('eligible') or type(key) is not int
                        or not 1 <= key <= 10000 or key in created):
                    raise EditorError('Invalid creation in the preset.')
                if op['op'] == 'add_behind':
                    if (type(gap) not in (int,float) or not math.isfinite(gap)
                            or (gap <= 0 if experimental else not 8 <= gap <= 50)):
                        raise EditorError('Invalid distance in the preset.')
                else:
                    for axis in ('x','z'):
                        coordinate = op.get(axis)
                        if type(coordinate) not in (int,float) or not math.isfinite(coordinate):
                            raise EditorError('Invalid point in the preset.')
                        try:
                            valid = math.isfinite(struct.unpack('<f',struct.pack('<f',coordinate))[0])
                        except (OverflowError,struct.error):
                            valid = False
                        if not valid:
                            raise EditorError('Point outside the float32 range in the preset.')
                created.add(key)
                created_models[key] = model_id
        self.recipe.clear()
        self.actor_keys.clear()
        self.replay_ids.clear()
        self.baseline = data['baseline']
        self.baseline_refs = {i:(v['model_id'],v['path']) for i,v in snap.vehicles.items()}
        self.replay_queue = list(operations)
        return self._continue_recipe()

    def _continue_recipe(self):
        while self.replay_queue:
            op = self.replay_queue.pop(0)
            snap = self._snapshot()
            experimental = op.get('experimental',False)
            vehicle_id = self._resolve(op['target'],snap,
                for_creation=op['op'] in ('add_behind','add_at'),experimental=experimental,
                for_speed=op['op']=='set_speed')
            if op['op'] == 'set_speed':
                self.set_speed(vehicle_id,op['control_value'],**({'experimental':True} if experimental else {}))
            elif op['op'] == 'move_lateral':
                self.move(vehicle_id,op['lateral_percent'],**({'experimental':True} if experimental else {}))
            elif op['op'] == 'add_at':
                from .batch import stage
                return stage(self,vehicle_id,op['model_id'],10,1,op.get('secondary_model_id'),
                    created_keys=[op['created_key']],experimental=experimental,at_point=(op['x'],op['z']),
                    point_reference=True,spawn_items=[dict(model_id=op['model_id'],
                        secondary_model_id=op.get('secondary_model_id'),variant=op.get('variant',0))])
            else:
                group = [op]
                while self.replay_queue and len(group) < 8:
                    nxt = self.replay_queue[0]
                    if (nxt.get('op') != 'add_behind' or nxt.get('target') != {'kind':'created','key':group[-1]['created_key']}
                            or nxt.get('gap') != op.get('gap')
                            or nxt.get('experimental',False) != experimental):
                        break
                    group.append(self.replay_queue.pop(0))
                from .batch import stage
                result = stage(self,vehicle_id,op['model_id'],op['gap'],len(group),op.get('secondary_model_id'),
                             created_keys=[r['created_key'] for r in group],
                             spawn_items=[dict(model_id=r['model_id'],secondary_model_id=r.get('secondary_model_id'),
                                               variant=r.get('variant',0)) for r in group],
                             **({'experimental':True} if experimental else {}))
                if self.replay_queue:
                    result['message'] += f' Queue: {len(self.replay_queue)} left; resume and pause for the next group.'
                return result
        return {'pending': False, 'core_paused': True,
                'message': 'Preset applied. Resume the game with Esc to check it.'}

    def close(self):
        if self.pending:
            raise EditorError('Finish the creation or reload a clean state before closing.')
        self.client.close()
