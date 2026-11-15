"""Free a known Burnout slot only after preserving verified local copies.

The caller owns emulator identity, pause and pending-request checks. This
module never sends emulator commands or deletes arbitrary paths. A concurrent
filesystem change cancels the operation rather than replacing files.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import secrets
import stat

from . import state_store


class SlotArchiveError(ValueError):
    def __init__(self,message: str,*,partial=False,archive_directory=None):
        super().__init__(message)
        self.partial = bool(partial)
        self.uncertain = bool(partial)
        self.archive_directory = str(archive_directory) if archive_directory else None


MAX_SLOT_FILE_BYTES = state_store.MAX_ARCHIVE_SIZE


def _slot(value):
    if type(value) is not int or not 0 <= value <= 9:
        raise SlotArchiveError('Escolha um slot de 0 a 9.')
    return value


def _directory(path):
    info = path.lstat()
    return (stat.S_ISDIR(info.st_mode)
            and not (getattr(info,'st_file_attributes',0) & getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0)))


def _location(emulator_root):
    root = Path(emulator_root).resolve(strict=True)
    states = state_store._states_directory(root)
    if state_store._present(states) and not _directory(states):
        raise SlotArchiveError('A pasta de estados não é um diretório regular.')
    return root,states


def _candidate_issue(states,path):
    # The configured states root is canonical. Do not traverse an optional
    # nested game directory if that child was replaced by a junction/link.
    if path.parent != states and not _directory(path.parent):
        return 'A pasta do slot é um link ou redirecionamento.'
    if not state_store._regular_file(path):
        return 'O slot contém um link ou arquivo não regular.'
    info = path.lstat()
    if not 0 <= info.st_size <= MAX_SLOT_FILE_BYTES:
        return 'O arquivo ultrapassa o tamanho admitido para arquivamento.'
    if path.resolve(strict=True) != path:
        return 'O caminho do slot foi redirecionado.'
    return None


def list_slots(emulator_root: Path) -> list[dict]:
    """List just this profile's two recognized filenames for each slot."""
    try:
        _root,states = _location(emulator_root)
        result = []
        for slot in range(10):
            paths = [path for path in state_store._candidates(states,slot) if state_store._present(path)]
            reasons = []
            total = 0
            for path in paths:
                issue = _candidate_issue(states,path)
                if issue:
                    reasons.append(issue)
                total += path.lstat().st_size
            result.append(dict(slot=slot,occupied=bool(paths),paths=[str(path) for path in paths],
                total_bytes=total,blocked=bool(reasons),reason=' '.join(dict.fromkeys(reasons))))
        return result
    except SlotArchiveError:
        raise
    except (OSError,state_store.StateStoreError) as error:
        raise SlotArchiveError(f'Não foi possível listar os slots: {error}') from error


def _identity(path):
    info = path.lstat()
    return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)


def _same_source(states,entry):
    path = entry['source']
    return (state_store._present(path) and _candidate_issue(states,path) is None
            and _identity(path) == entry['identity']
            and state_store._sha256(path) == entry['sha256'])


def _check_sources(states,candidates,entries):
    if [path for path in candidates if state_store._present(path)] != [entry['source'] for entry in entries]:
        raise SlotArchiveError('Os arquivos do slot mudaram durante o arquivamento.')
    if not all(_same_source(states,entry) for entry in entries):
        raise SlotArchiveError('Um arquivo do slot mudou durante o arquivamento.')


def _backup_directory(root,slot):
    parent = root/'editor-slot-backups'
    if state_store._present(parent):
        if not _directory(parent):
            raise SlotArchiveError('A pasta de cópias dos slots é um link ou redirecionamento.')
    else:
        parent.mkdir()
    if parent.resolve(strict=True).parent != root:
        raise SlotArchiveError('A pasta de cópias saiu da instalação do emulador.')
    name = f'slot{slot:02d}-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(8)
    directory = parent/name
    directory.mkdir()
    return directory


def archive_slot(emulator_root: Path,slot: int,*,guard=None) -> dict:
    """Copy all selected candidates first, then unlink only unchanged sources.

    Empty or damaged regular state archives can also be freed: their exact
    bytes are retained rather than requiring a valid save to preserve them.
    Removal is best effort under concurrent external writes, never atomic.
    """
    slot = _slot(slot)
    directory = None
    removed = []
    try:
        if guard is not None:
            guard()
        root,states = _location(emulator_root)
        candidates = state_store._candidates(states,slot)
        paths = [path for path in candidates if state_store._present(path)]
        if not paths:
            raise SlotArchiveError('Esse slot já está livre.')
        entries = []
        for path in paths:
            issue = _candidate_issue(states,path)
            if issue:
                raise SlotArchiveError(issue+' Nenhum arquivo foi removido.')
            identity = _identity(path)
            digest = state_store._sha256(path)
            if _identity(path) != identity:
                raise SlotArchiveError('O slot mudou durante a leitura. Nenhum arquivo foi removido.')
            entries.append(dict(source=path,identity=identity,sha256=digest))
        if guard is not None:
            guard()
        directory = _backup_directory(root,slot)
        backups = []
        for entry in entries:
            label = 'flat' if entry['source'].parent == states else 'nested'
            target_parent = directory/label
            target_parent.mkdir()
            destination = target_parent/entry['source'].name
            state_store._copy_exclusive(entry['source'],destination)
            if (not state_store._regular_file(destination)
                    or state_store._sha256(destination) != entry['sha256']):
                raise SlotArchiveError('A cópia do slot não pôde ser confirmada.')
            entry['backup'] = destination
            backups.append(dict(source=str(entry['source']),path=str(destination),sha256=entry['sha256']))
        if guard is not None:
            guard()
        _check_sources(states,candidates,entries)
        manifest = directory/'backup.json'
        with manifest.open('x',encoding='utf8') as stream:
            json.dump(dict(format='burnout3-slot-backup',version=1,slot=slot,files=backups),
                      stream,ensure_ascii=False,indent=2)
            stream.write('\n')
            stream.flush()
        remaining = list(entries)
        for entry in entries:
            # Recheck every remaining source and every preserved copy before
            # removing one exact filename. Never unlink a replaced path/link.
            if guard is not None:
                guard()
            _check_sources(states,candidates,remaining)
            if not all(state_store._regular_file(e['backup'])
                       and state_store._sha256(e['backup']) == e['sha256'] for e in entries):
                raise SlotArchiveError('Uma cópia mudou antes de liberar o slot.')
            if not _same_source(states,entry):
                raise SlotArchiveError('O arquivo do slot foi substituído antes da remoção.')
            entry['source'].unlink()
            removed.append(str(entry['source']))
            remaining.remove(entry)
        if any(state_store._present(path) for path in candidates):
            raise SlotArchiveError('Outro arquivo apareceu no slot; ele foi preservado.')
    except Exception as error:
        note = f' Cópias eventualmente criadas foram preservadas em {directory}.' if directory else ''
        if removed:
            note += ' Parte do slot já foi arquivada; não repita automaticamente.'
        raise SlotArchiveError(str(error)+note,partial=bool(removed),archive_directory=directory) from error
    return dict(slot=slot,archive_directory=str(directory),paths=[item['path'] for item in backups],
                source_paths=removed,backups=backups,
                message=f'Slot {slot} liberado. Saves preservados em {directory}.')
