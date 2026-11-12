"""Export candidate vehicle-selection metadata; never edit the game resource.

Layout derived from Ghidra FUN_0030c560; this is not a traffic-spawn parser.
"""
from pathlib import Path
import hashlib
import json
import struct

import argparse
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import add_paths, resolve_paths, prepare_outputs

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    add_paths(parser)
    ROOT, OUT=resolve_paths(parser,parser.parse_args())
    SOURCE=ROOT/'DATA'/'STAGEHED.BIN'
    prepare_outputs(OUT,['stagehed_records.json'])
    b = SOURCE.read_bytes()
    count = struct.unpack_from('<I', b, 0x260)[0]
    base, stride = 0x278, 0x3e0
    if count != 377 or base + count * stride > len(b):
        raise ValueError('Input does not match the researched 377-record USA layout')
    records = []
    for index in range(count):
        offset = base + index * stride
        if struct.unpack_from('<I', b, offset + 0x3c0)[0] != index:
            raise ValueError('Candidate record ordinal mismatch')
        slots = []
        for slot in range(6):
            so = offset + slot * 0x98
            primary, secondary = struct.unpack_from('<QQ', b, so)
            slots.append({'slot': slot, 'file_offset': hex(so),
                          'primary_id_u64': f'0x{primary:016x}',
                          'secondary_id_u64': f'0x{secondary:016x}',
                          'unknown_floats_a': struct.unpack_from('<16f', b, so + 0x10),
                          'unknown_floats_b': struct.unpack_from('<16f', b, so + 0x50),
                          'unknown_u32_90': struct.unpack_from('<I', b, so + 0x90)[0],
                          'variant_signed_byte_94': struct.unpack_from('<b', b, so + 0x94)[0],
                          'raw_tail_95_97': b[so + 0x95:so + 0x98].hex()})
        records.append({'index': index, 'file_offset': hex(offset),
                        'key_raw_16_bytes_at_390': b[offset + 0x390:offset + 0x3a0].hex(),
                        'slots': slots,
                        'unknown_trailing_u32': {hex(o): struct.unpack_from('<I', b, offset + o)[0]
                                                 for o in range(0x3a0, stride, 4)}})
    result = {'artifact': str(SOURCE), 'sha256': hashlib.sha256(b).hexdigest(),
              'authority': 'local bytes, layout derived from static Ghidra FUN_0030c560',
              'limitations': ['Global iRam0051a86c to file binding not yet independently traced.',
                              'Vehicle selection/tuning table; no traffic spawn coordinates identified.',
                              'Trailing 168 bytes retained as unknown, not called padding.'],
              'count': count, 'base': hex(base), 'stride': hex(stride),
              'records': records,
              'unknown_remaining_bytes': b[base + count * stride:].hex()}
    (OUT / 'stagehed_records.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(f'Exported {count} candidate records; ordinal check passed for all records.')

if __name__ == '__main__':
    main()
