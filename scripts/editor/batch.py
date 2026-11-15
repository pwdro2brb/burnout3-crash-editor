"""Bounded placement and completion of one-frame traffic batches."""
from __future__ import annotations

from dataclasses import dataclass
import math
import secrets
import struct
import time

from . import profile, spawncode
from .controller import EditorError, _state_digest, _word
from .pine import Patch, Status, PineError


PHYSICS_WAIT_SECONDS = 5.0


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
    completion_token: int
    allowed_hooks: tuple[bytes, ...]
    staged_at: float
    batch: bool = True
    experimental: bool = False
    at_point: tuple[float,float] | None = None
    physics_wait_started: float | None = None
    physics_wait_polls: int = 0
    items: list[dict] | None = None


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
    elif model.get('type') not in profile.SUPPORTED_SINGLE_TYPES or secondary_model_id is not None:
        raise EditorError('Uma carga deve ser criada junto de uma cabine compatível.')
    return model, secondary


def stage(editor, vehicle_id, model_id, gap, count, secondary_model_id=None, *, created_keys=None,
          experimental=False, reserve_count=None, at_point=None, point_reference=False,
          spawn_items=None, reserve_items=None):
    if type(experimental) is not bool:
        raise EditorError('Modo experimental inválido.')
    if type(count) is not int or not 1 <= count <= 8:
        raise EditorError('Escolha uma quantidade de 1 a 8 veículos.')
    if (type(gap) not in (int,float) or not math.isfinite(gap)
            or (gap <= 0 if experimental else not 8 <= gap <= 50)):
        raise EditorError('Use uma distância positiva finita.' if experimental else
                          'Use uma distância entre 8 e 50 unidades do jogo.')
    snap = editor._ready()
    target = reference(snap, vehicle_id)
    model_id = model_id or target['model_id']
    model, secondary = model_pair(snap, model_id, secondary_model_id)
    if spawn_items is None:
        spawn_items = [dict(model_id=model_id,secondary_model_id=secondary_model_id,variant=0) for _ in range(count)]
    if type(spawn_items) not in (list,tuple) or len(spawn_items) != count:
        raise EditorError('A sequência de modelos não corresponde à quantidade do lote.')
    def prepare(item):
        if (not isinstance(item,dict) or set(item)-{'model_id','secondary_model_id','variant'}
                or type(item.get('variant',0)) is not int or not 0 <= item.get('variant',0) <= 7):
            raise EditorError('Modelo ou variação visual inválidos na sequência.')
        primary,child = model_pair(snap,item.get('model_id'),item.get('secondary_model_id'))
        return dict(model_id=item['model_id'],model_hash=primary['model_hash'],type=primary['type'],
            secondary_model_id=item.get('secondary_model_id'),secondary_model_hash=child['model_hash'] if child else 0,
            variant=item.get('variant',0))
    items = [prepare(item) for item in spawn_items]
    if (items[0]['model_id'] != model_id or items[0]['secondary_model_id'] != secondary_model_id):
        raise EditorError('O primeiro modelo da sequência não corresponde à configuração do lote.')
    # Validate the complete future queue before installing its first group.
    if reserve_items is not None and (type(reserve_items) not in (list,tuple) or not count <= len(reserve_items) <= 253):
        raise EditorError('A reserva da sequência de modelos é inválida.')
    reserved_items = [prepare(item) for item in reserve_items] if reserve_items is not None else None
    if reserved_items is not None and reserved_items[:count] != items:
        raise EditorError('O início da reserva não corresponde ao lote preparado.')
    projection = None
    if at_point is not None:
        if count != 1:
            raise EditorError('Adicione um veículo ou conjunto por ponto escolhido.')
        from .placement import project_target
        projection = project_target(snap,vehicle_id if point_reference else None,*at_point,experimental=experimental)
        if not experimental and projection['error_distance'] > 25:
            raise EditorError('O ponto está longe dos caminhos carregados. Escolha um ponto mais próximo ou use o modo experimental.')
        target = reference(snap,projection['reference_id'])
        profile._lane_fraction_word(projection['lateral'])
        if not experimental:
            point_geometry = profile.lane(snap.memory,target['path'],projection['progression'],.5)
            across = point_geometry['lane']
            maximum_shift = max(abs(projection['lateral']),abs(1-projection['lateral']))*math.hypot(across[0],across[2])
            if maximum_shift > 10:
                raise EditorError('O ponto exige deslocamento lateral amplo. Ative o modo experimental para tentar essa posição.')
    if (not experimental and projection is None and
            (any(item['secondary_model_id'] or item['type'] == 5 for item in items)
             or target.get('native_pair_valid') or target['type'] == 5) and gap < 30):
        raise EditorError('Use distância de 30 a 50 unidades para ônibus ou conjuntos de cabine e carga.')
    reserved = count if reserve_count is None else reserve_count
    if type(reserved) is not int or not count <= reserved <= 253:
        raise EditorError('A quantidade ultrapassa a capacidade conhecida do tráfego.')
    if (reserved > count and reserved_items is None and
            any((item['model_id'],item['secondary_model_id']) !=
                (items[0]['model_id'],items[0]['secondary_model_id']) for item in items)):
        raise EditorError('Informe a sequência completa para reservar um lote misto com fila.')
    if reserved_items is not None and len(reserved_items) != reserved:
        raise EditorError('A reserva não corresponde à sequência completa do lote.')
    if (not experimental and projection is None and reserved_items is not None
            and any(item['secondary_model_id'] or item['type'] == 5 for item in reserved_items) and gap < 30):
        raise EditorError('Use distância de 30 a 50 unidades para ônibus ou conjuntos de cabine e carga.')
    needed = (sum(2 if item['secondary_model_id'] else 1 for item in reserved_items)
              if reserved_items is not None else
              sum(2 if item['secondary_model_id'] else 1 for item in items) if reserved == count else
              reserved*(2 if secondary else 1))
    counts = snap.inspection['counts']
    if (counts['free_objects'] < needed+1 or counts['free_nodes'] < reserved
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
        raise EditorError('Existe uma solicitação temporária na memória. Clique em Finalizar pendência antes de criar outro lote.')
    # Plan every position before the first write. No partial chain is installed
    # when the rear of the batch would cross the beginning of the path.
    progress = target['progress']
    lateral = projection['lateral'] if projection else target['lateral']
    positions, requests = [], []
    origin = profile.lane(snap.memory,target['path'],progress,target['lateral'])['point']
    residual = [target['position'][k]-origin[k] for k in range(3)]
    for item in items:
        if projection is None:
            options = {'node':target['node']}
            if experimental:
                options['experimental'] = True
            progress = profile.behind_progress(snap.memory,target['path'],progress,
                target['lateral'],float(gap),**options)
            point = profile.lane(snap.memory,target['path'],progress,target['lateral'])['point']
            point = [point[k]+residual[k] for k in range(3)]
        else:
            progress,point = projection['progression'],projection['point']
        if not experimental:
            for peer in snap.vehicles.values():
                if peer['id'] != target['id'] and peer.get('initialized') and peer.get('path') == target['path']:
                    if math.dist(point,peer['position']) < 6:
                        raise EditorError('O lote passaria por um veículo existente. Aumente a distância ou mude a referência.')
            if projection is not None and math.dist(point,target['position']) < 6:
                raise EditorError('O ponto está muito próximo da referência. Escolha outro ponto ou use o modo experimental.')
        if not experimental and any(math.dist(point,previous) < 6 for previous in positions):
            raise EditorError('As posições do lote ficaram muito próximas neste caminho.')
        positions.append(point)
        requests.append(dict(manager=spawncode.MANAGER,type_code=item['type'],
            model_hash=item['model_hash'],path_descriptor=profile.PATHS+target['path']*profile.PATH_STRIDE,
            progression=progress,speed=target['speed'],spacing=target['spacing_scalar'],
            variant=item['variant'],secondary_type_code=11 if item['secondary_model_id'] else 0,
            secondary_model_hash=item['secondary_model_hash']))
    keys = list(range(editor.next_key,editor.next_key+count)) if created_keys is None else list(created_keys)
    if len(keys) != count or len(set(keys)) != count or any(type(k) is not int or not 1 <= k <= 10000 for k in keys):
        raise EditorError('Identificadores do lote inválidos.')
    if not getattr(editor,'completion_history_loaded',False):
        from .recovery import known_completion_tokens
        editor.completion_tokens.update(known_completion_tokens(editor.journal_dir))
        editor.completion_history_loaded = True
    for _ in range(32):
        nonce = secrets.token_bytes(16)
        if spawncode.completion_token(nonce) not in editor.completion_tokens:
            break
    else:
        raise EditorError('Não foi possível reservar uma identificação nova para o lote. Nenhuma escrita foi aplicada.')
    payload = spawncode.build_batch(requests,nonce=nonce)
    editor.completion_tokens.add(payload['completion_token'])
    editor._start_recipe(snap)
    editor.recovery_digest = _state_digest(snap)
    editor.pending = BatchPending(payload['scratch_bytes'],payload['hook_bytes'],nonce.hex(),
        model_id,model['model_hash'],model['type'],secondary_model_id,
        secondary['model_hash'] if secondary else 0,target['path'],lateral,
        set(snap.vehicles),editor._reference(target),float(gap),keys,
        [p['address'] for p in payload['probes']],
        (spawncode.DATA-spawncode.CAVE,)+tuple(p['offset']+o for p in payload['probes'] for o in (0,4,8)),
        payload['clean_scratch'],payload['completion_address'],payload['completion_token'],
        (payload['hook_bytes'],payload['hook_bytes'][:4]+spawncode.ORIGINAL[4:],spawncode.ORIGINAL),
        time.monotonic())
    editor.pending.experimental = experimental
    editor.pending.at_point = tuple(at_point) if at_point is not None else None
    editor.pending.items = items
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
        completion_token=payload['completion_token'],format_version=payload['format_version'],
        experimental=experimental,requested_count=reserved,at_point=at_point,
        capacity=dict(counts,colliders=collision_count,endpoints=endpoint_count),
        items=[dict(model_id=item['model_id'],secondary_model_id=item['secondary_model_id'],
                    variant=item['variant'],type_code=item['type']) for item in items],
        progressions=[r['progression'] for r in requests])
    message = f'Lote de {count} preparado. Retome o PCSX2 uma vez e pause novamente para finalizar todos.'
    if projection:
        message += f" Ponto aproximado no caminho {target['path']}; diferença X/Z: {projection['error_distance']:.2f}."
    if experimental:
        message += ' Modo experimental: alto risco de travamento e perda de física.'
    return {'pending':True,'core_paused':True,'message':message}


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


def _wait_for_physics(editor, pending, *, reason, vehicle_ids=(), detail=None):
    """Bound a retired request's actor wait; never modify unconfirmed actors.

    Call only after validating the paused core, owned request, every record's
    completion, original hook and current generation's retirement token. Cleanup
    repeats those ownership checks immediately before touching request bytes.
    """
    now = time.monotonic()
    pending.physics_wait_polls += 1
    fields = dict(reason=reason,vehicle_ids=list(vehicle_ids),
                  physics_wait_polls=pending.physics_wait_polls)
    if detail is not None:
        fields['detail'] = detail
    if pending.physics_wait_started is None:
        pending.physics_wait_started = now
        editor._journal('batch_physics_wait',nonce=pending.nonce,**fields)
    elapsed = max(0.,now-pending.physics_wait_started)
    if elapsed < PHYSICS_WAIT_SECONDS:
        return {'pending':True,'core_paused':True,
            'message':'As solicitações já executaram; aguardando a física do lote por até 5 segundos. '
                      'Se possível, retome brevemente e pause.'}
    editor._cleanup_completed_request(pending,'batch_not_finalized',
        physics_wait_seconds=elapsed,**fields)
    return {'pending':False,'core_paused':True,'warning':True,
        'message':'O lote executou, mas a física não ficou pronta para confirmar o alinhamento. '
                  'Código temporário removido e editor liberado. Os veículos criados pelo jogo foram '
                  'mantidos; este lote não entrou na receita e a fila restante foi cancelada.'}


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
    retired = editor.client.read_many([(pending.completion_address,4)])[0] == pending.completion_token
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
    try:
        snap = editor._snapshot(pending=True)
    except profile.ProfileError as error:
        return _wait_for_physics(editor,pending,reason='profile_not_ready',detail=str(error))
    selected,seen,cold = [],set(),[]
    invalid = False
    expected_items = pending.items or [dict(model_id=pending.model_id,model_hash=pending.model_hash,
        type=pending.type_code,secondary_model_id=pending.secondary_model_id,
        secondary_model_hash=pending.secondary_model_hash,variant=0) for _ in probes]
    if len(expected_items) != len(probes):
        raise EditorError('A descrição do lote não corresponde às solicitações preparadas.')
    for (_state,object_ptr,node_ptr),item in zip(probes,expected_items):
        index = (object_ptr-profile.VEHICLES)//profile.VEHICLE_STRIDE
        row = snap.vehicles.get(index)
        if (not object_ptr or object_ptr != profile.VEHICLES+index*profile.VEHICLE_STRIDE
                or index in pending.old_ids or index in seen or not row
                or row['node'] != node_ptr or row['model_hash'] != item['model_hash']
                or row['type'] != item['type'] or row['path'] != pending.path):
            invalid = True
            break
        seen.add(index)
        if item['secondary_model_id'] is not None:
            child = snap.vehicles.get(row.get('child_id'))
            if (not row.get('native_pair_valid') or not child or child['id'] in pending.old_ids
                    or child['id'] in seen or child['model_hash'] != item['secondary_model_hash']
                    or child['parent_id'] != index or child['type'] != 11 or child['node'] != 0):
                invalid = True
                break
            seen.add(child['id'])
            if not child['initialized']:
                cold.append(child['id'])
            else:
                try:
                    valid = collider_valid(snap.memory,child)
                except profile.ProfileError as error:
                    return _wait_for_physics(editor,pending,reason='profile_not_ready',
                        vehicle_ids=[child['id']],detail=str(error))
                if not valid:
                    invalid = True
                    break
        elif not row['independent']:
            invalid = True
            break
        if not row['initialized']:
            cold.append(row['id'])
        else:
            try:
                valid = collider_valid(snap.memory,row)
            except profile.ProfileError as error:
                return _wait_for_physics(editor,pending,reason='profile_not_ready',
                    vehicle_ids=[row['id']],detail=str(error))
            if not valid:
                invalid = True
                break
        selected.append(row)
    if invalid:
        editor._cleanup_completed_request(pending,'batch_not_finalized',reason='allocation_or_identity_changed')
        return {'pending':False,'core_paused':True,'warning':True,
            'message':'O lote executou, mas uma instância mudou ou não pôde ser validada. '
                      'Código temporário removido; alinhamento e receita não confirmados.'}
    if cold:
        return _wait_for_physics(editor,pending,reason='physics_not_ready',vehicle_ids=cold)
    patches = []
    try:
        for row in selected:
            options = {'experimental':True} if pending.experimental else {}
            patches.extend(profile.lateral_patches(snap,row['id'],pending.lateral*100,**options))
    except profile.ProfileError as error:
        return _wait_for_physics(editor,pending,reason='alignment_not_ready',
            vehicle_ids=[row['id'] for row in selected],detail=str(error))
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
    for row,key,item in zip(selected,pending.created_keys,expected_items):
        editor.actor_keys[row['id']] = key
        editor.replay_ids[key] = row['id']
        operation = {'op':'add_behind','target':target_ref,'model_id':item['model_id'],
            'gap':pending.gap,'created_key':key}
        if pending.at_point is not None:
            operation.pop('gap')
            operation.update(op='add_at',x=pending.at_point[0],z=pending.at_point[1])
        if pending.experimental:
            operation['experimental'] = True
        if item['secondary_model_id'] is not None:
            operation['secondary_model_id'] = item['secondary_model_id']
        if item['variant']:
            operation['variant'] = item['variant']
        editor.recipe.append(operation)
        target_ref = {'kind':'created','key':key}
    editor._journal('batch_finished',nonce=pending.nonce,
        new_vehicle_ids=[row['id'] for row in selected],count=len(selected),
        model_id=pending.model_id,secondary_model_id=pending.secondary_model_id)
    if editor.replay_queue:
        try:
            result = editor._continue_recipe()
        except (EditorError,profile.ProfileError,PineError) as error:
            editor.replay_queue.clear()
            result = {'pending':editor.pending is not None,'warning':True,
                'message':f'O lote anterior foi finalizado, mas a fila foi interrompida: {error}'}
        result.setdefault('new_vehicle_id',selected[-1]['id'])
        result.setdefault('new_vehicle_ids',[row['id'] for row in selected])
        return result
    return {'pending':False,'core_paused':True,'new_vehicle_id':selected[-1]['id'],
        'new_vehicle_ids':[row['id'] for row in selected],
        'message':f'{len(selected)} veículo(s) adicionados e lote finalizado. Pode retomar para testar.'}
