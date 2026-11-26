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
        raise ValueError('Use between 2 and 256 samples per path.')
    with Path(path).open('rb') as stream:
        header = stream.read(SECTION_DIRECTORY + 8)
        if len(header) != SECTION_DIRECTORY + 8 or header[:8] != bytes.fromhex('0900000078013200'):
            raise ValueError('GAMEDATA.BGD header not compatible with the researched USA tracks.')
        start, end = struct.unpack_from('<2I', header, SECTION_DIRECTORY)
        size = stream.seek(0, 2)
        if (not SECTOR <= start < end <= size or start % SECTOR or end % SECTOR
                or end - start > MAX_SECTION_BYTES):
            raise ValueError("The path section's limits are invalid.")
        stream.seek(start)
        section = stream.read(end - start)
        if len(section) != end - start:
            raise ValueError('Reading the path section was incomplete.')

    table, vertex_offset, count = struct.unpack_from('<3I', section)
    table_end = table + count * DESCRIPTOR.size
    if (table != 12 or not 1 <= count <= 255 or vertex_offset % 16
            or not table_end <= vertex_offset <= len(section) - 16):
        raise ValueError('The native path table is invalid.')
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
            raise ValueError(f'The descriptor of path P{index} has invalid limits.')
        previous_end = aux2
        pairs = list(PAIR.iter_unpack(section[pair_offset:pair_end]))
        for pair in pairs:
            for vertex in pair:
                if vertex in vertices:
                    continue
                offset = vertex_offset + vertex * 16
                if offset + 16 > len(section):
                    raise ValueError(f'Path P{index} references a vertex outside the section.')
                point = POINT.unpack_from(section, offset)
                if not all(math.isfinite(x) for x in point):
                    raise ValueError(f'Path P{index} contains a non-finite coordinate.')
                vertices[vertex] = point
        # aux1 holds one (cumulative distance, width) float pair per control point.
        # The distance at control k is the value stored at k - 1 (0 for the first).
        distances = None
        if aux2 - aux1 >= controls * 8:
            table = [struct.unpack_from('<f', section, aux1 + 8 * k)[0] for k in range(controls)]
            if all(math.isfinite(v) for v in table) and all(b >= a for a, b in zip(table, table[1:])):
                distances = [0.0] + table[:-1]
        centers = [[(vertices[a][axis] + vertices[b][axis]) / 2 for axis in range(3)] for a, b in pairs]
        samples = min(controls, max_samples_per_path)
        progressions = [(controls - 1) * sample / (samples - 1) for sample in range(samples)]
        left = [_sample(pairs, vertices, t, 0) for t in progressions]
        right = [_sample(pairs, vertices, t, 1) for t in progressions]
        center = [[(x + y) / 2 for x, y in zip(a, b)] for a, b in zip(left, right)]
        paths.append(dict(id=index, count=controls, control_point_count=controls, sample_count=samples,
                          left=left, center=center, right=right, source='native_geometry',
                          control_centers=centers, control_distances=distances))
    return dict(paths=paths, path_count=count, control_pair_count=total_controls,
                section_offset=start, section_size=len(section),
                section_sha256=hashlib.sha256(section).hexdigest())


def point_at_distance(path: dict, distance: float):
    """Approximate X/Y/Z of a distance along a path, or None without a distance table."""
    table, centers = path.get('control_distances'), path.get('control_centers')
    if not table or not centers or not math.isfinite(distance):
        return None
    if distance <= table[0]:
        return list(centers[0])
    for k in range(1, len(table)):
        if distance <= table[k]:
            span = table[k] - table[k - 1]
            t = 0.0 if span <= 0 else (distance - table[k - 1]) / span
            return [a + (b - a) * t for a, b in zip(centers[k - 1], centers[k])]
    return list(centers[-1])
