"""l2ping-based sweep over the unknown UAP octet.

Probes run strictly serially, one l2ping at a time -- on purpose, not as
a simplification. A btmon capture against this exact adapter shows
Num_HCI_Command_Packets ("ncmd 1") on every Create Connection command,
meaning the controller only ever grants the host a single outstanding
page-attempt credit. Underneath that, the Link Controller has one
baseband and one RF front end, so it can only occupy the page state for
one target's frequency-hop sequence at a time regardless. Threading
around this bought zero real throughput and only added lock contention
and process bookkeeping, so it's gone. --pageto is the one knob that
actually changes total scan time.

No external timeout on the l2ping probe itself. Each address blocks
until l2ping exits on its own, bounded by the controller's own page
timeout (--pageto) -- that's the one place this should be bounded.
Ctrl-C still works if you need to bail out by hand.
"""
import shutil
import subprocess

from .constants import PAGETO_RE


def get_pageto(hcidev):
    if shutil.which("hciconfig") is None:
        return None
    out = subprocess.run(["hciconfig", hcidev, "pageto"], capture_output=True, text=True)
    m = PAGETO_RE.search(out.stdout)
    return int(m.group(1)) if m else None


def set_pageto(hcidev, slots):
    if shutil.which("hciconfig") is None:
        return False
    subprocess.run(["sudo", "hciconfig", hcidev, "pageto", str(slots)], capture_output=True)
    return True


def probe_one(addr, label=None):
    """Run a single l2ping probe against addr, blocking until it exits on
    its own. Returns 'FOUND' | 'no' | 'error'."""
    try:
        proc = subprocess.run(["sudo", "l2ping", "-c", "1", addr], capture_output=True, text=True)
        status = "FOUND" if proc.returncode == 0 else "no"
        stdout = proc.stdout
    except Exception:
        stdout, status = "", "error"

    tag = f"[{label}] " if label else ""
    print(f"{tag}Trying {addr} ... {status}")
    if status == "FOUND":
        print(stdout.strip())

    return status
