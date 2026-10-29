"""Connection lifecycle checks using HA/Bleak stubs; no radio required."""

import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, call, patch


ROOT = Path(__file__).resolve().parents[1] / "custom_components/odace_sfsp"


class HomeAssistantError(Exception):
    pass


class BleakError(Exception):
    pass


class SwitchEntity:
    @property
    def name(self):
        return self._attr_name


def load_switch():
    """Stub only external dependencies while importing the real platform."""
    names = (
        "bleak", "bleak_retry_connector", "voluptuous", "homeassistant",
        "homeassistant.components", "homeassistant.components.bluetooth",
        "homeassistant.components.switch", "homeassistant.const",
        "homeassistant.core", "homeassistant.exceptions", "homeassistant.helpers",
        "homeassistant.helpers.config_validation", "odace_test",
    )
    modules = {name: ModuleType(name) for name in names}
    modules["odace_test"].__path__ = [str(ROOT)]
    modules["bleak"].BleakError = BleakError
    modules["bleak_retry_connector"].BleakClientWithServiceCache = object
    modules["bleak_retry_connector"].establish_connection = AsyncMock()
    for name in ("Required", "Optional", "All", "Coerce", "Range", "Match"):
        setattr(modules["voluptuous"], name, MagicMock())
    modules["voluptuous"].Upper = str.upper
    modules["homeassistant.components"].bluetooth = modules[
        "homeassistant.components.bluetooth"
    ]
    modules["homeassistant.components.switch"].SwitchEntity = SwitchEntity
    modules["homeassistant.components.switch"].PLATFORM_SCHEMA = MagicMock()
    for name, value in (
        ("CONF_ADDRESS", "address"), ("CONF_NAME", "name"),
        ("EVENT_HOMEASSISTANT_STOP", "homeassistant_stop"),
    ):
        setattr(modules["homeassistant.const"], name, value)
    modules["homeassistant.core"].callback = lambda function: function
    modules["homeassistant.exceptions"].HomeAssistantError = HomeAssistantError
    modules["homeassistant.helpers.config_validation"].string = str
    modules["homeassistant.helpers"].config_validation = modules[
        "homeassistant.helpers.config_validation"
    ]
    spec = importlib.util.spec_from_file_location("odace_test.switch", ROOT / "switch.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


switch = load_switch()


class SwitchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.entity = switch.OdaceSwitch("AA:BB:CC:DD:EE:FF", "Test light")
        self.tasks = []

        def create_task(coro):
            task = asyncio.create_task(coro)
            self.tasks.append(task)
            return task

        self.entity.hass = SimpleNamespace(async_create_task=create_task)
        self.entity.async_write_ha_state = MagicMock()
        self.client = self.make_client()
        self.connect = AsyncMock(return_value=self.client)
        self.device = object()
        self.lookup = MagicMock(return_value=self.device)
        self.patches = [
            patch.object(switch, "establish_connection", self.connect),
            patch.object(
                switch.bluetooth, "async_ble_device_from_address", self.lookup,
                create=True,
            ),
        ]
        for replacement in self.patches:
            replacement.start()

    async def asyncTearDown(self):
        await self.entity.async_will_remove_from_hass()
        if self.tasks:
            await asyncio.gather(*self.tasks)
        for replacement in reversed(self.patches):
            replacement.stop()

    def make_client(self):
        return SimpleNamespace(
            is_connected=True,
            write_gatt_char=AsyncMock(),
            disconnect=AsyncMock(),
        )

    async def test_reuses_connection_and_updates_before_disconnect(self):
        await self.entity.async_turn_on()
        first_timer = self.entity._disconnect_timer
        self.assertIs(self.entity._attr_is_on, True)
        self.entity.async_write_ha_state.assert_called_once()
        self.client.disconnect.assert_not_awaited()
        await self.entity.async_turn_off()
        self.connect.assert_awaited_once()
        self.lookup.assert_called_once()
        self.assertTrue(first_timer.cancelled())
        self.assertIs(self.entity._attr_is_on, False)
        self.assertEqual(self.client.write_gatt_char.await_args_list, [
            call(switch.STATE_CHARACTERISTIC, b"\x01", response=True),
            call(switch.STATE_CHARACTERISTIC, b"\x00", response=True),
        ])

    async def test_idle_disconnect_and_reconnect(self):
        await self.entity.async_turn_on()
        await self.entity._async_disconnect_when_idle(self.entity._disconnect_timer)
        self.client.disconnect.assert_awaited_once()
        self.assertIsNone(self.entity._client)
        await self.entity.async_turn_off()
        self.assertEqual(self.connect.await_count, 2)

    async def test_expired_timer_cannot_disconnect_refreshed_connection(self):
        await self.entity.async_turn_on()
        old_timer = self.entity._disconnect_timer
        await self.entity.async_turn_off()
        await self.entity._async_disconnect_when_idle(old_timer)
        self.client.disconnect.assert_not_awaited()

    async def test_zero_timeout_disconnects_in_background(self):
        self.entity._connection_timeout = 0
        await self.entity.async_turn_on()
        self.assertIs(self.entity._attr_is_on, True)
        # Let the real timer fire, then drain the HA background task.
        for _ in range(5):
            await asyncio.sleep(0)
        self.client.disconnect.assert_awaited_once()
        self.assertIsNone(self.entity._client)

    async def test_dropped_connection_reconnects(self):
        await self.entity.async_turn_on()
        self.client.is_connected = False
        replacement = self.make_client()
        self.connect.return_value = replacement
        await self.entity.async_turn_off()
        replacement.write_gatt_char.assert_awaited_once_with(
            switch.STATE_CHARACTERISTIC, b"\x00", response=True
        )
        self.assertEqual(self.connect.await_count, 2)

    async def test_stale_connection_retries_explicit_state_once(self):
        await self.entity.async_turn_on()
        self.client.write_gatt_char.side_effect = BleakError("Disconnected")
        replacement = self.make_client()
        self.connect.return_value = replacement
        await self.entity.async_turn_off()
        self.client.disconnect.assert_awaited_once()
        replacement.write_gatt_char.assert_awaited_once_with(
            switch.STATE_CHARACTERISTIC, b"\x00", response=True
        )
        self.assertIs(self.entity._attr_is_on, False)

    async def test_failed_write_does_not_publish_state(self):
        self.client.write_gatt_char.side_effect = BleakError("Write failed")
        with self.assertRaises(HomeAssistantError):
            await self.entity.async_turn_on()
        self.client.disconnect.assert_awaited_once()
        self.assertIsNone(self.entity._client)
        self.assertIsNone(self.entity._attr_is_on)
        self.entity.async_write_ha_state.assert_not_called()

    async def test_reconnect_retry_is_bounded(self):
        await self.entity.async_turn_on()
        self.client.write_gatt_char.side_effect = BleakError("Disconnected")
        replacement = self.make_client()
        replacement.write_gatt_char.side_effect = BleakError("Write failed")
        self.connect.return_value = replacement
        with self.assertRaises(HomeAssistantError):
            await self.entity.async_turn_off()
        self.assertEqual(self.connect.await_count, 2)
        replacement.disconnect.assert_awaited_once()
        self.assertIsNone(self.entity._client)
        self.assertIsNone(self.entity._disconnect_timer)
        self.assertIs(self.entity._attr_is_on, True)

    async def test_missing_device(self):
        self.lookup.return_value = None
        with self.assertRaisesRegex(HomeAssistantError, "has not been discovered"):
            await self.entity.async_turn_on()
        self.connect.assert_not_awaited()

    async def test_commands_are_serialized(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def write(*args, **kwargs):
            entered.set()
            await release.wait()

        self.client.write_gatt_char.side_effect = write
        first = asyncio.create_task(self.entity.async_turn_on())
        await entered.wait()
        second = asyncio.create_task(self.entity.async_turn_off())
        await asyncio.sleep(0)
        self.assertEqual(self.client.write_gatt_char.await_count, 1)
        release.set()
        await asyncio.gather(first, second)
        self.connect.assert_awaited_once()
        self.assertIs(self.entity._attr_is_on, False)

    async def test_shutdown_during_write_cancels_new_idle_timer(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def write(*args, **kwargs):
            entered.set()
            await release.wait()

        self.client.write_gatt_char.side_effect = write
        command = asyncio.create_task(self.entity.async_turn_on())
        await entered.wait()
        shutdown = asyncio.create_task(self.entity._async_shutdown())
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(command, shutdown)
        self.assertIsNone(self.entity._disconnect_timer)
        self.client.disconnect.assert_awaited_once()
        with self.assertRaisesRegex(HomeAssistantError, "shutting down"):
            await self.entity.async_turn_off()

    async def test_cancelled_write_still_schedules_cleanup(self):
        entered = asyncio.Event()

        async def write(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()

        self.client.write_gatt_char.side_effect = write
        task = asyncio.create_task(self.entity.async_turn_on())
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNotNone(self.entity._disconnect_timer)
        self.entity.async_write_ha_state.assert_not_called()


if __name__ == "__main__":
    unittest.main()
