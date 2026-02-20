# meshcore-ble-connect — Developer Integration Manual

> Version 1.0.0 — February 2026

## 1. Overview

meshcore-ble-connect is a standalone BLE bond manager that communicates with BlueZ via D-Bus. It guarantees that a BLE bond is present and valid before your application starts. It is designed to be called by other programs, not imported as a Python module.

**Core principle:** call as a subprocess, never import as a Python module. The tool has its own D-Bus connection and async event loop. Mixing two D-Bus connections in one process leads to conflicts.

### 1.1 What it does

- Checks whether a BLE bond exists for the given MAC address
- Verifies the bond is valid (test connect to the device)
- Automatically pairs if no bond exists (BLE discovery + SMP pairing with PIN)
- Automatically repairs if the bond is corrupt or expired
- Returns an exit code your program can evaluate

### 1.2 What it does not do

- No GATT communication — it does not open services or characteristics
- No long-running process — it runs, checks/pairs, and exits
- No bleak dependency — it works purely via D-Bus (dbus-fast)

## 2. Installation

meshcore-ble-connect can be installed in the same virtualenv as your application or system-wide.

### 2.1 In an existing virtualenv

```bash
cd ~/meshcore-ble-connect
source ~/my-app/.venv/bin/activate
pip install .
```

### 2.2 System-wide

```bash
cd ~/meshcore-ble-connect
sudo pip install .
```

### 2.3 Verification

```bash
meshcore-ble-connect --version
# Output: meshcore-ble-connect 1.0.0
```

### 2.4 System requirements

- Python 3.10+
- BlueZ (any version with D-Bus support)
- D-Bus system bus access (root or membership of the `bluetooth` group)
- dbus-fast (installed automatically as dependency)

## 3. CLI interface

The tool is invoked with a MAC address as the first argument and optional flags.

### 3.1 Syntax

```bash
meshcore-ble-connect <MAC> [options]
```

### 3.2 Options

| Option | Description |
|--------|-------------|
| `--pin <PIN>` | Provide PIN non-interactively. Without this option, the tool prompts on stdin. |
| `--check-only` | Only check if a bond exists. No pairing, no prompt. Exit 0 = bond OK, exit 1 = no bond. |
| `--force-repair` | Remove existing bond and re-pair from scratch. |
| `--verbose` | Verbose debug output. |
| `--version` | Show version number. |

### 3.3 Exit codes

These are the exit codes your program must evaluate:

| Code | Constant | Meaning |
|------|----------|---------|
| 0 | `OK` | Bond verified — ready for GATT communication |
| 1 | `NO_BOND` | No bond present (only with `--check-only`) |
| 2 | `PAIRING_FAILED` | Pairing failed (wrong PIN, device unreachable, timeout) |
| 3 | `ADAPTER_ERROR` | Bluetooth adapter not found or cannot be powered on |
| 4 | `DBUS_PERMISSION` | No access to D-Bus system bus (permissions issue) |

## 4. Python integration

### 4.1 Basic call (synchronous)

The simplest integration: `subprocess.run` with timeout.

```python
import subprocess
import logging

logger = logging.getLogger(__name__)

def ensure_ble_bond(mac: str, pin: str | None = None,
                    timeout: int = 60) -> bool:
    """Ensure BLE bond exists before GATT communication.

    Args:
        mac:     BLE MAC address (AA:BB:CC:DD:EE:FF)
        pin:     PIN code (None = interactive prompt)
        timeout: Maximum seconds to wait

    Returns:
        True if bond is verified and ready
    """
    cmd = ["meshcore-ble-connect", mac]
    if pin:
        cmd.extend(["--pin", pin])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        if result.returncode == 0:
            logger.info("BLE bond OK: %s", mac)
            return True

        logger.error("BLE bond failed (exit %d): %s",
                     result.returncode, result.stderr.strip())
        return False

    except FileNotFoundError:
        logger.warning("meshcore-ble-connect not installed")
        return True  # graceful degradation

    except subprocess.TimeoutExpired:
        logger.error("BLE bond timeout after %ds", timeout)
        return False
```

### 4.2 Asyncio integration

For applications with an asyncio event loop (NiceGUI, FastAPI, etc.). Use `asyncio.to_thread` to run the blocking subprocess call in a thread pool.

```python
import asyncio

async def ensure_ble_bond_async(mac: str, pin: str | None = None,
                                timeout: int = 60) -> bool:
    """Async wrapper — runs subprocess in thread pool."""
    return await asyncio.to_thread(
        ensure_ble_bond, mac, pin, timeout
    )
```

**Note:** `asyncio.to_thread` runs the function in the default `ThreadPoolExecutor`. This blocks one worker thread for up to the timeout period. For most applications this is not a problem.

### 4.3 Integration in a connect flow

Typical pattern: bond check before bleak connect, with error handling per exit code.

```python
from bleak import BleakClient

class BLEWorker:
    def __init__(self, address: str, pin: str | None = None):
        self.address = address
        self.pin = pin
        self.client: BleakClient | None = None

    async def connect(self) -> bool:
        """Connect to BLE device with bond verification."""

        # Step 1: ensure bond
        bond_ok = await ensure_ble_bond_async(
            self.address, self.pin
        )
        if not bond_ok:
            logger.error("Cannot proceed without BLE bond")
            return False

        # Step 2: open GATT connection
        try:
            self.client = BleakClient(self.address)
            await self.client.connect()
            return True
        except Exception as e:
            logger.error("GATT connect failed: %s", e)
            return False
```

### 4.4 Reconnect with re-bond

On a BLE disconnect (device reboot, out of range) the bond must be re-verified. The device may have a new identity resolving key after reboot, making the old bond invalid.

```python
    async def reconnect(self, max_retries: int = 5) -> bool:
        """Reconnect with bond re-verification."""
        for attempt in range(1, max_retries + 1):
            delay = min(2 ** attempt, 30)  # exponential backoff
            logger.info("Reconnect attempt %d/%d (wait %ds)",
                        attempt, max_retries, delay)
            await asyncio.sleep(delay)

            # Re-verify bond (handles stale bonds)
            bond_ok = await ensure_ble_bond_async(
                self.address, self.pin
            )
            if not bond_ok:
                continue

            # Bond OK — try GATT connect
            try:
                self.client = BleakClient(self.address)
                await self.client.connect()
                return True
            except Exception:
                continue

        return False
```

### 4.5 Graceful degradation

If meshcore-ble-connect is not installed, your application should continue to work. The bond then depends on existing BlueZ state (manually paired via bluetoothctl, or via another agent).

The `FileNotFoundError` handler in section 4.1 returns `True` when the tool is missing, allowing the connect flow to proceed.

Optionally, check at startup whether the tool is available and log a warning:

```python
import shutil

def check_ble_tool() -> bool:
    """Check if meshcore-ble-connect is available."""
    if shutil.which("meshcore-ble-connect") is None:
        logger.warning(
            "meshcore-ble-connect not found. "
            "BLE bond management is disabled. "
            "Install with: pip install meshcore-ble-connect"
        )
        return False
    return True
```

## 5. Bash integration

### 5.1 In a startup script

```bash
#!/bin/bash
MAC="AA:BB:CC:DD:EE:FF"
PIN="123456"

# Ensure bond before application start
meshcore-ble-connect "$MAC" --pin "$PIN"
rc=$?

case $rc in
  0) echo "Bond OK, starting app..."
     python my_app.py "$MAC" ;;
  2) echo "Pairing failed" >&2; exit 1 ;;
  3) echo "Bluetooth adapter error" >&2; exit 1 ;;
  4) echo "Permission denied" >&2; exit 1 ;;
  *) echo "Unknown error ($rc)" >&2; exit 1 ;;
esac
```

### 5.2 Bond check only (no pairing)

```bash
# Check if bond already exists
meshcore-ble-connect "$MAC" --check-only
if [ $? -eq 0 ]; then
    echo "Bond exists"
else
    echo "No bond — pairing needed"
    meshcore-ble-connect "$MAC" --pin "$PIN"
fi
```

## 6. Systemd integration

For headless deployment (Raspberry Pi, NAS) you can run meshcore-ble-connect as a systemd service that your application depends on.

### 6.1 Bond service

```ini
# /etc/systemd/system/meshcore-ble-connect.service
[Unit]
Description=MeshCore BLE Bond Manager
After=bluetooth.target
Requires=bluetooth.target

[Service]
Type=oneshot
RemainAfterExit=yes
User=<user>
ExecStart=/home/<user>/.venv/bin/meshcore-ble-connect \
    AA:BB:CC:DD:EE:FF --pin 123456

[Install]
WantedBy=multi-user.target
```

### 6.2 Application service (dependency)

```ini
# /etc/systemd/system/my-app.service
[Unit]
Description=My BLE Application
After=meshcore-ble-connect.service
Requires=meshcore-ble-connect.service

[Service]
Type=simple
User=<user>
WorkingDirectory=/home/<user>/my-app
ExecStart=/home/<user>/my-app/.venv/bin/python app.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 6.3 Activation

```bash
sudo systemctl daemon-reload
sudo systemctl enable meshcore-ble-connect.service
sudo systemctl enable my-app.service
sudo systemctl start my-app.service
```

The bond service runs once at boot (`Type=oneshot`). Your application only starts after exit code 0 is returned. On failure, your application does not start.

## 7. Integration from other languages

meshcore-ble-connect is a CLI tool. Any language that can spawn a subprocess and read exit codes can use it.

### 7.1 Node.js

```javascript
const { execFileSync } = require("child_process");

function ensureBleBond(mac, pin) {
  try {
    execFileSync("meshcore-ble-connect", [mac, "--pin", pin], {
      timeout: 60000,
    });
    return true;
  } catch (err) {
    console.error(`Bond failed: exit ${err.status}`);
    return false;
  }
}
```

### 7.2 C / C++

```c
#include <stdlib.h>

int ensure_ble_bond(const char *mac, const char *pin) {
    char cmd[256];
    snprintf(cmd, sizeof(cmd),
        "meshcore-ble-connect %s --pin %s", mac, pin);
    int rc = system(cmd);
    return WEXITSTATUS(rc);  /* 0 = OK */
}
```

### 7.3 Rust

```rust
use std::process::Command;

fn ensure_ble_bond(mac: &str, pin: &str) -> bool {
    let status = Command::new("meshcore-ble-connect")
        .args(&[mac, "--pin", pin])
        .status()
        .expect("failed to run meshcore-ble-connect");
    status.success()
}
```

## 8. Error handling

### 8.1 Exit code mapping

Translate exit codes to user-friendly messages:

| Code | Cause | Recommended action |
|------|-------|--------------------|
| 0 | Bond OK | Proceed with GATT connect |
| 2 | Wrong PIN, device off, timeout | Show error, retry with backoff |
| 3 | Adapter not found or off | Show "Bluetooth adapter problem" |
| 4 | No D-Bus permissions | Show "Insufficient permissions, run as root or add to bluetooth group" |

### 8.2 Stderr output

On failure, meshcore-ble-connect writes diagnostic information to stderr. Log this at DEBUG level for troubleshooting:

```python
if result.returncode != 0:
    for line in result.stderr.strip().splitlines():
        logger.debug("ble-connect: %s", line)
```

### 8.3 Timeout scenarios

The default timeout of 60 seconds is sufficient for discovery (30s) plus pairing (a few seconds). Increase the timeout if the device is far away or the RF environment is busy:

```python
# Longer timeout for difficult RF environments
ensure_ble_bond(mac, pin, timeout=120)
```

## 9. Best practices

1. Call meshcore-ble-connect before every bleak/GATT connect — it is idempotent and fast when the bond is already valid (< 2 seconds).
2. Use `--pin` for non-interactive environments (systemd, cron, headless). Without `--pin` the tool waits for stdin input.
3. Implement graceful degradation — if the tool is not installed, proceed with bleak only. Log a warning.
4. Log stderr output at DEBUG level — this is essential for production troubleshooting.
5. Use exponential backoff on reconnect — give the device and Bluetooth stack time to recover.
6. Do not hardcode the PIN — use environment variables (`MESHCORE_BLE_PIN`) or a config file.
7. bt-agent is no longer needed — meshcore-ble-connect replaces the entire PIN/bond lifecycle.

## 10. Troubleshooting

### 10.1 Common problems

| Symptom | Cause | Solution |
|---------|-------|----------|
| `FileNotFoundError` | Tool not installed or not in PATH | `pip install .` in the correct venv |
| Exit code 4 | D-Bus permissions | `sudo usermod -aG bluetooth $USER` |
| Exit code 3 | Adapter off or not found | `sudo hciconfig hci0 up` |
| Exit code 2 (timeout) | Device not nearby | Verify device is powered on and within range |
| Exit code 2 (wrong PIN) | PIN mismatch | Check PIN on the device (MeshCore app) |
| Bond OK but bleak fails | GATT caching issue | `bluetoothctl remove MAC`, then retry |

### 10.2 Debug mode

```bash
# Manual test with verbose output
meshcore-ble-connect AA:BB:CC:DD:EE:FF --pin 123456 --verbose

# Expected output on success:
# Tool         : meshcore-ble-connect 1.0.0
# Adapter      : hci0 (powered)
# Target       : AA:BB:CC:DD:EE:FF
# Discovery    : device found
# Connect      : connected (retry 2)
# Agent        : Passkey 123456
# Pairing      : success
# Trusted      : set
# Result       : ✅ Bond established
```
