# Technical Reference — meshcore-ble-connect

## Architecture Overview

meshcore-ble-connect is structured as a layered system where a single orchestrator (`BleConnectApp`) coordinates specialized managers that each own one D-Bus responsibility. All BlueZ communication goes through `dbus-fast` on the system bus — no GATT libraries are used.

```
┌──────────────────────────────────────────────────┐
│                  BleConnectApp                    │
│              (orchestrator — §4 flow)             │
├──────────┬──────────┬──────────┬─────────────────┤
│ Adapter  │ Device   │Discovery │  PairingAgent   │
│ Manager  │ Manager  │          │  (Agent1)       │
├──────────┴──────────┴──────────┴─────────────────┤
│                  BusConnection                    │
│              (dbus-fast system bus)               │
├──────────────────────────────────────────────────┤
│                BlueZ (D-Bus)                      │
└──────────────────────────────────────────────────┘
```

## Class Diagram

```
PinProvider (Protocol)
├── StaticPinProvider      — pre-configured PIN (--pin flag)
└── InteractivePinProvider — stdin prompt (getpass)

BusConnection              — D-Bus system bus lifecycle
AdapterManager             — Adapter1: powered, pairable, version
DeviceManager              — Device1: exists, paired, verify, pair, trust, remove
Discovery                  — Adapter1.StartDiscovery + InterfacesAdded signal
PairingAgent               — Agent1: RequestPasskey/RequestPinCode (ServiceInterface)
OutputFormatter            — structured CLI output (§6.3 format)
BleConnectApp              — orchestrates all components (§4 flowchart)

ExitCode (IntEnum)         — exit codes 0-4
BleConnectError            — exception hierarchy base
├── AdapterError           → ExitCode.ADAPTER_ERROR (3)
├── PairingError           → ExitCode.PAIRING_FAILED (2)
├── DiscoveryError         → ExitCode.PAIRING_FAILED (2)
├── BondVerificationError  — (handled internally, triggers re-pair)
└── DbusPermissionError    → ExitCode.DBUS_PERMISSION (4)
```

## Component Responsibilities

### BleConnectApp (`app.py`)

**Single responsibility:** Orchestrates the connection management flow.

Implements the flowchart from design §4. Receives all dependencies via constructor injection. Translates exceptions from child components into exit codes.

Does not perform any D-Bus calls directly — all BlueZ interaction is delegated to the managers.

### AdapterManager (`adapter.py`)

**Single responsibility:** Bluetooth adapter state management.

Owns `Adapter1.Powered` and `Adapter1.Pairable` via the D-Bus Properties interface. Also reads BlueZ version for informational output. All operations are idempotent.

### DeviceManager (`device.py`)

**Single responsibility:** Device-level D-Bus operations.

Handles the full device lifecycle: existence check, paired/trusted status, bond verification (test connect), pairing with PIN agent, trust configuration, and device removal.

All critical D-Bus operations use direct `Message` calls instead of proxy introspection, because BlueZ does not always expose all interfaces via introspection XML (a known issue with `AgentManager1` and device object paths).

Key implementation details:

- `device_exists()` uses `GetManagedObjects()` to verify the device is a real managed object with `Device1` interface, rather than relying on proxy introspection which returns false positives.
- `pair()` establishes a BLE L2CAP connection via `Device1.Connect()` before calling `Device1.Pair()`. BLE SMP pairing requires an active connection; without it, BlueZ falls back to BR/EDR paging which fails on BLE-only devices.
- Connect retries with progressive backoff handle `le-connection-abort-by-local` (RF timing race after discovery).
- `remove()` uses a direct D-Bus message to `Adapter1.RemoveDevice`.

### Discovery (`discovery.py`)

**Single responsibility:** Finding a BLE device by MAC address.

Sets `SetDiscoveryFilter({'Transport': 'le'})` to ensure BLE-only scanning, then uses `Adapter1.StartDiscovery()` and listens for the `ObjectManager.InterfacesAdded` signal filtered by the target device path. After the device is found and `StopDiscovery` is called, a settle delay (2s) allows BlueZ to fully release scan state before the subsequent `Connect()` call.

### PairingAgent (`agent.py`)

**Single responsibility:** Responding to BlueZ pairing requests during BLE SMP and legacy BR/EDR pairing.

Implements `org.bluez.Agent1` via `dbus-fast.ServiceInterface` with capability `KeyboardDisplay`. Methods: `RequestPasskey` (returns PIN as uint32 for BLE SMP), `RequestPinCode` (returns PIN as string for legacy BR/EDR), `DisplayPasskey`, `RequestConfirmation`, `AuthorizeService` (auto-accept), and `Release`. This covers all pairing scenarios BlueZ may initiate.

### PinProvider (`pin.py`)

**Single responsibility:** Abstracting PIN acquisition.

Protocol with two implementations:
- `StaticPinProvider`: returns a pre-configured PIN (for `--pin` flag, systemd)
- `InteractivePinProvider`: prompts on stdin via `getpass`

The protocol enables Dependency Inversion: `BleConnectApp` depends on the abstraction, not on the input mechanism.

### BusConnection (`bus.py`)

**Single responsibility:** D-Bus system bus lifecycle.

Creates and holds the `MessageBus` connection. Provides `get_proxy()` for creating BlueZ proxy objects. Centralizes connection error handling (permissions).

### OutputFormatter (`output.py`)

**Single responsibility:** CLI output formatting.

Produces the aligned key-value output defined in design §6.3. Separates presentation from business logic. Supports verbose mode for debug output.

## Data Flow

### Normal flow (bond exists and is valid)

```
__main__.main()
  → parse_args()
  → BleConnectApp(mac, pin_provider, ...)
  → app.run()
    → BusConnection.connect()
    → AdapterManager.ensure_powered()      — D-Bus: Properties.Get(Adapter1.Powered)
    → AdapterManager.ensure_pairable()     — D-Bus: Properties.Get(Adapter1.Pairable)
    → DeviceManager.device_exists()        — D-Bus: GetManagedObjects (direct Message)
    → DeviceManager.is_paired()            — D-Bus: Properties.Get(Device1.Paired)
    → DeviceManager.verify_bond()          — D-Bus: Device1.Connect() + Disconnect()
    → DeviceManager.trust()                — D-Bus: Properties.Set(Device1.Trusted)
    → return ExitCode.OK
```

### Pairing flow (no bond or invalid bond)

```
__main__.main()
  → BleConnectApp.run()
    → [adapter checks — same as above]
    → DeviceManager.device_exists()        — not found (or bond invalid → remove)
    → PinProvider.get_pin()                — stdin prompt or --pin value
    → Discovery.discover()                 — D-Bus: SetDiscoveryFilter(le) + StartDiscovery + InterfacesAdded
    → PairingAgent registered on bus       — D-Bus: export Agent1 + RegisterAgent (direct Message)
    → DeviceManager.pair(agent)            — D-Bus: Connect() → Pair() → Agent1.RequestPasskey
    → DeviceManager.trust()                — D-Bus: Properties.Set(Device1.Trusted)
    → return ExitCode.OK
```

## D-Bus Interfaces Used

| Interface | Operations | Component |
|-----------|-----------|-----------|
| `org.bluez.Adapter1` | `StartDiscovery`, `StopDiscovery`, `SetDiscoveryFilter`, `RemoveDevice` | AdapterManager, Discovery, DeviceManager |
| `org.bluez.Device1` | `Connect`, `Pair`, `Disconnect` | DeviceManager |
| `org.bluez.Agent1` | `RequestPasskey`, `RequestPinCode`, `DisplayPasskey`, `RequestConfirmation`, `AuthorizeService`, `Release` (implemented) | PairingAgent |
| `org.bluez.AgentManager1` | `RegisterAgent`, `UnregisterAgent` (direct Message) | DeviceManager |
| `org.freedesktop.DBus.Properties` | `Get`, `Set` | AdapterManager, DeviceManager |
| `org.freedesktop.DBus.ObjectManager` | `GetManagedObjects`, `InterfacesAdded` (signal) | DeviceManager, Discovery |

## SOLID Compliance

| Principle | Implementation |
|-----------|---------------|
| **Single Responsibility** | Each class has exactly one reason to change (see Component Responsibilities above) |
| **Open/Closed** | `PinProvider` Protocol allows new providers without modifying `BleConnectApp` |
| **Liskov Substitution** | `StaticPinProvider` and `InteractivePinProvider` are interchangeable |
| **Interface Segregation** | `PairingAgent` implements only the two methods needed; adapter and device management are separate classes |
| **Dependency Inversion** | `BleConnectApp` depends on `PinProvider` Protocol, not concrete implementations |

## Error Handling Strategy

Exceptions propagate upward to `BleConnectApp.run()`, which catches them by type and maps to exit codes:

```
DbusPermissionError  → ExitCode.DBUS_PERMISSION (4)
AdapterError         → ExitCode.ADAPTER_ERROR (3)
PairingError         → ExitCode.PAIRING_FAILED (2)
DiscoveryError       → ExitCode.PAIRING_FAILED (2)
BleConnectError      → ExitCode.PAIRING_FAILED (2)  [fallback]
Exception            → ExitCode.PAIRING_FAILED (2)  [unexpected]
```

`BondVerificationError` is handled internally by the orchestrator (triggers re-pair flow) and does not propagate to exit codes.

## Design Decisions

1. **D-Bus only, no bleak** — Pairing is an OS-level concern. Using D-Bus directly avoids the abstraction mismatch of GATT libraries trying to manage bonds.

2. **Bond verification via test connect** — `Device1.Connect()` is the most reliable way to check if the remote device still recognizes the bond. Property checks (`.Paired`) only reflect the local state.

3. **Idempotent steps** — Every step checks its precondition before acting. This makes the tool safe to run on every boot or as a retry mechanism.

4. **PIN agent on D-Bus, not in application** — The agent is registered and unregistered within a single pairing operation. This avoids long-lived agent processes.

5. **Separated adapter/device management** — Although both use D-Bus Properties, they operate on different object paths and have different failure modes. Keeping them separate follows Single Responsibility.

6. **Protocol for PinProvider** — Enables non-interactive operation (systemd) and interactive operation (terminal) through the same orchestration code, without conditional logic in the app.

7. **Direct Message calls over proxy introspection** — BlueZ does not consistently expose all D-Bus interfaces via introspection XML across versions. AgentManager1, Device1.Connect, and Device1.Pair all use direct `dbus_fast.Message` calls, bypassing introspection entirely. This matches the approach used by the bleak library.

8. **BLE Connect-then-Pair sequence** — Per BLE specification, SMP pairing runs over an existing L2CAP connection. Calling `Device1.Pair()` without an active connection causes BlueZ to attempt BR/EDR paging, which fails on BLE-only devices with "Page Timeout".
