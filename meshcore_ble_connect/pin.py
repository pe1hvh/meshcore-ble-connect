"""PIN provider abstraction and implementations.

Defines the PinProvider protocol and two concrete implementations:
- StaticPinProvider: uses a pre-configured PIN (for --pin flag / systemd)
- InteractivePinProvider: prompts the user on stdin

The protocol enables Dependency Inversion: the orchestrator depends on
the abstraction, not on the concrete input method.
"""

import getpass
import logging
from typing import Protocol, runtime_checkable

from .output import OutputFormatter

logger = logging.getLogger(__name__)


@runtime_checkable
class PinProvider(Protocol):
    """Protocol for obtaining a PIN code.

    Implementations must provide a get_pin() method that returns
    the PIN string. The method is async to support future providers
    that might need I/O (e.g. GUI dialog, network request).
    """

    async def get_pin(self) -> str:
        """Obtains a PIN code for BLE pairing.

        Returns:
            The PIN code as a string.
        """
        ...


class StaticPinProvider:
    """Provides a pre-configured PIN code.

    Used when the PIN is supplied via the --pin CLI flag, enabling
    non-interactive operation for systemd services and scripts.

    Args:
        pin: The PIN code string.
    """

    def __init__(self, pin: str) -> None:
        self._pin = pin

    async def get_pin(self) -> str:
        """Returns the pre-configured PIN.

        Returns:
            The PIN code string.
        """
        logger.debug("Using pre-configured PIN")
        return self._pin


class InteractivePinProvider:
    """Prompts the user for a PIN code on stdin.

    Used in interactive mode when no --pin flag is provided.
    The PIN is entered securely (no echo) using getpass.

    Args:
        output: The output formatter for displaying the prompt.
    """

    def __init__(self, output: OutputFormatter) -> None:
        self._output = output

    async def get_pin(self) -> str:
        """Prompts the user to enter a PIN code.

        Returns:
            The PIN code entered by the user.
        """
        logger.debug("Prompting user for PIN")
        pin = getpass.getpass("Enter PIN: ")
        return pin
