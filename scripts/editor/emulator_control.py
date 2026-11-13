"""Optional Windows menu control, bound to the validated PINE endpoint owner.

Importing or constructing this module opens no DLL, window or connection.
The controller must validate the exact PINE/game profile before exposing this
capability. This is the wx 1.7.2521 menu command, not a PINE pause opcode.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import ntpath
import os
from pathlib import Path
import socket
import struct
import time
from typing import Protocol

from .pine import PineError, Status


PAUSE_MENU_ID = 135
MAIN_MENU_IDS = (132, 135, 136)
WM_COMMAND = 0x0111


class PauseControlError(RuntimeError):
    pass


class WindowAdapter(Protocol):
    def listener_pid(self, port: int) -> int | None: ...
    def process_image(self, pid: int) -> str: ...
    def main_window(self, pid: int) -> int | None: ...
    def post_pause_toggle(self, hwnd: int, pid: int) -> None: ...


@dataclass(frozen=True)
class _Target:
    pid: int
    image: str
    hwnd: int


def _listener_pid_from_table(data: bytes, port: int) -> int | None:
    if len(data) < 4:
        raise PauseControlError('A lista de conexões ficou incompleta.')
    count = struct.unpack_from('<I', data)[0]
    if count > (len(data) - 4) // 24:
        raise PauseControlError('A lista de conexões ficou incompleta.')
    owners = set()
    loopback = int.from_bytes(socket.inet_aton('127.0.0.1'), 'little')
    for index in range(count):
        state, address, local_port, _remote, _remote_port, pid = struct.unpack_from(
            '<6I', data, 4 + index * 24)
        if state == 2 and address == loopback and socket.ntohs(local_port & 0xFFFF) == port and pid:
            owners.add(pid)
    return owners.pop() if len(owners) == 1 else None


class WindowsAPI:
    """Small native adapter; instantiate only for an explicit capability check."""
    def __init__(self):
        if os.name != 'nt':
            raise PauseControlError('O controle de pausa está disponível somente no Windows.')
        import ctypes
        self.ctypes = ctypes
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.iphelper = ctypes.WinDLL('iphlpapi', use_last_error=True)
        uint, pointer, integer = ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int
        self.enum_callback = ctypes.WINFUNCTYPE(integer, pointer, ctypes.c_ssize_t)
        self.iphelper.GetExtendedTcpTable.argtypes = [pointer, ctypes.POINTER(uint), integer,
                                                     uint, integer, uint]
        self.iphelper.GetExtendedTcpTable.restype = uint
        self.kernel.OpenProcess.argtypes = [uint, integer, uint]
        self.kernel.OpenProcess.restype = pointer
        self.kernel.QueryFullProcessImageNameW.argtypes = [pointer, uint, ctypes.c_wchar_p,
                                                          ctypes.POINTER(uint)]
        self.kernel.QueryFullProcessImageNameW.restype = integer
        self.kernel.CloseHandle.argtypes = [pointer]
        self.kernel.CloseHandle.restype = integer
        self.user.EnumWindows.argtypes = [self.enum_callback, ctypes.c_ssize_t]
        self.user.EnumWindows.restype = integer
        self.user.GetWindowThreadProcessId.argtypes = [pointer, ctypes.POINTER(uint)]
        self.user.GetWindowThreadProcessId.restype = uint
        self.user.IsWindow.argtypes = [pointer]
        self.user.IsWindow.restype = integer
        self.user.GetWindow.argtypes = [pointer, uint]
        self.user.GetWindow.restype = pointer
        self.user.GetMenu.argtypes = [pointer]
        self.user.GetMenu.restype = pointer
        self.user.GetMenuState.argtypes = [pointer, uint, uint]
        self.user.GetMenuState.restype = uint
        self.user.PostMessageW.argtypes = [pointer, uint, ctypes.c_size_t, ctypes.c_ssize_t]
        self.user.PostMessageW.restype = integer

    def listener_pid(self, port: int) -> int | None:
        ctypes = self.ctypes
        size = ctypes.c_uint32()
        # AF_INET=2, TCP_TABLE_OWNER_PID_LISTENER=3. Do not accept wildcard,
        # remote, IPv6 or a different port as ownership of this endpoint.
        result = self.iphelper.GetExtendedTcpTable(None, ctypes.byref(size), 0, 2, 3, 0)
        if result not in (0, 122) or not 4 <= size.value <= 1048576:
            raise PauseControlError('Não foi possível identificar o processo da conexão PINE.')
        buffer = ctypes.create_string_buffer(size.value)
        result = self.iphelper.GetExtendedTcpTable(buffer, ctypes.byref(size), 0, 2, 3, 0)
        if result:
            raise PauseControlError('A lista de conexões mudou. Confira o PCSX2 antes de tentar novamente.')
        return _listener_pid_from_table(buffer.raw[:size.value], port)

    def process_image(self, pid: int) -> str:
        ctypes = self.ctypes
        handle = self.kernel.OpenProcess(0x1000, 0, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            raise PauseControlError('Não foi possível verificar o executável do emulador.')
        try:
            size = ctypes.c_uint32(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not self.kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                raise PauseControlError('Não foi possível verificar o executável do emulador.')
            return buffer.value
        finally:
            self.kernel.CloseHandle(handle)

    def _matching_window(self, hwnd: int, pid: int) -> bool:
        ctypes = self.ctypes
        owner = ctypes.c_uint32()
        if not self.user.IsWindow(hwnd) or not self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner)):
            return False
        if owner.value != pid or self.user.GetWindow(hwnd, 4):
            return False  # GW_OWNER: exclude owned dialogs.
        menu = self.user.GetMenu(hwnd)
        if not menu:
            return False
        # wx can hide its main frame while the separate GS window is active.
        # Menu presence identifies the frame; disabled state is transient and
        # must not invalidate readback after a successfully posted command.
        return all(self.user.GetMenuState(menu, command, 0) != 0xFFFFFFFF
                   for command in MAIN_MENU_IDS)  # MF_BYCOMMAND

    def main_window(self, pid: int) -> int | None:
        windows = []
        @self.enum_callback
        def collect(hwnd, _parameter):
            if self._matching_window(hwnd, pid):
                windows.append(int(hwnd))
            return 1
        if not self.user.EnumWindows(collect, 0):
            raise PauseControlError('Não foi possível verificar a janela principal do PCSX2.')
        if not windows:
            raise PauseControlError('A janela principal do PCSX2 não foi encontrada com os menus compatíveis desta versão.')
        if len(windows) != 1:
            raise PauseControlError('Há mais de uma janela principal compatível no processo PCSX2. Nenhum comando foi enviado.')
        return windows[0]

    def post_pause_toggle(self, hwnd: int, pid: int) -> None:
        if not self._matching_window(hwnd, pid):
            raise PauseControlError('A janela do PCSX2 mudou. Nenhum comando foi enviado.')
        state = self.user.GetMenuState(self.user.GetMenu(hwnd), PAUSE_MENU_ID, 0)
        if state == 0xFFFFFFFF or state & 3:  # MF_DISABLED / MF_GRAYED
            raise PauseControlError('A pausa do PCSX2 está temporariamente indisponível. Aguarde a operação atual terminar e confira o emulador.')
        if not self.user.PostMessageW(hwnd, WM_COMMAND, PAUSE_MENU_ID, 0):
            raise PauseControlError('O Windows não aceitou o comando de pausa do PCSX2.')


class WindowPauseControl:
    def __init__(self, client, port: int, *, adapter: WindowAdapter | None = None,
                 timeout: float = 2.0, clock=time.monotonic, sleeper=time.sleep):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('A porta precisa estar entre 1 e 65535.')
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or not 0 < timeout <= 10):
            raise ValueError('O tempo de confirmação precisa estar entre 0 e 10 segundos.')
        self.client, self.port, self.adapter = client, port, adapter
        self.timeout, self.clock, self.sleeper = float(timeout), clock, sleeper

    def _target(self) -> _Target:
        if getattr(self.client, 'host', None) != '127.0.0.1' or getattr(self.client, 'port', None) != self.port:
            raise PauseControlError('O controle de pausa exige a mesma conexão PINE local do editor.')
        if self.adapter is None:
            self.adapter = WindowsAPI()
        pid = self.adapter.listener_pid(self.port)
        if type(pid) is not int or pid <= 0:
            raise PauseControlError('Não há um único PCSX2 identificado na porta PINE configurada.')
        image = self.adapter.process_image(pid)
        name = ntpath.basename(image).lower()
        if not ntpath.isabs(image) or not name.startswith('pcsx2') or not name.endswith('.exe'):
            raise PauseControlError('O processo da conexão PINE não é um executável PCSX2 compatível.')
        hwnd = self.adapter.main_window(pid)
        if type(hwnd) is not int or hwnd <= 0:
            raise PauseControlError('Não foi encontrada uma única janela PCSX2 com o menu de pausa compatível.')
        return _Target(pid, ntpath.normcase(image), hwnd)

    def supports(self) -> bool:
        try:
            self._target()
        except (PauseControlError, OSError):
            return False
        return True

    def emulator_root(self) -> Path:
        """Return the freshly revalidated endpoint owner's executable folder."""
        target = self._target()
        self._confirm_target(target)
        return Path(ntpath.dirname(target.image))

    def _confirm_target(self, expected: _Target):
        if self._target() != expected:
            raise PauseControlError('A sessão do PCSX2 mudou. Nenhum comando adicional será enviado.')

    def _status(self) -> Status:
        try:
            state = self.client.status()
        except PineError as exc:
            raise PauseControlError('Não foi possível confirmar a pausa pela conexão PINE. Confira o PCSX2.') from exc
        if state not in (Status.RUNNING, Status.PAUSED):
            raise PauseControlError('Carregue o jogo antes de usar o controle de pausa.')
        return state

    def set_paused(self, paused: bool) -> dict[str, bool]:
        """Set a target state with at most one toggle; never retry uncertainty."""
        if type(paused) is not bool:
            raise ValueError('Informe se o emulador deve ficar pausado.')
        target = self._target()
        desired = Status.PAUSED if paused else Status.RUNNING
        before = self._status()
        self._confirm_target(target)
        if before is desired:
            return {'core_paused': paused, 'changed': False}
        self.adapter.post_pause_toggle(target.hwnd, target.pid)
        deadline = self.clock() + self.timeout
        while True:
            state = self._status()
            self._confirm_target(target)
            if state is desired:
                return {'core_paused': paused, 'changed': True}
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise PauseControlError('O PCSX2 não confirmou a mudança de pausa. Confira seu estado; o comando não será repetido.')
            self.sleeper(min(0.05, remaining))
