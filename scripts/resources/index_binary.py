"""Read-only ELF32 little-endian ASCII string index for Burnout 3 research."""
import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import add_paths, resolve_paths, prepare_outputs

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    add_paths(parser)
    parser.add_argument('--executable', default='SLUS_210.50', help='Executable path relative to game root')
    args=parser.parse_args()
    game, OUT=resolve_paths(parser,args)
    SOURCE=(game/args.executable).resolve()
    if not SOURCE.is_relative_to(game): parser.error('Executable must be inside the game root')
    prepare_outputs(OUT,['binary_strings.json','candidate_strings.tsv'])
    blob = SOURCE.read_bytes()
    if len(blob)<52 or blob[:6] != b'\x7fELF\x01\x01':
        raise ValueError('Expected a complete ELF32 little-endian file')
    phoff = struct.unpack_from('<I', blob, 28)[0]
    phentsize, phnum = struct.unpack_from('<HH', blob, 42)
    if phentsize < 32 or phoff + phnum * phentsize > len(blob):
        raise ValueError('Program header table lies outside the input')
    loads = []
    for i in range(phnum):
        kind, off, va, pa, filesz, memsz, flags, align = struct.unpack_from('<8I', blob, phoff + i * phentsize)
        if kind == 1 and filesz:
            loads.append((off, va, filesz))

    def address(off):
        for fileoff, va, size in loads:
            if fileoff <= off < fileoff + size:
                return f'{va + off - fileoff:08x}'
        return None

    terms = re.compile(r'crash|junction|traffic|spawn|\.dat|\.bgd|stagehed|tlist|track|vehicle|lane', re.I)
    strings = []
    for match in re.finditer(rb'[\x20-\x7e]{5,}', blob):
        text = match.group().decode('ascii')
        strings.append({'offset': match.start(), 'address': address(match.start()), 'text': text,
                        'candidate': bool(terms.search(text))})
    for literal in [b'enviro.dat', b'Gamedata.bgd', b'static.dat', b'streamed.dat', b'Data/stagehed.bin', b'Tracks/tlist.bin']:
        off = blob.find(literal)
        if off >= 0 and not any(s['offset'] == off for s in strings):
            strings.append({'offset': off, 'address': address(off), 'text': literal.decode(), 'candidate': True})
    strings.sort(key=lambda s: s['offset'])
    data = {'source': str(SOURCE), 'sha256': hashlib.sha256(blob).hexdigest(), 'size': len(blob),
            'scope': 'ASCII runs >=5 bytes and explicit resource path suffixes; runtime loading unknown',
            'strings': strings}
    (OUT / 'binary_strings.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
    candidates = [s for s in strings if s['candidate'] and s['address']]
    (OUT / 'candidate_strings.tsv').write_text(''.join(f"{s['address']}\t{s['offset']:x}\t{s['text']}\n" for s in candidates), encoding='utf-8')
    print(json.dumps({'source_sha256': data['sha256'], 'strings': len(strings), 'candidates': len(candidates)}))

if __name__ == '__main__':
    main()
