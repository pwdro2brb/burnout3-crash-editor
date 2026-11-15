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
from . import profile, spawncode, routes, speed


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
                'message':'Solicitação concluída liberada. Os veículos criados pelo jogo foram mantidos; '
                          'alinhamento e receita deste lote não foram confirmados. A fila restante foi cancelada.'}
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
            raise EditorError('Este editor aceita apenas Burnout 3 USA, SLUS-21050 / BEBF8793.')
        if '1.7.2521' not in result['version']:
            raise EditorError('Esta versão experimental foi preparada para PCSX2 1.7.2521.')
        if self.identity and result != self.identity:
            raise EditorError('O emulador ou o jogo mudou. Reabra a conexão antes de editar.')
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
            raise EditorError('O botão de pausa não encontrou a janela do emulador desta conexão.')
        self.pause_control.set_paused(True)
        result = self.poll() if self.pending else self.refresh()
        result.setdefault('pending', self.pending is not None)
        result.setdefault('message','PCSX2 pausado. Pode editar o evento.')
        result['emulator_control'] = True
        return result

    def export_state(self, destination):
        self._ready()
        if (self.client.read_bytes(spawncode.HOOK,8) != spawncode.ORIGINAL
                or self.client.read_bytes(spawncode.CAVE,4096) not in (bytes(4096),spawncode.clean_batch_scratch())):
            raise EditorError('Finalize a criação antes de salvar um estado editado.')
        if not self._control_available():
            raise EditorError('Não foi possível identificar a instalação portátil desta conexão.')
        from .state_store import export_state
        result = export_state(self.client,self.pause_control.emulator_root(),Path(destination))
        result.update(pending=False,core_paused=self.client.status() is Status.PAUSED)
        self._journal('state_export_finished',path=result['path'],sha256=result['sha256'])
        return result

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
            raise EditorError('Finalize a pendência antes de trabalhar com o projeto do evento.')
        if not self._control_available():
            raise EditorError('O projeto precisa da instalação portátil do PCSX2 desta conexão.')
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
            raise EditorError(f'Não foi possível capturar o projeto. Arquivos criados foram preservados em {folder}. {error}') from error
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
            raise EditorError('Informe um nome de evento com até 100 caracteres.')
        target = Path(directory)
        if target.exists() or target.is_symlink():
            raise EditorError('Escolha uma pasta nova para o projeto; os arquivos existentes serão preservados.')
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
            raise EditorError(f'O projeto não foi criado. A captura foi preservada em {source}. {error}') from error
        self.project = project
        self._reset_scene_tracking(snap)
        self._remove_project_capture(source,capture)
        self._journal('event_project_created',path=project['path'],name=project['name'])
        return {'pending':False,'core_paused':True,'event_projects':True,'project':self._project_info(),
            'message':'Projeto criado. A base foi preservada; edite o evento e use Testar para salvar a cena e jogar.'}

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
            'message':'Projeto criado a partir do estado conferido. A base foi copiada; o arquivo original foi preservado.'}

    def _current_project(self):
        if self.project is None:
            raise EditorError('Crie ou abra um projeto de evento antes de salvar a cena.')
        from .event_project import load
        current = load(Path(self.project['path']))
        if current['_manifest_sha256'] != self.project['_manifest_sha256']:
            raise EditorError('O projeto mudou em outra sessão. Abra-o novamente antes de salvar.')
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
            raise EditorError(f'A cena não foi registrada no projeto. A captura foi preservada em {source}. {error}') from error
        self.project = project
        self._remove_project_capture(source,capture)
        self._journal('event_project_saved',path=project['path'],scene=project['scene'])
        return {'pending':False,'core_paused':True,'event_projects':True,'project':self._project_info(),
            'message':'Cena do evento salva e verificada. Voltar ao início restaurará esta versão.'}

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
            'message':'Cena salva no projeto a partir do estado conferido. O arquivo escolhido foi preservado.'}

    def confirm_project(self,path: str,*,base=False):
        if type(base) is not bool:
            raise EditorError('Escolha a cena salva ou a base original do projeto.')
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
            'message':('Base carregada pelo menu conferida. Projeto pronto para editar.' if base else
                       'Cena carregada pelo menu conferida. Projeto pronto para editar ou testar.')}

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
                'message':f'A cena foi salva, mas não foi possível confirmar a retomada. {error}'}
        return {**saved,**result,'project':self._project_info(),
            'message':'Cena salva e PCSX2 retomado. Para repetir, pause e use Voltar ao início.'}

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
            raise EditorError('O estado foi carregado, mas o perfil não confirmou uma cena editável. '
                              'Recarregue uma referência limpa antes de editar.') from error
        self.project = project
        self._journal('event_project_restored',path=project['path'],base=base,sha256=restored['sha256'])
        return {**restored,'pending':False,'core_paused':True,'event_projects':True,
            'project':self._project_info(),
            'message':('Base original restaurada e conferida. A cena salva do projeto foi preservada.' if base else
                       'Cena salva restaurada e conferida. Pode editar ou retomar para repetir o evento.')}

    def open_project(self,path: str):
        from .event_project import load
        return self._restore_project(load(Path(path)))

    def restart_project(self):
        if self.project is None:
            raise EditorError('Crie ou abra um projeto antes de voltar ao início.')
        from .event_project import load
        return self._restore_project(load(Path(self.project['path'])))

    def restore_project_base(self):
        if self.project is None:
            raise EditorError('Crie ou abra um projeto antes de restaurar a base.')
        from .event_project import load
        return self._restore_project(load(Path(self.project['path'])),base=True)

    def resume(self):
        self._identity()
        if not self._control_available():
            raise EditorError('O botão de retomar não encontrou a janela do emulador desta conexão.')
        self.pause_control.set_paused(False)
        return {'pending':self.pending is not None,'core_paused':False,'emulator_control':True,
                'message':'PCSX2 retomado. '+('Pause novamente para finalizar o lote antes de dirigir.'
                                             if self.pending else 'Pode testar o evento.')}

    def _paused(self):
        self._identity()
        if self.client.status() is not Status.PAUSED:
            raise EditorError('Use Pausar PCSX2 no editor ou Sistema → Pausar no emulador antes de editar.')
        if self.unsafe:
            raise EditorError('A última escrita não pôde ser confirmada. Recarregue um estado limpo e reconecte.')

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
            raise EditorError('Não foi possível conectar. Abra a sessão de teste com PINE ativado e carregue o jogo.')
        except PineRemoteError:
            raise EditorError('O emulador ainda não disponibilizou o jogo. Termine o carregamento e tente novamente.')
        if self.unsafe:
            # Recovery never guesses whether an ambiguous allocation ran.
            clean = (self.client.read_bytes(spawncode.HOOK, 8) == spawncode.ORIGINAL
                     and self.client.read_bytes(spawncode.CAVE, 4096) in (bytes(4096),spawncode.clean_batch_scratch()))
            if not clean:
                raise EditorError('Recarregue um estado sem edição pendente antes de reconectar.')
            if self.client.status() is not Status.PAUSED:
                raise EditorError('Pause o PCSX2 após recarregar o estado de referência.')
            recovered = profile.snapshot(self.client, require_paused=True)
            if not self.recovery_digest or _state_digest(recovered) != self.recovery_digest:
                raise EditorError('A referência anterior não foi recuperada. Recarregue-a e reabra o editor.')
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
        result = {'status': 'Conectado. Pause o PCSX2 para listar e editar os veículos.',
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
                    message=f'{error} Use Finalizar pendência para conferir uma solicitação antiga; '
                            'se não for reconhecida, recarregue um estado limpo.')
        return result

    def refresh(self):
        if self.pending:
            return self.poll()
        self._identity()
        if self.client.status() is not Status.PAUSED:
            return {'status': 'Use Pausar PCSX2 para atualizar a lista.', 'core_paused': False}
        snap = self._snapshot()
        public = snap.public()
        for row in public['vehicles']:
            info = speed.summarize(snap.vehicles[row['id']])
            row.update(speed_info=info,can_set_speed=info['can_set_speed'])
        public['routes'] = routes.build_network(snap)
        if self.client.status() is not Status.PAUSED:
            return {'status':'O PCSX2 foi retomado durante a leitura. Pause e atualize novamente.',
                    'core_paused':False,'pending':False}
        history = {(i,v['model_hash'],v['node'],v['type']):v['initialized'] for i,v in snap.vehicles.items()}
        lost = sum(not ready and self.physics_history.get(key,False) for key,ready in history.items())
        self.physics_history = history
        capacity = dict(snap.inspection['counts'])
        capacity.update(initialized_objects=sum(v['initialized'] for v in snap.vehicles.values()),
            queued_operations=len(self.replay_queue),
            physics_warning=(f'{lost} veículo(s) deixaram de ter física inicializada nesta referência.' if lost else ''))
        return {**public,'pending':False,'capacity':capacity,'project':self._project_info()}

    @staticmethod
    def _selected(snap, vehicle_id, *, experimental=False):
        if type(vehicle_id) is not int or vehicle_id not in snap.vehicles:
            raise EditorError('Selecione um veículo ativo na lista atualizada.')
        row = snap.vehicles[vehicle_id]
        if not row.get('editable', False) and not (experimental and profile.can_move_experimental(snap.vehicles,row)):
            raise EditorError('Escolha um carro ou van independente com a física já inicializada.')
        return row

    def _ready(self):
        if self.pending:
            raise EditorError('Finalize a criação pendente antes de iniciar outra edição.')
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
                raise EditorError('O veículo do preset não corresponde ao evento atual.')
        else:
            raise EditorError('Referência de veículo inválida no preset.')
        select(snap, vehicle_id)
        return vehicle_id

    @staticmethod
    def _speed_selected(snap,vehicle_id):
        row = snap.vehicles.get(vehicle_id) if type(vehicle_id) is int else None
        if row is None or not speed.can_set_speed(row):
            raise EditorError('Selecione um veículo ou cabine com controle de velocidade pronto.')
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
            raise EditorError('As velocidades não puderam ser confirmadas. Recarregue uma referência limpa antes de repetir.') from error
        for row,target in zip(rows,targets):
            operation = dict(op='set_speed',target=target,control_value=control)
            if experimental:
                operation['experimental'] = True
            self.recipe.append(operation)
            self._journal('set_speed',vehicle_id=row['id'],operation=operation,
                previous_control=row['speed'],previous_advance=row['travel_speed'])
        return {'pending':False,'core_paused':True,
            'message':f'Velocidade desejada atualizada em {len(rows)} veículo(s). '
                      'Ao retomar, o jogo recalcula o avanço conforme o trânsito.'}

    def move(self, vehicle_id: int, lateral_percent: float, *, experimental=False):
        if type(experimental) is not bool:
            raise EditorError('Modo experimental inválido.')
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
            raise EditorError('A posição não pôde ser confirmada. Recarregue um estado limpo antes de repetir.')
        operation = {'op': 'move_lateral', 'target': reference,
                     'lateral_percent': float(lateral_percent)}
        if experimental:
            operation['experimental'] = True
        self.recipe.append(operation)
        self._journal('move', vehicle_id=vehicle_id, operation=operation)
        return {'message': 'Posição aplicada. Retome o jogo com Esc para conferir.',
                'core_paused': True, 'pending': False}

    def add_behind(self, vehicle_id: int, model_id: str | None, gap: float):
        return self.add_many_behind(vehicle_id, model_id, gap, 1)

    def add_many_behind(self, vehicle_id, model_id, gap, count, secondary_model_id=None, *, experimental=False):
        if (type(experimental) is not bool or type(count) is not int
                or not 1 <= count <= (253 if experimental else 8)):
            raise EditorError('Use quantidade de 1 a 8, ou ative o experimental para pedir até a capacidade do tráfego.')
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
            result['message'] += f' Fila: {count-8} restantes, em grupos de até oito; retome e pause a cada grupo.'
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
                'message':f'Fila cancelada ({count} operações). '+
                    ('Finalize o lote já preparado; ele não será repetido.' if self.pending else 'Nenhuma criação foi repetida.')}

    def _add_behind(self, vehicle_id, model_id, gap, *, created_key=None):
        snap = self._ready()
        target = self._selected(snap, vehicle_id)
        if not isinstance(gap, (int, float)) or isinstance(gap, bool) or not math.isfinite(gap) or not 8 <= gap <= 50:
            raise EditorError('Use uma distância entre 8 e 50 unidades do jogo.')
        model_id = model_id or target['model_id']
        model = snap.models.get(model_id)
        if not model or not model.get('eligible') or model.get('type') not in (1, 2):
            raise EditorError('Escolha um carro ou van carregado e compatível nesta versão.')
        if snap.memory.u8(0x527440 + 0x363BE):
            raise EditorError('O jogo está bloqueando novas instâncias neste momento.')
        if snap.inspection['counts']['free_objects'] < 2 or snap.inspection['counts']['free_nodes'] < 1:
            raise EditorError('Não há espaço livre suficiente para outro veículo.')
        progression = profile.behind_progress(snap.memory, target['path'], target['progress'],
                                             target['lateral'], float(gap), node=target['node'])
        candidate = profile.lane(snap.memory, target['path'], progression, target['lateral'])['point']
        origin = profile.lane(snap.memory, target['path'], target['progress'], target['lateral'])['point']
        center = [candidate[k] + target['position'][k] - origin[k] for k in range(3)]
        for peer_id, peer in snap.vehicles.items():
            if peer_id != vehicle_id and peer.get('independent') and peer.get('initialized') and peer['path'] == target['path']:
                if math.dist(center, peer['position']) < 6:
                    raise EditorError('Esse trecho já tem um veículo. Aumente a distância ou escolha outro alvo.')
        if self.client.read_bytes(spawncode.HOOK, 8) != spawncode.ORIGINAL:
            raise EditorError('O código do evento mudou. Recarregue um estado limpo.')
        if self.client.read_bytes(spawncode.CAVE, 4096) != bytes(4096):
            raise EditorError('Há uma edição incompleta na memória. Recarregue um estado limpo.')
        key = self.next_key if created_key is None else created_key
        if type(key) is not int or not 1 <= key <= 10000:
            raise EditorError('Identificador de criação inválido.')
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
                raise EditorError('A preparação da criação não conferiu.')
            self.client.apply_patch([
                Patch(spawncode.HOOK, 4, _word(spawncode.ORIGINAL[:4]), _word(payload['hook_bytes'][:4])),
                Patch(spawncode.HOOK+4, 4, _word(spawncode.ORIGINAL[4:]), _word(payload['hook_bytes'][4:]))])
        except Exception:
            self.unsafe = True
            self._journal('stage_unconfirmed', nonce=nonce)
            raise EditorError('A preparação não pôde ser confirmada. Recarregue um estado limpo antes de repetir.')
        self._journal('spawn_staged', nonce=nonce, model_id=model_id, gap=float(gap),
                      path=target['path'], progression=progression)
        return {'pending': True, 'core_paused': True,
                'message': 'Preparado. Retome o emulador com Esc; depois pause novamente com Esc para finalizar.'}

    @staticmethod
    def _validate_pending_bytes(pending: Pending, live_hook: bytes, live_scratch: bytes):
        """Accept only this request's hook and immutable code/data/nonce bytes."""
        if live_hook not in getattr(pending,'allowed_hooks',(pending.hook,)):
            raise EditorError('O código mudou durante a criação. Recarregue um estado limpo antes de continuar.')
        if len(live_scratch) != len(pending.scratch):
            raise EditorError('A leitura da área de trabalho ficou incompleta. Nenhuma limpeza foi aplicada.')
        expected = bytearray(pending.scratch)
        probe = spawncode.DATA - spawncode.CAVE
        # The routine changes only these three publication words. The nonce,
        # signature, instructions and constructor arguments must remain exact.
        offsets = getattr(pending, 'probe_offsets', (probe,probe+4,probe+8))
        for offset in offsets:
            expected[offset:offset+4] = live_scratch[offset:offset+4]
        if bytes(expected) != live_scratch:
            raise EditorError('A área de trabalho mudou fora do esperado. Não foi limpa automaticamente.')

    def _check_pending(self, pending: Pending):
        hook = self.client.read_bytes(spawncode.HOOK,8)
        self._validate_pending_bytes(pending,
            hook,
            self.client.read_bytes(spawncode.CAVE, 4096))
        if (getattr(pending,'batch',False) and (hook != spawncode.ORIGINAL
                or self.client.read_many([(pending.completion_address,4)])[0] != pending.completion_token)):
            raise EditorError('A rotina do lote ainda não terminou. Retome brevemente e pause.')

    def _clean(self, pending: Pending):
        # Re-read after alignment; never clean an area changed since preflight.
        self._check_pending(pending)
        if getattr(pending,'batch',False):
            # DONE is published only after leaving removable code, with the
            # original entry restored. Retain the permanent landing in case
            # the paused EE has not executed its final jump yet.
            if (self.client.read_bytes(spawncode.HOOK,8) != spawncode.ORIGINAL
                    or self.client.read_many([(pending.completion_address,4)])[0] != pending.completion_token):
                raise EditorError('A rotina do lote ainda não terminou. Retome brevemente e pause.')
            self.client.write_bytes(spawncode.CAVE,pending.clean_scratch)
            if self.client.read_bytes(spawncode.CAVE,4096) != pending.clean_scratch:
                raise EditorError('A limpeza da área de trabalho não conferiu.')
            return
        self.client.apply_patch([
            Patch(spawncode.HOOK+4, 4, _word(pending.hook[4:]), _word(spawncode.ORIGINAL[4:])),
            Patch(spawncode.HOOK, 4, _word(pending.hook[:4]), _word(spawncode.ORIGINAL[:4]))])
        self.client.write_bytes(spawncode.CAVE, bytes(4096))
        if self.client.read_bytes(spawncode.CAVE, 4096) != bytes(4096):
            raise EditorError('A limpeza da área de trabalho não conferiu.')

    def _cleanup_completed_request(self, pending: Pending, event: str, **fields):
        """Remove only our completed request; never repair or move its actor."""
        try:
            self._clean(pending)
        except Exception:
            self.unsafe = True
            self._journal('cleanup_unconfirmed', nonce=pending.nonce, **fields)
            raise EditorError('A limpeza não pôde ser confirmada. Recarregue um estado limpo antes de continuar.')
        self.pending = None
        self.replay_queue.clear()
        self._journal(event, nonce=pending.nonce, **fields)

    def poll(self):
        pending = self.pending
        if getattr(pending, 'batch', False):
            from . import batch
            return batch.poll(self)
        if pending is None:
            return {'pending': False, 'message': 'Nenhuma criação pendente.',
                    'core_paused': self.client.status() is Status.PAUSED}
        if self.unsafe:
            raise EditorError('Recarregue um estado limpo e reconecte; a operação anterior não será repetida.')
        self._identity()
        state = self.client.status()
        if state is Status.SHUTDOWN:
            raise EditorError('O jogo foi encerrado. A criação não será repetida automaticamente.')
        flag, object_ptr, node_ptr = self.client.read_many([(spawncode.DATA+i, 4) for i in (0,4,8)])
        waiting_message = ('Aguardando a atualização do tráfego. Retome o PCSX2 e, '
                           'se estiver em Continue/menu, inicie o evento.')
        if state is not Status.PAUSED:
            message = ('Veículo criado. Pause agora o PCSX2 para finalizar antes de dirigir.' if flag == 2
                       else waiting_message)
            return {'pending': True, 'message': message, 'core_paused': False}
        live_hook = self.client.read_bytes(spawncode.HOOK, 8)
        scratch = self.client.read_bytes(spawncode.CAVE, 4096)
        if live_hook == spawncode.ORIGINAL and scratch == bytes(4096):
            self.pending = None
            self.replay_queue.clear()
            self._journal('spawn_interrupted', nonce=pending.nonce)
            return {'pending': False, 'core_paused': True,
                    'message': 'O estado foi recarregado. A criação pendente foi cancelada, sem repetição automática.'}
        self._validate_pending_bytes(pending, live_hook, scratch)
        if flag != 2:
            return {'pending': True, 'core_paused': True,
                    'message': waiting_message}
        if object_ptr == 0:
            self._cleanup_completed_request(pending, 'spawn_refused',
                reason='allocator_returned_null', object_pointer=object_ptr, node_pointer=node_ptr)
            raise EditorError('O jogo recusou criar o veículo. A edição temporária foi removida.')
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
                    'message': 'Criação executada, mas o veículo mudou ou saiu do cenário. '
                               'Código temporário removido. Alinhamento não confirmado.'}
        if not row['initialized']:
            return {'pending': True, 'core_paused': True,
                    'message': 'A física ainda está inicializando. Retome por um instante e pause novamente.'}
        # Snapshot reads take time: confirm the request again before touching
        # even the newly created actor, not only before restoring the hook.
        self._check_pending(pending)
        try:
            self.client.apply_patch(profile.lateral_patches(snap, new_id, pending.lateral * 100))
            self._clean(pending)
        except Exception:
            self.unsafe = True
            self._journal('finalize_unconfirmed', nonce=pending.nonce)
            raise EditorError('A finalização não pôde ser confirmada. Recarregue um estado limpo antes de repetir.')
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
                'message': 'Veículo adicionado e edição finalizada. Retome com Esc para testar.'}

    def save_preset(self, path: str):
        if self.pending or not self.recipe or not self.baseline:
            raise EditorError('Finalize pelo menos uma edição antes de salvar um preset.')
        if any(op.get('target',{}).get('kind') == 'observed' for op in self.recipe):
            raise EditorError('Há edições em veículos que surgiram depois da referência inicial e não podem ser '
                              'recriados por esta receita. Use Salvar estado… (.p2s) para manter o cenário, '
                              'ou conecte novamente para iniciar uma receita com a cena atual.')
        destination = Path(path)
        payload = {'format': 'burnout3-current-event-recipe', 'version': 1,
                   'profile': 'SLUS-21050/BEBF8793', 'baseline': self.baseline,
                   'operations': self.recipe}
        text = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
        if len(text.encode('utf8')) > 131072 or len(self.recipe) > 256:
            raise EditorError('O preset ultrapassa o limite desta versão.')
        destination.write_text(text, encoding='utf8')
        return {'message': 'Preset salvo. Ele exige o mesmo estado inicial para ser reaplicado.'}

    def load_preset(self, path: str, *, experimental=False):
        if type(experimental) is not bool:
            raise EditorError('Modo experimental inválido.')
        allow_experimental = experimental
        snap = self._ready()
        source = Path(path)
        if source.stat().st_size > 131072:
            raise EditorError('Preset grande demais.')
        try:
            data = json.loads(source.read_text(encoding='utf8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise EditorError('O arquivo não contém um preset JSON válido.')
        if (not isinstance(data, dict) or data.get('format') != 'burnout3-current-event-recipe'
                or type(data.get('version')) is not int or data.get('version') != 1
                or data.get('profile') != 'SLUS-21050/BEBF8793'):
            raise EditorError('Formato de preset incompatível.')
        if data.get('baseline') != _fingerprint(snap):
            raise EditorError('Recarregue o mesmo estado inicial usado para criar este preset.')
        operations = data.get('operations')
        if not isinstance(operations, list) or not 1 <= len(operations) <= 256:
            raise EditorError('Lista de operações inválida.')
        # Validate every operation before making the first mutation.
        created = set()
        created_models = {}
        for op in operations:
            if not isinstance(op, dict) or op.get('op') not in ('move_lateral','add_behind','add_at','set_speed'):
                raise EditorError('Operação não suportada no preset.')
            experimental = op.get('experimental',False)
            if type(experimental) is not bool:
                raise EditorError('Modo experimental inválido no preset.')
            if experimental and not allow_experimental:
                raise EditorError('Esta receita usa o modo experimental. Ative o modo e leia o aviso antes de carregá-la.')
            ref = op.get('target')
            if not isinstance(ref, dict): raise EditorError('Alvo inválido no preset.')
            if ref.get('kind') == 'created':
                if type(ref.get('key')) is not int or ref.get('key') not in created:
                    raise EditorError('Referência fora de ordem no preset.')
            else:
                self._resolve(ref,snap,for_creation=op['op'] in ('add_behind','add_at'),
                    experimental=experimental,for_speed=op['op']=='set_speed')
            if op['op'] == 'set_speed':
                try:
                    speed.validate_control(op.get('control_value'),experimental=experimental)
                except profile.ProfileError as error:
                    raise EditorError(f'Velocidade inválida no preset: {error}') from error
            elif op['op'] == 'move_lateral':
                value = op.get('lateral_percent')
                if (type(value) not in (int,float) or not math.isfinite(value)
                        or (not experimental and not 0 <= value <= 100)):
                    raise EditorError('Posição inválida no preset.')
                try:
                    profile._lane_fraction_word(value/100)
                except profile.ProfileError as error:
                    raise EditorError('Posição fora do intervalo float32 no preset.') from error
            else:
                model_id = op.get('model_id')
                if not isinstance(model_id, str): raise EditorError('Modelo inválido no preset.')
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
                    raise EditorError('Use distância de 30 a 50 unidades para ônibus ou conjuntos de cabine e carga.')
                if (not model or not model.get('eligible') or type(key) is not int
                        or not 1 <= key <= 10000 or key in created):
                    raise EditorError('Criação inválida no preset.')
                if op['op'] == 'add_behind':
                    if (type(gap) not in (int,float) or not math.isfinite(gap)
                            or (gap <= 0 if experimental else not 8 <= gap <= 50)):
                        raise EditorError('Distância inválida no preset.')
                else:
                    for axis in ('x','z'):
                        coordinate = op.get(axis)
                        if type(coordinate) not in (int,float) or not math.isfinite(coordinate):
                            raise EditorError('Ponto inválido no preset.')
                        try:
                            valid = math.isfinite(struct.unpack('<f',struct.pack('<f',coordinate))[0])
                        except (OverflowError,struct.error):
                            valid = False
                        if not valid:
                            raise EditorError('Ponto fora do intervalo float32 no preset.')
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
                    point_reference=True)
            else:
                group = [op]
                while self.replay_queue and len(group) < 8:
                    nxt = self.replay_queue[0]
                    if (nxt.get('op') != 'add_behind' or nxt.get('target') != {'kind':'created','key':group[-1]['created_key']}
                            or any(nxt.get(k) != op.get(k) for k in ('model_id','gap','secondary_model_id'))
                            or nxt.get('experimental',False) != experimental):
                        break
                    group.append(self.replay_queue.pop(0))
                from .batch import stage
                result = stage(self,vehicle_id,op['model_id'],op['gap'],len(group),op.get('secondary_model_id'),
                             created_keys=[r['created_key'] for r in group],**({'experimental':True} if experimental else {}))
                if self.replay_queue:
                    result['message'] += f' Fila: {len(self.replay_queue)} restantes; retome e pause para o próximo grupo.'
                return result
        return {'pending': False, 'core_paused': True,
                'message': 'Preset aplicado. Retome o jogo com Esc para conferir.'}

    def close(self):
        if self.pending:
            raise EditorError('Finalize a criação ou recarregue um estado limpo antes de fechar.')
        self.client.close()
