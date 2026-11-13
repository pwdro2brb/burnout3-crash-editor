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
SECONDARY_MODEL_OFFSET = 0x38
BATCH_MAX_REQUESTS = 8
BATCH_CODE_STRIDE = 0x100
BATCH_RECORD_BASE = CAVE + 0xA00
BATCH_RECORD_STRIDE = 0x80
LANDING = CAVE + 0xFC0
LANDING_SIZE = 12


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


def _landing_rows() -> list[dict]:
    instructions = ((_i(43, 25, 24, 0), 'sw t8,0(t9)'),
                    (_j(2, RETURN), f'j {RETURN:#x}'), (0, 'nop'))
    return [{'address': LANDING + index * 4, 'word': word,
             'instruction': instruction, 'bytes_le': struct.pack('<I', word).hex()}
            for index, (word, instruction) in enumerate(instructions)]


def clean_batch_scratch() -> bytes:
    """Canonical idle area: all zero except the permanent twelve-byte landing.

    A paused EE may still be at the landing after it publishes completion.
    Cleanup must retain these exact instructions so that resuming can safely
    execute its jump and delay slot after the other temporary bytes are gone.
    """
    scratch = bytearray(END - CAVE)
    scratch[LANDING - CAVE:LANDING - CAVE + LANDING_SIZE] = b''.join(
        struct.pack('<I', row['word']) for row in _landing_rows())
    return bytes(scratch)


def build_spawn(manager: int, type_code: int, model_hash: int,
                path_descriptor: int, progression: float, speed: float,
                spacing: float, variant: int = 0, *,
                secondary_type_code: int = 0, secondary_model_hash: int = 0,
                nonce: bytes | None = None) -> dict:
    """Construct one independent vehicle or a linked tractor/trailer request.

    Types 1 and 2 admit no secondary component. Type 4 requires a type-11
    secondary and its own loaded model identifier. Model compatibility and
    capacity checks are the controller's job; the stock creator owns the
    linked objects, path node, model initialization and collision registration.
    The creator retains its normal initial lateral value; the controller can
    subsequently align the newly initialized independent vehicle while paused.

    Probe words at DATA are state, returned object pointer and node pointer.
    State 2 is written last on both allocation success and failure. A nonzero
    state prevents another allocation on subsequent frames. All scratch bytes
    except these three probe words remain immutable during this routine.
    The controller can discover a pair's secondary through returned_object+0x110;
    the probe layout stays compatible with existing cleanup ownership checks.
    """
    return _build_spawn(
        manager, type_code, model_hash, path_descriptor, progression, speed,
        spacing, variant, secondary_type_code=secondary_type_code,
        secondary_model_hash=secondary_model_hash, nonce=nonce,
        code_address=CAVE, data_address=DATA, return_address=RETURN,
    )


def _build_spawn(manager: int, type_code: int, model_hash: int,
                 path_descriptor: int, progression: float, speed: float,
                 spacing: float, variant: int = 0, *,
                 secondary_type_code: int = 0, secondary_model_hash: int = 0,
                 nonce: bytes | None = None, code_address: int,
                 data_address: int, return_address: int, finish_batch: bool = False) -> dict:
    """Render a validated request at private, caller-selected scratch offsets."""
    if manager != MANAGER or type(manager) is not int:
        raise ValueError('Only the researched USA traffic manager is admitted')
    _integer(type_code, 1, 4, 'Constructor type')
    if type_code not in (1, 2, 4):
        raise ValueError('Only independent types 1/2 or a linked type-4 pair are admitted')
    _integer(model_hash, 1, (1 << 64) - 1, 'Model identifier')
    _integer(secondary_type_code, 0, 11, 'Secondary constructor type')
    _integer(secondary_model_hash, 0, (1 << 64) - 1, 'Secondary model identifier')
    if type_code == 4:
        if secondary_type_code != 11 or secondary_model_hash == 0:
            raise ValueError('A type-4 tractor requires a type-11 secondary and model identifier')
    elif secondary_type_code != 0 or secondary_model_hash != 0:
        raise ValueError('Independent types 1/2 do not admit a secondary component')
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
        rows.append({'address': code_address + len(rows) * 4,
                     'word': word, 'instruction': instruction})

    def ins(op: int, rs: int, rt: int, immediate: int, instruction: str) -> None:
        emit(_i(op, rs, rt, immediate), instruction)

    def branch(op: int, rs: int, rt: int, label: str, instruction: str) -> None:
        fixups.append((len(rows), op, rs, rt, label))
        emit(0, instruction)

    def label(name: str) -> None:
        labels[name] = code_address + len(rows) * 4

    def data_base() -> None:
        ins(15, 0, 25, data_address >> 16, f'lui t9,{data_address >> 16:#x}')
        ins(13, 25, 25, data_address & 0xFFFF,
            f'ori t9,t9,{data_address & 0xFFFF:#x}')

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
    if type_code == 4:
        ins(9, 0, 7, secondary_type_code, 'addiu a3,zero,11')
        ins(55, 25, 8, SECONDARY_MODEL_OFFSET, 'ld t0,0x38(t9)')
    else:
        for reg, name in ((7, 'a3'), (8, 't0')):
            emit((reg << 11) | 0x21, f'addu {name},zero,zero')
    emit((11 << 11) | 0x21, 'addu t3,zero,zero')
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
    if finish_batch:
        # Restore the displaced delay slot before the jump instruction. Once
        # both stores complete, future traffic returns cannot enter the cave.
        ins(15, 0, 25, HOOK >> 16, f'lui t9,{HOOK >> 16:#x}')
        ins(13, 25, 25, HOOK & 0xFFFF, f'ori t9,t9,{HOOK & 0xFFFF:#x}')
        for offset in (4, 0):
            word = struct.unpack_from('<I', ORIGINAL, offset)[0]
            ins(15, 0, 24, word >> 16, f'lui t8,{word >> 16:#x}')
            ins(13, 24, 24, word & 0xFFFF, f'ori t8,t8,{word & 0xFFFF:#x}')
            ins(43, 25, 24, offset, f'sw t8,{offset}(t9)')
        ins(15, 0, 25, DATA >> 16, f'lui t9,{DATA >> 16:#x}')
        ins(13, 25, 25, DATA & 0xFFFF, f'ori t9,t9,{DATA & 0xFFFF:#x}')
        ins(9, 0, 24, PROBE_STATE_DONE, 'addiu t8,zero,2')
        emit(_j(2, LANDING), f'j {LANDING:#x}')
        emit(0, 'nop')
    else:
        emit(_j(2, return_address), f'j {return_address:#x}')
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
    if code_address + len(code) >= data_address:
        raise ValueError('Routine overlaps its parameter block')
    scratch = bytearray(END - CAVE)
    code_offset = code_address - CAVE
    scratch[code_offset:code_offset + len(code)] = code
    base = data_address - CAVE
    struct.pack_into('<I', scratch, base + 0x10, manager)
    struct.pack_into('<Q', scratch, base + 0x18, model_hash)
    struct.pack_into('<Q', scratch, base + SECONDARY_MODEL_OFFSET, secondary_model_hash)
    struct.pack_into('<I', scratch, base + 0x20, path_descriptor)
    struct.pack_into('<fff', scratch, base + 0x28, progression, speed, spacing)
    magic_address = data_address + 0x60
    nonce_address = magic_address + len(MAGIC)
    scratch[magic_address - CAVE:nonce_address - CAVE] = MAGIC
    scratch[nonce_address - CAVE:nonce_address - CAVE + 16] = nonce
    return {
        'hook_bytes': struct.pack('<II', _j(2, code_address), 0),
        'original_hook': ORIGINAL,
        'scratch_bytes': bytes(scratch),
        'code_bytes': code,
        'rows': rows,
        'probe_address': data_address,
        'probe_size': PROBE_SIZE,
        'probe_state_done': PROBE_STATE_DONE,
        'magic_address': magic_address,
        'nonce_address': nonce_address,
        'nonce': nonce,
    }


def build_batch(requests: list[dict] | tuple[dict, ...],
                nonce: bytes | None = None) -> dict:
    """Chain one to eight stock allocations during one traffic-update return.

    Each mapping uses ``build_spawn`` parameters except ``nonce``. Requests
    have independent one-shot probes: a failed allocation records DONE with
    null pointers and continues to the next request. Any nonzero state skips
    that allocation on later traversals, including an interrupted EXECUTING
    request. Cleanup requires every probe AND the global completion word to be
    DONE. The final stub restores the hook before jumping to a permanent landing;
    only that landing publishes global completion, outside the removable code.

    ``probes`` exposes each probe's absolute address and its scratch-relative
    offset. Only its first twelve bytes and the global DATA completion word may
    change. Per-request records and the global DATA header share one nonce;
    DATA+0x0c holds the count. Cleanup uses ``clean_scratch``, retaining LANDING.
    """
    if not isinstance(requests, (list, tuple)) or not 1 <= len(requests) <= BATCH_MAX_REQUESTS:
        raise ValueError('A batch requires between one and eight request mappings')
    if nonce is None:
        nonce = secrets.token_bytes(16)
    if not isinstance(nonce, bytes) or len(nonce) != 16:
        raise ValueError('Request nonce must contain exactly 16 bytes')

    clean_scratch = clean_batch_scratch()
    scratch = bytearray(clean_scratch)
    rows: list[dict] = []
    probes: list[dict] = []
    code_end = 0
    for index, request in enumerate(requests):
        if not isinstance(request, dict) or 'nonce' in request:
            raise ValueError('Each batch request must be a mapping without its own nonce')
        code_address = CAVE + index * BATCH_CODE_STRIDE
        data_address = BATCH_RECORD_BASE + index * BATCH_RECORD_STRIDE
        return_address = code_address + BATCH_CODE_STRIDE if index + 1 < len(requests) else RETURN
        try:
            item = _build_spawn(**request, nonce=nonce, code_address=code_address,
                                data_address=data_address, return_address=return_address,
                                finish_batch=index + 1 == len(requests))
        except TypeError as exc:
            raise ValueError('Batch request parameters must match build_spawn') from exc
        if len(item['code_bytes']) > BATCH_CODE_STRIDE:
            raise ValueError('A batch routine exceeds its reserved code slot')
        code_offset = code_address - CAVE
        record_offset = data_address - CAVE
        code_end = code_offset + len(item['code_bytes'])
        scratch[code_offset:code_end] = item['code_bytes']
        scratch[record_offset:record_offset + BATCH_RECORD_STRIDE] = (
            item['scratch_bytes'][record_offset:record_offset + BATCH_RECORD_STRIDE]
        )
        rows.extend(item['rows'])
        probes.append({'address': data_address, 'offset': record_offset})

    if CAVE + code_end > BATCH_RECORD_BASE:
        raise ValueError('Batch code overlaps its request records')
    header_offset = DATA - CAVE
    struct.pack_into('<I', scratch, header_offset + 0x0C, len(requests))
    scratch[MAGIC_ADDRESS - CAVE:NONCE_ADDRESS - CAVE] = MAGIC
    scratch[NONCE_ADDRESS - CAVE:NONCE_ADDRESS - CAVE + 16] = nonce
    rows.extend(_landing_rows())
    return {
        'hook_bytes': struct.pack('<II', _j(2, CAVE), 0),
        'original_hook': ORIGINAL,
        'scratch_bytes': bytes(scratch),
        'clean_scratch': clean_scratch,
        'code_bytes': bytes(scratch[:code_end]),
        'rows': rows,
        'probes': probes,
        'probe_size': PROBE_SIZE,
        'probe_state_done': PROBE_STATE_DONE,
        'request_count': len(requests),
        'header_address': DATA,
        'completion_address': DATA,
        'landing_address': LANDING,
        'magic_address': MAGIC_ADDRESS,
        'nonce_address': NONCE_ADDRESS,
        'nonce': nonce,
    }
