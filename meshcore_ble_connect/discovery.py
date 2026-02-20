"""BLE device discovery via D-Bus.

Triggers BlueZ discovery and waits for the target device to appear
by listening for the InterfacesAdded signal on the ObjectManager.
Discovery is only used when the device is not yet known to BlueZ.

See design document §7.4.
"""

import asyncio
import logging

from dbus_fast import Message, Variant

from .bus import BusConnection
from .constants import (
    ADAPTER_INTERFACE,
    ADAPTER_PATH,
    BLUEZ_SERVICE,
    DISCOVERY_TIMEOUT,
    OBJECT_MANAGER_INTERFACE,
    mac_to_device_path,
)
from .exceptions import DiscoveryError
from .output import OutputFormatter

logger = logging.getLogger(__name__)


class Discovery:
    """Discovers a BLE device by MAC address via D-Bus.

    Starts BlueZ discovery and listens for the InterfacesAdded signal
    filtered by the target MAC address. Stops discovery once the device
    is found or the timeout expires.

    Args:
        bus_conn: The shared D-Bus connection.
        mac: The target device MAC address (e.g. 'AA:BB:CC:DD:EE:FF').
        output: The output formatter for status messages.
    """

    def __init__(
        self,
        bus_conn: BusConnection,
        mac: str,
        output: OutputFormatter,
    ) -> None:
        self._bus_conn = bus_conn
        self._mac = mac
        self._output = output
        self._device_path = mac_to_device_path(mac)

    async def discover(self) -> str:
        """Starts discovery and waits for the target device.

        Returns:
            The D-Bus object path of the discovered device.

        Raises:
            DiscoveryError: If the device is not found within the timeout.
        """
        found_event = asyncio.Event()
        found_path: list[str] = []

        def on_interfaces_added(
            object_path: str,
            interfaces_and_properties: dict,
        ) -> None:
            """Signal handler for InterfacesAdded."""
            if object_path == self._device_path:
                logger.debug("Device appeared: %s", object_path)
                found_path.append(object_path)
                found_event.set()

        # Get ObjectManager for signal listening
        root_proxy = await self._bus_conn.get_root_proxy()
        obj_manager = root_proxy.get_interface(OBJECT_MANAGER_INTERFACE)
        obj_manager.on_interfaces_added(on_interfaces_added)

        # Get adapter interface for discovery control
        adapter_proxy = await self._bus_conn.get_proxy(ADAPTER_PATH)
        adapter = adapter_proxy.get_interface(ADAPTER_INTERFACE)

        try:
            # Set BLE-only transport filter to prevent classic Bluetooth pairing
            self._output.verbose("Setting BLE transport filter")
            await self._bus_conn.bus.call(
                Message(
                    destination=BLUEZ_SERVICE,
                    path=ADAPTER_PATH,
                    interface=ADAPTER_INTERFACE,
                    member="SetDiscoveryFilter",
                    signature="a{sv}",
                    body=[{"Transport": Variant("s", "le")}],
                )
            )

            self._output.verbose(f"Starting discovery for {self._mac}")
            await adapter.call_start_discovery()

            try:
                await asyncio.wait_for(found_event.wait(), timeout=DISCOVERY_TIMEOUT)
            except asyncio.TimeoutError:
                raise DiscoveryError(
                    f"Device {self._mac} not found within {DISCOVERY_TIMEOUT}s. "
                    "Is the device powered on and advertising?"
                )

            self._output.verbose(f"Device found: {found_path[0]}")
            return found_path[0]

        finally:
            try:
                await adapter.call_stop_discovery()
            except Exception:
                # StopDiscovery may fail if discovery was already stopped
                logger.debug("StopDiscovery failed (may already be stopped)")
            # Allow BlueZ to fully release scan state before Connect()
            await asyncio.sleep(2.0)

