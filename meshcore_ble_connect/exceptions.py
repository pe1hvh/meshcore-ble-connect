"""Custom exceptions for meshcore-ble-connect.

Each exception maps to a specific exit code, enabling clean error
propagation from any component to the top-level orchestrator.
"""


class BleConnectError(Exception):
    """Base exception for all meshcore-ble-connect errors."""


class AdapterError(BleConnectError):
    """Adapter is not available, not powered, or cannot be configured.

    Maps to ExitCode.ADAPTER_ERROR (3).
    """


class PairingError(BleConnectError):
    """Pairing failed — wrong PIN, device unreachable, or agent rejected.

    Maps to ExitCode.PAIRING_FAILED (2).
    """


class DiscoveryError(BleConnectError):
    """Device not found during BLE discovery within the timeout period.

    Maps to ExitCode.PAIRING_FAILED (2).
    """


class BondVerificationError(BleConnectError):
    """Test connect failed — bond exists in BlueZ but device rejected it.

    This is an expected condition, not a fatal error. The orchestrator
    handles this by removing the invalid bond and re-pairing.
    """


class DbusPermissionError(BleConnectError):
    """Insufficient permissions to access D-Bus system bus or BlueZ.

    Maps to ExitCode.DBUS_PERMISSION (4).
    """
