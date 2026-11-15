"""Restore one verified local state without treating a PINE ACK as completion.

The temporary load slot is created exclusively. A random, nonexecuted marker
in our idle data area must disappear before two paused target-memory checks
can confirm restoration, including when the target scene was already loaded.
The bounded evidence covers traffic, path descriptors and an available player
transform; it is not a bitwise comparison of the complete PS2 state.
No request is retried and no ambiguous load is rolled back.
"""
from __future__ import annotations

import math
from pathlib import Path
import secrets
import struct
import time
import zipfile

from . import profile, spawncode, state_store
from .pine import Status
from runtime.inspect_savestate import ORIGINAL_WORDS


POLL_INTERVAL = .10
STABLE_POLLS = 2
PROOF_REGIONS = ((0x539C10, 0x55B900-0x539C10), (0x55D720, 0xE0))
STATIC_PROOF_REGIONS = PROOF_REGIONS + (
    (profile.PATHS,profile.PATH_STRIDE*255),
    (profile.PLAYER_TRANSFORM_POINTER,4),
)


class RestoreError(ValueError):
    def __init__(self, message: str, *, uncertain: bool = False):
        super().__init__(message)
        self.uncertain = uncertain


def _paused(client):
    if client.status() is not Status.PAUSED:
        raise RestoreError('Pause o PCSX2 antes de restaurar o evento.')


def _identity(client):
    identity = client.identity()
    serial = ''.join(c for c in identity.get('game_id','').upper() if c.isalnum())
    crc = identity.get('game_crc','').upper().removeprefix('0X')
    if (serial != 'SLUS21050' or crc != 'BEBF8793'
            or '1.7.2521' not in identity.get('version','')):
        raise RestoreError('O emulador ou jogo não corresponde ao perfil do projeto.')
    return identity


def _read(client, address, length):
    result = client.read_bytes(address,length)
    if not isinstance(result,(bytes,bytearray)) or len(result) != length:
        raise RestoreError('A leitura da restauração ficou incompleta.')
    return bytes(result)


def _required_hash(value):
    if value is None:
        return None
    if (not isinstance(value,str) or len(value) != 64
            or any(char not in '0123456789abcdefABCDEF' for char in value)):
        raise RestoreError('A assinatura esperada do estado é inválida.')
    return value.lower()


def _check_required_hash(actual,required):
    if required is not None and actual != required:
        raise RestoreError('O estado não corresponde à assinatura registrada no projeto. '
                           'Nenhum carregamento ou escrita foi solicitado.')


def _saved_proof(source):
    state_store._valid_archive(source)
    with zipfile.ZipFile(source) as archive:
        data = archive.read('eeMemory.bin')
    if any(struct.unpack_from('<I',data,address)[0] != word
           for address,word in ORIGINAL_WORDS.items()):
        raise RestoreError('O estado não contém o código USA admitido pelo editor.')
    hook = data[spawncode.HOOK:spawncode.HOOK+8]
    cave = data[spawncode.CAVE:spawncode.END]
    if (hook != spawncode.ORIGINAL
            or cave not in (bytes(4096),spawncode.clean_batch_scratch())):
        raise RestoreError('O estado contém código alterado ou uma criação pendente. Use um estado finalizado.')
    regions = [(address,data[address:address+length]) for address,length in STATIC_PROOF_REGIONS]
    pointer = struct.unpack_from('<I',data,profile.PLAYER_TRANSFORM_POINTER)[0]
    if pointer and pointer % 16 == 0 and pointer <= state_store.EE_MEMORY_SIZE-0x40:
        regions.append((pointer,data[pointer:pointer+0x40]))
    # An absent or invalid optional player pointer is still compared verbatim;
    # never follow it outside EE RAM or invent a player transform at address 0.
    return cave,tuple(regions)


def _target_matches(client, identity, cave, regions):
    if _identity(client) != identity:
        raise RestoreError('A identidade do emulador mudou durante a restauração.')
    if (_read(client,spawncode.HOOK,8) != spawncode.ORIGINAL
            or _read(client,spawncode.CAVE,4096) != cave):
        return False
    for address,expected in regions:
        if _read(client,address,len(expected)) != expected:
            return False
    # A core resumed during a long memory read is never accepted as a snapshot.
    return (client.status() is Status.PAUSED
            and _read(client,spawncode.HOOK,8) == spawncode.ORIGINAL
            and _read(client,spawncode.CAVE,4096) == cave)


def verify_current_state(client, source: Path, *, expected_sha256: str | None = None) -> dict:
    """Verify an explicitly user-loaded/saved scene, without queuing a load.

    This is the manual-menu fallback when no test slot is free. Matching the
    current checked EE regions is sufficient here: this call has no outstanding
    load request, unlike ``restore_state`` and its mandatory challenge marker.
    The controller must separately reject pending or ambiguous earlier work.
    An expected digest binds this proof to the caller's verified manifest.
    """
    required_hash = _required_hash(expected_sha256)
    try:
        requested = Path(source)
        if requested.suffix.lower() != '.p2s' or not state_store._regular_file(requested):
            raise RestoreError('Selecione um arquivo .p2s regular do projeto.')
        source = requested.resolve(strict=True)
        signature = state_store._signature(source)
        expected_hash = state_store._sha256(source)
        _check_required_hash(expected_hash,required_hash)
        cave,regions = _saved_proof(source)
        _paused(client)
        identity = _identity(client)
        for index in range(STABLE_POLLS):
            _paused(client)
            if not _target_matches(client,identity,cave,regions):
                raise RestoreError('A memória atual não corresponde ao estado selecionado. '
                                   'Carregue o arquivo pelo menu do PCSX2, pause e confirme novamente.')
            if index+1 < STABLE_POLLS:
                time.sleep(POLL_INTERVAL)
        if (state_store._signature(source) != signature
                or state_store._sha256(source) != expected_hash):
            raise RestoreError('O estado mudou durante a conferência. Nenhuma alteração foi aplicada.')
        _check_required_hash(expected_hash,required_hash)
    except RestoreError:
        raise
    except Exception as error:
        raise RestoreError('Não foi possível conferir o estado selecionado. Nenhuma alteração foi aplicada.') from error
    return {'path':str(source),'sha256':expected_hash,'core_paused':True,
            'verified_current':True,
            'message':'A memória verificada da cena atual corresponde ao arquivo. '
                      'Nenhum carregamento ou escrita foi solicitado pelo editor.'}


def restore_state(client, emulator_root: Path, source: Path, *, timeout: float = 15.0,
                  expected_sha256: str | None = None) -> dict:
    """Load an unchanged file once, returning only after paused EE evidence.

    A failed marker write or any later failure has ``uncertain=True``. The
    controller must then block editing until a clean scene has been recovered;
    a queued load could still execute. Temporary files are preserved on errors.
    When supplied, the manifest digest is checked before any marker or request.
    """
    if type(timeout) not in (int,float) or not 0 < timeout <= 20 or not math.isfinite(timeout):
        raise RestoreError('Use um prazo maior que zero e de até 20 segundos.')
    required_hash = _required_hash(expected_sha256)
    requested = Path(source)
    uncertain = False
    try:
        # Reject a link before resolve(), which otherwise hides that evidence.
        if requested.suffix.lower() != '.p2s' or not state_store._regular_file(requested):
            raise RestoreError('Selecione um arquivo .p2s regular do projeto.')
        source = requested.resolve(strict=True)
        signature = state_store._signature(source)
        expected_hash = state_store._sha256(source)
        _check_required_hash(expected_hash,required_hash)
        cave,regions = _saved_proof(source)
        if (state_store._signature(source) != signature
                or state_store._sha256(source) != expected_hash):
            raise RestoreError('O estado mudou durante a validação. Nenhuma restauração foi enviada.')
        _check_required_hash(expected_hash,required_hash)
        _paused(client)
        identity = _identity(client)
        current_cave = _read(client,spawncode.CAVE,4096)
        if (_read(client,spawncode.HOOK,8) != spawncode.ORIGINAL
                or current_cave not in (bytes(4096),spawncode.clean_batch_scratch())):
            raise RestoreError('Finalize a criação pendente antes de restaurar o projeto.')
        states = state_store._states_directory(Path(emulator_root))
        selected = None
        for slot in range(9,-1,-1):
            candidates = state_store._candidates(states,slot)
            if not any(state_store._present(path) for path in candidates):
                selected = slot,candidates
                break
        if selected is None:
            raise RestoreError('Todos os dez slots já têm arquivos. Libere um slot de teste ou carregue '
                               'o .p2s pelo menu do PCSX2; nenhum arquivo existente foi substituído.')
        slot,candidates = selected
        temporary = candidates[0]
        temporary.parent.mkdir(parents=True,exist_ok=True)
        state_store._copy_exclusive(source,temporary)
        if (state_store._sha256(temporary) != expected_hash
                or state_store._sha256(source) != expected_hash
                or state_store._signature(source) != signature
                or [p for p in candidates if state_store._present(p)] != [temporary]):
            raise RestoreError('O slot ou o estado mudou antes da restauração. Os arquivos foram preservados.')

        _paused(client)
        if (_identity(client) != identity
                or _read(client,spawncode.HOOK,8) != spawncode.ORIGINAL
                or _read(client,spawncode.CAVE,4096) != current_cave):
            raise RestoreError('O jogo mudou antes da restauração. Nenhuma solicitação foi enviada.')
        # This is data in our canonical idle area, never an instruction or hook.
        # Both admitted saved-state templates have zero bytes at this location.
        marker = secrets.token_bytes(16)
        if marker == bytes(16):
            marker = b'B3RestoreProof!!'  # Exactly 16 bytes, nonzero fallback.
        marked = bytearray(current_cave)
        offset = spawncode.NONCE_ADDRESS-spawncode.CAVE
        marked[offset:offset+16] = marker
        uncertain = True
        client.write_bytes(spawncode.NONCE_ADDRESS,marker)
        if (_read(client,spawncode.CAVE,4096) != bytes(marked)
                or _read(client,spawncode.HOOK,8) != spawncode.ORIGINAL):
            raise RestoreError('O marcador de restauração não pôde ser confirmado.')
        _paused(client)
        # Recheck exclusive slot ownership immediately before the sole request.
        if ([p for p in candidates if state_store._present(p)] != [temporary]
                or not state_store._regular_file(temporary)
                or state_store._sha256(temporary) != expected_hash):
            raise RestoreError('O slot temporário mudou. Nenhuma nova tentativa será enviada.')
        client.request_load_state(slot)
        deadline = time.monotonic()+float(timeout)
        stable = 0
        while time.monotonic() < deadline:
            status = client.status()
            if status is Status.SHUTDOWN:
                raise RestoreError('O jogo foi encerrado durante a restauração.')
            if status is Status.PAUSED and _target_matches(client,identity,cave,regions):
                stable += 1
                if stable >= STABLE_POLLS:
                    break
            else:
                stable = 0
            time.sleep(min(POLL_INTERVAL,max(0.,deadline-time.monotonic())))
        else:
            raise RestoreError('O PCSX2 não confirmou o estado restaurado dentro do prazo. '
                               'Não repita automaticamente; recupere uma cena limpa antes de editar.')
    except RestoreError as error:
        if uncertain and not error.uncertain:
            raise RestoreError(str(error),uncertain=True) from error
        raise
    except Exception as error:
        raise RestoreError('Não foi possível confirmar a restauração. Os arquivos foram preservados.',
                           uncertain=uncertain) from error

    removed = False
    try:
        if (state_store._regular_file(temporary)
                and [p for p in candidates if state_store._present(p)] == [temporary]
                and state_store._sha256(temporary) == expected_hash
                and state_store._sha256(source) == expected_hash):
            temporary.unlink()
            removed = True
    except OSError:
        pass
    message = 'Cena restaurada e memória confirmada. O PCSX2 permanece pausado.'
    if not removed:
        message += ' O arquivo temporário do slot foi preservado.'
    return {'message':message,'path':str(source),'sha256':expected_hash,'loaded_slot':slot,
            'core_paused':True,'temporary_removed':removed,'warning':not removed,
            'temporary_path':None if removed else str(temporary)}
