"""BLE device management via D-Bus.

Handles all device-level operations: existence check, paired status,
bond verification (test connect), pairing, trust, and removal.
All operations use the BlueZ Device1 D-Bus interface directly.

See design document §4 (steps 3-9), §7.1, and §7.3.
"""

import asyncio
import logging

from dbus_fast import Message, MessageType, Variant
from dbus_fast.errors import DBusError

from .agent import PairingAgent
from .bus import BusConnection
from .constants import (
    ADAPTER_INTERFACE,
    ADAPTER_PATH,
    AGENT_MANAGER_INTERFACE,
    AGENT_PATH,
    BLUEZ_PATH,
    BLUEZ_SERVICE,
    CONNECT_RETRIES,
    CONNECT_RETRY_DELAY,
    CONNECT_TIMEOUT,
    DEVICE_INTERFACE,
    AGENT_CAPABILITY,
    OBJECT_MANAGER_INTERFACE,
    PROPERTIES_INTERFACE,
    mac_to_device_path,
)
from .exceptions import BondVerificationError, PairingError
from .output import OutputFormatter

logger = logging.getLogger(__name__)


class DeviceManager:
    """Manages a single BLE device via D-Bus.

    Provides all device-level operations needed by the connection
    manager: existence check, paired status, bond verification,
    pairing with a PIN agent, trust configuration, and device removal.

    Args:
        bus_conn: The shared D-Bus connection.
        mac: The target device MAC address.
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

    async def device_exists(self) -> bool:
        """Checks if the device is a managed BlueZ object with Device1 interface.

        Uses ObjectManager.GetManagedObjects() via direct D-Bus message
        instead of introspection, because introspection can return XML
        for non-existent device paths.

        Returns:
            True if the device is a real managed object in BlueZ.
        """
        reply = await self._bus_conn.bus.call(
            Message(
                destination=BLUEZ_SERVICE,
                path="/",
                interface=OBJECT_MANAGER_INTERFACE,
                member="GetManagedObjects",
            )
        )
        if reply.message_type == MessageType.ERROR:
            self._output.verbose(f"GetManagedObjects failed: {reply.error_name}")
            return False

        managed_objects = reply.body[0]  # dict: path -> {interface -> {prop -> value}}
        if self._device_path in managed_objects:
            interfaces = managed_objects[self._device_path]
            if DEVICE_INTERFACE in interfaces:
                self._output.verbose(f"Device exists: {self._device_path}")
                return True

        self._output.verbose(f"Device not found: {self._device_path}")
        return False

    async def is_paired(self) -> bool:
        """Checks if the device is currently paired in BlueZ.

        Returns:
            True if the Device1.Paired property is true.
        """
        try:
            props = await self._get_device_properties()
            paired = await props.call_get(DEVICE_INTERFACE, "Paired")
            return bool(paired.value)
        except Exception:
            return False

    async def is_trusted(self) -> bool:
        """Checks if the device is currently trusted in BlueZ.

        Returns:
            True if the Device1.Trusted property is true.
        """
        try:
            props = await self._get_device_properties()
            trusted = await props.call_get(DEVICE_INTERFACE, "Trusted")
            return bool(trusted.value)
        except Exception:
            return False

    async def verify_bond(self) -> bool:
        """Verifies the bond with a test GATT connect.

        Performs a short connect/disconnect cycle via D-Bus to check
        if the device still recognizes the bond. This detects stale
        bonds where BlueZ has the key but the device has lost it
        (e.g. after a reboot or reflash).

        Returns:
            True if the test connect succeeded, False if rejected.

        See design document §7.3.
        """
        self._output.verbose("Verifying bond with test connect")
        try:
            device_proxy = await self._bus_conn.get_proxy(self._device_path)
            device_iface = device_proxy.get_interface(DEVICE_INTERFACE)

            await asyncio.wait_for(
                device_iface.call_connect(),
                timeout=CONNECT_TIMEOUT,
            )
            # Bond is valid — disconnect cleanly
            try:
                await device_iface.call_disconnect()
            except Exception:
                logger.debug("Disconnect after verify failed (non-critical)")
            return True

        except (DBusError, asyncio.TimeoutError, Exception) as exc:
            logger.debug("Bond verification failed: %s", exc)
            return False

    async def pair(self, agent: PairingAgent) -> None:
        """Pairs with the device using the provided PIN agent.

        BLE pairing requires an active L2CAP connection before SMP
        (Security Manager Protocol) can run. The sequence is:
        1. Register PIN agent on D-Bus
        2. Device1.Connect() — establishes BLE L2CAP connection
        3. Device1.Pair() — SMP pairing over existing connection
        4. Disconnect — clean up for application to connect later

        All D-Bus operations use direct Message calls (no introspection)
        following the same pattern as the bleak library.

        Args:
            agent: The PairingAgent that provides the PIN code.

        Raises:
            PairingError: If pairing fails.

        See design document §7.2.
        """
        bus = self._bus_conn.bus

        try:
            # Step 1: Export and register PIN agent
            bus.export(AGENT_PATH, agent)
            self._output.field("Agent", "registered")
            await self._register_agent(bus)

            # Step 2: Connect (direct Message, with retry on abort-by-local)
            await self._ble_connect(bus)
            self._output.verbose("Connected — initiating SMP pairing")

            # Step 3: Pair over existing connection (direct Message)
            reply = await bus.call(
                Message(
                    destination=BLUEZ_SERVICE,
                    interface=DEVICE_INTERFACE,
                    path=self._device_path,
                    member="Pair",
                )
            )
            if reply.message_type == MessageType.ERROR:
                raise DBusError(reply.error_name, reply.body[0] if reply.body else "Pair failed")

            self._output.field("Pairing", "success")
            logger.info("Pairing successful for %s", self._mac)

            # Step 4: Disconnect (application will connect later)
            try:
                await bus.call(
                    Message(
                        destination=BLUEZ_SERVICE,
                        interface=DEVICE_INTERFACE,
                        path=self._device_path,
                        member="Disconnect",
                    )
                )
            except Exception:
                logger.debug("Disconnect after pair failed (non-critical)")

        except DBusError as exc:
            raise PairingError(
                f"Pairing failed for {self._mac}: {exc.text}"
            ) from exc
        except PairingError:
            raise
        except asyncio.TimeoutError as exc:
            raise PairingError(
                f"Connection to {self._mac} timed out. "
                "Is the device powered on and in range?"
            ) from exc
        except Exception as exc:
            raise PairingError(
                f"Pairing failed for {self._mac}: {exc}"
            ) from exc
        finally:
            # Clean up agent registration
            try:
                await self._unregister_agent(bus)
            except Exception:
                logger.debug("Agent unregister failed (non-critical)")
            try:
                bus.unexport(AGENT_PATH)
            except Exception:
                logger.debug("Agent unexport failed (non-critical)")

    async def _register_agent(self, bus) -> None:
        """Registers the pairing agent with BlueZ AgentManager1.

        Uses a direct D-Bus method call instead of proxy introspection,
        because AgentManager1 is not always visible via introspection.

        Args:
            bus: The active MessageBus connection.

        Raises:
            PairingError: If agent registration fails.
        """
        reply = await bus.call(
            Message(
                destination=BLUEZ_SERVICE,
                path=BLUEZ_PATH,
                interface=AGENT_MANAGER_INTERFACE,
                member="RegisterAgent",
                signature="os",
                body=[AGENT_PATH, AGENT_CAPABILITY],
            )
        )
        if reply.message_type == MessageType.ERROR:
            raise PairingError(
                f"Failed to register agent: {reply.error_name}: {reply.body}"
            )
        logger.debug("Agent registered with BlueZ")

    async def _unregister_agent(self, bus) -> None:
        """Unregisters the pairing agent from BlueZ AgentManager1.

        Args:
            bus: The active MessageBus connection.
        """
        await bus.call(
            Message(
                destination=BLUEZ_SERVICE,
                path=BLUEZ_PATH,
                interface=AGENT_MANAGER_INTERFACE,
                member="UnregisterAgent",
                signature="o",
                body=[AGENT_PATH],
            )
        )

    async def _ble_connect(self, bus) -> None:
        """Establishes BLE L2CAP connection using direct D-Bus messages.

        Retries on le-connection-abort-by-local (RF timing issue after
        discovery). Between retries, waits for the Connected property
        to go back to False — same pattern as bleak library.

        Args:
            bus: The active MessageBus connection.

        Raises:
            PairingError: If connection fails after all retries.
        """
        self._output.verbose("Connecting to device (BLE L2CAP)")

        for attempt in range(1, CONNECT_RETRIES + 1):
            reply = await asyncio.wait_for(
                bus.call(
                    Message(
                        destination=BLUEZ_SERVICE,
                        interface=DEVICE_INTERFACE,
                        path=self._device_path,
                        member="Connect",
                    )
                ),
                timeout=CONNECT_TIMEOUT,
            )

            if reply.message_type != MessageType.ERROR:
                return  # Connected successfully

            error_msg = reply.body[0] if reply.body else str(reply.error_name)

            if "le-connection-abort-by-local" not in error_msg:
                raise PairingError(
                    f"Connection failed for {self._mac}: {error_msg}"
                )

            logger.debug(
                "Connect attempt %d/%d: %s (retrying)",
                attempt, CONNECT_RETRIES, error_msg,
            )
            self._output.verbose(f"Connect retry {attempt}/{CONNECT_RETRIES}")

            # Wait for BlueZ to fully process the disconnect before retrying.
            # BlueZ briefly sets Connected=True then back to False on this error.
            await asyncio.sleep(CONNECT_RETRY_DELAY * attempt)

        raise PairingError(
            f"Connection to {self._mac} failed after {CONNECT_RETRIES} attempts. "
            "Is the device powered on and in range?"
        )

    async def trust(self) -> None:
        """Sets the device as trusted if not already trusted.

        Idempotent: if the device is already trusted, this is a no-op.
        """
        try:
            if await self.is_trusted():
                self._output.verbose("Device already trusted")
                return
            props = await self._get_device_properties()
            await props.call_set(DEVICE_INTERFACE, "Trusted", Variant("b", True))
            self._output.field("Trusted", "set")
            logger.info("Device %s set as trusted", self._mac)
        except Exception as exc:
            logger.warning("Failed to set trusted: %s", exc)
            # Non-fatal: pairing succeeded, trust is best-effort

    async def remove(self) -> None:
        """Removes the device from BlueZ (cleans up the bond).

        Uses a direct D-Bus message call to Adapter1.RemoveDevice.
        After removal, the device path no longer exists and a fresh
        discovery + pairing cycle is required.
        """
        reply = await self._bus_conn.bus.call(
            Message(
                destination=BLUEZ_SERVICE,
                path=ADAPTER_PATH,
                interface=ADAPTER_INTERFACE,
                member="RemoveDevice",
                signature="o",
                body=[self._device_path],
            )
        )
        if reply.message_type == MessageType.ERROR:
            logger.debug("RemoveDevice failed: %s: %s", reply.error_name, reply.body)
        else:
            self._output.verbose(f"Removed device {self._mac}")
            logger.info("Removed device %s", self._mac)

    async def remove_if_exists(self) -> None:
        """Removes the device if it exists in BlueZ.

        Idempotent: if the device does not exist, this is a no-op.
        """
        if await self.device_exists():
            await self.remove()

    async def get_bond_info(self) -> str:
        """Returns a human-readable summary of the current bond state.

        Returns:
            A string like 'found (paired + trusted)' or 'not found'.
        """
        if not await self.device_exists():
            return "not found \u2014 pairing required"
        paired = await self.is_paired()
        trusted = await self.is_trusted()
        if paired and trusted:
            return "found (paired + trusted)"
        if paired:
            return "found (paired, not trusted)"
        return "found (not paired)"

    async def _get_device_properties(self):
        """Gets the Properties interface for the device.

        Returns:
            The org.freedesktop.DBus.Properties interface proxy.
        """
        proxy = await self._bus_conn.get_proxy(self._device_path)
        return proxy.get_interface(PROPERTIES_INTERFACE)

