# meshcore-ble-connect

Standalone BLE Connection Manager — ensures a BLE bond is established via D-Bus before your application starts.

## Purpose

Applications that communicate with BLE devices should not manage pairing themselves. `meshcore-ble-connect` handles all pairing and bonding via D-Bus, so your application can assume a valid bond is already present.

Key properties:

- **Standalone** — independent of any application; usable by scripts, GUIs, or systemd services
- **D-Bus only** — communicates with BlueZ exclusively via D-Bus (no bleak, no GATT libraries)
- **Idempotent** — safe to run multiple times; skips steps that are already satisfied
- **Bond verification** — detects stale bonds (device rebooted) and re-pairs automatically
- **BlueZ version independent** — works across BlueZ 5.66, 5.72, 5.82+

## Requirements

- Python 3.10+
- BlueZ (any version with D-Bus support)
- D-Bus system bus access (root or `bluetooth` group membership)
- `dbus-fast` (installed automatically)

## Installation

meshcore-ble-connect is called as a subprocess, not imported as a Python module. It can be installed anywhere as long as the binary is in your PATH.

```bash
git clone https://github.com/pe1hvh/meshcore-ble-connect.git
cd meshcore-ble-connect
```

**Option 1: In your application's existing virtualenv** (simplest)

```bash
source ~/my-app/.venv/bin/activate
pip install .
```

**Option 2: In its own virtualenv** (cleanest separation)

```bash
python -m venv .venv
source .venv/bin/activate
pip install .
```

**Option 3: System-wide** (always in PATH)

```bash
sudo pip install .
```

Verify the installation:

```bash
meshcore-ble-connect --version
```

## Usage

```bash
# Normal use — verifies bond, prompts for PIN only when needed
meshcore-ble-connect AA:BB:CC:DD:EE:FF

# Non-interactive — provide PIN upfront (for systemd / scripts)
meshcore-ble-connect AA:BB:CC:DD:EE:FF --pin 123456

# Check if bond exists and is valid (no pairing, no prompt)
meshcore-ble-connect AA:BB:CC:DD:EE:FF --check-only

# Skip verify, remove bond and re-pair
meshcore-ble-connect AA:BB:CC:DD:EE:FF --force-repair

# Non-interactive force repair
meshcore-ble-connect AA:BB:CC:DD:EE:FF --force-repair --pin 123456

# Verbose output for debugging
meshcore-ble-connect AA:BB:CC:DD:EE:FF --verbose
```

## Exit Codes

| Code | Meaning |
|------|---------|
| `0`  | Bond verified — ready for application |
| `1`  | Bond not present or invalid (`--check-only` was used) |
| `2`  | Pairing failed (wrong PIN, device unreachable) |
| `3`  | Adapter problem (not powered, not found) |
| `4`  | D-Bus permission error |

## Project Structure

```
meshcore-ble-connect/
├── meshcore_ble_connect/
│   ├── __init__.py          # Package metadata
│   ├── __main__.py          # CLI entry point, argument parsing
│   ├── app.py               # Orchestrator (main flow)
│   ├── adapter.py           # Bluetooth adapter management
│   ├── device.py            # Device operations (pair, trust, verify, remove)
│   ├── discovery.py         # BLE device discovery
│   ├── agent.py             # D-Bus PIN agent (Agent1)
│   ├── pin.py               # PIN provider abstraction
│   ├── bus.py               # D-Bus connection management
│   ├── output.py            # CLI output formatting
│   ├── constants.py         # Exit codes, version, D-Bus constants
│   └── exceptions.py        # Custom exceptions
├── systemd/
│   └── meshcore-ble-connect.service
├── docs/
│   ├── DESIGN.md            # Design document
│   ├── USER_REFERENCE.md    # User documentation
│   ├── TECHNICAL_REFERENCE.md
│   └── DEVELOPER_INTEGRATION.md  # Integration guide for developers
├── README.md
├── requirements.txt
├── pyproject.toml
└── .gitignore
```

## Systemd Deployment

See `systemd/meshcore-ble-connect.service` for the service template. Update the paths, MAC address, and PIN for your deployment.

Your application declares a dependency on the bond service:

```ini
[Unit]
After=meshcore-ble-connect.service
Requires=meshcore-ble-connect.service
```

## Documentation

- [User Reference](docs/USER_REFERENCE.md) — complete CLI documentation with examples
- [Technical Reference](docs/TECHNICAL_REFERENCE.md) — architecture, classes, data flow
- [Developer Integration](docs/DEVELOPER_INTEGRATION.md) — how to call from your application (Python, Bash, systemd, other languages)
- [Design Document](docs/DESIGN.md) — original design and rationale

## Changelog

### v1.0.0 — Initial Release

- Complete BLE bond management flow via D-Bus
- All D-Bus operations use direct `Message` calls instead of proxy introspection, matching the approach of the bleak library
- BLE SMP pairing with `Connect()` before `Pair()` for correct BLE transport
- Full Agent1 interface: `RequestPasskey` (BLE SMP), `RequestPinCode` (legacy BR/EDR), `DisplayPasskey`, `RequestConfirmation`, `AuthorizeService`
- BLE transport filter (`SetDiscoveryFilter({'Transport': 'le'})`)
- Connect retry logic with progressive backoff for `le-connection-abort-by-local`
- Bond verification with test connect
- Stale device cleanup (removes "known but not paired" state before discovery)
- Device existence check via `GetManagedObjects()` for reliability
- CLI with `--check-only`, `--force-repair`, `--verbose` flags
- Systemd service template

## License

MIT
