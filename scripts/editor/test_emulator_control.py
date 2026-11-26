"""Fake-only menu-control tests: no native API, window or socket is opened."""
from pathlib import Path
import ctypes
import socket
import struct
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editor import emulator_control as module
from editor.emulator_control import WindowPauseControl, PauseControlError
from editor.pine import PineTransportError, Status


class FakeAdapter:
    def __init__(self):
        self.pid = 123
        self.image = r'C:\Test\pcsx2x64.exe'
        self.hwnd = 77
        self.commands = []
        self.owners = []
    def listener_pid(self, port):
        assert port == 28011
        return self.owners.pop(0) if self.owners else self.pid
    def process_image(self, pid): return self.image
    def main_window(self, pid): return self.hwnd
    def post_pause_toggle(self, hwnd, pid): self.commands.append((hwnd, pid))


class FakeClock:
    def __init__(self): self.now = 0
    def __call__(self): return self.now
    def sleep(self, seconds): self.now += seconds


class FakeClient:
    def __init__(self, states):
        self.states, self.calls = list(states), 0
        self.host, self.port = '127.0.0.1', 28011
    def status(self):
        self.calls += 1
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        if isinstance(state, Exception): raise state
        return state


class FakeUser32:
    def __init__(self, windows=None):
        self.windows = windows if windows is not None else {77: self.window()}
        self.commands = []
        self.disable_after_post = False
        self.IsWindowVisible = Mock(side_effect=AssertionError('Visibility must not identify the wx frame'))
    @staticmethod
    def window(*, pid=123, owner=0, menu=300, pause_state=0):
        return {'pid': pid, 'owner': owner, 'menu': menu,
                'states': {132: 0, 135: pause_state, 136: 0}}
    def IsWindow(self, hwnd): return int(hwnd in self.windows)
    def GetWindowThreadProcessId(self, hwnd, owner):
        owner._obj.value = self.windows[hwnd]['pid']
        return 1
    def GetWindow(self, hwnd, flag):
        assert flag == 4
        return self.windows[hwnd]['owner']
    def GetMenu(self, hwnd): return self.windows[hwnd]['menu']
    def GetMenuState(self, menu, command, flag):
        assert flag == 0
        window = next((window for window in self.windows.values() if window['menu'] == menu), None)
        return window['states'].get(command, 0xFFFFFFFF) if window else 0xFFFFFFFF
    def EnumWindows(self, callback, parameter):
        for hwnd in self.windows:
            if not callback(hwnd, parameter): return 0
        return 1
    def PostMessageW(self, hwnd, message, command, parameter):
        self.commands.append((hwnd, message, command, parameter))
        if self.disable_after_post:
            self.windows[hwnd]['states'][135] = 2
        return 1


def fake_windows_adapter(user=None):
    # Skip __init__: no WinDLL, real EnumWindows or other native API is called.
    api = module.WindowsAPI.__new__(module.WindowsAPI)
    api.ctypes = ctypes
    api.user = user if user is not None else FakeUser32()
    api.enum_callback = lambda callback: callback
    api.listener_pid = lambda port: 123
    api.process_image = lambda pid: r'C:\Test\pcsx2x64.exe'
    return api


def control(states, adapter=None):
    fake_api, clock = adapter or FakeAdapter(), FakeClock()
    client = FakeClient(states)
    return WindowPauseControl(client, 28011, adapter=fake_api, timeout=.2,
                              clock=clock, sleeper=clock.sleep), fake_api, client


class WindowPauseTests(unittest.TestCase):
    def test_construction_does_not_load_native_apis(self):
        with patch.object(module, 'WindowsAPI') as native:
            WindowPauseControl(Mock(), 28011)
        native.assert_not_called()

    def test_supports_checks_target_without_sending_a_command(self):
        pause, api, client = control([Status.RUNNING])
        self.assertTrue(pause.supports())
        self.assertEqual(api.commands, [])
        self.assertEqual(client.calls, 0)

    def test_emulator_folder_metadata_is_revalidated_without_menu_command(self):
        pause, api, _client = control([Status.PAUSED])
        self.assertEqual(pause.emulator_root(), Path(r'c:\test'))
        self.assertEqual(api.commands, [])
        api.owners = [123, 456]
        with self.assertRaisesRegex(PauseControlError, 'session changed'):
            pause.emulator_root()
        self.assertEqual(api.commands, [])

    def test_already_matching_state_is_idempotent(self):
        for requested, state in [(True, Status.PAUSED), (False, Status.RUNNING)]:
            with self.subTest(requested=requested):
                pause, api, _client = control([state])
                self.assertEqual(pause.set_paused(requested),
                                 {'core_paused': requested, 'changed': False})
                self.assertEqual(api.commands, [])

    def test_pause_and_resume_each_send_one_toggle_then_verify_pine(self):
        for requested, old, new in [(True, Status.RUNNING, Status.PAUSED),
                                    (False, Status.PAUSED, Status.RUNNING)]:
            with self.subTest(requested=requested):
                pause, api, client = control([old, old, new])
                self.assertEqual(pause.set_paused(requested),
                                 {'core_paused': requested, 'changed': True})
                self.assertEqual(api.commands, [(77, 123)])
                self.assertEqual(client.calls, 3)

    def test_timeout_does_not_retry_toggle(self):
        pause, api, _client = control([Status.RUNNING])
        with self.assertRaisesRegex(PauseControlError, 'will not be repeated'):
            pause.set_paused(True)
        self.assertEqual(api.commands, [(77, 123)])

    def test_changed_endpoint_owner_before_command_sends_nothing(self):
        api = FakeAdapter()
        api.owners = [123, 456]
        pause, api, _client = control([Status.RUNNING], api)
        with self.assertRaisesRegex(PauseControlError, 'session changed'):
            pause.set_paused(True)
        self.assertEqual(api.commands, [])

    def test_client_endpoint_must_match_discovered_listener_before_native_access(self):
        for field, value in [('host', '127.0.0.2'), ('port', 28012), ('host', None)]:
            with self.subTest(field=field, value=value):
                pause, api, client = control([Status.RUNNING])
                setattr(client, field, value)
                with patch.object(api, 'listener_pid', wraps=api.listener_pid) as discover:
                    self.assertFalse(pause.supports())
                    with self.assertRaisesRegex(PauseControlError, 'own local PINE connection'):
                        pause.set_paused(True)
                    discover.assert_not_called()
                self.assertEqual(api.commands, [])

    def test_changed_endpoint_owner_after_command_does_not_retry(self):
        api = FakeAdapter()
        api.owners = [123, 123, 456]
        pause, api, _client = control([Status.RUNNING, Status.PAUSED], api)
        with self.assertRaisesRegex(PauseControlError, 'session changed'):
            pause.set_paused(True)
        self.assertEqual(api.commands, [(77, 123)])

    def test_wrong_executable_or_ambiguous_window_is_not_supported(self):
        for field, value in [('image', r'C:\Test\other.exe'), ('pid', None), ('hwnd', None)]:
            with self.subTest(field=field):
                api = FakeAdapter()
                setattr(api, field, value)
                pause, api, _client = control([Status.RUNNING], api)
                self.assertFalse(pause.supports())
                with self.assertRaises(PauseControlError): pause.set_paused(True)
                self.assertEqual(api.commands, [])

    def test_readback_disconnect_or_shutdown_never_retries(self):
        error = PineTransportError('fake disconnect', may_have_executed=False)
        for state in (error, Status.SHUTDOWN):
            with self.subTest(state=state):
                pause, api, _client = control([Status.RUNNING, state])
                with self.assertRaises(PauseControlError): pause.set_paused(True)
                self.assertEqual(api.commands, [(77, 123)])

    def test_input_validation_precedes_target_discovery(self):
        pause, api, _client = control([Status.RUNNING])
        for value in (None, 1, 'true'):
            with self.assertRaises(ValueError): pause.set_paused(value)
        self.assertEqual(api.commands, [])
        with patch.object(module, 'WindowsAPI') as native:
            for port in (0, 65536, True):
                with self.assertRaises(ValueError): WindowPauseControl(Mock(), port)
            native.assert_not_called()


class TcpOwnershipTests(unittest.TestCase):
    @staticmethod
    def row(address='127.0.0.1', port=28011, pid=123, state=2):
        return struct.pack('<6I', state, int.from_bytes(socket.inet_aton(address), 'little'),
                           socket.htons(port), 0, 0, pid)

    def test_only_exact_loopback_listener_and_port_can_own_target(self):
        rows = [self.row('0.0.0.0', pid=20), self.row('127.0.0.1', port=28012, pid=30),
                self.row('127.0.0.1', state=5, pid=40), self.row()]
        self.assertEqual(module._listener_pid_from_table(struct.pack('<I', len(rows)) + b''.join(rows), 28011), 123)

    def test_multiple_owners_or_truncated_tables_fail_closed(self):
        table = struct.pack('<I', 2) + self.row(pid=123) + self.row(pid=456)
        self.assertIsNone(module._listener_pid_from_table(table, 28011))
        for data in (b'', struct.pack('<I', 2) + self.row()):
            with self.assertRaises(PauseControlError): module._listener_pid_from_table(data, 28011)


class NativeWrapperFakeTests(unittest.TestCase):
    def test_hidden_unowned_main_frame_is_identified_by_pid_and_menus(self):
        api = fake_windows_adapter()
        self.assertEqual(api.main_window(123), 77)
        api.user.IsWindowVisible.assert_not_called()

    def test_disabled_pause_item_keeps_frame_identity_but_blocks_post(self):
        user = FakeUser32({77: FakeUser32.window(pause_state=2)})
        api = fake_windows_adapter(user)
        self.assertEqual(api.main_window(123), 77)
        with self.assertRaisesRegex(PauseControlError, 'temporarily unavailable'):
            api.post_pause_toggle(77, 123)
        self.assertEqual(user.commands, [])

    def test_readback_accepts_same_frame_with_pause_menu_transiently_disabled(self):
        api = fake_windows_adapter()
        api.user.disable_after_post = True
        pause, _api, _client = control([Status.RUNNING, Status.PAUSED], api)
        self.assertEqual(pause.set_paused(True), {'core_paused': True, 'changed': True})
        self.assertEqual(api.user.commands, [(77, module.WM_COMMAND, 135, 0)])

    def test_none_and_multiple_matching_frames_have_distinct_errors(self):
        api = fake_windows_adapter(FakeUser32({}))
        with self.assertRaisesRegex(PauseControlError, 'was not found'):
            api.main_window(123)
        user = FakeUser32({77: FakeUser32.window(), 88: FakeUser32.window(menu=400)})
        api = fake_windows_adapter(user)
        with self.assertRaisesRegex(PauseControlError, 'more than one'):
            api.main_window(123)
        self.assertEqual(user.commands, [])

    def test_owned_wrong_pid_or_missing_marker_menu_is_not_a_main_frame(self):
        windows = [FakeUser32.window(owner=5), FakeUser32.window(pid=456)]
        for missing in module.MAIN_MENU_IDS:
            window = FakeUser32.window()
            del window['states'][missing]
            windows.append(window)
        for window in windows:
            with self.subTest(window=window):
                api = fake_windows_adapter(FakeUser32({77: window}))
                with self.assertRaisesRegex(PauseControlError, 'was not found'):
                    api.main_window(123)

    def test_target_identity_is_checked_again_immediately_before_post(self):
        api = fake_windows_adapter()
        self.assertEqual(api.main_window(123), 77)
        api.user.windows[77]['pid'] = 456
        with self.assertRaisesRegex(PauseControlError, 'window changed'):
            api.post_pause_toggle(77, 123)
        self.assertEqual(api.user.commands, [])


if __name__ == '__main__': unittest.main()
