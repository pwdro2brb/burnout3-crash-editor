"""Bounded, read-only USA traffic snapshots and lateral placement estimates.

The memory adapter reads only requested physical EE RAM, not a 32 MiB dump.
Geometry is a double-precision reconstruction of the observed path spline;
the game still owns later orientation, contact and dependent-cache updates.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct
from typing import Any

from runtime.inspect_savestate import (
    inspect_memory, index_for_pointer, MANAGER, VEHICLES, VEHICLE_STRIDE,
    NODES, NODE_STRIDE, MATRICES, MATRIX_STRIDE, POOL_COUNT, ORIGINAL_WORDS,
)
from .catalog import classify_model
from .pine import Patch, Status, RAM_SIZE

MODEL_IDS = MANAGER + 0x34390
MODEL_POINTERS = MANAGER + 0x343F0
MODEL_COUNT = MANAGER + 0x34450
PATHS = 0x52288C
PATH_STRIDE = 0x4C
EPILOGUE = 0x166D6C
EPILOGUE_ORIGINAL = bytes.fromhex('0800b6c79000be7b')
EDITOR_JUMP = struct.pack('<II', 0x08000000 | (0xB3000 >> 2), 0)
PLAYER_TRANSFORM_POINTER = 0x64D388
TRAILER_CATEGORIES = {'freight_container', 'flatbed', 'lumber_trailer', 'tanker', 'covered_trailer'}
SUPPORTED_SINGLE_TYPES = frozenset((1, 2, 3, 5))


class ProfileError(ValueError):
    pass


class CachedMemory:
    """A bounded sparse snapshot, with lazy 4 KiB pages for model/path data.

    Caching is per snapshot. Callers must discard it before the next operation.
    Core pause is checked by snapshot(), not by this low-level read adapter.
    """
    def __init__(self, client):
        self.client = client
        self._regions: list[tuple[int, bytes]] = []
        self.bytes_fetched = 0

    @staticmethod
    def _bounds(address: int, size: int) -> None:
        if type(address) is not int or type(size) is not int or address < 0 or size < 0 or address + size > RAM_SIZE:
            raise ProfileError('Endereço de memória fora do perfil admitido.')

    def preload(self, address: int, size: int) -> None:
        self._bounds(address, size)
        data = self.client.read_bytes(address, size)
        if not isinstance(data, (bytes, bytearray)) or len(data) != size:
            raise ProfileError('Leitura incompleta da memória do jogo.')
        self._regions.append((address, bytes(data)))
        self.bytes_fetched += size

    def read_bytes(self, address: int, size: int) -> bytes:
        self._bounds(address, size)
        if size == 0:
            return b''
        for start, data in reversed(self._regions):
            if start <= address and address + size <= start + len(data):
                return data[address-start:address-start+size]
        start = address & ~0xFFF
        end = min(RAM_SIZE, (address + size + 0xFFF) & ~0xFFF)
        # One request may cross a page; do not silently substitute zero holes.
        self.preload(start, end-start)
        return self._regions[-1][1][address-start:address-start+size]

    def read(self, address: int, format_: str):
        if not format_.startswith('<'):
            raise ProfileError('O perfil usa somente leituras little-endian explícitas.')
        return struct.unpack(format_, self.read_bytes(address, struct.calcsize(format_)))

    def u8(self, address: int) -> int:
        return self.read(address, '<B')[0]

    def u32(self, address: int) -> int:
        return self.read(address, '<I')[0]

    def xyz(self, address: int) -> list[float]:
        return list(self.read(address, '<3f'))


def _finite(values) -> bool:
    return all(math.isfinite(v) for v in values)


@dataclass
class Snapshot:
    memory: CachedMemory
    inspection: dict[str, Any]
    vehicles: dict[int, dict[str, Any]]
    models: dict[str, dict[str, Any]]
    core_paused: bool
    player: dict[str, list[float]] | None = None

    def public(self) -> dict[str, Any]:
        vehicles = []
        for index, row in sorted(self.vehicles.items()):
            model = self.models[row['model_id']]
            reason = None
            if row['can_edit_compound']:
                reason = None
            elif row.get('parent_id') is not None:
                reason = 'Carga vinculada: selecione a cabine para editar o conjunto.'
            elif row.get('kind') == 'truck':
                if row.get('node_index') is None or not row.get('path_valid'):
                    reason = 'A cabine não tem um caminho de tráfego válido para reposicionar o conjunto.'
                else:
                    reason = 'O conjunto ainda não tem física ou formato validado para reposicionamento.'
            elif not row['independent']:
                reason = 'Este componente vinculado não pode ser editado isoladamente.'
            elif row['type'] not in SUPPORTED_SINGLE_TYPES:
                reason = 'Este tipo de veículo ainda não está habilitado para edição.'
            elif not row['initialized']:
                reason = 'O jogo ainda não inicializou os pontos físicos deste veículo.'
            elif row.get('node_index') is None:
                reason = 'O veículo não tem um nó de tráfego; mover pela largura da via não está disponível.'
            elif row.get('path') in (None, 0xFF):
                reason = 'O veículo não está associado a um caminho de tráfego válido.'
            elif not row['editable']:
                reason = 'A posição ou os parâmetros do caminho não passaram na validação; a direção do jogador não é um filtro.'
            reference_reason = None
            if not row['can_reference']:
                reference_reason = reason or 'Os parâmetros nativos de velocidade ou espaçamento não permitem criar um lote nesta referência.'
            public_row = {
                'id': index, 'label': f"Veículo {index} — {model['label']}",
                'model_id': row['model_id'], 'type_label': model['type_label'],
                'position': list(row['position']), 'path': row['path'],
                'progress': row['progress'],
                'lateral_percent': None if row['lateral'] is None else 100 * row['lateral'],
                'editable': row['editable'], 'independent': row['independent'],
                'experimental_editable': can_move_experimental(self.vehicles,row),
                'edit_reason': reason,
                'initialized': row['initialized'],
                'kind': row['kind'], 'parent_id': row['parent_id'], 'child_id': row['child_id'],
                'parent_model_id': row['parent_model_id'], 'child_model_id': row['child_model_id'],
                'secondary_model_id': row['secondary_model_id'],
                'native_pair_valid': row['native_pair_valid'],
                'can_reference': row['can_reference'],
                'reference_reason': reference_reason,
                'can_edit_compound': row['can_edit_compound'],
                'can_add': row['can_reference'] and model['eligible'],
            }
            if self.player and _finite(row['position']):
                public_row['distance_to_player'] = math.dist(row['position'], self.player['position'])
            vehicles.append(public_row)
        models = [{k: row[k] for k in ('id', 'label', 'type_label', 'verified', 'eligible',
                  'kind', 'type', 'eligible_as_trailer', 'trailer_model_ids', 'truck_model_ids',
                  'native_pair_valid')}
                  for row in self.models.values()]
        result = {'vehicles': vehicles, 'models': models,
                'status': 'Jogo pausado' if self.core_paused else 'Pause o jogo no PCSX2 para editar.',
                'core_paused': self.core_paused}
        if self.player:
            result['player'] = {key: list(value) for key, value in self.player.items()}
        return result


def _player(memory: CachedMemory) -> dict[str, list[float]] | None:
    """Optional current player transform; absence must not block traffic reads."""
    pointer = memory.u32(PLAYER_TRANSFORM_POINTER)
    if not pointer or pointer % 16 or pointer > RAM_SIZE-0x40:
        return None
    position, forward = memory.xyz(pointer+0x30), memory.xyz(pointer+0x20)
    if not _finite(position+forward) or any(abs(v) > 1_000_000 for v in position):
        return None
    if not 0.5 <= math.sqrt(sum(v*v for v in forward)) <= 1.5:
        return None
    return {'position': position, 'forward': forward}


def _compound_metadata(vehicles, models):
    """Recognize loaded native 4+11 pairs and the guarded placement layout.

    Model compatibility is demonstrated by actual reciprocal native pairs,
    not inferred from a category label or the presence of unrelated trailers.
    Zero/uninitialized physics may prove a model pairing but cannot be used
    as a placement reference. The controller still verifies path direction.
    """
    members = {name: [] for name in models}
    for row in vehicles.values():
        members[row['model_id']].append(row)
        parent, child = vehicles.get(row['parent_id']), vehicles.get(row['child_id'])
        row['parent_model_id'] = parent['model_id'] if parent else None
        row['child_model_id'] = child['model_id'] if child else None
        row['secondary_model_id'] = None
        row['native_pair_valid'] = False
        row['can_edit_compound'] = False
        row['can_reference'] = row['editable'] and _reference_parameters_ready(row)
    for primary in vehicles.values():
        child = vehicles.get(primary['child_id'])
        if not child:
            continue
        truck, trailer = models[primary['model_id']], models[child['model_id']]
        valid = (truck['kind'] == 'truck' and trailer['kind'] == 'trailer'
            and truck['verified'] and trailer['verified']
            and truck['observed_types'] == {4} and trailer['observed_types'] == {11}
            and primary['type'] == 4 and child['type'] == 11
            and primary['parent_id'] is None and child['child_id'] is None
            and child['parent_id'] == primary['id']
            and primary['node_index'] is not None and child['node'] == 0)
        if not valid:
            continue
        primary['native_pair_valid'] = child['native_pair_valid'] = True
        primary['secondary_model_id'] = child['model_id']
        primary['can_edit_compound'] = _compound_layout_ready(primary, child)
        primary['editable'] = primary['can_edit_compound']
        primary['can_reference'] = (primary['can_edit_compound']
            and _reference_parameters_ready(primary))
        truck['trailer_model_ids'].add(child['model_id'])
        trailer['truck_model_ids'].add(primary['model_id'])
    for name, model in models.items():
        observed = model['observed_types']
        if model['verified'] and len(observed) == 1:
            model['type'] = next(iter(observed))
        if model['kind'] == 'independent':
            model['eligible'] = (model['verified'] and len(observed) == 1
                and observed <= SUPPORTED_SINGLE_TYPES and model['independent_observed_types'] == observed)
        else:
            model['native_pair_valid'] = bool(members[name]) and all(row['native_pair_valid'] for row in members[name])
            model['eligible'] = model['kind'] == 'truck' and observed == {4} and model['native_pair_valid']
            model['eligible_as_trailer'] = model['kind'] == 'trailer' and observed == {11} and model['native_pair_valid']
        model['observed_types'] = sorted(observed)
        model['independent_observed_types'] = sorted(model['independent_observed_types'])
        model['trailer_model_ids'] = sorted(model['trailer_model_ids'])
        model['truck_model_ids'] = sorted(model['truck_model_ids'])


def _reference_parameters_ready(row):
    """A stopped traffic controller can still describe a native creation path.

    Direction belongs to the selected path and saved forward axis, not to the
    player's heading. behind_progress separately checks that alignment.
    """
    values = [row['speed'],row['travel_speed'],row['spacing_scalar']]
    return (_finite(values) and 0 <= values[0] <= 240 and values[1] >= 0
            and 0 <= values[2] <= 10000)


def _compound_layout_ready(primary, child):
    if not (primary['native_pair_valid'] and child['native_pair_valid']
            and primary['type'] == 4 and child['type'] == 11
            and primary['parent_id'] is None and child['child_id'] is None
            and primary['child_id'] == child['id'] and child['parent_id'] == primary['id']
            and primary['node_index'] is not None and child['node'] == 0
            and primary['initialized'] and child['initialized'] and primary['path_valid']):
        return False
    # Type 11 derives its front/hitch from the parent in FUN_00172070. Its
    # unused first anchor must retain the observed null layout; only rear and
    # rendered center receive the same X/Z translation as the tractor.
    if child['anchor0'] != [0.0, 0.0, 0.0]:
        return False
    if not _finite(child['anchor1']+child['position']+primary['body_forward']
                   +[primary['hitch_offset'], child['front_offset'], child['rear_offset']]):
        return False
    if any(math.sqrt(sum(v*v for v in point)) <= 1e-6 for point in (child['anchor1'], child['position'])):
        return False
    hitch = [primary['position'][k]+primary['body_forward'][k]*primary['hitch_offset'] for k in range(3)]
    return math.dist(hitch, child['anchor1']) > 1e-6


def snapshot(client, require_paused: bool = True, *, allow_editor_hook: bool = False) -> Snapshot:
    """Read this profile while paused and reject inconsistent or patched pools.

    A pause check is not an atomic transaction with a concurrent user's resume.
    The transport/controller must also guard writes and compare expected bytes.
    """
    start_status = client.status()
    if start_status is Status.SHUTDOWN:
        raise ProfileError('Carregue um evento antes de conectar o editor.')
    if require_paused and start_status is not Status.PAUSED:
        raise ProfileError('Pause pelo Esc do PCSX2 antes de editar; o menu do jogo não basta.')
    memory = CachedMemory(client)
    memory.preload(VEHICLES, 0x55B900 - VEHICLES)
    memory.preload(MANAGER + 0x362E0, 0x120)
    for address in ORIGINAL_WORDS:
        memory.preload(address, 4)
    memory.preload(EPILOGUE, 8)
    checks = inspect_memory(memory, POOL_COUNT)
    if not checks['candidate_structure_consistent']:
        raise ProfileError('As estruturas de tráfego deste estado não passaram na verificação.')
    if not all(checks['original_code_word_matches'].values()):
        raise ProfileError('Este estado contém alterações de código incompatíveis com o editor.')
    epilogue = memory.read_bytes(EPILOGUE, 8)
    if epilogue != EPILOGUE_ORIGINAL and not (allow_editor_hook and epilogue == EDITOR_JUMP):
        if epilogue == EDITOR_JUMP:
            raise ProfileError('Há uma criação pendente de outra sessão do editor neste estado. '
                               'Recarregue a referência anterior à criação e conecte novamente.')
        raise ProfileError('Há uma alteração de código não reconhecida na atualização do tráfego.')
    model_count = memory.u8(MODEL_COUNT)
    if not 1 <= model_count <= 12:
        raise ProfileError('A tabela de modelos não corresponde ao perfil pesquisado.')
    models: dict[str, dict[str, Any]] = {}
    by_index = {}
    for index in range(model_count):
        value = memory.read(MODEL_IDS + index*8, '<Q')[0]
        pointer = memory.u32(MODEL_POINTERS + index*4)
        if not 0 < pointer < RAM_SIZE - 0xEA0:
            raise ProfileError('Modelo carregado aponta para fora da memória admitida.')
        try:
            info = classify_model(value)
        except ValueError as error:
            raise ProfileError('Identificador de modelo inválido neste estado.') from error
        name = info['asset_id']
        if not name or name in models:
            raise ProfileError('A tabela de modelos tem entradas ambíguas.')
        row = {'id': name, 'model_id': name, 'model_hash': value, 'model_pointer': pointer,
               'model_index': index, 'label': info['label'], 'type_label': info['category_label'],
               'category': info['category'], 'verified': info['verified'], 'eligible': False,
               'type': None, 'observed_types': set(), 'independent_observed_types': set(),
               'kind': 'truck' if info['category'] == 'big_rig' else
                       'trailer' if info['category'] in TRAILER_CATEGORIES else 'independent',
               'eligible_as_trailer': False, 'trailer_model_ids': set(), 'truck_model_ids': set(),
               'native_pair_valid': False}
        models[name] = row
        by_index[index] = row
    vehicles = {}
    for example in checks['examples']:
        index = example['vehicle_index']
        address = VEHICLES + index*VEHICLE_STRIDE
        model_index = memory.u8(address + 0x176)
        model = by_index.get(model_index)
        if model is None or memory.u32(address + 0xB0) != model['model_pointer']:
            raise ProfileError('Um veículo ativo não corresponde à tabela de modelos carregados.')
        type_ = memory.u8(address + 0x173)
        parent, child = memory.u32(address+0x10C), memory.u32(address+0x110)
        independent = not (parent or child)
        node = memory.u32(address+0x114)
        node_index = index_for_pointer(node, NODES, NODE_STRIDE) if node else None
        anchor0, anchor1, position = (memory.xyz(address+o) for o in (0, 0x30, 0xA0))
        initialized = _finite(anchor0 + anchor1 + position) and math.dist(anchor0, anchor1) > 1e-6
        if type_ in (3, 5):
            # Newly admitted native single-body classes require both physical
            # points and render center, not a partial zero/real-anchor layout.
            initialized = initialized and all(any(v != 0 for v in point)
                for point in (anchor0, anchor1, position))
        progress = lateral = path = None
        speed = travel_speed = spacing_scalar = 0.0
        if node_index is not None:
            progress, lateral = memory.read(node+0x30, '<2f')
            path = memory.u8(node+0x41)
            speed = memory.read(node, '<f')[0]
            travel_speed = memory.read(node+0x2C, '<f')[0]
            spacing_scalar = memory.read(node+0x24, '<f')[0]
        path_valid = node_index is not None and path != 0xFF and _finite([progress, lateral, speed, travel_speed, spacing_scalar]) and 0 <= lateral <= 1 and progress >= 0
        # These native independent types share the two-anchor/body layout.
        # Special 6..10 types have separate flags, links and collider behavior.
        editable = type_ in SUPPORTED_SINGLE_TYPES and independent and initialized and path_valid
        vehicles[index] = {'id': index, 'address': address, 'node': node,
                           'node_index': node_index, 'path': path, 'progress': progress,
                           'lateral': lateral, 'type': type_, 'model_id': model['id'],
                           'model_hash': model['model_hash'], 'model_pointer': model['model_pointer'],
                           'model_index': model_index, 'position': position,
                           'anchor0': anchor0, 'anchor1': anchor1, 'independent': independent,
                           'body_forward': memory.xyz(address+0x90),
                           'hitch_offset': memory.read(address+0x134, '<f')[0],
                           'front_offset': memory.read(address+0x138, '<f')[0],
                           'rear_offset': memory.read(address+0x14C, '<f')[0],
                           'initialized': initialized, 'editable': editable,
                           'kind': model['kind'], 'path_valid': path_valid,
                           'parent_id': index_for_pointer(parent, VEHICLES, VEHICLE_STRIDE) if parent else None,
                           'child_id': index_for_pointer(child, VEHICLES, VEHICLE_STRIDE) if child else None,
                           'speed': speed, 'travel_speed': travel_speed,
                           'spacing_scalar': spacing_scalar}
        model['observed_types'].add(type_)
        if independent:
            model['independent_observed_types'].add(type_)
    _compound_metadata(vehicles, models)
    player = _player(memory)
    final_status = client.status()
    if final_status is not start_status or (require_paused and final_status is not Status.PAUSED):
        raise ProfileError('O estado de pausa mudou durante a leitura; pause e atualize a lista.')
    return Snapshot(memory, checks, vehicles, models, start_status is Status.PAUSED, player)


def lane(memory, path: int, progress: float, lateral: float) -> dict[str, Any]:
    """Estimate spline position, cross-lane vector and increasing-path tangent."""
    if type(path) is not int or not 0 <= path < 255 or not _finite([progress, lateral]) or not 0 <= lateral <= 1:
        raise ProfileError('Caminho ou posição lateral inválidos.')
    descriptor = PATHS + path*PATH_STRIDE
    if memory.u8(descriptor+0x47) != path:
        raise ProfileError('O descritor do caminho não corresponde ao veículo selecionado.')
    geometry = memory.u32(descriptor)
    if not 0 < geometry < RAM_SIZE - 0x14:
        raise ProfileError('Geometria de caminho ausente.')
    pairs, vertices, count = memory.u32(geometry), memory.u32(geometry+0xC), memory.u32(geometry+0x10)
    if not 2 <= count <= 65536 or not 0 <= progress <= count-1:
        raise ProfileError('A posição está fora do caminho carregado.')
    if not 0 < pairs <= RAM_SIZE-count*4 or not 0 < vertices < RAM_SIZE-16:
        raise ProfileError('Geometria de caminho fora da memória admitida.')
    segment = min(int(progress), count-2)
    t = progress-segment
    weights = [(1-t)**3/6, (3*t**3-6*t*t+4)/6,
               (-3*t**3+3*t*t+3*t+1)/6, t**3/6]
    derivative_weights = [-(1-t)**2/2, (9*t*t-12*t)/6,
                          (-9*t*t+6*t+3)/6, t*t/2]
    sides = [[], []]
    for k in range(4):
        pair_index = max(0, min(count-1, segment+k-1))
        for side, vertex in enumerate(memory.read(pairs+pair_index*4, '<2H')):
            point = memory.xyz(vertices+vertex*16)
            if not _finite(point):
                raise ProfileError('O caminho contém coordenadas inválidas.')
            sides[side].append(point)
    boundaries = [[sum(weights[k]*points[k][axis] for k in range(4)) for axis in range(3)] for points in sides]
    tangents = [[sum(derivative_weights[k]*points[k][axis] for k in range(4)) for axis in range(3)] for points in sides]
    across = [b-a for a,b in zip(*boundaries)]
    point = [boundaries[0][axis]+lateral*across[axis] for axis in range(3)]
    derivative = [(1-lateral)*tangents[0][axis]+lateral*tangents[1][axis] for axis in range(3)]
    width = math.sqrt(sum(x*x for x in across))
    if not 1e-6 < width <= 100 or not _finite(point+derivative):
        raise ProfileError('A largura ou orientação do caminho é inválida.')
    return {'point': point, 'lane': across, 'derivative': derivative,
            'count': count, 'width': width, 'descriptor': descriptor}


def _arc(memory, path, lo, hi, lateral, samples=64):
    previous = lane(memory, path, lo, lateral)['point']
    distance = 0.0
    for i in range(1, samples+1):
        point = lane(memory, path, lo+(hi-lo)*i/samples, lateral)['point']
        distance += math.dist(previous, point)
        previous = point
    return distance


def behind_progress(memory, path: int, progress: float, lateral: float, gap: float, *, node: int | None = None, experimental: bool = False) -> float:
    """Find a lower path parameter roughly `gap` game units behind.

    Pass the selected node to also verify finite nonnegative travel and agreement
    between its saved path-forward axis and the increasing spline parameter.
    """
    if type(experimental) is not bool:
        raise ProfileError('Modo experimental inválido.')
    if (type(gap) not in (int,float) or not math.isfinite(gap)
            or (gap <= 0 if experimental else not 2 <= gap <= 50)):
        raise ProfileError('Use uma distância positiva finita.' if experimental else
                           'A distância precisa estar entre 2 e 50 unidades do jogo.')
    origin = lane(memory, path, progress, lateral)
    if node is not None:
        ni = index_for_pointer(node, NODES, NODE_STRIDE)
        if ni is None:
            raise ProfileError('O veículo não tem um nó válido neste caminho.')
        speed = memory.read(node+0x2C, '<f')[0]
        if not math.isfinite(speed) or speed < 0 or memory.u8(node+0x41) != path:
            raise ProfileError('A referência precisa de avanço não negativo e do mesmo caminho de tráfego.')
        forward = memory.xyz(MATRICES+ni*MATRIX_STRIDE+0x20)
        derivative = origin['derivative']
        norms = math.sqrt(sum(x*x for x in forward))*math.sqrt(sum(x*x for x in derivative))
        if norms <= 1e-9 or sum(a*b for a,b in zip(forward, derivative))/norms < 0.5:
            raise ProfileError('Não foi possível confirmar a direção do caminho deste veículo.')
    lo, hi = max(0.0, progress-64.0), progress
    while experimental and lo > 0 and _arc(memory,path,lo,hi,lateral) < gap:
        lo = max(0.0,progress-2*(progress-lo))
    if _arc(memory, path, lo, hi, lateral) < gap:
        raise ProfileError('Não há comprimento de caminho suficiente atrás do veículo.')
    for _ in range(36):
        mid = (lo+hi)/2
        if _arc(memory, path, mid, progress, lateral) > gap:
            lo = mid
        else:
            hi = mid
    return (lo+hi)/2


def can_move_experimental(vehicles, row) -> bool:
    """Allow a known physical layout to return from an extrapolated lane."""
    if (row.get('node_index') is None or type(row.get('path')) is not int or row['path'] == 0xFF
            or not _finite([row.get('progress',float('nan')),row.get('lateral',float('nan'))])
            or row['progress'] < 0 or not row.get('initialized')):
        return False
    if row['type'] in SUPPORTED_SINGLE_TYPES and row['independent']:
        return True
    if row.get('kind') == 'truck':
        child = vehicles.get(row.get('child_id'))
        return bool(child and _compound_layout_ready(dict(row,path_valid=True),child))
    return False


def _lane_fraction_word(target):
    try:
        packed = struct.pack('<f',target)
        if not math.isfinite(struct.unpack('<f',packed)[0]):
            raise ValueError('nonfinite')
    except (OverflowError,ValueError,struct.error) as error:
        raise ProfileError('A fração lateral está fora do intervalo float32 finito.') from error
    return struct.unpack('<I',packed)[0]


def lateral_patches(state: Snapshot, vehicle_id: int, lateral_percent: float, *, experimental: bool = False) -> list[Patch]:
    """Prepare six X/Z changes plus the node fraction; never write memory."""
    if type(vehicle_id) is not int or vehicle_id not in state.vehicles:
        raise ProfileError('Selecione um veículo válido da lista atual.')
    if (type(experimental) is not bool or type(lateral_percent) not in (int, float)
            or not math.isfinite(lateral_percent) or (not experimental and not 0 <= lateral_percent <= 100)):
        raise ProfileError('A posição lateral precisa estar entre 0% e 100%.')
    row = state.vehicles[vehicle_id]
    if row['kind'] == 'truck':
        return compound_lateral_patches(state, vehicle_id, lateral_percent,experimental=experimental)
    if not row['editable'] and not (experimental and can_move_experimental(state.vehicles,row)):
        raise ProfileError('Este veículo ainda não tem física independente pronta para edição.')
    target = lateral_percent/100.0
    target_word = _lane_fraction_word(target)
    geometry = lane(state.memory, row['path'], row['progress'], .5 if experimental else row['lateral'])
    delta = [(target-row['lateral'])*value for value in geometry['lane']]
    if not experimental and math.hypot(delta[0], delta[2]) > 10:
        raise ProfileError('O deslocamento solicitado excede o limite deste protótipo.')
    patches = []
    for offset in (0, 0x30, 0xA0):
        for axis in (0, 2):
            address = row['address']+offset+axis*4
            original = state.memory.read(address, '<f')[0]
            value = original+delta[axis]
            try:
                packed = struct.pack('<f', value)
            except (OverflowError, struct.error) as error:
                raise ProfileError('Coordenada fora do intervalo permitido.') from error
            if not math.isfinite(struct.unpack('<f', packed)[0]):
                raise ProfileError('Coordenada não finita.')
            patches.append(Patch(address, 4, state.memory.u32(address), struct.unpack('<I', packed)[0]))
    address = row['node']+0x34
    patches.append(Patch(address, 4, state.memory.u32(address), target_word))
    return patches


def compound_lateral_patches(state: Snapshot, primary_id: int, lateral_percent: float, *, experimental: bool = False) -> list[Patch]:
    """Prepare eleven guarded floats for a native tractor/type-11 pair.

    Static reconstruction identifies the trailer rear/center and derived hitch.
    This preserves the null first trailer anchor, all Y coordinates, linkage,
    orientation and caches. Runtime movement/collision still need validation.
    """
    if type(primary_id) is not int or primary_id not in state.vehicles:
        raise ProfileError('Selecione uma cabine ativa do conjunto.')
    if (type(experimental) is not bool or type(lateral_percent) not in (int, float)
            or not math.isfinite(lateral_percent) or (not experimental and not 0 <= lateral_percent <= 100)):
        raise ProfileError('A posição lateral precisa estar entre 0% e 100%.')
    primary = state.vehicles[primary_id]
    child = state.vehicles.get(primary['child_id'])
    checked_primary = dict(primary,path_valid=True) if experimental and can_move_experimental(state.vehicles,primary) else primary
    if not child or not _compound_layout_ready(checked_primary, child):
        raise ProfileError('A cabine e a carga não têm o vínculo e os pontos físicos admitidos para mover o conjunto.')
    target = lateral_percent/100.0
    target_word = _lane_fraction_word(target)
    geometry = lane(state.memory, primary['path'], primary['progress'], .5 if experimental else primary['lateral'])
    delta = [(target-primary['lateral'])*value for value in geometry['lane']]
    if not experimental and math.hypot(delta[0], delta[2]) > 10:
        raise ProfileError('O deslocamento solicitado excede o limite deste protótipo.')
    patches = []
    for row, offsets in ((primary, (0, 0x30, 0xA0)), (child, (0x30, 0xA0))):
        for offset in offsets:
            for axis in (0, 2):
                address = row['address']+offset+axis*4
                value = state.memory.read(address, '<f')[0]+delta[axis]
                try:
                    packed = struct.pack('<f', value)
                except (OverflowError, struct.error) as error:
                    raise ProfileError('Coordenada fora do intervalo permitido.') from error
                if not math.isfinite(struct.unpack('<f', packed)[0]):
                    raise ProfileError('Coordenada não finita.')
                patches.append(Patch(address, 4, state.memory.u32(address), struct.unpack('<I', packed)[0]))
    address = primary['node']+0x34
    patches.append(Patch(address, 4, state.memory.u32(address), target_word))
    return patches
