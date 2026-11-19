"""Loaded Crash event identity is checked against two independent path fields."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editor import native_identity as identity
from editor.catalog import encode_identifier
from editor.controller import EditorController
from editor.pine import Status


class Memory:
    def __init__(self, event="1G0007EUC3V1", path=b"tracks/EU/C3_V1/Gamedata.bgd"):
        self.fields = {
            identity.EVENT_IDENTIFIER: encode_identifier(event).to_bytes(8, "little"),
            identity.STAGE_RESOURCE_PATH: path.ljust(identity.PATH_WINDOW, b"\0"),
            identity.LOADED_RESOURCE_PATH: path.ljust(identity.PATH_WINDOW, b"\0"),
        }

    def read_bytes(self, address, size):
        return self.fields[address][:size]


class NativeIdentityTests(unittest.TestCase):
    def test_grand_slam(self):
        self.assertEqual(identity.read_identity(Memory()), {
            "event_key": "1G0007EUC3V1",
            "track": "EU/C3_V1",
            "resource_path": "TRACKS/EU/C3_V1/GAMEDATA.BGD",
        })

    def test_two_distinct_events_on_the_same_track(self):
        for event in ("1G030IASC3V2", "1G040IASC3V2"):
            with self.subTest(event=event):
                result = identity.read_identity(Memory(event, b"tracks/AS/C3_V2/Gamedata.bgd"))
                self.assertEqual((result["event_key"], result["track"]), (event, "AS/C3_V2"))

    def test_invalid_or_inconsistent_fields_do_not_identify_an_event(self):
        bad_fields = (
            (identity.EVENT_IDENTIFIER, bytes(8)),
            (identity.EVENT_IDENTIFIER, bytes(7)),
            (identity.EVENT_IDENTIFIER, b"\xff" * 8),
            (identity.EVENT_IDENTIFIER, encode_identifier("1R0007EUC3V1").to_bytes(8, "little")),
            (identity.EVENT_IDENTIFIER, encode_identifier("1G0007USC3V1").to_bytes(8, "little")),
            (identity.STAGE_RESOURCE_PATH, b"tracks/US/C3_V1/Gamedata.bgd".ljust(48, b"\0")),
            (identity.LOADED_RESOURCE_PATH, b"tracks/EU/C3_V1/Gamedata.bgd".ljust(48, b" ")),
            (identity.LOADED_RESOURCE_PATH, b"tracks/EU/C3_V1/Gamedata.bgd\0"),
        )
        for address, data in bad_fields:
            with self.subTest(address=hex(address), data=data):
                memory = Memory()
                memory.fields[address] = data
                self.assertIsNone(identity.read_identity(memory))

    def test_foreign_resource_in_both_fields_is_rejected(self):
        self.assertIsNone(identity.read_identity(Memory(path=b"tracks/EU/C3_V1/preview.bgd")))

    def test_refresh_reports_current_identity_and_keeps_unknown_scenes_editable(self):
        client = Mock()
        client.identity.return_value = {
            "version": "PCSX2 1.7.2521", "game_id": "SLUS-21050", "game_crc": "BEBF8793",
        }
        client.status.return_value = Status.PAUSED
        controller = EditorController(client=client)
        snapshot = SimpleNamespace(
            memory=Memory(), vehicles={}, inspection={"counts": {"free_objects": 30}},
            public=lambda: {"core_paused": True, "vehicles": []},
        )
        with patch.object(controller, "_snapshot", return_value=snapshot), \
                patch("editor.controller.routes.build_network", return_value={"paths": []}):
            self.assertEqual(controller.refresh()["native_identity"]["event_key"], "1G0007EUC3V1")
            snapshot.memory.fields[identity.EVENT_IDENTIFIER] = bytes(8)
            result = controller.refresh()
            self.assertIsNone(result["native_identity"])
            self.assertTrue(result["core_paused"])
            self.assertEqual(result["capacity"]["free_objects"], 30)
            client.status.side_effect = (Status.PAUSED, Status.RUNNING)
            result = controller.refresh()
            self.assertFalse(result["core_paused"])
            self.assertNotIn("native_identity", result)


if __name__ == "__main__":
    unittest.main()
