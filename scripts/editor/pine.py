"""Bounded stdlib PINE client for PCSX2's EE RAM and metadata.

Protocol checked against official PCSX2 tag v1.7.2521, PINE.h/PINE.cpp.
No emulator configuration, startup or process-memory access is performed.
Writes are opt-in. PINE batches are sequential commands, NOT transactions;
pause/readback guards cannot eliminate a concurrent user's resume race.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import ipaddress
import socket
import struct
import threading
from typing import Iterable, Sequence

DEFAULT_PORT = 28011
RAM_SIZE = 32 * 1024 * 1024
MAX_REQUEST = 650000
MAX_REPLY = 449999  # Server's SafetyChecks rejects a final size >=450000.
MAX_STRING = 65536
MAX_COMMANDS = 8192


class PineError(RuntimeError):
    pass


class PineProtocolError(PineError):
    pass


class PineRemoteError(PineError):
    """Earlier commands in the failed batch may already have executed."""


class PineTransportError(PineError):
    def __init__(self, message: str, *, may_have_executed: bool):
        super().__init__(message)
        self.may_have_executed = may_have_executed


class PineWriteDisabled(PineError):
    pass


class PineNotPaused(PineError):
    pass


class PinePatchConflict(PineError):
    pass


class PineVerificationError(PineError):
    pass


class Status(IntEnum):
    RUNNING = 0
    PAUSED = 1
    SHUTDOWN = 2


@dataclass(frozen=True)
class Write:
    address: int
    width: int
    value: int


@dataclass(frozen=True)
class Patch:
    address: int
    width: int
    expected: int
    value: int


@dataclass(frozen=True)
class _Command:
    payload: bytes
    result: int | str  # Fixed byte count, or length-prefixed NUL string.


def _unsigned(value: int, bits: int, name: str) -> int:
    if type(value) is not int or not 0 <= value < (1 << bits):
        raise ValueError(f'{name} must be an unsigned {bits}-bit integer')
    return value


def _address(address: int, width: int) -> None:
    if type(width) is not int or width not in (1, 2, 4, 8):
        raise ValueError('RAM width must be 1, 2, 4 or 8 bytes')
    _unsigned(address, 32, 'address')
    if address % width or address + width > RAM_SIZE:
        raise ValueError('Only aligned, bounded physical EE RAM is admitted')


def _read(address: int, width: int) -> _Command:
    _address(address, width)
    return _Command(bytes(((1, 2, 4, 8).index(width),)) + struct.pack('<I', address), width)


def _write(write: Write) -> _Command:
    if not isinstance(write, Write):
        raise TypeError('Expected Write records')
    _address(write.address, write.width)
    _unsigned(write.value, write.width * 8, 'value')
    opcode = 4 + (1, 2, 4, 8).index(write.width)
    return _Command(bytes((opcode,)) + struct.pack('<I', write.address)
                    + write.value.to_bytes(write.width, 'little'), 0)


class PineClient:
    """One persistent loopback connection; no automatic retry of any command.

    `Status.PAUSED` means PCSX2 core suspension (Escape/System pause) in this
    old wx build. Its in-game menu and Input Recording pause do not reliably
    report this state. There is no pause/resume opcode in this protocol.
    """
    def __init__(self, host: str = '127.0.0.1', port: int = DEFAULT_PORT,
                 timeout: float = 2.0, *, allow_writes: bool = False):
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError as error:
            raise ValueError('Use an explicit loopback IP address') from error
        if not loopback:
            raise ValueError('Only loopback emulator endpoints are admitted')
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('Port must be in 1..65535')
        if not isinstance(timeout, (int, float)) or not 0 < timeout <= 60:
            raise ValueError('Timeout must be positive and at most 60 seconds')
        self.host, self.port, self.timeout = host, port, float(timeout)
        if type(allow_writes) is not bool:
            raise TypeError('allow_writes must be explicitly True or False')
        self.allow_writes = allow_writes
        self._socket: socket.socket | None = None
        self._lock = threading.RLock()

    def connect(self) -> 'PineClient':
        with self._lock:
            if self._socket is None:
                try:
                    self._socket = socket.create_connection((self.host, self.port), self.timeout)
                    self._socket.settimeout(self.timeout)
                except OSError as error:
                    self.close()
                    raise PineTransportError(str(error), may_have_executed=False) from error
        return self

    def close(self) -> None:
        with self._lock:
            connection, self._socket = self._socket, None
            if connection is not None:
                connection.close()

    def __enter__(self):
        return self.connect()

    def __exit__(self, *_):
        self.close()

    def _recv_exact(self, size: int) -> bytes:
        result = bytearray()
        while len(result) < size:
            part = self._socket.recv(size - len(result))
            if not part:
                raise OSError('PINE connection ended inside a frame')
            result.extend(part)
        return bytes(result)

    def _exchange(self, commands: Sequence[_Command]) -> list[int | str]:
        if not commands or len(commands) > MAX_COMMANDS:
            raise ValueError('Choose a bounded, nonempty command batch')
        payload = b''.join(command.payload for command in commands)
        if len(payload) + 4 > MAX_REQUEST:
            raise ValueError('Request exceeds server frame limit')
        minimum_reply = 5 + sum(c.result if type(c.result) is int else 4 for c in commands)
        if minimum_reply > MAX_REPLY:
            raise ValueError('Reply would exceed server frame limit')
        frame = struct.pack('<I', len(payload) + 4) + payload
        with self._lock:
            self.connect()
            sent = False
            try:
                sent = True  # sendall can fail after a partial send.
                self._socket.sendall(frame)
                length = struct.unpack('<I', self._recv_exact(4))[0]
                if not 5 <= length <= MAX_REPLY:
                    raise PineProtocolError('Invalid PINE reply length')
                body = self._recv_exact(length - 4)
                if body[0] == 255:
                    if length != 5:
                        raise PineProtocolError('Malformed failed reply')
                    raise PineRemoteError('PINE rejected the batch; earlier commands may have executed')
                if body[0] != 0:
                    raise PineProtocolError('Unknown PINE reply status')
                cursor, values = 1, []
                for command in commands:
                    if type(command.result) is int:
                        end = cursor + command.result
                        if end > len(body):
                            raise PineProtocolError('Truncated command reply')
                        values.append(int.from_bytes(body[cursor:end], 'little'))
                        cursor = end
                    else:
                        if cursor + 4 > len(body):
                            raise PineProtocolError('Truncated string length')
                        size = struct.unpack_from('<I', body, cursor)[0]
                        cursor += 4
                        if not 1 <= size <= MAX_STRING or cursor + size > len(body):
                            raise PineProtocolError('Invalid string reply length')
                        value = body[cursor:cursor + size]
                        cursor += size
                        if not value.endswith(b'\0') or b'\0' in value[:-1]:
                            raise PineProtocolError('Malformed NUL-terminated string')
                        try:
                            values.append(value[:-1].decode('utf-8'))
                        except UnicodeDecodeError as error:
                            raise PineProtocolError('Invalid UTF-8 metadata') from error
                if cursor != len(body):
                    raise PineProtocolError('Unexpected trailing reply bytes')
                return values
            except (PineProtocolError, PineRemoteError):
                self.close()
                raise
            except OSError as error:
                self.close()
                raise PineTransportError(str(error), may_have_executed=sent) from error

    def status(self) -> Status:
        value = self._exchange([_Command(b'\x0f', 4)])[0]
        try:
            return Status(value)
        except ValueError as error:
            self.close()
            raise PineProtocolError('Unknown emulator status') from error

    def identity(self) -> dict[str, str]:
        # Version/ID/CRC require an active VM in this exact older server.
        values = self._exchange([_Command(bytes((n,)), 'string') for n in (8, 12, 13)])
        return dict(zip(('version', 'game_id', 'game_crc'), values))

    def metadata(self) -> dict[str, str]:
        values = self._exchange([_Command(bytes((n,)), 'string') for n in (8, 11, 12, 13, 14)])
        return dict(zip(('version', 'title', 'game_id', 'game_crc', 'game_version'), values))

    def read_many(self, requests: Iterable[tuple[int, int]]) -> list[int]:
        commands = [_read(address, width) for address, width in requests]
        if not commands:
            return []
        return self._exchange(commands)

    def read(self, address: int, width: int = 4) -> int:
        return self.read_many([(address, width)])[0]

    def read_bytes(self, address: int, length: int) -> bytes:
        _unsigned(address, 32, 'address')
        if type(length) is not int or length < 0 or address + length > RAM_SIZE:
            raise ValueError('Read must remain inside physical EE RAM')
        output, requests = bytearray(), []
        end = address + length
        with self._lock:
            while address < end:
                width = next(w for w in (8, 4, 2, 1) if address % w == 0 and address + w <= end)
                requests.append((address, width))
                address += width
                if len(requests) == MAX_COMMANDS or address == end:
                    values = self.read_many(requests)
                    for (_, size), value in zip(requests, values):
                        output.extend(value.to_bytes(size, 'little'))
                    requests.clear()
        return bytes(output)

    def _write_access(self, require_paused: bool):
        if not self.allow_writes:
            raise PineWriteDisabled('This client was opened without write permission')
        if require_paused and self.status() is not Status.PAUSED:
            raise PineNotPaused('Suspend the PCSX2 core before editing (in-game pause is insufficient)')

    def write_many(self, writes: Iterable[Write], *, require_paused: bool = True) -> None:
        items = list(writes)
        commands = [_write(item) for item in items]  # Preflight all entries before any send.
        if not commands:
            return
        with self._lock:
            self._write_access(require_paused)
            self._exchange(commands)
            if require_paused and self.status() is not Status.PAUSED:
                raise PineNotPaused('Core pause changed during writes; results require inspection')

    def write(self, address: int, value: int, width: int = 4, *, require_paused: bool = True) -> None:
        self.write_many([Write(address, width, value)], require_paused=require_paused)

    def write_bytes(self, address: int, data: bytes, *, require_paused: bool = True) -> None:
        """Write a bounded patch as aligned commands; the batch is not atomic."""
        _unsigned(address, 32, 'address')
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError('Patch data must be bytes')
        if len(data) > 65536 or address + len(data) > RAM_SIZE:
            raise ValueError('Byte patch must be at most64KiB and inside physical EE RAM')
        cursor, writes = 0, []
        while cursor < len(data):
            at = address + cursor
            width = next(w for w in (8, 4, 2, 1) if at % w == 0 and cursor + w <= len(data))
            writes.append(Write(at, width, int.from_bytes(data[cursor:cursor + width], 'little')))
            cursor += width
        self.write_many(writes, require_paused=require_paused)

    def apply_patch(self, patches: Iterable[Patch]) -> None:
        """Best-effort guarded patch while core is paused; not an atomic CAS.

        No writes occur if expected bytes disagree. A transport/readback failure
        never triggers an automatic retry or rollback of ambiguous writes.
        """
        items = list(patches)
        if not items:
            return
        for item in items:
            if not isinstance(item, Patch):
                raise TypeError('Expected Patch records')
            _write(Write(item.address, item.width, item.value))
            _unsigned(item.expected, item.width * 8, 'expected')
        spans = sorted((p.address, p.address + p.width) for p in items)
        if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
            raise ValueError('Overlapping patches are not admitted')
        with self._lock:
            self._write_access(True)
            values = self.read_many((p.address, p.width) for p in items)
            if values != [p.expected for p in items]:
                raise PinePatchConflict('Live RAM differs from the prepared patch')
            self.write_many(Write(p.address, p.width, p.value) for p in items)
            actual = self.read_many((p.address, p.width) for p in items)
            if actual != [p.value for p in items]:
                raise PineVerificationError('Written values failed readback; no automatic rollback attempted')

    def _state_request(self, opcode: int, slot: int) -> None:
        if type(slot) is not int or not 0 <= slot <= 9:
            raise ValueError('Save-state slot must be 0..9')
        with self._lock:
            self._write_access(True)
            self._exchange([_Command(bytes((opcode, slot)), 0)])

    def request_save_state(self, slot: int) -> None:
        """Queue save; ACK is NOT completion and can replace an existing slot."""
        self._state_request(9, slot)

    def request_load_state(self, slot: int) -> None:
        """Queue load; ACK is NOT completion, success, or restored VM identity."""
        self._state_request(10, slot)
