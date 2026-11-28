"""Export an equal-size overlay on a new copy of a Burnout 3 USA ISO9660 disc."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import struct
import tempfile


SECTOR = 2048
CHUNK = 1024 * 1024


def _dual(data, offset, width):
    little = int.from_bytes(data[offset:offset + width], 'little')
    big = int.from_bytes(data[offset + width:offset + 2 * width], 'big')
    if little != big:
        raise ValueError('The two values of the ISO9660 field differ.')
    return little


def _record(record, volume_size):
    if (len(record) < 34 or record[0] != len(record) or record[32] == 0
            or 33 + record[32] > len(record) or record[1] or record[26:28] != b'\0\0'
            or _dual(record, 28, 2) != 1 or record[25] not in (0, 2)):
        raise ValueError('Invalid ISO9660 record or incompatible record type.')
    start, size = _dual(record, 2, 4) * SECTOR, _dual(record, 10, 4)
    if start < 17 * SECTOR or start + size > volume_size:
        raise ValueError('An ISO9660 record points outside the data sectors.')
    return record[33:33 + record[32]], record[25] == 2, start, size


def _name(raw, directory):
    try:
        item = raw.decode('ascii')
    except UnicodeDecodeError as error:
        raise ValueError('Invalid ISO9660 file name.') from error
    if not directory:
        item = item.removesuffix(';1')
    if item in ('.', '..') or not re.fullmatch(r'[A-Z0-9_.-]+', item):
        raise ValueError('Incompatible ISO9660 file name.')
    return item


def _files(stream):
    volume_size = stream.seek(0, 2)
    stream.seek(16 * SECTOR)
    primary = stream.read(SECTOR)
    if (len(primary) != SECTOR or primary[:7] != b'\x01CD001\x01'
            or primary[40:72].rstrip(b' ') != b'SLUS_21050'
            or _dual(primary, 128, 2) != SECTOR or _dual(primary, 80, 4) * SECTOR != volume_size
            or _dual(primary, 120, 2) != 1 or _dual(primary, 124, 2) != 1):
        raise ValueError('Select a Burnout 3 USA (SLUS-21050) ISO9660 image with 2048-byte sectors.')
    terminator = stream.read(SECTOR)
    if terminator[:7] != b'\xffCD001\x01':
        raise ValueError("The end of the Burnout 3 ISO's descriptors is invalid.")
    ranges = [(0, 18 * SECTOR)]
    table_size = _dual(primary, 132, 4)
    tables = (*struct.unpack_from('<2I', primary, 140), *struct.unpack_from('>2I', primary, 148))
    if not table_size or not tables[0] or not tables[2]:
        raise ValueError("The ISO's path tables are missing.")
    for sector in tables:
        if sector:
            start = sector * SECTOR
            if start + table_size > volume_size:
                raise ValueError('A path table goes beyond the ISO.')
            ranges.append((start, start + table_size))
    name, is_dir, root, root_size = _record(primary[156:156 + primary[156]], volume_size)
    if name != b'\0' or not is_dir:
        raise ValueError("The ISO's root directory is invalid.")
    pending = [('', root, root_size, root, root_size)]
    files = {}
    directories = set()
    while pending:
        prefix, start, size, parent, parent_size = pending.pop()
        if start in directories or len(directories) >= 1024 or not 0 < size <= 1024 * 1024:
            raise ValueError('Cycle, duplicate or invalid size in an ISO directory.')
        directories.add(start)
        ranges.append((start, start + size))
        stream.seek(start)
        data = stream.read(size)
        if len(data) != size:
            raise ValueError('The ISO directory read ended earlier than expected.')
        offset = 0
        seen = set()
        while offset < size:
            length = data[offset]
            block_end = min(size, (offset // SECTOR + 1) * SECTOR)
            if not length:
                if any(data[offset:block_end]):
                    raise ValueError('Invalid padding between ISO directory records.')
                offset = block_end
                continue
            if offset + length > block_end:
                raise ValueError('A directory record crosses the sector boundary.')
            raw, directory, extent, extent_size = _record(data[offset:offset + length], volume_size)
            offset += length
            if raw in (b'\0', b'\1'):
                expected = (start, size) if raw == b'\0' else (parent, parent_size)
                if not directory or (extent, extent_size) != expected:
                    raise ValueError('An ISO directory reference is inconsistent.')
                key = raw
            else:
                key = _name(raw, directory)
                path = prefix + '/' + key if prefix else key
                if directory:
                    pending.append((path, extent, extent_size, start, size))
                else:
                    files[path] = extent, extent_size
                    if len(files) > 32768:
                        raise ValueError('The ISO contains too many files for this profile.')
                    if extent_size:
                        ranges.append((extent, extent + extent_size))
            if key in seen:
                raise ValueError('Duplicate name in the ISO directory.')
            seen.add(key)
        if not {b'\0', b'\1'} <= seen:
            raise ValueError('The ISO directory is incomplete.')
    ranges.sort()
    if any(left[1] > right[0] for left, right in zip(ranges, ranges[1:])):
        raise ValueError('There are overlapping file extents or metadata in the ISO.')
    return files


def _plan(stream, changes):
    if not changes:
        raise ValueError('The project contains no changes for the ISO.')
    files = _files(stream)
    plan = []
    seen = set()
    for raw, (before, after) in changes.items():
        name = raw.removeprefix('/').upper().removesuffix(';1')
        if name in seen or name not in files:
            raise ValueError(f'File missing or repeated in the ISO: {raw}.')
        seen.add(name)
        start, length = files[name]
        if not isinstance(before, bytes) or not isinstance(after, bytes) or len(before) != length or len(after) != length:
            raise ValueError(f'The original size of {name} must be preserved.')
        stream.seek(start)
        for offset in range(0, length, CHUNK):
            if stream.read(min(CHUNK, length - offset)) != memoryview(before)[offset:offset + CHUNK]:
                raise ValueError(f'The ISO content differs from the extracted original for {name}.')
        plan.append((start, name, before, after))
    return sorted(plan)


def _copy_overlay(source, output, plan, size, progress=None):
    source.seek(0)
    digest = hashlib.sha256()
    for start, name, before, after in [*plan, (size, '', b'', b'')]:
        remaining = start - source.tell()
        while remaining > 0:
            data = source.read(min(CHUNK, remaining))
            if not data:
                raise ValueError('The ISO read ended earlier than expected.')
            output.write(data)
            digest.update(data)
            remaining -= len(data)
            if progress is not None:
                progress('copying', source.tell(), size)
        for offset in range(0, len(before), CHUNK):
            if source.read(min(CHUNK, len(before) - offset)) != memoryview(before)[offset:offset + CHUNK]:
                raise ValueError(f'The file {name} changed during the export.')
            replacement = memoryview(after)[offset:offset + CHUNK]
            output.write(replacement)
            digest.update(replacement)
    return digest.hexdigest()


def export_iso(source_iso: Path, destination: Path, changes: dict[str, tuple[bytes, bytes]],
               progress=None) -> dict:
    """Verify original files, stream and verify one private copy, then publish exclusively.

    ``progress(stage, done, total)`` is called from this thread while the copy
    is written ('copying') and read back ('verifying'), in bytes.
    """
    destination = Path(destination)
    if destination.suffix.lower() != '.iso':
        raise ValueError('Choose a destination with the .iso extension.')
    if os.path.lexists(destination):
        raise FileExistsError('The destination already exists. Choose a new name for the ISO.')
    with Path(source_iso).open('rb') as source:
        original = os.fstat(source.fileno())
        if progress is not None:
            progress('checking', 0, original.st_size)
        plan = _plan(source, changes)
        temporary = tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.burnout3-', suffix='.partial', delete=False)
        temp_path = Path(temporary.name)
        try:
            with temporary as output:
                digest = _copy_overlay(source, output, plan, original.st_size, progress)
                output.flush()
                os.fsync(output.fileno())
            current = os.fstat(source.fileno())
            if (current.st_size, current.st_mtime_ns) != (original.st_size, original.st_mtime_ns):
                raise ValueError('The source ISO changed during the export.')
            check = hashlib.sha256()
            with temp_path.open('rb') as written:
                for block in iter(lambda: written.read(CHUNK), b''):
                    check.update(block)
                    if progress is not None:
                        progress('verifying', written.tell(), original.st_size)
                if written.tell() != original.st_size or check.hexdigest() != digest:
                    raise ValueError('Verifying the ISO copy on disk failed.')
            if os.name == 'nt':
                os.rename(temp_path, destination)  # Windows refuses an existing destination.
            else:
                os.link(temp_path, destination)  # Atomic no-replace publication on POSIX.
        finally:
            temp_path.unlink(missing_ok=True)
    return dict(size=original.st_size, sha256=digest, changed_files=[name for _, name, _, _ in plan])
