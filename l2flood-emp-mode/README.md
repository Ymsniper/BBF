# l2flood

[![builds.sr.ht status](https://builds.sr.ht/~kovmir/l2flood/commits/master/.build.yml.svg)](https://builds.sr.ht/~kovmir/l2flood/commits/master/.build.yml?)

Flood a given bluetooth device with ping requests in order to force it to
disconnect.

# INSTALL

Satisfy the [dependencies](#dependencies) first, and then:

```bash
git clone https://git.sr.ht/~kovmir/l2flood
cd l2flood
make
sudo make install
```

# USAGE

Suppose there is a loud bluetooth speaker in public, and suppose
`94:3a:2c:e1:2b:07` is its address. You can shut it off like that:

```bash
l2flood 94:3a:2c:e1:2b:07 # Flood with up to 4 threads, depending on how many CPU cores are available.
l2flood -t 5 94:3a:2c:e1:2b:07 # Flood with 5 threads.
```

A weak speaker CPU or Bluetooth interface will not be able to process that many
ping requests, and receive/decode music simultaneously, so it will
disconnect.

*Your bluetooth card is your bottleneck: Even if you have a multi-core
multi-gigahertz CPU, it makes little to no sense to spawn as much as 100
threads, because your bluetooth card is unlikely to be fast enough to process
all the requests as quick as you submit them.*

# DEPENDENCIES

* [Bluez][3]
  * On Debian/Ubuntu/Kali `sudo apt install -y libbluetooth-dev`.

# SUPPORTED OPERATING SYSTEMS

* Linux

# CREDITS

[@Ymsniper](https://github.com/Ymsniper) refactored the entire flood algorithm.

# FIELD TEST RESULTS

Tested against a **K07 Bluetooth speaker** (`B3:C0:10:2D:B6:78`) from a
Kali Linux i686 system with two HCI adapters (hci0, hci1).

## What actually works

| Scenario | Result |
|---|---|
| Phone **disconnected**, `l2flood <addr>` | l2flood establishes ACL link and floods. Phone cannot reconnect until l2flood loses the connection (reset-by-peer). |
| Phone **disconnected**, `l2flood -R <addr>` (EMP mode) | Sustained DOS. When the device resets the connection, l2flood automatically reconnects and resumes flooding. Phone remains locked out indefinitely. |
| Phone **connected**, `l2flood <addr>` | Fails. `connect()` returns "Host is down." l2flood cannot displace an existing ACL link. |
| Phone **connected**, `l2flood -R <addr>` | Fails silently. Tight retry loop, but every `connect()` attempt is rejected. |

## Key observations

- **Recovery after EMP mode does not require a power cycle.** After
  sustained `-R` flooding, the phone was able to reconnect to the K07
  once l2flood was stopped, without resetting either the speaker or the
  phone.

- **L2CAP echo requests go unanswered.** `l2ping` successfully
  establishes an ACL connection to the K07 but receives no echo
  response. l2flood still disrupts the device despite this, because the
  disruption mechanism is connection-level, not ping-level.

- **The device does not need to be discoverable.** Non-discoverable mode
  only suppresses inquiry scan responses. `l2ping` and `l2flood` call
  `connect()` directly, which uses page scan, a separate mechanism that
  most devices leave enabled at all times.

## Comparison to upstream claims

The original l2flood README states:

> *"A weak speaker CPU or Bluetooth interface will not be able to
> process that many ping requests, and receive/decode music
> simultaneously, so it will disconnect."*

This description is **inaccurate**. The actual disruption mechanism is
**ACL link preemption**, not CPU/radio overload:

1. Classic Bluetooth allows only **one ACL link per remote BD_ADDR**.
   When l2flood holds the ACL link, the phone's connection request is
   rejected at the baseband layer before any L2CAP traffic is involved.

2. l2flood **cannot** force an already-connected device to disconnect.
   If the phone already holds the ACL link, l2flood's `connect()` fails
   with `EHOSTDOWN`. The speaker's CPU load is irrelevant.

3. The flood does not need to overwhelm anything. A single successful
   `connect()` is sufficient to block the phone. The L2CAP ping flood
   that follows simply keeps the connection alive and may contribute to
   the persistent state corruption observed after EMP mode.

The practical implication: l2flood is a **reconnection denial** tool,
not a **disconnection** tool. It blocks new connections but cannot break
existing ones. To disrupt an active audio stream, the attacker must
wait for or cause a natural disconnection first (e.g., move out of
range, wait for a timeout, or rely on the user pausing playback).

## i686 build note

On 32-bit (i686) Kali, PIE executables exhibit stack corruption in
`main()` (`argc` receives a garbage stack address). The Makefile builds
with `-no-pie -fno-pie` to avoid this. If you see l2flood segfault
immediately on launch with no arguments, this is the likely cause.

# FAQ

**Q: Does it work in [termux][2]?**

A: No, [Bluez][3] libraries are not available in termux.

**Q: Does it work on Steam Deck?**

A: Yes.

**Q: How to increase flood efficiency?**

A: Get a second bluetooth card, and flood using both of them.

```bash
BT_ADDR='00:00:00:00:00:00' # Set the target address.
l2flood -i hci0 $BT_ADDR &
l2flood -i hci1 $BT_ADDR
```

**Q: How to fix `Can't create socket: Operation not permitted`?**

A: Re-run as `root` user.

[2]: https://github.com/termux/termux-app
[3]: https://www.bluez.org/
