"""Direct BLE on/off control of paired Schneider Odace SFSP receivers."""

import asyncio
import logging

from bleak import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.switch import PLATFORM_SCHEMA, SwitchEntity
from homeassistant.const import CONF_ADDRESS, CONF_NAME, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .protocol import MANUFACTURER_ID, receiver_state

_LOGGER = logging.getLogger(__name__)
STATE_CHARACTERISTIC = "720a9081-9c7d-11e5-a7e3-0002a5d5c51b"
CONF_CONNECTION_TIMEOUT = "connection_timeout"
DEFAULT_CONNECTION_TIMEOUT = 30

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_ADDRESS): vol.All(
            cv.string, vol.Upper, vol.Match(r"^(?:[0-9A-F]{2}:){5}[0-9A-F]{2}$")
        ),
        vol.Optional(CONF_NAME, default="Odace light"): cv.string,
        vol.Optional(
            CONF_CONNECTION_TIMEOUT, default=DEFAULT_CONNECTION_TIMEOUT
        ): vol.All(vol.Coerce(float), vol.Range(min=0, max=300)),
    }
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Add a YAML-configured receiver, already bonded in the host's BlueZ."""
    async_add_entities(
        [
            OdaceSwitch(
                config[CONF_ADDRESS],
                config[CONF_NAME],
                config[CONF_CONNECTION_TIMEOUT],
            )
        ]
    )


class OdaceSwitch(SwitchEntity):
    """Reuse command connections briefly; listen to broadcasts for changes."""

    _attr_should_poll = False

    def __init__(
        self,
        address: str,
        name: str,
        connection_timeout: float = DEFAULT_CONNECTION_TIMEOUT,
    ) -> None:
        self._address = address
        self._attr_name = name
        self._attr_unique_id = f"odace_sfsp_{address}"
        self._attr_is_on = None
        self._lock = asyncio.Lock()
        self._client = None
        self._connection_timeout = connection_timeout
        self._disconnect_timer = None
        self._stopping = False

    async def async_added_to_hass(self) -> None:
        """Subscribe to the existing HA scanner without starting a new one."""
        self.async_on_remove(
            self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STOP, self._async_shutdown
            )
        )
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

    async def _async_shutdown(self, event=None) -> None:
        """Release our Bluetooth connection on shutdown or entity removal."""
        self._stopping = True
        self._cancel_disconnect_timer()
        async with self._lock:
            self._cancel_disconnect_timer()
            await self._disconnect()

    async def async_will_remove_from_hass(self) -> None:
        await self._async_shutdown()

    def _cancel_disconnect_timer(self) -> None:
        if self._disconnect_timer is not None:
            self._disconnect_timer.cancel()
            self._disconnect_timer = None

    async def _disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.disconnect()
            except (BleakError, OSError, TimeoutError):
                _LOGGER.warning("Could not disconnect %s", self._address)

    @callback
    def _schedule_disconnect(self) -> None:
        self._cancel_disconnect_timer()
        self._disconnect_timer = asyncio.get_running_loop().call_later(
            self._connection_timeout, self._disconnect_when_idle
        )

    @callback
    def _disconnect_when_idle(self) -> None:
        timer = self._disconnect_timer
        self.hass.async_create_task(self._async_disconnect_when_idle(timer))

    async def _async_disconnect_when_idle(self, timer) -> None:
        async with self._lock:
            # A command may have refreshed the timeout while we waited for it.
            if timer is not self._disconnect_timer:
                return
            self._disconnect_timer = None
            await self._disconnect()

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

    async def _connect(self) -> None:
        if self._client is not None and self._client.is_connected:
            return
        await self._disconnect()
        device = bluetooth.async_ble_device_from_address(
            self.hass, self._address, connectable=True
        )
        if device is None:
            raise HomeAssistantError(
                f"Odace receiver {self._address} has not been discovered. "
                "Check Bluetooth is enabled and the receiver is in range."
            )
        self._client = await establish_connection(
            BleakClientWithServiceCache, device, self.name
        )

    async def _send(self, on: bool) -> None:
        async with self._lock:
            if self._stopping:
                raise HomeAssistantError("Odace receiver is shutting down")
            self._cancel_disconnect_timer()
            reused_connection = self._client is not None and self._client.is_connected
            try:
                for attempt in range(2 if reused_connection else 1):
                    try:
                        await self._connect()
                        await self._client.write_gatt_char(
                            STATE_CHARACTERISTIC, bytes([int(on)]), response=True
                        )
                        break
                    except (BleakError, OSError, TimeoutError):
                        await self._disconnect()
                        if not reused_connection or attempt:
                            raise
                        # A cached connection can die before BlueZ reports it.
                        # Retrying an explicit on/off value is safe, not a toggle.
                        _LOGGER.debug(
                            "Reconnecting to %s after write failure", self._address
                        )
            except (BleakError, OSError, TimeoutError) as err:
                raise HomeAssistantError(
                    f"Could not control Odace receiver {self._address}: {err}"
                ) from err
            finally:
                # Also release a connection if the command task was cancelled.
                if self._client is not None:
                    self._schedule_disconnect()
            # Immediate GATT readback was stale in testing. Use the acknowledged
            # command initially, then reconcile with subsequent advertisements.
            self._attr_is_on = on
            self.async_write_ha_state()
