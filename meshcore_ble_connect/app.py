"""BLE Connection Manager orchestrator.

Implements the main flow from design §4: adapter check → device check →
bond verification → pairing → trust. Coordinates all components and
translates exceptions to exit codes.
"""

import logging

from .adapter import AdapterManager
from .bus import BusConnection
from .agent import PairingAgent
from .constants import ExitCode
from .device import DeviceManager
from .discovery import Discovery
from .exceptions import (
    AdapterError,
    BleConnectError,
    DbusPermissionError,
    DiscoveryError,
    PairingError,
)
from .output import OutputFormatter
from .pin import PinProvider

logger = logging.getLogger(__name__)


class BleConnectApp:
    """Orchestrates the BLE connection management flow.

    Runs through the fixed sequence of D-Bus operations defined in
    the design document (§4). Every step is idempotent: if the
    condition is already satisfied, the step is skipped.

    Args:
        mac: Target device MAC address (e.g. 'AA:BB:CC:DD:EE:FF').
        pin_provider: Provider for obtaining the PIN code.
        force_repair: Skip verification and force re-pairing.
        check_only: Only check bond status, do not pair.
        verbose: Enable verbose output.
    """

    def __init__(
        self,
        mac: str,
        pin_provider: PinProvider,
        force_repair: bool = False,
        check_only: bool = False,
        verbose: bool = False,
    ) -> None:
        self._mac = mac.upper()
        self._pin_provider = pin_provider
        self._force_repair = force_repair
        self._check_only = check_only
        self._output = OutputFormatter(verbose=verbose)
        self._bus_conn = BusConnection()

    async def run(self) -> ExitCode:
        """Executes the connection management flow.

        Returns:
            The appropriate ExitCode for the result.
        """
        try:
            await self._bus_conn.connect()
            return await self._execute_flow()
        except DbusPermissionError as exc:
            self._output.error(str(exc))
            return ExitCode.DBUS_PERMISSION
        except AdapterError as exc:
            self._output.error(str(exc))
            return ExitCode.ADAPTER_ERROR
        except (PairingError, DiscoveryError) as exc:
            self._output.error(str(exc))
            return ExitCode.PAIRING_FAILED
        except BleConnectError as exc:
            self._output.error(str(exc))
            return ExitCode.PAIRING_FAILED
        except Exception as exc:
            self._output.error(f"Unexpected error: {exc}")
            logger.exception("Unexpected error")
            return ExitCode.PAIRING_FAILED
        finally:
            await self._bus_conn.disconnect()

    async def _execute_flow(self) -> ExitCode:
        """Runs the main orchestration flow.

        This implements the flowchart from design §4:
        1. Adapter powered? → power on
        2. Adapter pairable? → enable
        3. Device known? → check paired → verify bond → pair if needed
        4. Trust device
        5. Exit with appropriate code

        Returns:
            The appropriate ExitCode.
        """
        adapter = AdapterManager(self._bus_conn, self._output)
        device = DeviceManager(self._bus_conn, self._mac, self._output)

        # Print header
        bluez_version = await adapter.get_bluez_version()
        self._output.header(bluez_version, await adapter.get_adapter_info(), self._mac)

        # Step 1-2: Ensure adapter is ready
        await adapter.ensure_powered()
        await adapter.ensure_pairable()

        # Handle --force-repair: skip verification, remove and re-pair
        if self._force_repair:
            return await self._handle_force_repair(device)

        # Step 3: Check if device is known to BlueZ
        if await device.device_exists():
            # Step 4: Check if device is paired
            if await device.is_paired():
                bond_info = await device.get_bond_info()
                self._output.field("Bond", bond_info)

                # Step 5: Verify bond with test connect
                self._output.field("Verify", "testing connection...")
                bond_valid = await device.verify_bond()

                if bond_valid:
                    self._output.field("Verify", "test connect OK")
                    # Handle --check-only
                    if self._check_only:
                        self._output.result("Bond verified \u2014 ready to connect")
                        return ExitCode.OK
                    # Step 9: Ensure trusted
                    await device.trust()
                    self._output.result("Bond verified \u2014 ready to connect")
                    return ExitCode.OK
                else:
                    # Step 6: Bond is invalid — remove and re-pair
                    self._output.field("Verify", "test connect FAILED \u2014 bond is invalid")
                    self._output.field("Cleanup", "removed invalid bond")
                    await device.remove()
                    # Fall through to pairing flow

            else:
                self._output.field("Bond", "found (not paired)")
                # Stale cache entry — remove so discovery does a real BLE scan
                await device.remove()
                self._output.verbose("Removed stale device for clean discovery")

        else:
            self._output.field("Bond", "not found \u2014 pairing required")

        # Handle --check-only: no valid bond, report and exit
        if self._check_only:
            self._output.result("No valid bond present")
            return ExitCode.BOND_INVALID

        # Pairing flow (§5.1 / §5.3)
        return await self._pair_flow(device)

    async def _pair_flow(self, device: DeviceManager) -> ExitCode:
        """Executes the discovery + pairing + trust flow.

        Args:
            device: The device manager for the target device.

        Returns:
            ExitCode.OK on success.
        """
        # Step 7: Get PIN
        pin = await self._pin_provider.get_pin()

        # Step 8: Discover device
        discovery = Discovery(self._bus_conn, self._mac, self._output)
        await discovery.discover()

        # Register agent and pair
        agent = PairingAgent(pin)
        await device.pair(agent)

        # Step 9: Ensure trusted
        await device.trust()

        self._output.result("Bond established \u2014 ready to connect")
        return ExitCode.OK

    async def _handle_force_repair(self, device: DeviceManager) -> ExitCode:
        """Handles the --force-repair flow (§5.4).

        Skips bond verification, removes the device immediately,
        and performs a fresh pairing.

        Args:
            device: The device manager for the target device.

        Returns:
            ExitCode.OK on success.
        """
        self._output.field("Mode", "force-repair")

        # Remove existing device (if any)
        await device.remove_if_exists()
        self._output.field("Cleanup", "removed existing bond")

        # Pair fresh
        pin = await self._pin_provider.get_pin()
        discovery = Discovery(self._bus_conn, self._mac, self._output)
        await discovery.discover()

        agent = PairingAgent(pin)
        await device.pair(agent)
        await device.trust()

        self._output.result("Re-paired \u2014 ready to connect")
        return ExitCode.OK
