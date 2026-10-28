"""Decode Odace advertisements without external dependencies."""

from dataclasses import dataclass

MANUFACTURER_ID = 0x02B6
ACTIONS = (
    "off", "on", "toggle", "dim_up", "dim_down", "up", "down", "stop",
    "scene_user", "scene_in", "scene_out",
)


@dataclass(frozen=True)
class ButtonPress:
    """A decoded switch command."""

    uid: str
    action: str


def decode(data: bytes) -> ButtonPress | None:
    """Decode data AFTER the two-byte BLE manufacturer ID (HA/Bleak format)."""
    if len(data) < 10 or not data.startswith(b"\x8e\x44"):
        return None
    code = data[9]
    if code >= len(ACTIONS):
        return None
    return ButtonPress(data[5:8][::-1].hex(), ACTIONS[code])


def receiver_state(data: bytes) -> bool | None:
    """Read receiver on/off from observed 9244 advertisements, without company ID."""
    if len(data) < 10 or not data.startswith(b"\x92\x44"):
        return None
    if data[9] not in (0, 1):
        return None
    return bool(data[9])
