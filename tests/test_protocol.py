"""Protocol checks; runnable without installing Home Assistant."""

import importlib.util
from pathlib import Path
import sys
import unittest

PATH = Path(__file__).resolve().parents[1] / "custom_components/odace_sfsp/protocol.py"
spec = importlib.util.spec_from_file_location("odace_protocol", PATH)
protocol = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = protocol
spec.loader.exec_module(protocol)


class ProtocolTests(unittest.TestCase):
    def test_synthetic_switch(self):
        # Synthetic UID and trailer; not a captured or authenticated command.
        raw = bytes.fromhex("b6028e4401010056341201020000040000000000000000000000")
        press = protocol.decode(raw[2:])
        self.assertEqual((press.uid, press.action), ("123456", "toggle"))

    def test_leading_zero_uid(self):
        raw = bytes.fromhex("b6028e4401010042590001020000040000000000923995c4cc19")
        self.assertEqual(protocol.decode(raw[2:]).uid, "005942")

    def test_all_actions(self):
        data = bytearray.fromhex("8e440101005634120102")
        for code, action in enumerate(protocol.ACTIONS):
            data[9] = code
            self.assertEqual(protocol.decode(data).action, action)

    def test_invalid_data(self):
        for data in (b"", b"\x8e\x44", bytes(10), bytes.fromhex("8e4401010056341201ff")):
            self.assertIsNone(protocol.decode(data))

    def test_receiver_state(self):
        for state in (0, 1):
            data = bytearray.fromhex("9244010020563412000000ffffffff00ffffffff00001201")
            data[9] = state
            self.assertIs(protocol.receiver_state(data), bool(state))

    def test_invalid_receiver_state(self):
        for data in (b"", bytes(10), bytes.fromhex("924401002056341200ff")):
            self.assertIsNone(protocol.receiver_state(data))


if __name__ == "__main__":
    unittest.main()
