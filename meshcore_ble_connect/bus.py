"""D-Bus system bus connection manager.

Provides a single shared connection to the D-Bus system bus used by
all components. Handles connection lifecycle and proxy object creation.
"""

import logging
from typing import Any

from dbus_fast.aio import MessageBus, ProxyObject
from dbus_fast import BusType

from .constants import BLUEZ_SERVICE
from .exceptions import DbusPermissionError

logger = logging.getLogger(__name__)


class BusConnection:
    """Manages the D-Bus system bus connection lifecycle.

    Provides helper methods for creating proxy objects that other
    components use to interact with BlueZ.

    Example:
        bus_conn = BusConnection()
        await bus_conn.connect()
        proxy = await bus_conn.get_proxy(ADAPTER_PATH)
        await bus_conn.disconnect()
    """

    def __init__(self) -> None:
        self._bus: MessageBus | None = None

    @property
    def bus(self) -> MessageBus:
        """Returns the active D-Bus connection.

        Raises:
            RuntimeError: If connect() has not been called.
        """
        if self._bus is None:
            raise RuntimeError("D-Bus connection not established. Call connect() first.")
        return self._bus

    async def connect(self) -> None:
        """Connects to the D-Bus system bus.

        Raises:
            DbusPermissionError: If the connection is refused due to permissions.
        """
        try:
            logger.debug("Connecting to D-Bus system bus")
            self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            logger.debug("D-Bus system bus connected")
        except PermissionError as exc:
            raise DbusPermissionError(
                "Cannot connect to D-Bus system bus. "
                "Are you running as root or in the bluetooth group?"
            ) from exc
        except Exception as exc:
            raise DbusPermissionError(
                f"Failed to connect to D-Bus system bus: {exc}"
            ) from exc

    async def get_proxy(self, object_path: str) -> ProxyObject:
        """Creates a proxy object for a BlueZ D-Bus path.

        Args:
            object_path: The D-Bus object path (e.g. '/org/bluez/hci0').

        Returns:
            A ProxyObject that can be used to get interfaces.

        Raises:
            RuntimeError: If connect() has not been called.
        """
        introspection = await self.bus.introspect(BLUEZ_SERVICE, object_path)
        return self.bus.get_proxy_object(BLUEZ_SERVICE, object_path, introspection)

    async def get_root_proxy(self) -> ProxyObject:
        """Creates a proxy object for the BlueZ root path.

        Used for ObjectManager operations like listening for
        InterfacesAdded signals during discovery.

        Returns:
            A ProxyObject for the BlueZ root path.
        """
        introspection = await self.bus.introspect(BLUEZ_SERVICE, "/")
        return self.bus.get_proxy_object(BLUEZ_SERVICE, "/", introspection)

    async def disconnect(self) -> None:
        """Disconnects from the D-Bus system bus."""
        if self._bus is not None:
            logger.debug("Disconnecting from D-Bus system bus")
            self._bus.disconnect()
            self._bus = None
