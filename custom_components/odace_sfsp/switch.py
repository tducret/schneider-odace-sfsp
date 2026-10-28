"""Direct BLE on/off control of paired Schneider Odace SFSP receivers."""

import asyncio
import logging

from bleak import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.switch import PLATFORM_SCHEMA, SwitchEntity
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .protocol import MANUFACTURER_ID, receiver_state

_LOGGER = logging.getLogger(__name__)
STATE_CHARACTERISTIC = "720a9081-9c7d-11e5-a7e3-0002a5d5c51b"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_ADDRESS): vol.All(
            cv.string, vol.Upper, vol.Match(r"^(?:[0-9A-F]{2}:){5}[0-9A-F]{2}$")
        ),
        vol.Optional(CONF_NAME, default="Odace light"): cv.string,
    }
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Add a YAML-configured receiver, already bonded in the host's BlueZ."""
    async_add_entities([OdaceSwitch(config[CONF_ADDRESS], config[CONF_NAME])])


class OdaceSwitch(SwitchEntity):
    """Connect only for commands; listen to broadcasts for physical changes."""

    _attr_should_poll = False

    def __init__(self, address: str, name: str) -> None:
        self._address = address
        self._attr_name = name
        self._attr_unique_id = f"odace_sfsp_{address}"
        self._attr_is_on = None
        self._lock = asyncio.Lock()

    async def async_added_to_hass(self) -> None:
        """Subscribe to the existing HA scanner without starting a new one."""
        self.async_on_remove(
            bluetooth.async_register_callback(
                self.hass,
                self._received,
                {"address": self._address, "connectable": True},
                bluetooth.BluetoothScanningMode.PASSIVE,
            )
        )
        if info := bluetooth.async_last_service_info(
            self.hass, self._address, connectable=True
        ):
            self._update_from_advertisement(info)

    def _update_from_advertisement(self, info) -> None:
        state = receiver_state(info.manufacturer_data.get(MANUFACTURER_ID, b""))
        if state is not None:
            self._attr_is_on = state

    @callback
    def _received(self, info, change) -> None:
        self._update_from_advertisement(info)
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        await self._send(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._send(False)

    async def _send(self, on: bool) -> None:
        async with self._lock:
            device = bluetooth.async_ble_device_from_address(
                self.hass, self._address, connectable=True
            )
            if device is None:
                raise HomeAssistantError(
                    f"Odace receiver {self._address} has not been discovered. "
                    "Check Bluetooth is enabled and the receiver is in range."
                )
            client = None
            try:
                client = await establish_connection(
                    BleakClientWithServiceCache, device, self.name
                )
                await client.write_gatt_char(
                    STATE_CHARACTERISTIC, bytes([int(on)]), response=True
                )
            except (BleakError, OSError, TimeoutError) as err:
                raise HomeAssistantError(
                    f"Could not control Odace receiver {self._address}: {err}"
                ) from err
            finally:
                if client is not None:
                    try:
                        await client.disconnect()
                    except (BleakError, OSError, TimeoutError):
                        _LOGGER.warning("Could not disconnect %s", self._address)
            # Immediate GATT readback was stale in testing. Use the acknowledged
            # command initially, then reconcile with subsequent advertisements.
            self._attr_is_on = on
            self.async_write_ha_state()
