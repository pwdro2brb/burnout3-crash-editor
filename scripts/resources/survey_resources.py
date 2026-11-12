"""Read-only resource survey. Outputs only beside this script, never into game files."""
from pathlib import Path
import collections
import hashlib
import json
import re
import struct

import argparse
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import add_paths, resolve_paths, prepare_outputs


def identity(p, root):
    data = p.read_bytes()
    return {'path': p.relative_to(root).as_posix(), 'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest()}, data


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    add_paths(parser)
    ROOT, OUT=resolve_paths(parser,parser.parse_args())
    prepare_outputs(OUT,['globalus_strings.json','resource_survey.json'])
    report = {'authority': 'local artifact byte inspection; not REA evidence',
              'game_root': str(ROOT), 'observations': {}, 'limitations': []}
    obs = report['observations']
    gid, data = identity(ROOT / 'DATA/GLOBALUS.BIN', ROOT)
    count, table = struct.unpack_from('<II', data, 8)
    offsets = struct.unpack_from('<%dI' % count, data, table)
    assert table + count * 4 == offsets[0]
    assert all(a <= b for a, b in zip(offsets, offsets[1:]))
    rows = []
    for index, start in enumerate(offsets):
        end = offsets[index + 1] if index + 1 < count else len(data)
        assert start % 2 == end % 2 == 0
        text = data[start:end].decode('utf-16le').rstrip('\0')
        rows.append({'index': index, 'offset': hex(start), 'text': text})
    (OUT / 'globalus_strings.json').write_text(json.dumps({'artifact': gid, 'strings': rows}, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    obs['globalus'] = {'artifact': gid, 'count': count, 'offset_table': hex(table),
                      'encoding': 'UTF-16LE', 'offsets': 'absolute uint32LE, ascending',
                      'crash_samples': [row for row in rows if row['index'] in [289, 363, 365, 380, 1375, 1475, 2452]]}
    bgds = []
    terms = [b'Crash', b'CRASH', b'crash', b'Traffic', b'traffic', b'Spawn', b'spawn']
    for p in sorted((ROOT / 'TRACKS').rglob('GAMEDATA.BGD')):
        item, data = identity(p, ROOT)
        item.update({'first_u32': struct.unpack_from('<I', data)[0],
                     'class_marker_offset': hex(data.find(b'B3tGameDataGame')),
                     'label_offset': hex(data.find(b'SEXBURNER')),
                     'term_hits': {t.decode(): hex(data.find(t)) for t in terms if data.find(t) >= 0}})
        bgds.append(item)
    obs['gamedata_bgd'] = bgds
    audio = []
    for name in ['TRACKS/CRASH1.RWS', 'TRACKS/US/C1_V1/CRASH3.RWS']:
        item, data = identity(ROOT / name, ROOT)
        item['outer_chunk'] = hex(struct.unpack_from('<I', data)[0])
        item['first_child_chunk'] = hex(struct.unpack_from('<I', data, 12)[0])
        item['markers'] = {t.decode(): hex(data.find(t)) for t in [b'VAG (Sony ADPCM)', b'aGenCrash01', b'zSloCrash01', b'Exporting stream', b'rwasegment'] if data.find(t) >= 0}
        audio.append(item)
    obs['crash_rws_audio_samples'] = audio
    item, data = identity(ROOT / 'DATA/STAGEHED.BIN', ROOT)
    item.update({'first_u32': struct.unpack_from('<I', data)[0],
                 'u32_at_0x260': struct.unpack_from('<I', data, 0x260)[0],
                 'repeated_float_run': 'float32LE 0.9 at 0x288, 0xa48, 0xe28 etc.; 0x3e0 periodicity',
                 'hypothesis_only': 'Repeated blocks may describe preload/resource sizes and tuning. Base/count/record meaning unresolved; tail is not all zero padding.'})
    obs['stagehed'] = item
    item, data = identity(ROOT / 'TRACKS/TLIST.BIN', ROOT)
    item['first_two_u32'] = list(struct.unpack_from('<II', data))
    obs['tlist'] = item
    obs['track_regions'] = {region: collections.Counter(p.name for p in (ROOT / 'TRACKS' / region).rglob('*') if p.is_file()) for region in ['US', 'EU', 'AS']}
    report['limitations'] = ['No coordinate/spawn record has been identified.', 'GAMEDATA.BGD type marker does not identify record layout or fixups.', 'A negative literal search does not establish feature absence.', 'No game execution or mutation was performed.']
    (OUT / 'resource_survey.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('Wrote resource_survey.json and globalus_strings.json; original files read only.')


if __name__ == '__main__':
    main()
