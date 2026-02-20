"""Structured CLI output formatter.

Produces the aligned key-value output format defined in the design
document (§6.3). Separates presentation from business logic.
"""

import logging
import sys

from .constants import TOOL_NAME, VERSION

logger = logging.getLogger(__name__)


class OutputFormatter:
    """Formats and prints structured CLI output.

    Produces aligned key-value pairs as shown in design §6.3:
        meshcore-ble-connect v1.0
        BlueZ:    5.82
        Adapter:  hci0 (powered, pairable)
        ...

    Args:
        verbose: When True, additional debug information is printed.
    """

    LABEL_WIDTH: int = 10

    def __init__(self, verbose: bool = False) -> None:
        self._verbose = verbose

    def header(self, bluez_version: str, adapter_name: str, mac: str) -> None:
        """Prints the tool header with version and environment info.

        Args:
            bluez_version: The detected BlueZ version string.
            adapter_name: The Bluetooth adapter name (e.g. 'hci0').
            mac: The target device MAC address.
        """
        self._print(f"{TOOL_NAME} v{VERSION}")
        self._field("BlueZ", bluez_version)
        self._field("Adapter", adapter_name)
        self._field("Device", mac)

    def field(self, label: str, value: str) -> None:
        """Prints a labeled field in the output.

        Args:
            label: The field label (e.g. 'Bond', 'Verify').
            value: The field value.
        """
        self._field(label, value)

    def result(self, message: str) -> None:
        """Prints the final result line with a checkmark.

        Args:
            message: The result message.
        """
        self._field("Result", f"\u2705 {message}")

    def error(self, message: str) -> None:
        """Prints an error message to stderr.

        Args:
            message: The error message.
        """
        print(f"Error:    {message}", file=sys.stderr)

    def verbose(self, message: str) -> None:
        """Prints a message only when verbose mode is enabled.

        Args:
            message: The debug message.
        """
        if self._verbose:
            self._print(f"  [{message}]")
            logger.debug(message)

    def prompt(self, message: str) -> None:
        """Prints a prompt message without a newline.

        Args:
            message: The prompt text.
        """
        print(message, end="", flush=True)

    def _field(self, label: str, value: str) -> None:
        """Prints a field with aligned label and value.

        Args:
            label: The field label.
            value: The field value.
        """
        padded_label = f"{label}:".ljust(self.LABEL_WIDTH)
        self._print(f"{padded_label}{value}")

    def _print(self, message: str) -> None:
        """Prints a message to stdout.

        Args:
            message: The text to print.
        """
        print(message)
