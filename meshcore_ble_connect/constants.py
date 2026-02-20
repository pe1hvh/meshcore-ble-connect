"""Constants and configuration for meshcore-ble-connect.

Single source of truth for version, exit codes, and D-Bus paths.
"""

from enum import IntEnum

VERSION: str = "1.0.0"
TOOL_NAME: str = "meshcore-ble-connect"

# D-Bus constants
BLUEZ_SERVICE: str = "org.bluez"
BLUEZ_ROOT_PATH: str = "/"
ADAPTER_INTERFACE: str = "org.bluez.Adapter1"
DEVICE_INTERFACE: str = "org.bluez.Device1"
AGENT_INTERFACE: str = "org.bluez.Agent1"
AGENT_MANAGER_INTERFACE: str = "org.bluez.AgentManager1"
PROPERTIES_INTERFACE: str = "org.freedesktop.DBus.Properties"
OBJECT_MANAGER_INTERFACE: str = "org.freedesktop.DBus.ObjectManager"

BLUEZ_PATH: str = "/org/bluez"
ADAPTER_PATH: str = "/org/bluez/hci0"
AGENT_PATH: str = "/org/bluez/agent/meshcore"
DEVICE_PATH_PREFIX: str = "/org/bluez/hci0/dev_"

# Agent capability — KeyboardDisplay for BLE passkey entry
AGENT_CAPABILITY: str = "KeyboardDisplay"

# Timeouts (seconds)
DISCOVERY_TIMEOUT: float = 30.0
CONNECT_TIMEOUT: float = 10.0
CONNECT_RETRIES: int = 5
CONNECT_RETRY_DELAY: float = 1.0

# PIN constraints
PIN_MAX_LENGTH: int = 16


def mac_to_device_path(mac: str) -> str:
    """Converts a MAC address to a BlueZ device object path.

    Args:
        mac: MAC address (e.g. 'AA:BB:CC:DD:EE:FF').

    Returns:
        D-Bus path (e.g. '/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF').
    """
    mac_underscored = mac.replace(":", "_")
    return f"{DEVICE_PATH_PREFIX}{mac_underscored}"


class ExitCode(IntEnum):
    """Process exit codes as defined in the design document (§6.2).

    Attributes:
        OK: Bond verified — ready for application.
        BOND_INVALID: Bond not present or invalid (with --check-only).
        PAIRING_FAILED: Pairing failed (wrong PIN, device unreachable).
        ADAPTER_ERROR: Adapter problem (not powered, not found).
        DBUS_PERMISSION: D-Bus permission error.
    """

    OK = 0
    BOND_INVALID = 1
    PAIRING_FAILED = 2
    ADAPTER_ERROR = 3
    DBUS_PERMISSION = 4
