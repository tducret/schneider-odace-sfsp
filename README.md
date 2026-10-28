# Schneider Odace SFSP → Home Assistant

Control a Schneider Odace SFSP Bluetooth receiver directly from Home Assistant,
using the Raspberry Pi's built-in Bluetooth. No Theengs code, MQTT, cloud service,
or additional transmitter is needed.

The receiver must first be **paired and bonded with the Pi**. Your existing
physical switch continues to work independently.

## Requirements

- Home Assistant OS on a Raspberry Pi with a working Bluetooth adapter.
- Home Assistant's **Bluetooth** integration enabled.
- The **Terminal & SSH** add-on, with `bluetoothctl` and access to BlueZ over
  D-Bus. The standard add-on worked in the setup tested here.
- Safe access to the receiver's **PRESS** button for pairing.
- A file-transfer method for HA's `/config` directory, such as Samba or
  Studio Code Server.

Only press the receiver button if you can do so without touching exposed mains
wiring. Do not hold the button, reset the receiver, or remove existing pairings.

## 1. Check the Pi's Bluetooth adapter

Open the Terminal & SSH add-on and run:

```sh
bluetoothctl --version
bluetoothctl list
bluetoothctl show
```

Check that a controller is listed and `Powered: yes` is shown. In HA, also check
**Settings → Devices & services → Bluetooth** for a working adapter.

Add-on terminal access is not the same as HAOS host access. This procedure uses
BlueZ's D-Bus interface; it does not require raw Bluetooth tools or host debug SSH.

## 2. Identify your receiver

Start the interactive tool:

```sh
bluetoothctl
```

Inside it, enter:

```text
scan on
```

Wait for a receiver named `MOD GENERIC - <serial>` to appear. Record its
**Bluetooth address**, not the Pi controller's address and not the physical
switch's address.

Example values below are **synthetic placeholders**, not real device identities.
The model and firmware describe the hardware tested during development.

| Item | Value |
| --- | --- |
| Advertised name (example) | `MOD GENERIC - 123456` |
| Bluetooth address (example) | `AA:BB:CC:DD:EE:FF` |
| Device Information model | `Mod_generic_App_Module` |
| Firmware | `001.002.001` |

**Replace `AA:BB:CC:DD:EE:FF` throughout this guide with your receiver's address.**
If several receivers appear, confirm which one you intend to control. Signal
strength is a clue, not proof of identity. After connection, the name may shorten
to `MOD_GENERIC`.

## 3. Pair and bond the receiver with the Pi

Keep `bluetoothctl` open. **Enter commands individually, waiting for each prompt**;
pasting multiple lines at once skipped commands during testing.

```text
agent on
default-agent
```

Briefly press the receiver's **PRESS** button. On the tested receiver, its LED
flashed red/green to indicate pairing mode. While it is flashing, run:

```text
pair AA:BB:CC:DD:EE:FF
```

Accept any pairing confirmation for this receiver. Wait for pairing to finish,
then inspect it:

```text
info AA:BB:CC:DD:EE:FF
```

The important results are:

```text
Paired: yes
Bonded: yes
```

`Connected: yes` alone does **not** confirm pairing. `Trusted: no` did not prevent
control in our tests; setting trust was not required.

Pairing must be performed on the **Pi that runs HA**. A bond made on a Mac or
phone does not transfer to the Pi or to an ESPHome Bluetooth proxy.

## 4. Verify on/off control before installing the integration

These commands really operate the connected load. Use them only after confirming
you have selected your intended receiver.

In the same `bluetoothctl` session, enter each line separately:

```text
scan off
menu gatt
select-attribute 720a9081-9c7d-11e5-a7e3-0002a5d5c51b
write "0x00"
```

The light should turn **off**. If selecting the characteristic fails, stop rather
than writing to another characteristic.

Then run:

```text
write "0x01"
```

The light should turn **on**. If both work, finish the manual session:

```text
back
disconnect AA:BB:CC:DD:EE:FF
quit
```

Disconnecting does not remove the bond. **Do not use `remove`.**

## 5. Install the custom integration

Copy the following four files from this project into HA's configuration directory:

```text
/config/custom_components/odace_sfsp/
├── __init__.py
├── manifest.json
├── protocol.py
└── switch.py
```

For example, transfer the folder using Samba or Studio Code Server. No files need
to be installed on the HAOS host. Do not copy the Mac capture scripts or test
files into `custom_components`.

The integration uses HA's Bluetooth stack and the Bleak connection helper already
installed with HA Bluetooth. There is no additional package installation step.

## 6. Configure Home Assistant

Add this to `/config/configuration.yaml`:

```yaml
switch:
  - platform: odace_sfsp
    name: "Odace light"
    address: "AA:BB:CC:DD:EE:FF"
```

If you already have a `switch:` list, append the `- platform: odace_sfsp` entry
to it; **do not create a second top-level `switch:` key**. If your configuration
uses an included switches file, add the list entry there instead.

You do **not** need this section for receiver control:

```yaml
odace_sfsp:
  uid: "123456"
```

That is an optional physical-button listener, described below. Remove it unless
you also want those events. Removing it does not affect the physical switch's
existing pairing with the receiver.

Ensure HA's Bluetooth adapter entry is enabled. Check the configuration using
**Developer tools → YAML → Check configuration** (or `ha core check` in the
terminal), then **restart Home Assistant**. A YAML reload alone is not sufficient
for installing this platform.

This integration is configured through YAML; it does not have an **Add
Integration** dialog.

## 7. Use the switch

Find the new entity in **Developer tools → States**. With the example name, its
entity ID will normally be `switch.odace_light`; use the actual ID shown in HA.

Add it to a dashboard or use **Developer tools → Actions**:

```yaml
action: switch.turn_on
target:
  entity_id: switch.odace_light
```

Use `switch.turn_off` to turn it off, or `switch.toggle` to toggle based on HA's
current entity state.

Example automation, entered in the automation editor's YAML mode:

```yaml
alias: Turn on Odace light at sunset
triggers:
  - trigger: sun
    event: sunset
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.odace_light
mode: single
```

## State feedback and limitations

- Each command opens a BLE connection, writes on/off, then disconnects. The
  receiver must remain powered and within range of the Pi.
- After an acknowledged write, the entity initially shows the requested state.
  It then reconciles state from receiver advertisements, including changes made
  by the physical switch. A write acknowledgement is not independently measured
  confirmation that the load is powered.
- Immediate GATT readback was stale during testing, so it is not used for state.
- Receiver advertisements use manufacturer ID `0x02b6`, prefix `92 44`; the
  decoder reads on/off from payload byte 9, excluding the manufacturer ID.
  This interpretation is based on our captures and still needs live HA testing.
- Use the bonded Pi's local Bluetooth adapter for this setup. Bond credentials
  are not automatically shared with Bluetooth proxies.
- This version supports on/off, not dimming, timer configuration, or pairing
  through the HA UI.
- Direct on/off control and Pi pairing were verified on the actual receiver.
  Protocol unit tests pass, but the custom platform itself has not yet been
  verified inside a running Home Assistant instance. Other models and firmware
  versions may behave differently.

## Troubleshooting

### Receiver connects but does not pair

`Connected: yes` is not enough: check `Paired: yes` and `Bonded: yes`. Retry the
pair command while the receiver is in its documented pairing mode. Do not reset
it or remove its existing physical-switch pairing. Close other clients that
might be holding a connection.

### Receiver is not discovered in HA

Check that the Bluetooth integration is enabled, the receiver is powered and in
range, and the configured address belongs to the receiver. Close/disconnect any
manual `bluetoothctl`, Mac, or phone connection before testing HA control.

### Integration or entity does not appear

Verify the four files are directly in `/config/custom_components/odace_sfsp/`,
the YAML indentation is correct, and there is only one top-level `switch:` key.
Check configuration, restart HA, and inspect **Settings → System → Logs** for
`odace_sfsp` errors.

### Commands fail in the HA entity but work in bluetoothctl

Reconfirm that the Pi is still bonded and that no other client holds the
connection. Ensure HA is using the Pi's local adapter, not an unbonded proxy.
Inspect the HA logs before changing pairing or installing additional packages.

### Why not replay the battery-free switch?

We captured switch broadcasts and independently verified that the Pi replayed
the same manufacturer payload over the air. The receiver did not react, including
in a pairing-mode experiment. The original sender address was not reproduced,
and the purpose of the changing final six bytes is unknown. We have not proved
whether address filtering, authentication, or replay protection explains this.
Direct paired GATT control worked, so replay is not part of this installation.

HA's Bluetooth adapter was temporarily disabled during replay experiments to
resolve an advertising conflict. **That step is not required for this direct
control setup; leave HA Bluetooth enabled.**

## Optional: physical-switch button events

This is separate from receiver control and requires no pairing with the
battery-free switch. It emits events but does not create a button entity or
control the receiver by itself.

The tested switch was a Schneider S520104. These device-specific example values
are synthetic; replace the UID with your own:

| Item | Value |
| --- | --- |
| Model | Schneider S520104 |
| UID (example) | `123456` |
| Observed action | `toggle` (`0x02`) |
| Manufacturer payload prefix | `8e 44` (manufacturer ID `0x02b6`) |

Add to `configuration.yaml`, using your own switch's UID:

```yaml
odace_sfsp:
  uid: "123456"
```

Restart HA, listen to `odace_sfsp_button` in **Developer tools → Events**, then
press the physical switch. Expected event data includes:

```yaml
uid: "123456"
action: toggle
```

Repeated advertisements of the same action are suppressed until there has been
a 0.3-second gap. This is a heuristic, not a verified packet counter; rapid
presses may merge. Adjust `debounce: 0.3` under `odace_sfsp` (`0` disables it).
Test one press → one event before using it in automations. If the physical switch
already controls this receiver, do not also automate the same event to toggle
that receiver: it could toggle twice.

These button broadcasts are not authenticated by this integration. UID matching
is filtering, not authentication; do not use these events for security-sensitive
actions.

## Development and capture tools

Run the protocol tests locally:

```sh
python3 -m unittest discover -s tests -v
```

Optional native macOS tools, not needed for HA installation:

- `swift scan.swift 120`: receive-only Odace switch capture as JSON.
- `swift discover.swift 30`: nearby BLE advertisement inventory.
- `swift inspect.swift MACOS_DEVICE_UUID [MACOS_DEVICE_UUID ...]`: inspect services
  and read standard Device Information values on explicitly selected receivers.
  Obtain their local identifiers using `discover.swift` first.
- `swift control.swift MACOS_DEVICE_UUID on|off`: send a real command to a
  selected receiver; this is **not** a receive-only tool.

macOS device UUIDs are local CoreBluetooth identifiers, not Bluetooth addresses;
do not put them in HA's `address` setting.

### Capture privacy

The scanners and inspection tools can print device names, serial numbers,
Bluetooth addresses/local UUIDs, timestamps, and nearby-device advertisements.
Keep raw output private and review/redact it before sharing. `.gitignore`
excludes common capture formats, local HA configuration, credentials, and
generated files, but cannot protect output saved under arbitrary filenames or
files already committed to Git. Test packets use synthetic device values or the
public regression fixture from the PR linked below, not private captures.

Switch packet layout was checked against
[Theengs decoder PR #707](https://github.com/theengs/decoder/pull/707), but this
project does not use Theengs code or libraries. The receiver characteristic was
identified using
[Schneider/Clipsal BLE notes](https://gist.github.com/samthor/42f41372dfeb942b0e419e238d72f752)
and verified with the actual receiver.
