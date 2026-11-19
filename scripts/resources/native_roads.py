"""Read traffic paths from an extracted Burnout 3 USA track GAMEDATA.BGD."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import struct


SECTION_DIRECTORY = 0x270
SECTOR = 2048
MAX_SECTION_BYTES = 8 * 1024 * 1024
MAX_PAIRS_PER_TRACK = 131072
DESCRIPTOR = struct.Struct('<5I')
PAIR = struct.Struct('<2H')
POINT = struct.Struct('<3f')


def _sample(pairs, vertices, progress, side):
    # Same clamped cubic B-spline used for the live path preview.
    segment = min(int(progress), len(pairs) - 2)
    t = progress - segment
    weights = ((1 - t)**3/6, (3*t**3 - 6*t*t + 4)/6,
               (-3*t**3 + 3*t*t + 3*t + 1)/6, t**3/6)
    controls = [vertices[pairs[min(max(segment + k - 1, 0), len(pairs) - 1)][side]]
                for k in range(4)]
    return [sum(weight * point[axis] for weight, point in zip(weights, controls))
            for axis in range(3)]


def read_roads(path: Path, *, max_samples_per_path: int = 96) -> dict:
    """Return bounded XYZ previews. IDs are native descriptor ordinals.

    All pair indices are validated, including those outside the preview samples.
    The digest covers the entire native geometry section including padding.
    """
    if type(max_samples_per_path) is not int or not 2 <= max_samples_per_path <= 256:
        raise ValueError('Use entre 2 e 256 amostras por caminho.')
    with Path(path).open('rb') as stream:
        header = stream.read(SECTION_DIRECTORY + 8)
        if len(header) != SECTION_DIRECTORY + 8 or header[:8] != bytes.fromhex('0900000078013200'):
            raise ValueError('Cabeçalho de GAMEDATA.BGD incompatível com as pistas USA pesquisadas.')
        start, end = struct.unpack_from('<2I', header, SECTION_DIRECTORY)
        size = stream.seek(0, 2)
        if (not SECTOR <= start < end <= size or start % SECTOR or end % SECTOR
                or end - start > MAX_SECTION_BYTES):
            raise ValueError('Os limites da seção de caminhos são inválidos.')
        stream.seek(start)
        section = stream.read(end - start)
        if len(section) != end - start:
            raise ValueError('A leitura da seção de caminhos ficou incompleta.')

    table, vertex_offset, count = struct.unpack_from('<3I', section)
    table_end = table + count * DESCRIPTOR.size
    if (table != 12 or not 1 <= count <= 255 or vertex_offset % 16
            or not table_end <= vertex_offset <= len(section) - 16):
        raise ValueError('A tabela nativa de caminhos é inválida.')
    descriptors = list(DESCRIPTOR.iter_unpack(section[table:table_end]))
    paths = []
    total_controls = 0
    previous_end = table_end
    vertices = {}
    for index, (pair_offset, aux1, aux2, reserved, controls) in enumerate(descriptors):
        total_controls += controls
        pair_end = pair_offset + controls * PAIR.size
        if (reserved != 0 or not 2 <= controls <= 65536 or total_controls > MAX_PAIRS_PER_TRACK
                or pair_offset % 4 or not previous_end <= pair_offset < pair_end <= aux1 < aux2 <= vertex_offset):
            raise ValueError(f'O descritor do caminho P{index} contém limites inválidos.')
        previous_end = aux2
        pairs = list(PAIR.iter_unpack(section[pair_offset:pair_end]))
        for pair in pairs:
            for vertex in pair:
                if vertex in vertices:
                    continue
                offset = vertex_offset + vertex * 16
                if offset + 16 > len(section):
                    raise ValueError(f'O caminho P{index} referencia um vértice fora da seção.')
                point = POINT.unpack_from(section, offset)
                if not all(math.isfinite(x) for x in point):
                    raise ValueError(f'O caminho P{index} contém uma coordenada não finita.')
                vertices[vertex] = point
        samples = min(controls, max_samples_per_path)
        progressions = [(controls - 1) * sample / (samples - 1) for sample in range(samples)]
        left = [_sample(pairs, vertices, t, 0) for t in progressions]
        right = [_sample(pairs, vertices, t, 1) for t in progressions]
        center = [[(x + y) / 2 for x, y in zip(a, b)] for a, b in zip(left, right)]
        paths.append(dict(id=index, count=controls, control_point_count=controls, sample_count=samples,
                          left=left, center=center, right=right, source='native_geometry'))
    return dict(paths=paths, path_count=count, control_pair_count=total_controls,
                section_offset=start, section_size=len(section),
                section_sha256=hashlib.sha256(section).hexdigest())
