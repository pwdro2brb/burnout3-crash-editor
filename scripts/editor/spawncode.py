"""Build one bounded stock-engine spawn request for the researched USA profile.

This module only constructs bytes. The controller must establish a paused,
matching VM, loaded model, valid path and unused scratch area before installing
them, and must remove them only while the VM is paused again. PINE writes are
not atomic with a running EE. The routine uses the common epilogue join at
0x166d6c, including the alternate return that bypasses 0x166d68.
"""
from __future__ import annotations

import math
import secrets
import struct


MANAGER = 0x527440
PATHS = 0x52288C
PATH_STRIDE = 0x4C
HOOK = 0x166D6C
ORIGINAL = bytes.fromhex('0800b6c79000be7b')
CAVE = 0xB3000
DATA = 0xB3F00
END = 0xB4000
ALLOCATOR = 0x164A50
RETURN = 0x166D74
MAGIC = b'B3EDv1\0\0'
MAGIC_ADDRESS = DATA + 0x60
NONCE_ADDRESS = MAGIC_ADDRESS + len(MAGIC)
PROBE_STATE_READY = 0
PROBE_STATE_EXECUTING = 1
PROBE_STATE_DONE = 2
PROBE_SIZE = 12


def _integer(value: int, minimum: int, maximum: int, label: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{label} is outside the supported range')
    return value


def _float32(value: float, minimum: float, maximum: float, label: str) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not minimum <= value <= maximum):
        raise ValueError(f'{label} must be finite and within the supported range')
    return struct.unpack('<f', struct.pack('<f', value))[0]


def _i(op: int, rs: int, rt: int, immediate: int) -> int:
    return (op << 26) | (rs << 21) | (rt << 16) | (immediate & 0xFFFF)


def _j(op: int, target: int) -> int:
    return (op << 26) | (target >> 2)


def build_spawn(manager: int, type_code: int, model_hash: int,
                path_descriptor: int, progression: float, speed: float,
                spacing: float, variant: int = 0, *, nonce: bytes | None = None) -> dict:
    """Construct a single independent vehicle allocation request.

    Constructor types 1 and 2 are the limited independent types admitted by
    this first editor. Category/model compatibility is the controller's job.
    The creator retains its normal initial lateral value; the controller can
    subsequently align the newly initialized vehicle while paused.

    Probe words at DATA are state, returned object pointer and node pointer.
    State 2 is written last on both allocation success and failure. A nonzero
    state prevents another allocation on subsequent frames. All scratch bytes
    except these three probe words remain immutable during this routine.
    """
    if manager != MANAGER or type(manager) is not int:
        raise ValueError('Only the researched USA traffic manager is admitted')
    _integer(type_code, 1, 2, 'Constructor type')
    _integer(model_hash, 1, (1 << 64) - 1, 'Model identifier')
    _integer(path_descriptor, PATHS, MANAGER - 1, 'Path descriptor')
    if (path_descriptor - PATHS) % PATH_STRIDE:
        raise ValueError('Path descriptor is not an aligned USA path record')
    progression = _float32(progression, 0, 65535, 'Path progression')
    speed = _float32(speed, 0, 240, 'Control speed')
    spacing = _float32(spacing, 0, 10000, 'Spacing scalar')
    _integer(variant, 0, 7, 'Model variant')
    if nonce is None:
        nonce = secrets.token_bytes(16)
    if not isinstance(nonce, bytes) or len(nonce) != 16:
        raise ValueError('Request nonce must contain exactly 16 bytes')

    rows: list[dict] = []
    labels: dict[str, int] = {}
    fixups: list[tuple[int, int, int, int, str]] = []

    def emit(word: int, instruction: str) -> None:
        rows.append({'address': CAVE + len(rows) * 4,
                     'word': word, 'instruction': instruction})

    def ins(op: int, rs: int, rt: int, immediate: int, instruction: str) -> None:
        emit(_i(op, rs, rt, immediate), instruction)

    def branch(op: int, rs: int, rt: int, label: str, instruction: str) -> None:
        fixups.append((len(rows), op, rs, rt, label))
        emit(0, instruction)

    def label(name: str) -> None:
        labels[name] = CAVE + len(rows) * 4

    def data_base() -> None:
        ins(15, 0, 25, DATA >> 16, 'lui t9,0xb')
        ins(13, 25, 25, DATA & 0xFFFF, 'ori t9,t9,0x3f00')

    # The original function's frame remains intact above this extra frame.
    # Outgoing constructor flags are at our SP+0, separate from saved values.
    ins(9, 29, 29, -0x80, 'addiu sp,sp,-0x80')
    ins(31, 29, 2, 0x20, 'sq v0,0x20(sp)')
    ins(31, 29, 3, 0x30, 'sq v1,0x30(sp)')
    saved_floats = ((0, 0x40), (1, 0x44), (12, 0x48), (13, 0x4C), (14, 0x50))
    for reg, offset in saved_floats:
        ins(57, 29, reg, offset, f'swc1 f{reg},{offset:#x}(sp)')
    data_base()
    ins(35, 25, 24, 0, 'lw t8,0(t9)')
    branch(5, 24, 0, 'restore', 'bne t8,zero,restore')
    emit(0, 'nop')
    ins(9, 0, 24, PROBE_STATE_EXECUTING, 'addiu t8,zero,1')
    ins(43, 25, 24, 0, 'sw t8,0(t9)')
    ins(35, 25, 4, 0x10, 'lw a0,0x10(t9)')
    ins(9, 0, 5, type_code, f'addiu a1,zero,{type_code}')
    ins(55, 25, 6, 0x18, 'ld a2,0x18(t9)')
    for reg, name in ((7, 'a3'), (8, 't0'), (11, 't3')):
        emit((reg << 11) | 0x21, f'addu {name},zero,zero')
    ins(9, 0, 10, variant, f'addiu t2,zero,{variant}')
    ins(35, 25, 9, 0x20, 'lw t1,0x20(t9)')
    ins(43, 29, 0, 0, 'sw zero,0(sp)')
    for reg, offset in ((12, 0x28), (13, 0x2C), (14, 0x30)):
        ins(49, 25, reg, offset, f'lwc1 f{reg},{offset:#x}(t9)')
    emit(_j(3, ALLOCATOR), 'jal 0x164a50')
    emit(0, 'nop')
    data_base()  # The allocator may clobber all volatile integer registers.
    ins(43, 25, 2, 4, 'sw v0,4(t9)')
    branch(4, 2, 0, 'complete', 'beq v0,zero,complete')
    emit(0, 'nop')
    ins(35, 2, 3, 0x114, 'lw v1,0x114(v0)')
    ins(43, 25, 3, 8, 'sw v1,8(t9)')
    label('complete')
    ins(9, 0, 24, PROBE_STATE_DONE, 'addiu t8,zero,2')
    ins(43, 25, 24, 0, 'sw t8,0(t9)')
    label('restore')
    for reg, offset in saved_floats:
        ins(49, 29, reg, offset, f'lwc1 f{reg},{offset:#x}(sp)')
    ins(30, 29, 2, 0x20, 'lq v0,0x20(sp)')
    ins(30, 29, 3, 0x30, 'lq v1,0x30(sp)')
    ins(9, 29, 29, 0x80, 'addiu sp,sp,0x80')
    # RA was already loaded on either original return route, then our JAL
    # changed it. Reload it as well as both displaced restore instructions.
    ins(55, 29, 31, 0xA0, 'ld ra,0xa0(sp)')
    ins(49, 29, 22, 8, 'lwc1 f22,8(sp)')
    ins(30, 29, 30, 0x90, 'lq s8,0x90(sp)')
    emit(_j(2, RETURN), 'j 0x166d74')
    emit(0, 'nop')

    for index, op, rs, rt, target in fixups:
        displacement = (labels[target] - rows[index]['address'] - 4) // 4
        if not -32768 <= displacement <= 32767:
            raise ValueError('Internal branch is outside the encoded range')
        rows[index]['word'] = _i(op, rs, rt, displacement)
        rows[index]['branch_target'] = labels[target]
    for row in rows:
        row['bytes_le'] = struct.pack('<I', row['word']).hex()
    code = b''.join(struct.pack('<I', row['word']) for row in rows)
    if CAVE + len(code) >= DATA:
        raise ValueError('Routine overlaps its parameter block')
    scratch = bytearray(END - CAVE)
    scratch[:len(code)] = code
    base = DATA - CAVE
    struct.pack_into('<I', scratch, base + 0x10, manager)
    struct.pack_into('<Q', scratch, base + 0x18, model_hash)
    struct.pack_into('<I', scratch, base + 0x20, path_descriptor)
    struct.pack_into('<fff', scratch, base + 0x28, progression, speed, spacing)
    scratch[MAGIC_ADDRESS - CAVE:NONCE_ADDRESS - CAVE] = MAGIC
    scratch[NONCE_ADDRESS - CAVE:NONCE_ADDRESS - CAVE + 16] = nonce
    return {
        'hook_bytes': struct.pack('<II', _j(2, CAVE), 0),
        'original_hook': ORIGINAL,
        'scratch_bytes': bytes(scratch),
        'code_bytes': code,
        'rows': rows,
        'probe_address': DATA,
        'probe_size': PROBE_SIZE,
        'probe_state_done': PROBE_STATE_DONE,
        'magic_address': MAGIC_ADDRESS,
        'nonce_address': NONCE_ADDRESS,
        'nonce': nonce,
    }
