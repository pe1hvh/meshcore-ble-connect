"""Entry point for meshcore-ble-connect.

Parses CLI arguments as defined in design §6.1, configures logging,
creates the appropriate PinProvider, and runs the connection manager.
"""

import argparse
import asyncio
import logging
import re
import sys

from .app import BleConnectApp
from .constants import ExitCode, TOOL_NAME, VERSION
from .pin import InteractivePinProvider, StaticPinProvider
from .output import OutputFormatter

MAC_PATTERN = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parses command-line arguments.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description="BLE Connection Manager — ensures a BLE bond before your application starts.",
    )
    parser.add_argument(
        "mac",
        metavar="MAC",
        help="Target device MAC address (e.g. AA:BB:CC:DD:EE:FF)",
    )
    parser.add_argument(
        "--pin",
        metavar="PIN",
        default=None,
        help="PIN code for non-interactive pairing (for systemd / scripts)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Check if bond exists and is valid, without pairing",
    )
    parser.add_argument(
        "--force-repair",
        action="store_true",
        help="Skip verification, remove bond and re-pair",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output for debugging",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{TOOL_NAME} v{VERSION}",
    )
    return parser.parse_args(argv)


def validate_mac(mac: str) -> str:
    """Validates and normalizes a MAC address.

    Args:
        mac: The MAC address string to validate.

    Returns:
        The MAC address in uppercase format.

    Raises:
        SystemExit: If the MAC address is invalid.
    """
    if not MAC_PATTERN.match(mac):
        print(f"Error: Invalid MAC address: {mac}", file=sys.stderr)
        print("Expected format: AA:BB:CC:DD:EE:FF", file=sys.stderr)
        sys.exit(ExitCode.PAIRING_FAILED)
    return mac.upper()


def configure_logging(verbose: bool) -> None:
    """Configures the logging module.

    Args:
        verbose: When True, sets log level to DEBUG.
    """
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    """CLI entry point for meshcore-ble-connect."""
    args = parse_args()
    mac = validate_mac(args.mac)
    configure_logging(args.verbose)

    # Validate mutually exclusive flags
    if args.check_only and args.force_repair:
        print(
            "Error: --check-only and --force-repair are mutually exclusive",
            file=sys.stderr,
        )
        sys.exit(ExitCode.PAIRING_FAILED)

    # Create the appropriate PIN provider
    output = OutputFormatter(verbose=args.verbose)
    if args.pin is not None:
        pin_provider = StaticPinProvider(args.pin)
    else:
        pin_provider = InteractivePinProvider(output)

    # Create and run the application
    app = BleConnectApp(
        mac=mac,
        pin_provider=pin_provider,
        force_repair=args.force_repair,
        check_only=args.check_only,
        verbose=args.verbose,
    )

    exit_code = asyncio.run(app.run())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
