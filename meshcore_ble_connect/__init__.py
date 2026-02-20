"""meshcore-ble-connect — Standalone BLE Connection Manager.

Ensures a BLE bond is established via D-Bus before any application
starts. Independent of bleak or any GATT library.
"""

from .constants import VERSION

__version__ = VERSION
