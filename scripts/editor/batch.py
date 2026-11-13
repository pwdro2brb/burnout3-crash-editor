"""Bounded placement and completion of one-frame traffic batches."""
from __future__ import annotations

from dataclasses import dataclass
import math
import secrets
import struct
import time

from . import profile, spawncode
from .controller import EditorError, _state_digest, _word
from .pine import Patch, Status


@dataclass
class BatchPending:
    scratch: bytes
    hook: bytes
    nonce: str
    model_id: str
    model_hash: int
    type_code: int
    secondary_model_id: str | None
    secondary_model_hash: int
    path: int
    lateral: float
    old_ids: set[int]
    target_ref: dict
    gap: float
    created_keys: list[int]
    probes: list[int]
    probe_offsets: tuple[int, ...]
    clean_scratch: bytes
    completion_address: int
    allowed_hooks: tuple[bytes, ...]
    staged_at: float
    batch: bool = True


def reference(snapshot, vehicle_id):
    row = snapshot.vehicles.get(vehicle_id) if type(vehicle_id) is int else None
    if not row or not row.get('can_reference', row.get('editable', False)):
        raise EditorError('Selecione um veículo com caminho e física inicializados para servir de referência.')
    return row


def model_pair(snapshot, model_id, secondary_model_id):
    model = snapshot.models.get(model_id)
    if not model or not model.get('eligible'):
        raise EditorError('Escolha um modelo carregado e compatível com esta sessão.')
    secondary = None
    if model.get('type') == 4:
        secondary = snapshot.models.get(secondary_model_id)
        if (not secondary or not secondary.get('eligible_as_trailer')
                or secondary_model_id not in model.get('trailer_model_ids', [])
                or model_id not in secondary.get('truck_model_ids', [])):
            raise EditorError('Escolha uma carga cuja combinação com esta cabine foi observada no jogo.')
    elif model.get('type') not in (1, 2) or secondary_model_id is not None:
        raise EditorError('Uma carga deve ser criada junto de uma cabine compatível.')
    return model, secondary


def stage(editor, vehicle_id, model_id, gap, count, secondary_model_id=None, *, created_keys=None):
    if type(count) is not int or not 1 <= count <= 8:
        raise EditorError('Escolha uma quantidade de 1 a 8 veículos.')
    if type(gap) not in (int, float) or not math.isfinite(gap) or not 8 <= gap <= 50:
        raise EditorError('Use uma distância entre 8 e 50 unidades do jogo.')
    snap = editor._ready()
    target = reference(snap, vehicle_id)
    model_id = model_id or target['model_id']
    model, secondary = model_pair(snap, model_id, secondary_model_id)
    if (secondary or target.get('native_pair_valid')) and gap < 30:
        raise EditorError('Use distância de 30 a 50 unidades para conjuntos de cabine e carga.')
    needed = count*(2 if secondary else 1)
    counts = snap.inspection['counts']
    if (counts['free_objects'] < needed+1 or counts['free_nodes'] < count
            or counts['active_objects']+needed+1 > counts['capacity_budget_byte_0x363ab']):
        raise EditorError('O lote excede o espaço disponível nos pools de tráfego.')
    collision_count = snap.memory.u32(0x55EF70+0x1CB70)
    endpoint_count = snap.memory.u32(0x55EF70+0x1CB74)
    if (not 0 <= collision_count <= 1224-needed
            or not 0 <= endpoint_count <= 2448-2*needed):
        raise EditorError('O lote excede o espaço disponível nos registros de colisão.')
    if snap.memory.u8(0x527440+0x363BE):
        raise EditorError('O jogo está bloqueando novas instâncias neste momento.')
    if editor.client.read_bytes(spawncode.HOOK,8) != spawncode.ORIGINAL:
        raise EditorError('O código do evento mudou. Recarregue uma referência limpa.')
    if editor.client.read_bytes(spawncode.CAVE,4096) not in (bytes(4096), spawncode.clean_batch_scratch()):
        raise EditorError('Existe uma solicitação temporária na memória. Finalize-a antes de criar outro lote.')
    # Plan every position before the first write. No partial chain is installed
    # when the rear of the batch would cross the beginning of the path.
    progress = target['progress']
    positions, requests = [], []
    origin = profile.lane(snap.memory,target['path'],progress,target['lateral'])['point']
    residual = [target['position'][k]-origin[k] for k in range(3)]
    for _ in range(count):
        progress = profile.behind_progress(snap.memory, target['path'], progress,
            target['lateral'], float(gap), node=target['node'])
        point = profile.lane(snap.memory,target['path'],progress,target['lateral'])['point']
        point = [point[k]+residual[k] for k in range(3)]
        for peer in snap.vehicles.values():
            if peer['id'] != vehicle_id and peer.get('initialized') and peer.get('path') == target['path']:
                if math.dist(point,peer['position']) < 6:
                    raise EditorError('O lote passaria por um veículo existente. Aumente a distância ou mude a referência.')
        if any(math.dist(point,previous) < 6 for previous in positions):
            raise EditorError('As posições do lote ficaram muito próximas neste caminho.')
        positions.append(point)
        requests.append(dict(manager=spawncode.MANAGER,type_code=model['type'],
            model_hash=model['model_hash'],path_descriptor=profile.PATHS+target['path']*profile.PATH_STRIDE,
            progression=progress,speed=target['speed'],spacing=target['spacing_scalar'],
            secondary_type_code=11 if secondary else 0,
            secondary_model_hash=secondary['model_hash'] if secondary else 0))
    keys = list(range(editor.next_key,editor.next_key+count)) if created_keys is None else list(created_keys)
    if len(keys) != count or len(set(keys)) != count or any(type(k) is not int or not 1 <= k <= 10000 for k in keys):
        raise EditorError('Identificadores do lote inválidos.')
    nonce = secrets.token_bytes(16)
    payload = spawncode.build_batch(requests,nonce=nonce)
    editor._start_recipe(snap)
    editor.recovery_digest = _state_digest(snap)
    editor.pending = BatchPending(payload['scratch_bytes'],payload['hook_bytes'],nonce.hex(),
        model_id,model['model_hash'],model['type'],secondary_model_id,
        secondary['model_hash'] if secondary else 0,target['path'],target['lateral'],
        set(snap.vehicles),editor._reference(target),float(gap),keys,
        [p['address'] for p in payload['probes']],
        (spawncode.DATA-spawncode.CAVE,)+tuple(p['offset']+o for p in payload['probes'] for o in (0,4,8)),
        payload['clean_scratch'],payload['completion_address'],
        (payload['hook_bytes'],payload['hook_bytes'][:4]+spawncode.ORIGINAL[4:],spawncode.ORIGINAL),
        time.monotonic())
    editor.next_key = max(editor.next_key,max(keys)+1)
    try:
        editor.client.write_bytes(spawncode.CAVE,payload['scratch_bytes'])
        if editor.client.read_bytes(spawncode.CAVE,4096) != payload['scratch_bytes']:
            raise EditorError('A preparação do lote não conferiu.')
        editor.client.apply_patch([
            Patch(spawncode.HOOK,4,_word(spawncode.ORIGINAL[:4]),_word(payload['hook_bytes'][:4])),
            Patch(spawncode.HOOK+4,4,_word(spawncode.ORIGINAL[4:]),_word(payload['hook_bytes'][4:]))])
    except Exception:
        editor.unsafe = True
        editor._journal('batch_stage_unconfirmed',nonce=nonce.hex())
        raise EditorError('A preparação do lote não pôde ser confirmada. Recarregue a referência limpa.')
    editor._journal('batch_staged',nonce=nonce.hex(),model_id=model_id,
        secondary_model_id=secondary_model_id,count=count,gap=float(gap),path=target['path'],
        progressions=[r['progression'] for r in requests])
    return {'pending':True,'core_paused':True,
        'message':f'Lote de {count} preparado. Retome o PCSX2 uma vez e pause novamente para finalizar todos.'}


def collider_valid(memory, row):
    """Check the observed broad-phase registration, without changing it."""
    base = 0x55EF70
    ptr = memory.u32(row['address']+0x16C)
    count = memory.u32(base+0x1CB70)
    index = (ptr-base-0x70)//0x30
    if not 0 < count <= 1224 or not 0 <= index < count or ptr != base+0x70+index*0x30:
        return False
    if (memory.u8(ptr) != 3 or memory.u32(ptr+4) != row['address']+0x70
            or memory.u32(ptr+8) != row['model_pointer']+0xE80
            or memory.u32(ptr+0xC) != row['address']):
        return False
    lo,hi = memory.xyz(ptr+0x10),memory.xyz(ptr+0x20)
    return all(math.isfinite(x) for x in lo+hi) and all(a <= b for a,b in zip(lo,hi))


def poll(editor):
    pending = editor.pending
    if editor.unsafe:
        raise EditorError('Recarregue uma referência limpa; o lote anterior não será repetido.')
    editor._identity()
    status = editor.client.status()
    if status is Status.SHUTDOWN:
        raise EditorError('O jogo foi encerrado. O lote não será repetido.')
    values = editor.client.read_many([(p+o,4) for p in pending.probes for o in (0,4,8)])
    probes = [values[i:i+3] for i in range(0,len(values),3)]
    complete = sum(p[0] == 2 for p in probes)
    retired = editor.client.read_many([(pending.completion_address,4)])[0] == 2
    if status is not Status.PAUSED:
        return {'pending':True,'core_paused':False,
            'message':f'{complete}/{len(probes)} solicitações executadas. '
                + ('Pause agora para finalizar antes de dirigir.' if complete == len(probes)
                   else 'Inicie/retome o evento para executar o lote.')}
    hook,scratch = editor.client.read_bytes(spawncode.HOOK,8),editor.client.read_bytes(spawncode.CAVE,4096)
    if hook == spawncode.ORIGINAL and scratch in (bytes(4096), pending.clean_scratch):
        editor.pending = None
        editor.replay_queue.clear()
        return {'pending':False,'core_paused':True,'warning':True,
            'message':'O estado foi recarregado; o lote pendente foi cancelado.'}
    editor._validate_pending_bytes(pending,hook,scratch)
    if complete != len(probes) or not retired:
        return {'pending':True,'core_paused':True,
            'message':'Retome o evento por um instante para executar todas as solicitações do lote.'}
    if hook != spawncode.ORIGINAL:
        raise EditorError('O lote terminou sem restaurar a entrada do jogo. Recarregue uma referência limpa.')
    snap = editor._snapshot(pending=True)
    selected,seen = [],set()
    invalid = False
    for _state,object_ptr,node_ptr in probes:
        index = (object_ptr-profile.VEHICLES)//profile.VEHICLE_STRIDE
        row = snap.vehicles.get(index)
        if (not object_ptr or object_ptr != profile.VEHICLES+index*profile.VEHICLE_STRIDE
                or index in pending.old_ids or index in seen or not row
                or row['node'] != node_ptr or row['model_hash'] != pending.model_hash
                or row['type'] != pending.type_code or row['path'] != pending.path):
            invalid = True
            break
        seen.add(index)
        if pending.secondary_model_id is not None:
            child = snap.vehicles.get(row.get('child_id'))
            if (not row.get('native_pair_valid') or not child or child['id'] in pending.old_ids
                    or child['id'] in seen or child['model_hash'] != pending.secondary_model_hash
                    or child['parent_id'] != index or child['type'] != 11 or child['node'] != 0):
                invalid = True
                break
            seen.add(child['id'])
            if not child['initialized']:
                return {'pending':True,'core_paused':True,'message':'A carga ainda está inicializando. Retome brevemente e pause.'}
            if not collider_valid(snap.memory,child):
                invalid = True
                break
        elif not row['independent']:
            invalid = True
            break
        if not row['initialized']:
            return {'pending':True,'core_paused':True,'message':'A física do lote ainda está inicializando. Retome brevemente e pause.'}
        if not collider_valid(snap.memory,row):
            invalid = True
            break
        selected.append(row)
    if invalid:
        editor._cleanup_completed_request(pending,'batch_not_finalized',reason='allocation_or_identity_changed')
        return {'pending':False,'core_paused':True,'warning':True,
            'message':'O lote executou, mas uma instância mudou ou não pôde ser validada. '
                      'Código temporário removido; alinhamento e receita não confirmados.'}
    patches = []
    for row in selected:
        patches.extend(profile.lateral_patches(snap,row['id'],pending.lateral*100))
    editor._check_pending(pending)
    try:
        editor.client.apply_patch(patches)
        editor._clean(pending)
    except Exception:
        editor.unsafe = True
        editor._journal('batch_finalize_unconfirmed',nonce=pending.nonce)
        raise EditorError('A finalização do lote não pôde ser confirmada. Recarregue a referência limpa.')
    editor.pending = None
    target_ref = pending.target_ref
    for row,key in zip(selected,pending.created_keys):
        editor.actor_keys[row['id']] = key
        editor.replay_ids[key] = row['id']
        operation = {'op':'add_behind','target':target_ref,'model_id':pending.model_id,
            'gap':pending.gap,'created_key':key}
        if pending.secondary_model_id is not None:
            operation['secondary_model_id'] = pending.secondary_model_id
        editor.recipe.append(operation)
        target_ref = {'kind':'created','key':key}
    editor._journal('batch_finished',nonce=pending.nonce,
        new_vehicle_ids=[row['id'] for row in selected],count=len(selected),
        model_id=pending.model_id,secondary_model_id=pending.secondary_model_id)
    if editor.replay_queue:
        result = editor._continue_recipe()
        result.setdefault('new_vehicle_id',selected[-1]['id'])
        result.setdefault('new_vehicle_ids',[row['id'] for row in selected])
        return result
    return {'pending':False,'core_paused':True,'new_vehicle_id':selected[-1]['id'],
        'new_vehicle_ids':[row['id'] for row in selected],
        'message':f'{len(selected)} veículo(s) adicionados e lote finalizado. Pode retomar para testar.'}
