"""D-Bus pairing agent for PIN-based BLE authentication.

Implements the org.bluez.Agent1 interface for MeshCore devices.
Supports both legacy PIN (RequestPinCode) and BLE passkey
(RequestPasskey) methods. MeshCore BLE devices use numeric
passkey entry for SMP pairing.

See design document §7.2.
"""

import logging

from dbus_fast.service import ServiceInterface, method

logger = logging.getLogger(__name__)


class PairingAgent(ServiceInterface):
    """BlueZ Agent1 implementation for static PIN/passkey pairing.

    This agent is registered on the D-Bus system bus and responds
    to BlueZ pairing requests with the configured PIN code.

    Implements both RequestPinCode (legacy BR/EDR) and RequestPasskey
    (BLE SMP) to support all BlueZ pairing scenarios.

    Args:
        pin: The PIN code to respond with during pairing.
    """

    def __init__(self, pin: str) -> None:
        super().__init__("org.bluez.Agent1")
        self._pin = pin

    @method()
    def RequestPinCode(self, device: "o") -> "s":  # noqa: N802
        """Called by BlueZ for legacy (BR/EDR) PIN authentication.

        Args:
            device: The D-Bus object path of the device being paired.

        Returns:
            The PIN code string.
        """
        logger.debug("PinCode requested for device: %s", device)
        return self._pin

    @method()
    def RequestPasskey(self, device: "o") -> "u":  # noqa: N802
        """Called by BlueZ for BLE SMP passkey authentication.

        Args:
            device: The D-Bus object path of the device being paired.

        Returns:
            The passkey as uint32.
        """
        passkey = int(self._pin)
        logger.debug("Passkey requested for device: %s → %d", device, passkey)
        return passkey

    @method()
    def DisplayPasskey(self, device: "o", passkey: "u", entered: "q") -> None:  # noqa: N802
        """Called by BlueZ to display a passkey during pairing."""
        logger.debug("DisplayPasskey for %s: %06d (entered: %d)", device, passkey, entered)

    @method()
    def RequestConfirmation(self, device: "o", passkey: "u") -> None:  # noqa: N802
        """Called by BlueZ for numeric comparison — auto-confirm."""
        logger.debug("Auto-confirming passkey %06d for %s", passkey, device)

    @method()
    def AuthorizeService(self, device: "o", uuid: "s") -> None:  # noqa: N802
        """Called by BlueZ to authorize a service — auto-authorize."""
        logger.debug("Auto-authorizing service %s for %s", uuid, device)

    @method()
    def Release(self) -> None:  # noqa: N802
        """Called by BlueZ when the agent is unregistered."""
        logger.debug("Agent released")
