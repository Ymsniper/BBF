# bbf --- Bluetooth BD_ADDR UAP brute-forcer

Brute-forces one unknown octet (the UAP) of a target's Bluetooth
`BD_ADDR` by `l2ping`-ing every possible value, given a known LAP.
Useful for locating a non-discoverable device when part of the address
is already known (from a prior scan, OUI lookup, sniffed traffic, etc).

If no LAP is given on the command line, `bbf` instead drives an
interactive `ubertooth-rx` survey to find candidate addresses over the
air, then lets you pick one to feed into the sweep.

The UAP space is only 256 values, so a full sweep is a couple hundred
serial l2ping calls, 5 minutes worst-case at the default pageto,
often faster since most candidates fail well before the timeout.

> **Scope.** A `BD_ADDR` is `NAP(2 bytes):UAP(1 byte):LAP(3 bytes)`.
> `ubertooth`'s survey always resolves the LAP (that's what identifies
> the piconet from the channel access code) and often resolves the UAP
> too (via CRC-based recovery), but never the NAP — `bbf` assumes the
> NAP (`--prefix`, default `00:00`) and never brute-forces it.
>
> **Why the NAP always shows as `??:??`.** This isn't a gap in
> `ubertooth-rx` or a limitation of this tool — the NAP is structurally
> unrecoverable from over-the-air traffic for *any* sniffer. The
> physical link (the frequency-hopping sequence and the channel access
> code used to page a device and stay synced to it) is derived only
> from the LAP and UAP. The NAP is never transmitted as part of that
> derivation; it only exists for the OUI/manufacturer-lookup portion of
> the address. That's precisely why `bbf` can just assume it via
> `--prefix` instead of sweeping it: the baseband layer doesn't consult
> the NAP to complete a connection, so a wrong assumed NAP doesn't
> prevent `l2ping` from reaching the device once the UAP is correct.

## Legal / ethical use

Only run this against devices you own or are explicitly authorized to
test (e.g. as part of an engagement you have written permission for).
Brute-forcing a device's address defeats Bluetooth's non-discoverable
mode, which some people rely on for privacy. Locating or fingerprinting
someone else's device without consent may be illegal in your
jurisdiction and is not the intended use of this tool.

most Bluetooth devices are paired and set to non-discoverable, since general discovery scans are what most people/OSes turn off after initial setup, but non-discoverable only blocks scanning, not connections. L2CAP is connection-oriented and has no discovery mechanism of its own; l2ping/l2flood both call connect() directly and need only the LAP+UAP (NAP not needed, exact full BD_ADDR not needed) which what bbf + ubertooth does Therefore bbf makes flood tools more dangerous against real targets.

## Requirements

- Linux with BlueZ (`l2ping`, `hciconfig`) — `sudo apt install bluez`
- `sudo` privileges (both `l2ping` and `hciconfig pageto` need root)
- A Bluetooth adapter, brought up (`hciconfig hci0 up`)
- Optional, only for the survey front-end: an
  [Ubertooth One](https://github.com/greatscottgadgets/ubertooth) and
  `ubertooth-rx` on `PATH` — `sudo apt install ubertooth`

## Install

```bash
git clone https://github.com/Ymsniper/BBF
cd bbf
pip install .
# (pip install . --break-system-packages) if needed
```

This installs a `bbf` command. For local development, install in
editable mode with the test dependencies:

```bash
pip install -e ".[dev]"
```

## Usage

```
bbf [known_octets] [--prefix XX:XX] [--hcidev hci0]
    [--pageto SLOTS] [--no-pageto-override] [--no-retry]
    [--retries N] [--only BYTES] [--scan-time SECONDS]
```

| Option | Default | Meaning |
|---|---|---|
| `known_octets` | *(none)* | The 3 known trailing octets (LAP), e.g. `1E:B7:E4`. If omitted, runs the interactive `ubertooth-rx` survey first. |
| `--prefix` | `00:00` | The 2 known leading octets (NAP). |
| `--hcidev` | `hci0` | HCI adapter to tune. |
| `--pageto` | `1600` | Controller page timeout in slots (1 slot = 0.625 ms) used for the duration of the sweep, so a dead address doesn't tie up the controller for long. Restored before the recheck pass. |
| `--no-pageto-override` | off | Leave the adapter's page timeout untouched. |
| `--no-retry` | off | Skip the serial recheck pass entirely. |
| `--retries` | `2` | Extra attempts per address during the recheck pass (so 3 total attempts by default). |
| `--only` | *(none)* | Comma-separated hex byte(s) to test directly instead of sweeping `00..ff`, e.g. `5c` or `04,5c,a1`. |
| `--scan-time` | *(prompted, 30s)* | `ubertooth-rx -t` duration for the interactive survey. Only used when `known_octets` is omitted. |

### Examples

Sweep all 256 possible UAP values against a known LAP:

```bash
bbf 1E:B7:E4
# probes 00:00:XX:1E:B7:E4 for XX in 00..FF
```

Test one specific candidate byte directly, skipping the sweep:

```bash
bbf 1E:B7:E4 --only 5c
# tests only 00:00:5c:1E:B7:E4
```

No LAP known yet — run an interactive `ubertooth-rx` survey, pick a
target from the results, then sweep it:

```bash
bbf
```

## How it works

### The survey (when `known_octets` is omitted)

`bbf` runs `ubertooth-rx -z -t <seconds>`, streaming its output live
and parsing the "Survey Results" section at the end. Each line is one
of:

```
??:??:BE:B4:F1:3F   UAP resolved (BE). Nothing left to sweep — this is
                     already a complete candidate modulo the assumed
                     NAP. Listed as "ready to use".
??:??:??:C5:9D:87    UAP unresolved (extra ??). LAP (C5:9D:87) is
                     offered as a numbered sweep target.
```

### The sweep

Probes run strictly serially, one `l2ping` at a time, on purpose, not
as a simplification. A `btmon` capture against a typical adapter shows
`Num_HCI_Command_Packets` (`ncmd 1`) on every Create Connection command,
meaning the controller only ever grants the host a single outstanding
page-attempt credit. Underneath that, the Link Controller has one
baseband and one RF front end, so it can only occupy the page state for
one target's frequency-hop sequence at a time regardless. `--pageto` is
the one knob that actually changes total scan time.

There's no external timeout on the `l2ping` probe itself — each address
blocks until `l2ping` exits on its own, bounded by the controller's own
page timeout (`--pageto`). Ctrl-C still works if you need to bail out
by hand.

After the first pass, any address that came back "no" gets a serial
**recheck pass**: the original (larger) page timeout is restored, and
each address gets up to `--retries` extra attempts, since a Bluetooth
device only listens for pages during its own page-scan window — a
single miss, even against the exact right address, can just mean the
attempt didn't land inside that window.

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT — see [LICENSE](LICENSE).
