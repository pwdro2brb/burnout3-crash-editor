"""Read the USA Crash event directory from an extracted disc."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
import re
import struct

from editor.catalog import decode_identifier
from resources.native_traffic import stage_offsets


STAGE_TABLE = 0x278
STAGE_STRIDE = 0x3E0
STAGE_KEYS = 0x390
THRESHOLDS_OFFSET = 0x3A0
CRASHBREAKER_OFFSET = 0x3AC
SECTOR = 0x800
FIRST_CRASH = 96
CRASH_COUNT = 100
FIRST_UPPERCASE_TITLE = 1374
FIRST_TITLE = 1474


@dataclass(frozen=True)
class CrashEvent:
    key: str
    track: str
    title: str
    progression_index: int
    stage_index: int
    stage_offset: int
    bgd_stage_offset: int
    event_offset: int
    thresholds: tuple[float, float, float]
    bgd_thresholds: tuple[float, float, float]
    crashbreaker_wrecks: int | None = None
    bgd_crashbreaker_wrecks: int | None = None


def stagehed_path(game_root: Path) -> Path:
    return Path(game_root) / "DATA" / "STAGEHED.BIN"


def bgd_path(game_root: Path, track: str) -> Path:
    match = re.fullmatch(r"(US|EU|AS)_(C[0-9]+_V[0-9]+)", track)
    if not match:
        raise ValueError(f"Identificador de pista incompatível: {track!r}.")
    return Path(game_root) / "TRACKS" / match[1] / match[2] / "GAMEDATA.BGD"


def _check_range(data: bytes, start: int, size: int) -> None:
    if start < 0 or size < 0 or start + size > len(data):
        raise ValueError("O recurso de eventos tem um offset fora do arquivo.")


def _words(data: bytes, offset: int, count: int = 1) -> tuple:
    _check_range(data, offset, 4 * count)
    return struct.unpack_from(f"<{count}I", data, offset)


def _read_progression(data: bytes) -> dict[bytes, int]:
    version, groups, group_count = _words(data, 0, 3)
    if version != 4 or group_count != 2:
        raise ValueError("PRGDATA.BIN incompatível com a edição USA.")
    tiers, tier_count = _words(data, groups + 8, 2)
    if tier_count != 5:
        raise ValueError("Quantidade inesperada de grupos de Crash em PRGDATA.BIN.")
    result = {}
    for tier in range(tier_count):
        entries, count = _words(data, tiers + tier * 0x18 + 0x10, 2)
        if count != 20:
            raise ValueError("Grupo de Crash incompleto em PRGDATA.BIN.")
        for entry in range(count):
            event, instances = _words(data, entries + entry * 0x40 + 0x34, 2)
            index, mode = _words(data, event + 0x10, 2)
            pair = data[event:event + 0x10]
            if (instances != 1 or mode != 6 or pair in result
                    or index != FIRST_CRASH + len(result)):
                raise ValueError("Registro de progressão de Crash inconsistente.")
            result[pair] = index
    return result


def _read_titles(data: bytes) -> tuple[str, ...]:
    count, table = _words(data, 8, 2)
    if table != 0x10 or count <= FIRST_TITLE + CRASH_COUNT:
        raise ValueError("Tabela de títulos incompleta em GLOBALUS.BIN.")
    _check_range(data, table, count * 4)

    def label(index: int) -> str:
        start, end = _words(data, table + index * 4, 2)
        _check_range(data, start, end - start)
        if start < table + count * 4 or start % 2 or end % 2 or end - start < 4:
            raise ValueError("Limites de título inválidos em GLOBALUS.BIN.")
        if data[end - 2:end] != b"\0\0":
            raise ValueError("Título sem terminador em GLOBALUS.BIN.")
        value = data[start:end - 2].decode("utf-16le")
        if "\0" in value:
            raise ValueError("Título com terminador inesperado em GLOBALUS.BIN.")
        return value

    titles = []
    for ordinal in range(CRASH_COUNT):
        title = label(FIRST_TITLE + ordinal)
        if title.upper() != label(FIRST_UPPERCASE_TITLE + ordinal):
            raise ValueError("As duas séries de títulos de Crash divergem.")
        titles.append(title)
    return tuple(titles)


def _thresholds(data: bytes, start: int) -> tuple[float, float, float]:
    _check_range(data, start + THRESHOLDS_OFFSET, 12)
    values = struct.unpack_from("<3f", data, start + THRESHOLDS_OFFSET)
    if not all(isfinite(v) for v in values):
        raise ValueError("Valor de meta não finito no descritor de Crash.")
    return values


def _bgd_index(data: bytes, pairs: dict[bytes, int]) -> dict[bytes, tuple]:
    records = {}
    for start in stage_offsets(data):
        pair = data[start + STAGE_KEYS:start + STAGE_KEYS + 16]
        if pair not in pairs:
            continue
        if pair in records:
            raise ValueError("Descritor de Crash duplicado na mesma pista.")
        sector_size, _, _, event = _words(data, start + 0x3BC, 4)
        if sector_size != SECTOR or event % SECTOR or not 0 < event < len(data):
            raise ValueError("Descritor de pista contém um bloco de evento inválido.")
        wrecks, = _words(data, start + CRASHBREAKER_OFFSET)
        records[pair] = start, event, _thresholds(data, start), wrecks
    return records


def load_crash_events(game_root: Path) -> tuple[CrashEvent, ...]:
    """Read all 100 original progression slots. The two descriptors can differ."""
    root = Path(game_root)
    stages = stagehed_path(root).read_bytes()
    pairs = _read_progression((root / "DATA" / "PRGDATA.BIN").read_bytes())
    titles = _read_titles((root / "DATA" / "GLOBALUS.BIN").read_bytes())
    count = _words(stages, 0x260)[0]
    if _words(stages, 0)[0] != 8:
        raise ValueError("Versão de STAGEHED.BIN incompatível.")
    _check_range(stages, STAGE_TABLE, count * STAGE_STRIDE)
    tracks = {}
    result = {}
    for row in range(count):
        start = STAGE_TABLE + row * STAGE_STRIDE
        pair = stages[start + STAGE_KEYS:start + STAGE_KEYS + 16]
        if pair not in pairs:
            continue
        track, key = (decode_identifier(n) for n in struct.unpack("<QQ", pair))
        sector_size, ordinal = _words(stages, start + 0x3BC, 2)
        if pair in result or not key.startswith("1G") or ordinal != row or sector_size != SECTOR:
            raise ValueError("Descritor de Crash inconsistente em STAGEHED.BIN.")
        if track not in tracks:
            tracks[track] = _bgd_index(bgd_path(root, track).read_bytes(), pairs)
        if pair not in tracks[track]:
            raise ValueError(f"Falta o descritor de {key} no GAMEDATA.BGD de {track}.")
        bgd_stage, event, local_values, local_wrecks = tracks[track][pair]
        wrecks, = _words(stages, start + CRASHBREAKER_OFFSET)
        index = pairs[pair]
        result[pair] = CrashEvent(key, track, titles[index - FIRST_CRASH], index,
                                  row, start, bgd_stage, event,
                                  _thresholds(stages, start), local_values, wrecks, local_wrecks)
    if result.keys() != pairs.keys():
        raise ValueError("Faltam descritores de Crash em STAGEHED.BIN.")
    return tuple(sorted(result.values(), key=lambda event: event.progression_index))
