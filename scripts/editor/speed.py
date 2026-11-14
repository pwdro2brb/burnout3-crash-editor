"""Nominal traffic speed and a guarded desired-speed patch.

The stock traffic controller converts node+0 by 0.44704 and writes the
resulting, obstacle-dependent advance at node+0x2c. Only the desired control
value is editable here. Km/h values are nominal conversions, not measurements
of the physical vehicle or proof that a game-world unit is a metre.
"""
from __future__ import annotations

import math
import struct

from . import profile
from .pine import Patch


CONTROL_TO_TRAVEL = 0.44704
CONTROL_TO_NOMINAL_KMH = 1.609344
TRAVEL_TO_NOMINAL_KMH = 3.6
MAX_NORMAL_CONTROL = 240.0
UNITS = 'Controle original do jogo; conversão nominal de mph, sem medição física.'


def _number(value):
    if type(value) not in (int,float):
        return None
    try:
        number=float(value)
    except (OverflowError,ValueError):
        return None
    return number if math.isfinite(number) else None


def _has_node(row):
    index=row.get('node_index')
    return (type(index) is int and 0 <= index < profile.POOL_COUNT
            and row.get('node') == profile.NODES+index*profile.NODE_STRIDE)


def can_set_speed(row) -> bool:
    """Describe readiness without requiring movement or a positive target."""
    if (type(row.get('id')) is not int or not 0 <= row['id'] < profile.POOL_COUNT
            or row.get('address') != profile.VEHICLES+row['id']*profile.VEHICLE_STRIDE
            or not _has_node(row)
            or not row.get('initialized') or not row.get('path_valid')
            or type(row.get('path')) is not int or not 0 <= row['path'] < 255
            or _number(row.get('progress')) is None or row['progress'] < 0
            or row.get('parent_id') is not None):
        return False
    control,travel,spacing = (_number(row.get(name)) for name in ('speed','travel_speed','spacing_scalar'))
    if control is None or travel is None or spacing is None or control < 0 or travel < 0:
        return False
    if row.get('type') in profile.SUPPORTED_SINGLE_TYPES and row.get('independent'):
        return True
    return bool(row.get('type') == 4 and row.get('kind') == 'truck'
                and row.get('native_pair_valid') and row.get('can_edit_compound'))


def summarize(row) -> dict:
    has_node=_has_node(row)
    control = _number(row.get('speed')) if has_node else None
    travel = _number(row.get('travel_speed')) if has_node else None
    spacing = _number(row.get('spacing_scalar')) if has_node else None
    return dict(control_value=control,travel_value=travel,spacing_value=spacing,
        nominal_target_kmh=control*CONTROL_TO_NOMINAL_KMH if control is not None and control >= 0 else None,
        nominal_travel_kmh=travel*TRAVEL_TO_NOMINAL_KMH if travel is not None and travel >= 0 else None,
        units=UNITS,conversion='nominal',physical_speed_measured=False,
        can_set_speed=can_set_speed(row),
        stopped=travel == 0 if travel is not None else None,
        note=('Velocidade controlada pela cabine; a carga não tem controle próprio.'
              if row.get('parent_id') is not None else
              'Velocidade indisponível: este registro não tem nó de tráfego reconhecido.' if not has_node else
              'O avanço pode ser reduzido por filas, obstáculos e pelo estado do tráfego.'))


def validate_control(new_control,*,experimental=False) -> float:
    """Validate a recipe/API value before any mutation; return finite float32."""
    if type(experimental) is not bool:
        raise profile.ProfileError('Modo experimental inválido.')
    value = _number(new_control)
    if value is None or value < 0 or (not experimental and value > MAX_NORMAL_CONTROL):
        raise profile.ProfileError('Use controle de velocidade de 0 a 240.' if not experimental else
                                   'Use um controle de velocidade positivo ou zero e finito.')
    try:
        packed = struct.pack('<f',value)
    except (OverflowError,struct.error) as error:
        raise profile.ProfileError('A velocidade desejada está fora do intervalo float32.') from error
    if not math.isfinite(struct.unpack('<f',packed)[0]):
        raise profile.ProfileError('A velocidade desejada está fora do intervalo float32 finito.')
    return struct.unpack('<f',packed)[0]


def patches(state,vehicle_id,new_control,*,experimental=False) -> list[Patch]:
    """Return one expected-value patch of node+0, never current speed/spacing."""
    if getattr(state,'core_paused',False) is not True:
        raise profile.ProfileError('Pause o PCSX2 antes de alterar a velocidade desejada.')
    value=validate_control(new_control,experimental=experimental)
    row = state.vehicles.get(vehicle_id) if type(vehicle_id) is int else None
    if row is None or not can_set_speed(row):
        raise profile.ProfileError('Selecione um veículo ou cabine com nó, caminho e física prontos.')
    packed=struct.pack('<f',value)
    node,memory = row['node'],state.memory
    if (memory.u8(node+0x49) != row['node_index'] or memory.u8(node+0x4A) != vehicle_id
            or memory.u8(node+0x41) != row['path'] or not 1 <= memory.u8(node+0x46) <= 7
            or memory.u32(row['address']+0x114) != node):
        raise profile.ProfileError('O nó de velocidade não corresponde mais ao veículo selecionado.')
    current = memory.read(node,'<f')[0]
    if not math.isfinite(current) or current < 0 or current != row['speed']:
        raise profile.ProfileError('O controle de velocidade mudou; atualize a lista antes de editar.')
    return [Patch(node,4,memory.u32(node),struct.unpack('<I',packed)[0])]
