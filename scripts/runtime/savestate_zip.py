"""Replace one plain-deflate ZIP member while preserving all other raw payloads.

This deliberately supports a bounded, single-disk, non-ZIP64 profile without
data descriptors or encryption. It never extracts a file or writes a path.
"""

from __future__ import annotations

from io import BytesIO
import struct
import zipfile
import zlib


MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_TOTAL_MEMBER_BYTES = 256 * 1024 * 1024


def _metadata(info: zipfile.ZipInfo) -> tuple:
    return tuple(getattr(info, name) for name in (
        "filename", "date_time", "compress_type", "comment", "extra",
        "create_system", "create_version", "extract_version", "reserved",
        "flag_bits", "volume", "internal_attr", "external_attr", "file_size",
    ))


def _has_zip64(extra: bytes) -> bool:
    offset = 0
    while offset < len(extra):
        if offset + 4 > len(extra):
            raise ValueError("Malformed ZIP extra field")
        tag, size = struct.unpack_from("<HH", extra, offset)
        if offset + 4 + size > len(extra):
            raise ValueError("Truncated ZIP extra field")
        if tag == 1:
            return True
        offset += 4 + size
    return False


def _payload_span(data: bytes, info: zipfile.ZipInfo) -> tuple[int, int]:
    offset = info.header_offset
    if offset < 0 or data[offset:offset + 4] != b"PK\x03\x04":
        raise ValueError("Missing local ZIP header")
    flags, method = struct.unpack_from("<HH", data, offset + 6)
    crc, compressed, size = struct.unpack_from("<III", data, offset + 14)
    name_size, extra_size = struct.unpack_from("<HH", data, offset + 26)
    if (flags, method, crc, compressed, size) != (info.flag_bits, info.compress_type, info.CRC, info.compress_size, info.file_size):
        raise ValueError("Local and central ZIP headers disagree")
    start = offset + 30 + name_size + extra_size
    end = start + compressed
    if start > len(data) or end > len(data):
        raise ValueError("ZIP payload is out of bounds")
    if _has_zip64(data[offset + 30 + name_size:start]):
        raise ValueError("ZIP64 is outside this profile")
    return start, end


def read_member(data: bytes, member: str) -> bytes:
    """Validate the admitted ZIP profile and read one member into memory."""
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError("Archive exceeds the bounded savestate profile")
    with zipfile.ZipFile(BytesIO(data)) as archive:
        infos = archive.infolist()
        if not infos or len(infos) > 256:
            raise ValueError("Unexpected ZIP member count")
        if len({info.filename for info in infos}) != len(infos):
            raise ValueError("Duplicate ZIP member names are not admitted")
        if sum(info.file_size for info in infos) > MAX_TOTAL_MEMBER_BYTES:
            raise ValueError("Inflated archive exceeds the bounded profile")
        spans = []
        for info in infos:
            if info.flag_bits or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) or info.volume:
                raise ValueError("Only plain stored/deflate single-disk ZIP entries are admitted")
            if info.file_size > MAX_MEMBER_BYTES or info.extract_version >= 45 or _has_zip64(info.extra):
                raise ValueError("ZIP64 or oversized entry is outside this profile")
            start, end = _payload_span(data, info)
            if end > archive.start_dir:
                raise ValueError("Member overlaps the central directory")
            spans.append((info.header_offset, end))
        spans.sort()
        if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
            raise ValueError("ZIP members overlap")
        selected = archive.getinfo(member)
        if selected.compress_type != zipfile.ZIP_DEFLATED:
            raise ValueError("Selected EE RAM member must use plain deflate")
        return archive.read(selected)


def replace_member(data: bytes, member: str, replacement: bytes) -> tuple[bytes, dict]:
    """Return a verified archive; unchanged entries retain compressed bytes."""
    old_member = read_member(data, member)
    if len(replacement) != len(old_member):
        raise ValueError("Member replacement must preserve its uncompressed size")
    with zipfile.ZipFile(BytesIO(data)) as original:
        infos = original.infolist()
        selected = original.getinfo(member)
        start, end = _payload_span(data, selected)
        compressor = zlib.compressobj(level=6, wbits=-15)
        compressed = compressor.compress(replacement) + compressor.flush()
        crc = zlib.crc32(replacement) & 0xFFFFFFFF
        local = selected.header_offset
        header = bytearray(data[local:start])
        struct.pack_into("<III", header, 14, crc, len(compressed), len(replacement))
        delta = len(compressed) - selected.compress_size
        output = bytearray(data[:local] + header + compressed + data[end:])
        directory = original.start_dir + delta
        cursor = directory
        for info in infos:
            if output[cursor:cursor + 4] != b"PK\x01\x02":
                raise ValueError("Unexpected central-directory structure")
            name_size, extra_size, comment_size = struct.unpack_from("<HHH", output, cursor + 28)
            recorded = struct.unpack_from("<I", output, cursor + 42)[0]
            if recorded != info.header_offset:
                raise ValueError("ZIP directory entry order disagrees with parsed headers")
            if info.filename == member:
                struct.pack_into("<III", output, cursor + 16, crc, len(compressed), len(replacement))
            if recorded >= end:
                struct.pack_into("<I", output, cursor + 42, recorded + delta)
            cursor += 46 + name_size + extra_size + comment_size
        if output[cursor:cursor + 4] != b"PK\x05\x06" or cursor + 22 > len(output):
            raise ValueError("Expected a standard ZIP end record")
        disk, directory_disk, count_disk, count_total = struct.unpack_from("<HHHH", output, cursor + 4)
        directory_size, recorded_directory = struct.unpack_from("<II", output, cursor + 12)
        comment_size = struct.unpack_from("<H", output, cursor + 20)[0]
        if (disk, directory_disk, count_disk, count_total) != (0, 0, len(infos), len(infos)):
            raise ValueError("Multi-disk or ZIP64 archive is outside this profile")
        if (directory_size, recorded_directory) != (cursor - directory, original.start_dir) or cursor + 22 + comment_size != len(output):
            raise ValueError("Unexpected directory size, offset or trailing data")
        struct.pack_into("<I", output, cursor + 16, directory)
        result = bytes(output)
        members = []
        with zipfile.ZipFile(BytesIO(result)) as candidate:
            if candidate.namelist() != original.namelist() or candidate.comment != original.comment:
                raise AssertionError("ZIP entries, order or comment changed")
            for info in infos:
                new = candidate.getinfo(info.filename)
                if _metadata(info) != _metadata(new):
                    raise AssertionError(f"Member metadata changed: {info.filename}")
                if candidate.read(new) != (replacement if info.filename == member else original.read(info)):
                    raise AssertionError(f"Member contents differ unexpectedly: {info.filename}")
                expected_offset = info.header_offset + (delta if info.header_offset >= end else 0)
                if new.header_offset != expected_offset:
                    raise AssertionError("Unexpected local-header relocation")
                if info.filename != member:
                    old_start, old_end = _payload_span(data, info)
                    new_start, new_end = _payload_span(result, new)
                    if data[old_start:old_end] != result[new_start:new_end] or (info.CRC, info.compress_size) != (new.CRC, new.compress_size):
                        raise AssertionError("Unchanged compressed payload or derived metadata changed")
                members.append(info.filename)
        return result, {"member_names_in_original_order": members,
                        "member_metadata_preserved": True, "archive_comment_preserved": True,
                        "other_member_contents_and_compressed_payloads_identical": True,
                        "modified_member_readback_matches": True,
                        "derived_payload_size_delta": delta}
