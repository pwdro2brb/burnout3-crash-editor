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
UNITS = "The game's original control; nominal conversion from mph, no physical measurement."


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
        note=('Speed controlled by the cab; the trailer has no control of its own.'
              if row.get('parent_id') is not None else
              'Speed unavailable: this record has no recognized traffic node.' if not has_node else
              'Progress can be reduced by queues, obstacles and the state of the traffic.'))


def validate_control(new_control,*,experimental=False) -> float:
    """Validate a recipe/API value before any mutation; return finite float32."""
    if type(experimental) is not bool:
        raise profile.ProfileError('Invalid experimental mode.')
    value = _number(new_control)
    if value is None or value < 0 or (not experimental and value > MAX_NORMAL_CONTROL):
        raise profile.ProfileError('Use a speed control from 0 to 240.' if not experimental else
                                   'Use a positive or zero, finite speed control.')
    try:
        packed = struct.pack('<f',value)
    except (OverflowError,struct.error) as error:
        raise profile.ProfileError('The target speed is outside the float32 range.') from error
    if not math.isfinite(struct.unpack('<f',packed)[0]):
        raise profile.ProfileError('The target speed is outside the finite float32 range.')
    return struct.unpack('<f',packed)[0]


def _selected(state,vehicle_id):
    row = state.vehicles.get(vehicle_id) if type(vehicle_id) is int else None
    if row is None or row.get('id') != vehicle_id or not can_set_speed(row):
        raise profile.ProfileError('Select a vehicle or cab whose node, path and physics are ready.')
    return row


def _control_patch(state,row,vehicle_id,value_word):
    node,memory = row['node'],state.memory
    if (memory.u8(node+0x49) != row['node_index'] or memory.u8(node+0x4A) != vehicle_id
            or memory.u8(node+0x41) != row['path'] or not 1 <= memory.u8(node+0x46) <= 7
            or memory.u32(row['address']+0x114) != node):
        raise profile.ProfileError('The speed node no longer matches the selected vehicle.')
    current = memory.read(node,'<f')[0]
    if not math.isfinite(current) or current < 0 or current != row['speed']:
        raise profile.ProfileError('The speed control changed; refresh the list before editing.')
    return Patch(node,4,memory.u32(node),value_word)


def patches(state,vehicle_id,new_control,*,experimental=False) -> list[Patch]:
    """Return one expected-value patch of node+0, never current speed/spacing."""
    if getattr(state,'core_paused',False) is not True:
        raise profile.ProfileError('Pause PCSX2 before changing the target speed.')
    value=validate_control(new_control,experimental=experimental)
    row=_selected(state,vehicle_id)
    word=struct.unpack('<I',struct.pack('<f',value))[0]
    return [_control_patch(state,row,vehicle_id,word)]


def patches_many(state,vehicle_ids,new_control,*,experimental=False) -> list[Patch]:
    """Preflight a whole selection and return one desired-control patch per node.

    This pure preparation never writes memory or skips an invalid selection.
    The caller should pass the complete returned list to one guarded apply_patch
    call; that transport operation remains best effort rather than atomic.
    """
    if getattr(state,'core_paused',False) is not True:
        raise profile.ProfileError('Pause PCSX2 before changing the target speed.')
    value=validate_control(new_control,experimental=experimental)
    if (type(vehicle_ids) not in (list,tuple)
            or not 1 <= len(vehicle_ids) <= profile.POOL_COUNT):
        raise profile.ProfileError('Select 1 to 254 vehicles or cabs to change the speed.')
    if any(type(index) is not int or not 0 <= index < profile.POOL_COUNT for index in vehicle_ids):
        raise profile.ProfileError('The selection contains an invalid vehicle identifier.')
    if len(set(vehicle_ids)) != len(vehicle_ids):
        raise profile.ProfileError('The selection contains repeated vehicles.')
    rows=[_selected(state,index) for index in vehicle_ids]
    if len({row['node'] for row in rows}) != len(rows):
        raise profile.ProfileError('Two selected vehicles point to the same traffic node.')
    word=struct.unpack('<I',struct.pack('<f',value))[0]
    # Validate every live backlink and expected current value before returning
    # any patches. A late mismatch discards the entire prepared selection.
    return [_control_patch(state,row,index,word) for index,row in zip(vehicle_ids,rows)]
