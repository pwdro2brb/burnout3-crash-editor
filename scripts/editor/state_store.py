"""Export a paused portable PCSX2 state through a previously unused slot.

Save ACKs are queued requests. Completion is established from a stable, valid
archive before an exclusive destination copy is verified. Emulator settings
are read only; existing slots and destination files are never replaced here.
"""
from __future__ import annotations

import codecs
import configparser
import hashlib
import math
import os
from pathlib import Path
import stat
import time
import zipfile

from .pine import Status


class StateStoreError(ValueError):
    pass


POLL_INTERVAL = .10
STABLE_POLLS = 3
EE_MEMORY_SIZE = 32*1024*1024
MAX_ARCHIVE_SIZE = 128*1024*1024
MAX_UNCOMPRESSED_SIZE = 256*1024*1024
STATE_NAME = 'SLUS-21050 (BEBF8793).{slot:02d}.p2s'
STATE_DIRECTORY = 'SLUS-21050 - (BEBF8793)'


def _present(path: Path) -> bool:
    try:
        path.lstat()  # A broken link also occupies the filename.
        return True
    except FileNotFoundError:
        return False


def _states_directory(emulator_root: Path) -> Path:
    root = Path(emulator_root).resolve(strict=True)
    if not root.is_dir() or not (root/'portable.ini').is_file():
        raise StateStoreError('Select the portable PCSX2 copy used by the editor.')
    raw = (root/'inis'/'PCSX2_ui.ini').read_bytes()
    encoding = 'utf-16' if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else 'utf-8-sig'
    try:
        text = raw.decode(encoding)
        first_nul = text.find('\0')
        if first_nul >= 0:
            # Some wx INIs retain a zero-filled tail after complete text lines.
            # Never repair a NUL inside a key/value or followed by more config.
            if ((first_nul > 0 and text[first_nul-1] not in '\r\n')
                    or any(char not in '\0\r\n' for char in text[first_nul:])):
                raise StateStoreError('The INI contains a null character inside the configuration.')
            text = text[:first_nul]
        parser = configparser.ConfigParser(interpolation=None)
        # wxFileConfig permits root keys before the first named section.
        # Keep them separate from [Folders] instead of treating them as defaults.
        parser.read_string('[__PCSX2_ROOT__]\n'+text)
        folders = parser['Folders']
        default = folders.get('UseDefaultSavestates', 'enabled').strip().lower()
        if default in ('enabled', 'true', 'yes', '1'):
            folder = Path('sstates')
        elif default in ('disabled', 'false', 'no', '0'):
            value = folders.get('Savestates', '').strip()
            if not value:
                raise StateStoreError('The states folder is not set in the portable PCSX2.')
            folder = Path(value)
        else:
            raise StateStoreError("PCSX2's states folder option was not recognized.")
    except (UnicodeError, configparser.Error, KeyError) as error:
        raise StateStoreError("Could not read the portable PCSX2's states folder.") from error
    return (folder if folder.is_absolute() else root/folder).resolve()


def _candidates(states: Path, slot: int) -> tuple[Path, Path]:
    name = STATE_NAME.format(slot=slot)
    return states/name, states/STATE_DIRECTORY/name


def _regular_file(path: Path) -> bool:
    info = path.lstat()
    reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
    return stat.S_ISREG(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & reparse)


def _signature(path: Path):
    info = path.stat()
    return info.st_size, info.st_mtime_ns


def _valid_archive(path: Path):
    if not _regular_file(path):
        raise StateStoreError('The temporary state is not a regular file.')
    size = path.stat().st_size
    if not 0 < size <= MAX_ARCHIVE_SIZE:
        raise StateStoreError("The temporary state's size was not recognized.")
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if len(members) > 256 or sum(entry.file_size for entry in members) > MAX_UNCOMPRESSED_SIZE:
            raise StateStoreError('The state file exceeds the limits of this version.')
        ee = [entry for entry in members if entry.filename == 'eeMemory.bin']
        if len(ee) != 1 or ee[0].file_size != EE_MEMORY_SIZE:
            raise StateStoreError('The file does not contain a complete 32 MiB EE memory.')
        if archive.testzip() is not None:
            raise StateStoreError("The state file's integrity did not check out.")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_exclusive(source: Path, destination: Path):
    with source.open('rb') as incoming, destination.open('xb') as outgoing:
        for chunk in iter(lambda: incoming.read(1024*1024), b''):
            outgoing.write(chunk)
        outgoing.flush()
        os.fsync(outgoing.fileno())


def _paused(client):
    if client.status() is not Status.PAUSED:
        raise StateStoreError('Pause PCSX2 before exporting the edited state.')


def _wait_capture(client, candidates, timeout):
    deadline = time.monotonic()+timeout
    previous = None
    stable = 0
    last_error = None
    while time.monotonic() < deadline:
        _paused(client)
        found = [path for path in candidates if _present(path)]
        if len(found) > 1:
            raise StateStoreError('More than one file appeared for the slot. The files were kept.')
        if found:
            source = found[0]
            current = (source, _signature(source))
            stable = stable+1 if current == previous else 1
            previous = current
            if stable >= STABLE_POLLS:
                try:
                    _valid_archive(source)
                    if _signature(source) == current[1]:
                        return source, current[1]
                    stable = 0
                except (OSError, zipfile.BadZipFile, EOFError, StateStoreError) as error:
                    last_error = error
        else:
            stable, previous = 0, None
        time.sleep(min(POLL_INTERVAL, max(0.0, deadline-time.monotonic())))
    message = 'PCSX2 did not finish a valid state file in time. The files were kept.'
    if last_error:
        message += f' {last_error}'
    raise StateStoreError(message)


def export_state(client, emulator_root: Path, destination: Path, timeout: float = 15.0) -> dict:
    """Queue one unused slot, verify completion, copy exclusively and clean it.

    The caller must separately verify game identity and clean editor hooks.
    Failure after the request preserves its output. A destination copy is
    complete only after SHA-256 readback; no ambiguous request is repeated.
    """
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 20:
        raise StateStoreError('Use a timeout greater than zero and up to 20 seconds.')
    requested_destination = Path(destination)
    if _present(requested_destination):
        raise StateStoreError('The destination file already exists. Choose another name.')
    destination = requested_destination.resolve()
    if destination.suffix.lower() != '.p2s':
        raise StateStoreError('Choose a file with the .p2s extension.')
    try:
        _paused(client)
        states = _states_directory(Path(emulator_root))
        if _present(destination):
            raise StateStoreError('The destination file already exists. Choose another name.')
        selected = None
        for slot in range(9, -1, -1):
            candidates = _candidates(states, slot)
            if not any(_present(path) for path in candidates):
                selected = slot, candidates
                break
        if selected is None:
            raise StateStoreError('All ten slots already have files. No existing state will be replaced. '
                'In PCSX2, use System → Save state → File… and choose a new .p2s file.')
        slot, candidates = selected
        if destination in candidates:
            raise StateStoreError("Choose a destination other than PCSX2's temporary slot.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Recheck both names immediately before queuing; the ACK is not completion.
        _paused(client)
        if any(_present(path) for path in candidates):
            raise StateStoreError('The chosen slot became occupied. No request was sent.')
        client.request_save_state(slot)
        source, signature = _wait_capture(client, candidates, float(timeout))
        source_hash = _sha256(source)
        if _signature(source) != signature or [p for p in candidates if _present(p)] != [source]:
            raise StateStoreError('The state changed before the copy. The files were kept.')
        _paused(client)
        _copy_exclusive(source, destination)
        if _sha256(destination) != source_hash or _sha256(source) != source_hash or _signature(source) != signature:
            raise StateStoreError('The copy could not be confirmed. The files were kept.')
    except (OSError, zipfile.BadZipFile, EOFError) as error:
        raise StateStoreError('Could not export the state. Any files created were kept.') from error

    removed = False
    try:
        # Never remove a replaced, linked, ambiguous or changed temporary file.
        if (_regular_file(source) and source.resolve() in candidates
                and [p for p in candidates if _present(p)] == [source]
                and _sha256(source) == source_hash):
            source.unlink()
            removed = True
    except OSError:
        pass
    message = 'Edited state exported and copy verified.'
    if not removed:
        message += " The slot's temporary file was kept."
    return {'message': message, 'path': str(destination), 'sha256': source_hash,
            'saved_slot': slot, 'temporary_removed': removed, 'warning': not removed,
            'temporary_path': None if removed else str(source)}
