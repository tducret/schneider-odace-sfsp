"""Expose Odace SFSP broadcasts on Home Assistant's event bus."""

from time import monotonic

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .protocol import MANUFACTURER_ID, decode

DOMAIN = "odace_sfsp"
CONFIG_SCHEMA = vol.Schema(
    {
        vol.Optional(DOMAIN): vol.Schema(
            {
                vol.Required("uid"): vol.All(
                    cv.string, vol.Lower, vol.Match(r"^[0-9a-f]{6}$")
                ),
                vol.Optional("debounce", default=0.3): vol.All(
                    vol.Coerce(float), vol.Range(min=0, max=5)
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Subscribe to HA's shared scanner; do not open another BLE scanner."""
    if DOMAIN not in config:
        return True
    settings = config[DOMAIN]
    last_seen: dict[str, float] = {}

    @callback
    def received(
        info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        press = decode(info.manufacturer_data.get(MANUFACTURER_ID, b""))
        if press is None or press.uid != settings["uid"]:
            return
        now = monotonic()
        previous = last_seen.get(press.action)
        last_seen[press.action] = now
        if previous is not None and now - previous < settings["debounce"]:
            return
        hass.bus.async_fire(
            DOMAIN + "_button",
            {
                "uid": press.uid,
                "action": press.action,
                "address": info.address,
                "rssi": info.rssi,
            },
        )

    unsubscribe = bluetooth.async_register_callback(
        hass,
        received,
        {"manufacturer_id": MANUFACTURER_ID, "connectable": False},
        bluetooth.BluetoothScanningMode.PASSIVE,
    )
    hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_STOP, callback(lambda event: unsubscribe())
    )
    return True
