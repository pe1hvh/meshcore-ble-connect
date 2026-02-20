# User Reference — meshcore-ble-connect

## Overview

`meshcore-ble-connect` is a command-line tool that manages BLE (Bluetooth Low Energy) bonds via D-Bus. It ensures your BLE device is paired, trusted, and ready before your application starts.

Run it once before launching your BLE application, or deploy it as a systemd service for automatic boot-time pairing.

## Installation

### From source

```bash
git clone https://github.com/user/meshcore-ble-connect.git
cd meshcore-ble-connect
python -m venv .venv
source .venv/bin/activate
pip install .
```

### Verify installation

```bash
meshcore-ble-connect --version
```

### Prerequisites

- Python 3.10 or newer
- BlueZ installed and running (`systemctl status bluetooth`)
- Permission to access D-Bus system bus — either run as root or add your user to the `bluetooth` group:
  ```bash
  sudo usermod -aG bluetooth $USER
  ```

## Command Reference

```
meshcore-ble-connect [-h] [--pin PIN] [--check-only] [--force-repair] [--verbose] [--version] MAC
```

### Positional arguments

| Argument | Description |
|----------|-------------|
| `MAC`    | Target device MAC address in `AA:BB:CC:DD:EE:FF` format |

### Optional arguments

| Flag | Description |
|------|-------------|
| `--pin PIN` | Provide PIN upfront for non-interactive operation |
| `--check-only` | Check if a valid bond exists, without attempting to pair |
| `--force-repair` | Remove any existing bond and re-pair from scratch |
| `--verbose` | Show detailed debug output |
| `--version` | Print version and exit |
| `-h`, `--help` | Show help message |

**Note:** `--check-only` and `--force-repair` are mutually exclusive.

## Common Scenarios

### First-time pairing

The device has never been paired. The tool discovers the device, asks for a PIN, and establishes the bond.

```
$ meshcore-ble-connect AA:BB:CC:DD:EE:FF
meshcore-ble-connect v1.0.0
BlueZ:    5.82
Adapter:  hci0 (powered, pairable)
Device:   AA:BB:CC:DD:EE:FF
Bond:     not found — pairing required
Enter PIN: ******
Agent:    registered
Pairing:  success
Trusted:  set
Result:   ✅ Bond established — ready to connect
```

### Existing valid bond

The device was previously paired and the bond is still valid. The tool verifies with a test connect and exits immediately — no PIN needed.

```
$ meshcore-ble-connect AA:BB:CC:DD:EE:FF
meshcore-ble-connect v1.0.0
BlueZ:    5.82
Adapter:  hci0 (powered, pairable)
Device:   AA:BB:CC:DD:EE:FF
Bond:     found (paired + trusted)
Verify:   test connect OK
Result:   ✅ Bond verified — ready to connect
```

### Device rebooted with new PIN

The bond exists in BlueZ, but the device lost its side. The tool detects this, removes the stale bond, and re-pairs.

```
$ meshcore-ble-connect AA:BB:CC:DD:EE:FF
meshcore-ble-connect v1.0.0
BlueZ:    5.82
Adapter:  hci0 (powered, pairable)
Device:   AA:BB:CC:DD:EE:FF
Bond:     found (paired + trusted)
Verify:   test connect FAILED — bond is invalid
Cleanup:  removed invalid bond
Enter PIN: ******
Agent:    registered
Pairing:  success
Trusted:  set
Result:   ✅ Bond established — ready to connect
```

### Force repair

You know the bond is bad and want to skip verification. The `--force-repair` flag removes the device immediately.

```
$ meshcore-ble-connect AA:BB:CC:DD:EE:FF --force-repair
meshcore-ble-connect v1.0.0
BlueZ:    5.82
Adapter:  hci0 (powered, pairable)
Device:   AA:BB:CC:DD:EE:FF
Mode:     force-repair
Cleanup:  removed existing bond
Enter PIN: ******
Agent:    registered
Pairing:  success
Trusted:  set
Result:   ✅ Re-paired — ready to connect
```

### Non-interactive pairing (scripts / systemd)

Use `--pin` to provide the PIN without interactive prompts:

```bash
meshcore-ble-connect AA:BB:CC:DD:EE:FF --pin 123456
```

### Bond status check

Use `--check-only` to test if a valid bond exists without modifying anything:

```bash
meshcore-ble-connect AA:BB:CC:DD:EE:FF --check-only
echo $?  # 0 = valid bond, 1 = no valid bond
```

## Exit Codes

| Code | Meaning | Typical action |
|------|---------|----------------|
| `0`  | Bond verified — ready for application | Proceed with your app |
| `1`  | No valid bond (`--check-only` mode) | Run without `--check-only` to pair |
| `2`  | Pairing failed | Check PIN, check if device is on |
| `3`  | Adapter problem | Check `systemctl status bluetooth` |
| `4`  | D-Bus permission error | Run as root or join `bluetooth` group |

## Systemd Deployment

### Bond service

Copy and edit the provided service template:

```bash
sudo cp systemd/meshcore-ble-connect.service /etc/systemd/system/
sudo systemctl edit meshcore-ble-connect.service  # update paths, MAC, PIN
sudo systemctl enable meshcore-ble-connect.service
```

### Application dependency

Your application's service file declares a dependency:

```ini
[Unit]
Description=My BLE Application
After=meshcore-ble-connect.service
Requires=meshcore-ble-connect.service

[Service]
ExecStart=/path/to/your/app

[Install]
WantedBy=multi-user.target
```

### Boot sequence

1. systemd starts `meshcore-ble-connect.service`
   - Bond exists and valid? → exit 0 (instant)
   - No bond? → pair with configured PIN → exit 0
2. systemd starts your application service
   - Application connects to the device (bond is already present)

## Troubleshooting

### "D-Bus permission error" (exit code 4)

You need system bus access. Either run as root or add yourself to the bluetooth group:
```bash
sudo usermod -aG bluetooth $USER
# Log out and back in for the group change to take effect
```

### "Adapter problem" (exit code 3)

Check that Bluetooth is enabled:
```bash
systemctl status bluetooth
sudo bluetoothctl power on
```

### "Device not found" during pairing (exit code 2)

Make sure the device is powered on and advertising. Use `--verbose` to see discovery progress:
```bash
meshcore-ble-connect AA:BB:CC:DD:EE:FF --verbose
```

### "Pairing failed" (exit code 2)

The most common cause is a wrong PIN. If the device rebooted and generated a new PIN, use `--force-repair`:
```bash
meshcore-ble-connect AA:BB:CC:DD:EE:FF --force-repair
```

## FAQ

**Q: Does this replace bleak?**
No. `meshcore-ble-connect` handles pairing/bonding only. Your application still uses bleak (or any GATT library) for data communication after the bond is established.

**Q: Can I use this with devices other than MeshCore?**
Yes, as long as the device uses static PIN-based pairing. The agent only implements `RequestPinCode`.

**Q: What happens if I run it twice?**
Nothing bad — the tool is idempotent. If the bond is already valid, it verifies and exits immediately.

**Q: Does it work without BlueZ?**
No. The tool communicates exclusively with BlueZ via D-Bus.
