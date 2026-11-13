"""Guarded controller for the experimental USA current-event editor.

Only the loopback PINE API is used. No process handles, input injection,
emulator configuration changes, or game files are accessed by this module.
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
import time

from .pine import PineClient, Status, Patch, PineError, PineNotPaused, PineTransportError, PineRemoteError
from . import profile, spawncode


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
    def __init__(self, port: int = 28011, journal_dir: Path | None = None, *, client=None):
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

    def _paused(self):
        self._identity()
        if self.client.status() is not Status.PAUSED:
            raise EditorError('Pause o emulador com Esc. A pausa do menu do jogo não basta para editar.')
        if self.unsafe:
            raise EditorError('A última escrita não pôde ser confirmada. Recarregue um estado limpo e reconecte.')

    def _snapshot(self, *, pending=False):
        self._paused()
        return profile.snapshot(self.client, require_paused=True, allow_editor_hook=pending)

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
                     and self.client.read_bytes(spawncode.CAVE, 4096) == bytes(4096))
            if not clean:
                raise EditorError('Recarregue um estado sem edição pendente antes de reconectar.')
            if self.client.status() is not Status.PAUSED:
                raise EditorError('Pause com Esc após recarregar o estado de referência.')
            recovered = profile.snapshot(self.client, require_paused=True)
            if not self.recovery_digest or _state_digest(recovered) != self.recovery_digest:
                raise EditorError('A referência anterior não foi recuperada. Recarregue-a e reabra o editor.')
            self.pending = None
            self.replay_queue.clear()
            self.unsafe = False
        if self.pending is None:
            self.baseline = None
            self.recipe.clear()
            self.actor_keys.clear()
            self.replay_ids.clear()
            self.baseline_refs.clear()
            self.replay_queue.clear()
        paused = self.client.status() is Status.PAUSED
        result = {'status': 'Conectado. Pause com Esc para listar e editar os veículos.',
                  'game': 'Burnout 3 USA', 'profile': 'SLUS-21050',
                  'core_paused': paused, 'pending': self.pending is not None, **identity}
        if paused and self.pending is None:
            result.update(self.refresh())
        return result

    def refresh(self):
        if self.pending:
            return self.poll()
        self._identity()
        if self.client.status() is not Status.PAUSED:
            return {'status': 'Pause o emulador com Esc para atualizar a lista.', 'core_paused': False}
        snap = self._snapshot()
        return {**snap.public(), 'pending': False}

    @staticmethod
    def _selected(snap, vehicle_id):
        if type(vehicle_id) is not int or vehicle_id not in snap.vehicles:
            raise EditorError('Selecione um veículo ativo na lista atualizada.')
        row = snap.vehicles[vehicle_id]
        if not row.get('editable', False):
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
            raise EditorError('Esse veículo não pertence à referência da receita. Conecte novamente para iniciar outra sessão.')
        return {'kind': 'initial', 'id': row['id'], 'model_id': row['model_id'], 'path': row['path']}

    def _resolve(self, reference, snap):
        if reference.get('kind') == 'created':
            vehicle_id = self.replay_ids.get(reference.get('key'))
        elif reference.get('kind') == 'initial':
            vehicle_id = reference.get('id')
            row = self._selected(snap, vehicle_id)
            if row['model_id'] != reference.get('model_id') or row['path'] != reference.get('path'):
                raise EditorError('O veículo do preset não corresponde ao evento atual.')
        else:
            raise EditorError('Referência de veículo inválida no preset.')
        self._selected(snap, vehicle_id)
        return vehicle_id

    def move(self, vehicle_id: int, lateral_percent: float):
        snap = self._ready()
        row = self._selected(snap, vehicle_id)
        patches = profile.lateral_patches(snap, vehicle_id, lateral_percent)
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
        self.recipe.append(operation)
        self._journal('move', vehicle_id=vehicle_id, operation=operation)
        return {'message': 'Posição aplicada. Retome o jogo com Esc para conferir.',
                'core_paused': True, 'pending': False}

    def add_behind(self, vehicle_id: int, model_id: str | None, gap: float):
        return self._add_behind(vehicle_id, model_id, gap)

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
        if live_hook != pending.hook:
            raise EditorError('O código mudou durante a criação. Recarregue um estado limpo antes de continuar.')
        if len(live_scratch) != len(pending.scratch):
            raise EditorError('A leitura da área de trabalho ficou incompleta. Nenhuma limpeza foi aplicada.')
        expected = bytearray(pending.scratch)
        probe = spawncode.DATA - spawncode.CAVE
        # The routine changes only these three publication words. The nonce,
        # signature, instructions and constructor arguments must remain exact.
        for offset in (0, 4, 8):
            expected[probe+offset:probe+offset+4] = live_scratch[probe+offset:probe+offset+4]
        if bytes(expected) != live_scratch:
            raise EditorError('A área de trabalho mudou fora do esperado. Não foi limpa automaticamente.')

    def _check_pending(self, pending: Pending):
        self._validate_pending_bytes(pending,
            self.client.read_bytes(spawncode.HOOK, 8),
            self.client.read_bytes(spawncode.CAVE, 4096))

    def _clean(self, pending: Pending):
        # Re-read after alignment; never clean an area changed since preflight.
        self._check_pending(pending)
        self.client.apply_patch([
            Patch(spawncode.HOOK+4, 4, _word(pending.hook[4:]), _word(spawncode.ORIGINAL[4:])),
            Patch(spawncode.HOOK, 4, _word(pending.hook[:4]), _word(spawncode.ORIGINAL[:4]))])
        self.client.write_bytes(spawncode.CAVE, bytes(4096))
        if self.client.read_bytes(spawncode.CAVE, 4096) != bytes(4096):
            raise EditorError('A limpeza da área de trabalho não conferiu.')

    def poll(self):
        pending = self.pending
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
        if state is not Status.PAUSED:
            message = ('Carro criado. Pause o emulador novamente com Esc para finalizar.' if flag == 2
                       else 'Retome o emulador com Esc para executar a criação.')
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
                    'message': 'Retome com Esc por um instante e pause novamente para concluir a criação.'}
        if object_ptr == 0:
            self._clean(pending)
            self.pending = None
            self.replay_queue.clear()
            raise EditorError('O jogo recusou criar o veículo. A edição temporária foi removida.')
        snap = self._snapshot(pending=True)
        new_id = (object_ptr - 0x539C10) // 0x180
        row = snap.vehicles.get(new_id)
        if (object_ptr != 0x539C10 + new_id*0x180 or new_id in pending.old_ids or not row
                or row['node'] != node_ptr or row['model_hash'] != pending.model_hash
                or row['path'] != pending.path or row['type'] != pending.type_code or not row['independent']):
            raise EditorError('O veículo criado não corresponde à solicitação. Recarregue um estado limpo.')
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
        destination = Path(path)
        payload = {'format': 'burnout3-current-event-recipe', 'version': 1,
                   'profile': 'SLUS-21050/BEBF8793', 'baseline': self.baseline,
                   'operations': self.recipe}
        text = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
        if len(text.encode('utf8')) > 131072 or len(self.recipe) > 32:
            raise EditorError('O preset ultrapassa o limite desta versão.')
        destination.write_text(text, encoding='utf8')
        return {'message': 'Preset salvo. Ele exige o mesmo estado inicial para ser reaplicado.'}

    def load_preset(self, path: str):
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
        if not isinstance(operations, list) or not 1 <= len(operations) <= 32:
            raise EditorError('Lista de operações inválida.')
        # Validate every operation before making the first mutation.
        created = set()
        for op in operations:
            if not isinstance(op, dict) or op.get('op') not in ('move_lateral','add_behind'):
                raise EditorError('Operação não suportada no preset.')
            ref = op.get('target')
            if not isinstance(ref, dict): raise EditorError('Alvo inválido no preset.')
            if ref.get('kind') == 'created':
                if type(ref.get('key')) is not int or ref.get('key') not in created:
                    raise EditorError('Referência fora de ordem no preset.')
            else:
                self._resolve(ref, snap)
            if op['op'] == 'move_lateral':
                value = op.get('lateral_percent')
                if type(value) not in (int,float) or not math.isfinite(value) or not 0 <= value <= 100:
                    raise EditorError('Posição inválida no preset.')
            else:
                model_id = op.get('model_id')
                if not isinstance(model_id, str): raise EditorError('Modelo inválido no preset.')
                model = snap.models.get(model_id)
                gap, key = op.get('gap'), op.get('created_key')
                if (not model or not model.get('eligible') or type(gap) not in (int,float)
                        or not math.isfinite(gap) or not 8 <= gap <= 50
                        or type(key) is not int or not 1 <= key <= 10000 or key in created):
                    raise EditorError('Criação inválida no preset.')
                created.add(key)
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
            vehicle_id = self._resolve(op['target'], snap)
            if op['op'] == 'move_lateral':
                self.move(vehicle_id, op['lateral_percent'])
            else:
                return self._add_behind(vehicle_id, op['model_id'], op['gap'], created_key=op['created_key'])
        return {'pending': False, 'core_paused': True,
                'message': 'Preset aplicado. Retome o jogo com Esc para conferir.'}

    def close(self):
        if self.pending:
            raise EditorError('Finalize a criação ou recarregue um estado limpo antes de fechar.')
        self.client.close()
