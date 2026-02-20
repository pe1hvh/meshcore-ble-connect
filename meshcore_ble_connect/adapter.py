"""Bluetooth adapter management via D-Bus.

Handles adapter discovery, power-on, and pairable configuration.
All operations are idempotent: if the condition is already met,
the step is skipped.

See design document §4 (steps 1-2) and §7.1.
"""

import logging

from dbus_fast import Variant

from .bus import BusConnection
from .constants import (
    ADAPTER_INTERFACE,
    ADAPTER_PATH,
    BLUEZ_SERVICE,
    PROPERTIES_INTERFACE,
)
from .exceptions import AdapterError
from .output import OutputFormatter

logger = logging.getLogger(__name__)


class AdapterManager:
    """Manages the Bluetooth adapter state via D-Bus.

    Ensures the adapter is powered on and pairable before any
    pairing operations begin. All operations are idempotent.

    Args:
        bus_conn: The shared D-Bus connection.
        output: The output formatter for status messages.
    """

    def __init__(self, bus_conn: BusConnection, output: OutputFormatter) -> None:
        self._bus_conn = bus_conn
        self._output = output

    async def ensure_powered(self) -> None:
        """Ensures the Bluetooth adapter is powered on.

        If the adapter is already powered, this is a no-op.

        Raises:
            AdapterError: If the adapter cannot be found or powered on.
        """
        try:
            props = await self._get_properties_interface()
            powered = await props.call_get(ADAPTER_INTERFACE, "Powered")
            if powered.value:
                self._output.verbose("Adapter already powered")
                return
            self._output.verbose("Powering on adapter")
            await props.call_set(ADAPTER_INTERFACE, "Powered", Variant("b", True))
            logger.info("Adapter powered on")
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(f"Failed to power on adapter: {exc}") from exc

    async def ensure_pairable(self) -> None:
        """Ensures the Bluetooth adapter is in pairable mode.

        If the adapter is already pairable, this is a no-op.

        Raises:
            AdapterError: If the adapter cannot be set to pairable.
        """
        try:
            props = await self._get_properties_interface()
            pairable = await props.call_get(ADAPTER_INTERFACE, "Pairable")
            if pairable.value:
                self._output.verbose("Adapter already pairable")
                return
            self._output.verbose("Enabling pairable mode")
            await props.call_set(ADAPTER_INTERFACE, "Pairable", Variant("b", True))
            logger.info("Adapter set to pairable")
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(f"Failed to enable pairable: {exc}") from exc

    async def get_adapter_info(self) -> str:
        """Returns a summary string for the adapter status.

        Returns:
            A string like 'hci0 (powered, pairable)'.

        Raises:
            AdapterError: If the adapter cannot be queried.
        """
        try:
            props = await self._get_properties_interface()
            powered = await props.call_get(ADAPTER_INTERFACE, "Powered")
            pairable = await props.call_get(ADAPTER_INTERFACE, "Pairable")
            flags = []
            if powered.value:
                flags.append("powered")
            if pairable.value:
                flags.append("pairable")
            flag_str = ", ".join(flags) if flags else "inactive"
            return f"hci0 ({flag_str})"
        except Exception as exc:
            raise AdapterError(f"Failed to query adapter: {exc}") from exc

    async def get_bluez_version(self) -> str:
        """Retrieves the BlueZ version from the adapter properties.

        Returns:
            The BlueZ version string, or 'unknown' if not available.
        """
        try:
            introspection = await self._bus_conn.bus.introspect(
                BLUEZ_SERVICE, ADAPTER_PATH
            )
            # BlueZ doesn't expose version via a standard property;
            # we parse it from the bluetoothd process or return a
            # placeholder. The version is informational only.
            return await self._read_bluez_version()
        except Exception:
            return "unknown"

    async def _read_bluez_version(self) -> str:
        """Reads the BlueZ version via bluetoothd --version or D-Bus.

        Returns:
            The version string, or 'unknown'.
        """
        import asyncio

        try:
            proc = await asyncio.create_subprocess_exec(
                "bluetoothctl", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            # Output: "bluetoothctl: 5.82"
            version_line = stdout.decode().strip()
            if ":" in version_line:
                return version_line.split(":")[-1].strip()
            return version_line or "unknown"
        except Exception:
            return "unknown"

    async def _get_properties_interface(self):
        """Gets the Properties interface for the adapter.

        Returns:
            The org.freedesktop.DBus.Properties interface proxy.

        Raises:
            AdapterError: If the adapter path does not exist.
        """
        try:
            proxy = await self._bus_conn.get_proxy(ADAPTER_PATH)
            return proxy.get_interface(PROPERTIES_INTERFACE)
        except Exception as exc:
            raise AdapterError(
                f"Bluetooth adapter not found at {ADAPTER_PATH}. "
                "Is Bluetooth enabled?"
            ) from exc
