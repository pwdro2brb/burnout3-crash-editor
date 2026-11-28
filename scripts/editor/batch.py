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
    # One entry per request when a batch spans several references (paths):
    # {'path', 'lateral', 'target_ref'}. None keeps the single-chain layout.
    requests_meta: list[dict] | None = None


def reference(snapshot, vehicle_id):
    row = snapshot.vehicles.get(vehicle_id) if type(vehicle_id) is int else None
    if not row or not row.get('can_reference', row.get('editable', False)):
        raise EditorError('Select a vehicle with a valid traffic path to act as the reference.')
    return row


def _occupied(peer):
    """Position of a peer that already occupies its path, or None.

    Distant traffic has no physics points, but its render centre follows the
    path node, so it still blocks a stretch of road.
    """
    if not (peer.get('initialized') or peer.get('far_reference')):
        return None
    position = peer.get('position')
    if (not isinstance(position,(list,tuple)) or len(position) != 3
            or not all(type(v) in (int,float) and math.isfinite(v) for v in position)):
        return None
    return position


def beyond_physics(snapshot, row) -> bool:
    """True when a vehicle is outside the player's physics range (~250 units).

    The game initializes physics points only inside that range, so a new
    vehicle there legitimately stays without physics until the player nears.
    Without a readable player position nothing is assumed.
    """
    player = getattr(snapshot,'player',None)
    position = row.get('position')
    if not isinstance(player,dict) or not isinstance(position,(list,tuple)) or len(position) != 3:
        return False
    origin = player.get('position')
    try:
        values = [float(v) for v in list(position)+list(origin)]
    except (TypeError,ValueError):
        return False
    if len(values) != 6 or not all(math.isfinite(v) for v in values) or not any(values[:3]):
        return False
    return math.dist(values[:3],values[3:]) >= profile.PHYSICS_RANGE


def model_pair(snapshot, model_id, secondary_model_id):
    model = snapshot.models.get(model_id)
    if not model or not model.get('eligible'):
        raise EditorError('Choose a model that is loaded and compatible with this session.')
    secondary = None
    if model.get('type') == 4:
        secondary = snapshot.models.get(secondary_model_id)
        if (not secondary or not secondary.get('eligible_as_trailer')
                or secondary_model_id not in model.get('trailer_model_ids', [])
                or model_id not in secondary.get('truck_model_ids', [])):
            raise EditorError('Choose a trailer whose combination with this cab was observed in the game.')
    elif model.get('type') not in profile.SUPPORTED_SINGLE_TYPES or secondary_model_id is not None:
        raise EditorError('A trailer must be created together with a compatible cab.')
    return model, secondary


def stage(editor, vehicle_id, model_id, gap, count, secondary_model_id=None, *, created_keys=None,
          experimental=False, reserve_count=None, at_point=None, point_reference=False,
          spawn_items=None, reserve_items=None):
    if type(experimental) is not bool:
        raise EditorError('Invalid experimental mode.')
    if type(count) is not int or not 1 <= count <= 8:
        raise EditorError('Choose an amount of 1 to 8 vehicles.')
    if (type(gap) not in (int,float) or not math.isfinite(gap)
            or (gap <= 0 if experimental else not 8 <= gap <= 50)):
        raise EditorError('Use a positive finite distance.' if experimental else
                          'Use a distance between 8 and 50 game units.')
    snap = editor._ready()
    target = reference(snap, vehicle_id)
    model_id = model_id or target['model_id']
    model, secondary = model_pair(snap, model_id, secondary_model_id)
    if spawn_items is None:
        spawn_items = [dict(model_id=model_id,secondary_model_id=secondary_model_id,variant=0) for _ in range(count)]
    if type(spawn_items) not in (list,tuple) or len(spawn_items) != count:
        raise EditorError('The model sequence does not match the batch amount.')
    def prepare(item):
        if (not isinstance(item,dict) or set(item)-{'model_id','secondary_model_id','variant'}
                or type(item.get('variant',0)) is not int or not 0 <= item.get('variant',0) <= 7):
            raise EditorError('Invalid model or visual variant in the sequence.')
        primary,child = model_pair(snap,item.get('model_id'),item.get('secondary_model_id'))
        return dict(model_id=item['model_id'],model_hash=primary['model_hash'],type=primary['type'],
            secondary_model_id=item.get('secondary_model_id'),secondary_model_hash=child['model_hash'] if child else 0,
            variant=item.get('variant',0))
    items = [prepare(item) for item in spawn_items]
    if (items[0]['model_id'] != model_id or items[0]['secondary_model_id'] != secondary_model_id):
        raise EditorError('The first model of the sequence does not match the batch configuration.')
    # Validate the complete future queue before installing its first group.
    if reserve_items is not None and (type(reserve_items) not in (list,tuple) or not count <= len(reserve_items) <= 253):
        raise EditorError('The model sequence reservation is invalid.')
    reserved_items = [prepare(item) for item in reserve_items] if reserve_items is not None else None
    if reserved_items is not None and reserved_items[:count] != items:
        raise EditorError('The start of the reservation does not match the prepared batch.')
    projection = None
    if at_point is not None:
        if count != 1:
            raise EditorError('Add one vehicle or set per chosen point.')
        from .placement import project_target
        projection = project_target(snap,vehicle_id if point_reference else None,*at_point,experimental=experimental)
        if not experimental and projection['error_distance'] > 25:
            raise EditorError('The point is far from the loaded paths. Choose a closer point or use experimental mode.')
        target = reference(snap,projection['reference_id'])
        profile._lane_fraction_word(projection['lateral'])
        if not experimental:
            point_geometry = profile.lane(snap.memory,target['path'],projection['progression'],.5)
            across = point_geometry['lane']
            maximum_shift = max(abs(projection['lateral']),abs(1-projection['lateral']))*math.hypot(across[0],across[2])
            if maximum_shift > 10:
                raise EditorError('The point needs a large lateral offset. Enable experimental mode to try that position.')
    if (not experimental and projection is None and
            (any(item['secondary_model_id'] or item['type'] == 5 for item in items)
             or target.get('native_pair_valid') or target['type'] == 5) and gap < 30):
        raise EditorError('Use a distance of 30 to 50 units for buses or cab-and-trailer sets.')
    reserved = count if reserve_count is None else reserve_count
    if type(reserved) is not int or not count <= reserved <= 253:
        raise EditorError('The amount exceeds the known traffic capacity.')
    if (reserved > count and reserved_items is None and
            any((item['model_id'],item['secondary_model_id']) !=
                (items[0]['model_id'],items[0]['secondary_model_id']) for item in items)):
        raise EditorError('Give the complete sequence to reserve a mixed batch with a queue.')
    if reserved_items is not None and len(reserved_items) != reserved:
        raise EditorError('The reservation does not match the complete batch sequence.')
    if (not experimental and projection is None and reserved_items is not None
            and any(item['secondary_model_id'] or item['type'] == 5 for item in reserved_items) and gap < 30):
        raise EditorError('Use a distance of 30 to 50 units for buses or cab-and-trailer sets.')
    needed = (sum(2 if item['secondary_model_id'] else 1 for item in reserved_items)
              if reserved_items is not None else
              sum(2 if item['secondary_model_id'] else 1 for item in items) if reserved == count else
              reserved*(2 if secondary else 1))
    counts = snap.inspection['counts']
    if (counts['free_objects'] < needed+1 or counts['free_nodes'] < reserved
            or counts['active_objects']+needed+1 > counts['capacity_budget_byte_0x363ab']):
        raise EditorError('The batch exceeds the space available in the traffic pools.')
    collision_count = snap.memory.u32(0x55EF70+0x1CB70)
    endpoint_count = snap.memory.u32(0x55EF70+0x1CB74)
    if (not 0 <= collision_count <= 1224-needed
            or not 0 <= endpoint_count <= 2448-2*needed):
        raise EditorError('The batch exceeds the space available in the collision records.')
    if snap.memory.u8(0x527440+0x363BE):
        raise EditorError('The game is blocking new instances right now.')
    if editor.client.read_bytes(spawncode.HOOK,8) != spawncode.ORIGINAL:
        raise EditorError("The event's code changed. Reload a clean reference.")
    if editor.client.read_bytes(spawncode.CAVE,4096) not in (bytes(4096), spawncode.clean_batch_scratch()):
        raise EditorError('There is a temporary request in memory. Click Finish pending request before creating another batch.')
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
                occupied = _occupied(peer) if peer['id'] != target['id'] and peer.get('path') == target['path'] else None
                if occupied is not None and math.dist(point,occupied) < 6:
                    raise EditorError('The batch would pass through an existing vehicle. Increase the distance or change the reference.')
            if projection is not None and math.dist(point,target['position']) < 6:
                raise EditorError('The point is too close to the reference. Choose another point or use experimental mode.')
        if not experimental and any(math.dist(point,previous) < 6 for previous in positions):
            raise EditorError('The batch positions ended up too close on this path.')
        positions.append(point)
        requests.append(dict(manager=spawncode.MANAGER,type_code=item['type'],
            model_hash=item['model_hash'],path_descriptor=profile.PATHS+target['path']*profile.PATH_STRIDE,
            progression=progress,speed=target['speed'],spacing=target['spacing_scalar'],
            variant=item['variant'],secondary_type_code=11 if item['secondary_model_id'] else 0,
            secondary_model_hash=item['secondary_model_hash']))
    keys = list(range(editor.next_key,editor.next_key+count)) if created_keys is None else list(created_keys)
    if len(keys) != count or len(set(keys)) != count or any(type(k) is not int or not 1 <= k <= 10000 for k in keys):
        raise EditorError('Invalid batch identifiers.')
    if not getattr(editor,'completion_history_loaded',False):
        from .recovery import known_completion_tokens
        editor.completion_tokens.update(known_completion_tokens(editor.journal_dir))
        editor.completion_history_loaded = True
    for _ in range(32):
        nonce = secrets.token_bytes(16)
        if spawncode.completion_token(nonce) not in editor.completion_tokens:
            break
    else:
        raise EditorError('Could not reserve a new identifier for the batch. No write was applied.')
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
            raise EditorError('The batch setup did not check out.')
        editor.client.apply_patch([
            Patch(spawncode.HOOK,4,_word(spawncode.ORIGINAL[:4]),_word(payload['hook_bytes'][:4])),
            Patch(spawncode.HOOK+4,4,_word(spawncode.ORIGINAL[4:]),_word(payload['hook_bytes'][4:]))])
    except Exception:
        editor.unsafe = True
        editor._journal('batch_stage_unconfirmed',nonce=nonce.hex())
        raise EditorError('The batch setup could not be confirmed. Reload the clean reference.')
    editor._journal('batch_staged',nonce=nonce.hex(),model_id=model_id,
        secondary_model_id=secondary_model_id,count=count,gap=float(gap),path=target['path'],
        completion_token=payload['completion_token'],format_version=payload['format_version'],
        experimental=experimental,requested_count=reserved,at_point=at_point,
        capacity=dict(counts,colliders=collision_count,endpoints=endpoint_count),
        items=[dict(model_id=item['model_id'],secondary_model_id=item['secondary_model_id'],
                    variant=item['variant'],type_code=item['type']) for item in items],
        progressions=[r['progression'] for r in requests])
    message = f'Batch of {count} prepared. Resume PCSX2 once and pause again to finish them all.'
    if projection:
        message += f" Point snapped to path {target['path']}; X/Z difference: {projection['error_distance']:.2f}."
    if experimental:
        message += ' Experimental mode: high risk of freezes and lost physics.'
    return {'pending':True,'core_paused':True,'message':message}


def stage_segments(editor, segments, gap, *, experimental=False, reserve=None):
    """Stage one batch that adds vehicles behind several references at once.

    ``segments`` is a list of ``{'vehicle_id', 'items', 'keys'}``: each segment
    is a chain behind its own reference (possibly on different paths). All
    requests still run in one traffic update (at most eight), every position is
    planned before the first write, and the same capacity, hook and spacing
    checks as ``stage`` apply. ``reserve`` = ``(vehicles, objects)`` reserves
    pool space for the queued remainder of a larger request.
    """
    if type(experimental) is not bool:
        raise EditorError('Invalid experimental mode.')
    if (type(gap) not in (int,float) or not math.isfinite(gap)
            or (gap <= 0 if experimental else not 8 <= gap <= 50)):
        raise EditorError('Use a positive finite distance.' if experimental else
                          'Use a distance between 8 and 50 game units.')
    if type(segments) not in (list,tuple) or not segments:
        raise EditorError('Choose at least one reference vehicle.')
    count = sum(len(segment.get('items') or ()) for segment in segments)
    if not 1 <= count <= spawncode.BATCH_MAX_REQUESTS:
        raise EditorError('A batch holds 1 to 8 vehicles; the rest waits in the queue.')
    snap = editor._ready()
    plans = []
    seen_targets = set()
    for segment in segments:
        if not isinstance(segment,dict) or set(segment)-{'vehicle_id','items','keys'}:
            raise EditorError('Invalid batch segment.')
        target = reference(snap,segment.get('vehicle_id'))
        if target['id'] in seen_targets:
            raise EditorError('Each reference vehicle can appear only once in a batch.')
        seen_targets.add(target['id'])
        items = []
        for item in segment.get('items') or ():
            if (not isinstance(item,dict) or set(item)-{'model_id','secondary_model_id','variant'}
                    or type(item.get('variant',0)) is not int or not 0 <= item.get('variant',0) <= 7):
                raise EditorError('Invalid model or visual variant in the sequence.')
            model_id = item.get('model_id') or target['model_id']
            primary,child = model_pair(snap,model_id,item.get('secondary_model_id'))
            items.append(dict(model_id=model_id,model_hash=primary['model_hash'],type=primary['type'],
                secondary_model_id=item.get('secondary_model_id'),
                secondary_model_hash=child['model_hash'] if child else 0,variant=item.get('variant',0)))
        if not items:
            raise EditorError('Each reference needs at least one vehicle.')
        if (not experimental and gap < 30 and
                (any(item['secondary_model_id'] or item['type'] == 5 for item in items)
                 or target.get('native_pair_valid') or target['type'] == 5)):
            raise EditorError('Use a distance of 30 to 50 units for buses or cab-and-trailer sets.')
        plans.append((target,items,segment.get('keys')))
    needed = sum(2 if item['secondary_model_id'] else 1 for _t,items,_k in plans for item in items)
    vehicles_needed,objects_needed = (count,needed) if reserve is None else reserve
    if (type(vehicles_needed) is not int or type(objects_needed) is not int
            or not count <= vehicles_needed <= 253 or not needed <= objects_needed <= 506):
        raise EditorError('The amount exceeds the known traffic capacity.')
    counts = snap.inspection['counts']
    if (counts['free_objects'] < objects_needed+1 or counts['free_nodes'] < vehicles_needed
            or counts['active_objects']+objects_needed+1 > counts['capacity_budget_byte_0x363ab']):
        raise EditorError('The batch exceeds the space available in the traffic pools.')
    collision_count = snap.memory.u32(0x55EF70+0x1CB70)
    endpoint_count = snap.memory.u32(0x55EF70+0x1CB74)
    if (not 0 <= collision_count <= 1224-needed
            or not 0 <= endpoint_count <= 2448-2*needed):
        raise EditorError('The batch exceeds the space available in the collision records.')
    if snap.memory.u8(0x527440+0x363BE):
        raise EditorError('The game is blocking new instances right now.')
    if editor.client.read_bytes(spawncode.HOOK,8) != spawncode.ORIGINAL:
        raise EditorError("The event's code changed. Reload a clean reference.")
    if editor.client.read_bytes(spawncode.CAVE,4096) not in (bytes(4096), spawncode.clean_batch_scratch()):
        raise EditorError('There is a temporary request in memory. Click Finish pending request before creating another batch.')
    # Plan every chain before the first write.
    keys_all = []
    next_key = editor.next_key
    for _target,items,keys in plans:
        if keys is None:
            keys = list(range(next_key,next_key+len(items)))
        keys = list(keys)
        if len(keys) != len(items):
            raise EditorError('Invalid batch identifiers.')
        keys_all.append(keys)
        next_key = max([next_key]+[k+1 for k in keys if type(k) is int])
    flat_keys = [k for keys in keys_all for k in keys]
    if len(set(flat_keys)) != len(flat_keys) or any(type(k) is not int or not 1 <= k <= 10000 for k in flat_keys):
        raise EditorError('Invalid batch identifiers.')
    requests, meta, flat_items, planned_points = [], [], [], []
    for (target,items,_keys),keys in zip(plans,keys_all):
        progress = target['progress']
        origin = profile.lane(snap.memory,target['path'],progress,target['lateral'])['point']
        residual = [target['position'][k]-origin[k] for k in range(3)]
        for index,item in enumerate(items):
            options = {'node':target['node']}
            if experimental:
                options['experimental'] = True
            progress = profile.behind_progress(snap.memory,target['path'],progress,
                target['lateral'],float(gap),**options)
            point = profile.lane(snap.memory,target['path'],progress,target['lateral'])['point']
            point = [point[k]+residual[k] for k in range(3)]
            if not experimental:
                for peer in snap.vehicles.values():
                    occupied = (_occupied(peer) if peer['id'] not in seen_targets
                                and peer.get('path') == target['path'] else None)
                    if occupied is not None and math.dist(point,occupied) < 6:
                        raise EditorError('The batch would pass through an existing vehicle. Increase the distance or change the reference.')
                for other in snap.vehicles.values():
                    if (other['id'] in seen_targets and other['id'] != target['id']
                            and other.get('path') == target['path']):
                        occupied = _occupied(other)
                        if occupied is not None and math.dist(point,occupied) < 6:
                            raise EditorError('A chain would reach another selected vehicle on the same lane. '
                                              'Use fewer vehicles or a shorter distance.')
                if any(path == target['path'] and math.dist(point,previous) < 6
                       for path,previous in planned_points):
                    raise EditorError('The batch positions ended up too close on this path.')
            planned_points.append((target['path'],point))
            requests.append(dict(manager=spawncode.MANAGER,type_code=item['type'],
                model_hash=item['model_hash'],path_descriptor=profile.PATHS+target['path']*profile.PATH_STRIDE,
                progression=progress,speed=target['speed'],spacing=target['spacing_scalar'],
                variant=item['variant'],secondary_type_code=11 if item['secondary_model_id'] else 0,
                secondary_model_hash=item['secondary_model_hash']))
            meta.append(dict(path=target['path'],lateral=target['lateral'],
                target_ref=target if index == 0 else {'kind':'created','key':keys[index-1]}))
            flat_items.append(item)
    if not getattr(editor,'completion_history_loaded',False):
        from .recovery import known_completion_tokens
        editor.completion_tokens.update(known_completion_tokens(editor.journal_dir))
        editor.completion_history_loaded = True
    for _ in range(32):
        nonce = secrets.token_bytes(16)
        if spawncode.completion_token(nonce) not in editor.completion_tokens:
            break
    else:
        raise EditorError('Could not reserve a new identifier for the batch. No write was applied.')
    payload = spawncode.build_batch(requests,nonce=nonce)
    editor.completion_tokens.add(payload['completion_token'])
    editor._start_recipe(snap)
    editor.recovery_digest = _state_digest(snap)
    for request in meta:
        # The first request of each chain targets its reference vehicle; the
        # baseline must exist before a reference is classified.
        if 'kind' not in request['target_ref']:
            request['target_ref'] = editor._reference(request['target_ref'])
    first = flat_items[0]
    editor.pending = BatchPending(payload['scratch_bytes'],payload['hook_bytes'],nonce.hex(),
        first['model_id'],first['model_hash'],first['type'],first['secondary_model_id'],
        first['secondary_model_hash'],meta[0]['path'],meta[0]['lateral'],
        set(snap.vehicles),meta[0]['target_ref'],float(gap),flat_keys,
        [p['address'] for p in payload['probes']],
        (spawncode.DATA-spawncode.CAVE,)+tuple(p['offset']+o for p in payload['probes'] for o in (0,4,8)),
        payload['clean_scratch'],payload['completion_address'],payload['completion_token'],
        (payload['hook_bytes'],payload['hook_bytes'][:4]+spawncode.ORIGINAL[4:],spawncode.ORIGINAL),
        time.monotonic())
    editor.pending.experimental = experimental
    editor.pending.items = flat_items
    editor.pending.requests_meta = meta
    editor.next_key = max(editor.next_key,max(flat_keys)+1)
    try:
        editor.client.write_bytes(spawncode.CAVE,payload['scratch_bytes'])
        if editor.client.read_bytes(spawncode.CAVE,4096) != payload['scratch_bytes']:
            raise EditorError('The batch setup did not check out.')
        editor.client.apply_patch([
            Patch(spawncode.HOOK,4,_word(spawncode.ORIGINAL[:4]),_word(payload['hook_bytes'][:4])),
            Patch(spawncode.HOOK+4,4,_word(spawncode.ORIGINAL[4:]),_word(payload['hook_bytes'][4:]))])
    except Exception:
        editor.unsafe = True
        editor._journal('batch_stage_unconfirmed',nonce=nonce.hex())
        raise EditorError('The batch setup could not be confirmed. Reload the clean reference.')
    editor._journal('batch_staged',nonce=nonce.hex(),model_id=first['model_id'],
        secondary_model_id=first['secondary_model_id'],count=count,gap=float(gap),
        paths=sorted({m['path'] for m in meta}),references=[t['id'] for t,_i,_k in plans],
        completion_token=payload['completion_token'],format_version=payload['format_version'],
        experimental=experimental,requested_count=vehicles_needed,
        capacity=dict(counts,colliders=collision_count,endpoints=endpoint_count),
        items=[dict(model_id=item['model_id'],secondary_model_id=item['secondary_model_id'],
                    variant=item['variant'],type_code=item['type']) for item in flat_items],
        progressions=[r['progression'] for r in requests])
    far = sum(1 for t,_i,_k in plans if not t.get('initialized'))
    message = (f'Batch of {count} behind {len(plans)} reference(s) prepared. '
               'Resume PCSX2 once and pause again to finish them all.')
    if far:
        message += (f' {far} reference(s) are far from the player: their new vehicles start without '
                    'physics and the game turns it on when you get close.')
    if experimental:
        message += ' Experimental mode: high risk of freezes and lost physics.'
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
            'message':"The requests already ran; waiting up to 5 seconds for the batch's physics. "
                      'If possible, resume briefly and pause.'}
    editor._cleanup_completed_request(pending,'batch_not_finalized',
        physics_wait_seconds=elapsed,**fields)
    return {'pending':False,'core_paused':True,'warning':True,
        'message':'The batch ran, but physics was not ready to confirm the alignment. '
                  'Temporary code removed and editor released. The vehicles created by the game were '
                  'kept; this batch was not added to the recipe and the rest of the queue was cancelled.'}


def poll(editor):
    pending = editor.pending
    if editor.unsafe:
        raise EditorError('Reload a clean reference; the previous batch will not be repeated.')
    editor._identity()
    status = editor.client.status()
    if status is Status.SHUTDOWN:
        raise EditorError('The game was closed. The batch will not be repeated.')
    values = editor.client.read_many([(p+o,4) for p in pending.probes for o in (0,4,8)])
    probes = [values[i:i+3] for i in range(0,len(values),3)]
    complete = sum(p[0] == 2 for p in probes)
    retired = editor.client.read_many([(pending.completion_address,4)])[0] == pending.completion_token
    if status is not Status.PAUSED:
        return {'pending':True,'core_paused':False,
            'message':f'{complete}/{len(probes)} requests ran. '
                + ('Pause now to finish before driving.' if complete == len(probes)
                   else 'Start/resume the event to run the batch.')}
    hook,scratch = editor.client.read_bytes(spawncode.HOOK,8),editor.client.read_bytes(spawncode.CAVE,4096)
    if hook == spawncode.ORIGINAL and scratch in (bytes(4096), pending.clean_scratch):
        editor.pending = None
        editor.replay_queue.clear()
        return {'pending':False,'core_paused':True,'warning':True,
            'message':'The state was reloaded; the pending batch was cancelled.'}
    editor._validate_pending_bytes(pending,hook,scratch)
    if complete != len(probes) or not retired:
        return {'pending':True,'core_paused':True,
            'message':'Resume the event for a moment to run all the requests of the batch.'}
    if hook != spawncode.ORIGINAL:
        raise EditorError("The batch finished without restoring the game's entry. Reload a clean reference.")
    try:
        snap = editor._snapshot(pending=True)
    except profile.ProfileError as error:
        return _wait_for_physics(editor,pending,reason='profile_not_ready',detail=str(error))
    selected,seen,cold,far = [],set(),[],set()
    invalid = False
    expected_items = pending.items or [dict(model_id=pending.model_id,model_hash=pending.model_hash,
        type=pending.type_code,secondary_model_id=pending.secondary_model_id,
        secondary_model_hash=pending.secondary_model_hash,variant=0) for _ in probes]
    meta = getattr(pending,'requests_meta',None) or [dict(path=pending.path,lateral=pending.lateral)
                                                     for _ in probes]
    if len(expected_items) != len(probes) or len(meta) != len(probes):
        raise EditorError('The batch description does not match the prepared requests.')
    for (_state,object_ptr,node_ptr),item,request in zip(probes,expected_items,meta):
        index = (object_ptr-profile.VEHICLES)//profile.VEHICLE_STRIDE
        row = snap.vehicles.get(index)
        if (not object_ptr or object_ptr != profile.VEHICLES+index*profile.VEHICLE_STRIDE
                or index in pending.old_ids or index in seen or not row
                or row['node'] != node_ptr or row['model_hash'] != item['model_hash']
                or row['type'] != item['type'] or row['path'] != request['path']):
            invalid = True
            break
        seen.add(index)
        # Outside the player's physics range the game keeps new traffic on its
        # path node only; that is the expected state, not a failed creation.
        distant = not row['initialized'] and beyond_physics(snap,row)
        if distant:
            far.add(index)
        if item['secondary_model_id'] is not None:
            child = snap.vehicles.get(row.get('child_id'))
            if (not row.get('native_pair_valid') or not child or child['id'] in pending.old_ids
                    or child['id'] in seen or child['model_hash'] != item['secondary_model_hash']
                    or child['parent_id'] != index or child['type'] != 11 or child['node'] != 0):
                invalid = True
                break
            seen.add(child['id'])
            if not child['initialized'] and not distant:
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
        if not row['initialized'] and not distant:
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
            'message':'The batch ran, but an instance changed or could not be validated. '
                      'Temporary code removed; alignment and recipe not confirmed.'}
    if cold:
        return _wait_for_physics(editor,pending,reason='physics_not_ready',vehicle_ids=cold)
    patches = []
    try:
        for row,request in zip(selected,meta):
            options = {'experimental':True} if pending.experimental else {}
            align = profile.far_lateral_patches if row['id'] in far else profile.lateral_patches
            patches.extend(align(snap,row['id'],request['lateral']*100,**options))
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
        raise EditorError('The batch finish could not be confirmed. Reload the clean reference.')
    editor.pending = None
    target_ref = pending.target_ref
    for row,key,item,request in zip(selected,pending.created_keys,expected_items,meta):
        editor.actor_keys[row['id']] = key
        editor.replay_ids[key] = row['id']
        target_ref = request.get('target_ref',target_ref)
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
        model_id=pending.model_id,secondary_model_id=pending.secondary_model_id,
        distant_vehicle_ids=sorted(far))
    if editor.replay_queue:
        try:
            result = editor._continue_recipe()
        except (EditorError,profile.ProfileError,PineError) as error:
            editor.replay_queue.clear()
            result = {'pending':editor.pending is not None,'warning':True,
                'message':f'The previous batch was finished, but the queue was interrupted: {error}'}
        result.setdefault('new_vehicle_id',selected[-1]['id'])
        result.setdefault('new_vehicle_ids',[row['id'] for row in selected])
        return result
    message = f'{len(selected)} vehicle(s) added and batch finished. You can resume to test.'
    if far:
        message += (f' {len(far)} of them are far from the player and have no physics yet; '
                    'the game turns it on when you get within about 250 units.')
    return {'pending':False,'core_paused':True,'new_vehicle_id':selected[-1]['id'],
        'new_vehicle_ids':[row['id'] for row in selected],'message':message}
