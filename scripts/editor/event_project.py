"""Local named Crash scenes backed by verified, immutable state snapshots.

Only the small manifest is replaced on save. Base and earlier scene files
remain untouched. State archives stay local and are never extracted here.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import zipfile

from . import state_store


class ProjectError(ValueError):
    pass


FORMAT = 'burnout3-crash-event-project'
VERSION = 1
PROFILE = 'SLUS21050/BEBF8793'
EMULATOR = '1.7.2521'
MANIFEST = 'event.b3event.json'
MAX_MANIFEST_BYTES = 131072
MAX_REVISION = 1000000
_SCENE_NAME = re.compile(r'scene-[0-9a-f]{32}\.p2s\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_IO_ERRORS = (OSError, UnicodeError, zipfile.BadZipFile, EOFError, state_store.StateStoreError)


def _regular(path: Path) -> bool:
    return state_store._regular_file(path)


def _directory(path: Path) -> bool:
    info = path.lstat()
    reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
    return stat.S_ISDIR(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & reparse)


def _root(path: Path) -> Path:
    if not _directory(path):
        raise ProjectError('The project folder cannot be a link or a redirect.')
    return path.resolve(strict=True)


def _name(value) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value.strip()) > 100
            or any(ord(char) < 32 or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF for char in value)):
        raise ProjectError('Enter an event name of 1 to 100 characters, without control characters.')
    return value.strip()


def _json_dict(value, label):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ProjectError(f'{label} precisa ser um objeto JSON.')
    def check(item, depth=0):
        if depth > 32:
            raise ProjectError(f'{label} exceeds the structure limit.')
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float and math.isfinite(item):
            return
        if isinstance(item, list):
            for child in item:
                check(child, depth+1)
            return
        if isinstance(item, dict) and all(type(key) is str for key in item):
            for child in item.values():
                check(child, depth+1)
            return
        raise ProjectError(f'{label} contains an invalid JSON value.')
    check(value)
    # Copy metadata so the caller cannot mutate the saved payload by alias.
    try:
        text = json.dumps(value, ensure_ascii=False, allow_nan=False)
        size = len(text.encode('utf8'))
    except (ValueError, UnicodeError, OverflowError) as error:
        raise ProjectError(f'{label} contains an invalid JSON value.') from error
    if size > 98304:
        raise ProjectError(f'{label} exceeds the size limit.')
    return json.loads(text)


def _record(record, *, scene=False):
    expected = {'file','sha256','revision'} if scene else {'file','sha256'}
    if not isinstance(record, dict) or set(record) != expected:
        raise ProjectError('Invalid state reference in the project.')
    filename, digest = record.get('file'), record.get('sha256')
    if (not isinstance(filename, str) or (filename != 'base.p2s' and not _SCENE_NAME.fullmatch(filename))
            or not isinstance(digest, str) or not _SHA.fullmatch(digest)):
        raise ProjectError("The project's state must be an internal file with a valid hash.")
    if not scene and filename != 'base.p2s':
        raise ProjectError('The initial reference must use base.p2s.')
    if scene:
        revision = record['revision']
        if type(revision) is not int or not 0 <= revision <= MAX_REVISION:
            raise ProjectError('Invalid scene revision.')
        if (revision == 0) != (filename == 'base.p2s'):
            raise ProjectError('The scene revision does not match the file.')
    return dict(record)


def _payload(data):
    required = {'format','version','profile','emulator','name','base','scene','recipe','summary'}
    if not isinstance(data, dict) or set(data) != required:
        raise ProjectError('Invalid project manifest.')
    if (data['format'] != FORMAT or type(data['version']) is not int or data['version'] != VERSION
            or data['profile'] != PROFILE or data['emulator'] != EMULATOR):
        raise ProjectError('Project incompatible with Burnout 3 USA / PCSX2 1.7.2521.')
    result = {**data,'name':_name(data['name']), 'base':_record(data['base']),
              'scene':_record(data['scene'],scene=True),
              'recipe':_json_dict(data['recipe'],'Receita'),
              'summary':_json_dict(data['summary'],'Resumo')}
    if result['scene']['revision'] == 0 and result['scene']['sha256'] != result['base']['sha256']:
        raise ProjectError("The initial scene does not match the project's reference.")
    return result


def _encode(payload) -> bytes:
    encoded = (json.dumps(_payload(payload), ensure_ascii=False, allow_nan=False, indent=2)+'\n').encode('utf8')
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise ProjectError("The manifest exceeds the project's size limit.")
    return encoded


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProjectError('The manifest contains repeated fields.')
        result[key] = value
    return result


def _manifest_bytes(path: Path):
    if not _regular(path) or not 0 < path.stat().st_size <= MAX_MANIFEST_BYTES:
        raise ProjectError('The manifest is not a regular file of an admitted size.')
    raw = path.read_bytes()
    if not 0 < len(raw) <= MAX_MANIFEST_BYTES:
        raise ProjectError('The manifest exceeds the size limit.')
    return raw


def _verified_state(root: Path, record):
    path = root/record['file']
    if path.resolve(strict=True).parent != root or not _regular(path):
        raise ProjectError('The state must be a regular file inside the project folder.')
    signature = state_store._signature(path)
    state_store._valid_archive(path)
    if state_store._sha256(path) != record['sha256'] or state_store._signature(path) != signature:
        raise ProjectError("The project's state changed or its hash does not match.")
    return path


def load(manifest: Path) -> dict:
    """Validate manifest and every referenced archive without loading the VM."""
    try:
        requested = Path(manifest)
        if requested.name != MANIFEST:
            raise ProjectError(f'Select the {MANIFEST} file.')
        root = _root(requested.parent)
        path = root/MANIFEST
        raw = _manifest_bytes(path)
        try:
            data = json.loads(raw.decode('utf8'), object_pairs_hook=_no_duplicate_keys)
        except ProjectError:
            raise
        except (ValueError, RecursionError) as error:
            raise ProjectError('The file does not contain a valid JSON manifest.') from error
        payload = _payload(data)
        base = _verified_state(root,payload['base'])
        scene = base if payload['scene']['file'] == 'base.p2s' else _verified_state(root,payload['scene'])
        if _manifest_bytes(path) != raw:
            raise ProjectError('The manifest changed during the read. Open the project again.')
        return {**payload,'path':str(path),'base_path':str(base),'scene_path':str(scene),
                '_manifest_sha256':hashlib.sha256(raw).hexdigest()}
    except _IO_ERRORS as error:
        raise ProjectError(f'Could not open the project: {error}') from error


def _expected_source_digest(value):
    if value is not None and (not isinstance(value,str) or not _SHA.fullmatch(value)):
        raise ProjectError("The state's expected hash must have 64 lowercase hexadecimal characters.")
    return value


def _copy_state(source: Path, root: Path, filename: str, *, expected_source_sha256=None):
    expected_source_sha256 = _expected_source_digest(expected_source_sha256)
    source = Path(source)
    if not _regular(source) or source.suffix.lower() != '.p2s':
        raise ProjectError('Choose a regular .p2s state, not a link.')
    signature = state_store._signature(source)
    state_store._valid_archive(source)
    digest = state_store._sha256(source)
    if expected_source_sha256 is not None and digest != expected_source_sha256:
        raise ProjectError('The state changed since the check. No scene was published to the project.')
    destination = root/filename
    state_store._copy_exclusive(source,destination)
    if (state_store._sha256(destination) != digest or state_store._sha256(source) != digest
            or state_store._signature(source) != signature):
        raise ProjectError('The state changed during the copy. The files were kept.')
    _verified_state(root,{'file':filename,'sha256':digest})
    return {'file':filename,'sha256':digest}


def create(directory: Path, name: str, base_state: Path, *, recipe=None, summary=None,
           expected_source_sha256: str | None = None) -> dict:
    """Create a new folder only, keeping the supplied source file untouched."""
    event_name = _name(name)
    expected_source_sha256 = _expected_source_digest(expected_source_sha256)
    recipe, summary = _json_dict(recipe,'Receita'), _json_dict(summary,'Resumo')
    try:
        requested = Path(directory)
        requested.parent.mkdir(parents=True,exist_ok=True)
        root = requested.parent.resolve(strict=True)/requested.name
        root.mkdir()  # Refuse even an existing empty directory or broken link.
        base = _copy_state(Path(base_state),root,'base.p2s',expected_source_sha256=expected_source_sha256)
        payload = dict(format=FORMAT,version=VERSION,profile=PROFILE,emulator=EMULATOR,
            name=event_name,base=base,scene={**base,'revision':0},recipe=recipe,summary=summary)
        encoded = _encode(payload)
        with (root/MANIFEST).open('xb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        return load(root/MANIFEST)
    except _IO_ERRORS as error:
        raise ProjectError(f'Could not create the project. Existing files were kept: {error}') from error


@contextmanager
def _write_lock(root: Path):
    path, token = root/'.event-write.lock', secrets.token_hex(16).encode('ascii')
    try:
        with path.open('xb') as stream:
            stream.write(token)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ProjectError('Another project write is in progress. Wait before saving again.') from error
    try:
        yield
    finally:
        try:
            if _regular(path) and path.read_bytes() == token:
                path.unlink()
        except OSError:
            pass


def save_scene(project: dict, source: Path, *, recipe=None, summary=None,
               expected_source_sha256: str | None = None) -> dict:
    """Save a fresh snapshot; atomically publish its manifest after verification."""
    if not isinstance(project,dict) or not isinstance(project.get('path'),str):
        raise ProjectError('Open or create a project before saving the scene.')
    expected_source_sha256 = _expected_source_digest(expected_source_sha256)
    recipe, summary = _json_dict(recipe,'Receita'), _json_dict(summary,'Resumo')
    try:
        current = load(Path(project['path']))
        if (current['_manifest_sha256'] != project.get('_manifest_sha256')
                or current['base'] != project.get('base') or current['scene'] != project.get('scene')):
            raise ProjectError('The project changed since it was opened. Open it again before saving.')
        if current['scene']['revision'] >= MAX_REVISION:
            raise ProjectError('The project reached the revision limit of this version.')
        root = Path(current['path']).parent
        with _write_lock(root):
            if hashlib.sha256(_manifest_bytes(root/MANIFEST)).hexdigest() != current['_manifest_sha256']:
                raise ProjectError('The project changed before the write. Open it again.')
            scene = _copy_state(Path(source),root,'scene-'+secrets.token_hex(16)+'.p2s',
                                expected_source_sha256=expected_source_sha256)
            scene['revision'] = current['scene']['revision']+1
            payload = {key:current[key] for key in ('format','version','profile','emulator','name','base')}
            payload.update(scene=scene,recipe=recipe,summary=summary)
            encoded = _encode(payload)
            temporary = root/('.manifest-'+secrets.token_hex(16)+'.tmp')
            with temporary.open('xb') as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            if (not _regular(root/MANIFEST)
                    or hashlib.sha256(_manifest_bytes(root/MANIFEST)).hexdigest() != current['_manifest_sha256']):
                raise ProjectError('The manifest changed before publishing. The files were kept.')
            os.replace(temporary,root/MANIFEST)
        return load(root/MANIFEST)
    except _IO_ERRORS as error:
        raise ProjectError(f'Could not save the scene. Previous versions were kept: {error}') from error


def public_info(project: dict) -> dict:
    return {key:project[key] for key in ('path','name','base_path','scene_path')} | {
        'scene_revision':project['scene']['revision']}
